#!/usr/bin/env python3
"""
Extract a structured course database from the Coe College course catalog PDF.

Usage:
    python3 tools/extract_catalog.py [--pdf PATH] [--out PATH]

Produces data/courses_catalog_2025.json keyed by course prefix, with each
course's code, title, credits, and WE (Writing Emphasis) flag.

Division assignments follow catalog page 11 (Divisional Requirements).
Prefixes not listed in any division land in "professional" as a catch-all
for applied/non-GE prefixes (BUS, EDU, KIN, NUR, etc.).
"""

from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Divisional prefix lists from 2025-2026 Catalog, page 11.
DIVISIONS: dict[str, list[str]] = {
    "fine_arts":       ["ARH", "ART", "CRW", "MU", "MUA", "THE"],
    "humanities":      ["AAM", "CLA", "COM", "ENG", "HIS", "JPN", "PHL", "REL", "SPA"],
    "nat_sci_math":    ["BIO", "CHM", "CS", "DS", "ENR", "MTH", "PHY", "STA"],
    "social_sciences": ["ANT", "ECO", "GS", "POL", "PSY", "SOC"],
}
PREFIX_TO_DIV = {p: d for d, prefixes in DIVISIONS.items() for p in prefixes}

SECTION_RE = re.compile(r"^COURSES IN\s+(.+?)(?:\s+BY CONTENT AREA)?\s*$")
# Em-dash "—Section Name" headers also partition departments. Some variants:
#   —ANTHROPOLOGY (COURSES ONLY)        (course listings follow directly)
#   —Aerospace Studies                   (ROTC sub-section; courses follow)
#   —Business Administration             (sub-section inside COURSES IN BUSINESS)
# We treat them all as section resets; the final department label is picked
# by majority vote across where a prefix's courses land, so sub-section
# flicker doesn't harm the output.
EMDASH_SECTION_RE = re.compile(r"^[—–][^\W\d_].*$")
EMDASH_NAME_RE = re.compile(r"^[—–]\s*(.+?)(?:\s*\(.*\))?\s*$")
COURSE_RE  = re.compile(r"^([A-Z]{2,4})-(\d{3}[A-Z]?)\s+(.+?)\s*$")
# Combined listings pair two course codes under a single title/description:
#   CHM-121/-121L General Chemistry I and Laboratory
#   BIO-462/463  Advanced Biology Laboratory I and II
#   AAM-447/-457 Directed Learning in African American Studies
# The "/" separator may optionally be followed by "-" before the second num.
COMBINED_COURSE_RE = re.compile(
    r"^([A-Z]{2,4})-(\d{3}[A-Z]?)/-?(\d{3}[A-Z]?)\s+(.+?)\s*$"
)
CODE_RE    = re.compile(r"\b[A-Z]{2,4}-\d{3}[A-Z]?\b")
CREDIT_RE  = re.compile(r"\((\d+(?:\.\d+)?)\s*course\s*credit\b", re.IGNORECASE)
WE_SUFFIX  = re.compile(r"\s*\(WE\)\s*$")
PAGE_HDR   = re.compile(r"^Coe College Catalog\b")
CROSS_REF_RE = re.compile(r"^See\s+.+?\s+p\.?\s*\d+\.?$", re.IGNORECASE)

# Catalog has a pdftotext artifact: "H ISTORY" with an embedded space.
HISTORY_TYPO = re.compile(r"\bH ISTORY\b")

# A handful of prefixes appear in the catalog without a "COURSES IN X" header
# (their courses are listed inline under a program description). Map them to
# their intended section label so the first course recorded gets the right
# department name.
IMPLICIT_SECTIONS: dict[str, str] = {
    "CFP": "Crimson Fellows Program",
    "ESL": "English as a Second Language",
    "OCC": "Occasional Courses",
}


def run_pdftotext(pdf_path: Path) -> str:
    """Extract layout-preserved text from the catalog PDF."""
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout


def parse(text: str) -> tuple[dict, list]:
    """Walk the catalog text, emitting (prefixes_map, warnings)."""
    prefixes: dict[str, dict] = {}
    warnings: list[str] = []

    cur_section: str | None = None
    cur_course: dict | None = None
    cur_desc: list[str] = []

    def finalize() -> None:
        nonlocal cur_course, cur_desc
        if not cur_course:
            return

        prefix = cur_course["prefix"]
        nums = cur_course["nums"]
        desc = " ".join(cur_desc).strip()

        # Skip cross-reference stubs ("See Economics, p. 89") and bare
        # entries with no description — those are TOC listings or pointer
        # references to the real definition later in the catalog, not
        # course headers in their own right.
        if not desc or CROSS_REF_RE.match(desc):
            cur_course = None
            cur_desc = []
            return

        # Only search the first handful of description lines for the credit
        # annotation. When a course is the last one before a long stretch of
        # non-course content (front matter, program descriptions), cur_desc
        # can accumulate stray text like "(24 course credits)" that refers
        # to graduation requirements, not the course itself.
        credit_window = " ".join(cur_desc[:8])
        m = CREDIT_RE.search(credit_window)
        base_credits = float(m.group(1)) if m else None

        bucket = prefixes.setdefault(prefix, {
            "division":    PREFIX_TO_DIV.get(prefix, "professional"),
            "department":  cur_course["section"] or "(unknown)",
            "_sec_counts": {},
            "courses":     {},
        })

        for num in nums:
            code = f"{prefix}-{num}"
            is_lab_like = code.endswith("L") or code.endswith("C")
            if len(nums) > 1:
                # Combined listings (e.g. "CHM-121/-121L") describe a paired
                # lecture+lab. L/C sibling gets 0.2. The main sibling ignores
                # a "(0.0 course credit)" CREDIT_RE hit — that phrase refers
                # to the P/NP lab, not the lecture — and defaults to 1.0.
                if is_lab_like:
                    credits = 0.2
                elif base_credits is not None and base_credits > 0:
                    credits = base_credits
                else:
                    credits = 1.0
            else:
                if base_credits is not None:
                    credits = base_credits
                elif is_lab_like:
                    credits = 0.2
                else:
                    credits = 1.0

            entry = {"title": cur_course["title"], "credits": credits}
            if cur_course["we"]:
                entry["we"] = True
            bucket["courses"][code] = entry

        sec = cur_course["section"]
        if sec:
            bucket["_sec_counts"][sec] = bucket["_sec_counts"].get(sec, 0) + len(nums)

        cur_course = None
        cur_desc = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line or PAGE_HDR.match(line):
            continue

        at_column_0 = bool(raw) and not raw[0].isspace()

        m = SECTION_RE.match(line)
        if m:
            finalize()
            cur_section = _titlecase(HISTORY_TYPO.sub("HISTORY", m.group(1)))
            continue
        # Em-dash headers must be at column 0 — indented em-dash lines are
        # dotted-filler entries in the front-of-catalog table of contents
        # ("          —RESERVE OFFICER TRAINING CORPS ..........206").
        if at_column_0 and EMDASH_SECTION_RE.match(line):
            name_m = EMDASH_NAME_RE.match(line)
            if name_m:
                finalize()
                cur_section = _titlecase(name_m.group(1))
            continue

        # Course headers must be at column 0 in the raw line — indented
        # references inside program descriptions (e.g. "    ART-201 ...")
        # look like course headers after strip but are not. Also skip
        # multi-column layout lines (TOC-style listings like the WE/DAC
        # tables and the History-by-content-area index) which carry two
        # course codes on one line.
        code_hits = CODE_RE.findall(line)
        if at_column_0 and len(code_hits) == 1:
            nums: list[str] | None = None
            prefix = title = ""
            cm = COMBINED_COURSE_RE.match(line)
            if cm:
                prefix, nums, title = cm.group(1), [cm.group(2), cm.group(3)], cm.group(4)
            else:
                m = COURSE_RE.match(line)
                if m:
                    prefix, nums, title = m.group(1), [m.group(2)], m.group(3)
            if nums:
                we = bool(WE_SUFFIX.search(title))
                title = WE_SUFFIX.sub("", title).strip()
                # Some entries are formatted "OCC-003 — Title" with a
                # leading em-dash separator; strip it.
                title = re.sub(r"^[—–]\s*", "", title)
                finalize()
                section = cur_section or IMPLICIT_SECTIONS.get(prefix)
                cur_course = {
                    "prefix": prefix, "nums": nums, "title": title,
                    "section": section, "we": we,
                }
                cur_desc = []
                continue

        if cur_course:
            cur_desc.append(line)

    finalize()
    return prefixes, warnings


_MINOR_WORDS = {"and", "or", "of", "in", "the", "for", "a", "an"}


def _titlecase(s: str) -> str:
    """Titlecase section label like 'ACCOUNTING' or 'HISTORY' → 'Accounting'."""
    parts = [w.capitalize() if w.isupper() else w for w in s.split()]
    return " ".join(p.lower() if i > 0 and p.lower() in _MINOR_WORDS else p
                    for i, p in enumerate(parts))


def build_output(prefixes: dict, source: Path) -> dict:
    div_prefix_map: dict[str, list[str]] = {d: [] for d in DIVISIONS}
    div_prefix_map["professional"] = []
    for prefix in sorted(prefixes):
        div_prefix_map[prefixes[prefix]["division"]].append(prefix)

    # Pick the department name from the section that contributed the most
    # courses — this avoids cross-references or TOC false-matches setting a
    # misleading label (e.g. ECO courses listed inside the Business section).
    for prefix in sorted(prefixes):
        counts = prefixes[prefix].pop("_sec_counts", {})
        if counts:
            prefixes[prefix]["department"] = max(counts.items(), key=lambda kv: kv[1])[0]
        prefixes[prefix]["courses"] = dict(sorted(prefixes[prefix]["courses"].items()))

    return {
        "version": "2025-2026",
        "source":  source.name,
        "notes": (
            "Generated by tools/extract_catalog.py. Division assignments "
            "follow catalog page 11. 'professional' is a catch-all for "
            "applied/non-GE prefixes. Re-run the script to regenerate after "
            "catalog updates."
        ),
        "divisions": div_prefix_map,
        "prefixes":  dict(sorted(prefixes.items())),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", default=str(REPO / "catalogs" / "2025-2026 Catalog final.pdf"))
    ap.add_argument("--out", default=str(REPO / "data" / "courses_catalog_2025.json"))
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    out_path = Path(args.out)

    text = run_pdftotext(pdf_path)
    prefixes, warnings = parse(text)
    output = build_output(prefixes, pdf_path)

    out_path.write_text(json.dumps(output, indent=2) + "\n")

    course_count = sum(len(p["courses"]) for p in prefixes.values())
    print(f"Wrote {out_path.relative_to(REPO)}")
    print(f"  {len(prefixes)} prefixes, {course_count} courses")
    for div, prefs in output["divisions"].items():
        print(f"  {div:18s} {len(prefs):2d} prefixes: {', '.join(prefs)}")
    if warnings:
        print(f"\n{len(warnings)} warnings:")
        for w in warnings[:20]:
            print(f"  - {w}")
        if len(warnings) > 20:
            print(f"  ... and {len(warnings) - 20} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
