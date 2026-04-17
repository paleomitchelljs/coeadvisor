# How to Read a Coe College Catalog Year

Reference for Claude when extracting or comparing program requirements across catalog years.

## Catalog PDF Structure

Every catalog follows the same layout. Only the "Departmental Programs" section matters for program JSON files.

| Section | Pages (typical) | What's there | Action |
|---------|----------------|--------------|--------|
| Preface, College info | 1-12 | Mission, history, calendar | **Skip** |
| Educational Program | 13-25 | GE requirements, WE, FYS, practicum | Only read if updating `ge_*.json` |
| Special Programs | 27-33 | Crimson Fellows, pre-professional | Only read if updating `pathways/*.json` |
| Off-Campus Study | 30-35 | Study abroad programs | **Skip** |
| Campus Resources | 35-39 | Student services | **Skip** |
| College Regulations | 40-49 | Policies, grading, transfer | **Skip** |
| **Departmental Programs** | **50-210** | **Program requirements + course listings** | **This is what we need** |
| Admission, Financial Aid | 210+ | Enrollment info | **Skip** |

The Table of Contents (pp. 2-5) lists every department with page numbers. Use it to jump directly to specific programs.

## Departmental Program Page Format

Each department section follows this pattern:

```
—DEPARTMENT NAME
Faculty list

Introductory paragraph about the department.

[Program Name] Major                    ← REQUIREMENTS START HERE
A major in X requires...
1. COURSE-101 Title
2. COURSE-201 Title
3. Two of the following:               ← choose_n or choose_one signal
   COURSE-301 Title A
   COURSE-302 Title B
4. Three additional X courses 200+     ← open_n signal

[Program Name] Minor                    ← SEPARATE PROGRAM
1. ...

COURSES IN [DEPARTMENT]                 ← COURSE DESCRIPTIONS START
COURSE-101 Title                        ← Skip everything below this line
Description paragraph...
```

### What to read

- **"X Major"** and **"X Minor"** headings and the numbered/bulleted requirement lists below them
- **Concentration/track headings** within a major (e.g., "Finance Concentration", "Global South Track")
- **GPA notes** (e.g., "minimum cumulative 2.0 GPA")
- **Non-course requirements** (e.g., "study abroad experience", "senior recital", "portfolio review")

### What to skip

- **Course descriptions** — everything after "COURSES IN X" heading. These are individual course descriptions with prerequisites, not requirements.
- **Faculty lists** — names after the department heading
- **Department philosophy paragraphs** — introductory text about the department's mission
- **Prerequisite chains** — within course descriptions (not requirements)

## Mapping Catalog Text to JSON Section Types

| Catalog phrasing | JSON `type` | Key fields |
|-----------------|-------------|------------|
| Numbered list where all items required | `all` | `items[]` with `id`, `title`, `codes` |
| "One of the following:" | `choose_one` | `options[]` |
| "Two of the following:" / "Choose N from:" | `choose_n` | `options[]`, `n` |
| "N additional X courses" / "N electives in X numbered 200+" | `open_n` | `n`, `constraints.prefixes`, optionally `min_level` |
| "Study abroad experience" / "Senior recital" / "Portfolio" | `non_course` | `description` |

### Recognizing section boundaries

Sections are separated by language like:
- **"and"** between numbered items = same `all` section
- **"One/Two/Three of the following:"** = new `choose_one` or `choose_n` section
- **"N additional courses in X"** = new `open_n` section
- A blank line + new bold heading = new section

### Concentrations vs separate programs

Use **concentrations** (within one JSON file) when:
- Programs share a common core (same required courses for all tracks)
- The catalog presents them under one department heading with track sub-headings
- Examples: Business Administration (Finance/Marketing/Management), International Studies (Global South/Intl Relations/European)

Use **separate program files** when:
- Programs have distinct names and fully independent requirement sets
- The catalog lists them as separate majors/minors
- Examples: Kinesiology — Fitness Development vs Pre-Athletic Training (different core courses), Theatre Arts — Acting/Directing vs Design/Tech (different cores)

## Course Code Conventions

