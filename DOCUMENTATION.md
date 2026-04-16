# Coe College Academic Advising Tool — Documentation

## Overview

An academic advising tool for Coe College available as three interfaces sharing the same data and logic:

1. **Desktop app** (`advisor.py`) — Python/CustomTkinter GUI, bundled as macOS `.app` and Windows `.exe`
2. **Flask web app** (`web_advisor.py`) — server-side web interface for local use
3. **Static web app** (`docs/`) — pure HTML/CSS/JS for GitHub Pages deployment, no server needed

All three check student progress against major/minor requirements and GE requirements, surface trajectory hints from historical student data, and produce compatible `.adv` files.

---

## Running and Building

**Desktop (development):**
```
pip install customtkinter
python advisor.py
```
Requires Python 3.10+.

**Flask web app:**
```
pip install flask
python web_advisor.py
```
Then open [http://localhost:5050](http://localhost:5050).

**Static web app:**
Open `docs/index.html` in a browser, or deploy `docs/` via GitHub Pages.

**macOS App Bundle:**
```
./rebuild_dist.sh
```
Uses PyInstaller (`advisor.spec`) to produce `dist/CoeAdvisor.app`, then zips it. The `data/` directory is embedded in the bundle. When frozen, `sys._MEIPASS` is used as the base path instead of the script directory.

**Windows build:**
```
pip install pyinstaller customtkinter
pyinstaller advisor_windows.spec --clean --noconfirm
```
Output: `dist\CoeAdvisor\CoeAdvisor.exe` (onedir mode).

**CI build via GitHub Actions:**
Builds are triggered on version tag push (`v*`) or manual trigger. To cut a release:
```bash
git tag v1.4.0
git push origin main --tags
```

---

## Architecture

```
                     ┌──────────────────┐
                     │  advisor_core.py │  Pure logic (stdlib only)
                     │  - normalize()   │  - Course utilities
                     │  - check_*()     │  - Requirement checker
                     │  - load_*()      │  - Data loading
                     │  - TrajectoryData│  - Trajectory hints
                     └────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
     ┌────────▼──────┐  ┌────▼─────┐  ┌──────▼──────────┐
     │  advisor.py   │  │ web_     │  │  docs/app.js    │
     │  Desktop GUI  │  │ advisor  │  │  Static web app │
     │  (CTk)        │  │ (Flask)  │  │  (JS port)      │
     └───────────────┘  └──────────┘  └─────────────────┘
              │               │               │
              └───────────────┼───────────────┘
                              │
                     ┌────────▼─────────┐
                     │    data/*.json   │  Programs, GE, pathways,
                     │    data/*.csv    │  intake, trajectory
                     └──────────────────┘
```

- **`advisor_core.py`** — all pure logic: course normalization, requirement checking, GE checking, data loading, and the `TrajectoryData` class. No GUI or web dependencies. Imported by both `advisor.py` and `web_advisor.py`.
- **`docs/app.js`** — JavaScript port of the same algorithms for the static web app. Data is bundled into `docs/data.js` by `tools/bundle_web_data.py`.
- All program/GE data is JSON; loaded at startup, never written back.
- `.adv` file format is compatible across all three interfaces.

**After changing any data files**, run:
```
python tools/bundle_web_data.py
```
This regenerates `docs/data.js`. The desktop and Flask apps pick up changes automatically on next launch.

---

## File Structure

```
advising/
├── advisor_core.py              Shared logic (imported by desktop + Flask apps)
├── advisor.py                   Desktop application (CustomTkinter)
├── web_advisor.py               Flask web interface
├── templates/index.html         Flask UI template
├── static/style.css             Flask UI styles
├── requirements-web.txt         Flask dependency (flask>=3.0)
├── advisor.spec                 PyInstaller spec — macOS .app bundle
├── advisor_windows.spec         PyInstaller spec — Windows .exe (onedir)
├── version_info.txt             Windows VERSIONINFO resource
├── rebuild_dist.sh              Local macOS build script
├── CLAUDE.md                    Claude Code context file
├── DOCUMENTATION.md             This file
├── README.md                    User-facing README
├── .github/workflows/build.yml  CI/CD — builds and releases on tag push
├── docs/                        Static web app (GitHub Pages)
│   ├── index.html               Main page
│   ├── style.css                Styles
│   ├── app.js                   JS port of core logic + UI
│   ├── data.js                  Bundled data (generated, do not hand-edit)
│   └── .nojekyll                Tells GitHub Pages to serve raw files
├── tools/
│   ├── bundle_web_data.py       Bundles data/ into docs/data.js
│   ├── extract_catalog.py       Generates courses_catalog_2025.json from PDF
│   └── extract_offerings.py     Generates offerings_2026.json from PDF
└── data/
    ├── ge_2025.json             GE requirement definitions
    ├── course_credits.json      Partial-credit overrides (labs, specials)
    ├── courses_catalog_2025.json Structured course catalog
    ├── offerings_2026.json      Per-term course offerings
    ├── dac_2025.json            Approved DAC course list
    ├── we_courses.json          Known Writing Emphasis courses
    ├── first_two_years.json     Recommended first-two-year sequences by major
    ├── programs/                One JSON per major/minor/collateral (~64 files)
    ├── pathways/                Pre-professional pathways (premed, pa, pt_dpt)
    ├── intake/                  New-student wizard questions per program
    └── student_obs/             Historical cohort data (CSV)
        ├── major_course_summary.csv
        ├── major_profiles.csv
        └── major_summary.csv
```

---

## Data Formats

### Program JSON (`data/programs/*.json`)

```json
{
  "id": "biology_major_2025",
  "name": "Biology",
  "program_type": "major",
  "catalog_year": "2025",
  "major_code": "BIO",
  "source": "Biology Checklist 2025.pdf",
  "sections": [ ... ],
  "recommended": [ "BIO-415", ... ],
  "notes": "Free-text advisor notes",
  "pathway_notes": {
    "premed": "CHM-121/121L must start first semester"
  }
}
```

**Section Types:**

| `type`       | Meaning                                       | Key fields                        |
|--------------|-----------------------------------------------|-----------------------------------|
| `all`        | Every listed item required                    | `items[]`                         |
| `choose_one` | Exactly one option set must be fully complete | `options[]`                       |
| `choose_n`   | Student must complete N items from the list   | `items[]`, `n`                    |
| `open_n`     | N elective courses matching constraints       | `n`, `constraints`                |
| `non_course` | Non-course requirement (marked manually)      | `description`                     |

`open_n` constraint fields:
```json
"constraints": {
  "prefixes": ["BIO"],
  "exclude_codes": ["BIO-145"],
  "min_level": 300,
  "min_level_count": 2
}
```

`items` and `options` entries:
```json
{ "id": "bio145", "title": "Principles of Biology", "codes": ["BIO-145", "BIO-145L"] }
```
A requirement with both a lecture and lab code is satisfied when the **primary** (non-`-L`/`-C`) code is in the taken set.

### Pathway JSON (`data/pathways/*.json`)

Same schema as programs but with `pathway_type: "preprofessional"` instead of `program_type`, and an optional top-level `timing_note` string.

### GE JSON (`data/ge_2025.json`)

```json
{
  "version": "GE2025",
  "divisional": {
    "rule": "Max 2 courses per prefix",
    "sections": {
      "fine_arts":        { "prefixes": [...], "credits_required": 2 },
      "humanities":       { ... },
      "nat_sci_math":     { ... },
      "lab_science":      { ... },
      "social_sciences":  { ... }
    }
  },
  "additional": {
    "first_year_seminar":  { "count": 1, "prefixes": ["FYS", "FS"] },
    "writing_emphasis":    { "count_standard": 5, "count_transfer_8_16": 3 },
    "dac":                 { "count": 2 },
    "practicum":           { "count": 1, "prefixes": ["PRX"] }
  }
}
```

The `lab_science` section requires a matched lecture + lab pair (e.g., `BIO-145` + `BIO-145L`).

### Course Credits Override (`data/course_credits.json`)

```json
{ "overrides": { "EDU-219": 0.5, "MUA-101": 0.5, ... } }
```

Default credit values: `-L`/`-C` suffix -> 0.2, everything else -> 1.0. Overrides take priority.

### First Two Years (`data/first_two_years.json`)

```json
{
  "entries": [
    {
      "id": "biology_well_prepared",
      "label": "Biology — well-prepared track",
      "variant_note": "Students with strong high school science background",
      "match_major_codes": ["BIO"],
      "match_program_ids": ["biology_major_2025"],
      "semesters": {
        "y1_fall":   { "essential": ["BIO-155", "BIO-155L"], "suggested": ["CHM-121", "CHM-121L"] },
        "y1_spring": { "essential": ["BIO-145", "BIO-145L"], "suggested": ["CHM-122", "CHM-122L"] },
        "y2_fall":   { "essential": [...], "suggested": [...] },
        "y2_spring": { "essential": [...], "suggested": [...] }
      },
      "notes": "Free-text notes for advisors"
    }
  ]
}
```

Matching: entries are matched to selected programs by `match_major_codes` (program's `major_code`) or `match_program_ids` (program's `id`).

### Intake Wizard (`data/intake/*.json`)

```json
{
  "program_id": "biology_major_2025",
  "intro": "Two quick questions to build a first-semester plan.",
  "questions": [
    { "id": "hs_bio_chem", "text": "Did this student take Biology and Chemistry in high school?", "type": "yes_no" }
  ],
  "routes": [
    {
      "when": { "hs_bio_chem": true },
      "major": "biology_major_2025",
      "pathway": "premed",
      "semester_1": ["BIO-145", "BIO-145L"],
      "note": "Start with BIO 155 for well-prepared students."
    }
  ]
}
```

`_default.json` is the fallback for programs without their own intake file.

### Student Observation CSV (`data/student_obs/major_course_summary.csv`)

Columns: `major`, `course`, `dept`, `division`, `course_tier`, `n_took`, `n_total_grads`, `pct_took`, `typical_semester`, `earliest_semester`, `latest_semester`, `mean_grade`

- `major` — matches `major_code` in program JSON (e.g., `BIO`, `CS`)
- `course_tier` — `common` or `elective` (only these two tiers appear in suggestions)
- `pct_took` — fraction of graduates in that major who took this course (0-1)
- `typical_semester` — median semester students took this course (1 = first semester)
- `mean_grade` — present in data but **intentionally not displayed** to advisors

---

## Student File Format (`.adv`)

Created by **Save .adv** in any interface, loaded by **Load .adv**.

```
# Coe College Academic Advising Student File
# Generated: 2026-04-16 10:30

NAME: Jane Doe
ID: 12345
YEAR: First Year
MAJOR1: biology_major_2025
MAJOR2: chemistry_major_2026
MAJOR3:
MINOR1:
MINOR2:
PATHWAYS: premed
TRANSFER_WE: 0 credits (5 WE)

SEMESTER: Transfer
COURSE: AP-BIO, completed

SEMESTER: Semester 1
COURSE: BIO-145, completed
COURSE: BIO-145L, completed
COURSE: CHM-121, completed
COURSE: CHM-121L, completed
COURSE: FS-110, completed

SEMESTER: Semester 2
COURSE: BIO-155, completed
COURSE: BIO-155L, completed
COURSE: CHM-122, planned

# -- SUGGESTED NEXT COURSES (reference only -- not imported) --
# BIO-325        67% of grads   Sem 3
# CHM-231        45% of grads   Sem 4
```

**Import rules:**
- Lines starting with `#` are ignored
- Blank lines are ignored
- `SEMESTER:` starts a new semester block; `COURSE:` adds a course to the current block
- Course status is `completed` or `planned`
- The `SUGGESTED NEXT COURSES` block is comment-prefixed and ignored on import
- Legacy format (`COURSES:` flat list, `PROGRAMS:` comma-separated) is supported on import

---

## Code Reference

### `advisor_core.py` — Shared logic module

All pure logic shared by the desktop app, Flask app, and (via JS port) static web app.

**Constants:**

| Name | Value |
|------|-------|
| `COMPLETE` | `"complete"` |
| `PARTIAL` | `"partial"` |
| `INCOMPLETE` | `"incomplete"` |
| `MANUAL` | `"manual"` |
| `STUDENT_YEARS` | `["First Year", "Sophomore", "Junior", "Senior", "Transfer Student"]` |
| `PLAN_SEM_LABELS` | `{1: "Fall -- Year 1", 2: "Spring -- Year 1", ...}` |
| `F2Y_SEM_KEYS` | `["y1_fall", "y1_spring", "y2_fall", "y2_spring"]` |

**Data loading functions:**

| Function | Returns | Notes |
|----------|---------|-------|
| `load_programs()` | `dict[id -> program]` | Loads all `data/programs/*.json` |
| `load_ge()` | `dict` | Loads `data/ge_2025.json` |
| `load_dac()` | `set` | Loads `data/dac_2025.json` -> set of course codes |
| `load_we()` | `set` | Loads `data/we_courses.json` -> set of course codes |
| `load_course_credits()` | `dict[code -> float]` | Loads `data/course_credits.json`, normalizes keys |
| `load_pathways()` | `dict[id -> pathway]` | Loads all `data/pathways/*.json` |
| `load_first_two_years()` | `list` | Loads `data/first_two_years.json` entries |
| `load_catalog()` | `dict` | Loads `data/courses_catalog_2025.json` |
| `load_offerings()` | `dict` | Loads `data/offerings_2026.json` |
| `load_intake()` | `dict[program_id -> intake]` | Loads all `data/intake/*.json` |

All accept an optional `data_dir` parameter; defaults to `BASE_DIR / "data"`.

**Course utilities:**

| Function | Purpose |
|----------|---------|
| `normalize(code)` | `"bio 145"` -> `"BIO-145"` |
| `parse_courses(text)` | Parses free-form text; handles `BIO-145/145L` shorthand |
| `prefix_of(code)` | `"BIO-145"` -> `"BIO"` |
| `level_of(code)` | `"BIO-215"` -> `200` |
| `is_lab(code)` | True if ends in digit + `L` |
| `is_clinical(code)` | True if ends in digit + `C` |
| `is_auxiliary(code)` | True if lab or clinical |
| `is_math_course(code)` | True if prefix in MTH/STA/MAT |
| `is_science_course(code)` | True if prefix in BIO/CHM/PHY/ESC/ENS/GEO |
| `credit_of(code, overrides)` | Returns credit value for one course |
| `total_credits(taken, overrides)` | Sums credits for a set of courses |

**Requirement checker:**

| Function | Purpose |
|----------|---------|
| `check_section(section, taken)` | Evaluates one requirement section -> dict with `status` |
| `check_program(program, taken)` | Evaluates all sections -> dict with `sections`, `total`, `complete` |
| `check_ge(ge, taken, dac, we, manual)` | Evaluates all GE requirements -> dict keyed by category |

**`TrajectoryData` class:**

Loads `major_course_summary.csv` and provides:
- `course_info(major_code, course_code)` -> `{tier, sem, grade, pct}` or `None`
- `elective_suggestions(major_code, exclude, n=12)` -> list of `(code, info)` sorted by `pct` descending, filtered to `tier in ("elective", "common")` and `pct >= 0.15`
- `as_dict()` -> raw `{major: {code: info}}` for serialization

### `advisor.py` — Desktop GUI

Imports all logic from `advisor_core`. Contains the `AdvisorApp` class (~2800 lines) which builds the CustomTkinter interface.

**Key methods:**
| Method | Purpose |
|--------|---------|
| `check()` | Parses courses, runs requirement checks, renders all tabs |
| `clear_all()` | Resets all fields and clears tabs |
| `export()` | Saves full advising report as `.txt` |
| `save_student()` | Saves student data as `.adv` file |
| `load_student()` | Reads `.adv` file and populates form |
| `_render_suggested_plan()` | Builds the Suggested Plan tab with collapsible semesters |

### `web_advisor.py` — Flask web interface

Imports all logic from `advisor_core`. Routes:
- `GET /` — serves the main page
- `POST /api/check` — runs GE + program checks, returns JSON

### `docs/app.js` — Static web app

JavaScript port of all `advisor_core` algorithms. Uses `DATA` from `docs/data.js` (generated by `tools/bundle_web_data.py`).

Features: GE checking, program checking, Suggested Plan (collapsible semesters, GE fill-in hints), First Two Years, trajectory hints, intake wizard, .adv save/load.

---

## Static Web App — Updating Data

The static site in `docs/` bundles all data into `docs/data.js`. This file is generated and should not be hand-edited.

**When to regenerate:**
- After adding, editing, or removing any file in `data/`
- After changing programs, pathways, intake, GE, course credits, trajectory CSVs, etc.

**How to regenerate:**
```
python tools/bundle_web_data.py
```

**What gets bundled:**
- All `data/programs/*.json`
- All `data/pathways/*.json`
- All `data/intake/*.json`
- `data/ge_2025.json`
- `data/course_credits.json`
- `data/dac_2025.json`
- `data/we_courses.json`
- `data/first_two_years.json`
- `data/courses_catalog_2025.json` (if present)
- `data/offerings_2026.json` (if present)
- `data/student_obs/major_course_summary.csv` (parsed to JSON)

The generated `data.js` is committed to the repo so GitHub Pages can serve it. Remember to commit the regenerated file after running the bundler.

---

## Adding a New Program

1. Create `data/programs/<id>.json` following the program schema above.
2. Set `"id"` to match the filename (without `.json`).
3. Set `"major_code"` to the prefix used in `student_obs` CSVs (e.g., `"CS"`, `"BIO"`).
4. **Rebuild the web bundle:** `python tools/bundle_web_data.py`
5. Restart the desktop/Flask app — programs are loaded at startup with no code changes needed.

To add trajectory data, add rows to `data/student_obs/major_course_summary.csv` with `major` matching the new `major_code`, then rebuild the web bundle.

To add intake wizard questions, create `data/intake/<program_id>.json` following the intake schema, then rebuild the web bundle.

## Adding a New GE Catalog Year

1. Copy `data/ge_2025.json` to `data/ge_<year>.json` and edit as needed.
2. In `advisor_core.py`, update the `load_ge()` function to reference the new filename.
3. In `tools/bundle_web_data.py`, update the GE path in the bundle dict.
4. Rebuild the web bundle.

---

## Status Indicators

| Symbol | Status | Color | Meaning |
|--------|--------|-------|---------|
| ✓ | `complete` | Green `#15803d` | All items in section satisfied |
| ◑ | `partial` | Amber `#b45309` | Some items satisfied |
| ✗ | `incomplete` | Red `#b91c1c` | No items satisfied |
| ℹ | `manual` | Blue `#1d4ed8` | Non-course requirement — mark manually |

---

## Known Limitations

- **No semester tracking for courses taken.** The `Sem N` trajectory hints show the *typical* semester based on historical cohorts, not when this student took the course.
- **Session only — no auto-save.** Use Save .adv before closing to persist a session.
- **Transfer credit granularity.** Only three WE-count tiers are supported (0, 1-7, 8-15, 16+ credits). Individual transfer course articulations are not modeled.
- **No GPA display.** The `mean_grade` field exists in the trajectory CSV but is intentionally hidden. Only "% of grads" and "Sem N" hints are shown.
- **Static site data is a snapshot.** The `docs/data.js` bundle must be regenerated manually after data changes.
