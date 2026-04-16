#!/usr/bin/env python3
"""
Coe College Academic Advising Tool — Web Interface
====================================================
A Flask web app providing the same advising logic as the desktop app.
Reads the shared data/ directory; produces compatible .adv files.

Usage:  pip install flask && python web_advisor.py
"""

import csv
import json
import re
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, request, jsonify

# ─────────────────────────── Paths ──────────────────────────────────────────

BASE_DIR     = Path(__file__).parent
DATA_DIR     = BASE_DIR / "data"
PROGRAMS_DIR = DATA_DIR / "programs"

# ─────────────────────────── Constants ──────────────────────────────────────

COMPLETE   = "complete"
PARTIAL    = "partial"
INCOMPLETE = "incomplete"
MANUAL     = "manual"

STUDENT_YEARS = ["First Year", "Sophomore", "Junior", "Senior",
                 "Transfer Student"]

# ─────────────────────────── Data loading ───────────────────────────────────

def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_programs():
    progs = {}
    for fp in sorted(PROGRAMS_DIR.glob("*.json")):
        try:
            data = _load_json(fp)
            progs[data["id"]] = data
        except Exception:
            pass
    return progs


def load_pathways():
    pws = {}
    pw_dir = DATA_DIR / "pathways"
    if not pw_dir.exists():
        return pws
    for fp in sorted(pw_dir.glob("*.json")):
        try:
            data = _load_json(fp)
            pws[data["id"]] = data
        except Exception:
            pass
    return pws

# ─────────────────────────── Course utilities ───────────────────────────────

def normalize(code):
    code = code.strip().upper().replace(" ", "")
    m = re.match(r'^([A-Z]+)-?(\d+[A-Z]*)$', code)
    return f"{m.group(1)}-{m.group(2)}" if m else code


def prefix_of(code):
    m = re.match(r'^([A-Z]+)-', code)
    return m.group(1) if m else ""


def level_of(code):
    m = re.match(r'^[A-Z]+-(\d)', code)
    return int(m.group(1)) * 100 if m else 0


def is_lab(code):
    return bool(re.match(r'^[A-Z]+-\d+L$', code))


def is_clinical(code):
    return bool(re.match(r'^[A-Z]+-\d+C$', code))


def is_auxiliary(code):
    return is_lab(code) or is_clinical(code)


def credit_of(code, overrides=None):
    if overrides and code in overrides:
        return overrides[code]
    return 0.2 if is_auxiliary(code) else 1.0


def total_credits(taken, overrides=None):
    return sum(credit_of(c, overrides) for c in taken)


def parse_courses(text):
    seen, result = set(), []

    def add(code):
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

# ─────────────────────────── Requirement checker ────────────────────────────

def _codes_satisfied(codes, taken):
    norm = [normalize(c) for c in codes]
    primary = [c for c in norm if not is_auxiliary(c)]
    found = [c for c in norm if c in taken]
    sat = (bool(primary and any(c in taken for c in primary))
           or (not primary and bool(found)))
    return sat, found


def check_section(section, taken):
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
        status = (COMPLETE if count >= n
                  else PARTIAL if count > 0 else INCOMPLETE)
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
        above = (sum(1 for x in matching if level_of(x) >= min_lvl)
                 if min_lvl else len(matching))
        level_ok = (above >= min_cnt) if min_cnt else True
        status = (COMPLETE if len(matching) >= n and level_ok
                  else PARTIAL if matching else INCOMPLETE)
        parts = [f"{len(matching)}/{n} electives"]
        if min_cnt:
            parts.append(f"{above}/{min_cnt} at {min_lvl}+ level")
        return {**section, "matching": matching, "above_level": above,
                "status": status, "message": "; ".join(parts)}

    return {**section, "status": INCOMPLETE, "message": "Unknown type"}


def check_program(program, taken):
    sections = [check_section(s, taken)
                for s in program.get("sections", [])]
    countable = [s for s in sections if s["status"] != MANUAL]
    done = sum(1 for s in countable if s["status"] == COMPLETE)
    return {"program": program, "sections": sections,
            "total": len(countable), "complete": done}


def check_ge(ge, taken, dac, we):
    div = ge["divisional"]["sections"]

    def div_courses(pfxs, max_per=2):
        by_pfx = {}
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

    we_found = sorted(c for c in taken
                      if not is_auxiliary(c)
                      and (c in we or c.endswith("W") or c.endswith("WE")))
    dac_found = sorted(c for c in taken if c in dac and not is_auxiliary(c))
    fys_found = [c for c in taken if prefix_of(c) == "FYS"
                 or c in ("FS-110", "FS-111", "FS-112")]
    prx_found = [c for c in taken if prefix_of(c) in ("PRX",)]

    return {
        "fine_arts":      {"label": "Fine Arts (\u22652)",
                           "required": 2, "courses": fa,
                           "complete": len(fa) >= 2},
        "humanities":     {"label": "Humanities (\u22652)",
                           "required": 2, "courses": hum,
                           "complete": len(hum) >= 2},
        "nat_sci_math":   {"label": "Nat. Sci. & Math (\u22651)",
                           "required": 1, "courses": ns[:1],
                           "complete": len(ns) >= 1},
        "lab_science":    {"label": "Lab Science (\u22651 pair)",
                           "required": 1, "pairs": lab_pairs[:1],
                           "complete": len(lab_pairs) >= 1},
        "social_sciences":{"label": "Social Sciences (\u22652)",
                           "required": 2, "courses": ss,
                           "complete": len(ss) >= 2},
        "fys":            {"label": "First Year Seminar (1)",
                           "required": 1, "courses": fys_found,
                           "complete": len(fys_found) >= 1},
        "we":             {"label": "Writing Emphasis (5)",
                           "required": 5, "courses": we_found,
                           "complete": len(we_found) >= 5},
        "dac":            {"label": "Diversity Across Curriculum (2)",
                           "required": 2, "courses": dac_found[:2],
                           "complete": len(dac_found) >= 2},
        "practicum":      {"label": "Practicum (1)",
                           "required": 1, "courses": prx_found,
                           "complete": len(prx_found) >= 1},
    }

