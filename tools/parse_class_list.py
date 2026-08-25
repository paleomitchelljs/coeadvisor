#!/usr/bin/env python3
"""Parse Coe College class-list PDFs into schedule JSON files.

Usage:
    python tools/parse_class_list.py "class_lists/SP 2026 11.12.2025.pdf"
    python tools/parse_class_list.py class_lists/*.pdf

The Registrar issues the same report in two layouts, and which one you get
depends on how far along the term's build is:

  finalized  One row per section, human-readable throughout:
                 ACC 413 01 WE Auditing  C Melcher  TR 09:30 AM 10:50 AM
                 Stuart Hall  1.00
             Full titles, abbreviated instructors, truncated building names,
             no dates. Header reads "Course Number/Title".

  draft      The raw DataWindow dump, two rows per section:
                 ACC 413 01 WE 1.00 Auditing                ACC 413 01 WE
                 Carrie Melcher TR 09:30 AM 10:50 AM 08/26/2026 12/17/2026
                 COE HH 207
             Titles truncated to the column width (~31 chars), but it carries
             the things the finalized layout drops: full instructor names,
             room numbers, per-section start/end dates (so half-term courses
             are visible), and a Parent Course column that exposes
             cross-listings. Header reads "Course ... Parent Course".

`parse_pdf` sniffs the header and dispatches; both layouts produce the same
schedule JSON, so callers do not care which one they were handed.

Requires: pip install pdfplumber
"""

import json
import re
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("Error: pdfplumber not installed. Run: pip install pdfplumber")

# ── Finalized layout: column boundaries (x-coordinate thresholds) ───────────
# Determined empirically from the standardized Coe class-list PDF layout.
COL_PREFIX    =  18   # course prefix starts here
COL_NUMBER    =  35   # course number
COL_SECTION   =  52   # section number
COL_WE        =  70   # WE flag region
COL_TITLE     =  90   # title starts here
COL_INSTRUCTOR = 250  # instructor column
COL_DAYS      = 340   # days column
COL_START     = 378   # start time
COL_END       = 420   # end time
COL_BUILDING  = 465   # building/room
COL_CREDITS   = 540   # credits (right-aligned)

# Font detection
HEADER_SIZE = 11.0     # department headers are 12pt bold; data rows are 8pt
DATA_FONT_SIZE = 8.0

# Day-letter validation
VALID_DAYS = set("MTWRF")


def parse_time_24(t):
    """Convert '01:00 PM' -> '13:00', '09:30 AM' -> '09:30'."""
    if not t or t.startswith("00:00"):
        return None
    m = re.match(r'(\d{1,2}):(\d{2})\s*([AP]M)', t.strip(), re.IGNORECASE)
    if not m:
        return None
    h, mn, ap = int(m.group(1)), m.group(2), m.group(3).upper()
    if ap == "PM" and h != 12:
        h += 12
    elif ap == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mn}"


def assign_column(x0):
    """Map an x-coordinate to a column name."""
    if x0 < COL_NUMBER:
        return "prefix"
    if x0 < COL_SECTION:
        return "number"
    if x0 < COL_WE:
        return "section"
    if x0 < COL_TITLE:
        return "we_or_title"  # WE flag or start of title
    if x0 < COL_INSTRUCTOR:
        return "title"
    if x0 < COL_DAYS:
        return "instructor"
    if x0 < COL_START:
        return "days"
    if x0 < COL_END:
        return "start_time"
    if x0 < COL_BUILDING:
        return "end_time"
    if x0 < COL_CREDITS:
        return "building"
    return "credits"


def group_words_into_rows(words):
    """Group words by y-position (top) into rows, tolerating ±3pt variation."""
    if not words:
        return []
    rows = []
    current_row = [words[0]]
    current_top = words[0]["top"]
    for w in words[1:]:
        if abs(w["top"] - current_top) < 3.5:
            current_row.append(w)
        else:
            rows.append(current_row)
            current_row = [w]
            current_top = w["top"]
    rows.append(current_row)
    return rows


def row_to_record(row_words):
    """Convert a row of words into a column-assigned dict."""
    rec = {}
    for w in row_words:
        col = assign_column(w["x0"])
        if col in rec:
            rec[col] += " " + w["text"]
        else:
            rec[col] = w["text"]
    return rec


def is_dept_header(row_words):
    """Check if this row is a department header (large bold font)."""
    sizes = [w.get("size", 0) for w in row_words]
    return any(s >= HEADER_SIZE for s in sizes)


