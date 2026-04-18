#!/usr/bin/env python3
"""Extract major/minor/collateral program requirements from Coe College catalog PDFs.

Usage:
    python3 tools/extract_programs.py "catalogs/Academic Catalog 2025-26.pdf"
    python3 tools/extract_programs.py catalogs/*.pdf

Outputs one JSON file per program into data/programs/<catalog_year>/.
Files need human review — the extractor handles ~80% of the structure
automatically but constraints, exclude_codes, and edge cases require
manual touch-up.

Requires: pip install pdfplumber
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("Error: pdfplumber not installed. Run: pip install pdfplumber")

REPO = Path(__file__).resolve().parent.parent

# ── Course code regex ──────────────────────────────────────────────────────
CODE_RE = re.compile(r'([A-Z]{2,4})-\s?(\d{3}[A-Z]?)')
# Combined code: BIO-145/-145L or CHM-431/-431L (allows optional space after dash)
COMBINED_RE = re.compile(r'([A-Z]{2,4})-\s?(\d{3}[A-Z]?)(?:/(?:-?\s?)(\d{3}[A-Z]?))?')

# ── Program header patterns ───────────────────────────────────────────────
PROGRAM_HEADER_RE = re.compile(
    r'^(Collateral Major in .+|.+?\s+Major(?:\s*[—–-]\s*.+)?|.+?\s+Minor'
    r'|.+?Major\s+Areas?\s+of\s+Emphasis'
    r'|Bachelor of (?:Arts|Science)[:\s]+.+Major)$'
)

# Numbered requirement line: "1. ..." or "5-9. ..." (range)
NUMBERED_RE = re.compile(r'^(\d{1,2})(?:-\d{1,2})?\.\s+(.+)$')

# "One/Two/Three of the following:" etc.
# Also catches "One Introductory Mathematics course:" patterns
CHOOSE_N_RE = re.compile(
    r'^(?:(?:One|Two|Three|Four|Five|Six|Seven|Eight)\s+of\s+the\s+following'
    r'|(?:One|Two|Three|Four|Five|Six|Seven|Eight)\s+'
    r'(?:additional\s+|or more\s+)?(?:[A-Z]\w+\s+)*courses?\b)',
    re.IGNORECASE
)

# "All of the following"
ALL_OF_RE = re.compile(r'All\s+of\s+the\s+following', re.IGNORECASE)

# "or" on its own line
OR_LINE_RE = re.compile(r'^\s*or\s*$', re.IGNORECASE)

# Number words
NUM_WORDS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
}

# Lines that terminate a program's requirements
STOP_PATTERNS = [
    re.compile(r'^Strongly recommended', re.IGNORECASE),
    re.compile(r'^Recommended:?\s*$', re.IGNORECASE),
    re.compile(r'^Students completing'),
    re.compile(r'^Students planning'),
    re.compile(r'^Students should'),
    re.compile(r'^Students seeking'),
    re.compile(r'^Students interested'),
    re.compile(r'^Students are required'),
    re.compile(r'^Students are strongly'),
    re.compile(r'^Students earning'),
    re.compile(r'^Students who'),
    re.compile(r'^NOTE:', re.IGNORECASE),
    re.compile(r'^Scheduling may'),
    re.compile(r'^With (?:consent|departmental|permission)', re.IGNORECASE),
    re.compile(r'^Laboratory Study'),
    re.compile(r'^Concentrations? (?:in|within)', re.IGNORECASE),
    re.compile(r'^To complete a concentration'),
    re.compile(r'^The Education Department'),
    re.compile(r'^COURSES IN ', re.IGNORECASE),
    re.compile(r'^Jazz Emphasis'),
    re.compile(r'^Music Industry Emphasis'),
    re.compile(r'^[—–][A-Z]'),  # em-dash department header
]

# Common prefix to major_code mappings
PREFIX_MAP = {
    'African American Studies': 'AAM',
    'American Chemical Society Certified Chemistry': 'CHM',
    'Art': 'ART',
    'Art History': 'ARH',
    'Asian Studies': 'AS',
    'Biochemistry': 'BIO',
    'Biology': 'BIO',
    'Business Administration': 'BUS',
    'Chemistry': 'CHM',
    'Classical Studies': 'CLA',
    'Communication Studies': 'COM',
    'Computer Science': 'CS',
    'Creative Writing': 'CRW',
    'Data Science': 'DS',
    'Economics': 'ECO',
    'Elementary Education': 'EDU',
    'Engineering Physics': 'PHY',
    'English': 'ENG',
    'Environmental Science': 'BIO',
    'Environmental Studies': 'EVS',
    'Film Studies': 'FLM',
    'Gender and Sexuality Studies': 'GS',
    'Health and Society Studies': 'SOC',
    'History': 'HIS',
    'Interdisciplinary Science': 'SCI',
    'International Economics': 'ECO',
    'International Business': 'BUS',
    'International Studies': 'IS',
    'Kinesiology': 'KIN',
    'Literature': 'ENG',
    'Mathematics': 'MTH',
    'Applied Mathematics': 'MTH',
    'Managerial Accounting': 'ACC',
    'Molecular Biology': 'BIO',
    'Museum Studies': 'MS',
    'Music': 'MU',
    'Neuroscience': 'NEU',
    'Nursing': 'NUR',
    'Organizational Science': 'PSY',
    'Philosophy': 'PHL',
    'Physics': 'PHY',
    'Political Science': 'POL',
    'Psychology': 'PSY',
    'Public Accounting': 'ACC',
    'Public Relations': 'PR',
    'Religion': 'REL',
    'Social & Criminal Justice': 'SCJ',
    'Secondary Education': 'EDU',
    'Sociology': 'SOC',
    'Spanish': 'SPA',
    'Spanish Studies': 'SPA',
    'Theatre Arts': 'THE',
    'Theatre': 'THE',
    'Writing and Rhetoric': 'ENG',
}


def extract_codes(text: str) -> list[str]:
    """Extract all course codes from a text string.

    Returns codes like ['BIO-145', 'BIO-145L'].
    Handles combined listings: BIO-145/-145L -> ['BIO-145', 'BIO-145L']
    """
    codes = []
    for m in COMBINED_RE.finditer(text):
        prefix = m.group(1)
        num1 = m.group(2)
        num2 = m.group(3)
        codes.append(f"{prefix}-{num1}")
        if num2:
            codes.append(f"{prefix}-{num2}")
    # Also handle "and PREFIX-NUM" patterns
    and_pattern = re.compile(r'and\s+([A-Z]{2,4})-(\d{3}[A-Z]?)(?:/(?:-?)(\d{3}[A-Z]?))?')
    for m in and_pattern.finditer(text):
        c = f"{m.group(1)}-{m.group(2)}"
        if c not in codes:
            codes.append(c)
        if m.group(3):
            c2 = f"{m.group(1)}-{m.group(3)}"
            if c2 not in codes:
                codes.append(c2)
    return codes


def clean_title(text: str) -> str:
    """Strip course codes, parenthetical credit notes, and cleanup whitespace."""
    # Remove leading number+period
    text = re.sub(r'^\d{1,2}\.\s*', '', text)
    # Remove course codes (including combined like BIO-145/-145L, CS- 245)
    text = re.sub(r'[A-Z]{2,4}-\s?\d{3}[A-Z]?(?:/(?:-?\s?)\d{3}[A-Z]?)?', '', text)
    # Remove "and Laboratory", "& Laboratory" that's left orphaned
    text = re.sub(r'^\s*(?:and|&)\s+', '', text)
    # Remove WE markers: "(WE)", "(WE", "WE)"
    text = re.sub(r'\(WE\)?', '', text)
    text = re.sub(r'\bWE\)', '', text)
    # Remove credit notes like "(0.5 course credit)" "(0.2 cc)" "(0.3 cc)"
    text = re.sub(r'\(\d+\.?\d*\s*(?:course\s+)?credits?\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\(\d+\.?\d*\s*cc\)', '', text, flags=re.IGNORECASE)
    # Remove "(7 weeks)"
    text = re.sub(r'\(\d+\s*weeks?\)', '', text, flags=re.IGNORECASE)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove trailing punctuation artifacts
    text = text.rstrip(' ,:;-—–')
    return text


def make_item_id(codes: list[str], title: str) -> str:
    """Generate a section item ID from codes or title."""
    if codes:
        return codes[0].lower().replace('-', '')
    slug = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')
    return slug[:40]


def parse_choose_n(text: str) -> int:
    """Extract the N from 'One of the following', 'Two additional courses', etc.

    Only matches the FIRST number word in the text, to avoid confusion with
    embedded counts like 'at least three' in open_n descriptions.
    """
    text_lower = text.lower().split()
    if text_lower:
        first_word = text_lower[0]
        if first_word in NUM_WORDS:
            return NUM_WORDS[first_word]
    return 1


def detect_catalog_year(pdf, pdf_path: str = '') -> str:
    """Detect catalog year from PDF text or filename, e.g. '2025-26'."""
    # Try first few pages (page 1 is often a cover with broken text)
    for page_idx in range(min(5, len(pdf.pages))):
        text = pdf.pages[page_idx].extract_text() or ''
        m = re.search(r'(\d{4})\s*[–-]\s*(\d{4})', text)
        if m:
            y1 = m.group(1)
            y2 = m.group(2)[-2:]
            return f"{y1}-{y2}"
    # Try page footers (e.g. "Coe College Catalog (2025-2026)")
    for page_idx in range(min(30, len(pdf.pages))):
        text = pdf.pages[page_idx].extract_text() or ''
        m = re.search(r'Catalog\s*\((\d{4})[–-](\d{4})\)', text)
        if m:
            y1 = m.group(1)
            y2 = m.group(2)[-2:]
            return f"{y1}-{y2}"
    # Fallback: extract from filename like "Academic Catalog 2025-26.pdf"
    if pdf_path:
        m = re.search(r'(\d{4})-(\d{2,4})', Path(pdf_path).stem)
        if m:
            y1 = m.group(1)
            y2 = m.group(2)[-2:]
            return f"{y1}-{y2}"
    return "unknown"


def is_stop_line(line: str) -> bool:
    """Check if this line signals end of requirements."""
    for pat in STOP_PATTERNS:
        if pat.search(line):
            return True
    return False


def guess_program_type(header: str) -> str:
    """Guess program_type from header text."""
    h = header.lower()
    if 'collateral' in h:
        return 'collateral'
    if 'minor' in h:
        return 'minor'
    return 'major'


def guess_major_code(name: str) -> str:
    """Guess the major_code prefix from program name."""
    if name in PREFIX_MAP:
        return PREFIX_MAP[name]
    for key, code in PREFIX_MAP.items():
        if key in name:
            return code
    return ''


def make_program_id(name: str, prog_type: str, catalog_year: str) -> str:
    """Generate a program ID like 'biology_major_2025-26'."""
    slug = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    for suffix in ('_major', '_minor', '_collateral'):
        if slug.endswith(suffix):
            slug = slug[:-len(suffix)]
    return f"{slug}_{prog_type}_{catalog_year}"


def parse_program_name(header: str) -> tuple[str, str]:
    """Parse header into (program_name, program_type)."""
    header = header.strip()
    prog_type = guess_program_type(header)

    if header.startswith('Collateral Major in '):
        name = header.replace('Collateral Major in ', '')
        return name.strip(), 'collateral'

    name = re.sub(r'\s+Major\b', '', header)
    name = re.sub(r'\s+Minor\b', '', name)
    name = re.sub(r'^BACHELOR OF (?:ARTS|SCIENCE)[:\s]+', '', name, flags=re.IGNORECASE)
    name = re.sub(r'^Bachelor of (?:Arts|Science)[:\s]+', '', name)

    return name.strip(), prog_type


def extract_pages_text(pdf) -> list[str]:
    """Extract text from all pages, returning list of page texts."""
    return [page.extract_text() or '' for page in pdf.pages]


def find_programs(pages_text: list[str]) -> list[dict]:
    """Find all program requirement sections in the catalog.

    Concatenates all pages (filtering footers) into one line stream,
    then identifies program headers and collects numbered requirements.
    This correctly handles requirements that span page boundaries.

    Returns list of dicts with: header, page, raw_lines
    """
    # Build a single line stream with page numbers
    all_lines = []  # list of (line_text, page_number)
    for page_idx, text in enumerate(pages_text):
        for line in text.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            # Skip page footers
            if stripped.startswith('Coe College Catalog'):
                continue
            all_lines.append((stripped, page_idx + 1))

    programs = []
    i = 0
    while i < len(all_lines):
        line, page_num = all_lines[i]

        # Check for program header
        if not PROGRAM_HEADER_RE.match(line):
            i += 1
            continue

        # Skip table-of-contents style entries
        if any(skip in line for skip in [
            'Areas of Study', 'Area of Study',
            'Major Areas of Emphasis',
        ]):
            i += 1
            continue

        header = line
        header_page = page_num
        i += 1

        # Collect requirement lines: skip preamble, gather numbered items + sub-items
        req_lines = []
        found_numbered = False
        while i < len(all_lines):
            cur, _ = all_lines[i]

            # Stop at next program header
            if PROGRAM_HEADER_RE.match(cur) and not cur.startswith('All of'):
                break

            # Stop at known terminators
            if is_stop_line(cur):
                i += 1
                break

            # Check if this is a numbered requirement
            if NUMBERED_RE.match(cur):
                found_numbered = True

            if found_numbered:
                req_lines.append(cur)
            # else: preamble — skip

            i += 1

        if req_lines:
            programs.append({
                'header': header,
                'page': header_page,
                'raw_lines': req_lines,
            })

    return programs


def parse_requirements(raw_lines: list[str]) -> list[dict]:
    """Parse numbered requirement lines into program sections."""
    sections = []

    # Group lines by numbered requirement
    groups = []
    current_group = None
    next_pseudo_num = 100  # for non-numbered structural lines

    for line in raw_lines:
        m = NUMBERED_RE.match(line)
        if m:
            num = int(m.group(1))
            text = m.group(2).strip()
            current_group = {'num': num, 'text': text, 'sub_lines': []}
            groups.append(current_group)
        elif (ALL_OF_RE.match(line) or CHOOSE_N_RE.match(line)
              or re.match(r'^(?:FOUR|FIVE|SIX|SEVEN|EIGHT)\s+of\s+the\s+following', line, re.IGNORECASE)):
            # Non-numbered structural line (e.g. "All of the following courses...")
            current_group = {'num': next_pseudo_num, 'text': line.strip(), 'sub_lines': []}
            next_pseudo_num += 1
            groups.append(current_group)
        elif line.strip().upper() == 'OR' and current_group is not None:
            # "OR" separating two option groups within a requirement
            current_group['sub_lines'].append(line.strip())
        elif current_group is not None:
            current_group['sub_lines'].append(line.strip())

    for group in groups:
        section = parse_single_requirement(group['num'], group['text'], group['sub_lines'])
        if section:
            sections.append(section)

    return sections


def parse_single_requirement(num: int, text: str, sub_lines: list[str]) -> dict | None:
    """Parse a single numbered requirement into a section dict."""

    codes = extract_codes(text)

    # ── Pattern: "One of the following:" with sub-items ───────────────
    # Also catch lines ending with ":" that have sub-items containing course codes
    has_coded_subs = sub_lines and any(CODE_RE.search(sl) for sl in sub_lines)
    is_choose = (CHOOSE_N_RE.match(text) or text.rstrip(':').endswith('following')
                 or (text.endswith(':') and has_coded_subs))
    if is_choose and sub_lines:
        n = parse_choose_n(text)
        options = parse_sub_options(sub_lines)

        if not options:
            return {
                'id': f'req_{num}',
                'label': text.rstrip(':'),
                'type': 'non_course',
                'description': text + '\n' + '\n'.join(sub_lines),
                '_review': True,
            }

        if n == 1:
            return {
                'id': f'req_{num}',
                'label': clean_label(text),
                'type': 'choose_one',
                'options': options,
            }
        else:
            return {
                'id': f'req_{num}',
                'label': clean_label(text),
                'type': 'choose_n',
                'n': n,
                'options': options,
            }

    # ── Pattern: "All of the following" with sub-items ────────────────
    if ALL_OF_RE.match(text) and sub_lines:
        items = parse_sub_items(sub_lines)
        return {
            'id': f'req_{num}',
            'label': clean_label(text),
            'type': 'all',
            'items': items,
        }

    # ── Pattern: Open-ended electives (N courses with constraints) ────
    open_n = detect_open_n(text, sub_lines)
    if open_n:
        return open_n | {'id': f'req_{num}'}

    # ── Pattern: Simple course requirement ────────────────────────────
    if codes:
        return None  # Will be grouped into an 'all' section

    # ── Pattern: Non-course requirement ───────────────────────────────
    desc = text
    if sub_lines:
        desc += '\n' + '\n'.join(sub_lines)
    return {
        'id': f'req_{num}',
        'label': text.rstrip(':'),
        'type': 'non_course',
        'description': desc,
        '_review': True,
    }


def parse_sub_options(sub_lines: list[str]) -> list[dict]:
    """Parse sub-items under a 'one of the following' requirement.

    Handles:
    - Simple course lines: BIO-145/-145L Cellular and Molecular Biology
    - Multi-code options: STA-100 ... and STA-110 ...
    - "or" separated groups
    """
    options = []
    current_option_lines = []

    for line in sub_lines:
        if not line.strip():
            continue

        # Skip note/recommendation lines that happen to contain course codes
        line_lower = line.lower()
        if any(w in line_lower for w in ['encouraged', 'recommended', 'strongly']):
            break

        # "or" on its own line = separator between option groups
        if OR_LINE_RE.match(line):
            if current_option_lines:
                opt = build_option_from_lines(current_option_lines)
                if opt:
                    options.append(opt)
                current_option_lines = []
            continue

        if CODE_RE.search(line):
            if current_option_lines and not line.startswith(' '):
                opt = build_option_from_lines(current_option_lines)
                if opt:
                    options.append(opt)
                current_option_lines = [line]
            else:
                current_option_lines.append(line)
        elif current_option_lines:
            current_option_lines.append(line)

    if current_option_lines:
        opt = build_option_from_lines(current_option_lines)
        if opt:
            options.append(opt)

    return options


def build_option_from_lines(lines: list[str]) -> dict | None:
    """Build a single option dict from one or more text lines."""
    full_text = ' '.join(lines)
    codes = extract_codes(full_text)
    if not codes:
        return None
    title = clean_title(full_text)
    return {
        'id': make_item_id(codes, title),
        'title': title if title else ' + '.join(codes),
        'codes': codes,
    }


def parse_sub_items(sub_lines: list[str]) -> list[dict]:
    """Parse sub-items for an 'all' section (items that are all required)."""
    items = []
    for line in sub_lines:
        codes = extract_codes(line)
        if codes:
            title = clean_title(line)
            items.append({
                'id': make_item_id(codes, title),
                'title': title if title else ' + '.join(codes),
                'codes': codes,
            })
    return items


def detect_open_n(text: str, sub_lines: list[str]) -> dict | None:
    """Detect open_n requirements like 'Three biology electives' or
    'Two additional courses numbered 200 or above'."""

    text_lower = text.lower()

    # Extract N from the FIRST number word only
    n_match = None
    first_word = text_lower.split()[0] if text_lower.split() else ''
    if first_word in NUM_WORDS:
        n_match = NUM_WORDS[first_word]
    # Also try leading digit: "4 biology electives"
    if not n_match:
        m = re.match(r'(\d+)\s+', text)
        if m:
            n_match = int(m.group(1))

    if not n_match:
        return None

    # Must have elective/course language without enumerated sub-items with codes
    elective_words = ['elective', 'course', 'credit', 'additional']
    if not any(w in text_lower for w in elective_words):
        return None

    # If sub_lines have course codes, this is probably choose_n, not open_n
    sub_has_codes = any(CODE_RE.search(sl) for sl in sub_lines)
    if sub_has_codes:
        return None

    # Try to extract constraints from the text
    constraints = {}

    # Prefix detection: look for department name patterns
    prefix_hints = CODE_RE.findall(text)
    if prefix_hints:
        constraints['prefixes'] = list(set(p[0] for p in prefix_hints))
    else:
        # Infer prefix from keywords like "biology electives", "history courses"
        prefix_keywords = {
            'biology': ['BIO'], 'chemistry': ['CHM'], 'physics': ['PHY'],
            'mathematics': ['MTH'], 'math': ['MTH'], 'history': ['HIS'],
            'psychology': ['PSY'], 'sociology': ['SOC'], 'english': ['ENG'],
            'computer science': ['CS', 'DS'], 'art': ['ART'],
            'music': ['MU'], 'communication': ['COM'], 'political science': ['POL'],
            'economics': ['ECO'], 'philosophy': ['PHL'], 'religion': ['REL'],
            'spanish': ['SPA'], 'business': ['BUS'], 'education': ['EDU'],
            'kinesiology': ['KIN'], 'nursing': ['NUR'], 'theatre': ['THE'],
        }
        for kw, prefixes in prefix_keywords.items():
            if kw in text_lower:
                constraints['prefixes'] = prefixes
                break

    # Level detection: "200-level or higher", "numbered 300 or above"
    level_match = re.search(r'(\d{3})\s*(?:-?\s*level|or (?:higher|above)|numbered)', text_lower)
    if level_match:
        constraints['min_level'] = int(level_match.group(1))

    # "at least N must be 200-level"
    at_least = re.search(r'at least (\w+)\s+must be\s+(\d{3})', text_lower)
    if at_least:
        count_word = at_least.group(1)
        level = int(at_least.group(2))
        count = NUM_WORDS.get(count_word, 1)
        constraints['min_level'] = level
        constraints['min_level_count'] = count

    # "one of which must be 300 level or above"
    one_must = re.search(r'(\w+)\s+of which must be\s+(\d{3})', text_lower)
    if one_must:
        count_word = one_must.group(1)
        level = int(one_must.group(2))
        count = NUM_WORDS.get(count_word, 1)
        constraints['min_level'] = level
        constraints['min_level_count'] = count

    return {
        'label': clean_title_for_label(text),
        'type': 'open_n',
        'n': n_match,
        'description': text,
        'constraints': constraints if constraints else {},
        '_review': True,
    }


def clean_title_for_label(text: str) -> str:
    """Clean a requirement text for use as a label.

    Removes trailing clauses in parentheses that got cut off by page breaks,
    and trims excessive length.
    """
    # Remove trailing incomplete parenthetical
    text = re.sub(r'\([^)]*$', '', text).strip()
    # Trim to reasonable length
    if len(text) > 100:
        text = text[:97] + '...'
    return text.rstrip(':;,. ')


def clean_label(text: str) -> str:
    """Clean a requirement label: remove trailing colon/punctuation.

    Strips 'of the following' boilerplate but keeps the descriptive prefix.
    If only 'N of the following:' remains, generates a descriptive label.
    """
    text = text.rstrip(':;,.')
    # Strip 'of the following' suffix, keeping any prefix like "One Management course"
    cleaned = re.sub(r'\s*(?:of\s+the\s+following)\s*:?\s*$', '', text, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    # If only the number word remains (e.g. "FOUR"), make a better label
    if cleaned.lower() in NUM_WORDS or not cleaned:
        n = NUM_WORDS.get(cleaned.lower(), 1) if cleaned else 1
        if n == 1:
            return "Choose One"
        return f"Choose {cleaned.title()}"
    return cleaned


def group_simple_courses(sections: list[dict], raw_lines: list[str]) -> list[dict]:
    """Group consecutive simple-course requirements into an 'all' section.

    The main parser returns None for simple course items. This function
    re-reads the raw lines, identifies numbered items that are just course
    codes (not choose_one, not open_n), and groups them into an 'all' section.
    """
    result = []

    # Build a set of requirement numbers that already have sections
    handled_nums = set()
    for sec in sections:
        if sec:
            m = re.match(r'req_(\d+)', sec['id'])
            if m:
                handled_nums.add(int(m.group(1)))

    # Re-parse raw lines for simple courses
    simple_items = []
    groups = []
    current_group = None
    for line in raw_lines:
        m = NUMBERED_RE.match(line)
        if m:
            num = int(m.group(1))
            text = m.group(2).strip()
            current_group = {'num': num, 'text': text, 'sub_lines': []}
            groups.append(current_group)
        elif current_group:
            current_group['sub_lines'].append(line.strip())

    for group in groups:
        num = group['num']
        text = group['text']

        if num in handled_nums:
            continue

        codes = extract_codes(text)
        if not codes:
            continue

        if CHOOSE_N_RE.match(text) or ALL_OF_RE.match(text):
            continue

        title = clean_title(text)
        simple_items.append({
            'id': make_item_id(codes, title),
            'title': title if title else ' + '.join(codes),
            'codes': codes,
        })

    # Insert an 'all' section at the front with all simple items
    if simple_items:
        all_section = {
            'id': 'core',
            'label': 'Required Courses',
            'type': 'all',
            'items': simple_items,
        }
        result.append(all_section)

    # Then add the non-None structured sections
    for sec in sections:
        if sec:
            result.append(sec)

    return result


def build_program_json(prog_info: dict, catalog_year: str) -> dict:
    """Build a complete program JSON from parsed info."""
    header = prog_info['header']
    name, prog_type = parse_program_name(header)
    major_code = guess_major_code(name.split('—')[0].split('–')[0].strip())

    sections_raw = parse_requirements(prog_info['raw_lines'])
    sections = group_simple_courses(sections_raw, prog_info['raw_lines'])

    prog_id = make_program_id(name, prog_type, catalog_year)

    result = {
        'id': prog_id,
        'name': name,
        'program_type': prog_type,
        'catalog_year': catalog_year,
    }
    if major_code:
        result['major_code'] = major_code
    result['source'] = f"Academic Catalog {catalog_year}, p. {prog_info['page']}"
    result['sections'] = sections

    needs_review = any(s.get('_review') for s in sections)
    if needs_review:
        result['_needs_review'] = True

    return result


def strip_review_flags(obj):
    """Recursively remove _review flags from the output."""
    if isinstance(obj, dict):
        return {k: strip_review_flags(v) for k, v in obj.items() if k != '_review'}
    if isinstance(obj, list):
        return [strip_review_flags(item) for item in obj]
    return obj


def make_filename(prog_id: str, catalog_year: str) -> str:
    """Generate output filename from program ID, stripping the catalog year suffix."""
    suffix = f'_{catalog_year}'
    if prog_id.endswith(suffix):
        return prog_id[:-len(suffix)] + '.json'
    return prog_id + '.json'


def deduplicate_programs(programs: list[dict]) -> list[dict]:
    """Remove duplicate programs (same filename), keeping the one with more sections."""
    seen = {}
    for prog in programs:
        filename = make_filename(prog['id'], prog['catalog_year'])
        if filename not in seen:
            seen[filename] = prog
        else:
            # Keep the one with more sections
            existing = seen[filename]
            if len(prog.get('sections', [])) > len(existing.get('sections', [])):
                seen[filename] = prog
    return list(seen.values())


def parse_catalog(pdf_path: str) -> list[dict]:
    """Parse a catalog PDF and return list of program JSON dicts."""
    with pdfplumber.open(pdf_path) as pdf:
        catalog_year = detect_catalog_year(pdf, pdf_path)
        pages_text = extract_pages_text(pdf)

    print(f"  Catalog year: {catalog_year}")
    print(f"  Pages: {len(pages_text)}")

    raw_programs = find_programs(pages_text)
    print(f"  Found {len(raw_programs)} raw program sections")

    programs = []
    for prog in raw_programs:
        prog_json = build_program_json(prog, catalog_year)
        programs.append(prog_json)

    programs = deduplicate_programs(programs)
    print(f"  After dedup: {len(programs)} programs")

    return programs


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tools/extract_programs.py <catalog_pdf> [<catalog_pdf> ...]")
        print()
        print("Options:")
        print("  --dry-run      Print summary without writing files")
        print("  --stdout       Print JSON to stdout instead of writing files")
        print("  --overwrite    Overwrite existing files (default: skip)")
        sys.exit(1)

    dry_run = '--dry-run' in sys.argv
    to_stdout = '--stdout' in sys.argv
    overwrite = '--overwrite' in sys.argv
    pdf_paths = [a for a in sys.argv[1:] if not a.startswith('--')]

    for pdf_path in pdf_paths:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            print(f"File not found: {pdf_path}")
            continue

        print(f"\nParsing {pdf_path.name}...")
        programs = parse_catalog(str(pdf_path))

        if not programs:
            print("  No programs found!")
            continue

        catalog_year = programs[0].get('catalog_year', 'unknown')
        out_dir = REPO / 'data' / 'programs' / catalog_year

        review_count = 0
        for prog in programs:
            prog_clean = strip_review_flags(prog)
            needs_review = prog.get('_needs_review', False)
            if needs_review:
                review_count += 1

            filename = make_filename(prog['id'], catalog_year)
            n_sections = len(prog.get('sections', []))
            flag = ' [REVIEW]' if needs_review else ''

            if to_stdout:
                print(json.dumps(prog_clean, indent=2))
                print()
            elif dry_run:
                print(f"  {filename}: {prog['name']} ({prog['program_type']}) "
                      f"- {n_sections} sections{flag}")
            else:
                out_dir.mkdir(parents=True, exist_ok=True)
                out_file = out_dir / filename
                if out_file.exists() and not overwrite:
                    print(f"  -- {out_file.relative_to(REPO)}: exists, skipping "
                          f"(use --overwrite)")
                    continue
                with open(out_file, 'w') as f:
                    json.dump(prog_clean, f, indent=2)
                    f.write('\n')
                print(f"  -> {out_file.relative_to(REPO)}: {n_sections} sections{flag}")

        total = len(programs)
        print(f"\n  Summary: {total} programs extracted"
              f" ({review_count} need review)")
        if not dry_run and not to_stdout:
            print(f"  Output: {out_dir.relative_to(REPO)}/")


if __name__ == '__main__':
    main()
