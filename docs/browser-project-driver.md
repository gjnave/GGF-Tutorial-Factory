# Reusable browser tutorial driver

Use this pattern when a browser application has meaningful runtime state but does not create a local output file.

## Required project files

- `projects\APP\app.yaml`: source root, browser launch runtime, stable CSS selectors, and `adapter.kind: project-driver`.
- `projects\APP\driver.py`: launches the application's local server and a token-protected browser bridge, exposes semantic operations, captures the page at 1920x1080, and closes only processes it started.
- `projects\APP\browser_bridge.mjs`: operates the real page through the browser automation library already installed with the application.
- `projects\APP\discovery.json`: source-derived framework, controls, data sources, and workflow facts.
- `projects\APP\app_knowledge.json`: user-facing feature knowledge plus exact rebuild commands.
- `projects\APP\driver-manifest.json` and `driver-validation.json`: capabilities and real-run evidence.
- `projects\APP\tutorials\TUTORIAL\tutorial.yaml`: narration, actions, scenes, and acceptance requirements.

Do not modify the target application merely to make it recordable. Keep the adapter and bridge inside Tutorial Factory.

## Semantic operation contract

Each durable operation should:

1. use the application's real public UI or runtime method;
2. wait for the requested state and live data to settle;
3. select current objects dynamically instead of hard-coding ephemeral ids;
4. return a JSON-safe result containing `verified: true` and the real id/count/source used;
5. expose a stable `focus_control` so the renderer can place a thin highlight;
6. throw or return `verified: false` when the requested state was not proved.

For dynamic feeds, choose a currently rendered object. Stable preferred targets such as ISS may be attempted first, with a current rendered object as fallback.

## Stateful acceptance

Browser tutorials may set:

```yaml
verification:
  requires_new_output: false
  required_operations:
    - show_live_data
    - track_live_object
```

The generic factory then requires every listed operation to execute and return `verified: true`. File-output checks remain mandatory by default for applications that create files.

## Darla production sequence

Read `factory\presenter\providers\DARLA_LTX25_WORKFLOW.md` before rendering.

```bat
generate-darla-a2v.bat projects\APP\tutorials\TUTORIAL\tutorial.yaml runs\APP\presenter-proof\presenter\clips --only 1
```

Inspect representative frames and verify the embedded audio against the immutable conditioned WAV. Only after the proof passes:

```bat
generate-darla-a2v.bat projects\APP\tutorials\TUTORIAL\tutorial.yaml runs\APP\presenter-proof\presenter\clips
.venv\Scripts\python.exe -m factory.cli build --project APP --tutorial TUTORIAL --reuse-run runs\APP\presenter-proof
```

The generator resolves relative paths before FireRed or LTX changes working directories. Reused presenter clips retain their `.provenance.json` and `.ltx-a2v.log` sidecars. The finished filename uses the actual presenter name.

## Final checks

- All required semantic operations passed with real result data.
- Contact sheet shows every chapter, readable UI, correct highlights, and no obstructive close-ups.
- Presenter clips contain native LTX audio and matching provenance.
- Final video is H.264, 1920x1080, 30 fps, with AAC 48 kHz stereo audio.
- Copy only after QA passes, then compare byte size and SHA-256.

Godseye is the reference implementation: `projects\godseye`.

