#!/usr/bin/env python3
"""
Clean up advice plan JSON files: extract course codes from mixed text entries,
split "X or Y" entries into separate codes, and remove purely descriptive text.

Usage:  python3 tools/clean_advice_plans.py [--dry-run]
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ADVICE_DIR = ROOT / "data" / "advice"

DRY_RUN = "--dry-run" in sys.argv

# Match PREFIX-NNN (optionally with slash-separated alternatives: MUA-100/101/104)
SLASH_RE = re.compile(r'([A-Z]{2,4})-(\d{3}(?:/\d{3})*[A-Z]?)')
CLEAN_RE = re.compile(r'^[A-Z]{2,4}-\d{3}[A-Z]?$')


def extract_codes(text):
    """Extract all valid course codes from a text string."""
    codes = []
    for m in SLASH_RE.finditer(text.upper()):
        prefix = m.group(1)
        nums_str = m.group(2)
        # Handle trailing letter (e.g. "L" in BIO-155L)
        trailing = ""
        if nums_str[-1].isalpha():
            trailing = nums_str[-1]
            nums_str = nums_str[:-1]
        for num in nums_str.split("/"):
            code = f"{prefix}-{num}{trailing}"
            if code not in codes:
                codes.append(code)
    return codes


def clean_plan(plan_data):
    """Clean a plan's semester entries. Returns (modified_data, changes_list)."""
    changes = []
    semesters = plan_data.get("semesters", {})

    for sem_key in sorted(semesters.keys(), key=lambda x: int(x) if x.isdigit() else x):
        sem_data = semesters[sem_key]
        for cat in ["essential", "suggested"]:
            items = sem_data.get(cat, [])
            new_items = []
            for item in items:
                if CLEAN_RE.match(item):
                    new_items.append(item)
                    continue

                codes = extract_codes(item)
                if codes:
                    for code in codes:
                        if code not in new_items:
                            new_items.append(code)
                    changes.append(f"  sem {sem_key} {cat}: {item!r} → {codes}")
                else:
                    changes.append(f"  sem {sem_key} {cat}: REMOVED {item!r}")

            sem_data[cat] = new_items

    return plan_data, changes


def main():
    total_changes = 0

    for plan_file in sorted(ADVICE_DIR.glob("*/plan_*.json")):
        with open(plan_file, encoding="utf-8") as f:
            data = json.load(f)

        cleaned, changes = clean_plan(data)

        if changes:
            label = f"{plan_file.parent.name}/{plan_file.name}"
            print(f"\n{label}:")
            for c in changes:
                print(c)
            total_changes += len(changes)

            if not DRY_RUN:
                with open(plan_file, "w", encoding="utf-8") as f:
                    json.dump(cleaned, f, indent=2, ensure_ascii=False)
                    f.write("\n")

    if total_changes == 0:
        print("No changes needed.")
    else:
        print(f"\n{'Would modify' if DRY_RUN else 'Modified'} {total_changes} entries.")


if __name__ == "__main__":
    main()