def is_page_header(row_words):
    """Check if this row is a page header/footer."""
    text = " ".join(w["text"] for w in row_words)
    if "Coe College" in text or "Course Schedules" in text:
        return True
    if "Course Number/Title" in text:
        return True
    if re.match(r'Page \d+ of \d+', text):
        return True
    if re.match(r'\d{1,2}/\d{1,2}/\d{4}', text):
        return True
    if "Writing Emphasis" in text:
        return True
    if re.match(r'\d{4}-\d{4}', text):
        return True
    return False


def is_note_line(row_words):
    """Check if this row is a sub-note like 'meets first 7 weeks'."""
    text = " ".join(w["text"] for w in row_words).lower()
    return "meets" in text and "weeks" in text


def normalize_code(prefix, number):
    """Build a normalized course code like 'BIO-145L'."""
    return f"{prefix}-{number}"


def detect_term(first_text):
    """Read '2026-2027 Fall Term' style headers into (label, term_code)."""
    if "Spring" in first_text:
        m = re.search(r'(\d{4}-\d{4})\s+Spring', first_text)
        year = m.group(1).split("-")[1] if m else "2026"
        return f"Spring {year}", f"spring_{year}"
    if "Fall" in first_text:
        m = re.search(r'(\d{4}-\d{4})\s+Fall', first_text)
        year = m.group(1).split("-")[0] if m else "2026"
        return f"Fall {year}", f"fall_{year}"
    return "Unknown", "unknown"


def parse_finalized(pdf, pdf_path):
    """Parse the one-row-per-section layout."""
    sections_list = []
    current_section = None

    # Detect term from first page header
    first_text = pdf.pages[0].extract_text() or ""
    term, term_code = detect_term(first_text)

    for page in pdf.pages:
        words = page.extract_words(extra_attrs=["fontname", "size"])
        if not words:
            continue

        rows = group_words_into_rows(words)

        for row_words in rows:
            if is_page_header(row_words):
                continue
            if is_dept_header(row_words):
                continue
            if is_note_line(row_words):
                continue

            rec = row_to_record(row_words)

            # Check if this is a course line (has prefix + number + section)
            has_prefix = "prefix" in rec
            has_number = "number" in rec
            has_section = "section" in rec

            if has_prefix and has_number and has_section:
                prefix = rec["prefix"].strip()
                number = rec["number"].strip()
                section = rec["section"].strip()

                # WE flag. On a few rows it is set tight enough against the
                # section number to fall inside the section column instead of
                # its own, which leaves a section id of "01 WE" and loses the
                # flag entirely (HIS-257, KIN-347, PR-205 in Spring 2026).
                we = False
                if section.endswith(" WE"):
                    section, we = section[:-3].strip(), True

                title_parts = []
                if "we_or_title" in rec:
                    wt = rec["we_or_title"].strip()
                    if wt.startswith("WE"):
                        we = True
                        rest = wt[2:].strip()
                        if rest:
                            title_parts.append(rest)
                    else:
                        title_parts.append(wt)
                if "title" in rec:
                    title_parts.append(rec["title"].strip())
                title = " ".join(title_parts).strip()

                instructor = rec.get("instructor", "").strip()
                days_str = rec.get("days", "").strip()
                start_raw = rec.get("start_time", "").strip()
                end_raw = rec.get("end_time", "").strip()
                building = rec.get("building", "").strip()
                credits_str = rec.get("credits", "").strip()

                # Clean credits (sometimes picks up junk like "41.00")
                credits = 0.0
                if credits_str:
                    # Take rightmost float-like match
                    cm = re.search(r'(\d+\.\d{2})$', credits_str)
                    if cm:
                        credits = float(cm.group(1))
                        # Sanity: credits > 4 is likely a parsing artifact
                        if credits > 4.5:
                            credits = float(credits_str[-4:]) if len(credits_str) >= 4 else 1.0

                code = normalize_code(prefix, number)
                start_24 = parse_time_24(start_raw)
                end_24 = parse_time_24(end_raw)

                meetings = []
                if days_str and all(c in VALID_DAYS for c in days_str) and start_24 and end_24:
                    meetings.append({
                        "days": days_str,
                        "start": start_24,
                        "end": end_24,
                        "location": building
                    })

                current_section = {
                    "code": code,
                    "section": section,
                    "title": title,
                    "instructor": instructor,
                    "we": we,
                    "credits": credits,
                    "meetings": meetings
                }
                sections_list.append(current_section)

            elif current_section is not None:
                # Continuation line: additional meeting time for the previous section
                days_str = rec.get("days", "").strip()
                start_raw = rec.get("start_time", "").strip()
                end_raw = rec.get("end_time", "").strip()
                building = rec.get("building", "").strip()
                instructor = rec.get("instructor", "").strip()

                start_24 = parse_time_24(start_raw)
                end_24 = parse_time_24(end_raw)

                if days_str and all(c in VALID_DAYS for c in days_str) and start_24 and end_24:
                    if not building and current_section["meetings"]:
                        building = current_section["meetings"][0]["location"]
                    current_section["meetings"].append({
                        "days": days_str,
                        "start": start_24,
                        "end": end_24,
                        "location": building
                    })
                # Update instructor if continuation provides one
                if instructor and not current_section["instructor"]:
                    current_section["instructor"] = instructor

    return build_schedule(sections_list, term, term_code, pdf_path)


