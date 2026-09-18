# Tutorial Factory application profile v1

An application is understood once and reused many times. Application behavior belongs in `app.yaml`; tutorial behavior belongs in `tutorial.yaml`. Do not write a new Python tutorial for each application.

## Application profile

```yaml
profile_version: 1
application:
  name: Example App
  slug: example-app
  source_root: D:\apps\example
  framework: qt
adapter:
  kind: qt-uia
  semantic_primary: true
  vision_fallback: true
launch:
  command:
    - D:\apps\example\.venv\Scripts\python.exe
    - D:\apps\example\app.py
  cwd: D:\apps\example
  window_title_re: Example\ App
  timeout_seconds: 45
controls:
  ui.prompt:
    control_type: Edit
    found_index: 0
  ui.generate:
    control_type: Button
    title: Generate
outputs:
  - directory: D:\apps\example\outputs
    glob: "*.mp4"
```

Control selectors support `title`, `title_re`, `auto_id`, `control_type`, and `found_index`. Source-generated metadata such as `source_symbol`, `source_file`, `values`, and `initially_enabled` is retained as discovery evidence.

## Tutorial actions

```yaml
schema_version: 1
title: Getting Started
application:
  profile: app.yaml
video:
  width: 1920
  height: 1080
  fps: 30
  production_style: approved-v2
presenter:
  provider: gary
narration:
  segments:
    - chapter: 1. Add a prompt
      text: Enter the subject, action, lighting and camera movement.
actions:
  - action: type
    target: ui.prompt
    value: A dog runs along a beach at sunrise.
    chapter: 1
    offset: 1.0
    closeup: true
  - action: click
    target: ui.generate
    chapter: 1
    offset: 4.0
  - action: wait_for_output
    timeout_seconds: 3600
  - action: show_output
```

Supported actions: `launch`, `click`, `double_click`, `hover`, `type`, `select`, `wait_for`, `open_file`, `capture`, `verify`, `wait_for_output`, `show_output`, and `scroll_to`.

Use `optional: true` only when a control may legitimately be unavailable in the demonstrated state. Rehearsal records skipped optional actions and fails on every required action.
