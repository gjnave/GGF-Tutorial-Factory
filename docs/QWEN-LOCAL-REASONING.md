# Local Qwen reasoning boundary

Tutorial Factory uses `LLMProvider` as a reasoning-only interface. The current implementation is `QwenLocalProvider`, connected to the installed llama.cpp OpenAI-compatible API.

Verified live server on 2026-09-08:

- Process: `llama-server.exe`
- Endpoint: `http://127.0.0.1:28084/v1`
- Model alias: `Qwen3.8-27B-UD-Q4_K_M`
- Loaded model: Qwen3.8 27B UD-Q4_K_M GGUF
- Command-line context: 240,000 tokens
- Effective `/v1/models` context: 240,128 tokens
- Trained context reported by server: 262,144 tokens
- OpenAI-compatible chat completions: verified
- Function/tool calling: verified with parsed OpenAI-style `tool_calls`
- Required-function structured decisions: used by Tutorial Factory
- Native `response_format: json_schema`: not used; the current server returns HTTP 400 because the grammar rejects the chat template's initial `<think>` token

Qwen may understand source, infer workflows, select a lesson and grounded controls, draft narration, and propose bounded repairs. It cannot execute UI actions, wait for results, verify files, create timestamps, record video, render FFmpeg output, or decide deterministic QA pass/fail.

The source retrieval layer sends a compact deterministic analysis, prioritized semantic controls, signal connections, and bounded excerpts around relevant callbacks, output logic, tooltips, and control symbols. It excludes environments, dependencies, models, build output, and the rest of the repository.

Safe repair is allowlisted to selector fields on an existing semantic control. The original profile is copied to the project's history folder before an accepted repair is written. The factory retries rehearsal at most once. It does not accept commands, arbitrary patches, output reuse, safety bypasses, launch changes, or application execution from Qwen.

Operational checks:

```bat
run-factory.bat llm-status
run-factory.bat
```

Choose `2. Guided Qt tutorial - new application`. When Qwen is available, the wizard reports the detected model, context, endpoint, and structured-output strategy. When it is unavailable, deterministic fallback remains active.
