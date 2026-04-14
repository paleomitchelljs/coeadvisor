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
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
from pathlib import Path
from datetime import datetime

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

# ─────────────────────────── Course utilities ────────────────────────────────

def normalize(code: str) -> str:
    """Normalize a course code to PREFIX-NUMBER format."""
    code = code.strip().upper().replace(" ", "")
    m = re.match(r'^([A-Z]+)-?(\d+[A-Z]*)$', code)
    return f"{m.group(1)}-{m.group(2)}" if m else code


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

    we_found  = sorted(c for c in taken if c in we  and not is_auxiliary(c))
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
                           "note": "Only courses in the WE database are auto-detected"},
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
    "complete":   "#1e8449",
    "partial":    "#b7770d",
    "incomplete": "#c0392b",
    "manual":     "#2471a3",
    "header":     "#1a1a2e",
    "hint":       "#7f8c8d",
    "note":       "#566573",
    "bg":         "#ffffff",
    "panel_bg":   "#f2f3f4",
}

GRADES = ["", "A", "A-", "B+", "B", "B-", "C+", "C", "C-",
          "D+", "D", "D-", "F", "P", "NP", "W", "IP"]

STUDENT_YEARS = ["First Year", "Sophomore", "Junior", "Senior", "Transfer Student"]


class AdvisorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Coe College Academic Advising Tool")
        self.root.geometry("1080x740")
        self.root.minsize(800, 600)

        # ── Load data ──
        try:
            self.programs       = load_programs()
            self.ge_data        = load_ge()
            self.dac            = load_dac()
            self.we             = load_we()
            self.course_credits = load_course_credits()
            self.pathways       = load_pathways()
            self.first_two_years = load_first_two_years()
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

    # ──────────────────────────────────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header bar with page-toggle tabs ─────────────────────────────────
        top = tk.Frame(self.root, bg="#1a1a2e", height=48)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        tk.Label(top, text="  Coe College  |  Academic Advising Tool",
                 bg="#1a1a2e", fg="white",
                 font=("Helvetica", 13, "bold")).pack(side=tk.LEFT, padx=12, pady=10)

        tab_bar = tk.Frame(top, bg="#1a1a2e")
        tab_bar.pack(side=tk.RIGHT, padx=12, pady=6)
        self._tab_btns = {}
        for key, label in [("setup", "  Student Setup  "),
                            ("results", "  Check Requirements  ")]:
            btn = tk.Button(tab_bar, text=label,
                            font=("Helvetica", 10),
                            relief=tk.FLAT, bd=0, cursor="hand2",
                            padx=8, pady=4,
                            command=lambda k=key: self._switch_page(k))
            btn.pack(side=tk.LEFT, padx=2)
            self._tab_btns[key] = btn

        # ── Full-window page frames ───────────────────────────────────────────
        self.page_setup   = tk.Frame(self.root, bg=COLORS["panel_bg"])
        self.page_results = tk.Frame(self.root, bg=COLORS["bg"])

        self._build_setup_page(self.page_setup)
        self._build_results_page(self.page_results)

        self._switch_page("setup")   # start on setup page

    def _switch_page(self, name: str):
        """Show one page, hide the other, update tab button styles."""
        pages = {"setup": self.page_setup, "results": self.page_results}
        for key, frame in pages.items():
            if key == name:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()
        for key, btn in self._tab_btns.items():
            if key == name:
                btn.configure(bg="#3a3a6e", fg="white")
            else:
                btn.configure(bg="#1a1a2e", fg="#9999bb")

    def _build_setup_page(self, parent: tk.Frame):
        """Full-width student-setup page with scrollable content."""
        BG = COLORS["panel_bg"]

        # Scrollable canvas fills the page
        _canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        _vsb    = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=_canvas.yview)
        _canvas.configure(yscrollcommand=_vsb.set)
        _vsb.pack(side=tk.RIGHT, fill=tk.Y)
        _canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        f = tk.Frame(_canvas, bg=BG)
        _win = _canvas.create_window((0, 0), window=f, anchor="nw")

        f.bind("<Configure>",
               lambda e: _canvas.configure(scrollregion=_canvas.bbox("all")))
        _canvas.bind("<Configure>",
                     lambda e: _canvas.itemconfig(_win, width=e.width))

        def _mw(e):
            if e.delta:
                _canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        _canvas.bind("<Enter>", lambda e: _canvas.bind_all("<MouseWheel>", _mw))
        _canvas.bind("<Leave>", lambda e: _canvas.unbind_all("<MouseWheel>"))

        # ── Import button ─────────────────────────────────────────────────────
        imp = tk.Frame(f, bg=BG)
        imp.pack(fill=tk.X, padx=24, pady=(18, 4))
        ttk.Button(imp, text="Load Student File",
                   command=self.load_student).pack(side=tk.LEFT)
        tk.Label(imp, text="───  or fill in below  ───",
                 bg=BG, fg="#999999",
                 font=("Helvetica", 9, "italic")).pack(side=tk.LEFT, padx=16)

        # ── Two-column: Student (left) | Programs (right) ─────────────────────
        self._two_col_frame = tk.Frame(f, bg=BG)
        self._two_col_frame.pack(fill=tk.X, padx=24, pady=(4, 8))
        self._two_col_frame.columnconfigure(0, weight=1)
        self._two_col_frame.columnconfigure(1, weight=2)

        def _panel(parent_grid, col, title):
            outer = tk.Frame(parent_grid, bg="#cccccc")
            outer.grid(row=0, column=col,
                       padx=(0, 12) if col == 0 else (0, 0),
                       pady=0, sticky="nsew")
            inner = tk.Frame(outer, bg=COLORS["bg"])
            inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
            tk.Label(inner, text=title,
                     font=("Helvetica", 9, "bold"),
                     bg=COLORS["bg"], fg="#333333").pack(anchor=tk.W, padx=14, pady=(10, 2))
            tk.Frame(inner, bg="#dddddd", height=1).pack(fill=tk.X, padx=14, pady=(0, 6))
            content = tk.Frame(inner, bg=COLORS["bg"])
            content.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 10))
            return content

        # Student panel
        sp = _panel(self._two_col_frame, 0, "STUDENT")
        pad = {"padx": 10, "pady": 2}
        for lbl, attr in [("Name:", "name_var"), ("Student ID:", "id_var")]:
            tk.Label(sp, text=lbl, bg=COLORS["bg"],
                     font=("Helvetica", 9)).pack(anchor=tk.W, **pad)
            var = tk.StringVar()
            setattr(self, attr, var)
            ttk.Entry(sp, textvariable=var).pack(fill=tk.X, padx=10, pady=1)

        tk.Label(sp, text="Year:", bg=COLORS["bg"],
                 font=("Helvetica", 9)).pack(anchor=tk.W, **pad)
        self._year_var = tk.StringVar(value=STUDENT_YEARS[0])
        ttk.Combobox(sp, textvariable=self._year_var,
                     values=STUDENT_YEARS, state="readonly",
                     width=22).pack(anchor=tk.W, padx=10, pady=1)

        tk.Label(sp, text="Transfer credits (WE):", bg=COLORS["bg"],
                 font=("Helvetica", 9)).pack(anchor=tk.W, **pad)
        self.transfer_var = tk.StringVar(value="0 credits (5 WE)")
        ttk.Combobox(sp, textvariable=self.transfer_var, width=22,
                     values=["0 credits (5 WE)",
                             "1–7 credits (5 WE)",
                             "8 credits — max (3 WE)"],
                     state="readonly").pack(anchor=tk.W, padx=10, pady=1)

        # Programs panel
        pp = _panel(self._two_col_frame, 1, "PROGRAMS")

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
        self._display_to_pid = {**self._major_display_to_pid, **self._minor_display_to_pid}
        self._pid_to_display = {}
        for pid, p in major_progs + minor_progs:
            self._pid_to_display[pid] = _prog_display(p)

        # Lay programs out in two sub-columns within the programs panel
        pp.columnconfigure(0, weight=1)
        pp.columnconfigure(1, weight=1)

        maj_labels = ["Major:", "Major 2 (optional):", "Major 3 (optional):"]
        for i in range(3):
            row_f = tk.Frame(pp, bg=COLORS["bg"])
            row_f.grid(row=i, column=0, columnspan=2, sticky="ew", padx=4, pady=2)
            tk.Label(row_f, text=maj_labels[i], width=18, anchor="w",
                     bg=COLORS["bg"], font=("Helvetica", 9)).pack(side=tk.LEFT)
            var = tk.StringVar(value=NONE_OPT)
            self._major_vars.append(var)
            ttk.Combobox(row_f, textvariable=var,
                         values=major_names, state="readonly",
                         width=28).pack(side=tk.LEFT, fill=tk.X, expand=True)

        min_labels = ["Minor (optional):", "Minor 2 (optional):"]
        for i in range(2):
            row_f = tk.Frame(pp, bg=COLORS["bg"])
            row_f.grid(row=3 + i, column=0, columnspan=2, sticky="ew", padx=4, pady=2)
            tk.Label(row_f, text=min_labels[i], width=18, anchor="w",
                     bg=COLORS["bg"], font=("Helvetica", 9)).pack(side=tk.LEFT)
            var = tk.StringVar(value=NONE_OPT)
            self._minor_vars.append(var)
            ttk.Combobox(row_f, textvariable=var,
                         values=minor_names, state="readonly",
                         width=28).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ── Pathways (conditional, horizontal) ───────────────────────────────
        self._pw_container = tk.Frame(f, bg=BG)
        # establish pack order now, then hide
        self._pw_container.pack(fill=tk.X, padx=24, pady=(0, 4))
        self._pw_container.pack_forget()

        pw_outer = tk.Frame(self._pw_container, bg="#cccccc")
        pw_outer.pack(fill=tk.X)
        pw_inner = tk.Frame(pw_outer, bg=COLORS["bg"])
        pw_inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        tk.Label(pw_inner, text="PATHWAYS  (optional — check to add results tab)",
                 font=("Helvetica", 9, "bold"), bg=COLORS["bg"],
                 fg="#333333").pack(anchor=tk.W, padx=14, pady=(8, 2))
        tk.Frame(pw_inner, bg="#dddddd", height=1).pack(fill=tk.X, padx=14, pady=(0, 6))
        self._pw_rows_frame = tk.Frame(pw_inner, bg=COLORS["bg"])
        self._pw_rows_frame.pack(anchor=tk.W, padx=10, pady=(0, 8))

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
            row = tk.Frame(self._pw_rows_frame, bg=COLORS["bg"])
            ttk.Checkbutton(row, text=pw_label,
                            variable=var).pack(anchor=tk.W)
            self._pathway_rows[pw_id] = row

        # ── Track / variant selector (shown when a program has multiple F2Y tracks) ─
        self._variant_container = tk.Frame(f, bg=BG)
        self._variant_container.pack(fill=tk.X, padx=24, pady=(0, 4))
        self._variant_container.pack_forget()

        va_outer = tk.Frame(self._variant_container, bg="#cccccc")
        va_outer.pack(fill=tk.X)
        va_inner = tk.Frame(va_outer, bg=COLORS["bg"])
        va_inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        tk.Label(va_inner,
                 text="TRACK / CONCENTRATION  (select the path that best fits this student)",
                 font=("Helvetica", 9, "bold"), bg=COLORS["bg"],
                 fg="#333333").pack(anchor=tk.W, padx=14, pady=(8, 2))
        tk.Frame(va_inner, bg="#dddddd", height=1).pack(fill=tk.X, padx=14, pady=(0, 6))
        self._variant_rows_frame = tk.Frame(va_inner, bg=COLORS["bg"])
        self._variant_rows_frame.pack(anchor=tk.W, padx=10, pady=(0, 8))

        # Traces after pathway/variant structures are built
        for var in self._major_vars + self._minor_vars:
            var.trace_add("write", lambda *_: self._update_pathway_visibility())
            var.trace_add("write", lambda *_: self._update_variant_visibility())

        # ── Courses by semester ───────────────────────────────────────────────
        hdr_f = tk.Frame(f, bg=BG)
        hdr_f.pack(fill=tk.X, padx=24, pady=(6, 0))
        tk.Label(hdr_f, text="COURSES BY SEMESTER",
                 font=("Helvetica", 10, "bold"), bg=BG,
                 fg="#333333").pack(side=tk.LEFT)
        tk.Label(hdr_f, text="   ☑ = completed   ☐ = planned",
                 font=("Helvetica", 8, "italic"), bg=BG,
                 fg=COLORS["hint"]).pack(side=tk.LEFT, padx=8)
        tk.Frame(f, bg="#cccccc", height=1).pack(fill=tk.X, padx=24, pady=(4, 6))

        self._courses_area = tk.Frame(f, bg=BG)
        self._courses_area.pack(fill=tk.X, padx=18)
        for col in range(3):
            self._courses_area.columnconfigure(col, weight=1, minsize=260)

        self._add_semester("Transfer", initial_rows=2, is_transfer=True)
        for i in range(1, 5):
            self._add_semester(f"Semester {i}", initial_rows=3)

        # "+ Add Semester" below grid
        add_sem_f = tk.Frame(f, bg=BG)
        add_sem_f.pack(fill=tk.X, padx=24, pady=(4, 6))
        tk.Button(add_sem_f, text="+ Add Semester",
                  font=("Helvetica", 9), relief=tk.FLAT,
                  bg="#d5e8f0", fg="#2c5f8a", cursor="hand2",
                  command=self._add_next_semester).pack(anchor=tk.W)

        # ── Bottom action bar ─────────────────────────────────────────────────
        bot = tk.Frame(f, bg=BG)
        bot.pack(fill=tk.X, padx=24, pady=(8, 20))

        ttk.Button(bot, text="Save Student File",
                   command=self.save_student).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bot, text="Clear All",
                   command=self.clear_all).pack(side=tk.LEFT)
        ttk.Button(bot, text="Check Requirements  →",
                   command=self.check).pack(side=tk.RIGHT)

    def _build_results_page(self, parent: tk.Frame):
        """Full-width results page: summary + tabbed requirement checks."""
        self.summary_var = tk.StringVar(
            value="Fill in the Student Setup page and click Check Requirements.")
        tk.Label(parent, textvariable=self.summary_var,
                 bg=COLORS["bg"], font=("Helvetica", 10),
                 wraplength=1020, justify=tk.LEFT,
                 fg=COLORS["note"]).pack(anchor=tk.W, padx=20, pady=(12, 4))
        self.nb = ttk.Notebook(parent)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))


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
        """Create a semester box and place it in the 3-column grid."""
        idx = len(self._semesters)
        BG  = COLORS["panel_bg"]
        HDR = "#3a7ca5" if is_transfer else "#2c3e50"

        outer = tk.Frame(self._courses_area, bg="#cccccc", relief=tk.FLAT)
        outer.grid(row=idx // 3, column=idx % 3, sticky="nsew", padx=4, pady=4)
        # ensure all 3 columns grow equally
        self._courses_area.columnconfigure(idx % 3, weight=1, minsize=260)

        inner = tk.Frame(outer, bg=BG)
        inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        hdr = tk.Frame(inner, bg=HDR)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text=label, font=("Helvetica", 9, "bold"),
                 bg=HDR, fg="white").pack(side=tk.LEFT, padx=8, pady=3)

        rows_frame = tk.Frame(inner, bg=BG)
        rows_frame.pack(fill=tk.X, padx=4, pady=4)

        sem_dict = {"label": label, "frame": outer, "rows": [],
                    "rows_frame": rows_frame, "is_transfer": is_transfer}
        self._semesters.append(sem_dict)

        for _ in range(initial_rows):
            self._add_course_row(sem_dict)

        add_btn = tk.Button(inner, text="+ course",
                            font=("Helvetica", 8), relief=tk.FLAT,
                            bg=BG, fg="#2c5f8a", cursor="hand2",
                            command=lambda sd=sem_dict: self._add_course_row(sd))
        add_btn.pack(anchor=tk.W, padx=8, pady=(0, 4))

        return sem_dict

    def _add_course_row(self, sem_dict: dict, code: str = "",
                        grade: str = "", completed: bool = True):
        """Append one course-entry row to a semester box."""
        BG = COLORS["panel_bg"]
        rf = sem_dict["rows_frame"]
        row_f = tk.Frame(rf, bg=BG)
        row_f.pack(fill=tk.X, pady=1)

        completed_var = tk.BooleanVar(value=completed)
        ttk.Checkbutton(row_f, variable=completed_var).pack(side=tk.LEFT)

        code_var = tk.StringVar(value=code)
        tk.Entry(row_f, textvariable=code_var, width=10,
                 font=("Courier", 9)).pack(side=tk.LEFT, padx=(2, 2))

        grade_var = tk.StringVar(value=grade)
        ttk.Combobox(row_f, textvariable=grade_var,
                     values=GRADES, state="readonly",
                     width=4).pack(side=tk.LEFT)

        row_dict = {"code_var": code_var, "grade_var": grade_var,
                    "completed_var": completed_var, "frame": row_f}

        def _delete(rd=row_dict, sd=sem_dict):
            rd["frame"].destroy()
            if rd in sd["rows"]:
                sd["rows"].remove(rd)

        tk.Button(row_f, text="×", font=("Helvetica", 10), relief=tk.FLAT,
                  bg=BG, fg="#cc0000", cursor="hand2",
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
        for i in range(1, 5):
            self._add_semester(f"Semester {i}", initial_rows=3)

    # ──────────────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────────────

    def check(self):
        sel_ids = self._selected_program_ids()
        taken   = self._collect_courses()

        # WE count adjustment for transfer students
        we_required = 3 if "8 credits" in self.transfer_var.get() else 5

        # Clear tabs
        for tab in self.nb.tabs():
            self.nb.forget(tab)
        self.manual_ge.clear()

        # GE tab
        ge_result = check_ge(self.ge_data, taken, self.dac, self.we)
        ge_frame  = tk.Frame(self.nb, bg=COLORS["bg"])
        self.nb.add(ge_frame, text="GE Requirements")
        self._render_ge(ge_frame, ge_result, we_required)

        # Active pathways
        active_pathway_ids = [pid for pid, var in self.pathway_vars.items()
                              if var.get()]

        # Program tabs
        for pid in sel_ids:
            prog   = self.programs[pid]
            result = check_program(prog, taken)
            frame  = tk.Frame(self.nb, bg=COLORS["bg"])
            ptype  = prog.get("program_type", "").title()
            self.nb.add(frame, text=f"{prog['name']} ({ptype})")
            self._render_program(frame, result, active_pathways=active_pathway_ids)

        # Pathway tabs
        for pw_id in active_pathway_ids:
            pw     = self.pathways[pw_id]
            result = check_program(pw, taken)
            frame  = tk.Frame(self.nb, bg=COLORS["bg"])
            self.nb.add(frame, text=f"\u2b21 {pw['name']}")
            self._render_program(frame, result)

        # First Two Years tab
        f2y_entries = self._matching_first_two_years(sel_ids)
        if f2y_entries:
            frame = tk.Frame(self.nb, bg=COLORS["bg"])
            self.nb.add(frame, text="First 2 Years")
            self._render_first_two_years(frame, f2y_entries, taken)

        # Suggested Plan tab
        if sel_ids:
            frame = tk.Frame(self.nb, bg=COLORS["bg"])
            self.nb.add(frame, text="Suggested Plan")
            self._render_suggested_plan(frame, sel_ids, taken, ge_result, we_required)

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

    def clear_all(self):
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
        for tab in self.nb.tabs():
            self.nb.forget(tab)
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
        for tab_id in self.nb.tabs():
            tab_text = self.nb.tab(tab_id, "text")
            widget   = self.nb.nametowidget(tab_id)
            for child in widget.winfo_children():
                for subchild in child.winfo_children():
                    if isinstance(subchild, tk.Text):
                        lines.append(f"\n{'=' * 60}")
                        lines.append(tab_text.upper())
                        lines.append('=' * 60)
                        lines.append(subchild.get("1.0", tk.END).strip())
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

    def _make_text(self, parent: tk.Frame) -> tk.Text:
        frame = tk.Frame(parent, bg=COLORS["bg"])
        frame.pack(fill=tk.BOTH, expand=True)
        vsb = ttk.Scrollbar(frame)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        t = tk.Text(frame, wrap=tk.WORD, padx=14, pady=10,
                    font=("Courier", 10), bg=COLORS["bg"],
                    relief=tk.FLAT, yscrollcommand=vsb.set,
                    cursor="arrow")
        t.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.config(command=t.yview)

        t.tag_configure("h1",     font=("Helvetica", 13, "bold"), foreground=COLORS["header"], spacing3=6)
        t.tag_configure("h2",     font=("Helvetica", 10, "bold"), foreground=COLORS["header"], spacing1=8, spacing3=2)
        t.tag_configure("divider",font=("Courier",  8),           foreground="#cccccc", spacing1=6)
        t.tag_configure("summary",font=("Helvetica", 9),          foreground=COLORS["note"])
        t.tag_configure("complete",   font=("Helvetica", 10, "bold"), foreground=COLORS["complete"])
        t.tag_configure("partial",    font=("Helvetica", 10, "bold"), foreground=COLORS["partial"])
        t.tag_configure("incomplete", font=("Helvetica", 10, "bold"), foreground=COLORS["incomplete"])
        t.tag_configure("manual",     font=("Helvetica", 10, "bold"), foreground=COLORS["manual"])
        t.tag_configure("item_done",  font=("Courier", 10),           foreground=COLORS["complete"])
        t.tag_configure("item_todo",  font=("Courier", 10),           foreground=COLORS["incomplete"])
        t.tag_configure("item_manual",font=("Courier", 10),           foreground=COLORS["manual"])
        t.tag_configure("hint",       font=("Courier",  9),           foreground=COLORS["hint"])
        t.tag_configure("note",       font=("Courier",  9, "italic"), foreground=COLORS["note"])
        return t

    def _ins(self, t: tk.Text, text: str, tag: str = ""):
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

            grp = tk.Frame(self._variant_rows_frame, bg=COLORS["bg"])
            grp.pack(anchor=tk.W, padx=4, pady=(4, 2))
            tk.Label(grp, text=f"{prog_name}:", bg=COLORS["bg"],
                     font=("Helvetica", 9, "bold")).pack(anchor=tk.W)

            var = tk.StringVar(value=entries[0]["id"])
            self._variant_vars[pid] = var
            for entry in entries:
                lbl = entry.get("label", entry["id"])
                vn  = entry.get("variant_note", "")
                display = lbl + (f"  —  {vn}" if vn else "")
                ttk.Radiobutton(grp, text=display, variable=var,
                                value=entry["id"]).pack(anchor=tk.W, padx=20)

        if any_visible:
            self._variant_container.pack(fill=tk.X, padx=24, pady=(0, 4))
        else:
            self._variant_container.pack_forget()

    def _render_suggested_plan(self, parent: tk.Frame, sel_ids: list,
                               taken: set, ge_result: dict, we_required: int):
        """Render a semester-ordered plan of what remains to be completed."""
        t = self._make_text(parent)
        self._ins(t, "SUGGESTED COURSE PLAN\n", "h1")
        self._ins(t,
            "Required courses are sorted by typical semester (from historical student data).\n"
            "✓ = already completed.  □ = still needed.  ◇ = flexible / choose-from list.\n\n",
            "summary")

        # ── Gather all unsatisfied requirements across selected programs ────────
        soon, mid, later, flex, non_courses = [], [], [], [], []

        for pid in sel_ids:
            prog = self.programs.get(pid, {})
            result = check_program(prog, taken)
            major_code = prog.get("major_code", "")
            prog_name = prog.get("name", pid)

            for sec in result["sections"]:
                if sec["status"] == COMPLETE:
                    continue
                stype = sec.get("type", "all")
                label = sec.get("label", "")

                if stype == "non_course":
                    non_courses.append({
                        "label": label, "program": prog_name,
                        "desc": sec.get("description", ""),
                    })
                    continue

                if stype == "all":
                    for item in sec.get("items", []):
                        if item.get("satisfied"):
                            continue
                        codes = item.get("codes", [])
                        primary = next(
                            (normalize(c) for c in codes if not is_auxiliary(normalize(c))),
                            None)
                        info = self.trajectory.course_info(major_code, primary) if primary else None
                        sem  = info["sem"] if info else None
                        pct  = info["pct"] if info else None
                        entry = {
                            "display": " / ".join(codes),
                            "title":   item.get("title", ""),
                            "program": prog_name,
                            "sem": sem, "pct": pct,
                            "kind": "req",
                        }
                        if   sem is None: flex.append(entry)
                        elif sem <= 3:    soon.append(entry)
                        elif sem <= 6:    mid.append(entry)
                        else:             later.append(entry)

                elif stype == "choose_one":
                    opts = sec.get("options", [])
                    codes_preview = " / ".join(
                        (o.get("codes") or [""])[0]
                        for o in opts if o.get("codes"))
                    best_sem = None
                    for o in opts:
                        c0 = (o.get("codes") or [""])[0]
                        if c0:
                            inf = self.trajectory.course_info(major_code, normalize(c0))
                            if inf and inf["sem"]:
                                if best_sem is None or inf["sem"] < best_sem:
                                    best_sem = inf["sem"]
                    flex.append({
                        "display": f"{label}  [{codes_preview}]",
                        "title": "", "program": prog_name,
                        "sem": best_sem, "pct": None, "kind": "flex",
                    })

                elif stype == "choose_n":
                    n = sec.get("n", 1)
                    done_n = sec.get("satisfied_count", 0)
                    flex.append({
                        "display": f"{label}  (need {n - done_n} more)",
                        "title": "", "program": prog_name,
                        "sem": None, "pct": None, "kind": "flex",
                    })

                elif stype == "open_n":
                    n = sec.get("n", 1)
                    found = len(sec.get("matching", []))
                    desc  = sec.get("description", label)
                    flex.append({
                        "display": f"{desc}  (need {n - found} more)",
                        "title": "", "program": prog_name,
                        "sem": None, "pct": None, "kind": "flex",
                    })

        def _render_bucket(items, header):
            if not items:
                return
            self._ins(t, f"\n{header}\n", "divider")
            items.sort(key=lambda x: (x.get("sem") or 99, x.get("display", "")))
            for item in items:
                sem_str = f"   [Sem {item['sem']}]" if item.get("sem") else ""
                pct_str = f"  {item['pct']:.0%} of grads" if item.get("pct") else ""
                prog_str = f"  ({item['program']})"
                title    = f"    {item['title']}" if item.get("title") else ""
                if item["kind"] == "flex":
                    self._ins(t, f"   ◇  {item['display']}{prog_str}\n", "note")
                else:
                    self._ins(t,
                        f"   □  {item['display']}{title}{sem_str}{pct_str}{prog_str}\n",
                        "item_todo")

        _render_bucket(soon,  "── COMPLETE SOON  (typically sems 1–3) ─────────────────────────")
        _render_bucket(mid,   "── MID-PROGRAM  (typically sems 4–6) ───────────────────────────")
        _render_bucket(later, "── LATER  (typically sems 7+) ───────────────────────────────────")
        _render_bucket(flex,  "── FLEXIBLE / ELECTIVE REQUIREMENTS ─────────────────────────────")

        # ── GE gaps ───────────────────────────────────────────────────────────
        ge_gaps = []
        for key in ("fine_arts", "humanities", "nat_sci_math", "lab_science", "social_sciences"):
            req = ge_result.get(key, {})
            if not req.get("complete"):
                found_n = len(req.get("courses") or req.get("pairs") or [])
                still   = req["required"] - found_n
                ge_gaps.append(f"{req['label']}  — need {still} more")
        we_found = len(ge_result.get("we", {}).get("courses", []))
        if we_found < we_required:
            ge_gaps.append(f"Writing Emphasis  — need {we_required - we_found} more")
        dac_found = len(ge_result.get("dac", {}).get("courses", []))
        if dac_found < 2:
            ge_gaps.append(f"Diversity Across Curriculum  — need {2 - dac_found} more")
        if not ge_result.get("fys", {}).get("complete"):
            ge_gaps.append("First Year Seminar  — 1 required")
        if not ge_result.get("practicum", {}).get("complete"):
            ge_gaps.append("Practicum  — 1 required")

        if ge_gaps:
            self._ins(t, "\n── GE REQUIREMENTS STILL TO MEET ────────────────────────────────\n",
                      "divider")
            for g in ge_gaps:
                self._ins(t, f"   □  {g}\n", "item_todo")

        # ── Non-course reminders ──────────────────────────────────────────────
        if non_courses:
            self._ins(t, "\n── NON-COURSE REQUIREMENTS (mark when complete) ─────────────────\n",
                      "divider")
            for nc in non_courses:
                self._ins(t, f"   ◻  {nc['label']}  ({nc['program']})\n", "item_manual")
                if nc["desc"]:
                    self._ins(t, f"      {nc['desc']}\n", "hint")

        # ── Historical electives ──────────────────────────────────────────────
        shown_elec_header = set()
        for pid in sel_ids:
            prog = self.programs.get(pid, {})
            major_code = prog.get("major_code", "")
            if not major_code:
                continue
            suggestions = self.trajectory.elective_suggestions(major_code, exclude=taken, n=10)
            if not suggestions:
                continue
            if major_code not in shown_elec_header:
                self._ins(t,
                    f"\n── COMMONLY TAKEN ELECTIVES  ({prog['name']}) ──────────────────────\n",
                    "divider")
                self._ins(t, "   Taken by ≥15% of graduates — not automatically required.\n", "hint")
                shown_elec_header.add(major_code)
            for code, info in suggestions:
                sem_str = f"Sem {info['sem']}" if info["sem"] else "?"
                pct_str = f"{info['pct']:.0%}"
                self._ins(t,
                    f"   •  {code:<12}  {pct_str} of grads   {sem_str}\n", "note")

        t.config(state=tk.DISABLED)

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

        t.config(state=tk.DISABLED)

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
        self._ins(t, "     Note: only courses in the WE database are auto-detected.\n", "hint")

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

        t.config(state=tk.DISABLED)

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

        t.config(state=tk.DISABLED)


# ─────────────────────────── Entry point ─────────────────────────────────────

def main():
    root = tk.Tk()
    try:
        # Use a clean theme
        style = ttk.Style(root)
        for theme in ("aqua", "clam", "alt", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
    except Exception:
        pass
    AdvisorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
