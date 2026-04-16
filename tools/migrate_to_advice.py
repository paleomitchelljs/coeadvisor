#!/usr/bin/env python3
"""
Migrate first_two_years.json and intake files into the new data/advice/ structure.

Creates:
  data/advice/<program>/_advice.json   (master file)
  data/advice/<program>/plan_*.json    (plan files)
  data/advice/<program>/intake.json    (intake, if exists)
  data/advice/<program>/notes.json     (notes, extracted from F2Y)
"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
ADVICE_DIR = DATA / "advice"
F2Y_PATH = DATA / "first_two_years.json"
INTAKE_DIR = DATA / "intake"

SEM_MAP = {"y1_fall": 1, "y1_spring": 2, "y2_fall": 3, "y2_spring": 4}

# Explicit mapping: F2Y entry ID -> (dir_name, variant_name)
ENTRY_MAP = {
    "biology_standard":           ("biology",           "standard"),
    "biology_advanced":           ("biology",           "advanced"),
    "biology_typical":            ("biology",           "typical"),
    "business_admin":             ("business_admin",    "standard"),
    "chemistry":                  ("chemistry",         "standard"),
    "communication_studies":      ("communication_studies", "standard"),
    "computer_science":           ("computer_science",  "standard"),
    "creative_writing":           ("creative_writing",  "standard"),
    "economics":                  ("economics",         "standard"),
    "elementary_education":       ("elementary_education", "standard"),
    "english":                    ("english",           "standard"),
    "environmental_studies":      ("environmental_studies", "standard"),
    "french_francophone":         ("french_francophone", "standard"),
    "health_society_studies":     ("health_society_studies", "standard"),
    "history":                    ("history",           "standard"),
    "international_studies":      ("international_studies", "standard"),
    "kinesiology_fitness":        ("kinesiology_fitness", "standard"),
    "kinesiology_athletic_training": ("kinesiology_athletic_training", "standard"),
    "mathematics":                ("mathematics",       "standard"),
    "museum_studies":             ("museum_studies",    "standard"),
    "music":                      ("music",             "standard"),
    "nursing":                    ("nursing",           "standard"),
    "organizational_science":     ("organizational_science", "standard"),
    "philosophy":                 ("philosophy",        "standard"),
    "physics":                    ("physics",           "standard"),
    "political_science":          ("political_science", "standard"),
    "psychology":                 ("psychology",        "standard"),
    "social_criminal_justice":    ("social_criminal_justice", "standard"),
    "sociology":                  ("sociology",         "standard"),
    "studio_art":                 ("studio_art",        "standard"),
    "art_history_minor":          ("art_history",       "standard"),
}

# Explicit match_programs: dir_name -> list of program IDs
# Only includes the specific programs this advice applies to
MATCH_PROGRAMS = {
    "biology":               ["biology_major_2025", "biology_major_2025-26"],
    "business_admin":        ["business_admin_major_2018", "business_admin_major_2025-26"],
    "chemistry":             ["chemistry_major_2026", "chemistry_major_2025-26", "chemistry_acs_major_2025-26"],
    "communication_studies": ["communication_studies_major_2024", "communication_studies_major_2025-26"],
    "computer_science":      ["computer_science_major_2021", "computer_science_major_2025-26"],
    "creative_writing":      ["creative_writing_major_2022", "creative_writing_major_2025-26"],
    "economics":             ["economics_major_2022", "economics_major_2025-26",
                              "international_economics_major_2018", "international_economics_major_2025-26"],
    "elementary_education":  ["elementary_education_major_2025", "elementary_education_major_2025-26"],
    "english":               ["english_major_2022", "english_major_2025-26"],
    "environmental_studies": ["environmental_studies_collateral_2025",
                              "environmental_studies_collateral_major_2025-26"],
    "french_francophone":    ["french_francophone_major_2019"],
    "health_society_studies": ["health_society_studies_minor_2020",
                               "health_society_studies_minor_2025-26"],
    "history":               ["history_major_2021", "history_major_2025-26"],
    "international_studies": ["international_studies_major_2021",
                              "international_studies_global_south_major_2025-26",
                              "international_studies_intl_relations_major_2025-26",
                              "international_studies_european_major_2025-26"],
    "kinesiology_fitness":   ["kinesiology_fitness_major_2024",
                              "kinesiology_fitness_major_2025-26"],
    "kinesiology_athletic_training": ["kinesiology_athletic_training_major_2021",
                                      "kinesiology_pre_athletic_training_major_2025-26"],
    "mathematics":           ["mathematics_major_2018", "mathematics_major_2025-26"],
    "museum_studies":        ["museum_studies_minor_2026", "museum_studies_minor_2025-26"],
    "music":                 ["music_ba_major_2019", "music_major_2025-26"],
    "nursing":               ["nursing_bsn_2025", "nursing_bsn_major_2025-26"],
    "organizational_science": ["organizational_science_collateral_2023",
                                "psychology_major_2025-26"],  # embedded as concentration
    "philosophy":            ["philosophy_major_2025", "philosophy_major_2025-26"],
    "physics":               ["physics_major_2019", "physics_major_2025-26"],
    "political_science":     ["political_science_major_2025", "political_science_major_2025-26"],
    "psychology":            ["psychology_major_2025", "psychology_major_2025-26"],
    "social_criminal_justice": ["social_criminal_justice_major_2025",
                                 "social_criminal_justice_major_2025-26"],
    "sociology":             ["sociology_major_2025", "sociology_major_2025-26"],
    "studio_art":            ["studio_art_major_2026", "art_major_2025-26"],
    "art_history":           ["art_history_minor_2026", "art_minor_2025-26"],
}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    f2y_data = load_json(F2Y_PATH)
    entries = f2y_data.get("entries", f2y_data)
    if not isinstance(entries, list):
        print("No entries found"); return

    # Load intake files
    intakes = {}
    if INTAKE_DIR.is_dir():
        for fp in INTAKE_DIR.glob("*.json"):
            data = load_json(fp)
            pid = data.get("program_id", "")
            if pid and pid != "_default":
                intakes[pid] = data

    # Group entries by dir_name
    groups = {}
    for entry in entries:
        eid = entry.get("id", "")
        if eid not in ENTRY_MAP:
            print(f"  WARN: unmapped entry '{eid}', skipping")
            continue
        dir_name, variant = ENTRY_MAP[eid]
        groups.setdefault(dir_name, []).append((variant, entry))

    total_plans = 0
    for dir_name, variant_entries in sorted(groups.items()):
        out_dir = ADVICE_DIR / dir_name
        print(f"\n{dir_name}/")

        # Determine major_code from first entry
        first_entry = variant_entries[0][1]
        match_codes = first_entry.get("match_major_codes", [])
        major_code = match_codes[0] if match_codes else ""

        # Check for intake data
        intake_data = None
        for _, entry in variant_entries:
            for pid in entry.get("match_program_ids", []):
                if pid in intakes:
                    intake_data = intakes[pid]
                    break
            if intake_data: break

        # Build plans
        plans_meta = []
        for variant, entry in variant_entries:
            # Plan file
            semesters = {}
            for sem_key, sem_num in SEM_MAP.items():
                sem_data = (entry.get("semesters") or {}).get(sem_key, {})
                semesters[str(sem_num)] = {
                    "essential": sem_data.get("essential", []),
                    "suggested": sem_data.get("suggested", []),
                }
            for i in range(5, 9):
                semesters[str(i)] = {"essential": [], "suggested": []}

            plan = {
                "id": f"{dir_name}_{variant}",
                "label": entry.get("label", ""),
                "semesters": semesters,
                "general_notes": entry.get("notes", ""),
            }
            save_json(out_dir / f"plan_{variant}.json", plan)
            total_plans += 1
            print(f"  plan_{variant}.json")

            # Plan metadata for master
            pm = {
                "id": variant,
                "file": f"plan_{variant}.json",
                "label": entry.get("label", ""),
            }
            if entry.get("default", False) or len(variant_entries) == 1:
                pm["default"] = True
            conds = entry.get("conditions", {})
            if conds:
                pm["conditions"] = conds
            plans_meta.append(pm)

        # Ensure exactly one default
        if not any(p.get("default") for p in plans_meta):
            plans_meta[0]["default"] = True

        # Display name from first entry's label
        raw_label = first_entry.get("label", "")
        display_name = raw_label.split(" — ")[0].split(" (")[0].strip()

        # Master file
        master = {
            "id": dir_name,
            "major_code": major_code,
            "display_name": display_name,
        }
        if dir_name in MATCH_PROGRAMS:
            master["match_programs"] = MATCH_PROGRAMS[dir_name]

        default_plan = next((p["id"] for p in plans_meta if p.get("default")), "standard")
        master["default_plan"] = default_plan
        master["plans"] = plans_meta

        if intake_data:
            master["intake"] = "intake.json"
        has_notes = any(e.get("notes", "").strip() for _, e in variant_entries)
        if has_notes:
            master["notes"] = "notes.json"

        save_json(out_dir / "_advice.json", master)
        print(f"  _advice.json")

        # Notes file
        if has_notes:
            notes_entries = [(v, e) for v, e in variant_entries]
            general = notes_entries[0][1].get("notes", "")
            notes_data = {"general": general}
            if len(notes_entries) > 1:
                vnotes = {}
                for v, e in notes_entries:
                    vn = e.get("variant_note", "").strip()
                    if vn:
                        vnotes[v] = vn
                if vnotes:
                    notes_data["variant_notes"] = vnotes
            save_json(out_dir / "notes.json", notes_data)
            print(f"  notes.json")

        # Intake file
        if intake_data:
            # Remap route plan references to match our variant IDs
            new_routes = []
            for route in intake_data.get("routes", []):
                new_route = {"when": route.get("when", {})}
                # Determine plan from route characteristics
                if route.get("pathway") == "premed":
                    # Premed route -> the "advanced" plan
                    has_bio_chem = route.get("when", {}).get("hs_bio_chem")
                    new_route["plan"] = "advanced"
                elif route.get("when", {}).get("hs_bio_chem") is False:
                    new_route["plan"] = "typical"
                else:
                    new_route["plan"] = "standard"
                if route.get("pathway"):
                    new_route["pathway"] = route["pathway"]
                if route.get("note"):
                    new_route["note"] = route["note"]
                if route.get("semester_1"):
                    new_route["semester_1"] = route["semester_1"]
                new_routes.append(new_route)

            intake_out = {
                "intro": intake_data.get("intro", ""),
                "questions": intake_data.get("questions", []),
                "routes": new_routes,
            }
            save_json(out_dir / "intake.json", intake_out)
            print(f"  intake.json")

    print(f"\n=== Created {len(groups)} advice directories, {total_plans} plan files ===")


if __name__ == "__main__":
    main()
