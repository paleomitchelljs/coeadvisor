# CoeAdvisor

A standalone desktop app for academic advising at Coe College. Advisors enter a student's completed courses and selected programs; the tool checks progress against major/minor/GE requirements and surfaces trajectory hints from historical student data.

---

## Quick Start

**Run from source (development):**
```
python advisor.py
```
Requires Python 3.10+ with `customtkinter` installed (`pip install customtkinter`).

**Download a built release:**
Go to the [Releases](../../releases) page and download the `.zip` for the latest version.

**First-launch instructions (important):**

- **macOS:** Unzip and right-click `CoeAdvisor.app`, then choose **Open**. macOS will warn that the app is from an unidentified developer — click **Open** in the dialog. You only need to do this once; after that it opens normally.
- **Windows:** Extract the `CoeAdvisor_Windows.zip` folder and run `CoeAdvisor.exe`. If SmartScreen shows "Windows protected your PC," click **More info** then **Run anyway**. This happens because the app is not commercially code-signed — it is safe to run.

---

## Adding a New Major or Minor

Drop a new JSON file in `data/programs/` — no code changes needed. The app discovers all `*.json` files in that directory at startup.

After adding or changing any data files, rebuild the web bundle so the static site stays in sync:
```
python tools/bundle_web_data.py
```

### File naming

Use the pattern `<major_name>_<program_type>_<catalog_year>.json`, e.g.:

```
data/programs/biochemistry_major_2026.json
data/programs/theatre_minor_2026.json
```

### Minimum required fields

```json
{
  "id": "biochemistry_major_2026",
  "name": "Biochemistry",
  "program_type": "major",
  "catalog_year": "2026",
  "major_code": "BCH",
  "sections": [ ... ]
}
```

| Field | Description |
|-------|-------------|
| `id` | Must match the filename (without `.json`). Used internally and in `.adv` save files. |
| `name` | Display name shown in the program dropdowns. |
| `program_type` | `major`, `minor`, `collateral`, or `certificate`. |
| `catalog_year` | Four-digit year string. Used as a label; does not affect logic. |
| `major_code` | Three-letter prefix (e.g., `BIO`, `CS`). Must match the `major` column in `data/student_obs/` CSVs for trajectory hints to appear. |
| `sections` | Array of requirement sections — see below. |

### Section types

**`all` — every listed course is required:**
```json
{
  "id": "core",
  "label": "Core Courses",
  "type": "all",
  "items": [
    { "id": "bcm310", "title": "Biochemistry I", "codes": ["BCM-310"] },
    { "id": "bcm310l", "title": "Biochemistry Lab", "codes": ["BCM-310L"] }
  ]
}
```

**`choose_one` — student completes exactly one of the listed options:**
```json
{
  "id": "stats_or_calc",
  "label": "Mathematics (choose one)",
  "type": "choose_one",
  "options": [
    { "id": "calc", "title": "Calculus I", "codes": ["MTH-135"] },
    { "id": "stats", "title": "Statistical Foundations + Inferential Statistics", "codes": ["STA-100", "STA-110"] }
  ]
}
```

**`choose_n` — student must complete N specific items from the list:**
```json
{
  "id": "electives",
  "label": "Two from the following",
  "type": "choose_n",
  "n": 2,
  "items": [
    { "id": "bcm410", "title": "Biochemistry II", "codes": ["BCM-410"] },
    { "id": "bcm420", "title": "Protein Structure", "codes": ["BCM-420"] },
    { "id": "bcm430", "title": "Nucleic Acid Chemistry", "codes": ["BCM-430"] }
  ]
}
```

**`open_n` — N elective courses matching a constraint:**
```json
{
  "id": "upper_bio",
  "label": "Two upper-division BIO electives",
  "type": "open_n",
  "n": 2,
  "description": "Any BIO course numbered 300 or above.",
  "constraints": {
    "prefixes": ["BIO"],
    "exclude_codes": ["BIO-145", "BIO-155"],
    "min_level": 300,
    "min_level_count": 2
  }
}
```

