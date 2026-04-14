# Coe College Academic Advising Tool — Documentation

## Overview

A standalone Python desktop application for academic advising at Coe College. Advisors enter a student's completed courses and selected programs; the tool checks progress against all requirement sections, flags gaps, and surfaces commonly taken electives drawn from historical student data.

---

## Running and Building

**Development:**
```
python advisor.py
```
Requires Python 3.11+ with no third-party packages (uses only stdlib: `tkinter`, `csv`, `json`, `re`, `pathlib`).

**macOS App Bundle:**
```
./rebuild_dist.sh
```
Uses PyInstaller (`advisor.spec`) to produce `dist/CoeAdvisor.app`, then zips it. The `data/` directory is embedded in the bundle. When frozen, `sys._MEIPASS` is used as the base path instead of the script directory.

---

## File Structure

```
advising/
├── advisor.py                  Main application (single file)
├── advisor.spec                PyInstaller build spec
├── rebuild_dist.sh             Build script → CoeAdvisor.app + .zip
├── DOCUMENTATION.md            This file
└── data/
    ├── ge_2025.json            GE requirement definitions
    ├── course_credits.json     Partial-credit overrides (labs, specials)
    ├── dac_2025.json           Approved DAC course list
    ├── we_courses.json         Known Writing Emphasis courses
    ├── programs/               One JSON per major/minor (24 files)
    │   ├── biology_major_2025.json
    │   ├── cs_major_2021.json
    │   └── …
    ├── pathways/               Pre-professional pathways (3 files)
    │   ├── premed.json
    │   ├── pa.json
    │   └── pt_dpt.json
    └── student_obs/            Historical cohort data (CSV)
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
  "program_type": "major",          // major | minor | collateral | certificate
  "catalog_year": "2025",
  "major_code": "BIO",              // matches major column in student_obs CSVs
  "source": "Biology Checklist 2025.pdf",
  "sections": [ ... ],              // see Section Types below
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
  "prefixes": ["BIO"],          // only these prefixes count
  "exclude_codes": ["BIO-145"], // these codes do not count
  "min_level": 300,             // at least min_level_count must be ≥ this level
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
    "first_year_seminar":  { "count": 1, "prefixes": ["FYS"] },
    "writing_emphasis":    { "count_standard": 5, "count_transfer_8_16": 3 },
    "dac":                 { "count": 2 },
    "practicum":           { "count": 1, "prefixes": ["PRX"] }
  }
}
```

The `lab_science` section requires a matched lecture + lab pair (e.g., `BIO-145` + `BIO-145L`).

### Course Credits Override (`data/course_credits.json`)

```json
{ "overrides": { "EDU-219": 0.5, "MUA-101": 0.5, … } }
```

Default credit values: `-L`/`-C` suffix → 0.2, everything else → 1.0. Overrides take priority.

### Student Observation CSV (`data/student_obs/major_course_summary.csv`)

Columns: `major`, `course`, `dept`, `division`, `course_tier`, `n_took`, `n_total_grads`, `pct_took`, `typical_semester`, `earliest_semester`, `latest_semester`, `mean_grade`

- `major` — matches `major_code` in program JSON (e.g., `BIO`, `CS`)
- `course_tier` — `common` or `elective` (only these two tiers appear in suggestions)
- `pct_took` — fraction of graduates in that major who took this course (0–1)
- `typical_semester` — median semester students took this course (1 = first semester)

---

## Student File Format (`.adv`)

Created by **Save Student File**, read by **Load Student File**.

```
# Coe College Academic Advising Student File
# Generated: 2026-04-14 10:30

NAME: Jane Doe
ID: 12345
TRANSFER: 0 credits (5 WE)
PROGRAMS: biology_major_2025, chemistry_major_2026
PATHWAYS: premed

COURSES:
# Typical Semester 1
BIO-145
BIO-145L
CHM-121
CHM-121L

# Typical Semester 2
BIO-195
CHM-122

# No semester data
ENG-110

# ── SUGGESTED NEXT COURSES (reference only — not imported) ──────
# BIO-325        67% of grads   Sem 3
# CHM-231        45% of grads   Sem 4
```

