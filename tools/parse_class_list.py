#!/usr/bin/env python3
"""Parse Coe College class-list PDFs into schedule JSON files.

Usage:
    python tools/parse_class_list.py "class_lists/SP 2026 11.12.2025.pdf"
    python tools/parse_class_list.py class_lists/*.pdf

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

# ── Column boundaries (x-coordinate thresholds) ─────────────────────────────
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


def parse_pdf(pdf_path):
    """Parse a class-list PDF and return structured schedule data."""
    sections_list = []
    current_section = None

    with pdfplumber.open(pdf_path) as pdf:
        # Detect term from first page header
        first_text = pdf.pages[0].extract_text() or ""
        term = "Unknown"
        term_code = "unknown"
        if "Spring" in first_text:
            m = re.search(r'(\d{4}-\d{4})\s+Spring', first_text)
            year = m.group(1).split("-")[1] if m else "2026"
            term = f"Spring {year}"
            term_code = f"spring_{year}"
        elif "Fall" in first_text:
            m = re.search(r'(\d{4}-\d{4})\s+Fall', first_text)
            year = m.group(1).split("-")[0] if m else "2026"
            term = f"Fall {year}"
            term_code = f"fall_{year}"

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

                    # WE flag
                    we = False
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

    # Group by course code
    courses = {}
    for sec in sections_list:
        code = sec["code"]
        if code not in courses:
            courses[code] = {
                "title": sec["title"],
                "sections": []
            }
        courses[code]["sections"].append({
            "id": sec["section"],
            "instructor": sec["instructor"],
            "credits": sec["credits"],
            "we": sec["we"],
            "meetings": sec["meetings"]
        })
        # Use the most descriptive title (longest)
        if len(sec["title"]) > len(courses[code]["title"]):
            courses[code]["title"] = sec["title"]

    return {
        "term": term,
        "term_code": term_code,
        "source": Path(pdf_path).name,
        "courses": courses
    }


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

        n_courses = len(schedule["courses"])
        n_sections = sum(len(c["sections"]) for c in schedule["courses"].values())
        n_with_meetings = sum(
            1 for c in schedule["courses"].values()
            for s in c["sections"] if s["meetings"]
        )

        out_file = out_dir / f"{schedule['term_code']}.json"
        with open(out_file, "w") as f:
            json.dump(schedule, f, indent=2)

        print(f"  -> {out_file} ({n_courses} courses, {n_sections} sections, "
              f"{n_with_meetings} with scheduled meetings)")


if __name__ == "__main__":
    main()
