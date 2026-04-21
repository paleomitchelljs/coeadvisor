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
        # Hard floor: no course below this level may count, ever.
        # Distinct from min_level, which is a threshold used with min_level_count.
        # Back-compat: if min_level is set and min_level_count implies all-must-be-above,
        # treat min_level itself as the floor.
        floor_lvl = c.get("floor_level", 0)
        if not floor_lvl and min_lvl and (not min_cnt or min_cnt >= n):
            floor_lvl = min_lvl
        matching = [x for x in taken
                    if not is_auxiliary(x)
                    and (not pfxs or prefix_of(x) in pfxs)
                    and x not in excl
                    and (not floor_lvl or level_of(x) >= floor_lvl)]
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


# ─────────────────────────── First-semester recommender ─────────────────────
#
# Produces a recommended first-semester course list from four inputs:
#   interest_major_codes: list of major_codes (e.g. ["BIO", "PSY"]) or []/"EXPLORATORY"
#   prep_level:           "well" | "typical" | "under"
#   premed:               bool
#   certainty:            "exploring" | "leaning" | "committed"
#
# Rules are grounded in new_student_considerations/advisor_brief_fall_registration.md:
#   - Hard-landing courses carry outsized retention risk when failed in-aligned.
#   - MTH-135 + another hard-landing course together compound risk.
#   - Under-prepared students benefit from schedule diversity (≤2 in-dept).
#   - Declared EDU / PHY / EP / BCM interests need stricter triage on aligned fails.

FIRST_YEAR_SEMINAR = "FS-110"

HARD_LANDING_COURSES = {"BIO-145", "MTH-135", "CS-125", "PHY-185", "CHM-121"}

# Majors whose aligned-fail penalty materially exceeds the pooled mean.
STRICT_MONITORING_MAJORS = {"EDU", "PHY", "EP", "BCM"}

# Which major_code(s) make which hard-landing course "aligned".
ALIGNMENT_MAP = {
    "BIO-145": {"BIO", "BCM", "NEURO"},
    "MTH-135": {"MTH", "CS", "PHY", "EP", "DS"},
    "CS-125":  {"CS", "DS"},
    "PHY-185": {"PHY", "EP", "CHM", "BCM"},
    "CHM-121": {"CHM", "BCM", "BIO", "PHY", "EP"},
}

# Quantitative majors for whom MTH-135 belongs in fall if prep is strong.
QUANT_MAJORS = {"MTH", "CS", "PHY", "EP", "BCM", "CHM", "DS"}


def _pick_f2y_entry(major_code: str, premed: bool, prep: str,
                    entries: list) -> dict:
    """Select the first-two-years entry that best matches inputs.

    Prefers pathway-conditional entries when the pathway applies, and
    intake_only variants (e.g. biology_typical) when prep is not strong.
    """
    if not major_code:
        return {}
    candidates = [e for e in entries
                  if major_code in (e.get("match_major_codes") or [])]
    if not candidates:
        return {}

    def score(e):
        s = 0
        cond = e.get("conditions") or {}
        pathways = cond.get("pathways") or []
        if premed and "premed" in pathways:
            s += 100
        if cond.get("intake_only") and prep in ("typical", "under"):
            s += 50
        if not cond and prep == "well":
            s += 30
        if e.get("default"):
            s += 5
        return s

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def _is_aligned(course: str, major_code: str, premed: bool) -> bool:
    course = normalize(course)
    majors = ALIGNMENT_MAP.get(course, set())
    if major_code in majors:
        return True
    if premed and course in ("BIO-145", "CHM-121"):
        return True
    return False


def _normalize_major_codes(major_codes) -> list:
    """Accept a string, list, or None; return a de-duped list of uppercase codes
    with EXPLORATORY dropped if any real major is present."""
    if major_codes is None:
        return []
    if isinstance(major_codes, str):
        major_codes = [major_codes]
    seen = []
    for c in major_codes:
        if not c:
            continue
        cu = c.upper()
        if cu not in seen:
            seen.append(cu)
    real = [c for c in seen if c != "EXPLORATORY"]
    return real if real else seen


