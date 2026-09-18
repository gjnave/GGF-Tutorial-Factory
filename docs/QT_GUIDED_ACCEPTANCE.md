# Qt guided onboarding acceptance status

## User entry point

Double-click `D:\ggf-tools\GGF-Tutorial-Factory\run-factory.bat` and choose option 2.

## Proven HeartMuLa run

- Project: `heartmula-guided`
- Source-generated profile: yes
- Application-specific tutorial Python: none
- Safe rehearsal: passed
- Real Generate click: passed
- New output: `D:\apps2review\heartmula\heartlib\output\heartmula_20260908_093448.mp3`
- New-output baseline and timestamp verification: passed
- Play action: passed
- Gary presenter: passed
- Approved V2 render and QA: passed
- Final MP4: `D:\ggf-tools\GGF-Tutorial-Factory\runs\2026-09-08_093312_heartmula-guided_getting-started\render\heartmula-guided_getting-started_with_gary.mp4`

## Proven fresh third Qt application

- Application: Get Going Fast Installer (`D:\staging\ggfginstaller`)
- Prior Tutorial Factory profile: none before this acceptance run
- Project: `ggf-installer-acceptance`
- Broken source-local Python detected; wizard requested a working Qt Python executable
- Missing output location detected; wizard requested it
- Source-generated profile and approved human-readable plan: passed
- Live control validation and safe rehearsal: passed
- Real Install click and new manifest verification: passed
- Application-specific tutorial Python: none
- Gary presenter, approved V2 render, acceptance QA, visual QA, and media QA: passed
- Final MP4: `D:\ggf-tools\GGF-Tutorial-Factory\runs\2026-09-08_095946_ggf-installer-acceptance_getting-started\render\ggf-installer-acceptance_getting-started_with_gary.mp4`
- Final SHA-256: `1513A10A4F48B98610F2A571A464A1B3F9E831E6049AFD7316F2A178808AE0A3`

## Preserved production path

Menu option 1 still calls the existing dedicated GrizzlyMax approved V2 builder. The Qt guided work did not replace or alter `factory/core/orchestrator.py` or the GrizzlyMax adapter. GrizzlyMax can be migrated incrementally only after regression proof; its current production path remains the fallback.

## VisoMaster onboarding repair

- Bundled `dependencies` and Python standard-library files are excluded from source analysis.
- The main title is inferred as `VisoMaster - Fusion - 1.0.0`; the version suffix is allowed to vary at runtime.
- `Initial Setup: Execution Provider` is reported as an application-attention step instead of a launch timeout.
- After setup, the adapter reacquires the real VisoMaster main window.
- Ambiguous workflow buttons are presented as a numbered user choice instead of being guessed.
- Incomplete project `visomaster-fusion` is resumable and its generated profile is refreshed with a timestamped history backup.
