# Rupeezy Defect Tracker

A local-first QA defect management system for fintech testing across **Android, iOS, Web and API** platforms — built to replace Excel-based bug tracking and to scale to thousands of defects over multiple years.

Runs entirely on your machine: SQLite storage, vendored front-end assets (no CDN), no external services.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.9+, Flask 3, SQLAlchemy 2 (typed ORM), Flask-Login, Flask-Migrate (Alembic), Flask-WTF |
| Database | SQLite (default) → PostgreSQL via one env var, no code changes |
| Frontend | Jinja2, Bootstrap 5.3 (vendored), vanilla JS, dark mode |
| Testing | pytest |

## Architecture

Strict layering — each layer only talks to the one below it:

```
Browser / automation client
        │
        ▼
Routes (Blueprints)      thin: parse request, call service, render/JSON
        │
        ▼
Services                 business rules, workflow validation, transactions
        │
        ▼
Repositories             queries only — never commit
        │
        ▼
SQLAlchemy models  ──►   SQLite (dev)  /  PostgreSQL (via DATABASE_URL)
```

Key conventions:

- **JSON envelope** — every API/error response uses `{"success": ..., "data": ..., "error": {"code", "message"}}`, the same shape as Rupeezy backend services, so automation tooling sees one format everywhere.
- **Domain exceptions** (`app/exceptions.py`) — services raise `NotFoundError`, `ConflictError`, `BusinessRuleError`, etc.; global handlers (`app/error_handlers.py`) translate them to flash+redirect (web) or the envelope (API). Routes contain no status-code plumbing.
- **Transactions** — repositories stage changes; only services commit (`BaseService.commit()` rolls back on failure).
- **Portable migrations** — a metadata naming convention plus Alembic batch mode means every migration written against SQLite replays cleanly on PostgreSQL.
- **SQLite hardening** — every connection gets `foreign_keys=ON` (cascades depend on it), WAL journal and a busy timeout, so browsing stays responsive while automation writes.
- **Private uploads** — `uploads/` lives outside `static/` and will be served through an authenticated route, never as a public file.

## Data model

```
User (Admin / QA / Developer)          Module ── Feature
  │ reports / is assigned                 │ RESTRICT
  ▼                                       ▼
Epic ── Story ──┬── Defect ──┬── Comment (threaded, CASCADE)
        Sprint ─┘   BUG-001  ├── Attachment (CASCADE)
                             ├── ActivityLog (audit, CASCADE)
                             └── Labels / Tags (M2M, CASCADE)
```

- **Business keys** (`BUG-001`, `STORY-125`, `EPIC-007`) come from a `key_counters` table — never from primary keys — so numbers are never reused after deletion (`app/services/keys.py`).
- **Vocabulary enums** (status, severity, priority, platform, environment, resolution, …) are stored as human-readable VARCHAR values (`app/models/enums.py`); adding a value is a code change, not a migration.
- **Delete rules live in the database**: modules and reporters with defects are RESTRICT-protected; sprint/story/assignee links SET NULL; comments, attachments, activity and label/tag links CASCADE. SQLite enforces all of it because every connection runs `PRAGMA foreign_keys=ON`.
- **Audit trail**: `activity_log` records who/when/what (old → new value) per event; defect deletion itself survives as a row with `entity_type='defect', defect_id=NULL`.
- **All timestamps are naive UTC** (`app/utils/datetime.py`); render local time in templates only.

Database workflow:

```bash
.venv/bin/flask db upgrade     # apply migrations
.venv/bin/flask seed           # demo data (idempotent; all accounts: Password@123)
.venv/bin/flask db migrate -m "..."   # autogenerate after model changes
.venv/bin/flask db check       # verify models match the migration head
```

> ⚠️ Seeded accounts (`admin`, `priya.qa`, …) share the demo password `Password@123` — change them before using the tracker with real data.

## Authentication & roles

- **Secure by default** — a global login guard protects every route; views opt *out* with `@public_route` (only the login page and `/health`). New blueprints are protected the moment they're registered.
- **Sign in with username or email** (case-insensitive), optional 30-day "remember me"; last sign-in is recorded.
- **Roles**: Admin / QA / Developer. `@role_required(...)` / `@admin_required` guard views; `/api/*` paths get a JSON 401 envelope instead of a redirect.
- **Admin user management** (`/users`): search + role/status filters, create/edit, password reset, activate/deactivate — every change lands in the audit trail as per-field old→new rows.
- **Usernames are renameable** and should resemble the full name: the create form auto-derives the username as you type the name ("Krishna Pal" → `krishna.pal`), the edit form has a "Match name" button, and renames are uniqueness-checked, audit-logged and flashed with the old → new sign-in name.
- **Invariants** enforced in the service layer: you cannot deactivate yourself or drop your own admin role, and the system never ends up without an active admin.