# ─────────────────────────── Flask app ──────────────────────────────────────

app = Flask(__name__)

# Load all data at startup
programs       = load_programs()
pathways       = load_pathways()
ge_data        = _load_json(DATA_DIR / "ge_2025.json")
course_credits = _load_json(DATA_DIR / "course_credits.json")
dac_set        = set(_load_json(DATA_DIR / "dac_2025.json"))
we_set         = set(_load_json(DATA_DIR / "we_courses.json"))
catalog        = _load_json(DATA_DIR / "courses_catalog_2025.json") \
                 if (DATA_DIR / "courses_catalog_2025.json").exists() else {}


def _program_list(ptype):
    return sorted(
        [{"id": pid, "name": p["name"],
          "catalog_year": p.get("catalog_year", ""),
          "program_type": p.get("program_type", "")}
         for pid, p in programs.items()
         if p.get("program_type") in
         (ptype if isinstance(ptype, tuple) else (ptype,))],
        key=lambda x: x["name"])


@app.route("/")
def index():
    majors = _program_list(("major", "collateral", "certificate"))
    minors = _program_list(("minor",))
    pw_list = [{"id": pid, "name": p.get("name", pid)}
               for pid, p in sorted(pathways.items())]
    return render_template("index.html",
                           majors=majors, minors=minors,
                           pathways=pw_list,
                           student_years=STUDENT_YEARS)


@app.route("/api/check", methods=["POST"])
def api_check():
    data = request.get_json()
    sel_ids = [pid for pid in data.get("programs", []) if pid]

    # Collect courses from semester data
    all_courses = set()
    for sem in data.get("semesters", []):
        for course in sem.get("courses", []):
            code = course.get("code", "").strip()
            if code:
                for c in parse_courses(code):
                    all_courses.add(c)

    taken = all_courses

    # WE requirement adjustment
    transfer = data.get("transfer_we", "")
    if "16+" in transfer:
        we_required = 2
    elif "8" in transfer:
        we_required = 3
    else:
        we_required = 5

    # GE results
    ge_result = check_ge(ge_data, taken, dac_set, we_set)
    ge_result["we"]["required"] = we_required
    ge_result["we"]["complete"] = (
        len(ge_result["we"]["courses"]) >= we_required)
    ge_result["we"]["label"] = f"Writing Emphasis ({we_required})"

    # Program results
    prog_results = []
    for pid in sel_ids:
        prog = programs.get(pid)
        if not prog:
            continue
        result = check_program(prog, taken)
        prog_results.append({
            "id": pid,
            "name": prog.get("name", pid),
            "program_type": prog.get("program_type", ""),
            "total": result["total"],
            "complete": result["complete"],
            "sections": _serialize_sections(result["sections"]),
        })

    # Pathway results
    pw_results = []
    for pw_id in data.get("pathways_active", []):
        pw = pathways.get(pw_id)
        if not pw:
            continue
        result = check_program(pw, taken)
        pw_results.append({
            "id": pw_id,
            "name": pw.get("name", pw_id),
            "total": result["total"],
            "complete": result["complete"],
            "sections": _serialize_sections(result["sections"]),
        })

    credits = total_credits(taken, course_credits)

    return jsonify({
        "ge": {k: {kk: vv for kk, vv in v.items()
                    if kk != "prefixes"}
               for k, v in ge_result.items()},
        "programs": prog_results,
        "pathways": pw_results,
        "credits": round(credits, 1),
        "course_count": len(taken),
    })


def _serialize_sections(sections):
    out = []
    for s in sections:
        d = {
            "id": s.get("id", ""),
            "label": s.get("label", ""),
            "type": s.get("type", ""),
            "status": s.get("status", ""),
            "message": s.get("message", ""),
        }
        if "items" in s:
            d["items"] = [
                {"title": it.get("title", ""),
                 "codes": it.get("codes", []),
                 "satisfied": it.get("satisfied", False)}
                for it in s["items"]]
        if "options" in s:
            d["options"] = [
                {"title": o.get("title", ""),
                 "codes": o.get("codes", []),
                 "satisfied": o.get("satisfied", False)}
                for o in s["options"]]
        if "matching" in s:
            d["matching"] = s["matching"]
        if "satisfied_count" in s:
            d["satisfied_count"] = s["satisfied_count"]
        if s.get("type") == "choose_n":
            d["n"] = s.get("n", 1)
        if s.get("type") == "open_n":
            d["n"] = s.get("n", 1)
            d["description"] = s.get("description", "")
        out.append(d)
    return out


if __name__ == "__main__":
    app.run(debug=True, port=5050)
