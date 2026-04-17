#!/usr/bin/env python3
"""
Bundle all advising data files into a single docs/data.js for the static web app.

Usage:  python tools/bundle_web_data.py
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_dir(d, key_fn=None):
    result = {}
    for fp in sorted(d.glob("*.json")):
        data = load_json(fp)
        k = key_fn(data) if key_fn else fp.stem
        result[k] = data
    return result


def load_trajectory():
    path = DATA / "student_obs" / "major_course_summary.csv"
    if not path.exists():
        return {}
    by_major = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            major = row.get("major", "").strip()
            raw = row.get("course", "").strip().upper().replace(" ", "")
            import re
            m = re.match(r'^([A-Z]+)-?(\d+[A-Z]*)$', raw)
            code = f"{m.group(1)}-{m.group(2)}" if m else raw
            if not major or not code:
                continue
            try:
                pct = float(row.get("pct_took", 0) or 0)
                sem = round(float(row.get("typical_semester", 0) or 0))
            except ValueError:
                pct, sem = 0.0, 0
            by_major.setdefault(major, {})[code] = {
                "tier": row.get("course_tier", "elective"),
                "sem": sem if sem > 0 else None,
                "pct": round(pct, 4),
            }
    return by_major


def load_programs(programs_dir):
    """Load programs from flat dir and catalog-year subfolders.

    Flat files:  data/programs/*.json  (legacy)
    Year folders: data/programs/2025-26/*.json  (new structure)

    Year-folder programs override flat files with the same id.
    """
    programs = {}
    catalog_years = set()

    # Legacy flat files
    for fp in sorted(programs_dir.glob("*.json")):
        data = load_json(fp)
        programs[data["id"]] = data
        cy = data.get("catalog_year", "")
        if cy:
            catalog_years.add(cy)

    # Catalog-year subfolders (e.g. data/programs/2025-26/)
    for subdir in sorted(programs_dir.iterdir()):
        if not subdir.is_dir() or subdir.name.startswith((".", "_")):
            continue
        year_label = subdir.name          # e.g. "2025-26"
        catalog_years.add(year_label)
        for fp in sorted(subdir.glob("*.json")):
            data = load_json(fp)
            # Ensure catalog_year matches the folder
            data["catalog_year"] = year_label
            programs[data["id"]] = data

    return programs, sorted(catalog_years)


def load_advice(advice_dir):
    """Load advice from data/advice/ subdirectories.

    Each subdirectory contains:
      _advice.json  — master file with metadata and pointers
      plan_*.json   — plan files referenced by the master
      intake.json   — optional intake wizard data
      notes.json    — optional advisor notes

    Sub-files are inlined into the master, so the bundled output is
    a flat dict keyed by the advice directory name with everything resolved.
    """
    if not advice_dir.is_dir():
        return {}
    result = {}
    for subdir in sorted(advice_dir.iterdir()):
        if not subdir.is_dir() or subdir.name.startswith("."):
            continue
        master_path = subdir / "_advice.json"
        if not master_path.exists():
            continue
        master = load_json(master_path)
        # Inline plan files (preserve master's id/label/conditions)
        for plan in master.get("plans", []):
            plan_file = plan.pop("file", None)
            if plan_file:
                plan_path = subdir / plan_file
                if plan_path.exists():
                    plan_data = load_json(plan_path)
                    # Keep master's id, merge plan data underneath
                    saved_id = plan.get("id")
                    saved_label = plan.get("label")
                    plan.update(plan_data)
                    if saved_id:
                        plan["id"] = saved_id
                    if saved_label:
                        plan["label"] = saved_label
        # Inline intake
        intake_ref = master.pop("intake", None)
        if intake_ref:
            intake_path = subdir / intake_ref
            if intake_path.exists():
                master["intake"] = load_json(intake_path)
        # Inline notes
        notes_ref = master.pop("notes", None)
        if notes_ref:
            notes_path = subdir / notes_ref
            if notes_path.exists():
                master["notes"] = load_json(notes_path)
        result[master["id"]] = master
    return result


def main():
    DOCS.mkdir(exist_ok=True)

    programs, catalog_years = load_programs(DATA / "programs")

    bundle = {
        "programs": programs,
        "catalog_years": catalog_years,
        "pathways": load_dir(DATA / "pathways", key_fn=lambda d: d["id"]),
        "ge": load_json(DATA / "ge_2025.json"),
        "course_credits": load_json(DATA / "course_credits.json"),
        "dac": load_json(DATA / "dac_2025.json"),
        "we": load_json(DATA / "we_courses.json"),
        "practicum": load_json(DATA / "practicum_2025.json"),
        "first_two_years": load_json(DATA / "first_two_years.json"),
        "intake": load_dir(DATA / "intake", key_fn=lambda d: d["program_id"]),
        "trajectory": load_trajectory(),
    }

    advice = load_advice(DATA / "advice")
    if advice:
        bundle["advice"] = advice

    if (DATA / "courses_catalog_2025.json").exists():
        bundle["catalog"] = load_json(DATA / "courses_catalog_2025.json")
    if (DATA / "offerings_2026.json").exists():
        bundle["offerings"] = load_json(DATA / "offerings_2026.json")

    # Schedule data (class lists parsed from PDFs)
    sched_dir = DATA / "schedules"
    if sched_dir.exists():
        schedules = {}
        for sf in sorted(sched_dir.glob("*.json")):
            sd = load_json(sf)
            schedules[sd.get("term_code", sf.stem)] = sd
        if schedules:
            bundle["schedules"] = schedules

    js = "const DATA = " + json.dumps(bundle, separators=(",", ":")) + ";\n"
    out = DOCS / "data.js"
    out.write_text(js, encoding="utf-8")
    size_kb = len(js) / 1024
    print(f"Wrote {out} ({size_kb:.0f} KB, {len(bundle['programs'])} programs, "
          f"{len(catalog_years)} catalog years, "
          f"{len(bundle['trajectory'])} majors in trajectory)")


if __name__ == "__main__":
    main()