**`non_course` — a non-course requirement advisors mark manually:**
```json
{
  "id": "seminar",
  "label": "Research Seminar Attendance",
  "type": "non_course",
  "description": "Attendance at department seminars in junior and senior years."
}
```

### Optional top-level fields

| Field | Description |
|-------|-------------|
| `recommended` | Array of free-text strings shown as advisor notes below the checklist. |
| `notes` | Single free-text string shown as an advisor note. |
| `pathway_notes` | Object mapping pathway IDs (`premed`, `pa`, `pt_dpt`) to warning strings shown when that pathway is active. |

### Items and codes

Each item in `items` or `options` has the form:
```json
{ "id": "bio145", "title": "Cellular and Molecular Biology", "codes": ["BIO-145", "BIO-145L"] }
```

A multi-code requirement (lecture + lab) is satisfied when the **primary code** (the one without an `-L` or `-C` suffix) appears in the student's course list. Lab codes are shown in the checklist but do not need to be entered separately for the requirement to be marked complete.

---

## Adding Wizard Questions for a Program

When an advisor clicks **New Student** and selects a major on the interest screen, the app looks for a matching intake file at:

```
data/intake/<program_id>.json
```

If no program-specific file exists, it falls back to `data/intake/_default.json`, which asks universal math/science comfort questions.

### Intake file format

```json
{
  "program_id": "biochemistry_major_2026",
  "intro": "Two quick questions to build a first-semester plan.",
  "questions": [
    {
      "id": "hs_chem",
      "text": "Did this student take Chemistry in high school?",
      "type": "yes_no"
    },
    {
      "id": "premed",
      "text": "Is this student interested in medical school (pre-med)?",
      "type": "yes_no"
    }
  ],
  "routes": [
    {
      "when": { "hs_chem": true, "premed": true },
      "major":      "biochemistry_major_2026",
      "pathway":    "premed",
      "semester_1": ["CHM-121", "CHM-121L", "BCM-101"],
      "note": "CHM 121 must begin first semester to keep the pre-med chemistry sequence on track."
    },
    {
      "when": { "hs_chem": true, "premed": false },
      "major":      "biochemistry_major_2026",
      "semester_1": ["CHM-121", "CHM-121L"],
      "note": "Start with CHM 121 to begin the chemistry sequence."
    },
    {
      "when": { "hs_chem": false, "premed": false },
      "major":      "biochemistry_major_2026",
      "semester_1": ["CHM-115"],
      "note": "CHM 115 (Intro Chemistry) builds the foundation before CHM 121."
    }
  ]
}
```

### Fields

| Field | Description |
|-------|-------------|
| `program_id` | Must match the program JSON `id` exactly. |
| `intro` | Short text shown above the questions. |
| `questions` | Array of yes/no questions. Only `"type": "yes_no"` is supported. |
| `routes` | Array of outcomes, checked in order. The first route whose `when` clause matches all answers is used. |

### Route fields

| Field | Required | Description |
|-------|----------|-------------|
| `when` | Yes | Object mapping question IDs to `true`/`false`. All entries must match. |
| `major` | No | Program ID to pre-select. If omitted, the selected program is used automatically. |
| `pathway` | No | Pathway ID to activate (e.g., `premed`, `pa`, `pt_dpt`). |
| `semester_1` | No | Array of course codes to pre-populate in the first semester. |
| `comfort_math` | No | `false` suppresses math courses from the suggested Year 1 plan. |
| `comfort_science` | No | `false` suppresses science courses from the suggested Year 1 plan. |
| `note` | No | Free-text string shown as a route note on the suggested plan. |

### The default fallback (`_default.json`)

`data/intake/_default.json` is used for any major without its own intake file. It asks whether the student is ready to start college-level math and science this semester. Answering "no" to either sets `comfort_math` or `comfort_science` to `false`, which suppresses those course suggestions from the first-semester plan without requiring a program-specific intake file.

### Updating the web bundle

