---
name: verify-shared-dev-server
description: During /verify, parallel design-critic agents share ONE Turbopack dev server — another agent's mid-edit file 500s every route, including yours.
metadata:
  type: project
---

During `/verify` state-3a, design-critic is spawned in parallel across pages
but all instances share a single Turbopack dev server (`base_url` is handed to
you; you must not start or kill it). Turbopack fails the whole compilation
graph on any parse error, so while another page's critic is mid-edit, **your**
route returns HTTP 500 with a `__NEXT_DATA__` error naming *their* file.

**Why:** observed in run `verify-2026-08-10T05:35:29Z` reviewing `/login` —
the server was held at 500 for ~20 minutes first by
`src/app/audit-file/signed-notices.tsx`, then by
`src/app/staff/roster-import-card.tsx`, both out of boundary.

**How to apply:**
- A 500 is not automatically your bug. Read the error before reacting:
  `curl -s <base_url><route> | python3 -c "import sys,json,re; h=sys.stdin.read(); m=re.search(r'__NEXT_DATA__\" type=\"application/json\">(.*?)</script>', h, re.S); print(json.loads(m.group(1))['err']['message'][:600])"`
- Prove your own boundary files parse independently of the server:
  `./node_modules/@esbuild/win32-x64/esbuild.exe --loader:.tsx=tsx --jsx=automatic <file> --outfile=<tmp>` (exit 0 = clean).
- Then poll for 200 before screenshotting, and screenshot immediately — the
  window closes fast.
- Record the blocking file under `shared_issues` + `unresolved_shared`; do not
  fix it (out of boundary).

Related: [[build-fails-offline-google-fonts]]
