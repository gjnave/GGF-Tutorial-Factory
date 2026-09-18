# GGF Tutorial Factory

Local, source-aware tutorial automation for Windows applications. GrizzlyMax is the reference implementation; new applications are onboarded into persistent YAML profiles and reusable tutorial manifests. Gary is the default presenter, using the supplied local video reference and FireRedTTS3 voice clone. Liz remains available as an alternate presenter.

The factory preserves the rehearsal -> capture -> verify -> narration -> presenter -> render -> QA architecture. The generic path analyzes source, detects the executable UI entry point, creates semantic controls, drives them with Windows UI Automation, records only the real target window, verifies real outputs, removes dead time, adds V2 chapter cards/highlights/arrows, and runs media plus chapter-frame QA.

Local Qwen 3.8 is the optional reasoning layer for unfamiliar applications. It interprets a bounded source/control/callback evidence bundle, recommends the lesson and workflow, proposes schema-constrained actions and narration, and may recommend a bounded selector repair after rehearsal. The deterministic factory remains solely responsible for UI execution, recording, waits, output verification, timestamps, rendering, and QA.

For complex applications, onboarding can now compile a persistent project-specific driver instead of forcing control through generic UIA. The driver exposes verified semantic operations such as `load_target_media`, `process_swap`, or `preview_result`; tutorial manifests invoke them with the common `operation` action. Qt drivers may run a token-protected localhost bridge inside the application's own Qt process, avoiding dependence on an external accessibility tree. See `docs\generated-application-drivers.md`.

Application source and normal Python environments are not modified. Profiles live under `projects`, while tutorial state, generated media, logs, screenshots, presenter assets, and QA are written to unique folders under `runs`.

## Setup

Double-click `setup.bat` once. It creates `.venv` inside Tutorial Factory and installs only the factory's dependencies. Liz rendering uses the already-installed `D:\apps2review\ltx25\New folder\LTX-2\.venv`; GrizzlyMax continues to use its own isolated environment.

## Commands

```bat
run-factory.bat audit
run-factory.bat rehearse
run-factory.bat build --project grizzlymax --tutorial complete-workflow
run-factory.bat build --project grizzlymax --tutorial first-t2va
run-factory.bat onboard --source D:\path\to\app-source --name "My App" --project my-app
run-factory.bat profile --project my-app
run-factory.bat rehearse --project my-app --tutorial getting-started
run-factory.bat build --project my-app --tutorial getting-started
run-factory.bat llm-status
run-factory.bat driver-generate --project my-app --goal "Teach the main successful workflow"
run-factory.bat driver-validate --project my-app
```

## Self-service Qt workflow

Double-click `run-factory.bat` and choose `2. Guided Qt tutorial - new application`.
The guided compiler:

1. accepts a Python Qt/PySide/PyQt source folder;
2. discovers the framework, entrypoint, runtime, window title, controls, signals, likely inputs, run action, and output folders;
3. sends only a compact structured discovery plus relevant source excerpts to the configured local Qwen reasoning provider;
4. has Qwen propose what the app does, a useful lesson, the workflow, example inputs, success condition, action outline, and Gary narration;
5. asks only unresolved user-intent/input/safety questions, then launches the real app and validates the required semantic controls;
6. displays a readable proposed plan with Approve, Edit, and Reject choices;
7. compiles the approved plan into the internal action schema;
8. rehearses while replacing unsafe real actions with hover-only validation; one schema-validated selector repair may be proposed by Qwen and retried safely;
9. runs and records the real workflow, requiring an output absent from the pre-run baseline and created after the run began;
10. pauses frame capture during long output waits, resumes for completion/result demonstration, creates Gary, renders approved V2 visuals, and runs acceptance, visual, and media QA;
11. prints `FINAL_MP4` and `OUTPUT_FOLDER`, then offers `Open Output Folder`.

If Qwen is stopped or disabled, guided onboarding prints the reason and continues through the deterministic Qt flow. Existing approved profiles and tutorials never require Qwen to build.

## Local Qwen reasoning

`config\providers.yaml` configures the provider. The verified local installation is llama.cpp at `http://127.0.0.1:28084/v1`, serving `Qwen3.8-27B-UD-Q4_K_M`. Runtime capability discovery reads `/health`, `/v1/models`, and `/props`; the current server reports a 240,128-token effective context.

The server supports OpenAI-compatible chat completions and function/tool calling. Tutorial Factory uses a required function call plus independent Python schema validation for structured decisions. Native `response_format: json_schema` is not used because the installed llama.cpp/model template currently rejects its grammar at the model's `<think>` prefix.

Every reasoning request, capability record, raw response, validated decision, retrieval bundle, normalized proposal, and repair proposal is retained under `projects\<project>\llm`. That directory is copied into every rehearsal/build run under `runs\...\app\llm` for auditability. The retrieval record includes source-file/character counts and explicitly records that the repository was not sent wholesale.

