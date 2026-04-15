#!/usr/bin/env python3
"""
Coe College Academic Advising Tool
====================================
Tracks student progress toward graduation across multiple majors/minors
and GE requirements.

Usage:  python advisor.py
"""

import csv
import json
import os
import re
import sys
import tkinter as tk
from tkinter import messagebox, filedialog
from pathlib import Path
from datetime import datetime

import customtkinter as ctk

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# ─────────────────────────── Paths ───────────────────────────────────────────

def _base_dir() -> Path:
    """Return the directory that contains the 'data/' folder.

    When running as a PyInstaller bundle (frozen), sys._MEIPASS holds the
    temp directory where the bundle was extracted.  Otherwise use the real
    script location.
    """
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

# ─────────────────────────── Data loading ────────────────────────────────────

def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_programs() -> dict:
    """Return {program_id: program_dict} for every file in programs/."""
    programs = {}
    if not PROGRAMS_DIR.exists():
        return programs
    for fp in sorted(PROGRAMS_DIR.glob("*.json")):
        try:
            data = _load_json(fp)
            programs[data["id"]] = data
        except Exception as exc:
            print(f"Warning: could not load {fp.name}: {exc}")
    return programs


def load_ge() -> dict:
    return _load_json(DATA_DIR / "ge_2025.json")


def load_dac() -> set:
    data = _load_json(DATA_DIR / "dac_2025.json")
    return set(data.get("courses", []))


def load_we() -> set:
    data = _load_json(DATA_DIR / "we_courses.json")
    return set(data.get("courses", []))


def load_course_credits() -> dict:
    """Return {course_code: credit_value} for partial-credit overrides."""
    path = DATA_DIR / "course_credits.json"
    if not path.exists():
        return {}
    data = _load_json(path)
    return {normalize(k): v for k, v in data.get("overrides", {}).items()}


def load_pathways() -> dict:
    """Return {pathway_id: pathway_dict} for every file in data/pathways/."""
    pathways = {}
    pathway_dir = DATA_DIR / "pathways"
    if not pathway_dir.exists():
        return pathways
    for fp in sorted(pathway_dir.glob("*.json")):
        try:
            data = _load_json(fp)
            pathways[data["id"]] = data
        except Exception as exc:
            print(f"Warning: could not load pathway {fp.name}: {exc}")
    return pathways


def load_first_two_years() -> list:
    """Return list of first-two-years entries from data/first_two_years.json."""
    path = DATA_DIR / "first_two_years.json"
    if not path.exists():
        return []
    try:
        data = _load_json(path)
        return data.get("entries", [])
    except Exception as exc:
        print(f"Warning: could not load first_two_years.json: {exc}")
        return []


def load_intake() -> dict:
    """Return {program_id: intake_dict} for every file in data/intake/.

    Each file defines 'questions' (yes/no prompts) and 'routes' (answer → first-
    semester recommendations).  Drop a new JSON file into data/intake/ to enable
    the wizard for another program — no code changes required.
    """
    intake = {}
    intake_dir = DATA_DIR / "intake"
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
    """Normalize a course code to PREFIX-NUMBER format."""
    code = code.strip().upper().replace(" ", "")
    m = re.match(r'^([A-Z]+)-?(\d+[A-Z]*)$', code)
    return f"{m.group(1)}-{m.group(2)}" if m else code


_MATH_PREFIXES    = {"MTH", "STA", "MAT"}
_SCIENCE_PREFIXES = {"BIO", "CHM", "PHY", "ESC", "ENS", "GEO"}

def is_math_course(code: str) -> bool:
    """Return True if the normalized course code is a math/stats course."""
    return (code.split("-")[0] if "-" in code else code) in _MATH_PREFIXES

def is_science_course(code: str) -> bool:
    """Return True if the normalized course code is a lab-science course."""
    return (code.split("-")[0] if "-" in code else code) in _SCIENCE_PREFIXES


def parse_courses(text: str) -> list:
    """
    Parse courses from free-form text.
    Accepts one-per-line or comma/semicolon-separated.
    Handles 'BIO-145/145L' shorthand by expanding to two codes.
    Lines starting with # are treated as comments.
    """
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

        # Handle "PREFIX-NUM/NUMSFX" → two codes, e.g. BIO-145/145L
        slash_m = re.match(r'^([A-Z]+-?)(\d+)/(\d+[A-Z]*)$',
                           raw_line.upper().replace(" ", ""))
        if slash_m:
            pfx = slash_m.group(1).rstrip('-')
            add(f"{pfx}-{slash_m.group(2)}")
            add(f"{pfx}-{slash_m.group(3)}")
        else:
            add(raw_line)

    return result


def prefix_of(code: str) -> str:
    m = re.match(r'^([A-Z]+)-', code)
    return m.group(1) if m else ""


def level_of(code: str) -> int:
    """Return the hundred-level (100, 200, …) of a course, or 0."""
    m = re.match(r'^[A-Z]+-(\d)', code)
    return int(m.group(1)) * 100 if m else 0


def is_lab(code: str) -> bool:
    return bool(re.match(r'^[A-Z]+-\d+L$', code))


def is_clinical(code: str) -> bool:
    return bool(re.match(r'^[A-Z]+-\d+C$', code))


def is_auxiliary(code: str) -> bool:
    """Lab or clinical section — not a stand-alone lecture credit."""
    return is_lab(code) or is_clinical(code)


def credit_of(code: str, overrides: dict = None) -> float:
    """Return the credit value for a single course code.

    Rules (in priority order):
      1. Explicit override in course_credits.json → use that value
      2. -L suffix (lab) or -C suffix (clinical) → 0.2
      3. Everything else → 1.0
    """
    if overrides and code in overrides:
        return overrides[code]
    if is_auxiliary(code):
        return 0.2
    return 1.0


def total_credits(taken: set, overrides: dict = None) -> float:
    """Return the sum of credit values for all courses in taken."""
    return sum(credit_of(c, overrides) for c in taken)

# ─────────────────────────── Requirement checker ─────────────────────────────