After adding or changing any data files (programs, intake, pathways, GE, course credits, trajectory CSVs, etc.), run:
```
python tools/bundle_web_data.py
```
This regenerates `docs/data.js` so the static web app reflects the latest data. The desktop app and Flask app pick up data changes automatically on next launch; only the static site needs this step.

---

## Building

### Local build (macOS)

Requirements: Python 3.12 from [python.org](https://python.org) (the universal2 installer — not Homebrew or the system Python).

```bash
./rebuild_dist.sh
```

This script:
1. Finds the python.org Python installation in `/Library/Frameworks/Python.framework/`
2. Installs `pyinstaller` and `customtkinter` into it
3. Runs `pyinstaller advisor.spec --clean --noconfirm`
4. Produces `dist/CoeAdvisor.app` and packages it as `dist/CoeAdvisor_macOS.zip`

If the script cannot find python.org Python, download the **Python 3.12 macOS universal2** installer from [python.org/downloads](https://www.python.org/downloads/) and run it, then retry.

### Local build (Windows)

From a command prompt with Python 3.12 and `pyinstaller`/`customtkinter` installed:

```
pip install pyinstaller customtkinter
pyinstaller advisor_windows.spec --clean --noconfirm
```

Output: `dist\CoeAdvisor.exe` (single-file executable, no installer needed).

### CI build via GitHub Actions

Builds are triggered automatically on:
- **Any push of a version tag** (`v*`) — builds both macOS and Windows, attaches both artifacts to a GitHub Release
- **Manual trigger** — go to Actions → Build CoeAdvisor → Run workflow

To cut a release:
```bash
git tag v1.2.0
git push origin main --tags
```

GitHub Actions will build both platforms and publish the release with downloadable artifacts within a few minutes.

### What gets bundled

Both build specs embed the entire `data/` directory and all CustomTkinter theme assets into the app. No separate installation is needed on end-user machines — download, unzip, and run.

---

## Web Interface

There are two web interfaces — choose whichever fits your deployment:

### Static site (GitHub Pages)

A fully client-side app in `docs/`. No server needed — open `docs/index.html` directly or deploy via GitHub Pages.

All data is bundled into a single `data.js` file. To rebuild after changing data files:
```
python tools/bundle_web_data.py
```

Features: GE checking, program checking, Suggested Plan, First Two Years, trajectory hints, intake wizard, .adv save/load.

### Flask app (local server)

```
pip install flask
python web_advisor.py
```
Then open [http://localhost:5050](http://localhost:5050).

Both web interfaces produce `.adv` files compatible with the desktop app and vice versa.

---

## Project Structure

```
advising/
├── advisor_core.py              Shared logic (imported by desktop + Flask apps)
├── advisor.py                   Desktop application (CustomTkinter)
├── web_advisor.py               Flask web interface
├── templates/index.html         Flask UI template
├── static/style.css             Flask UI styles
├── requirements-web.txt         Flask dependency
├── advisor.spec                 PyInstaller spec — macOS .app bundle
├── advisor_windows.spec         PyInstaller spec — Windows .exe
├── rebuild_dist.sh              Local macOS build script
├── DOCUMENTATION.md             Full technical reference (schemas, code map)
├── .github/workflows/build.yml  CI/CD — builds and releases on tag push
├── docs/                        Static web app (GitHub Pages)
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── data.js                  Bundled data (generated by tools/bundle_web_data.py)
├── tools/
│   ├── bundle_web_data.py       Bundles data/ into docs/data.js
│   ├── extract_catalog.py       Generates courses_catalog_2025.json from PDF
│   └── extract_offerings.py     Generates offerings_2026.json from PDF
└── data/
    ├── ge_2025.json             GE requirement definitions
    ├── course_credits.json      Partial-credit overrides (labs, special courses)
    ├── dac_2025.json            Approved DAC course list
    ├── we_courses.json          Known Writing Emphasis courses
    ├── programs/                One JSON per major/minor/collateral (~64 files)
    ├── pathways/                Pre-professional pathways (premed, pa, pt_dpt)
    ├── intake/                  New-student wizard questions per program
    └── student_obs/             Historical cohort CSVs (trajectory hints)
```