- Standard format: `PREFIX-NNN` (e.g., `BIO-145`, `CS-125`)
- Labs: `PREFIX-NNNL` (e.g., `BIO-145L`, `CHM-121L`) — always 0.2 credit
- Clinicals: `PREFIX-NNNC` (e.g., `NUR-300C`) — always 0.2 credit
- When catalog lists "BIO-145 and BIO-145L", combine into one item: `"codes": ["BIO-145", "BIO-145L"]`
- Letter suffixes on non-lab courses (e.g., `PHY-200A`) are part of the code

## Program JSON Conventions

### File naming
```
data/programs/{catalog_year}/{program_name}_{type}.json
```
Examples:
- `data/programs/2025-26/biology_major.json`
- `data/programs/2025-26/biology_minor.json`
- `data/programs/2025-26/biochemistry_collateral_major.json`

### ID format
```
{program_name}_{type}_{catalog_year}
```
Examples: `biology_major_2025-26`, `computer_science_minor_2024-25`

### Required top-level fields
```json
{
  "id": "biology_major_2025-26",
  "name": "Biology",
  "program_type": "major",
  "catalog_year": "2025-26",
  "major_code": "BIO",
  "source": "Academic Catalog 2025-26, pp. 69-75",
  "sections": [ ... ]
}
```

- `major_code`: the primary course prefix (used for trajectory matching and advice lookups)
- `source`: always cite the catalog and page numbers
- `program_type`: one of `"major"`, `"minor"`, `"collateral"`

### Section `id` naming
Use lowercase snake_case descriptive names: `core`, `electives`, `language`, `track_req`, `upper_level`, `lab_science`, etc. Keep them stable across catalog years for the same logical section.

## Comparing Across Catalog Years

### Quick-diff strategy

For each program that exists in both years:

1. **Count sections** — same number? If not, something structural changed.
2. **Compare core/required courses** — are the course codes identical? Added/removed courses?
3. **Compare elective pools** — are the options lists identical? New options added? Old ones removed?
4. **Compare constraints** — same `n` values? Same `min_level`? Same `prefixes`?
5. **Check concentrations** — were tracks added/removed/restructured?

### What constitutes "unchanged"

A program is **unchanged** (can reuse the JSON directly) if:
- All required course codes are identical
- All choose_one/choose_n option lists are identical
- All open_n constraints are identical
- Concentrations (if any) are identical
- Only cosmetic differences (title wording, description text, page numbers)

A program **needs updating** if any course code, option, constraint, or structural element changed.

### Efficient page reading

When comparing a known program against a new catalog year:
1. Use the ToC to find the page number
2. Read only the requirement pages (typically 1-3 pages per program) — stop at "COURSES IN X"
3. Diff the numbered requirements against the existing JSON
4. If identical, create the new JSON by copying the old one and updating `id`, `catalog_year`, and `source`

### Programs that commonly change between years

- Programs with many elective options (lists get updated as courses are added/retired)
- Interdisciplinary programs (cross-department dependencies shift)
- Professional programs (Nursing, Education — accreditation changes)
- New programs appear; old ones occasionally get discontinued

### Programs that rarely change

- Small/focused programs (Classical Studies minor, Anthropology minor)
- Math-heavy programs (Mathematics, Physics — course sequences are stable)
- Established liberal arts programs (Philosophy, Religion)

## Workflow: Adding a New Catalog Year

1. **Create the directory**: `data/programs/{year}/`
2. **Read the ToC** (pp. 2-5) to get the full department list and page numbers
3. **For each department**, read the requirement pages and either:
   - Copy+update from the nearest existing year if unchanged
   - Write new JSON if requirements changed
4. **Update advice references**: check `data/advice/*/_advice.json` `match_programs` arrays
5. **Rebuild the web bundle**: `python3 tools/bundle_web_data.py`
6. **Test in browser**: verify programs appear in dropdowns and check correctly

## Tools

| Tool | Purpose |
|------|---------|
| `tools/bundle_web_data.py` | Bundles all `data/` into `docs/data.js` for the static web app |
| `tools/extract_catalog.py` | Extracts course listings (not requirements) from catalog PDF into `courses_catalog_*.json` |
| `tools/clean_advice_plans.py` | Cleans up advice plan JSON files (course code extraction) |

Note: `extract_catalog.py` extracts **course descriptions**, not program requirements. Program requirement JSONs are created manually by reading the catalog.
