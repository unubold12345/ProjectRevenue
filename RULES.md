# Rules for future sessions (opencode)

## Context discipline

- After each finished task: update `START.md` (current state, commands, gotchas), add a new entry to `VERSION.md`, then compress the closed range with a short summary (decisions, paths, commands only).
- Never compress the active task. Do not paste full file contents into summaries; reference `path:line`.
- A fresh session resumes from `START.md`. `VERSION.md` is the implementation changelog.
- The backend is not in this repo. `/api/revenue` and the admin finance UI live in `C:\Users\PC\Desktop\Codes\LawTest`; their versions are tracked there.

## Versioning (`VERSION.md`)

- Every completed implementation gets a new version entry in `VERSION.md`. Add the newest entry at the top; never renumber, rewrite or delete old entries.
- Version IDs are `vYYYY.MM.DD.N`, where `N` is the next unused sequence for that date in the file. They are documentation versions, independent of any app/package version.
- Each entry records date, status (`PUSHED <sha>`, `LOCAL`, `UNCOMMITTED`, `MIXED`), implementation scope/files, verification, and the product version after the change (or "no product-version change").
- `VERSION.md` has `## Product maturity` for the current product version and `## Retrospective product-version judgment` for how earlier batches were assessed. Update those judgments when a batch materially changes product completeness.
- Product version bump policy: a big new implementation increases the product version by 0.1 (for example 0.8.0 → 0.9.0); fixes and small additions increase it by 0.01 (0.9.0 → 0.9.1, one patch step). The AI agent doing the work judges the size by user-visible scope and product completeness, not line count, and prefers the smaller bump when unsure. Record the resulting product version in the entry and in `## Product maturity`; the date-based implementation ID never changes because of this.
- Update the `START.md` push-status line in the same task so the two files do not disagree.

## Working rules

- Python 3.14 standard library only (Tkinter). Do not add third-party dependencies without explicit user approval.
- Verify changes with `python -m py_compile revenue_app.pyw revenue_client.py neon_billing.py vercel_billing.py` and `python revenue_app.pyw --check` when the API/config path is affected. Run a GUI smoke check for visible UI changes.
- Never commit or push without explicit user approval. Never stage `config.json`, `.env*`, `__pycache__/`, `*.pyc`, logs or OS junk.
- `config.json` contains live secrets (Lexlab API key, Neon key, Vercel token). Never print it, paste it into code/logs, or commit it. Use the documented environment overrides when testing.
- Never write source files through PowerShell `Set-Content`/`Get-Content`: Cyrillic/UTF-8 gets corrupted. Use the editing tools and keep UTF-8 without BOM.
- Treat provider figures as estimates unless they come from a paid invoice. Label Neon/Vercel estimates clearly and do not invent billing data.
- Keep the launcher shortcut working when files move: target `C:\Python314\pythonw.exe` with the absolute `revenue_app.pyw` path, working directory this repo, and `icon.ico`.
- The dashboard is read-only toward LawTest. Do not add write endpoints or send provider keys to Lexlab servers; Neon/Vercel calls go directly from the desktop app.
- Ask the user when a product decision or destructive change is ambiguous; do not guess.
