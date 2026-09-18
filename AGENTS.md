# Instructions for coding agents

Before creating or repairing any tutorial that uses Darla, read
`factory/presenter/providers/DARLA_LTX25_WORKFLOW.md` completely and follow it.

The canonical Darla path is native LTX 2.5 audio-to-video conditioning. Never
use post-generation voice replacement, `atempo`, Wav2Lip, LivePortrait, or the
legacy generated-voice/post-mux providers for Darla.

For a new app, use `generate-darla-a2v.bat` with its tutorial YAML and run
`--only 1` as the proof before generating all segments.

GrizzlyMax reference assets and retained runs are documented in
`docs/GRIZZLYMAX-DARLA-HANDOFF.md`. Do not delete retained source, provenance,
presenter, final-render, or MobileOffice files.