## Dashboard

`/dashboard` (also the home page) — stat tiles (open / closed / critical / high-severity), quick-filter chips, and eight Chart.js charts: 30-day bug trend (reported vs resolved), open vs completed, severity & priority distributions, open-bug aging buckets, developer workload stacked by severity, open bugs by module, and per-sprint completion. Plus a live sprint-progress card (date-matched current sprint), a humanized recent-activity feed, and today's counts.

Implementation notes:

- All numbers come from grouped aggregate queries in `app/repositories/dashboard.py` — no N+1s; windowed fetches (trend/aging) are bucketed in Python for SQLite/PostgreSQL portability.
- Chart.js is vendored (`static/vendor/chartjs/`); charts rebuild automatically when the theme toggles so axes/legends follow dark mode.
- Quick filters and tile links target the Phase 5 defect list (`status`, `severity`, `priority`, `state=open`, `regression`, `assignee` params) and render as disabled chips until that endpoint exists — they activate automatically via the `endpoint_exists()` template global.
- "Today" uses *local* day boundaries converted to UTC for querying (`local_day_start_utc`).

## Defect module

- **List** (`/defects/`) — search (id/title), filters for status, severity, priority, platform, module, sprint, developer, date range, plus URL-only params the dashboard chips use (`state=open`, `assignee=unassigned`, `regression`, `qa`, `story`); sortable columns (severity sorts by rank, not alphabetically) and pagination.
- **Create / edit** — every spec field; the Feature select is filtered client-side by the chosen Module (and re-validated server-side); labels are checkboxes, tags are comma-separated get-or-create.
- **Workflow** — `WORKFLOW` in `app/services/defects.py` is the legal-transition matrix (e.g. Open → In Progress → Ready for QA → Verified → Closed, with Blocked/Deferred/Duplicate/Rejected/Cannot Reproduce branches and re-open paths). Terminal moves auto-set resolution + resolved date, re-opening clears them, `Duplicate` requires the original's id, and closing a regression-required defect demands a **passed** regression.
- **Comments** — threaded replies (nested), delete own (admins any); **attachments** — multi-file upload with an extension allowlist, kind auto-detection (screenshot/video/log), random stored names, image thumbnails, authenticated inline/download route, delete removes the file.
- **Audit** — every change lands in `activity_log` (field-level old → new), rendered as the History timeline; deleting a defect (admin-only) leaves a tombstone row that survives the cascade.

## Sprints, stories & epics

- **Sprints** (`/sprints/`) — list with per-sprint rollups (stories, defects done/total, completion bar, current-sprint marker), create/edit with unique-number and date validation, and a detail page: stat tiles, completion %, full status breakdown, stories with bug counts, and the sprint's defects (capped table + link into the filtered defect list).
- **Story tree** (`/sprints/stories/`) — the expandable Epic → Story → Defects hierarchy (Bootstrap collapse, animated chevrons); stories without an epic group under "No epic"; `?story=<id>` deep-links expand and scroll to a story (used by defect pages).
- **Stories & epics** — `STORY-N` / `EPIC-N` keys from the counter service; stories carry status, points, epic and sprint links; every create/edit is audit-logged field-by-field.
- **Permissions** — everyone signed in can view; creating/editing sprints, stories and epics is Admin/QA only.
- Rollup queries use correlated subqueries (never two outer joins in one statement) so counts stay correct and fast.

## Developers & workload

- **Directory** (`/developers/`) — Development team and QA team cards with per-person counts (developers: open / critical / resolved; QA: queue / reported / verified+); inactive accounts stay listed but marked.
- **Profiles** (`/developers/<id>`) — work for any account and adapt to it: stat tiles (open assigned, resolved all-time, critical open, **overdue vs ETA**), an "assigned by status" chart, delivery panel with **average resolution time** (created → resolved, computed in Python for SQLite/PostgreSQL parity), open-by-severity chips, and tabbed defect lists (open assigned / all assigned / QA queue / reported) each linking into the filtered defect list.
- **People are links** — reporter, assigned QA and developer names on defect pages, the defect list and sprint tables all click through to profiles; the defect list gained a `reporter` filter param to support the "reported by" views.

