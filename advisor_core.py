"""
Coe College Academic Advising Tool — Shared Core
==================================================
Pure logic shared by the desktop app (advisor.py) and the web interface.
No GUI dependencies — only stdlib + csv/json/re/pathlib.
"""

import csv
import json
import re
import sys
from pathlib import Path

# ─────────────────────────── Paths ───────────────────────────────────────────

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)           # type: ignore[attr-defined]
    return Path(__file__).parent


BASE_DIR     = _base_dir()
DATA_DIR     = BASE_DIR / "data"
PROGRAMS_DIR = DATA_DIR / "programs"

# ─────────────────────────── Status constants ────────────────────────────────

COMPLETE   = "complete"
PARTIAL    = "partial"
INCOMPLETE = "incomplete"
MANUAL     = "manual"

STUDENT_YEARS = ["First Year", "Sophomore", "Junior", "Senior",
                 "Transfer Student"]

# ─────────────────────────── Semester key constants ──────────────────────────

F2Y_SEM_KEYS   = ["y1_fall", "y1_spring", "y2_fall", "y2_spring"]
F2Y_SEM_NUM    = {"y1_fall": 1, "y1_spring": 2, "y2_fall": 3, "y2_spring": 4}
F2Y_SEM_LABELS = {
    "y1_fall":   "Year 1 \u2014 Fall",
    "y1_spring": "Year 1 \u2014 Spring",
    "y2_fall":   "Year 2 \u2014 Fall",
    "y2_spring": "Year 2 \u2014 Spring",
}

PLAN_SEM_LABELS = {
    1: "Fall \u2014 Year 1",   2: "Spring \u2014 Year 1",
    3: "Fall \u2014 Year 2",   4: "Spring \u2014 Year 2",
    5: "Fall \u2014 Year 3",   6: "Spring \u2014 Year 3",
    7: "Fall \u2014 Year 4",   8: "Spring \u2014 Year 4",
}

# ─────────────────────────── Data loading ────────────────────────────────────

def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_programs(programs_dir: Path = None) -> dict:
    d = programs_dir or PROGRAMS_DIR
    programs = {}
    if not d.exists():
        return programs
    for fp in sorted(d.glob("*.json")):
        try:
            data = _load_json(fp)
            programs[data["id"]] = data
        except Exception as exc:
            print(f"Warning: could not load {fp.name}: {exc}")
    return programs


def load_ge(data_dir: Path = None) -> dict:
    return _load_json((data_dir or DATA_DIR) / "ge_2025.json")


def load_dac(data_dir: Path = None) -> set:
    data = _load_json((data_dir or DATA_DIR) / "dac_2025.json")
    return set(data.get("courses", []))


def load_we(data_dir: Path = None) -> set:
    data = _load_json((data_dir or DATA_DIR) / "we_courses.json")
    we = set(data.get("courses", []))
    # Also include courses marked WE in the catalog
    catalog = load_catalog(data_dir)
    for pfx_data in (catalog.get("prefixes") or {}).values():
        for code, info in (pfx_data.get("courses") or {}).items():
            if info.get("we"):
                we.add(code)
    return we


def load_course_credits(data_dir: Path = None) -> dict:
    path = (data_dir or DATA_DIR) / "course_credits.json"
    if not path.exists():
        return {}
    data = _load_json(path)
    return {normalize(k): v for k, v in data.get("overrides", {}).items()}


def load_pathways(data_dir: Path = None) -> dict:
    pathway_dir = (data_dir or DATA_DIR) / "pathways"
    pathways = {}
    if not pathway_dir.exists():
        return pathways
    for fp in sorted(pathway_dir.glob("*.json")):
        try:
            data = _load_json(fp)
            pathways[data["id"]] = data
        except Exception as exc:
            print(f"Warning: could not load pathway {fp.name}: {exc}")
    return pathways


def load_first_two_years(data_dir: Path = None) -> list:
    path = (data_dir or DATA_DIR) / "first_two_years.json"
    if not path.exists():
        return []
    try:
        data = _load_json(path)
        return data.get("entries", [])
    except Exception as exc:
        print(f"Warning: could not load first_two_years.json: {exc}")
        return []


