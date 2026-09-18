# Canonical Darla presenter workflow

This file is the source of truth for every future Darla tutorial.

## Standard entry point

From the factory root, generate only the first segment and inspect it:

`generate-darla-a2v.bat projects\APP\tutorials\getting-started\tutorial.yaml runs\APP\presenter --only 1`

After the proof passes, run the same command without `--only 1`. The BAT uses
the factory virtual environment and the standard `darla` provider. It is the
default entry point for new apps; the GrizzlyMax embedded-audio script exists
only to preserve the already-approved narration recovered during that repair.

## Required pipeline

1. Create the exact narration audio before video generation. For new words,
   use the approved Darla FireRed reference in
   `assets\presenters\darla\darla_voice_reference_short.wav`. If an approved
   Darla track already exists inside a media file, extract that exact audio
   instead of cloning it again.
2. Treat each narration WAV as immutable. Preserve voice, pitch, speed, words,
   and timing. Mono may be duplicated to stereo. Never use `atempo` or time
   stretching.
3. Compute `num_frames = 8*k+1` by rounding up from audio duration at 24 fps.
   Add trailing silence only so the WAV duration equals `num_frames / 24`.
4. Run `python -m ltx_pipelines.a2vid_two_stage` from
   `D:\apps2review\ltx25\New folder\LTX-2` with the WAV passed through
   `--audio-path` and Darla's image passed through `--image`.
5. Use the local LTX 2.5 split models, distilled LoRA, spatial upsampler,
   `--quantization fp8-cast`, `--offload cpu`, 512x512, 30 steps, and
   `--a2v-guidance-scale 3.0`. Start at 3.0 and increase only after a visual
   proof demonstrates weak speech motion.
6. Keep the LTX-produced MP4 and its embedded audio together. Never replace,
   stretch, or mux different narration onto it afterward.

Standard motion prompt: `Natural presenter motion: Darla sits behind the
stationary Get Going Fast box, facing the camera with accurate speech motion,
natural facial expressions, subtle hand and upper-body movement, locked camera,
realistic studio lighting.`

## Proof gate

Generate segment 1 first. Inspect multiple frames and play/extract its audio.
Confirm new facial/body movement, speech-conditioned mouth motion, the correct
Darla voice, matching audio/video duration, and no post-generation audio mux.
Only then generate the remaining segments.

## Reliability and resume

Windows can intermittently return `Attempted to access the data pointer on an
invalid python storage` or crash `torch_cpu.dll` while streaming model blocks.
Retry only the failed segment in a fresh LTX process; do not regenerate passed
clips. CPU offload is the proven mode. Disk offload reproduced invalid-storage
failures, and no-offload requires more VRAM than the 24 GB RTX 4090 provides.
Every clip must have the automatically generated provenance JSON containing
source path/hash, conditioned audio path/hash, frames, fps, output duration, and
`post_generation_audio_replacement: false`.

## Forbidden legacy paths

Do not use `darla_ltx25_clone_voice.py`, `darla_ltx25.py`, Wav2Lip,
LivePortrait, basic mouth animation, generated LTX speech followed by FireRed
replacement, or any workflow that muxes cloned audio after video generation.

## Final QA

Require all expected native-A2V clips, unique ordered narration, audio/video
duration agreement, representative frame inspection, readable UI, correctly
timed thin highlights/arrows, real output demonstrations, a complete ending,
1920x1080 H.264 video, and AAC audio. Compare the final timeline sections to
their immutable Darla sources with lag-compensated waveform correlation. Copy
to a delivery location only after QA passes, then verify byte size and SHA-256.