def build_schedule(sections_list, term, term_code, pdf_path):
    """Group a flat section list by course code into the schedule schema.

    Section dicts carry the mandatory keys plus whatever extras the layout
    supplied (`part_of_term`, `cross_list`); the extras pass through only when
    present, so the finalized layout's output is unchanged.
    """
    passthrough = ("part_of_term", "cross_list")
    courses = {}
    for sec in sections_list:
        code = sec["code"]
        if code not in courses:
            courses[code] = {
                "title": sec["title"],
                "sections": []
            }
        entry = {
            "id": sec["section"],
            "instructor": sec["instructor"],
            "credits": sec["credits"],
            "we": sec["we"],
            "meetings": sec["meetings"]
        }
        for key in passthrough:
            if sec.get(key):
                entry[key] = sec[key]
        courses[code]["sections"].append(entry)
        # Use the most descriptive title (longest)
        if len(sec["title"]) > len(courses[code]["title"]):
            courses[code]["title"] = sec["title"]

    return {
        "term": term,
        "term_code": term_code,
        "source": Path(pdf_path).name,
        "courses": courses
    }


# ── Draft layout ────────────────────────────────────────────────────────────
#
# The DataWindow dump prints each section as a course row followed by one
# detail row per meeting pattern:
#
#   x:  18   36  53   68     133   154                         278
#       BIO  345L 01   WE    0.50  Techniques in Molecular Bio  BIO 345L 01 WE
#   x:      38               196   244       291       335         388     440  478  517
#           Marta Lopez      MW    01:00 PM  02:50 PM  08/26/2026  12/17/2026  COE  PH  228
#
# Column left edges, as (x0 lower bound, name). A row's cells are assembled
# from characters rather than pdfplumber words, because a title that fills its
# column runs straight into the Parent Course text with no intervening space —
# "Techniques in Molecular Biology LBIO 345L 01" comes back as one word
# spanning the boundary. Characters have their own x-extents, so the split at
# 277 lands exactly where the columns do.
#
# Prefix/number/section/WE are read as one "head" cell and split on spaces
# instead of by x-position: those four fields are packed tightly enough that a
# long number overruns the next field's left edge (ACC 171's last digit sits
# past where FS 110's section starts), while the gaps between them stay wide.
DRAFT_COURSE_COLS = (
    (0, "head"), (130, "credits"), (152, "title"), (277, "parent"),
)
DRAFT_DETAIL_COLS = (
    (0, "instructor"), (195, "days"), (240, "start_time"), (285, "end_time"),
    (330, "start_date"), (380, "end_date"), (435, "locatn"),
    (470, "building"), (510, "room"), (548, "comment"),
)

# Widest intra-word character gap at 8pt Arial. Real spaces open ~2.2pt.
CHAR_SPACE_GAP = 1.2

# Building codes, resolved against the finalized layout's own names for the
# same Fall 2026 sections. The finalized report truncates these to 20
# characters ("Center for Health an"); spelled out in full here.
DRAFT_BUILDINGS = {
    "HH": "Hickok Hall",
    "SH": "Stuart Hall",
    "PH": "Peterson Hall",
    "DW": "Dows Center",
    "EBY": "Eby Fieldhouse",
    "MR": "Marquis Hall",
    "CHS": "Center for Health and Society",
    "ARC": "Athletics and Recreation Center",
    "CRC": "Clark Racquet Center",
    "CAU": "Cherry Auditorium",
    "SCC": "Struve Communication Center",
    "SML": "Stewart Memorial Library",
    "UNV": "University of Iowa",
}

