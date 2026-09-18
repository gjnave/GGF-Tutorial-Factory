# GrizzlyMax and Darla canonical handoff

## Finished reference

- Delivered video: `G:\My Drive\MobileOffice\grizzlymax_expanded_reference_and_text_with_darla.mp4`
- Factory final: `runs\2026-09-10_grizzlymax_darla_embedded_a2v_final`
- Corrected 18-clip presenter run: `runs\2026-09-09_grizzlymax_darla_embedded_a2v_presenter`
- Approved UI capture, results, screenshot, and actions: `runs\2026-09-09_130121_grizzlymax_expanded-reference-text-workflows`
- Original 18 correct-Darla audio sources: `runs\2026-09-09_172652_grizzlymax_expanded-reference-text-workflows`
- Final SHA-256: `5F6557F76FB9B68ECD2A45E7AF5243174349CC222D5D2371FD5F8EC6DC1E2539`

These four runs are retained because together they provide source media,
audio provenance, corrected A2V presenter clips, the final render, and QA.

## Future apps

Read `factory\presenter\providers\DARLA_LTX25_WORKFLOW.md` before work. Build a
new app profile/tutorial manifest, then use the reusable root launcher:

`generate-darla-a2v.bat projects\APP\tutorials\getting-started\tutorial.yaml runs\APP\presenter --only 1`

Inspect that native A2V proof before running the same command without
`--only 1`. The provider creates the FireRed Darla narration first, pads only
trailing silence, supplies it directly to LTX, and writes a provenance JSON
beside every MP4. Only after presenter QA should the normal app-specific
renderer combine the real UI capture, generated examples, thin highlights,
and the LTX presenter track.

The GrizzlyMax repair utilities are working references:

- `scripts\generate_darla_ltx_a2v_from_embedded.py`
- `scripts\render_grizzlymax_darla_embedded_a2v.py`
- `scripts\qa_grizzlymax_audio_alignment.py`

Those three are GrizzlyMax repair references. Do not copy their hard-coded
paths into another app. New tutorials should use `generate-darla-a2v.bat` and
the standard `darla` presenter provider.
