# Project Revenue — implementation versions

Repo: `C:\Users\PC\Desktop\Codes\ProjectRevenue` · no package manager/package version (Python 3.14 stdlib Tkinter application)

Append-only implementation changelog for the desktop dashboard. Version IDs are date-based implementation versions. Newest entries are at the top.

Status labels: `PUSHED <sha>`, `LOCAL`, `UNCOMMITTED`, `MIXED`. Every completed implementation gets a new entry here and a current-state update in `START.md`.

## Product maturity

- **Product version: 0.8.0 — internal beta** (assessed 2026-10-23). The dashboard is a capable internal tool, but not 1.0 until `/api/revenue` is deployed, an installer/update path exists, automated regression tests cover the billing math, and release QA passes. Provider figures remain estimates unless backed by paid invoices.

## Retrospective product-version judgment

The date-based IDs below remain the implementation record. This table is a retrospective judgment of how complete the desktop dashboard was after each batch; it is not a claim that these were tagged releases. The current product version is **0.8.0**.

| Implementation | Effective product version | Judgment |
| --- | --- | --- |
| v2026.10.23.1 | 0.2.0 | Dashboard prototype: one project, four KPIs and a revenue chart. |
| v2026.10.23.2 | 0.3.0 | Runnable internal tool with launcher and project config. |
| v2026.10.23.3 | 0.4.0 | Neon cost center added. |
| v2026.10.23.4 | 0.5.0 | Vercel cost center added; multi-provider dashboard. |
| v2026.10.23.5 | 0.6.0 | Credit and paid-invoice reconciliation. |
| v2026.10.23.6 | 0.7.0 | Billing-accuracy pass for Vercel credits and domains. |
| v2026.10.23.7 | 0.8.0 | Versioning and internal-beta readiness documentation. |

## Versions (newest first)

### v2026.10.23.9 — Product version bump policy — PUSHED `7757f85`

**Date:** 2026-10-23 · **Product version after:** 0.8.0 (unchanged)

- Documented the bump policy in `RULES.md`: a big implementation increases the product version by 0.1; fixes and small additions increase it by 0.01 (one patch step). The AI agent judges scope and prefers the smaller bump when unsure.
- Current product maturity remains **0.8.0** until the next product-changing batch.
- Documentation only; no compile/`--check`/GUI changes. Pushed in `7757f85`.

### v2026.10.23.8 — Retrospective product-version judgment — PUSHED `7757f85`

**Date:** 2026-10-23 · **Product version after:** 0.8.0 (unchanged)

- Added the retrospective product-version table above, mapping every earlier implementation batch to an effective product version from 0.2.0 through the current internal beta 0.8.0.
- The date-based implementation IDs remain the source of truth; the product versions are judgments of maturity, not historical release tags.
- No compile, `--check` or GUI changes; documentation only. Pushed in `7757f85`.

### v2026.10.23.7 — Versioning documentation — PUSHED `7757f85`

**Date:** 2026-10-23

- Added `VERSION.md` covering all desktop implementations.
- Added `RULES.md` with the versioning rule, secrets policy, backend boundary and verification commands.
- Verification: documentation only; no compile/check needed. Pushed in `7757f85`.

### v2026.10.23.6 — Vercel credit/domain clarification — PUSHED `76a0ff1`

**Date:** 2026-10-23 (pre-split)

- Excluded FOCUS `subscription licenses` rows (Pro subscription/seats/add-ons) from credit usage; real data moved from $3.12 to $0.54, leaving $19.46 of the $20 credit with no overage.
- `/v1/invoices` parsing now reads `lineItems` + `invoiceSource`; Pro plan invoices are split from other purchases, so the $1.99 domain appears as «бусад төлбөр».
- Vercel KPI remains $21.99 total paid with subtitle `Кредит $0.54/$20 · +$1.99`; the 880×900 detail dialog shows the Pro invoice plus other purchases and separate invoice lines.
- Verification: `py_compile` clean; synthetic subscription/invoice split tests passed; live GUI values/screenshots checked. No Next/server changes.

### v2026.10.23.5 — Vercel Pro credit and paid invoices — PUSHED `76a0ff1`

**Date:** 2026-10-23 (pre-split)