If a run is interrupted, choose the same source/name/project again. Approved projects resume rehearsal/build. If the previous output folder is not clean, the wizard asks for a new output folder and backs up the prior plan/profile/tutorial before updating them.

For applications that open a first-run setup/provider/workspace dialog, the wizard detects standard semantic dialog buttons without waiting for the full startup timeout, reports the visible dialog, and lists its choices. Select a number or enter the exact button name; pressing Enter alone does not answer the application's dialog. The wizard then reacquires the main Qt window automatically. Heavy Qt applications receive a 120-second startup window when no dialog is blocking launch.

Controls inside hidden Qt tabs are tagged with their owning tab during source discovery. Validation and execution select that tab semantically before locating the control, so controls such as output-folder fields on a Settings tab do not require manual navigation. Read-only output paths are demonstrated and captured rather than overwritten. If signal wiring does not uniquely identify the workflow action, the wizard lists the plausible semantic buttons and asks which workflow to demonstrate; no YAML editing is needed.

The guided milestone intentionally accepts only Python Qt applications. Browser, Gradio, Electron, Google Drive delivery, and a large GUI are deferred.

When discovery cannot infer the runtime, entry point, or title, provide only the missing values:

```bat
run-factory.bat onboard --source D:\path\to\source --name "My App" --project my-app --python D:\path\to\.venv\Scripts\python.exe --entrypoint D:\path\to\app.py --window-title "My App"
```

- `audit` records the current GrizzlyMax Git state, installed tools, and model files.
- `rehearse` proves semantic location, physical mouse movement, clicking, selection, typing, and postcondition checks without starting a model generation.
- `complete-workflow` is the default GrizzlyMax production build. The approved V2 renderer is now standard: separate Speed and Realism LoRA chapters, finished-row double-click, Preview, Open output folder, close focus regions, arrows, presenter repositioning, and the real generated result.
- `first-t2va` retains the original short tutorial.
- `build` writes a finished 1920x1080 tutorial MP4 plus subtitles, transcript, action metadata, screenshots, logs, presenter clips, and QA results.

Every run is created under `runs\<timestamp>_grizzlymax_first-t2va\`. Existing runs are never overwritten.

## Persistent application profiles

`onboard` scans source files and writes:

- `projects\<project>\discovery.json`: evidence for framework, launcher, controls and outputs.
- `projects\<project>\app.yaml`: reusable application adapter profile.
- `projects\<project>\tutorials\getting-started\tutorial.yaml`: profile-driven starter tutorial using the generic action schema.

Supported action names are `launch`, `click`, `double_click`, `hover`, `type`, `select`, `wait_for`, `open_file`, `capture`, `verify`, `wait_for_output`, `show_output`, and `scroll_to`. Actions may be timed with `at`, or positioned inside a narration chapter with `chapter` and `offset`.

Initial adapter targets are PySide/PyQt/Qt, browser/Gradio accessibility trees, Electron accessibility trees, and generic Windows UI Automation. Semantic controls are primary. Vision is reserved for verification and fallback.

The second-app acceptance proof is HeartMuLa, onboarded from `D:\apps2review\heartmula\heartlib`. Its profile and tutorial were generated without a HeartMuLa-specific Python tutorial program.

## Presenters

- `gary`: clones narration locally with FireRedTTS3 using `assets\presenters\gary\gary_voice_reference.wav`, then composes it with the supplied Gary video reference. The supplied still image is retained as `gary_driving_reference.jpg` for future driving-video generation.
- `darla`: uses immutable Darla narration as native LTX 2.5 A2V conditioning; read `factory\presenter\providers\DARLA_LTX25_WORKFLOW.md` before using it.
- `ltx25_liz`: retains the installed LTX 2.5 Liz provider used by the approved GrizzlyMax V2.
- `none`: reserved for non-presenter workflows.

The presenter is selected in each tutorial YAML. Generated narration and presenter clips stay inside that run.

## Current boundaries

- FFmpeg captures the exact maximized GrizzlyMax rectangle because Windows 11's title-based gdigrab intermittently loses Qt windows. This avoids changing the user's OBS profiles. An OBS provider can be added after the MVP is proven.
- GrizzlyMax retains its dedicated semantic bridge because it exposes richer queue/generation state than generic UIA.
- Qt/UIA is the proven generalized adapter. Browser/Gradio and Electron discovery/profile support is present but still requires a separate real-app acceptance run.
- Gary's efficient presenter mode reuses the supplied motion reference with newly cloned narration. A future lip-synchronized driving-video provider can use the retained still image and audio track without changing the app/tutorial architecture.
- YouTube publishing is intentionally out of scope.
