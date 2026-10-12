#!/usr/bin/env python3
"""Validate data/careers.json against the real program set.

The career chain is hand-written, but everything it points at is generated data
that moves between catalog years. This checks the two ways it can rot: a `goto`
or `program_keys` entry that no longer names anything, and a branch that grew
past the five-step budget the wizard is built around.

    python3 tools/check_careers.py
"""
import collections
import glob
import json
import re
import sys

ROOT = __file__.rsplit("/tools/", 1)[0]
MAX_STEPS = 5          # questions + the major pick + preparedness


def load_programs():
    """Majors per catalog year, keyed the way careers.json refers to them."""
    by_year = collections.defaultdict(list)
    for path in glob.glob(f"{ROOT}/data/programs/*/*.json"):
        year = path.split("/")[-2]
        if year.startswith("_"):          # _drafts, _archive — not active data
            continue
        prog = json.load(open(path))
        if prog.get("program_type") != "major":
            continue
        by_year[year].append({
            "id": prog["id"],
            "code": prog.get("major_code") or "",
            "key": re.sub(r"_\d{4}(-\d{2})?$", "", prog["id"]),
            "name": prog.get("name") or prog["id"],
        })
    return by_year


def catalog_codes():
    """Every course code in the newest catalog year we have."""
    years = sorted(glob.glob(f"{ROOT}/data/catalog_years/*/courses.json"))
    if not years:
        return None                       # nothing to check against
    catalog = json.load(open(years[-1]))
    codes = set()
    for prefix in (catalog.get("prefixes") or {}).values():
        codes.update((prefix.get("courses") or {}).keys())
    return codes


def resolve(leaf, programs):
    """Programs a result node offers, best first.

    `program_keys` is the precise list and restricts the offer — a leaf for
    aspiring physicians should not surface Kinesiology - Physical Education
    just because it shares the KIN code. `major_codes` is the fallback for when
    a program was renamed between catalog years and no key matches.
    """
    keys = leaf.get("program_keys") or []
    rank = {k: i for i, k in enumerate(keys)}
    hits = [p for p in programs if p["key"] in rank]
    if hits:
        hits.sort(key=lambda p: rank[p["key"]])
        return hits
    codes = set(leaf.get("major_codes") or [])
    return sorted((p for p in programs if p["code"] in codes), key=lambda p: p["name"])


def main():
    tree = json.load(open(f"{ROOT}/data/careers.json"))
    nodes = tree["nodes"]
    by_year = load_programs()
    errors, seen, depths = [], set(), []

    def walk(nid, path, steps):
        if nid not in nodes:
            errors.append(f"goto -> no such node {nid!r} (via {path})")
            return
        seen.add(nid)
        node = nodes[nid]
        if node.get("result"):
            depths.append(steps)
            if not isinstance(node.get("major_codes"), list):
                errors.append(f"{nid}: result has no major_codes list")
            # +1 for the major pick, +1 for preparedness
            if steps + 2 > MAX_STEPS:
                errors.append(f"{nid}: {steps + 2} steps, over the {MAX_STEPS} budget ({path})")
            return
        if not node.get("options"):
            errors.append(f"{nid}: neither a result nor a question")
        for opt in node.get("options", []):
            if "goto" not in opt:
                errors.append(f"{nid}: option {opt.get('label')!r} has no goto")
            else:
                walk(opt["goto"], f"{path} > {opt['label']}", steps + 1)

    walk(tree["root"], tree["root"], 1)

    orphans = sorted(set(nodes) - seen)
    if orphans:
        errors.append(f"unreachable nodes: {', '.join(orphans)}")

    leaves = [(k, v) for k, v in nodes.items() if v.get("result")]
    known_keys = {p["key"] for ps in by_year.values() for p in ps}
    courses = catalog_codes()
    pathway_ids = {json.load(open(f))["id"]
                   for f in glob.glob(f"{ROOT}/data/pathways/*.json")}
    for nid, leaf in leaves:
        for key in leaf.get("program_keys") or []:
            if key not in known_keys:
                errors.append(f"{nid}: program_keys entry {key!r} matches no program in any year")
        for pw in leaf.get("pathways") or []:
            if pw not in pathway_ids:
                errors.append(f"{nid}: pathway {pw!r} has no file in data/pathways/")
        # A substitution that names a course the catalog dropped would silently
        # put a dead code into every plan built down this branch.
        if courses is not None:
            for old_code, new_code in (leaf.get("substitutions") or {}).items():
                for code in (old_code, new_code):
                    if code not in courses:
                        errors.append(f"{nid}: substitution names {code!r}, "
                                      f"not in the newest course catalog")
        if not leaf.get("major_codes"):
            continue                      # 'still exploring' is deliberately empty
        for year, programs in sorted(by_year.items()):
            if not resolve(leaf, programs):
                errors.append(f"{nid}: resolves to nothing in {year} "
                              f"(codes={leaf['major_codes']})")

    questions = len(nodes) - len(leaves)
    print(f"{len(nodes)} nodes: {questions} questions, {len(leaves)} results")
    print(f"questions to a result: {min(depths)}-{max(depths)} "
          f"(+1 major pick, +1 preparedness = {max(depths) + 2} steps worst case)")
    print(f"catalog years checked: {', '.join(sorted(by_year))}")

    if errors:
        print(f"\n{len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