## Reports

- **Hub** (`/reports/`) — all exports in one place. CSVs open directly in Google Sheets (the team standard — no Excel dependency); PDFs open in the browser.
- **Defect CSV** — honors the *exact* defect-list filter contract; the defect list's **Export CSV** button carries whatever filters/search you have applied. 29 columns, UTF-8 with BOM, capped at 5 000 rows.
- **Team workload CSV** — one row per developer/QA: open, critical, overdue, resolved, average resolution days, QA queue, reported.
- **Sprint report PDF** and **QA summary PDF** (reportlab, pure Python, offline) — metrics tables, status breakdowns, stories, defect tables, severity chart, generated-by/date stamp.
- Known limitation (parked): the built-in PDF font lacks the ₹ glyph (shows as ■); fix later by vendoring a Unicode font.

## Project layout

```
defect-tracker/
├── run.py                  # dev entry point (python run.py → http://127.0.0.1:5001)
├── wsgi.py                 # WSGI entry; also what the `flask` CLI auto-discovers
├── requirements.txt        # runtime deps · requirements-dev.txt adds pytest
├── .env.example            # copy to .env and adjust
├── config/
│   └── settings.py         # env-driven config classes (dev / testing / prod)
├── app/
│   ├── __init__.py         # application factory (create_app)
│   ├── extensions.py       # db, migrate, login, csrf + naming conventions
│   ├── exceptions.py       # domain exception hierarchy
│   ├── error_handlers.py   # HTML pages for web, JSON envelope for /api
│   ├── models/             # ORM models: user, defect, agile, taxonomy, activity
│   ├── repositories/       # data access — BaseRepository
│   ├── services/           # business logic — BaseService
│   ├── dtos/               # request/response objects      (Phase 5+)
│   ├── routes/             # blueprints (main; auth/defects/… per phase)
│   ├── utils/              # logging, response envelope
│   ├── templates/          # Jinja: base shell, partials, errors
│   └── static/             # app.css, app.js, vendored Bootstrap + icons
├── uploads/                # attachment storage (private, gitignored)
├── instance/               # SQLite DB (auto-created, gitignored)
├── logs/                   # rotating app logs (auto-created, gitignored)
├── migrations/             # Alembic migration scripts (SQLite batch mode on)
└── tests/                  # pytest suite
```

## Getting started

```bash
cd defect-tracker
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # optional — defaults work out of the box
.venv/bin/python run.py         # → http://127.0.0.1:5001
```

Run the tests:

```bash
.venv/bin/python -m pytest
```

Health probe: `GET /health` → `{"success": true, "data": {"database": "up", ...}}`

## Configuration

All via environment variables / `.env` (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development` / `testing` / `production` |
| `SECRET_KEY` | dev-only value | **required** in production (boot refuses without it) |
| `DATABASE_URL` | SQLite in `instance/` | set a `postgresql+psycopg://…` URL to switch backends |
| `LOG_LEVEL` / `LOG_DIR` | `INFO` / `./logs` | rotating file + console logging |
| `UPLOAD_FOLDER` | `./uploads` | attachment storage |
| `MAX_UPLOAD_MB` | `200` | upload size cap (413 with a friendly message beyond it) |
| `HOST` / `PORT` | `127.0.0.1` / `5001` | dev server binding (5001 avoids macOS AirPlay on 5000) |

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Project architecture, app shell, error handling, base layers | ✅ delivered |
| 2 | Normalized database schema + migrations + seed data | ✅ delivered |
| 3 | Authentication & role-based access (Admin / QA / Developer) | ✅ delivered |
| 4 | Dashboard & analytics (charts, activity, workload) | ✅ delivered |
| 5 | Defect module — CRUD, workflow, comments, attachments | ✅ delivered |
| 6 | Sprint & story management, expandable tree view | ✅ delivered |
| 7 | Developer profiles & workload | ✅ delivered |
| 8 | Reports — CSV (Google Sheets) / PDF | ✅ delivered |
| 9 | REST API for automation (Appium / Playwright / Maestro / Postman) | planned |
| 10 | Full test suite & hardening | planned |
