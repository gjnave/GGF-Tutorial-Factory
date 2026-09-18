# Generated application drivers

## Architectural decision

The original generalized path coupled every unfamiliar desktop application to `WindowsUIAAdapter`. Source analysis and Qwen planning generalized successfully, but application control did not: a complex Qt application can expose valid controls and still lose a reliable external UI Automation connection during rehearsal.

Tutorial Factory now treats application onboarding as compilation:

1. deterministic discovery identifies the framework, launcher, controls, callbacks, outputs, and version evidence;
2. Qwen selects an application-specific automation strategy and capability vocabulary;
3. a second bounded retrieval sends only source relevant to those capabilities;
4. Qwen generates a persistent project-local driver;
5. the factory rejects unsafe imports/calls before writing the driver;
6. launch, state, and capture are validated incrementally;
7. bounded exact-replacement repair is available for a failed generated driver;
8. only a validated driver may replace the existing adapter in `app.yaml`;
9. future tutorial runs load the saved driver deterministically without repeating source discovery.

The existing UIA adapter remains a fallback. GrizzlyMax retains its proven dedicated adapter. HeartMuLa and other existing profiles are not converted automatically.

## Driver contract

Each project driver lives under `projects/<project>/driver.py`, defines `create_driver(profile, run_root)`, reports structured capabilities, and implements semantic operations. Tutorial YAML may use the common `operation` action to invoke those capabilities.

For source-available Qt applications, the preferred strategy is the bounded localhost Qt bridge. The generated host runs with the application's own Python environment, invokes source-backed Qt callbacks in the real process, exposes only the generated capability methods, returns JSON-safe state, and captures the real Qt window without UIA.

Generated code may not delete files, run shells/subprocesses, evaluate arbitrary code, or modify the target repository. The bridge binds only to `127.0.0.1` and uses a per-run random token. Driver generation and repair requests are retained under the project's `llm/driver-decisions` directory.

## Fail-closed behavior

The profile is switched to `project-driver` only after launch and native capture both pass. If generation, AST checks, launch, capture, or repair fails, the previous adapter profile is restored. The unverified driver and failure report remain available for audit and repair.

## VisoMaster status

Local Qwen selected `qt_inprocess_bridge` and generated a persistent VisoMaster driver with semantic likeness-transfer capabilities. AST safety passed after allowing diagnostic `traceback` and target-runtime `cv2` imports. Launch validation found generated startup/dispatch defects; the bounded repair could not run because the local Qwen endpoint stopped accepting connections. Therefore the VisoMaster profile remains on the prior `qt-uia` adapter and the generated driver is explicitly unverified.