# XLC rows are the cross-listing bookkeeping entries the finalized report
# leaves out — "XLC 155  Cross Listing w/ENR 155/MTH 155". Nobody registers
# for one, and what they record is already on the real sections' `cross_list`,
# so carrying them would put a phantom course in the schedule.
DRAFT_SKIP_PREFIXES = {"XLC"}


def detect_layout(pdf):
    """'draft' or 'finalized', from the column headers on the first pages."""
    head = "\n".join((p.extract_text() or "") for p in pdf.pages[:3])
    if "Parent Course" in head and "Beg Date" in head:
        return "draft"
    return "finalized"


def _draft_rows(page):
    """Group the 8pt non-bold characters on a page into rows.

    Everything else is chrome: department headings are 12pt bold, the column
    headers and the username stamp are bold, and the "Coe College" separator
    pages carry nothing else.
    """
    chars = [c for c in page.chars
             if c.get("size", 0) < 9.0
             and "Bold" not in (c.get("fontname") or "")
             and c["text"].strip()]
    if not chars:
        return []
    chars.sort(key=lambda c: (c["top"], c["x0"]))
    rows, row, top = [], [chars[0]], chars[0]["top"]
    for c in chars[1:]:
        # The instructor name sits ~1pt above the rest of its detail row.
        if abs(c["top"] - top) < 3.5:
            row.append(c)
        else:
            rows.append(sorted(row, key=lambda w: w["x0"]))
            row, top = [c], c["top"]
    rows.append(sorted(row, key=lambda w: w["x0"]))
    return rows


def _draft_cells(row, columns):
    """Slice a row of characters into named cells by x-position."""
    cells = {}
    for c in row:
        name = columns[0][1]
        for lower, cname in columns:
            if c["x0"] >= lower:
                name = cname
        cells.setdefault(name, []).append(c)
    out = {}
    for name, chars in cells.items():
        text, prev_x1 = [], None
        for c in chars:
            if prev_x1 is not None and c["x0"] - prev_x1 > CHAR_SPACE_GAP:
                text.append(" ")
            text.append(c["text"])
            prev_x1 = c["x1"]
        out[name] = "".join(text).strip()
    return out


def _draft_location(cells):
    """'Stuart Hall 205' / 'Online' / 'Arranged' from Locatn+Bldg+Room."""
    locatn = cells.get("locatn", "").strip()
    bldg = cells.get("building", "").strip()
    room = cells.get("room", "").strip()
    if locatn == "ONLIN" or bldg == "REM":
        return "Online"
    if bldg == "AR":
        return "Arranged"
    if not bldg:
        return ""
    name = DRAFT_BUILDINGS.get(bldg, bldg)
    return f"{name} {room}".strip() if room else name


def _iso_date(s):
    """'08/26/2026' -> '2026-08-26'."""
    m = re.match(r'(\d{2})/(\d{2})/(\d{4})$', (s or "").strip())
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else None


