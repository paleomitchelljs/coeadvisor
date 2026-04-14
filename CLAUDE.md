# Coe College Academic Advising Tool — Claude Context

## What this is

A standalone Python/Tkinter desktop app for academic advising at Coe College. Given a student's completed courses, it checks progress against major/minor requirements and GE requirements, and surfaces trajectory hints from historical student data.

## Key files

| File | Purpose |
|------|---------|
| `advisor.py` | Entire application — single file, ~1100 lines |
| `advisor.spec` | PyInstaller build spec for macOS `.app` bundle |
| `rebuild_dist.sh` | Builds `dist/CoeAdvisor.app` and packages as `.zip` |
| `DOCUMENTATION.md` | Full technical reference (schemas, code map, UI layout) |

## Data directory (`data/`)

| Path | Purpose |
|------|---------|
| `data/ge_2025.json` | GE requirement definitions (divisional + WE/DAC/FYS/Practicum) |
| `data/course_credits.json` | Credit overrides for partial-credit courses (labs=0.2, some specials=0.5) |
| `data/dac_2025.json` | Approved Diversity Across Curriculum course list |
| `data/we_courses.json` | Known Writing Emphasis courses |
| `data/programs/*.json` | One file per major/minor/collateral (24 files) |
| `data/pathways/*.json` | Pre-professional pathways: `premed`, `pa`, `pt_dpt` |
| `data/student_obs/*.csv` | Historical cohort data: typical semester, % of grads who took each course |

## Reference directories (source docs, not loaded by the app)

| Directory | Contents |
|-----------|---------|
| `checklists/` | Official PDF/DOCX advising checklists from the Registrar |
| `catalogs/` | Course catalog PDFs |
| `dac/` | DAC course list PDFs |
| `gened/` | GE worksheet PDFs |

## Architecture

- No external dependencies — pure Python stdlib (`tkinter`, `csv`, `json`, `re`, `pathlib`)
- All program/GE data is JSON; loaded at startup, never written back
- Student data lives in memory only during a session
- **Save Student File** → `.adv` text format (importable)
- **Load Student File** ← reads `.adv` and populates the form
- **Export Report** → timestamped `.txt` of the full rendered UI (not importable)

## Program JSON schema (brief)

```json
{
  "id": "biology_major_2025",
  "program_type": "major",
  "major_code": "BIO",
  "catalog_year": "2025",
  "sections": [
    { "type": "all|choose_one|choose_n|open_n|non_course", ... }
  ]
}
```

See `DOCUMENTATION.md` for full schema, section type details, `.adv` file format, and the complete code reference.

## Adding a new program

Drop a new JSON file in `data/programs/` following the schema — no code changes needed. The app discovers all `*.json` files in that directory at startup.

## Important goals / constraints

- **No GPA display.** The `mean_grade` field exists in the trajectory CSV but is intentionally not shown to advisors. Only `% of grads who took` and `Sem N` hints are surfaced.
- **No external dependencies.** Keep it stdlib-only so the app bundles cleanly with PyInstaller.
- **Single-file app.** All logic stays in `advisor.py`. Don't split into modules unless the file grows substantially beyond ~1500 lines.
- **Data-driven programs.** Requirement logic must stay in the JSON schemas, not hardcoded in Python, so new majors/catalog years can be added without touching code.