def _codes_satisfied(codes: list, taken: set) -> tuple:
    """
    Return (satisfied: bool, found: list).
    A requirement with codes like ["BIO-145","BIO-145L"] is satisfied when
    the primary (non-lab, non-clinical) code is present.
    """
    norm = [normalize(c) for c in codes]
    primary = [c for c in norm if not is_auxiliary(c)]
    found = [c for c in norm if c in taken]
    # Any non-auxiliary code in taken satisfies (handles cross-listed courses)
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
            codes = [normalize(c) for c in opt.get("codes", [])]
            sat = all(c in taken for c in codes) if codes else False
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

        matching = [x for x in taken
                    if not is_auxiliary(x)
                    and (not pfxs or prefix_of(x) in pfxs)
                    and x not in excl]
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
    """Check all GE requirements. manual is {key: bool} for non-course items."""
    if manual is None:
        manual = {}
    div = ge["divisional"]["sections"]

    def div_courses(pfxs: list, max_per: int = 2) -> list:
        by_pfx: dict = {}
        for c in taken:
            if is_auxiliary(c):
                continue
            p = prefix_of(c)
            if p in set(pfxs):
                by_pfx.setdefault(p, []).append(c)
        result = []
        for lst in by_pfx.values():
            result.extend(lst[:max_per])
        return result

    fa  = div_courses(div["fine_arts"]["prefixes"])
    hum = div_courses(div["humanities"]["prefixes"])
    ns  = div_courses(div["nat_sci_math"]["prefixes"])
    ss  = div_courses(div["social_sciences"]["prefixes"])

    # Lab science: need a lecture + its L-suffix counterpart both in taken
    lab_pairs = []
    for c in taken:
        if is_lab(c):
            lecture = re.sub(r'L$', '', c)
            if lecture in taken:
                lab_pairs.append((lecture, c))

    we_found  = sorted(c for c in taken
                       if not is_auxiliary(c)
                       and (c in we or c.endswith("W") or c.endswith("WE")))
    dac_found = sorted(c for c in taken if c in dac and not is_auxiliary(c))
    # FYS: accept both the legacy FYS-### prefix and Coe's current FS-110 code
    fys_found = [c for c in taken if prefix_of(c) == "FYS"
                 or c in ("FS-110", "FS-111", "FS-112")]
    prx_found = [c for c in taken if prefix_of(c) in ("PRX",)]

    fys_done  = len(fys_found) >= 1 or manual.get("fys", False)
    prx_done  = len(prx_found) >= 1 or manual.get("practicum", False)

    return {
        "fine_arts":      {"label": "Fine Arts (≥2 credits)",      "required": 2, "courses": fa,
                           "complete": len(fa) >= 2,
                           "prefixes": div["fine_arts"]["prefixes"]},
        "humanities":     {"label": "Humanities (≥2 credits)",     "required": 2, "courses": hum,
                           "complete": len(hum) >= 2,
                           "prefixes": div["humanities"]["prefixes"]},
        "nat_sci_math":   {"label": "Nat. Sci. & Math (≥1 credit)","required": 1, "courses": ns[:1],
                           "complete": len(ns) >= 1,
                           "prefixes": div["nat_sci_math"]["prefixes"]},
        "lab_science":    {"label": "Lab Science (≥1 lecture+lab)","required": 1,
                           "pairs": lab_pairs[:1], "complete": len(lab_pairs) >= 1},
        "social_sciences":{"label": "Social Sciences (≥2 credits)","required": 2, "courses": ss,
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
    """
    Loads student trajectory data from major_course_summary.csv.
    Provides per-course timing/grade hints and common-elective suggestions.
    """

    # Minimum fraction of graduates who took a course for it to appear as a suggestion
    SUGGESTION_THRESHOLD = 0.15

    def __init__(self, path: Path):
        self._by_major: dict = {}   # {major_code: {course_code: info_dict}}
        self._load(path)

    def _load(self, path: Path):
        if not path.exists():
            return
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                major = row.get("major", "").strip()
                raw   = row.get("course", "").strip()
                code  = normalize(raw)           # handles "BIO 145" → "BIO-145"
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
        """Return info dict for one course, or None."""
        return self._by_major.get(major_code, {}).get(normalize(course_code))

    def elective_suggestions(self, major_code: str,
                             exclude: set, n: int = 12) -> list:
        """
        Return up to n (code, info) pairs for courses commonly taken by
        students in major_code that are not already in exclude.
        Sorted by pct descending; only tiers elective/common and above threshold.
        """
        rows = []
        for code, info in self._by_major.get(major_code, {}).items():
            if code in exclude:
                continue
            if info["tier"] in ("elective", "common") and info["pct"] >= self.SUGGESTION_THRESHOLD:
                rows.append((code, info))
        rows.sort(key=lambda x: x[1]["pct"], reverse=True)
        return rows[:n]


# ─────────────────────────── GUI ─────────────────────────────────────────────

COLORS = {
    # Status / semantic
    "complete":   "#15803d",   # green-700
    "partial":    "#b45309",   # amber-700
    "incomplete": "#b91c1c",   # red-700
    "manual":     "#1d4ed8",   # blue-700
    # Typography
    "header":     "#1e293b",   # slate-800
    "hint":       "#94a3b8",   # slate-400
    "note":       "#64748b",   # slate-500
    # Layout
    "bg":         "#ffffff",   # card / content background
    "panel_bg":   "#eef1f5",   # page / scrollable background
    "border":     "#dde3ea",   # subtle dividers
    # Brand (Coe crimson + gold)
    "accent":     "#8b1a1a",
    "accent_dk":  "#6e1414",
    "gold":       "#c4991a",
}

GRADES = ["", "A", "A-", "B+", "B", "B-", "C+", "C", "C-",
          "D+", "D", "D-", "F", "P", "NP", "W", "IP"]

STUDENT_YEARS = ["First Year", "Sophomore", "Junior", "Senior", "Transfer Student"]


class AdvisorApp:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title("Coe College Academic Advising Tool")
        self.root.geometry("1080x740")
        self.root.minsize(800, 600)

        # ── Load data ──
        try:
            self.programs        = load_programs()
            self.ge_data         = load_ge()
            self.dac             = load_dac()
            self.we              = load_we()
            self.course_credits  = load_course_credits()
            self.pathways        = load_pathways()
            self.first_two_years = load_first_two_years()
            self.intake_data     = load_intake()
        except FileNotFoundError as e:
            messagebox.showerror("Data Error",
                f"Could not load data files.\n\nMissing: {e}\n\n"
                "Make sure the 'data/' folder is in the same directory as advisor.py.")
            root.destroy()
            return

        self.trajectory = TrajectoryData(
            DATA_DIR / "student_obs" / "major_course_summary.csv")

        # ── State ──
        self.manual_ge: dict[str, tk.BooleanVar] = {}
        self.pathway_vars: dict[str, tk.BooleanVar] = {}
        self._prog_ids: list[str] = []          # kept for legacy compat
        self._wizard_route_note: str = ""       # note from last intake route; shown in Suggested Plan
        self._comfort_math:      bool = True   # False → hide Y1 suggested math courses
        self._comfort_science:   bool = True   # False → hide Y1 suggested science courses

        # New structured-input state (set fully in _build_left)
        self._major_vars:    list = []          # 3 StringVars for major dropdowns
        self._minor_vars:    list = []          # 2 StringVars for minor dropdowns
        self._year_var:      tk.StringVar = None
        self._display_to_pid: dict = {}         # combined fallback (legacy)
        self._major_display_to_pid: dict = {}   # major/collateral only — avoids collision with same-named minors
        self._minor_display_to_pid: dict = {}   # minor only
        self._semesters:     list = []          # list of semester dicts
        self._courses_area:  tk.Frame = None    # frame semester sections pack into
        self._variant_vars:  dict = {}          # {program_id: StringVar} for F2Y track selection
        self._variant_container: tk.Frame = None
        self._variant_rows_frame: tk.Frame = None

        self._build_ui()

    # ──────────────────────────────────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────────────────────────────────


    def _build_ui(self):
        # ── Header bar ───────────────────────────────────────────────────────
        top = ctk.CTkFrame(self.root, fg_color=COLORS["accent"], height=54,
                           corner_radius=0)
        top.pack(fill=tk.X)
        top.pack_propagate(False)

        # Gold left accent stripe
        ctk.CTkFrame(top, fg_color=COLORS["gold"], width=6,
                     corner_radius=0).pack(side=tk.LEFT, fill=tk.Y)

        # Branding
        brand = ctk.CTkFrame(top, fg_color=COLORS["accent"], corner_radius=0)
        brand.pack(side=tk.LEFT, padx=14)
        ctk.CTkLabel(brand, text="Coe College",
                     fg_color="transparent", text_color="white",
                     font=("Helvetica", 14, "bold")).pack(anchor=tk.W)
        ctk.CTkLabel(brand, text="Academic Advising Tool",
                     fg_color="transparent", text_color="#e8b4b4",
                     font=("Helvetica", 8)).pack(anchor=tk.W)

        # Nav pills (right side)
        nav_f = ctk.CTkFrame(top, fg_color="transparent", corner_radius=0)
        nav_f.pack(side=tk.RIGHT, padx=16, pady=10)
        self._tab_btns = {}
        for key, label in [("setup", "Student Setup"),
                            ("results", "Check Requirements")]:
            btn = ctk.CTkButton(nav_f, text=label,
                                font=("Helvetica", 9),
                                fg_color=COLORS["accent"],
                                hover_color=COLORS["accent_dk"],
                                text_color="#e8b4b4",
                                corner_radius=6,
                                width=130, height=32,
                                command=lambda k=key: self._switch_page(k))
            btn.pack(side=tk.LEFT, padx=3)
            self._tab_btns[key] = btn

        # ── Page frames ──────────────────────────────────────────────────────
        self.page_wizard   = ctk.CTkFrame(self.root, fg_color=COLORS["panel_bg"],
                                          corner_radius=0)
        self.page_interest = ctk.CTkFrame(self.root, fg_color=COLORS["panel_bg"],
                                          corner_radius=0)
        self.page_intake   = ctk.CTkFrame(self.root, fg_color=COLORS["panel_bg"],
                                          corner_radius=0)
        self.page_setup    = ctk.CTkFrame(self.root, fg_color=COLORS["panel_bg"],
                                          corner_radius=0)
        self.page_results  = ctk.CTkFrame(self.root, fg_color=COLORS["panel_bg"],
                                          corner_radius=0)

        self._build_wizard_page(self.page_wizard)
        self._build_interest_page(self.page_interest)
        # page_intake is built dynamically in _build_intake_page()
        self._build_setup_page(self.page_setup)
        self._build_results_page(self.page_results)

        self._switch_page("wizard")

    def _switch_page(self, name: str):
        """Show one page, hide the rest, update nav pill styles."""
        pages = {
            "wizard":   self.page_wizard,
            "interest": self.page_interest,
            "intake":   self.page_intake,
            "setup":    self.page_setup,
            "results":  self.page_results,
        }
        for key, frame in pages.items():
            if key == name:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()
        # Nav pills: only "setup" / "results" are in the header; wizard pages dim both
        for key, btn in self._tab_btns.items():
            if key == name:
                btn.configure(fg_color="white", text_color=COLORS["accent"],
                              hover_color="#f0f0f0")
            else:
                btn.configure(fg_color=COLORS["accent"], text_color="#e8b4b4",
                              hover_color=COLORS["accent_dk"])

    # ──────────────────────────────────────────────────────────────────────────
    # Wizard pages
    # ──────────────────────────────────────────────────────────────────────────

    def _wizard_card(self, parent, width: int = 520) -> ctk.CTkFrame:
        """Return a centered white card frame with rounded corners."""
        outer = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        outer.place(relx=0.5, rely=0.5, anchor="center")
        card = ctk.CTkFrame(outer, fg_color=COLORS["bg"], corner_radius=10,
                            border_width=1, border_color=COLORS["border"],
                            width=width)
        card.pack()
        # Do NOT call pack_propagate(False) — that freezes height at the
        # CTkFrame default, clipping content below the first widget.
        return card

    def _build_wizard_page(self, parent):
        """Welcome screen: New Student or Returning Student."""
        card = self._wizard_card(parent, width=480)

        ctk.CTkLabel(card, text="Coe College Advising Tool",
                     fg_color="transparent", text_color=COLORS["accent"],
                     font=("Helvetica", 16, "bold")).pack(pady=(32, 4))
        ctk.CTkLabel(card, text="Is this a new student or a returning student?",
                     fg_color="transparent", text_color=COLORS["header"],
                     font=("Helvetica", 11)).pack(pady=(0, 24))

        ctk.CTkFrame(card, fg_color=COLORS["border"], height=1,
                     corner_radius=0).pack(fill=tk.X, padx=32, pady=(0, 20))

        def _big_btn(title, subtitle, command):
            btn_frame = ctk.CTkFrame(card, fg_color=COLORS["panel_bg"],
                                     corner_radius=8,
                                     border_width=1,
                                     border_color=COLORS["border"],
                                     cursor="hand2")
            btn_frame.pack(fill=tk.X, padx=32, pady=6)

            inner = ctk.CTkFrame(btn_frame, fg_color="transparent",
                                 corner_radius=0)
            inner.pack(fill=tk.X, padx=16, pady=12)

            ctk.CTkLabel(inner, text=title, fg_color="transparent",
                         text_color=COLORS["accent"],
                         font=("Helvetica", 11, "bold"),
                         anchor="w").pack(fill=tk.X)
            ctk.CTkLabel(inner, text=subtitle, fg_color="transparent",
                         text_color=COLORS["note"],
                         font=("Helvetica", 9),
                         anchor="w").pack(fill=tk.X)

            def _on_enter(e):
                btn_frame.configure(fg_color=COLORS["bg"],
                                    border_color=COLORS["accent"])
            def _on_leave(e):
                btn_frame.configure(fg_color=COLORS["panel_bg"],
                                    border_color=COLORS["border"])

            for w in (btn_frame, inner) + tuple(inner.winfo_children()):
                w.bind("<Button-1>", lambda e, c=command: c())
                w.bind("<Enter>", _on_enter)
                w.bind("<Leave>", _on_leave)

        _big_btn("New Student",
                 "Answer a few questions to build a first-semester plan.",
                 lambda: self._switch_page("interest"))
        _big_btn("Returning Student",
                 "Go directly to manual course entry and requirement checking.",
                 lambda: self._switch_page("setup"))

        ctk.CTkFrame(card, fg_color="transparent", height=24,
                     corner_radius=0).pack()

    def _build_interest_page(self, parent):
        """New-student area of interest page: select a major."""
        # Back link
        back_btn = ctk.CTkButton(parent, text="← Back",
                                 fg_color="transparent",
                                 hover_color=COLORS["panel_bg"],
                                 text_color=COLORS["accent"],
                                 font=("Helvetica", 9),
                                 width=70, height=28,
                                 command=lambda: self._switch_page("wizard"))
        back_btn.place(x=12, y=12)

        card = self._wizard_card(parent, width=480)

        ctk.CTkLabel(card, text="Area of Interest",
                     fg_color="transparent", text_color=COLORS["accent"],
                     font=("Helvetica", 16, "bold")).pack(pady=(32, 4))
        ctk.CTkLabel(card, text="Select this student's primary major of interest.",
                     fg_color="transparent", text_color=COLORS["header"],
                     font=("Helvetica", 10)).pack(pady=(0, 4))
        ctk.CTkLabel(card,
                     text="Majors marked  ★  have a guided first-semester setup.",
                     fg_color="transparent", text_color=COLORS["hint"],
                     font=("Helvetica", 8, "italic")).pack(pady=(0, 18))

        ctk.CTkFrame(card, fg_color=COLORS["border"], height=1,
                     corner_radius=0).pack(fill=tk.X, padx=32, pady=(0, 18))

        inner = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
        inner.pack(padx=32, fill=tk.X)

        # Build display list — programs with intake data get a ★ prefix
        major_progs = sorted(
            [(pid, p) for pid, p in self.programs.items()
             if p.get("program_type") in ("major", "collateral", "certificate")],
            key=lambda x: x[1].get("name", ""))

        def _disp(pid, p):
            yr   = p.get("catalog_year", "")
            star = "★ " if pid in self.intake_data else ""
            base = f"{p['name']} ({yr})" if yr else p["name"]
            return f"{star}{base}"

        self._interest_display_to_pid = {_disp(pid, p): pid for pid, p in major_progs}
        interest_names = ["(select a major)"] + list(self._interest_display_to_pid.keys())

        self._interest_var = tk.StringVar(value="(select a major)")
        ctk.CTkComboBox(inner, variable=self._interest_var,
                        values=interest_names, state="readonly",
                        width=416, height=36,
                        fg_color=COLORS["bg"],
                        border_color=COLORS["border"],
                        button_color=COLORS["accent"],
                        button_hover_color=COLORS["accent_dk"],
                        dropdown_fg_color=COLORS["bg"],
                        dropdown_hover_color=COLORS["panel_bg"],
                        text_color=COLORS["header"],
                        font=("Helvetica", 10)).pack(fill=tk.X, pady=(0, 20))

        ctk.CTkButton(inner,
                      text="Continue  →",
                      font=("Helvetica", 10, "bold"),
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_dk"],
                      text_color="white",
                      corner_radius=6,
                      height=38,
                      command=self._interest_continue).pack(anchor=tk.E, pady=(0, 28))

    def _interest_continue(self):
        """Handle Continue from the interest page."""
        disp = self._interest_var.get()
        pid  = self._interest_display_to_pid.get(disp)
        if not pid:
            return
        # Use a program-specific intake if one exists; fall back to the
        # universal default intake (comfort questions) if available.
        intake_key = pid if pid in self.intake_data else (
            "_default" if "_default" in self.intake_data else None)
        if intake_key:
            self._build_intake_page(pid, intake_key)
            self._switch_page("intake")
        else:
            # No intake data at all — pre-set major and go straight to setup
            if self._major_vars:
                display = self._pid_to_display.get(pid, "")
                if display:
                    self._major_vars[0].set(display)
            self._switch_page("setup")

    def _build_intake_page(self, pid: str, intake_key: str = None):
        """Dynamically build the intake-questions page for the given program."""
        for w in self.page_intake.winfo_children():
            w.destroy()

        intake = self.intake_data[intake_key or pid]
        prog   = self.programs.get(pid, {})

        # Back link
        back_btn = ctk.CTkButton(self.page_intake, text="← Back",
                                 fg_color="transparent",
                                 hover_color=COLORS["panel_bg"],
                                 text_color=COLORS["accent"],
                                 font=("Helvetica", 9),
                                 width=70, height=28,
                                 command=lambda: self._switch_page("interest"))
        back_btn.place(x=12, y=12)

        card = self._wizard_card(self.page_intake, width=500)

        ctk.CTkLabel(card, text=prog.get("name", ""),
                     fg_color="transparent", text_color=COLORS["accent"],
                     font=("Helvetica", 16, "bold")).pack(pady=(32, 2))
        ctk.CTkLabel(card, text=intake.get("intro", ""),
                     fg_color="transparent", text_color=COLORS["note"],
                     font=("Helvetica", 9, "italic")).pack(pady=(0, 16))
        ctk.CTkFrame(card, fg_color=COLORS["border"], height=1,
                     corner_radius=0).pack(fill=tk.X, padx=32, pady=(0, 18))

        q_vars: dict[str, tk.StringVar] = {}  # "yes" | "no" | ""

        for q in intake.get("questions", []):
            qid  = q["id"]
            qvar = tk.StringVar(value="")
            q_vars[qid] = qvar

            qf = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
            qf.pack(fill=tk.X, padx=32, pady=(0, 16))
            ctk.CTkLabel(qf, text=q["text"],
                         fg_color="transparent", text_color=COLORS["header"],
                         font=("Helvetica", 10),
                         wraplength=420, justify=tk.LEFT,
                         anchor="w").pack(anchor=tk.W, pady=(0, 8))

            btn_row = ctk.CTkFrame(qf, fg_color="transparent", corner_radius=0)
            btn_row.pack(anchor=tk.W)

            btn_yes = ctk.CTkButton(btn_row, text="Yes",
                                    font=("Helvetica", 9),
                                    fg_color=COLORS["bg"],
                                    hover_color=COLORS["panel_bg"],
                                    text_color=COLORS["accent"],
                                    border_width=1,
                                    border_color=COLORS["accent"],
                                    corner_radius=6,
                                    width=80, height=32)
            btn_yes.pack(side=tk.LEFT, padx=(0, 8))

            btn_no = ctk.CTkButton(btn_row, text="No",
                                   font=("Helvetica", 9),
                                   fg_color=COLORS["bg"],
                                   hover_color=COLORS["panel_bg"],
                                   text_color=COLORS["accent"],
                                   border_width=1,
                                   border_color=COLORS["accent"],
                                   corner_radius=6,
                                   width=80, height=32)
            btn_no.pack(side=tk.LEFT)

            def _make_yesno(qv, val, by, bn):
                def _select():
                    qv.set(val)
                    if val == "yes":
                        by.configure(fg_color=COLORS["accent"], text_color="white",
                                     border_color=COLORS["accent"])
                        bn.configure(fg_color=COLORS["bg"], text_color=COLORS["accent"],
                                     border_color=COLORS["accent"])
                    else:
                        bn.configure(fg_color=COLORS["accent"], text_color="white",
                                     border_color=COLORS["accent"])
                        by.configure(fg_color=COLORS["bg"], text_color=COLORS["accent"],
                                     border_color=COLORS["accent"])
                    _check_ready()
                return _select

            btn_yes.configure(command=_make_yesno(qvar, "yes", btn_yes, btn_no))
            btn_no.configure(command=_make_yesno(qvar, "no",  btn_yes, btn_no))

        ctk.CTkFrame(card, fg_color=COLORS["border"], height=1,
                     corner_radius=0).pack(fill=tk.X, padx=32, pady=(8, 18))

        cont_btn = ctk.CTkButton(card,
                                 text="Build Plan  →",
                                 font=("Helvetica", 10, "bold"),
                                 fg_color=COLORS["border"],
                                 hover_color=COLORS["border"],
                                 text_color=COLORS["note"],
                                 corner_radius=6,
                                 height=38,
                                 state="disabled")
        cont_btn.pack(anchor=tk.E, padx=32, pady=(0, 28))

        def _check_ready():
            if all(v.get() for v in q_vars.values()):
                cont_btn.configure(state="normal",
                                   fg_color=COLORS["accent"],
                                   hover_color=COLORS["accent_dk"],
                                   text_color="white")
            else:
                cont_btn.configure(state="disabled",
                                   fg_color=COLORS["border"],
                                   hover_color=COLORS["border"],
                                   text_color=COLORS["note"])

        def _on_continue():
            answers = {qid: (v.get() == "yes") for qid, v in q_vars.items()}
            route   = self._match_intake_route(intake, answers)
            if route:
                # If the matched route doesn't specify a major (e.g. _default
                # intake), inject the program the student selected on the
                # interest page so _apply_intake_route can set the dropdown.
                if not route.get("major") and pid:
                    route = dict(route, major=pid)
                self._apply_intake_route(route)
                self.check(jump_to_suggested=True)

        cont_btn.configure(command=_on_continue)

    def _match_intake_route(self, intake: dict, answers: dict) -> dict | None:
        """Return the first route whose 'when' conditions match answers."""
        for route in intake.get("routes", []):
            when = route.get("when", {})
            if all(answers.get(k) == v for k, v in when.items()):
                return route
        return None

    def _build_setup_page(self, parent):
        """Full-width student-setup page with scrollable content."""
        BG = COLORS["panel_bg"]

        # CTkScrollableFrame replaces the old canvas+scrollbar pattern
        sf = ctk.CTkScrollableFrame(parent, fg_color=BG, corner_radius=0,
                                    scrollbar_button_color=COLORS["border"],
                                    scrollbar_button_hover_color=COLORS["note"])
        sf.pack(fill=tk.BOTH, expand=True)
        f = sf   # alias — rest of the method packs into f

        def _card(parent_f, title, gold=False):
            """Return a content frame inside a rounded card."""
            outer = ctk.CTkFrame(parent_f,
                                 fg_color=COLORS["bg"],
                                 corner_radius=8,
                                 border_width=1,
                                 border_color=COLORS["border"])
            ctk.CTkLabel(outer, text=title,
                         fg_color="transparent",
                         text_color=COLORS["gold"] if gold else COLORS["accent"],
                         font=("Helvetica", 10, "bold"),
                         anchor="w").pack(anchor=tk.W, padx=14, pady=(10, 2))
            ctk.CTkFrame(outer, fg_color=COLORS["border"], height=1,
                         corner_radius=0).pack(fill=tk.X, padx=14, pady=(0, 8))
            content = ctk.CTkFrame(outer, fg_color="transparent", corner_radius=0)
            content.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 12))
            return outer, content

        def _field_label(parent_f, text):
            ctk.CTkLabel(parent_f, text=text,
                         fg_color="transparent", text_color=COLORS["header"],
                         font=("Helvetica", 9), anchor="w").pack(
                         anchor=tk.W, padx=10, pady=(4, 0))

        def _combobox(parent_f, variable, values, **kw):
            return ctk.CTkComboBox(parent_f, variable=variable, values=values,
                                   state="readonly", height=30,
                                   fg_color=COLORS["bg"],
                                   border_color=COLORS["border"],
                                   button_color=COLORS["accent"],
                                   button_hover_color=COLORS["accent_dk"],
                                   dropdown_fg_color=COLORS["bg"],
                                   dropdown_hover_color=COLORS["panel_bg"],
                                   text_color=COLORS["header"],
                                   font=("Helvetica", 9), **kw)

        # ── Import button ─────────────────────────────────────────────────────
        imp = ctk.CTkFrame(f, fg_color="transparent", corner_radius=0)
        imp.pack(fill=tk.X, padx=24, pady=(20, 8))
        ctk.CTkButton(imp, text="⬆  Load Student File",
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_dk"],
                      text_color="white",
                      font=("Helvetica", 9),
                      corner_radius=6, height=32,
                      command=self.load_student).pack(side=tk.LEFT)
        ctk.CTkLabel(imp, text="  or fill in below",
                     fg_color="transparent", text_color=COLORS["hint"],
                     font=("Helvetica", 9, "italic")).pack(side=tk.LEFT, padx=10)

        # ── Two-column: Student (left) | Programs (right) ─────────────────────
        self._two_col_frame = ctk.CTkFrame(f, fg_color="transparent", corner_radius=0)
        self._two_col_frame.pack(fill=tk.X, padx=24, pady=(4, 10))
        self._two_col_frame.columnconfigure(0, weight=1)
        self._two_col_frame.columnconfigure(1, weight=2)

        # Student card
        sp_outer, sp = _card(self._two_col_frame, "STUDENT")
        sp_outer.grid(row=0, column=0, padx=(0, 14), pady=0, sticky="nsew")

        for lbl, attr in [("Name:", "name_var"), ("Student ID:", "id_var")]:
            _field_label(sp, lbl)
            var = tk.StringVar()
            setattr(self, attr, var)
            ctk.CTkEntry(sp, textvariable=var, height=30,
                         fg_color=COLORS["bg"],
                         border_color=COLORS["border"],
                         text_color=COLORS["header"],
                         font=("Helvetica", 9)).pack(fill=tk.X, padx=10, pady=(2, 0))

        _field_label(sp, "Year:")
        self._year_var = tk.StringVar(value=STUDENT_YEARS[0])
        _combobox(sp, self._year_var, STUDENT_YEARS).pack(
            anchor=tk.W, padx=10, pady=(2, 0))

        _field_label(sp, "Transfer credits (WE):")
        self.transfer_var = tk.StringVar(value="0 credits (5 WE)")
        _combobox(sp, self.transfer_var,
                  ["0 credits (5 WE)", "1–7 credits (5 WE)",
                   "8 credits — max (3 WE)"]).pack(
            anchor=tk.W, padx=10, pady=(2, 0))

        # Programs card
        pp_outer, pp = _card(self._two_col_frame, "PROGRAMS")
        pp_outer.grid(row=0, column=1, padx=0, pady=0, sticky="nsew")
        pp.columnconfigure(0, weight=1)
        pp.columnconfigure(1, weight=1)

        NONE_OPT = "(none)"

        def _prog_display(p):
            yr = p.get("catalog_year", "")
            return f"{p['name']} ({yr})" if yr else p["name"]

        major_progs = sorted(
            [(pid, p) for pid, p in self.programs.items()
             if p.get("program_type") in ("major", "collateral", "certificate")],
            key=lambda x: x[1].get("name", ""))
        minor_progs = sorted(
            [(pid, p) for pid, p in self.programs.items()
             if p.get("program_type") == "minor"],
            key=lambda x: x[1].get("name", ""))

        major_names = [NONE_OPT] + [_prog_display(p) for _, p in major_progs]
        minor_names = [NONE_OPT] + [_prog_display(p) for _, p in minor_progs]

        self._major_display_to_pid = {_prog_display(p): pid for pid, p in major_progs}
        self._minor_display_to_pid = {_prog_display(p): pid for pid, p in minor_progs}
        self._display_to_pid = {**self._major_display_to_pid,
                                **self._minor_display_to_pid}
        self._pid_to_display = {}
        for pid, p in major_progs + minor_progs:
            self._pid_to_display[pid] = _prog_display(p)

        maj_labels = ["Major:", "Major 2 (optional):", "Major 3 (optional):"]
        for i in range(3):
            row_f = ctk.CTkFrame(pp, fg_color="transparent", corner_radius=0)
            row_f.grid(row=i, column=0, columnspan=2, sticky="ew", padx=4, pady=2)
            ctk.CTkLabel(row_f, text=maj_labels[i],
                         fg_color="transparent", text_color=COLORS["header"],
                         font=("Helvetica", 9), width=130,
                         anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=NONE_OPT)
            self._major_vars.append(var)
            _combobox(row_f, var, major_names, width=220).pack(
                side=tk.LEFT, fill=tk.X, expand=True)

        min_labels = ["Minor (optional):", "Minor 2 (optional):"]
        for i in range(2):
            row_f = ctk.CTkFrame(pp, fg_color="transparent", corner_radius=0)
            row_f.grid(row=3 + i, column=0, columnspan=2, sticky="ew",
                       padx=4, pady=2)
            ctk.CTkLabel(row_f, text=min_labels[i],
                         fg_color="transparent", text_color=COLORS["header"],
                         font=("Helvetica", 9), width=130,
                         anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=NONE_OPT)
            self._minor_vars.append(var)
            _combobox(row_f, var, minor_names, width=220).pack(
                side=tk.LEFT, fill=tk.X, expand=True)

        # ── Pathways (conditional, horizontal) ───────────────────────────────
        self._pw_container = ctk.CTkFrame(f, fg_color="transparent",
                                          corner_radius=0)
        self._pw_container.pack(fill=tk.X, padx=24, pady=(0, 4))
        self._pw_container.pack_forget()

        pw_outer, pw_inner = _card(self._pw_container,
                                   "PRE-PROFESSIONAL PATHWAYS", gold=True)
        pw_outer.pack(fill=tk.X)
        ctk.CTkLabel(pw_inner,
                     text="Optional — check any that apply to add a detailed pathway tab",
                     fg_color="transparent", text_color=COLORS["hint"],
                     font=("Helvetica", 8)).pack(anchor=tk.W, padx=4, pady=(0, 6))
        self._pw_rows_frame = ctk.CTkFrame(pw_inner, fg_color="transparent",
                                           corner_radius=0)
        self._pw_rows_frame.pack(anchor=tk.W, padx=4, pady=(0, 4))

        self._pathway_rows: dict    = {}
        self._pathway_related: dict = {}

        for pw_id, pw in sorted(self.pathways.items(),
                                key=lambda x: x[1].get("name", "")):
            var = tk.BooleanVar()
            self.pathway_vars[pw_id] = var
            related = set(pw.get("related_programs", []))
            self._pathway_related[pw_id] = related
            rel_codes = sorted(
                self.programs.get(r, {}).get("major_code",
                                             r.split("_")[0].upper())
                for r in related)
            codes_str = ", ".join(rel_codes[:2])
            hint = f"  [{codes_str}]" if rel_codes else ""
            pw_label = f"{pw['name']}{hint}"
            row = ctk.CTkFrame(self._pw_rows_frame, fg_color="transparent",
                               corner_radius=0)
            ctk.CTkCheckBox(row, text=pw_label, variable=var,
                            fg_color=COLORS["accent"],
                            hover_color=COLORS["accent_dk"],
                            border_color=COLORS["border"],
                            text_color=COLORS["header"],
                            font=("Helvetica", 9),
                            checkmark_color="white").pack(anchor=tk.W)
            self._pathway_rows[pw_id] = row

        # ── Track / variant selector ──────────────────────────────────────────
        self._variant_container = ctk.CTkFrame(f, fg_color="transparent",
                                               corner_radius=0)
        self._variant_container.pack(fill=tk.X, padx=24, pady=(0, 4))
        self._variant_container.pack_forget()

        va_outer, va_inner = _card(self._variant_container,
                                   "TRACK / CONCENTRATION")
        va_outer.pack(fill=tk.X)
        ctk.CTkLabel(va_inner,
                     text="Select the path that best describes this student",
                     fg_color="transparent", text_color=COLORS["hint"],
                     font=("Helvetica", 8)).pack(anchor=tk.W, padx=4, pady=(0, 6))
        self._variant_rows_frame = ctk.CTkFrame(va_inner, fg_color="transparent",
                                                corner_radius=0)
        self._variant_rows_frame.pack(anchor=tk.W, padx=4, pady=(0, 4))

        # Traces
        for var in self._major_vars + self._minor_vars:
            var.trace_add("write", lambda *_: self._update_pathway_visibility())
            var.trace_add("write", lambda *_: self._update_variant_visibility())

        # ── Courses by semester ───────────────────────────────────────────────
        hdr_f = ctk.CTkFrame(f, fg_color="transparent", corner_radius=0)
        hdr_f.pack(fill=tk.X, padx=24, pady=(10, 0))
        ctk.CTkLabel(hdr_f, text="COURSES BY SEMESTER",
                     fg_color="transparent", text_color=COLORS["accent"],
                     font=("Helvetica", 10, "bold")).pack(side=tk.LEFT)
        ctk.CTkLabel(hdr_f, text="  ☑ completed   ☐ planned",
                     fg_color="transparent", text_color=COLORS["hint"],
                     font=("Helvetica", 8)).pack(side=tk.LEFT, padx=10)
        ctk.CTkFrame(f, fg_color=COLORS["border"], height=1,
                     corner_radius=0).pack(fill=tk.X, padx=24, pady=(6, 8))

        self._courses_area = ctk.CTkFrame(f, fg_color="transparent",
                                          corner_radius=0)
        self._courses_area.pack(fill=tk.X, padx=18)
        for col in range(3):
            self._courses_area.columnconfigure(col, weight=1, minsize=260)

        self._add_semester("Transfer", initial_rows=2, is_transfer=True)
        self._add_semester("Semester 1", initial_rows=3)

        # "+ Add Semester"
        add_sem_f = ctk.CTkFrame(f, fg_color="transparent", corner_radius=0)
        add_sem_f.pack(fill=tk.X, padx=24, pady=(4, 6))
        ctk.CTkButton(add_sem_f, text="＋ Add Semester",
                      font=("Helvetica", 9),
                      fg_color="transparent",
                      hover_color=COLORS["panel_bg"],
                      text_color=COLORS["accent"],
                      corner_radius=6, height=28,
                      command=self._add_next_semester).pack(anchor=tk.W)

        # ── Bottom action bar ─────────────────────────────────────────────────
        ctk.CTkFrame(f, fg_color=COLORS["border"], height=1,
                     corner_radius=0).pack(fill=tk.X, padx=24, pady=(8, 0))
        bot = ctk.CTkFrame(f, fg_color="transparent", corner_radius=0)
        bot.pack(fill=tk.X, padx=24, pady=(10, 24))

        ctk.CTkButton(bot, text="Save Student File",
                      fg_color=COLORS["panel_bg"],
                      hover_color=COLORS["border"],
                      text_color=COLORS["header"],
                      border_width=1, border_color=COLORS["border"],
                      font=("Helvetica", 9), corner_radius=6, height=34,
                      command=self.save_student).pack(side=tk.LEFT, padx=(0, 8))
        ctk.CTkButton(bot, text="Clear All",
                      fg_color=COLORS["panel_bg"],
                      hover_color=COLORS["border"],
                      text_color=COLORS["header"],
                      border_width=1, border_color=COLORS["border"],
                      font=("Helvetica", 9), corner_radius=6, height=34,
                      command=self.clear_all).pack(side=tk.LEFT)
        ctk.CTkButton(bot, text="Check Requirements  →",
                      font=("Helvetica", 10, "bold"),
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_dk"],
                      text_color="white",
                      corner_radius=6, height=36,
                      command=self.check).pack(side=tk.RIGHT)

    def _build_results_page(self, parent):
        """Full-width results page: summary bar + tabbed requirement checks."""
        # Summary bar — dark strip with student info + action buttons
        bar = ctk.CTkFrame(parent, fg_color=COLORS["header"], corner_radius=0,
                           height=38)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)

        self.summary_var = tk.StringVar(
            value="Fill in the Student Setup page and click Check Requirements.")
        ctk.CTkLabel(bar, textvariable=self.summary_var,
                     fg_color="transparent", text_color="#cbd5e1",
                     font=("Helvetica", 9),
                     anchor="w").pack(side=tk.LEFT, padx=16, pady=0,
                                      fill=tk.X, expand=True)
        ctk.CTkButton(bar, text="Export Report",
                      font=("Helvetica", 8),
                      fg_color="transparent",
                      hover_color=COLORS["accent"],
                      text_color="#94a3b8",
                      corner_radius=4, height=26,
                      command=self.export).pack(side=tk.RIGHT, padx=10, pady=6)

        self._nb_tab_names: list[str] = []
        self.nb = ctk.CTkTabview(parent,
                                 fg_color=COLORS["bg"],
                                 segmented_button_fg_color=COLORS["panel_bg"],
                                 segmented_button_selected_color=COLORS["accent"],
                                 segmented_button_selected_hover_color=COLORS["accent_dk"],
                                 segmented_button_unselected_color=COLORS["panel_bg"],
                                 segmented_button_unselected_hover_color=COLORS["border"],
                                 text_color="white",
                                 text_color_disabled=COLORS["note"])
        self.nb.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)


    # ──────────────────────────────────────────────────────────────────────────
    # Semester / course helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _update_pathway_visibility(self):
        """Show pathway checkboxes only when a relevant major/minor is selected."""
        sel_ids = set(self._selected_program_ids())
        any_visible = False
        for pw_id, row in self._pathway_rows.items():
            related  = self._pathway_related.get(pw_id, set())
            visible  = bool(related & sel_ids)
            if visible:
                row.pack(side=tk.LEFT, padx=(0, 16))
                any_visible = True
            else:
                row.pack_forget()
                self.pathway_vars[pw_id].set(False)
        if any_visible:
            self._pw_container.pack(fill=tk.X, padx=24, pady=(0, 4))
        else:
            self._pw_container.pack_forget()

    def _selected_program_ids(self) -> list:
        """Return ordered, deduplicated program IDs from major/minor dropdowns."""
        seen, result = set(), []
        for var in self._major_vars:
            pid = self._major_display_to_pid.get(var.get())
            if pid and pid not in seen:
                seen.add(pid)
                result.append(pid)
        for var in self._minor_vars:
            pid = self._minor_display_to_pid.get(var.get())
            if pid and pid not in seen:
                seen.add(pid)
                result.append(pid)
        return result

    def _collect_courses(self) -> set:
        """Return normalized codes for all completed-checked courses."""
        taken = set()
        for sem in self._semesters:
            for row in sem["rows"]:
                code = row["code_var"].get().strip()
                if code and row["completed_var"].get():
                    for c in parse_courses(code):
                        taken.add(c)
        return taken

    def _add_semester(self, label: str, initial_rows: int = 3,
                      is_transfer: bool = False) -> dict:
        """Create a semester card and place it in the 3-column grid."""
        idx    = len(self._semesters)
        HDR_BG = "#2d5278" if is_transfer else "#2c3e50"
        ACCENT = COLORS["gold"] if is_transfer else COLORS["accent"]

        outer = ctk.CTkFrame(self._courses_area, fg_color=COLORS["bg"],
                             corner_radius=6, border_width=1,
                             border_color=COLORS["border"])
        outer.grid(row=idx // 3, column=idx % 3, sticky="nsew", padx=5, pady=5)
        self._courses_area.columnconfigure(idx % 3, weight=1, minsize=260)

        # Thin colored top accent bar
        ctk.CTkFrame(outer, fg_color=ACCENT, height=3,
                     corner_radius=0).pack(fill=tk.X)

        hdr = ctk.CTkFrame(outer, fg_color=HDR_BG, corner_radius=0)
        hdr.pack(fill=tk.X)
        ctk.CTkLabel(hdr, text=label, font=("Helvetica", 9, "bold"),
                     text_color="white", fg_color="transparent",
                     anchor="w").pack(side=tk.LEFT, padx=10, pady=6)

        rows_frame = ctk.CTkFrame(outer, fg_color=COLORS["bg"], corner_radius=0)
        rows_frame.pack(fill=tk.X, padx=6, pady=6)

        sem_dict = {"label": label, "frame": outer, "rows": [],
                    "rows_frame": rows_frame, "is_transfer": is_transfer}
        self._semesters.append(sem_dict)

        for _ in range(initial_rows):
            self._add_course_row(sem_dict)

        ctk.CTkButton(outer, text="+ course",
                      font=("Helvetica", 8),
                      fg_color="transparent",
                      hover_color=COLORS["border"],
                      text_color=COLORS["accent"],
                      border_width=0, anchor="w", height=24,
                      command=lambda sd=sem_dict: self._add_course_row(sd)
                      ).pack(anchor=tk.W, padx=4, pady=(0, 6))

        return sem_dict

    def _add_course_row(self, sem_dict: dict, code: str = "",
                        grade: str = "", completed: bool = True):
        """Append one course-entry row to a semester card."""
        rf = sem_dict["rows_frame"]
        row_f = ctk.CTkFrame(rf, fg_color=COLORS["bg"], corner_radius=0)
        row_f.pack(fill=tk.X, pady=1)

        completed_var = tk.BooleanVar(value=completed)
        ctk.CTkCheckBox(row_f, variable=completed_var, text="",
                        onvalue=True, offvalue=False,
                        width=20, height=20,
                        checkbox_width=16, checkbox_height=16,
                        fg_color=COLORS["accent"],
                        border_color=COLORS["border"],
                        corner_radius=3).pack(side=tk.LEFT, padx=(2, 2))

        code_var = tk.StringVar(value=code)
        ctk.CTkEntry(row_f, textvariable=code_var, width=100,
                     font=("Courier New", 10),
                     fg_color=COLORS["bg"],
                     text_color=COLORS["header"],
                     border_color=COLORS["border"],
                     border_width=1, corner_radius=4,
                     height=28).pack(side=tk.LEFT, padx=(2, 2))

        grade_var = tk.StringVar(value=grade)
        ctk.CTkComboBox(row_f, variable=grade_var,
                        values=GRADES, state="readonly",
                        width=70, height=28,
                        fg_color=COLORS["bg"],
                        border_color=COLORS["border"],
                        button_color=COLORS["border"],
                        border_width=1, corner_radius=4,
                        font=("Helvetica", 10)).pack(side=tk.LEFT, padx=(2, 2))

        row_dict = {"code_var": code_var, "grade_var": grade_var,
                    "completed_var": completed_var, "frame": row_f}

        def _delete(rd=row_dict, sd=sem_dict):
            rd["frame"].destroy()
            if rd in sd["rows"]:
                sd["rows"].remove(rd)

        ctk.CTkButton(row_f, text="×",
                      font=("Helvetica", 12, "bold"),
                      fg_color="transparent",
                      hover_color=COLORS["border"],
                      text_color=COLORS["border"],
                      width=24, height=24, corner_radius=4,
                      command=_delete).pack(side=tk.LEFT, padx=(2, 0))

        sem_dict["rows"].append(row_dict)

    def _add_next_semester(self):
        """Append the next numbered semester to the grid."""
        max_n = 0
        for sem in self._semesters:
            lbl = sem["label"]
            if lbl.startswith("Semester "):
                try:
                    max_n = max(max_n, int(lbl.split()[-1]))
                except ValueError:
                    pass
        self._add_semester(f"Semester {max_n + 1}", initial_rows=3)

    def _rebuild_semester_grid(self):
        """Destroy all semester boxes and recreate the defaults."""
        for sem in self._semesters:
            sem["frame"].destroy()
        self._semesters.clear()
        self._add_semester("Transfer", initial_rows=2, is_transfer=True)
        self._add_semester("Semester 1", initial_rows=3)

    # ──────────────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────────────

    def _apply_intake_route(self, route: dict):
        """Pre-populate the setup form from a wizard intake route result."""
        # Clear any previous wizard note
        self._wizard_route_note = route.get("note", "")
        # Store comfort flags (default True so programs without these fields
        # never suppress courses)
        self._comfort_math    = route.get("comfort_math",    True)
        self._comfort_science = route.get("comfort_science", True)

        # Set major dropdown
        major_pid = route.get("major", "")
        if major_pid and self._major_vars:
            display = self._pid_to_display.get(major_pid, "")
            if display:
                self._major_vars[0].set(display)
                for var in self._major_vars[1:]:
                    var.set("(none)")
            for var in self._minor_vars:
                var.set("(none)")

        # Set pathway checkbox
        pathway_id = route.get("pathway", "")
        for pid, var in self.pathway_vars.items():
            var.set(pid == pathway_id and bool(pathway_id))

        # Pre-fill Semester 1 with recommended courses (as "planned", not completed)
        courses = route.get("semester_1", [])
        if courses:
            sem1 = next((s for s in self._semesters if s["label"] == "Semester 1"), None)
            if sem1:
                for row in list(sem1["rows"]):
                    row["frame"].destroy()
                sem1["rows"].clear()
                for code in courses:
                    self._add_course_row(sem1, code=code, completed=False)
                self._add_course_row(sem1)  # one blank row at end

        self._update_pathway_visibility()

    def check(self, jump_to_suggested: bool = False):
        sel_ids = self._selected_program_ids()
        taken   = self._collect_courses()

        # WE count adjustment for transfer students
        we_required = 3 if "8 credits" in self.transfer_var.get() else 5

        # Clear tabs
        for name in self._nb_tab_names:
            self.nb.delete(name)
        self._nb_tab_names.clear()
        self.manual_ge.clear()

        # GE tab
        ge_result = check_ge(self.ge_data, taken, self.dac, self.we)
        self.nb.add("GE Requirements")
        self._nb_tab_names.append("GE Requirements")
        self._render_ge(self.nb.tab("GE Requirements"), ge_result, we_required)

        # Active pathways
        active_pathway_ids = [pid for pid, var in self.pathway_vars.items()
                              if var.get()]

        # Program tabs
        for pid in sel_ids:
            prog  = self.programs[pid]
            result = check_program(prog, taken)
            ptype = prog.get("program_type", "").title()
            tab_name = f"{prog['name']} ({ptype})"
            self.nb.add(tab_name)
            self._nb_tab_names.append(tab_name)
            self._render_program(self.nb.tab(tab_name), result,
                                 active_pathways=active_pathway_ids)

        # Pathway tabs
        for pw_id in active_pathway_ids:
            pw     = self.pathways[pw_id]
            result = check_program(pw, taken)
            tab_name = f"\u2b21 {pw['name']}"
            self.nb.add(tab_name)
            self._nb_tab_names.append(tab_name)
            self._render_program(self.nb.tab(tab_name), result)

        # First Two Years tab
        f2y_entries = self._matching_first_two_years(sel_ids)
        if f2y_entries:
            self.nb.add("First 2 Years")
            self._nb_tab_names.append("First 2 Years")
            self._render_first_two_years(self.nb.tab("First 2 Years"),
                                         f2y_entries, taken)

        # Suggested Plan tab
        if sel_ids:
            self.nb.add("Suggested Plan")
            self._nb_tab_names.append("Suggested Plan")
            self._render_suggested_plan(
                self.nb.tab("Suggested Plan"), sel_ids, taken, ge_result,
                we_required, active_pathway_ids, f2y_entries)

        # Summary
        name     = self.name_var.get().strip() or "Student"
        sid      = self.id_var.get().strip()
        sid_str  = f" (ID: {sid})" if sid else ""
        year     = self._year_var.get() if self._year_var else ""
        year_str = f"  ·  {year}" if year and year != STUDENT_YEARS[0] else ""
        cred     = total_credits(taken, self.course_credits)
        self.summary_var.set(
            f"{name}{sid_str}{year_str}  |  {cred:.1f} credits ({len(taken)} courses)"
            f"  |  {len(sel_ids)} program(s)  |  {len(active_pathway_ids)} pathway(s)")
        self._switch_page("results")

        # Jump straight to the Suggested Plan tab (used by the new-student wizard)
        if jump_to_suggested and "Suggested Plan" in self._nb_tab_names:
            self.nb.set("Suggested Plan")

    def clear_all(self):
        self._wizard_route_note = ""
        self._comfort_math      = True
        self._comfort_science   = True
        self.name_var.set("")
        self.id_var.set("")
        if self._year_var:
            self._year_var.set(STUDENT_YEARS[0])
        self.transfer_var.set("0 credits (5 WE)")
        for var in self._major_vars:
            var.set("(none)")
        for var in self._minor_vars:
            var.set("(none)")
        if self._courses_area:
            self._rebuild_semester_grid()
        self._update_pathway_visibility()
        for name in self._nb_tab_names:
            self.nb.delete(name)
        self._nb_tab_names.clear()
        self.summary_var.set(
            "Select programs and enter courses, then click Check Requirements.")
        self._switch_page("setup")

    def export(self):
        name  = self.name_var.get().strip() or "student"
        fname = f"advising_{name.replace(' ', '_')}_{datetime.now():%Y%m%d}.txt"
        path  = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile=fname)
        if not path:
            return

        prog_names = [v.get() for v in self._major_vars + self._minor_vars
                      if v.get() != "(none)"]
        prog_str   = ", ".join(prog_names) if prog_names else "N/A"
        year_str   = self._year_var.get() if self._year_var else ""

        lines = [
            "Coe College Academic Advising Report",
            f"Generated: {datetime.now():%Y-%m-%d %H:%M}",
            f"Student: {self.name_var.get() or 'N/A'}  |  ID: {self.id_var.get() or 'N/A'}  |  Year: {year_str}",
            f"Programs: {prog_str}",
            "=" * 60, "",
        ]
        for name in self._nb_tab_names:
            frame = self.nb.tab(name)
            for child in frame.winfo_children():
                if isinstance(child, ctk.CTkTextbox):
                    lines.append(f"\n{'=' * 60}")
                    lines.append(name.upper())
                    lines.append('=' * 60)
                    lines.append(child.get("1.0", tk.END).strip())
        try:
            Path(path).write_text("\n".join(lines), encoding="utf-8")
            messagebox.showinfo("Exported", f"Saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    def save_student(self):
        """Save current student data to an importable .adv file."""
        name  = self.name_var.get().strip() or "student"
        fname = f"student_{name.replace(' ', '_')}_{datetime.now():%Y%m%d}.adv"
        path  = filedialog.asksaveasfilename(
            defaultextension=".adv",
            filetypes=[("Advising files", "*.adv"), ("Text files", "*.txt"),
                       ("All files", "*.*")],
            initialfile=fname)
        if not path:
            return

        sel_ids    = self._selected_program_ids()
        active_pws = [pid for pid, var in self.pathway_vars.items() if var.get()]

        lines = [
            "# Coe College Academic Advising Student File",
            f"# Generated: {datetime.now():%Y-%m-%d %H:%M}",
            "",
            f"NAME: {self.name_var.get().strip()}",
            f"ID: {self.id_var.get().strip()}",
            f"YEAR: {self._year_var.get() if self._year_var else ''}",
        ]

        maj_ids = [self._major_display_to_pid.get(v.get(), "") for v in self._major_vars]
        min_ids = [self._minor_display_to_pid.get(v.get(), "") for v in self._minor_vars]
        for i, mid in enumerate(maj_ids, 1):
            lines.append(f"MAJOR{i}: {mid or ''}")
        for i, mid in enumerate(min_ids, 1):
            lines.append(f"MINOR{i}: {mid or ''}")

        lines.append(f"PATHWAYS: {', '.join(active_pws)}")
        lines.append(f"TRANSFER_WE: {self.transfer_var.get()}")
        lines.append("")

        # Semester/course data
        for sem in self._semesters:
            sem_courses = [
                (row["code_var"].get().strip(),
                 row["grade_var"].get().strip(),
                 row["completed_var"].get())
                for row in sem["rows"]
                if row["code_var"].get().strip()
            ]
            if not sem_courses:
                continue
            lines.append(f"SEMESTER: {sem['label']}")
            for code, grade, done in sem_courses:
                status = "completed" if done else "planned"
                lines.append(f"COURSE: {code}, {status}, {grade}")
            lines.append("")

        # Suggested courses as comments (not imported)
        taken = self._collect_courses()
        major_code = ""
        for pid in sel_ids:
            prog = self.programs.get(pid, {})
            if prog.get("program_type") == "major":
                major_code = prog.get("major_code", "")
                break
        if major_code:
            suggestions = self.trajectory.elective_suggestions(major_code, exclude=taken)
            if suggestions:
                lines.append(
                    "# \u2500\u2500 SUGGESTED NEXT COURSES (reference only \u2014 not imported) \u2500\u2500")
                for code, info in suggestions:
                    sem_str = f"Sem {info['sem']}" if info["sem"] else "?"
                    pct_str = f"{info['pct']:.0%}"
                    lines.append(f"# {code:<12}  {pct_str} of grads   {sem_str}")

        try:
            Path(path).write_text("\n".join(lines), encoding="utf-8")
            messagebox.showinfo("Saved", f"Student file saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

    def load_student(self):
        """Load student data from an .adv file into the form."""
        path = filedialog.askopenfilename(
            filetypes=[("Advising files", "*.adv"), ("Text files", "*.txt"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Load Error", str(e))
            return

        fields = {
            "NAME": "", "ID": "", "YEAR": "", "PATHWAYS": "", "TRANSFER_WE": "",
            "MAJOR1": "", "MAJOR2": "", "MAJOR3": "",
            "MINOR1": "", "MINOR2": "",
        }
        semesters_data = []   # list of [label, [(code, status, grade)]]
        old_courses    = []   # flat list from legacy COURSES: format
        current_sem    = None
        in_old_courses = False

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if stripped == "COURSES:":
                in_old_courses = True

            elif stripped.startswith("SEMESTER:"):
                in_old_courses = False
                label = stripped[9:].strip()
                current_sem = [label, []]
                semesters_data.append(current_sem)

            elif stripped.startswith("COURSE:") and current_sem is not None:
                parts  = stripped[7:].strip().split(",", 2)
                code   = parts[0].strip() if len(parts) > 0 else ""
                status = parts[1].strip() if len(parts) > 1 else "planned"
                grade  = parts[2].strip() if len(parts) > 2 else ""
                if code:
                    current_sem[1].append((code, status, grade))

            elif in_old_courses:
                old_courses.append(stripped)

            elif stripped.startswith("PROGRAMS:"):
                # Legacy: comma-separated program IDs
                old_pids = [p.strip() for p in stripped[9:].split(",") if p.strip()]
                maj_idx = min_idx = 0
                for pid in old_pids:
                    ptype = self.programs.get(pid, {}).get("program_type", "")
                    if ptype in ("major", "collateral", "certificate") and maj_idx < 3:
                        maj_idx += 1
                        fields[f"MAJOR{maj_idx}"] = pid
                    elif ptype == "minor" and min_idx < 2:
                        min_idx += 1
                        fields[f"MINOR{min_idx}"] = pid

            else:
                for key in fields:
                    if stripped.startswith(f"{key}:"):
                        fields[key] = stripped[len(key) + 1:].strip()
                        break

        # Apply scalar fields
        self.name_var.set(fields["NAME"])
        self.id_var.set(fields["ID"])
        if fields["YEAR"] in STUDENT_YEARS and self._year_var:
            self._year_var.set(fields["YEAR"])
        valid_we = ["0 credits (5 WE)", "1\u20137 credits (5 WE)",
                    "8 credits \u2014 max (3 WE)"]
        if fields["TRANSFER_WE"] in valid_we:
            self.transfer_var.set(fields["TRANSFER_WE"])

        # Set major/minor dropdowns
        for i, var in enumerate(self._major_vars, 1):
            pid = fields.get(f"MAJOR{i}", "")
            var.set(self._pid_to_display.get(pid, "(none)"))
        for i, var in enumerate(self._minor_vars, 1):
            pid = fields.get(f"MINOR{i}", "")
            var.set(self._pid_to_display.get(pid, "(none)"))

        # Set pathways
        pw_ids = [p.strip() for p in fields["PATHWAYS"].split(",") if p.strip()]
        for pw_id, var in self.pathway_vars.items():
            var.set(pw_id in pw_ids)

        # Rebuild semester grid from file data
        for sem in self._semesters:
            sem["frame"].destroy()
        self._semesters.clear()

        if semesters_data:
            for label, courses in semesters_data:
                is_t = label.lower() == "transfer"
                sd = self._add_semester(label, initial_rows=0, is_transfer=is_t)
                for code, status, grade in courses:
                    self._add_course_row(sd, code=code, grade=grade,
                                        completed=(status.lower() == "completed"))
                if not courses:
                    for _ in range(2 if is_t else 3):
                        self._add_course_row(sd)
        elif old_courses:
            # Legacy flat course list — put everything in Semester 1
            self._add_semester("Transfer", initial_rows=2, is_transfer=True)
            sd = self._add_semester("Semester 1", initial_rows=0)
            for code in old_courses:
                self._add_course_row(sd, code=code, completed=True)
            for i in range(2, 5):
                self._add_semester(f"Semester {i}", initial_rows=3)
        else:
            self._rebuild_semester_grid()

        self._update_pathway_visibility()
        messagebox.showinfo("Loaded", f"Student file loaded:\n{Path(path).name}")
    # ──────────────────────────────────────────────────────────────────────────
    # Rendering helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _make_text(self, parent) -> ctk.CTkTextbox:
        t = ctk.CTkTextbox(parent, wrap="word",
                           font=("Helvetica", 10),
                           fg_color=COLORS["bg"],
                           text_color=COLORS["header"],
                           corner_radius=0, border_width=0,
                           activate_scrollbars=True)
        t.pack(fill=tk.BOTH, expand=True)

        t.tag_configure("h1",      font=("Helvetica", 14, "bold"),
                        foreground=COLORS["accent"],  spacing1=4, spacing3=8)
        t.tag_configure("h2",      font=("Helvetica", 10, "bold"),
                        foreground=COLORS["header"],  spacing1=12, spacing3=3)
        t.tag_configure("divider", font=("Courier",   8),
                        foreground=COLORS["border"],  spacing1=10)
        t.tag_configure("summary", font=("Helvetica", 9),
                        foreground=COLORS["note"])
        t.tag_configure("complete",    font=("Helvetica", 10, "bold"),
                        foreground=COLORS["complete"])
        t.tag_configure("partial",     font=("Helvetica", 10, "bold"),
                        foreground=COLORS["partial"])
        t.tag_configure("incomplete",  font=("Helvetica", 10, "bold"),
                        foreground=COLORS["incomplete"])
        t.tag_configure("manual",      font=("Helvetica", 10, "bold"),
                        foreground=COLORS["manual"])
        t.tag_configure("item_done",   font=("Helvetica", 10),
                        foreground=COLORS["complete"])
        t.tag_configure("item_todo",   font=("Helvetica", 10),
                        foreground=COLORS["incomplete"])
        t.tag_configure("item_manual", font=("Helvetica", 10),
                        foreground=COLORS["manual"])
        t.tag_configure("hint",        font=("Helvetica",  9),
                        foreground=COLORS["hint"])
        t.tag_configure("note",        font=("Helvetica",  9, "italic"),
                        foreground=COLORS["note"])
        return t

    def _ins(self, t: ctk.CTkTextbox, text: str, tag: str = ""):
        t.insert(tk.END, text, tag)

    # ── First Two Years matching & rendering ──────────────────────────────────

    def _matching_first_two_years(self, sel_ids: list) -> list:
        """Return (entry, program) tuples matching selected programs, filtered
        by any track/variant the advisor has chosen in the setup panel."""
        results = []
        seen_entry_ids = set()
        for pid in sel_ids:
            prog = self.programs.get(pid, {})
            major_code = prog.get("major_code", "")
            selected_eid = self._variant_vars.get(pid, tk.StringVar()).get() or None
            for entry in self.first_two_years:
                eid = entry.get("id", "")
                if eid in seen_entry_ids:
                    continue
                # Match by explicit program ID first, then by major_code fallback
                matches = False
                if pid in entry.get("match_program_ids", []):
                    matches = True
                elif major_code and major_code in entry.get("match_major_codes", []):
                    if not entry.get("match_program_ids"):
                        matches = True
                if not matches:
                    continue
                # Honour variant selection (if a track was chosen, skip the others)
                if selected_eid and eid != selected_eid:
                    continue
                seen_entry_ids.add(eid)
                results.append((entry, prog))
        return results

    def _update_variant_visibility(self):
        """Show track/variant radio buttons when a selected program has multiple F2Y entries."""
        sel_ids = self._selected_program_ids()

        # Map each selected program → its matching F2Y entries
        prog_to_entries: dict = {}
        for pid in sel_ids:
            prog = self.programs.get(pid, {})
            major_code = prog.get("major_code", "")
            seen = set()
            matches = []
            for entry in self.first_two_years:
                eid = entry.get("id", "")
                if eid in seen:
                    continue
                if pid in entry.get("match_program_ids", []):
                    matches.append(entry); seen.add(eid)
                elif major_code and major_code in entry.get("match_major_codes", []):
                    if not entry.get("match_program_ids"):
                        matches.append(entry); seen.add(eid)
            if matches:
                prog_to_entries[pid] = matches

        # Rebuild variant UI
        for w in self._variant_rows_frame.winfo_children():
            w.destroy()
        self._variant_vars.clear()

        any_visible = False
        for pid in sel_ids:
            entries = prog_to_entries.get(pid, [])
            if len(entries) <= 1:
                continue
            prog = self.programs.get(pid, {})
            prog_name = prog.get("name", pid)
            any_visible = True

            grp = ctk.CTkFrame(self._variant_rows_frame, fg_color=COLORS["bg"],
                               corner_radius=0)
            grp.pack(anchor=tk.W, padx=4, pady=(4, 2))
            ctk.CTkLabel(grp, text=f"{prog_name}:", fg_color="transparent",
                         text_color=COLORS["header"],
                         font=("Helvetica", 9, "bold"),
                         anchor="w").pack(anchor=tk.W)

            var = tk.StringVar(value=entries[0]["id"])
            self._variant_vars[pid] = var
            for entry in entries:
                lbl = entry.get("label", entry["id"])
                vn  = entry.get("variant_note", "")
                display = lbl + (f"  —  {vn}" if vn else "")
                ctk.CTkRadioButton(grp, text=display, variable=var,
                                   value=entry["id"],
                                   fg_color=COLORS["accent"],
                                   border_color=COLORS["border"],
                                   font=("Helvetica", 9),
                                   text_color=COLORS["header"]
                                   ).pack(anchor=tk.W, padx=20)

        if any_visible:
            self._variant_container.pack(fill=tk.X, padx=24, pady=(0, 4))
        else:
            self._variant_container.pack_forget()

    def _render_suggested_plan(self, parent: tk.Frame, sel_ids: list,
                               taken: set, ge_result: dict, we_required: int,
                               active_pathway_ids: list, f2y_entries: list):
        """Render a semester-ordered plan of what remains to be completed."""
        _CODE_RE = re.compile(r'^[A-Z]+-\d')
        _YEAR_SEM = {
            "First Year":       1,
            "Sophomore":        3,
            "Junior":           5,
            "Senior":           7,
            "Transfer Student": 3,
        }
        _SEM_NUM = {"y1_fall": 1, "y1_spring": 2, "y2_fall": 3, "y2_spring": 4}
        _SEM_KEYS = ["y1_fall", "y1_spring", "y2_fall", "y2_spring"]
        _SEM_LABELS = {
            "y1_fall":   "Year 1 — Fall",
            "y1_spring": "Year 1 — Spring",
            "y2_fall":   "Year 2 — Fall",
            "y2_spring": "Year 2 — Spring",
        }

        year_label  = self._year_var.get() if self._year_var else "First Year"
        current_sem = _YEAR_SEM.get(year_label, 1)
        taken_norm  = {normalize(c) for c in taken}

        t = self._make_text(parent)
        shown_codes: set = set()   # primary non-aux codes already rendered anywhere

        def _f2y_primary(course_str):
            """Primary non-aux code from an F2Y entry string, or None."""
            if not _CODE_RE.match(course_str):
                return None
            raw  = course_str.split()[0]
            norm = normalize(raw)
            return None if is_auxiliary(norm) else norm

        def _primary_code(codes_list):
            """First non-auxiliary normalized code from a requirement codes list."""
            for c in codes_list:
                n = normalize(c)
                if not is_auxiliary(n):
                    return n
            return None

        # ── A: Status header ─────────────────────────────────────────────────────
        self._ins(t, "SUGGESTED COURSE PLAN\n", "h1")
        prog_names = [self.programs[pid]["name"]
                      for pid in sel_ids if pid in self.programs]
        cred = total_credits(taken, self.course_credits)
        self._ins(t,
            f"Year: {year_label}   Programs: {', '.join(prog_names) or '(none)'}   "
            f"Credits taken: {cred:.1f}\n"
            "□ = needed   ◇ = choose from options   ◻ = non-course   ⚠ = overdue\n\n",
            "summary")

        # Wizard routing note (shown when the new-student wizard produced this plan)
        if self._wizard_route_note:
            self._ins(t,
                "── FIRST-SEMESTER RECOMMENDATION ──────────────────────────────\n",
                "divider")
            self._ins(t, f"   ℹ  {self._wizard_route_note}\n\n", "note")

        # ── B: Near-term — F2Y essentials (Y1/Y2) or overdue list (Y3+) ─────────
        overdue_lines = []   # [(display_str, prog_name)] for Y3+ students

        if f2y_entries:
            if current_sem <= 4:
                any_printed = False
                for entry, prog in f2y_entries:
                    entry_label  = entry.get("label", "")
                    variant_note = entry.get("variant_note", "")
                    entry_sems   = entry.get("semesters", {})
                    upcoming = [
                        (sk, _SEM_NUM[sk]) for sk in _SEM_KEYS
                        if _SEM_NUM[sk] >= current_sem
                        and (entry_sems.get(sk, {}).get("essential")
                             or entry_sems.get(sk, {}).get("suggested"))
                    ]
                    if not upcoming:
                        continue
                    if not any_printed:
                        self._ins(t,
                            "── NEAR-TERM  (first two years) ────────────────────────────────\n",
                            "divider")
                        any_printed = True
                    header = (f"{entry_label}  —  {variant_note}"
                              if variant_note else entry_label)
                    self._ins(t, f"\n{header}\n", "h2")

                    for sk, snum in upcoming:
                        sem_data  = entry_sems.get(sk, {})
                        essential = sem_data.get("essential", [])
                        suggested = sem_data.get("suggested", [])
                        marker = "▸ " if snum == current_sem else ""
                        self._ins(t, f"\n   {marker}{_SEM_LABELS[sk]}\n", "h2")
                        if essential:
                            self._ins(t, "     Essential:\n", "hint")
                            for course in essential:
                                pcode = _f2y_primary(course)
                                if pcode:
                                    shown_codes.add(pcode)
                                if _CODE_RE.match(course):
                                    done = pcode in taken_norm if pcode else False
                                    ico  = "✓" if done else "□"
                                    tag  = "item_done" if done else "item_todo"
                                else:
                                    ico, tag = "•", "hint"
                                self._ins(t, f"       {ico}  {course}\n", tag)
                        if suggested:
                            comfort_skipped = False
                            visible_suggested = []
                            for course in suggested:
                                pcode = _f2y_primary(course)
                                # In Year 1, hide math/science suggestions when
                                # the student indicated they're not ready.
                                # Essential courses above are never filtered.
                                if pcode and snum <= 2:
                                    if not self._comfort_math and is_math_course(pcode):
                                        comfort_skipped = True
                                        continue
                                    if not self._comfort_science and is_science_course(pcode):
                                        comfort_skipped = True
                                        continue
                                visible_suggested.append((course, pcode))
                            if visible_suggested:
                                self._ins(t, "     Suggested:\n", "hint")
                                for course, pcode in visible_suggested:
                                    if pcode:
                                        shown_codes.add(pcode)
                                    if _CODE_RE.match(course):
                                        done = pcode in taken_norm if pcode else False
                                        ico  = "✓" if done else "○"
                                        tag  = "item_done" if done else "note"
                                    else:
                                        ico, tag = "○", "note"
                                    self._ins(t, f"       {ico}  {course}\n", tag)
                            if comfort_skipped:
                                self._ins(t,
                                    "     (some math/science courses omitted"
                                    " — student not ready this semester)\n",
                                    "note")

                    notes_str = entry.get("notes", "")
                    if notes_str:
                        self._ins(t, f"\n   ℹ  {notes_str}\n", "note")

            else:
                # Y3+: populate shown_codes and collect overdue essentials
                for entry, prog in f2y_entries:
                    prog_name = prog.get("name", "")
                    for sk in _SEM_KEYS:
                        for course in entry.get("semesters", {}).get(sk, {}).get("essential", []):
                            pcode = _f2y_primary(course)
                            if pcode:
                                shown_codes.add(pcode)
                                if pcode not in taken_norm:
                                    overdue_lines.append((course, prog_name))

        if overdue_lines:
            self._ins(t,
                "\n── ⚠ OVERDUE — First-Two-Year Essentials Not Yet Taken ────────────\n",
                "divider")
            for display, prog_name in overdue_lines:
                prog_str = f"  ({prog_name})" if prog_name else ""
                self._ins(t, f"   ⚠  {display}{prog_str}\n", "item_todo")

        # ── Collect required items for B/C/D from program sections ───────────────
        soon_req, mid_req, later_req = [], [], []
        flex_items  = []
        non_courses = []

        for pid in sel_ids:
            prog   = self.programs.get(pid, {})
            result = check_program(prog, taken)
            major_code = prog.get("major_code", "")
            prog_name  = prog.get("name", pid)

            for sec in result["sections"]:
                if sec["status"] == COMPLETE:
                    continue
                stype = sec.get("type", "all")
                label = sec.get("label", "")

                if stype == "non_course":
                    non_courses.append({
                        "label": label, "program": prog_name,
                        "desc":  sec.get("description", ""),
                    })
                    continue

                if stype == "all":
                    for item in sec.get("items", []):
                        if item.get("satisfied"):
                            continue
                        codes   = item.get("codes", [])
                        primary = _primary_code(codes)
                        if primary and primary in shown_codes:
                            continue   # already shown in F2Y
                        if primary:
                            shown_codes.add(primary)
                        info = (self.trajectory.course_info(major_code, primary)
                                if primary else None)
                        sem  = info["sem"] if info else None
                        pct  = info["pct"] if info else None
                        entry = {
                            "display": " / ".join(codes),
                            "title":   item.get("title", ""),
                            "program": prog_name,
                            "sem": sem, "pct": pct,
                        }
                        if sem is None or sem > current_sem + 5:
                            later_req.append(entry)
                        elif sem <= current_sem + 2:
                            soon_req.append(entry)
                        else:
                            mid_req.append(entry)

                elif stype == "choose_one":
                    opts = sec.get("options", [])
                    best_sem, best_code = None, None
                    for o in opts:
                        c0 = _primary_code(o.get("codes", []))
                        if c0:
                            inf = self.trajectory.course_info(major_code, c0)
                            if inf and inf["sem"]:
                                if best_sem is None or inf["sem"] < best_sem:
                                    best_sem = inf["sem"]
                                    best_code = c0
                    preview = "  |  ".join(
                        _primary_code(o.get("codes", [])) or o.get("title", "?")
                        for o in opts)
                    hint = f"   [earliest: {best_code}]" if best_code else ""
                    flex_items.append({
                        "label":   label,
                        "preview": preview,
                        "hint":    hint,
                        "program": prog_name,
                        "kind":    "choose_one",
                    })

                elif stype == "choose_n":
                    n      = sec.get("n", 1)
                    done_n = sec.get("satisfied_count", 0)
                    flex_items.append({
                        "label":   f"{label}  — need {n - done_n} more",
                        "program": prog_name, "kind": "flex",
                    })

                elif stype == "open_n":
                    n     = sec.get("n", 1)
                    found = len(sec.get("matching", []))
                    desc  = sec.get("description", label)
                    flex_items.append({
                        "label":   f"{desc}  — need {n - found} more",
                        "program": prog_name, "kind": "flex",
                    })

        def _render_req_bucket(items, header):
            if not items:
                return
            self._ins(t, f"\n{header}\n", "divider")
            items.sort(key=lambda x: (x.get("sem") or 99, x.get("display", "")))
            for item in items:
                sem_str  = f"  [Sem {item['sem']}]" if item.get("sem") else ""
                pct_str  = (f"  ({item['pct']:.0%} of grads)"
                            if item.get("pct") else "")
                prog_str = f"  ({item['program']})"
                title    = f"  {item['title']}" if item.get("title") else ""
                self._ins(t,
                    f"   □  {item['display']}{title}{sem_str}{pct_str}{prog_str}\n",
                    "item_todo")

        # ── B2: Trajectory-based near-term ───────────────────────────────────────
        if soon_req:
            _render_req_bucket(soon_req,
                f"── REQUIRED — NEXT UP  (traj sems ≤ {current_sem + 2}) ──────────────────────")

        # ── C: Mid-program ───────────────────────────────────────────────────────
        if mid_req:
            _render_req_bucket(mid_req,
                f"── REQUIRED — MID-PROGRAM  "
                f"(traj sems {current_sem + 3}–{current_sem + 5}) ──────────────")

        # ── D: Later / senior year ───────────────────────────────────────────────
        if later_req:
            _render_req_bucket(later_req,
                "── REQUIRED — LATER / SENIOR YEAR ──────────────────────────────")

        # ── E: Flexible / elective requirements ──────────────────────────────────
        if flex_items:
            self._ins(t,
                "\n── FLEXIBLE / ELECTIVE REQUIREMENTS ─────────────────────────────\n",
                "divider")
            for item in flex_items:
                prog_str = f"  ({item['program']})"
                if item["kind"] == "choose_one":
                    self._ins(t, f"   ◇  {item['label']}{prog_str}\n", "note")
                    self._ins(t,
                        f"      Options: {item['preview']}{item['hint']}\n", "hint")
                else:
                    self._ins(t, f"   ◇  {item['label']}{prog_str}\n", "note")

        # ── F: GE gaps ───────────────────────────────────────────────────────────
        ge_gaps = []
        for key in ("fine_arts", "humanities", "nat_sci_math",
                    "lab_science", "social_sciences"):
            req = ge_result.get(key, {})
            if not req.get("complete"):
                found_n = len(req.get("courses") or req.get("pairs") or [])
                still   = req["required"] - found_n
                ge_gaps.append(f"{req['label']}  — need {still} more")
        we_found  = len(ge_result.get("we",  {}).get("courses", []))
        dac_found = len(ge_result.get("dac", {}).get("courses", []))
        if we_found < we_required:
            ge_gaps.append(f"Writing Emphasis  — need {we_required - we_found} more")
        if dac_found < 2:
            ge_gaps.append(f"Diversity Across Curriculum  — need {2 - dac_found} more")
        if not ge_result.get("fys", {}).get("complete"):
            ge_gaps.append("First Year Seminar  — 1 required")
        if not ge_result.get("practicum", {}).get("complete"):
            ge_gaps.append("Practicum  — 1 required")

        if ge_gaps:
            self._ins(t,
                "\n── GE REQUIREMENTS STILL TO MEET ────────────────────────────────\n",
                "divider")
            for g in ge_gaps:
                self._ins(t, f"   □  {g}\n", "item_todo")

        # ── G: Non-course requirements ────────────────────────────────────────────
        if non_courses:
            self._ins(t,
                "\n── NON-COURSE REQUIREMENTS (mark when complete) ─────────────────\n",
                "divider")
            for nc in non_courses:
                self._ins(t,
                    f"   ◻  {nc['label']}  ({nc['program']})\n", "item_manual")
                if nc["desc"]:
                    self._ins(t, f"      {nc['desc']}\n", "hint")

        # ── H: Pathway requirements ───────────────────────────────────────────────
        if active_pathway_ids:
            pw_items, pw_non_courses = [], []
            for pw_id in active_pathway_ids:
                pw = self.pathways.get(pw_id)
                if not pw:
                    continue
                pw_result = check_program(pw, taken)
                pw_name   = pw.get("name", pw_id)
                for sec in pw_result["sections"]:
                    if sec["status"] == COMPLETE:
                        continue
                    stype = sec.get("type", "all")
                    label = sec.get("label", "")
                    if stype == "non_course":
                        pw_non_courses.append({
                            "label": label, "program": pw_name,
                            "desc":  sec.get("description", ""),
                        })
                        continue
                    if stype == "all":
                        for item in sec.get("items", []):
                            if item.get("satisfied"):
                                continue
                            codes   = item.get("codes", [])
                            primary = _primary_code(codes)
                            if primary and primary in shown_codes:
                                continue   # already listed above
                            if primary:
                                shown_codes.add(primary)
                            pw_items.append({
                                "display": " / ".join(codes),
                                "title":   item.get("title", ""),
                                "program": pw_name,
                            })
            if pw_items or pw_non_courses:
                self._ins(t,
                    "\n── PATHWAY REQUIREMENTS ─────────────────────────────────────────\n",
                    "divider")
                for item in pw_items:
                    title    = f"  {item['title']}" if item.get("title") else ""
                    prog_str = f"  ({item['program']})"
                    self._ins(t,
                        f"   □  {item['display']}{title}{prog_str}\n", "item_todo")
                for nc in pw_non_courses:
                    self._ins(t,
                        f"   ◻  {nc['label']}  ({nc['program']})\n", "item_manual")
                    if nc["desc"]:
                        self._ins(t, f"      {nc['desc']}\n", "hint")

        # ── I: Historical electives ───────────────────────────────────────────────
        for pid in sel_ids:
            prog = self.programs.get(pid, {})
            major_code = prog.get("major_code", "")
            if not major_code:
                continue
            exclude_set = taken_norm | shown_codes
            suggestions = self.trajectory.elective_suggestions(
                major_code, exclude=exclude_set, n=10)
            if not suggestions:
                continue
            self._ins(t,
                f"\n── COMMONLY TAKEN ELECTIVES  ({prog['name']}) ─────────────────────\n",
                "divider")
            self._ins(t,
                "   Taken by ≥15% of graduates — not automatically required.\n", "hint")
            for code, info in suggestions:
                sem_str = f"Sem {info['sem']}" if info["sem"] else "?"
                pct_str = f"{info['pct']:.0%}"
                self._ins(t,
                    f"   •  {code:<12}  {pct_str} of grads   {sem_str}\n", "note")
                shown_codes.add(code)

        t.configure(state="disabled")

    def _render_first_two_years(self, parent: tk.Frame,
                                entries: list, taken: set):
        """Render the First Two Years tab."""
        _CODE_RE = re.compile(r'^[A-Z]+-\d')

        t = self._make_text(parent)
        self._ins(t, "RECOMMENDED COURSES — FIRST TWO YEARS\n", "h1")
        self._ins(t,
            "Essential = strongly advised to take in that semester.\n"
            "Suggested = recommended but more flexible in timing.\n"
            "✓ = already completed.  □ = not yet taken.\n\n",
            "summary")

        sem_keys  = ["y1_fall", "y1_spring", "y2_fall", "y2_spring"]
        sem_labels = {
            "y1_fall":   "Year 1 — Fall",
            "y1_spring": "Year 1 — Spring",
            "y2_fall":   "Year 2 — Fall",
            "y2_spring": "Year 2 — Spring",
        }

        for entry, _prog in entries:
            label = entry.get("label", "")
            variant_note = entry.get("variant_note", "")
            self._ins(t, f"\n{'─' * 62}\n", "divider")
            self._ins(t, f"{label}\n", "h2")
            if variant_note:
                self._ins(t, f"   {variant_note}\n", "note")

            for sk in sem_keys:
                sem = entry.get("semesters", {}).get(sk, {})
                essential = sem.get("essential", [])
                suggested = sem.get("suggested", [])
                if not essential and not suggested:
                    continue
                self._ins(t, f"\n   {sem_labels[sk]}\n", "h2")

                if essential:
                    self._ins(t, "     Essential:\n", "hint")
                    for course in essential:
                        is_code = bool(_CODE_RE.match(course))
                        if is_code:
                            done = normalize(course.split()[0]) in taken
                            ico  = "✓" if done else "□"
                            tag  = "item_done" if done else "item_todo"
                        else:
                            ico, tag = "•", "hint"
                        self._ins(t, f"       {ico}  {course}\n", tag)

                if suggested:
                    self._ins(t, "     Suggested:\n", "hint")
                    for course in suggested:
                        is_code = bool(_CODE_RE.match(course))
                        if is_code:
                            done = normalize(course.split()[0]) in taken
                            ico  = "✓" if done else "○"
                            tag  = "item_done" if done else "note"
                        else:
                            ico, tag = "○", "note"
                        self._ins(t, f"       {ico}  {course}\n", tag)

            notes = entry.get("notes", "")
            if notes:
                self._ins(t, f"\n   ℹ  {notes}\n", "note")

        t.configure(state="disabled")

    # ── GE tab ────────────────────────────────────────────────────────────────

    def _render_ge(self, parent: tk.Frame, ge: dict, we_required: int):
        t = self._make_text(parent)

        self._ins(t, "GENERAL EDUCATION REQUIREMENTS  (2025–2026)\n", "h1")
        self._ins(t, "Divisional rule: ≤2 courses per prefix; each course used once.\n"
                     "Additional requirements (WE, DAC, Practicum) may overlap with divisional.\n\n",
                  "summary")

        self._ins(t, "── DIVISIONAL REQUIREMENTS ─────────────────────────────────────\n", "divider")

        for key in ("fine_arts", "humanities", "nat_sci_math", "lab_science", "social_sciences"):
            req = ge[key]
            ok  = req["complete"]
            tag = "complete" if ok else "incomplete"
            ico = "✓" if ok else "□"
            self._ins(t, f"\n{ico}  {req['label']}\n", tag)

            if key == "lab_science":
                if req["pairs"]:
                    lec, lab = req["pairs"][0]
                    self._ins(t, f"     ✓ {lec}  +  {lab}\n", "item_done")
                else:
                    self._ins(t, "     Need a lecture course + its lab (e.g. BIO-145 + BIO-145L)\n", "hint")
            else:
                pfx_str = "  ".join(req.get("prefixes", []))
                self._ins(t, f"     Prefixes: {pfx_str}\n", "hint")
                for c in req.get("courses", []):
                    self._ins(t, f"     ✓ {c}\n", "item_done")
                needed = req["required"] - len(req.get("courses", []))
                if needed > 0:
                    self._ins(t, f"     Need {needed} more course(s)\n", "item_todo")

        self._ins(t, "\n── ADDITIONAL REQUIREMENTS ────────────────────────────────────\n", "divider")

        # WE — adjust required count
        we_req  = ge["we"]
        we_found = we_req["courses"]
        we_done  = len(we_found) >= we_required
        self._ins(t, f"\n{'✓' if we_done else '□'}  Writing Emphasis ({we_required} required"
                     f"{' — adjusted for transfer credits' if we_required < 5 else ''})\n",
                  "complete" if we_done else "incomplete")
        for c in we_found:
            self._ins(t, f"     ✓ {c}\n", "item_done")
        shortfall = we_required - len(we_found)
        if shortfall > 0:
            self._ins(t, f"     Need {shortfall} more WE course(s)\n", "item_todo")
        self._ins(t, "     Note: courses with W/WE suffix (e.g. ENG-110W) are auto-detected.\n", "hint")

        # DAC
        dac_req  = ge["dac"]
        self._ins(t, f"\n{'✓' if dac_req['complete'] else '□'}  {dac_req['label']}\n",
                  "complete" if dac_req["complete"] else "incomplete")
        for c in dac_req.get("courses", []):
            self._ins(t, f"     ✓ {c}\n", "item_done")
        if not dac_req["complete"]:
            needed = dac_req["required"] - len(dac_req.get("courses", []))
            self._ins(t, f"     Need {needed} more DAC course(s)\n", "item_todo")

        # FYS & Practicum — manual checkboxes are rendered as tk widgets inline
        for key, label in (("fys", "First Year Seminar (1)"),
                           ("practicum", "Practicum (1)")):
            req = ge[key]
            ok  = req["complete"]
            tag = "complete" if ok else "incomplete"
            ico = "✓" if ok else "□"
            self._ins(t, f"\n{ico}  {label}\n", tag)
            for c in req.get("courses", []):
                self._ins(t, f"     ✓ {c}\n", "item_done")
            if req.get("note"):
                self._ins(t, f"     {req['note']}\n", "hint")
            if not ok:
                self._ins(t, "     → Mark manually in the advisor's notes\n", "note")

        t.configure(state="disabled")

    # ── Program tab ───────────────────────────────────────────────────────────

    def _traj_hint(self, major_code: str, code: str) -> str:
        """Return a short trajectory annotation string, or empty string."""
        if not major_code:
            return ""
        info = self.trajectory.course_info(major_code, code)
        if not info:
            return ""
        parts = []
        if info["sem"]:
            parts.append(f"Sem {info['sem']}")
        return f"  ← {', '.join(parts)}" if parts else ""

    def _render_program(self, parent: tk.Frame, result: dict,
                        active_pathways: list = None):
        t = self._make_text(parent)
        prog = result["program"]

        major_code = prog.get("major_code", "")
        name  = prog.get("name", "").upper()
        ptype = (prog.get("program_type") or prog.get("pathway_type") or "").upper()
        year  = prog.get("catalog_year", "")
        self._ins(t, f"{name}  {ptype}  CHECKLIST"
                     + (f"  ({year})" if year else "") + "\n", "h1")
        src = prog.get("source", "")
        if src:
            self._ins(t, f"Source: {src}\n", "summary")

        # Pathway timing banners — show when active pathways intersect this program
        pathway_notes = prog.get("pathway_notes", {})
        for pw_id in (active_pathways or []):
            note = pathway_notes.get(pw_id)
            if note:
                self._ins(t, f"{note}\n", "partial")

        timing = prog.get("timing_note", "")
        if timing:
            self._ins(t, f"{timing}\n", "partial")

        done, total = result["complete"], result["total"]
        pct = int(done / total * 100) if total else 0
        bar = ("█" * done) + ("░" * (total - done))
        self._ins(t, f"Progress: {done}/{total} sections complete ({pct}%)  {bar}\n\n",
                  "summary")

        # Collect all explicit course codes shown in required sections (for exclusion below)
        required_codes: set = set()

        for sec in result["sections"]:
            status = sec["status"]
            stype  = sec.get("type", "all")
            label  = sec.get("label", "")
            msg    = sec.get("message", "")

            if status == COMPLETE:
                ico, tag = "✓", "complete"
            elif status == PARTIAL:
                ico, tag = "◑", "partial"
            elif status == MANUAL:
                ico, tag = "◻", "manual"
            else:
                ico, tag = "□", "incomplete"

            suffix = f"  [{msg}]" if msg else ""
            self._ins(t, f"\n{ico}  {label}{suffix}\n", tag)

            if stype == "all":
                for item in sec.get("items", []):
                    codes = item.get("codes", [])
                    primary = next((normalize(c) for c in codes
                                    if not is_auxiliary(normalize(c))), None)
                    if primary:
                        required_codes.add(primary)
                    codes_str = "  /  ".join(codes)
                    title_str = item.get("title", "")
                    hint = self._traj_hint(major_code, primary) if primary else ""
                    if item.get("satisfied"):
                        self._ins(t, f"     ✓  {codes_str}    {title_str}{hint}\n", "item_done")
                    else:
                        self._ins(t, f"     □  {codes_str}    {title_str}{hint}\n", "item_todo")

            elif stype == "choose_one":
                for opt in sec.get("options", []):
                    codes = opt.get("codes", [])
                    primary = next((normalize(c) for c in codes
                                    if not is_auxiliary(normalize(c))), None)
                    if primary:
                        required_codes.add(primary)
                    codes_str = "  +  ".join(codes)
                    title_str = opt.get("title", "")
                    hint = self._traj_hint(major_code, primary) if primary else ""
                    if opt.get("satisfied"):
                        self._ins(t, f"     ✓  {codes_str}    {title_str}{hint}\n", "item_done")
                    else:
                        self._ins(t, f"     □  {codes_str}    {title_str}{hint}\n", "item_todo")

            elif stype == "choose_n":
                for item in sec.get("items", []):
                    codes = item.get("codes", [])
                    primary = next((normalize(c) for c in codes
                                    if not is_auxiliary(normalize(c))), None)
                    if primary:
                        required_codes.add(primary)
                    codes_str = "  /  ".join(codes)
                    title_str = item.get("title", "")
                    hint = self._traj_hint(major_code, primary) if primary else ""
                    if item.get("satisfied"):
                        self._ins(t, f"     ✓  {codes_str}    {title_str}{hint}\n", "item_done")
                    else:
                        self._ins(t, f"     □  {codes_str}    {title_str}{hint}\n", "item_todo")

            elif stype == "open_n":
                n = sec.get("n", 1)
                desc = sec.get("description", "")
                if desc:
                    self._ins(t, f"     {desc}\n", "hint")
                for c in sec.get("matching", []):
                    required_codes.add(c)
                    hint = self._traj_hint(major_code, c)
                    self._ins(t, f"     ✓  {c}{hint}\n", "item_done")
                remaining = n - len(sec.get("matching", []))
                if remaining > 0:
                    self._ins(t, f"     □  {remaining} more elective(s) needed\n", "item_todo")

            elif stype == "non_course":
                desc = sec.get("description", "")
                self._ins(t, f"     ◻  {desc}\n", "item_manual")

            # Section-level note
            if sec.get("note"):
                self._ins(t, f"     ℹ  {sec['note']}\n", "note")

        # Recommended (programs use plain strings; pathways use {codes, title} dicts)
        if prog.get("recommended"):
            self._ins(t, "\n── RECOMMENDED ────────────────────────────────────────────────\n",
                      "divider")
            for rec in prog["recommended"]:
                if isinstance(rec, dict):
                    codes_str = "  /  ".join(rec.get("codes", []))
                    title_str = rec.get("title", "")
                    sat = any(normalize(c) in result.get("_taken", set())
                              for c in rec.get("codes", []))
                    pfx = "✓" if sat else "•"
                    self._ins(t, f"   {pfx}  {codes_str}    {title_str}\n", "note")
                else:
                    self._ins(t, f"   • {rec}\n", "note")

        # Notes
        if prog.get("notes"):
            self._ins(t, "\n── NOTES ──────────────────────────────────────────────────────\n",
                      "divider")
            self._ins(t, f"   {prog['notes']}\n", "note")

        # Trajectory-based elective suggestions
        if major_code:
            suggestions = self.trajectory.elective_suggestions(
                major_code, exclude=required_codes)
            if suggestions:
                self._ins(t,
                    "\n── COMMONLY TAKEN ELECTIVES  (from historical student data) ───\n",
                    "divider")
                self._ins(t,
                    "   Courses taken by ≥15% of graduates — not automatically required.\n",
                    "hint")
                for code, info in suggestions:
                    sem_str = f"Sem {info['sem']}" if info["sem"] else "?"
                    pct_str = f"{info['pct']:.0%}"
                    self._ins(t,
                        f"   • {code:<12}  {pct_str} of grads   {sem_str}\n",
                        "note")

        t.configure(state="disabled")


# ─────────────────────────── Entry point ─────────────────────────────────────

def main():
    root = ctk.CTk()
    AdvisorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