def parse_draft(pdf, pdf_path):
    """Parse the two-rows-per-section DataWindow layout."""
    first_text = pdf.pages[0].extract_text() or ""
    term, term_code = detect_term(first_text)

    sections_list = []
    current = None
    spans = []          # (start, end) per section, for part-of-term detection
    clipped = set()     # codes whose title filled the column and lost its tail

    for page in pdf.pages:
        for row in _draft_rows(page):
            # Course rows start in the prefix column; detail rows are indented.
            head = row[0]
            if head["x0"] < 34:
                cells = _draft_cells(row, DRAFT_COURSE_COLS)
                head = cells.get("head", "").split()
                if len(head) < 3 or not (re.fullmatch(r'[A-Z]{2,4}', head[0])
                                         and re.fullmatch(r'\d{3}[A-Z]?', head[1])):
                    current = None
                    continue
                prefix, number, section = head[0], head[1], head[2]
                if prefix in DRAFT_SKIP_PREFIXES:
                    current = None
                    continue

                credits = 0.0
                cm = re.match(r'(\d+\.\d{2})$', cells.get("credits", ""))
                if cm:
                    credits = float(cm.group(1))

                code = normalize_code(prefix, number)
                current = {
                    "code": code,
                    "section": section,
                    "title": cells.get("title", ""),
                    "instructor": "",
                    # The WE slot also carries stray digits on placeholder
                    # rows ("FS 110 0 0"), so only the literal flag counts.
                    "we": len(head) > 3 and head[3] == "WE",
                    "credits": credits,
                    "meetings": [],
                }

                # Parent Course names the cross-list group a section belongs
                # to: MTH 155 and ENR 155 both report a parent of XLC 155,
                # meaning one meeting, two catalog codes.
                parent = cells.get("parent", "")
                pm = re.match(r'([A-Z]{2,4})\s+(\d{3}[A-Z]?)\b', parent)
                if pm:
                    parent_code = normalize_code(pm.group(1), pm.group(2))
                    if parent_code != code:
                        current["cross_list"] = parent_code

                title_x1 = max((c["x1"] for c in row if 152 <= c["x0"] < 277),
                               default=0)
                if title_x1 >= DRAFT_TITLE_CLIP_X:
                    clipped.add(code)

                sections_list.append(current)
                spans.append([None, None])
                continue

            if current is None:
                continue

            cells = _draft_cells(row, DRAFT_DETAIL_COLS)
            instructor = cells.get("instructor", "")
            days = cells.get("days", "")
            start = parse_time_24(cells.get("start_time", ""))
            end = parse_time_24(cells.get("end_time", ""))
            if not (instructor or days or start):
                continue    # page furniture, e.g. the "2026-2027 Fall Term" stamp

            if instructor and not current["instructor"]:
                current["instructor"] = instructor
            if days and all(c in VALID_DAYS for c in days) and start and end:
                current["meetings"].append({
                    "days": days,
                    "start": start,
                    "end": end,
                    "location": _draft_location(cells),
                })

            d0, d1 = _iso_date(cells.get("start_date", "")), _iso_date(cells.get("end_date", ""))
            span = spans[-1]
            if d0 and (span[0] is None or d0 < span[0]):
                span[0] = d0
            if d1 and (span[1] is None or d1 > span[1]):
                span[1] = d1

    # Sections that run only part of the term get their dates recorded: that
    # is how the half-semester courses (08/26-10/14 vs 10/19-12/17)
    # distinguish themselves, and several of them carry no meeting pattern at
    # all, so the dates are the only signal they are not full-term.
    #
    # "Different from the term span" is too loose a test — the arranged
    # independent studies end 12/18 against the term's 12/17, and those are
    # full-term by any reading. Only a span materially inside the term counts.
    t0, t1 = _modal_span(spans)
    for sec, (d0, d1) in zip(sections_list, spans):
        if not (d0 and d1 and t0 and t1):
            continue
        if _days_between(t0, d0) > PART_OF_TERM_SLACK or _days_between(d1, t1) > PART_OF_TERM_SLACK:
            sec["part_of_term"] = {"start": d0, "end": d1}

    schedule = build_schedule(sections_list, term, term_code, pdf_path)
    schedule["_clipped_titles"] = sorted(clipped)
    return schedule


# The title column ends at x=277.5. A title that reaches this near the edge
# lost its tail; the Registrar's own short forms stop by x=253.
DRAFT_TITLE_CLIP_X = 262


# How far a section's dates may sit inside the term's before it stops counting
# as full-term. Anything shorter at either end is a half-semester offering.
PART_OF_TERM_SLACK = 7


def _days_between(a, b):
    """Whole days from ISO date `a` to `b`; negative if `b` is earlier."""
    from datetime import date
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _modal_span(spans):
    """The (start, end) pair shared by most sections — the full term."""
    counts = {}
    for s in spans:
        if s[0] and s[1]:
            counts[(s[0], s[1])] = counts.get((s[0], s[1]), 0) + 1
    return max(counts, key=counts.get) if counts else (None, None)


def parse_pdf(pdf_path):
    """Parse a class-list PDF of either layout into schedule JSON."""
    with pdfplumber.open(pdf_path) as pdf:
        layout = detect_layout(pdf)
        schedule = (parse_draft if layout == "draft" else parse_finalized)(pdf, pdf_path)
        schedule["layout"] = layout
        # The Registrar reissues this report repeatedly for one term. The PDF's
        # own creation date is what tells two issues apart; the filenames do
        # not reliably.
        rev = _pdf_date(pdf.metadata.get("CreationDate"))
        if rev:
            schedule["revision"] = rev
    return schedule