def recommend_first_semester(major_codes, prep_level: str, premed: bool,
                              first_two_years: list,
                              certainty: str = "committed") -> dict:
    """Return {courses, notes, monitor_flags, stacking_note} for first fall.

    `major_codes` may be a single code, a list, or empty/"EXPLORATORY". When
    multiple real codes are given, the plan keeps gateway courses for each
    interest. `certainty` of "exploring" or "leaning" softens lock-in; only
    "committed" allows the well-prepped "suggested" extras.
    """
    codes = _normalize_major_codes(major_codes)
    is_exploratory = not codes or codes == ["EXPLORATORY"]
    prep_level = (prep_level or "typical").lower()
    certainty = (certainty or "committed").lower()
    notes: list = []
    flags: list = []
    stacking_note = ""

    # Exploratory path: breadth-forward default.
    if is_exploratory:
        courses = [FIRST_YEAR_SEMINAR, "MTH-100 or STA-100",
                   "Writing-emphasis humanities (WE)", "Breadth natural science"]
        if prep_level == "under":
            notes.append("Under-prepared: lean on foundational 100-level courses "
                         "and maximize disciplinary diversity.")
        elif prep_level == "well":
            notes.append("Well-prepared: consider a 200-level course in a plausible "
                         "major area as a probe.")
        return {"courses": courses, "notes": notes,
                "monitor_flags": flags, "stacking_note": stacking_note}

    # Primary major drives alignment/stacking rules; others contribute gateways.
    primary = codes[0]
    multi = len(codes) > 1

    # Collect essentials; fall back to suggested if a major has no essentials;
    # include all suggested when single + well + committed.
    courses: list = []
    for mc in codes:
        entry = _pick_f2y_entry(mc, premed, prep_level, first_two_years)
        y1f = ((entry.get("semesters") or {}).get("y1_fall") or {})
        ess = list(y1f.get("essential") or [])
        sug = list(y1f.get("suggested") or [])
        for c in ess:
            if c not in courses:
                courses.append(c)
        if not ess:
            for c in sug:
                if c not in courses:
                    courses.append(c)
        elif not multi and prep_level == "well" and certainty == "committed":
            for c in sug:
                if c not in courses:
                    courses.append(c)

    if multi:
        notes.append("Plan covers gateway courses for "
                     + ", ".join(codes) + " to keep all interests open.")

    # (a) BIO-155 → BIO-100 unless prep=well.
    if prep_level != "well":
        replaced = []
        swapped = False
        for c in courses:
            cn = normalize(c)
            if cn == "BIO-155":
                replaced.append("BIO-100")
                swapped = True
            elif cn == "BIO-155L":
                continue
            else:
                replaced.append(c)
        if swapped:
            notes.append("Swapped BIO-155 for BIO-100 given prep level.")
        courses = replaced

    # (b) MTH-135 only if quant major AND prep=well AND committed.
    if any(normalize(c) == "MTH-135" for c in courses):
        quant = any(mc in QUANT_MAJORS for mc in codes)
        if not (prep_level == "well" and quant and certainty == "committed"):
            courses = [c for c in courses if normalize(c) != "MTH-135"]
            if quant:
                courses.append("MTH-130 or STA-100 (Calc prep)")
                notes.append("Deferred MTH-135 — rebuild calc readiness in fall, "
                             "start 135 spring.")
            else:
                notes.append("MTH-135 removed: not required in fall for this interest.")

    # (c) BIO + CHM together in fall reserved for pre-med timing.
    has_bio = any(normalize(c).startswith("BIO-1") for c in courses)
    has_chm = any(normalize(c).startswith("CHM-121") for c in courses)
    if has_bio and has_chm and not premed:
        courses = [c for c in courses if not normalize(c).startswith("CHM-121")]
        notes.append("Dropped CHM-121 — pair with BIO in fall only for pre-med timing.")

    # (d) Certainty: exploring/leaning trims to a single aligned hard-landing
    # course and adds a breadth placeholder.
    if certainty in ("exploring", "leaning"):
        hard_in_plan = [c for c in courses if normalize(c) in HARD_LANDING_COURSES]
        if len(hard_in_plan) >= 2:
            aligned = [c for c in hard_in_plan if _is_aligned(c, primary, premed)]
            keep = aligned[0] if aligned else hard_in_plan[0]
            moved = [c for c in hard_in_plan if c != keep]
            for c in moved:
                if c in courses:
                    courses.remove(c)
                    lab = c + "L"
                    if lab in courses:
                        courses.remove(lab)
            stacking_note = (("Exploring" if certainty == "exploring" else "Leaning")
                             + ": held back " + ", ".join(moved)
                             + " to keep pivot options open.")
        if certainty == "exploring" and len(courses) < 4:
            if not any("breadth" in str(c).lower() or "WE" in str(c)
                       for c in courses):
                courses.append("Breadth / GE course")

    # Always-on stacking safety: ≥2 hard-landing courses still → unstack.
    hard_in_plan = [c for c in courses if normalize(c) in HARD_LANDING_COURSES]
    if len(hard_in_plan) >= 2 and not stacking_note:
        aligned = [c for c in hard_in_plan if _is_aligned(c, primary, premed)]
        keep = aligned[0] if aligned else hard_in_plan[0]
        moved = [c for c in hard_in_plan if c != keep]
        for c in moved:
            if c in courses:
                courses.remove(c)
                lab = c + "L"
                if lab in courses:
                    courses.remove(lab)
        stacking_note = ("Unstacked: moved " + ", ".join(moved)
                         + " to a later term to avoid compound hard-landing risk in fall.")

    # First-Year Seminar is required for every first-semester student.
    if not any(normalize(c) == FIRST_YEAR_SEMINAR for c in courses):
        courses.insert(0, FIRST_YEAR_SEMINAR)

    # Diversity.
    def _dept(c): return prefix_of(normalize(c))
    depts = [_dept(c) for c in courses if _dept(c)]
    unique_depts = set(depts)
    if len(unique_depts) <= 1 and courses:
        notes.append("Add at least one breadth course outside the interest area.")
    if prep_level == "under":
        from collections import Counter
        mode_count = max(Counter(depts).values()) if depts else 0
        if mode_count >= 3:
            notes.append("Under-prepared: reduce in-department load to ≤2 courses "
                         "and add breadth.")

    # Midterm monitoring flags for aligned hard-landing courses.
    for c in courses:
        if normalize(c) not in HARD_LANDING_COURSES:
            continue
        aligned_to = next((mc for mc in codes
                           if _is_aligned(c, mc, premed)), None)
        if not aligned_to and not (premed and normalize(c) in ("BIO-145", "CHM-121")):
            continue
        strict = aligned_to in STRICT_MONITORING_MAJORS
        flags.append({
            "course": normalize(c),
            "strict": strict,
            "message": (f"Priority midterm-F monitoring in {normalize(c)}. "
                        + ("Declared {} interest: aligned-fail retention penalty "
                           "is materially above the pooled mean — treat an F at "
                           "midterm as the sharpest single triage signal.".format(aligned_to)
                           if strict else
                           "An F at midterm is the retention triage threshold "
                           "(D recovers at ~45% to C-or-better)."))
        })

    return {"courses": courses, "notes": notes,
            "monitor_flags": flags, "stacking_note": stacking_note}