**Import rules:**
- Lines starting with `#` are always ignored (comments, semester headers, suggestion block)
- Blank lines are ignored
- All other lines in the `COURSES:` block are treated as course codes
- Semester groupings in the exported file are for human readability only — on import, courses are loaded as a flat list
- The `SUGGESTED NEXT COURSES` block is ignored on import (it is comment-prefixed)

**Valid `TRANSFER` values:**
- `0 credits (5 WE)`
- `1–7 credits (5 WE)`
- `8 credits — max (3 WE)`

---

## Code Reference (`advisor.py`)

### Top-level functions

| Function | Lines | Purpose |
|---|---|---|
| `_base_dir()` | ~24 | Resolves data directory for both dev and frozen app |
| `_load_json(path)` | ~49 | Reads and parses a JSON file |
| `_load_programs(dir)` | ~53 | Loads all `*.json` files from `data/programs/` |
| `_load_pathways(dir)` | ~93 | Loads all `*.json` files from `data/pathways/` |
| `normalize(code)` | ~107 | Normalizes `"bio 145"` → `"BIO-145"` |
| `parse_courses(text)` | ~114 | Parses free-form text; handles `/` shorthand |
| `prefix_of(code)` | ~147 | Returns `"BIO"` from `"BIO-145"` |
| `level_of(code)` | ~152 | Returns `200` from `"BIO-215"` |
| `is_lab(code)` | ~158 | True if code ends in a digit + `L` |
| `is_clinical(code)` | ~162 | True if code ends in a digit + `C` |
| `is_auxiliary(code)` | ~166 | True if lab or clinical |
| `credit_of(code, overrides)` | ~171 | Returns credit value for one course |
| `total_credits(taken, overrides)` | ~186 | Sums credits for a set of courses |
| `_codes_satisfied(codes, taken)` | ~192 | Checks if primary code is in taken set |
| `check_section(section, taken)` | ~205 | Evaluates one requirement section |
| `check_program(program, taken)` | ~271 | Evaluates all sections of one program |
| `check_ge(ge, taken, dac, we, manual)` | ~280 | Evaluates all GE requirements |

### `TrajectoryData` class (~line 353)

Loads `major_course_summary.csv` and provides two methods:

- `course_info(major_code, course_code)` → `{tier, sem, grade, pct}` or `None`
- `elective_suggestions(major_code, exclude, n=12)` → list of `(code, info)` pairs sorted by `pct` descending, filtered to `tier in ("elective", "common")` and `pct >= 0.15`

### `AdvisorApp` class (~line 427)

The main Tkinter application class.

**Key instance attributes:**

| Attribute | Type | Purpose |
|---|---|---|
| `self.programs` | `dict[id → program]` | All loaded programs |
| `self.pathways` | `dict[id → pathway]` | All loaded pathways |
| `self.ge_data` | `dict` | GE requirements |
| `self.we` | `set` | Known WE course codes |
| `self.dac` | `set` | Known DAC course codes |
| `self.course_credits` | `dict` | Credit overrides |
| `self.trajectory` | `TrajectoryData` | Historical data for hints |
| `self.prog_lb` | `tk.Listbox` | Multi-select program list |
| `self._prog_ids` | `list[str]` | Program IDs parallel to listbox rows |
| `self.pathway_vars` | `dict[id → BooleanVar]` | Pathway checkbox states |
| `self.courses_txt` | `ScrolledText` | Course entry textarea |
| `self.name_var` | `StringVar` | Student name |
| `self.id_var` | `StringVar` | Student ID |
| `self.transfer_var` | `StringVar` | Transfer credit selection |
| `self.nb` | `ttk.Notebook` | Results tab widget |

**Key methods:**