def _pdf_date(raw):
    """"D:20260817083339-05'00'" -> '2026-08-17'."""
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", raw or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def restore_truncated_titles(schedule, sources):
    """Repair titles the draft layout clipped at its column width.

    Two guards keep this from rewriting titles that were never broken:

    * Only courses whose title ran to the edge of the title column are
      considered. The Registrar's own abbreviations stop well short of it —
      "Comparative Chordate Anat" is what BIO-365 is called in *both* layouts,
      not a clipping, so promoting it to the catalog's "...Anatomy" would be
      changing the vocabulary rather than fixing a defect.
    * The replacement must *start with* the clipped title, so an extension is
      only ever the missing tail.

    Sources are consulted in order and the first extension wins, so the
    Registrar's wording from a previous issue of the same term beats the
    catalog's formal title ("...Biology Lab", not "...Biology Laboratory").
    """
    # Only the draft layout records clip positions; for any other layout there
    # is nothing to repair and this is a no-op.
    clipped = set(schedule.pop("_clipped_titles", []) or [])
    fixed = 0
    for code, course in schedule["courses"].items():
        if code not in clipped:
            continue
        title = course["title"]
        for src in sources:
            cand = src.get(code)
            if cand and len(cand) > len(title) and cand.startswith(title):
                course["title"] = cand
                fixed += 1
                break
    return fixed


def catalog_year_for(term_code):
    """'fall_2026' -> '2026-27'; 'spring_2026' -> '2025-26'.

    Fall opens the academic year, so it keeps its own calendar year; the
    terms after it belong to the year that started the previous autumn.
    """
    m = re.match(r'(fall|spring|summer|may|winter|interim)_(\d{4})$', term_code or "")
    if not m:
        return None
    start = int(m.group(2)) - (0 if m.group(1) == "fall" else 1)
    return f"{start}-{str(start + 1)[-2:]}"


def title_sources(repo_root, term_code, catalog_year=None):
    """Longer-title lookups for `restore_truncated_titles`, best first.

    The previous parse of the same term speaks the Registrar's vocabulary, so
    it is tried before the catalog, whose titles are the formal ones.
    """
    sources = []
    prev = Path(repo_root) / "data" / "schedules" / f"{term_code}.json"
    if prev.exists():
        try:
            data = json.loads(prev.read_text())
            sources.append({c: v.get("title", "")
                            for c, v in data.get("courses", {}).items()})
        except Exception:
            pass
    if catalog_year:
        cat = (Path(repo_root) / "data" / "catalog_years" / catalog_year / "courses.json")
        if cat.exists():
            try:
                data = json.loads(cat.read_text())
                titles = {}
                for pd in data.get("prefixes", {}).values():
                    for code, c in pd.get("courses", {}).items():
                        titles[code] = c.get("title", "") if isinstance(c, dict) else c
                sources.append(titles)
            except Exception:
                pass
    return sources


def supersedes(schedule, out_file):
    """Is `schedule` at least as current as what `out_file` already holds?

    Several PDFs describe the same term — the Registrar reissues the report as
    the build firms up — and they all write to the same filename. Without this
    an older reissue silently overwrites a newer one, which is exactly what
    happens when the files are processed in filename order.
    """
    if not Path(out_file).exists():
        return True, None
    try:
        existing = json.loads(Path(out_file).read_text())
    except Exception:
        return True, None
    old, new = existing.get("revision"), schedule.get("revision")
    if old and new and new < old:
        return False, f"{Path(out_file).name} already holds a newer issue ({old})"
    return True, None


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/parse_class_list.py <pdf_file> [<pdf_file> ...]")
        sys.exit(1)

    out_dir = Path("data/schedules")
    out_dir.mkdir(parents=True, exist_ok=True)

    for pdf_path in sys.argv[1:]:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            print(f"File not found: {pdf_path}")
            continue

        print(f"Parsing {pdf_path.name}...")
        schedule = parse_pdf(pdf_path)
        out_file = out_dir / f"{schedule['term_code']}.json"

        ok, why = supersedes(schedule, out_file)
        if not ok:
            print(f"  .. skipped: {why}")
            continue

        term_code = schedule["term_code"]
        fixed = restore_truncated_titles(
            schedule, title_sources(Path.cwd(), term_code,
                                    catalog_year_for(term_code)))
        if fixed:
            print(f"  .. restored {fixed} title(s) clipped by the draft layout")

        n_courses = len(schedule["courses"])
        n_sections = sum(len(c["sections"]) for c in schedule["courses"].values())
        n_with_meetings = sum(
            1 for c in schedule["courses"].values()
            for s in c["sections"] if s["meetings"]
        )

        with open(out_file, "w") as f:
            json.dump(schedule, f, indent=2)

        print(f"  -> {out_file} ({n_courses} courses, {n_sections} sections, "
              f"{n_with_meetings} with scheduled meetings)")


if __name__ == "__main__":
    main()