def load_catalog(data_dir: Path = None) -> dict:
    path = (data_dir or DATA_DIR) / "courses_catalog_2025.json"
    if not path.exists():
        return {}
    try:
        return _load_json(path)
    except Exception as exc:
        print(f"Warning: could not load courses_catalog_2025.json: {exc}")
        return {}


def load_offerings(data_dir: Path = None) -> dict:
    path = (data_dir or DATA_DIR) / "offerings_2026.json"
    if not path.exists():
        return {}
    try:
        return _load_json(path)
    except Exception as exc:
        print(f"Warning: could not load offerings_2026.json: {exc}")
        return {}


def load_intake(data_dir: Path = None) -> dict:
    intake_dir = (data_dir or DATA_DIR) / "intake"
    intake = {}
    if not intake_dir.exists():
        return intake
    for fp in sorted(intake_dir.glob("*.json")):
        try:
            data = _load_json(fp)
            intake[data["program_id"]] = data
        except Exception as exc:
            print(f"Warning: could not load intake {fp.name}: {exc}")
    return intake

# ─────────────────────────── Course utilities ────────────────────────────────

def normalize(code: str) -> str:
    code = code.strip().upper().replace(" ", "")
    m = re.match(r'^([A-Z]+)-?(\d+[A-Z]*)$', code)
    return f"{m.group(1)}-{m.group(2)}" if m else code


_MATH_PREFIXES    = {"MTH", "STA", "MAT"}
_SCIENCE_PREFIXES = {"BIO", "CHM", "PHY", "ESC", "ENS", "GEO"}


def is_math_course(code: str) -> bool:
    return (code.split("-")[0] if "-" in code else code) in _MATH_PREFIXES


def is_science_course(code: str) -> bool:
    return (code.split("-")[0] if "-" in code else code) in _SCIENCE_PREFIXES


def parse_courses(text: str) -> list:
    seen, result = set(), []

    def add(code: str):
        n = normalize(code)
        if n and n not in seen:
            seen.add(n)
            result.append(n)

    for raw_line in re.split(r'[\n,;]+', text):
        raw_line = raw_line.strip()
        if not raw_line or raw_line.startswith('#'):
            continue
        slash_m = re.match(r'^([A-Z]+-?)(\d+)/(\d+[A-Z]*)$',
                           raw_line.upper().replace(" ", ""))
        if slash_m:
            pfx = slash_m.group(1).rstrip('-')
            add(f"{pfx}-{slash_m.group(2)}")
            add(f"{pfx}-{slash_m.group(3)}")
            continue
        tokens = raw_line.split()
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if (i + 1 < len(tokens)
                    and re.match(r'^[A-Za-z]+$', tok)
                    and re.match(r'^\d+[A-Za-z]*$', tokens[i + 1])):
                add(f"{tok}-{tokens[i + 1]}")
                i += 2
            else:
                add(tok)
                i += 1
    return result


def prefix_of(code: str) -> str:
    m = re.match(r'^([A-Z]+)-', code)
    return m.group(1) if m else ""


def level_of(code: str) -> int:
    m = re.match(r'^[A-Z]+-(\d)', code)
    return int(m.group(1)) * 100 if m else 0


def is_lab(code: str) -> bool:
    return bool(re.match(r'^[A-Z]+-\d+L$', code))


def is_clinical(code: str) -> bool:
    return bool(re.match(r'^[A-Z]+-\d+C$', code))


def is_auxiliary(code: str) -> bool:
    return is_lab(code) or is_clinical(code)


def credit_of(code: str, overrides: dict = None) -> float:
    if overrides and code in overrides:
        return overrides[code]
    if is_auxiliary(code):
        return 0.2
    return 1.0


def total_credits(taken: set, overrides: dict = None) -> float:
    return sum(credit_of(c, overrides) for c in taken)

# ─────────────────────────── Requirement checker ─────────────────────────────

def _codes_satisfied(codes: list, taken: set) -> tuple:
    norm = [normalize(c) for c in codes]
    primary = [c for c in norm if not is_auxiliary(c)]
    found = [c for c in norm if c in taken]
    sat = bool(primary and any(c in taken for c in primary)) or (not primary and bool(found))
    return sat, found


