---
assumes: []
packages:
  runtime: []
  dev: []
files: []
env:
  server: []
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: []
---

# No Surface

Skip all surface-related steps.

- Skip design decisions for surface (`frontend-design` still runs for
  web-app product UI)
- Skip surface generation in bootstrap
- Skip surface deployment in deploy
- `visit_landing` event is not wired — funnel starts at `activate`
- `/distribute` stops with: "No surface configured. Ad campaigns require a
  surface URL. Add `stack.surface: co-located` or `detached` to experiment.yaml,
  or distribute manually."
