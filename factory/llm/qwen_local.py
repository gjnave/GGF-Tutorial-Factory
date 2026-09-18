from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from factory.llm.base import LLMCapabilities, LLMProvider


def _json_type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def validate_schema(value: Any, schema: dict[str, Any], path: str = "$" ) -> None:
    expected = schema.get("type")
    allowed_types = expected if isinstance(expected, list) else [expected] if expected else []
    if allowed_types and not any(_json_type_matches(value, item) for item in allowed_types):
        raise ValueError(f"{path} has the wrong type; expected {allowed_types}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not one of {schema['enum']}")
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value:
                raise ValueError(f"{path}.{key} is required")
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                raise ValueError(f"{path} contains unsupported fields: {sorted(extras)}")
        for key, child in value.items():
            if key in properties:
                validate_schema(child, properties[key], f"{path}.{key}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, child in enumerate(value):
            validate_schema(child, schema["items"], f"{path}[{index}]")


class QwenLocalProvider(LLMProvider):
    def __init__(self, config: dict[str, Any]):
        self.endpoint = str(config.get("endpoint") or "http://127.0.0.1:28084/v1").rstrip("/")
        self.model = str(config.get("model") or "Qwen3.8-27B-UD-Q4_K_M")
        self.temperature = float(config.get("temperature", 0.1))
        self.timeout_seconds = int(config.get("timeout_seconds", 240))
        self.max_output_tokens = int(config.get("max_output_tokens", 6000))
        self.configured_context = config.get("context_limit")
        self._capabilities: LLMCapabilities | None = None

    @property
    def base_url(self) -> str:
        return re.sub(r"/v1$", "", self.endpoint, flags=re.IGNORECASE)

    def _request(self, method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Authorization": "Bearer local-api-key"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Local Qwen HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Local Qwen endpoint unavailable at {url}: {exc}") from exc

    def probe(self) -> LLMCapabilities:
        try:
            health = self._request("GET", f"{self.base_url}/health")
            models = self._request("GET", f"{self.endpoint}/models")
            props = self._request("GET", f"{self.base_url}/props")
            model_rows = models.get("data") or models.get("models") or []
            selected = next((row for row in model_rows if (row.get("id") or row.get("name")) == self.model), None)
            selected = selected or (model_rows[0] if model_rows else {})
            actual_model = selected.get("id") or selected.get("name") or props.get("model_alias") or self.model
            meta = selected.get("meta") or {}
            context_limit = int(meta.get("n_ctx") or (props.get("default_generation_settings") or {}).get("n_ctx") or 0) or None
            caps = props.get("chat_template_caps") or {}
            tool_calling = bool(caps.get("supports_tools") and caps.get("supports_tool_calls"))
            available = health.get("status") == "ok" and bool(model_rows)
            result = LLMCapabilities(
                available=available,
                provider="qwen_local",
                endpoint=self.endpoint,
                model=str(actual_model),
                context_limit=context_limit,
                openai_compatible=True,
                tool_calling=tool_calling,
                structured_json="required_function_call" if tool_calling else "prompt_and_validate",
                detail="llama.cpp OpenAI-compatible chat completions",
            )
        except Exception as exc:
            result = LLMCapabilities(
                available=False,
                provider="qwen_local",
                endpoint=self.endpoint,
                model=self.model,
                detail=str(exc),
            )
        self._capabilities = result
        return result

    @staticmethod
    def _audit_path(audit_dir: Path, task: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        path = audit_dir / f"{stamp}_{re.sub(r'[^a-z0-9]+', '-', task.lower()).strip('-')}"
        path.mkdir(parents=True, exist_ok=False)
        return path

    def complete_json(
        self,
        *,
        task: str,
        system: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
        audit_dir: Path,
    ) -> dict[str, Any]:
        capabilities = self._capabilities or self.probe()
        if not capabilities.available:
            raise RuntimeError(capabilities.detail or "Local Qwen is unavailable")
        function_name = "submit_" + re.sub(r"[^a-z0-9_]+", "_", task.lower()).strip("_")
        request_payload = {
            "model": capabilities.model or self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "tools": [{
                "type": "function",
                "function": {
                    "name": function_name,
                    "description": "Submit the schema-constrained Tutorial Factory reasoning result.",
                    "parameters": schema,
                },
            }],
            "tool_choice": "required",
        }
        audit_path = self._audit_path(audit_dir, task)
        (audit_path / "capabilities.json").write_text(
            json.dumps(capabilities.to_dict(), indent=2), encoding="utf-8"
        )
        (audit_path / "request.json").write_text(
            json.dumps(request_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        response = self._request("POST", f"{self.endpoint}/chat/completions", request_payload)
        (audit_path / "raw-response.json").write_text(
            json.dumps(response, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        message = ((response.get("choices") or [{}])[0].get("message") or {})
        calls = message.get("tool_calls") or []
        if not calls:
            raise RuntimeError(f"Local Qwen did not return the required {function_name} function call")
        call = next((item for item in calls if (item.get("function") or {}).get("name") == function_name), calls[0])
        arguments = (call.get("function") or {}).get("arguments")
        decision = json.loads(arguments) if isinstance(arguments, str) else arguments
        if not isinstance(decision, dict):
            raise ValueError("Local Qwen returned non-object function arguments")
        validate_schema(decision, schema)
        (audit_path / "decision.json").write_text(
            json.dumps(decision, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return decision