def check_section(section: dict, taken: set) -> dict:
    stype = section.get("type", "all")

    if stype == "non_course":
        return {**section, "status": MANUAL,
                "message": section.get("description", "Mark manually")}

    if stype == "all":
        items, all_ok = [], True
        for item in section.get("items", []):
            sat, found = _codes_satisfied(item.get("codes", []), taken)
            if not sat:
                all_ok = False
            items.append({**item, "satisfied": sat, "found": found})
        return {**section, "items": items,
                "status": COMPLETE if all_ok else INCOMPLETE}

    if stype == "choose_one":
        opts, any_ok = [], False
        for opt in section.get("options", []):
            codes = opt.get("codes", [])
            norm = [normalize(c) for c in codes]
            primary = [c for c in norm if not is_auxiliary(c)]
            sat = (all(c in taken for c in primary) if primary
                   else bool(norm and any(c in taken for c in norm)))
            if sat:
                any_ok = True
            opts.append({**opt, "satisfied": sat})
        return {**section, "options": opts,
                "status": COMPLETE if any_ok else INCOMPLETE}

    if stype == "choose_n":
        n, count, items = section.get("n", 1), 0, []
        for item in section.get("items", []):
            sat, found = _codes_satisfied(item.get("codes", []), taken)
            if sat:
                count += 1
            items.append({**item, "satisfied": sat, "found": found})
        status = COMPLETE if count >= n else (PARTIAL if count > 0 else INCOMPLETE)
        return {**section, "items": items, "satisfied_count": count,
                "status": status, "message": f"{count}/{n} selected"}

    if stype == "open_n":
        n = section.get("n", 1)
        c = section.get("constraints", {})
        pfxs = set(c.get("prefixes", []))
        excl = {normalize(x) for x in c.get("exclude_codes", [])}
        min_lvl = c.get("min_level", 0)
        min_cnt = c.get("min_level_count", 0)
        level_is_floor = min_lvl and (not min_cnt or min_cnt >= n)
        matching = [x for x in taken
                    if not is_auxiliary(x)
                    and (not pfxs or prefix_of(x) in pfxs)
                    and x not in excl
                    and (not level_is_floor or level_of(x) >= min_lvl)]
        above = sum(1 for x in matching if level_of(x) >= min_lvl) if min_lvl else len(matching)
        level_ok = (above >= min_cnt) if min_cnt else True
        status = (COMPLETE if len(matching) >= n and level_ok
                  else PARTIAL if matching
                  else INCOMPLETE)
        parts = [f"{len(matching)}/{n} electives"]
        if min_cnt:
            parts.append(f"{above}/{min_cnt} at {min_lvl}+ level")
        return {**section, "matching": matching, "above_level": above,
                "status": status, "message": "; ".join(parts)}

    return {**section, "status": INCOMPLETE, "message": "Unknown section type"}


def check_program(program: dict, taken: set) -> dict:
    sections = [check_section(s, taken) for s in program.get("sections", [])]
    countable = [s for s in sections if s["status"] != MANUAL]
    done = sum(1 for s in countable if s["status"] == COMPLETE)
    return {"program": program, "sections": sections,
            "total": len(countable), "complete": done,
            "_taken": taken}


