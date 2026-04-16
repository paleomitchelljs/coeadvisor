#!/usr/bin/env python3
"""
Coe College Academic Advising Tool — Web Interface
====================================================
A Flask web app providing the same advising logic as the desktop app.
Reads the shared data/ directory; produces compatible .adv files.

Usage:  pip install flask && python web_advisor.py
"""

from flask import Flask, render_template, request, jsonify

from advisor_core import (
    DATA_DIR,
    STUDENT_YEARS,
    _load_json, load_programs, load_pathways, load_ge, load_dac, load_we,
    load_course_credits, load_catalog,
    normalize, parse_courses, total_credits,
    check_program, check_ge,
)

# ─────────────────────────── Flask app ──────────────────────────────────────

app = Flask(__name__)

programs       = load_programs()
pathways       = load_pathways()
ge_data        = load_ge()
course_credits = load_course_credits()
dac_set        = load_dac()
we_set         = load_we()
catalog        = load_catalog()


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

    all_courses = set()
    for sem in data.get("semesters", []):
        for course in sem.get("courses", []):
            code = course.get("code", "").strip()
            if code:
                for c in parse_courses(code):
                    all_courses.add(c)

    taken = all_courses

    transfer = data.get("transfer_we", "")
    if "16+" in transfer:
        we_required = 2
    elif "8" in transfer:
        we_required = 3
    else:
        we_required = 5

    ge_result = check_ge(ge_data, taken, dac_set, we_set)
    ge_result["we"]["required"] = we_required
    ge_result["we"]["complete"] = (
        len(ge_result["we"]["courses"]) >= we_required)
    ge_result["we"]["label"] = f"Writing Emphasis ({we_required})"

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
