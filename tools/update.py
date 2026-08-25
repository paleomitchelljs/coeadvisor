#!/usr/bin/env python3
"""Ingest any new PDFs dropped into catalogs/ and class_lists/.

Scans both folders, works out each file's time period from the text inside the
PDF (not the filename), extracts anything new, and rebuilds the web bundle.

    python3 tools/update.py              # process new/changed files
    python3 tools/update.py --dry-run    # report what would happen
    python3 tools/update.py --force      # reprocess everything
    python3 tools/update.py --no-bundle  # skip the docs/data.js rebuild
    python3 tools/update.py --check      # reconcile data against the catalog manifest

Processed files are recorded in data/.processed.json by content hash, so
re-running is cheap and a re-issued PDF is picked up automatically. To hold a
PDF back — one the Registrar has not formatted correctly yet, say — list its
filename in data/.update_ignore (one glob per line).

A catalog PDF produces:
    data/programs/_drafts/<year>/*.json     extracted programs, pending review
    data/catalog_years/<year>/courses.json  course catalog
    data/catalog_years/<year>/we.json       Writing Emphasis listing
    data/catalog_years/<year>/dac.json      Diversity Across the Curriculum
    data/catalog_years/<year>/practicum.json
    data/catalog_years/<year>/ge.json       only with --seed-ge (needs review)

A class-list PDF produces:
    data/schedules/<term>_<year>.json

Requires: pip install pdfplumber   (and pdftotext from poppler for the catalog)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("Error: pdfplumber not installed. Run: pip install pdfplumber")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

CATALOGS_DIR = REPO / "catalogs"
CLASS_LISTS_DIR = REPO / "class_lists"
PROGRAMS_DIR = REPO / "data" / "programs"
YEARS_DIR = REPO / "data" / "catalog_years"
SCHEDULES_DIR = REPO / "data" / "schedules"
MANIFEST = REPO / "data" / ".processed.json"

CODE_RE = re.compile(r"^([A-Z]{2,4})-\s?(\d{3}[A-Z]?)((?:/-?\s?\d{3}[A-Z]?)*)\s+(.*)$")

# Lines that mean "the course listing has ended" inside a two-column page.
LIST_STOP_MARKERS = (
    "PRACTICUM",
    "Additional practicum courses",
    "practicum experience",
    "TOTAL COURSE CREDITS",
    "AREAS OF STUDY",
)


# ── helpers ─────────────────────────────────────────────────────────────────

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text())
        except Exception:
            pass
    return {"files": {}}


def save_manifest(m: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def page_columns(page) -> list:
    """Split a two-column page into left and right text blocks."""
    w, h = page.width, page.height
    return [
        page.crop((0, 0, w / 2, h)).extract_text() or "",
        page.crop((w / 2, 0, w, h)).extract_text() or "",
    ]


def codes_from_lines(lines) -> dict:
    """Pull 'CODE Title' entries out of a listing, stopping at practicum text.

    Handles combined codes: 'SPA-475/-485 Topics ...' yields both codes.
    """
    out = {}
    for raw in lines:
        line = raw.strip()
        if any(line.startswith(m) or m in line for m in LIST_STOP_MARKERS):
            break
        m = CODE_RE.match(line)
        if not m:
            continue
        pfx, first, extra, title = m.groups()
        title = title.strip()
        out.setdefault(f"{pfx}-{first}", title)
        for e in re.findall(r"(\d{3}[A-Z]?)", extra or ""):
            out.setdefault(f"{pfx}-{e}", title)
    return out


# ── period detection ────────────────────────────────────────────────────────

def detect_catalog_year(pdf_path: Path) -> str:
    """Catalog year like '2026-27', read from inside the PDF."""
    from extract_programs import detect_catalog_year as _detect
    with pdfplumber.open(pdf_path) as pdf:
        return _detect(pdf, str(pdf_path))


TERM_RE = re.compile(
    r"(\d{4})\s*[–-]\s*(\d{4})\s+(Fall|Spring|Summer|May|Winter|Interim)\s+Term",
    re.IGNORECASE,
)
# Terms that fall in the second calendar year of the academic year.
SECOND_YEAR_TERMS = {"spring", "summer", "may", "winter", "interim"}


def detect_term(pdf_path: Path) -> dict | None:
    """Read term and year out of a class-list PDF's first pages.

    Coe headers read '2026-2027 Fall Term'. Fall belongs to the first calendar
    year of the academic year; Spring/Summer/May to the second.
    """
    with pdfplumber.open(pdf_path) as pdf:
        text = ""
        for page in pdf.pages[:3]:
            text += (page.extract_text() or "") + "\n"
    m = TERM_RE.search(text)
    if m:
        y1, y2, term = m.group(1), m.group(2), m.group(3).capitalize()
        year = y2 if term.lower() in SECOND_YEAR_TERMS else y1
        return {"term": term, "year": year,
                "academic_year": f"{y1}-{y2[-2:]}",
                "term_code": f"{term.lower()}_{year}",
                "label": f"{term} {year}"}
    # Fallback: a bare term word plus any 4-digit year on the page
    m = re.search(r"\b(Fall|Spring|Summer|May|Winter|Interim)\b", text, re.IGNORECASE)
    y = re.search(r"\b(20\d{2})\b", text)
    if m and y:
        term = m.group(1).capitalize()
        return {"term": term, "year": y.group(1),
                "academic_year": None,
                "term_code": f"{term.lower()}_{y.group(1)}",
                "label": f"{term} {y.group(1)}"}
    return None


# ── catalog extraction ──────────────────────────────────────────────────────

def is_toc_page(text: str) -> bool:
    """Table-of-contents pages repeat the same headings, so skip them.

    They are recognisable by dot leaders ('HEADING ....... 12').
    """
    return len(re.findall(r"\.{4,}\s*\d+", text)) >= 3


def find_listing_pages(pdf, heading: str) -> list:
    """1-based page numbers that contain `heading` and actual course codes.

    Table-of-contents pages are skipped: matching one would anchor the scan
    dozens of pages before the real listing.
    """
    hits = []
    for i, page in enumerate(pdf.pages[:60], start=1):
        text = page.extract_text() or ""
        if heading.lower() not in text.lower() or is_toc_page(text):
            continue
        hits.append(i)
    # Prefer the first page that actually carries course codes.
    for i in hits:
        text = pdf.pages[i - 1].extract_text() or ""
        if len(re.findall(r"\b[A-Z]{2,4}-\s?\d{3}", text)) >= 5:
            return [i] + [j for j in hits if j > i]
    return hits


def extract_course_listing(pdf, heading: str, max_pages: int = 8) -> dict:
    """Parse a two-column 'CODE Title' listing that starts at `heading`."""
    pages = find_listing_pages(pdf, heading)
    if not pages:
        return {}
    found = {}
    started = False
    for pno in range(pages[0], min(pages[0] + max_pages, len(pdf.pages) + 1)):
        page = pdf.pages[pno - 1]
        page_text = page.extract_text() or ""
        if started and heading.lower() not in page_text.lower():
            # Listing continues only while its (Continued) header is present.
            if not found:
                continue
            break
        for chunk in page_columns(page):
            lines = chunk.split("\n")
            if not started:
                for idx, line in enumerate(lines):
                    if heading.lower() in line.lower():
                        lines = lines[idx + 1:]
                        started = True
                        break
                else:
                    continue
            else:
                lines = [l for l in lines if heading.lower() not in l.lower()]
            found.update(codes_from_lines(lines))
    return found


def extract_practicum(pdf) -> dict:
    """Practicum rules: suffix-based categories plus the explicit extra list."""
    extras = {}
    for i, page in enumerate(pdf.pages[:60], start=1):
        text = page.extract_text() or ""
        if "Additional practicum courses" not in text:
            continue
        for chunk in page_columns(page):
            lines = chunk.split("\n")
            for idx, line in enumerate(lines):
                if "Additional practicum courses" in line:
                    lines = lines[idx + 1:]
                    break
            for raw in lines:
                m = CODE_RE.match(raw.strip())
                if m:
                    extras.setdefault(f"{m.group(1)}-{m.group(2)}", m.group(4).strip())
        break
    return extras


def build_year_data(pdf_path: Path, year: str, verbose: bool = True,
                    overwrite: bool = False, seed_ge: bool = False) -> list:
    """Write data/catalog_years/<year>/{courses,we,dac,practicum,ge}.json.

    Existing files are left alone unless `overwrite` is set, so hand-reviewed
    data is never silently replaced by a fresh extraction.
    """
    outdir = YEARS_DIR / year
    written = []
    skipped = []

    def emit(name: str, data, summary: str) -> None:
        dest = outdir / name
        if dest.exists() and not overwrite:
            skipped.append(name)
            return
        write_json(dest, data)
        written.append(f"{name} ({summary})")

    # 1. Course catalog (uses pdftotext via the existing extractor)
    try:
        import extract_catalog
        text = extract_catalog.run_pdftotext(pdf_path)
        prefixes, _warnings = extract_catalog.parse(text)
        courses = extract_catalog.build_output(prefixes, pdf_path)
        courses["catalog_year"] = year
        n = sum(len(p["courses"]) for p in prefixes.values())
        emit("courses.json", courses, f"{n} courses")
    except Exception as exc:
        print(f"    ! course catalog extraction failed: {exc}")

    with pdfplumber.open(pdf_path) as pdf:
        # 2. Writing Emphasis listing
        we = extract_course_listing(pdf, "Writing Emphasis Course Listing")
        if we:
            emit("we.json", {
                "label": "Known Writing Emphasis (WE) Courses",
                "year": year,
                "source": f"{pdf_path.name}, Writing Emphasis Course Listing",
                "note": ("All First-Year Seminars (FYS-/FS- prefixes) carry WE credit by "
                         "rule. Courses whose section ends in W or WE also count."),
                "courses": sorted(we),
            }, f"{len(we)} courses")

        # 3. Diversity Across the Curriculum listing
        dac = extract_course_listing(pdf, "Diversity Across the Curriculum")
        if dac:
            emit("dac.json", {
                "label": "Diversity Across the Curriculum — Approved Courses",
                "year": year,
                "source": f"{pdf_path.name}, Diversity Across the Curriculum listing",
                "courses": sorted(dac),
            }, f"{len(dac)} courses")

        # 4. Practicum
        extras = extract_practicum(pdf)
        if extras:
            catalog_codes = set()
            if (outdir / "courses.json").exists():
                cat = json.loads((outdir / "courses.json").read_text())
                for pd in cat.get("prefixes", {}).values():
                    catalog_codes.update(pd.get("courses", {}))
            suffix = {"internship": ["494", "499"], "research": ["454", "459"]}
            by_suffix = {k: sorted(c for c in catalog_codes
                                   if c.split("-")[-1] in v and not c.startswith("XXX"))
                         for k, v in suffix.items()}
            emit("practicum.json", {
                "version": year,
                "label": f"Practicum-Qualifying Experiences ({year} Catalog)",
                "note": ("All students, except those earning a second degree, must complete "
                         "at least ONE practicum experience."),
                "suffix_rules": suffix,
                "internship_courses": by_suffix["internship"],
                "research_courses": by_suffix["research"],
                "additional_practicum_courses": sorted(extras),
                "all_courses": sorted(set(extras)
                                      | set(by_suffix["internship"])
                                      | set(by_suffix["research"])),
            }, f"{len(extras)} extra courses")

    # 5. GE structure — opt-in seeding only.
    #    GE requirements are prose, not a listing, and the structure really does
    #    change between regimes (catalogs before 2025-26 use a different
    #    distribution scheme entirely). Copying a neighbouring year's ge.json
    #    would quietly assert requirements that never applied, so this only runs
    #    when explicitly asked for, and always lands flagged for review.
    ge_path = outdir / "ge.json"
    if seed_ge and not ge_path.exists():
        prior = sorted((p for p in YEARS_DIR.glob("*/ge.json")
                        if p.parent.name != year), reverse=True)
        earlier = [p for p in prior if p.parent.name < year]
        source = (earlier[0] if earlier else (prior[-1] if prior else None))
        if source:
            ge = json.loads(source.read_text())
            ge["_seeded_from"] = source.parent.name
            ge["_needs_review"] = ("Copied from another catalog year. Check divisional "
                                   "prefixes, credit counts, and WE/DAC/practicum counts "
                                   "against this year's catalog.")
            write_json(ge_path, ge)
            written.append(f"ge.json (seeded from {source.parent.name} — REVIEW)")

    if verbose:
        for w in written:
            print(f"    -> data/catalog_years/{year}/{w}")
        if skipped:
            print(f"    .. kept existing: {', '.join(skipped)}")
    return written


def process_catalog(pdf_path: Path, dry_run: bool, overwrite: bool = False,
                    seed_ge: bool = False) -> dict:
    year = detect_catalog_year(pdf_path)
    print(f"  {pdf_path.name}: catalog year {year}")
    if year == "unknown":
        print("    ! could not determine catalog year — skipping")
        return {"skipped": True}
    if dry_run:
        return {"period": year, "dry_run": True}

    outputs = []

    # Programs always land in _drafts/<year>/ — never straight into the active
    # set. The extractor gets roughly 80% of the structure right and uses its
    # own naming, so a draft can easily duplicate a hand-written program under
    # a different filename. The bundler ignores _-prefixed folders; promote a
    # draft by reviewing it against the PDF and moving it into the year folder.
    year_dir = PROGRAMS_DIR / year
    draft_dir = PROGRAMS_DIR / "_drafts" / year
    active = {p.name for p in year_dir.glob("*.json")} if year_dir.exists() else set()
    try:
        import extract_programs
        programs = extract_programs.parse_catalog(str(pdf_path))
        new_files, already = 0, 0
        for prog in programs:
            fname = extract_programs.make_filename(prog["id"], year)
            if fname in active:
                already += 1
                continue
            dest = draft_dir / fname
            if dest.exists():
                already += 1
                continue
            write_json(dest, extract_programs.strip_review_flags(prog))
            new_files += 1
        if new_files:
            outputs.append(f"data/programs/_drafts/{year}/ (+{new_files} drafts)")
            print(f"    -> data/programs/_drafts/{year}/: {new_files} new draft(s); "
                  f"{len(active)} active program(s) untouched")
            print(f"       Review each against the catalog, then move it into "
                  f"data/programs/{year}/ to activate.")
        else:
            print(f"    -> data/programs/{year}/: no new programs "
                  f"({len(active)} active, {already} already extracted)")
    except Exception as exc:
        print(f"    ! program extraction failed: {exc}")

    outputs += build_year_data(pdf_path, year, overwrite=overwrite, seed_ge=seed_ge)
    return {"period": year, "outputs": outputs}


# ── class-list extraction ───────────────────────────────────────────────────

def process_class_list(pdf_path: Path, dry_run: bool) -> dict:
    period = detect_term(pdf_path)
    if not period:
        print(f"  {pdf_path.name}: ! could not determine term — skipping")
        return {"skipped": True}
    print(f"  {pdf_path.name}: {period['label']}"
          + (f" (academic year {period['academic_year']})" if period["academic_year"] else ""))
    if dry_run:
        return {"period": period["term_code"], "dry_run": True}

    try:
        import parse_class_list
        schedule = parse_class_list.parse_pdf(pdf_path)
        # Trust the period we derived here over the parser's narrower detection.
        schedule["term"] = period["label"]
        schedule["term_code"] = period["term_code"]
        if period["academic_year"]:
            schedule["academic_year"] = period["academic_year"]
        SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
        out = SCHEDULES_DIR / f"{period['term_code']}.json"

        # Several PDFs can describe one term — the Registrar reissues the
        # report as the build firms up, and every issue lands in the same file.
        # Files are processed in filename order, which has nothing to do with
        # recency, so without this an April issue quietly overwrites an August
        # one. The PDF's own creation date is the tiebreak.
        ok, why = parse_class_list.supersedes(schedule, out)
        if not ok:
            print(f"    .. {why} — leaving it alone")
            return {"period": period["term_code"],
                    "outputs": [str(out.relative_to(REPO))]}

        # The draft layout clips titles at its column width; recover the tails
        # from a previous issue of this term, then from the catalog.
        fixed = parse_class_list.restore_truncated_titles(
            schedule,
            parse_class_list.title_sources(REPO, period["term_code"],
                                           period["academic_year"]))

        write_json(out, schedule)
        n_courses = len(schedule["courses"])
        n_sections = sum(len(c["sections"]) for c in schedule["courses"].values())
        layout = schedule.get("layout", "finalized")
        note = f", {fixed} title(s) restored" if fixed else ""
        print(f"    -> {out.relative_to(REPO)} ({n_courses} courses, "
              f"{n_sections} sections, {layout} layout{note})")
        return {"period": period["term_code"],
                "outputs": [str(out.relative_to(REPO))]}
    except Exception as exc:
        print(f"    ! class-list parsing failed: {exc}")
        return {"skipped": True}


# ── coverage check ───────────────────────────────────────────────────────────
#
# Concentrations are the part of the catalog most likely to drift silently: a
# collateral major becomes a concentration, a track is renamed, a department
# adds three at once. They are also invisible to extract_programs.py, which
# treats "Concentrations in X" as an end-of-program marker and has no
# concentrations output at all — so nothing catches a miss unless we look.
#
# The catalog titles every concentration's detail block the same way, which
# makes them cheap to enumerate directly from the body text:
#
#     Concentrations in Biology          <- group header, binds what follows
#     Molecular Biology Concentration*
#     Multimedia Graphic Design Concentration in Art   <- or an inline parent

CONCENTRATION_RE = re.compile(
    r"^(?P<name>[A-Z][A-Za-z&/\-,' ]{2,48}?)\s+Concentration\*?"
    r"(?:\s+in\s+(?P<parent>[A-Z][A-Za-z ]{2,30}?))?\s*$")
CONCENTRATION_GROUP_RE = re.compile(
    r"^Concentrations? in (?P<parent>[A-Z][A-Za-z ]{2,30}?)\s*$")

# The same idea under different names: Music uses "Emphasis", International
# Studies uses "Track". The data models all three as `concentrations`, so the
# check has to recognise them or they read as spurious extras.
ALT_HEADING_RES = (
    re.compile(r"^(?P<name>[A-Z][A-Za-z&/\-,' ]{2,48}?)\s+Emphasis\s*$"),
    re.compile(r".*?[\u2014\u2013-]\s*(?P<name>[A-Z][A-Za-z' ]{2,48}?)\s+[Tt]rack\s*$"),
    re.compile(r"^.+?\s+Major\s*[\u2014\u2013-]\s*(?P<name>[A-Z][A-Za-z' ]{2,48}?)\s*$"),
)
# Section titles that match the shape but are not programs.
ALT_HEADING_SKIP = {"theatre major areas of"}


def find_alt_headings(text: str) -> set:
    """Emphasis/Track names — concentrations by another name."""
    out = set()
    for raw in text.split("\n"):
        line = raw.strip()
        for rx in ALT_HEADING_RES:
            m = rx.match(line)
            if m:
                key = _norm_name(m.group("name"))
                if key and key not in ALT_HEADING_SKIP:
                    out.add(key)
    return out


def find_concentrations(pdf_path: Path) -> list:
    """Every concentration the catalog documents, with its parent major."""
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    parent, found, seen = None, [], set()
    for raw in text.split("\n"):
        line = raw.strip()
        g = CONCENTRATION_GROUP_RE.match(line)
        if g:
            parent = g.group("parent")
            continue
        m = CONCENTRATION_RE.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        key = _norm_name(name)
        if key in seen:
            continue
        seen.add(key)
        found.append({"name": name, "parent": m.group("parent") or parent})
    return found, find_alt_headings(text)


def _norm_name(s: str) -> str:
    """Loose key for comparing program names across the catalog and the data.

    The same option is written three ways — "Jazz Emphasis" in the data,
    "Jazz" under an Emphasis heading, "The Global South Track" in a major
    title — so the shared suffixes and a leading article are dropped.
    """
    s = re.sub(r"\s*\(.*?\)\s*", " ", s or "")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    s = " ".join(s.split())
    s = re.sub(r"\s+(concentration|emphasis|track)$", "", s)
    s = re.sub(r"^the\s+", "", s)
    return s.strip()


def check_coverage(year: str) -> int:
    """Compare the concentrations in data/programs/<year>/ against the catalog."""
    pdfs = [p for p in scan(CATALOGS_DIR, []) if detect_catalog_year(p) == year]
    if not pdfs:
        print(f"No catalog PDF found for {year}")
        return 1
    listed, alt = find_concentrations(pdfs[0])

    year_dir = PROGRAMS_DIR / year
    have = {}
    for fp in sorted(year_dir.glob("*.json")):
        d = json.loads(fp.read_text())
        for c in d.get("concentrations", []) or []:
            have[_norm_name(c.get("name", ""))] = (fp.name, d.get("name", ""))

    print(f"\nConcentration coverage — {year}  ({pdfs[0].name})")
    print(f"  catalog documents {len(listed)} concentration(s) "
          f"plus {len(alt)} emphasis/track heading(s); data has {len(have)}")

    missing = [c for c in listed if _norm_name(c["name"]) not in have]
    known = {_norm_name(c["name"]) for c in listed} | alt
    extra = {k: v for k, v in have.items() if k not in known}

    if missing:
        print(f"\n  MISSING from the data ({len(missing)}):")
        for c in missing:
            print(f"      - {c['name']}  (parent: {c['parent'] or '?'})")
    if extra:
        print(f"\n  In the data but NOT in this catalog ({len(extra)}):")
        for k, (fname, prog) in sorted(extra.items()):
            print(f"      - {k}  ({fname})")
    if not missing and not extra:
        print("\n  in sync.")
    else:
        print("\n  A rename shows up as one missing plus one extra; check before acting.")
    return 0


# ── main ────────────────────────────────────────────────────────────────────

IGNORE_FILE = REPO / "data" / ".update_ignore"


def load_ignore() -> list:
    """Filename patterns to leave alone, one per line (# comments allowed).

    Use this to hold back a PDF that is not ready to ingest — e.g. a class
    list the Registrar has not formatted correctly yet.
    """
    if not IGNORE_FILE.exists():
        return []
    return [ln.strip() for ln in IGNORE_FILE.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]


def scan(folder: Path, ignore: list) -> list:
    if not folder.is_dir():
        return []
    import fnmatch
    out = []
    for p in sorted(folder.glob("*.pdf")):
        if p.name.startswith("."):
            continue
        if any(fnmatch.fnmatch(p.name, pat) for pat in ignore):
            continue
        out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be processed, change nothing")
    ap.add_argument("--force", action="store_true",
                    help="reprocess files even if unchanged, overwriting extracted year data")
    ap.add_argument("--no-bundle", action="store_true",
                    help="skip rebuilding docs/data.js")
    ap.add_argument("--check", metavar="YEAR", nargs="?", const="", default=None,
                    help="reconcile data/programs/<YEAR>/ against the catalog's own "
                         "Areas of Study manifest (majors, collaterals, minors, "
                         "concentrations); defaults to the newest year")
    ap.add_argument("--seed-ge", action="store_true",
                    help="seed a missing ge.json from another year (flagged for review); "
                         "off by default because GE structure changes between regimes")
    args = ap.parse_args()

    if args.check is not None:
        year = args.check
        if not year:
            years = sorted((p.name for p in PROGRAMS_DIR.iterdir()
                            if p.is_dir() and not p.name.startswith(("_", "."))),
                           reverse=True)
            if not years:
                print("No program years found.")
                return 1
            year = years[0]
        return check_coverage(year)

    manifest = load_manifest()
    files = manifest.setdefault("files", {})
    ignore = load_ignore()
    processed = 0
    if ignore:
        print(f"Ignoring (data/.update_ignore): {', '.join(ignore)}")

    for folder, handler, kind in (
        (CATALOGS_DIR, process_catalog, "catalog"),
        (CLASS_LISTS_DIR, process_class_list, "class list"),
    ):
        pdfs = scan(folder, ignore)
        rel = folder.relative_to(REPO)
        print(f"\n{rel}/ — {len(pdfs)} PDF(s)")
        if not pdfs:
            continue
        for pdf in pdfs:
            key = str(pdf.relative_to(REPO))
            digest = sha256(pdf)
            known = files.get(key)
            if known and known.get("sha256") == digest and not args.force:
                print(f"  {pdf.name}: unchanged ({known.get('period', '?')}) — skipping")
                continue
            if known and not args.force:
                print(f"  {pdf.name}: changed since last run — reprocessing")
            result = (handler(pdf, args.dry_run, args.force, args.seed_ge)
                      if kind == "catalog" else handler(pdf, args.dry_run))
            if args.dry_run or result.get("skipped"):
                continue
            files[key] = {
                "sha256": digest,
                "kind": kind,
                "period": result.get("period"),
                "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "outputs": result.get("outputs", []),
            }
            processed += 1

    if args.dry_run:
        print("\nDry run — nothing written.")
        return 0

    save_manifest(manifest)

    if processed and not args.no_bundle:
        print("\nRebuilding docs/data.js ...")
        subprocess.run([sys.executable, str(REPO / "tools" / "bundle_web_data.py")],
                       check=False)
    elif not processed:
        print("\nNothing new to process.")

    if processed:
        print(f"\n{processed} file(s) processed. Newly extracted program files "
              f"need review against the catalog PDF before use.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
