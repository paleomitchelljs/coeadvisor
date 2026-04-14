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
    sat = bool(primary and primary[0] in taken) or (not primary and bool(found))
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
    fys_found = [c for c in taken if prefix_of(c) == "FYS"]
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


class AdvisorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Coe College Academic Advising Tool")
        self.root.geometry("1080x740")
        self.root.minsize(800, 600)

        # ── Load data ──
        try:
            self.programs      = load_programs()
            self.ge_data       = load_ge()
            self.dac           = load_dac()
            self.we            = load_we()
            self.course_credits = load_course_credits()
            self.pathways      = load_pathways()
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
        self._prog_ids: list[str] = []

        self._build_ui()

    # ──────────────────────────────────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Top bar
        top = tk.Frame(self.root, bg="#1a1a2e", height=44)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        tk.Label(top, text="  Coe College  |  Academic Advising Tool",
                 bg="#1a1a2e", fg="white",
                 font=("Helvetica", 13, "bold")).pack(side=tk.LEFT, padx=12, pady=8)

        # Main paned area
        pw = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(pw, bg=COLORS["panel_bg"], width=290)
        left.pack_propagate(False)
        pw.add(left, weight=0)

        right = tk.Frame(pw, bg=COLORS["bg"])
        pw.add(right, weight=1)

        self._build_left(left)
        self._build_right(right)

    def _build_left(self, parent: tk.Frame):
        pad = {"padx": 10, "pady": 3}

        # Student name
        sec = self._section_frame(parent, "STUDENT")
        tk.Label(sec, text="Name:", bg=COLORS["panel_bg"],
                 font=("Helvetica", 9)).pack(anchor=tk.W, **pad)
        self.name_var = tk.StringVar()
        ttk.Entry(sec, textvariable=self.name_var).pack(fill=tk.X, padx=10, pady=2)

        tk.Label(sec, text="ID:", bg=COLORS["panel_bg"],
                 font=("Helvetica", 9)).pack(anchor=tk.W, **pad)
        self.id_var = tk.StringVar()
        ttk.Entry(sec, textvariable=self.id_var).pack(fill=tk.X, padx=10, pady=2)

        tk.Label(sec, text="Transfer credits (Coe credits):",
                 bg=COLORS["panel_bg"], font=("Helvetica", 9)).pack(anchor=tk.W, **pad)
        self.transfer_var = tk.StringVar(value="0 credits (5 WE)")
        ttk.Combobox(sec, textvariable=self.transfer_var, width=22,
                     values=["0 credits (5 WE)",
                             "1–7 credits (5 WE)",
                             "8 credits — max (3 WE)"],
                     state="readonly").pack(anchor=tk.W, padx=10, pady=2)

        # Programs
        sec2 = self._section_frame(parent, "PROGRAMS  (Ctrl+click = multi-select)")
        prog_frame = tk.Frame(sec2, bg=COLORS["panel_bg"])
        prog_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        vsb = ttk.Scrollbar(prog_frame)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.prog_lb = tk.Listbox(prog_frame, selectmode=tk.MULTIPLE,
                                  yscrollcommand=vsb.set, height=12,
                                  exportselection=False,
                                  font=("Helvetica", 9),
                                  activestyle="none",
                                  bg="white", relief=tk.FLAT)
        self.prog_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.config(command=self.prog_lb.yview)

        # Populate listbox — sorted by type (major first) then name
        def sort_key(item):
            pid, prog = item
            order = {"major": 0, "minor": 1, "collateral": 2, "certificate": 3}
            return (order.get(prog.get("program_type", ""), 9), prog.get("name", ""))

        self._prog_ids = []
        for pid, prog in sorted(self.programs.items(), key=sort_key):
            ptype = prog.get("program_type", "").title()
            year  = prog.get("catalog_year", "")
            self.prog_lb.insert(tk.END, f"{prog['name']} — {ptype} ({year})")
            self._prog_ids.append(pid)

        # Pathways
        sec_pw = self._section_frame(parent, "PATHWAYS  (optional — check to add tab)")
        pw_canvas = tk.Canvas(sec_pw, bg=COLORS["panel_bg"],
                              highlightthickness=0, height=90)
        pw_scroll = ttk.Scrollbar(sec_pw, orient=tk.VERTICAL,
                                  command=pw_canvas.yview)
        pw_inner  = tk.Frame(pw_canvas, bg=COLORS["panel_bg"])
        pw_inner.bind("<Configure>",
                      lambda e: pw_canvas.configure(
                          scrollregion=pw_canvas.bbox("all")))
        pw_canvas.create_window((0, 0), window=pw_inner, anchor="nw")
        pw_canvas.configure(yscrollcommand=pw_scroll.set)
        pw_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))
        pw_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        for pw_id, pw in sorted(self.pathways.items(),
                                key=lambda x: x[1].get("name", "")):
            var = tk.BooleanVar()
            self.pathway_vars[pw_id] = var
            rel = pw.get("related_programs", [])
            hint = ""
            if rel:
                codes = [self.programs.get(r, {}).get("major_code", r.split("_")[0].upper())
                         for r in rel[:2]]
                hint = f"  [{', '.join(codes)}]"
            ttk.Checkbutton(pw_inner,
                            text=f"{pw['name']}{hint}",
                            variable=var,
                            style="TCheckbutton").pack(anchor=tk.W, pady=1)

        # Courses taken
        sec3 = self._section_frame(parent, "COURSES TAKEN  (one per line)")
        tk.Label(sec3, text="e.g.  BIO-145  or  BIO-145/145L",
                 bg=COLORS["panel_bg"], fg=COLORS["hint"],
                 font=("Helvetica", 8, "italic")).pack(anchor=tk.W, padx=10)
        self.courses_txt = ScrolledText(sec3, height=11, width=26,
                                        font=("Courier", 9),
                                        bg="white", relief=tk.FLAT,
                                        wrap=tk.WORD)
        self.courses_txt.pack(fill=tk.BOTH, padx=10, pady=4, expand=True)

        # Buttons
        btn_frame = tk.Frame(parent, bg=COLORS["panel_bg"])
        btn_frame.pack(fill=tk.X, padx=10, pady=(4, 8))
        ttk.Button(btn_frame, text="Check Requirements",
                   command=self.check).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="Export to Text File",
                   command=self.export).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="Clear All",
                   command=self.clear_all).pack(fill=tk.X, pady=2)

    def _section_frame(self, parent: tk.Frame, title: str) -> tk.Frame:
        tk.Label(parent, text=title, bg=COLORS["panel_bg"],
                 font=("Helvetica", 8, "bold"),
                 fg="#444444").pack(anchor=tk.W, padx=10, pady=(10, 0))
        sep = tk.Frame(parent, bg="#cccccc", height=1)
        sep.pack(fill=tk.X, padx=10, pady=(1, 4))
        f = tk.Frame(parent, bg=COLORS["panel_bg"])
        f.pack(fill=tk.BOTH, expand=True)
        return f

    def _build_right(self, parent: tk.Frame):
        self.summary_var = tk.StringVar(
            value="Select programs and enter courses, then click Check Requirements.")
        tk.Label(parent, textvariable=self.summary_var,
                 bg=COLORS["bg"], font=("Helvetica", 10),
                 wraplength=680, justify=tk.LEFT,
                 fg=COLORS["note"]).pack(anchor=tk.W, padx=12, pady=(8, 2))

        self.nb = ttk.Notebook(parent)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

    # ──────────────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────────────

    def check(self):
        sel_indices = self.prog_lb.curselection()
        sel_ids = [self._prog_ids[i] for i in sel_indices]
        raw = self.courses_txt.get("1.0", tk.END)
        taken_list = parse_courses(raw)
        taken = set(taken_list)

        # WE count adjustment for transfer students (Coe 1-credit system, max 8 credits)
        transfer_str = self.transfer_var.get()
        if "8 credits" in transfer_str:
            we_required = 3
        else:
            we_required = 5

        # Clear tabs
        for tab in self.nb.tabs():
            self.nb.forget(tab)
        self.manual_ge.clear()

        # GE tab
        ge_result = check_ge(self.ge_data, taken, self.dac, self.we)
        ge_frame = tk.Frame(self.nb, bg=COLORS["bg"])
        self.nb.add(ge_frame, text="GE Requirements")
        self._render_ge(ge_frame, ge_result, we_required)

        # Collect active pathway ids
        active_pathway_ids = [pid for pid, var in self.pathway_vars.items()
                              if var.get()]

        # Program tabs
        for pid in sel_ids:
            prog = self.programs[pid]
            result = check_program(prog, taken)
            frame = tk.Frame(self.nb, bg=COLORS["bg"])
            tab_label = f"{prog['name']} ({prog.get('program_type','').title()})"
            self.nb.add(frame, text=tab_label)
            self._render_program(frame, result, active_pathways=active_pathway_ids)

        # Pathway tabs
        for pw_id in active_pathway_ids:
            pw = self.pathways[pw_id]
            result = check_program(pw, taken)
            frame = tk.Frame(self.nb, bg=COLORS["bg"])
            self.nb.add(frame, text=f"⬡ {pw['name']}")
            self._render_program(frame, result)

        # Summary
        name = self.name_var.get().strip() or "Student"
        sid  = self.id_var.get().strip()
        sid_str = f" (ID: {sid})" if sid else ""
        cred = total_credits(taken, self.course_credits)
        self.summary_var.set(
            f"{name}{sid_str}  |  {cred:.1f} credits  ({len(taken)} courses)  "
            f"|  {len(sel_ids)} program(s)  |  {len(active_pathway_ids)} pathway(s)")

    def clear_all(self):
        self.name_var.set("")
        self.id_var.set("")
        self.courses_txt.delete("1.0", tk.END)
        self.prog_lb.selection_clear(0, tk.END)
        for tab in self.nb.tabs():
            self.nb.forget(tab)
        self.summary_var.set(
            "Select programs and enter courses, then click Check Requirements.")

    def export(self):
        name = self.name_var.get().strip() or "student"
        fname = f"advising_{name.replace(' ','_')}_{datetime.now():%Y%m%d}.txt"
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile=fname)
        if not path:
            return
        lines = [f"Coe College Academic Advising Report",
                 f"Generated: {datetime.now():%Y-%m-%d %H:%M}",
                 f"Student: {self.name_var.get() or 'N/A'}  |  ID: {self.id_var.get() or 'N/A'}",
                 "=" * 60, ""]
        for tab_id in self.nb.tabs():
            tab_text = self.nb.tab(tab_id, "text")
            widget   = self.nb.nametowidget(tab_id)
            # Grab the Text widget inside
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
        if info["grade"] is not None:
            parts.append(f"avg {info['grade']:.1f}")
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
                    sem_str   = f"Sem {info['sem']}" if info["sem"] else "?"
                    grade_str = f", avg {info['grade']:.1f}" if info["grade"] is not None else ""
                    pct_str   = f"{info['pct']:.0%}"
                    self._ins(t,
                        f"   • {code:<12}  {pct_str} of grads   {sem_str}{grade_str}\n",
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