| Method | Purpose |
|---|---|
| `_build_ui()` | Constructs top bar + paned window |
| `_build_left(parent)` | Left sidebar: student fields, program list, pathways, courses, buttons |
| `_build_right(parent)` | Right pane: summary label + notebook |
| `check()` | Parses courses, runs requirement checks, renders all tabs |
| `clear_all()` | Resets all fields and clears tabs |
| `export()` | Saves full advising report as `.txt` |
| `save_student()` | Saves student data (name/ID/programs/courses) as `.adv` file |
| `load_student()` | Reads an `.adv` file and populates all form fields |
| `_render_ge(parent, result, we_required)` | Draws the GE tab |
| `_render_program(parent, result, active_pathways)` | Draws one program/pathway tab |
| `_traj_hint(major_code, code)` | Returns `"← Sem N"` string for trajectory display, or `""` |

---

## UI Layout

```
┌─ Top bar (dark) ──────────────────────────────────────────────────────────┐
│  Coe College | Academic Advising Tool                                     │
├─ Left sidebar (290px) ────┬─ Right pane (expands) ────────────────────────┤
│  STUDENT                  │  [Summary label]                              │
│    Name                   │                                               │
│    ID                     │  ┌─ GE Requirements ─┬─ Biology (Major) ─┐   │
│    Transfer credits        │  │  Divisional reqs  │  Progress bar     │   │
│                           │  │  Additional reqs   │  Required sections│   │
│  PROGRAMS (multi-select)  │  │                   │  Recommended      │   │
│    [listbox]              │  │                   │  Elective hints   │   │
│                           │  └───────────────────┴───────────────────┘   │
│  PATHWAYS (checkboxes)    │                                               │
│                           │                                               │
│  COURSES TAKEN            │                                               │
│    [textarea]             │                                               │
│                           │                                               │
│  [Check Requirements]     │                                               │
│  [Save Student File]      │                                               │
│  [Load Student File]      │                                               │
│  [Export Report]          │                                               │
│  [Clear All]              │                                               │
└───────────────────────────┴───────────────────────────────────────────────┘
```

---

## Status Indicators

| Symbol | Tag | Color | Meaning |
|--------|-----|-------|---------|
| ✓ | `complete` | Green `#1e8449` | All items in section satisfied |
| ◑ | `partial` | Orange `#b7770d` | Some items satisfied |
| □ | `incomplete` | Red `#c0392b` | No items satisfied |
| ◻ | `manual` | Blue `#2471a3` | Non-course requirement — mark manually |

---

## Adding a New Program

1. Create `data/programs/<id>.json` following the program schema above.
2. Set `"id"` to match the filename (without `.json`).
3. Set `"major_code"` to the prefix used in `student_obs` CSVs (e.g., `"CS"`, `"BIO"`).
4. Restart the app — programs are loaded at startup with no code changes needed.

To add trajectory data for the new program, add rows to `data/student_obs/major_course_summary.csv` with `major` matching the new `major_code`.

## Adding a New GE Catalog Year

1. Copy `data/ge_2025.json` to `data/ge_<year>.json` and edit as needed.
2. In `advisor.py` near line 437, update the path passed to `_load_json`:
   ```python
   self.ge_data = _load_json(DATA_DIR / "ge_<year>.json")
   ```

---

## Known Limitations

- **No semester tracking for courses taken.** The app has no field for which semester a student took a course. The `Sem N` trajectory hints show the *typical* semester based on historical cohorts, not when this student took the course.
- **Session only — no auto-save.** Use **Save Student File** before closing to persist a session.
- **Transfer credit granularity.** Only three WE-count tiers are supported (0 credits, 1–7 credits, 8+ credits). Individual transfer course articulations are not modeled.
- **GE manual items.** FYS and Practicum can be satisfied by recognized course prefixes (`FYS-*`, `PRX-*`) but the UI does not expose a manual-override checkbox — they appear as `◻ manual` if no matching course is found.