def check_ge(ge: dict, taken: set, dac: set, we: set,
             manual=None) -> dict:
    if manual is None:
        manual = {}
    div = ge["divisional"]["sections"]

    def div_courses(pfxs: list, max_per: int = 2) -> list:
        by_pfx: dict = {}
        for c in sorted(taken):
            if is_auxiliary(c):
                continue
            p = prefix_of(c)
            if p in set(pfxs):
                by_pfx.setdefault(p, []).append(c)
        result = []
        for p in sorted(by_pfx):
            result.extend(by_pfx[p][:max_per])
        return result

    fa  = div_courses(div["fine_arts"]["prefixes"])
    hum = div_courses(div["humanities"]["prefixes"])
    ns  = div_courses(div["nat_sci_math"]["prefixes"])
    ss  = div_courses(div["social_sciences"]["prefixes"])

    lab_pairs = []
    for c in taken:
        if is_lab(c):
            lecture = re.sub(r'L$', '', c)
            if lecture in taken:
                lab_pairs.append((lecture, c))

    we_found  = sorted(c for c in taken
                       if c in we or c.endswith("W") or c.endswith("WE")
                       or prefix_of(c) in ("FYS", "FS"))
    dac_found = sorted(c for c in taken if c in dac and not is_auxiliary(c))
    fys_found = [c for c in taken if prefix_of(c) == "FYS"
                 or c in ("FS-110", "FS-111", "FS-112")]
    prx_found = [c for c in taken if prefix_of(c) in ("PRX",)]

    fys_done  = len(fys_found) >= 1 or manual.get("fys", False)
    prx_done  = len(prx_found) >= 1 or manual.get("practicum", False)

    return {
        "fine_arts":      {"label": "Fine Arts (\u22652 credits)",      "required": 2, "courses": fa,
                           "complete": len(fa) >= 2,
                           "prefixes": div["fine_arts"]["prefixes"]},
        "humanities":     {"label": "Humanities (\u22652 credits)",     "required": 2, "courses": hum,
                           "complete": len(hum) >= 2,
                           "prefixes": div["humanities"]["prefixes"]},
        "nat_sci_math":   {"label": "Nat. Sci. & Math (\u22651 credit)","required": 1, "courses": ns[:1],
                           "complete": len(ns) >= 1,
                           "prefixes": div["nat_sci_math"]["prefixes"]},
        "lab_science":    {"label": "Lab Science (\u22651 lecture+lab)","required": 1,
                           "pairs": lab_pairs[:1], "complete": len(lab_pairs) >= 1},
        "social_sciences":{"label": "Social Sciences (\u22652 credits)","required": 2, "courses": ss,
                           "complete": len(ss) >= 2,
                           "prefixes": div["social_sciences"]["prefixes"]},
        "fys":            {"label": "First Year Seminar (1)",       "required": 1,
                           "courses": fys_found, "complete": fys_done,
                           "manual_key": "fys",
                           "note": "Enter FYS-### course code or check the box below"},
        "we":             {"label": "Writing Emphasis (5 courses)", "required": 5,
                           "courses": we_found, "complete": len(we_found) >= 5,
                           "note": "Auto-detected by W/WE suffix (e.g. ENG-110W) or WE course list"},
        "dac":            {"label": "Diversity Across Curriculum (2)","required": 2,
                           "courses": dac_found[:2], "complete": len(dac_found) >= 2},
        "practicum":      {"label": "Practicum (1)",                "required": 1,
                           "courses": prx_found, "complete": prx_done,
                           "manual_key": "practicum",
                           "note": "Mark manually or enter PRX course code"},
    }

# ─────────────────────────── Trajectory data ─────────────────────────────────

class TrajectoryData:
    SUGGESTION_THRESHOLD = 0.15

    def __init__(self, path: Path):
        self._by_major: dict = {}
        self._load(path)

    def _load(self, path: Path):
        if not path.exists():
            return
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                major = row.get("major", "").strip()
                raw   = row.get("course", "").strip()
                code  = normalize(raw)
                if not major or not code:
                    continue
                try:
                    pct  = float(row.get("pct_took", 0) or 0)
                    sem  = round(float(row.get("typical_semester", 0) or 0))
                    raw_g = row.get("mean_grade", "").strip()
                    grade = float(raw_g) if raw_g and raw_g != "NA" else None
                except ValueError:
                    pct, sem, grade = 0.0, 0, None
                self._by_major.setdefault(major, {})[code] = {
                    "tier":  row.get("course_tier", "elective"),
                    "sem":   sem if sem > 0 else None,
                    "grade": grade,
                    "pct":   pct,
                }

    def course_info(self, major_code: str, course_code: str):
        return self._by_major.get(major_code, {}).get(normalize(course_code))

    def elective_suggestions(self, major_code: str,
                             exclude: set, n: int = 12) -> list:
        rows = []
        for code, info in self._by_major.get(major_code, {}).items():
            if code in exclude:
                continue
            if info["tier"] in ("elective", "common") and info["pct"] >= self.SUGGESTION_THRESHOLD:
                rows.append((code, info))
        rows.sort(key=lambda x: x[1]["pct"], reverse=True)
        return rows[:n]

    def as_dict(self) -> dict:
        """Return raw data for serialization (used by bundle_web_data)."""
        return self._by_major