- `vercel_billing.py` now reads FOCUS `ChargeCategory=Usage` `EffectiveCost` as the $20 Pro credit usage, falls back to $20 without a Team ID, and reads `/v1/invoices` for paid invoices.
- Only `status=paid` invoices count as cost; otherwise an estimate is shown with a `≈` prefix. Breakdowns use `EffectiveCost`.
- Vercel KPI shows paid total/estimate plus `Кредит $used/$total · %`; the detail dialog gained five tiles (usage, credit used, credit remaining, overage/projection, latest invoice) and invoice/service/project lists.
- Verification: real data usage $3.12/$20, $16.88 left, 3 paid invoices totaling $21.99; `py_compile` clean; 30-check harness and live GUI passed.

### v2026.10.23.4 — Vercel billing — PUSHED `76a0ff1`

**Date:** 2026-10-23 (pre-split)

- New `vercel_billing.py`: Vercel `/v1/billing/charges` FOCUS JSONL, current UTC month-to-date, `BilledCost` and `EffectiveCost`, grouping by service/project/date/category and month-end projection.
- Config v4 with optional `vercel` settings and environment overrides; sixth grey «VERCEL ТӨЛБӨР» KPI, detail dialog and «Vercel тохиргоо».
- Fixed multi-monitor dialog placement: all Toplevels center on the parent/primary screen and clamp inside it.
- Verification: `py_compile` clean; 24-check config/migration/JSONL/grouping/math harness passed; no-key/dummy-token states and six-KPI GUI checked.

### v2026.10.23.3 — Neon billing — PUSHED `76a0ff1`

**Date:** 2026-10-23 (pre-split)

- New `neon_billing.py`: Neon `/api/v2/consumption_history/v2/projects`, current-month daily consumption, project names/spending limit, and estimates for compute, storage, transfer, branches, projected month and USD→MNT conversion (default 3,500).
- Config v3 with optional `neon` settings and environment overrides; fifth cyan «NEON ТӨЛБӨР» KPI, Neon detail dialog and «Neon тохиргоо».
- Keys stay local in gitignored `config.json`; no key is sent to Lexlab servers; figures are labeled estimates because Neon has no invoice-amount API for this flow.
- Verification: `py_compile` clean; synthetic consumption math passed; no-key KPI/dialog/settings, dummy-key 401 and synthetic-data rendering checked.

### v2026.10.23.2 — Launcher and local project setup — PUSHED `76a0ff1`

**Date:** 2026-10-23 (pre-split)

- Recreated `C:\Users\PC\Desktop\Project Revenue.lnk` targeting `C:\Python314\pythonw.exe` with `revenue_app.pyw` (normal window, `icon.ico`), removed the old Lexlab shortcut and refreshed shell icons.
- Window title is now `Project Revenue`; the active project stays in the «Төсөл» menu.
- Seeded local `config.json` (Lexlab, `http://127.0.0.1:3010`, key from `.env`) and kept the local Next server on port 3010 for live data.
- Verification: shortcut target exists; `--check` against local API returned live data. Production `/api/revenue` still 404 until deploy + `REVENUE_API_KEY`.

### v2026.10.23.1 — Desktop dashboard and revenue API — PUSHED `76a0ff1`

**Date:** 2026-10-23 (pre-split)

- New Windows desktop dashboard (`revenue_app.pyw`): 1200x800 dark Tkinter UI, project switcher, add/edit/delete projects with masked keys, four KPI cards, 12-month chart, dynamic cost panel, current-month profit/insights, 60s auto-refresh, F5, Ctrl+, and `--check`.
- `revenue_client.py`: config v2 with `projects` + `activeProjectId`, legacy migration, env overrides `REVENUE_API_URL`/`REVENUE_API_KEY` (legacy `LEXLAB_*` fallback).
- LawTest backend counterpart: `src/lib/finance.ts` and `GET /api/revenue` with timing-safe Bearer / `x-api-key`, `REVENUE_API_KEY`, `no-store`, and only aggregate revenue/cost data. Backend remains local-only in LawTest until deployed.
- `run.bat`, `icon.png`, `icon.ico`; local `config.json` is gitignored.
- Verification: `py_compile` passed; config migration/add/edit/save/env tests passed; LawTest `npx tsc --noEmit` clean and build 53/53; local API returned 1,476,300₮ revenue / 288,000₮ costs / 1,188,300₮ profit / 37 payments; GUI states checked.

## Dependency / backend versions

The desktop app is a client of LawTest. The `/api/revenue` backend and admin finance UI are versioned in `C:\Users\PC\Desktop\Codes\LawTest\VERSION.md` (`v2026.10.23.2`, `LOCAL`). Do not treat the API as deployed until that entry is pushed and `REVENUE_API_KEY` is configured in Vercel.
