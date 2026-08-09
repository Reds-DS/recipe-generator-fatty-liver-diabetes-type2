#!/usr/bin/env python3
"""Pre-seed the USDA alias cache from ``data/usda_aliases.seed.yaml``.

Stage 4 caches the LLM's food pick per canonical ingredient name in
``data/usda_alias.db``, and ``register_alias()`` keeps the FIRST-stored ``fdc_id``
stable. Seeding before a generation run therefore pins the right record for the
ingredients the FTS shortlist gets wrong — for the whole book, not one recipe.

The pilot found two failure modes this fixes (both detailed in the seed file):
the model inventing USDA descriptions that do not exist, and the shortlist
missing a no-salt-added record that does. Both land on sodium, on a book whose
main-meal ceiling is 550 mg.

**Re-run this after every `build-nutrition-db`** — that command recreates the
alias DB from scratch.

Usage:
    uv run python scripts/seed_usda_aliases.py            # seed + verify
    uv run python scripts/seed_usda_aliases.py --dry-run  # verify only
"""
from __future__ import annotations

import sqlite3
import sys

import yaml

from src.config import DATA_DIR, USDA_DB
from src.nutrition.usda_loader import get_alias, register_alias

SEED_FILE = DATA_DIR / "usda_aliases.seed.yaml"


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    if not SEED_FILE.is_file():
        print(f"ERROR: no seed file at {SEED_FILE}")
        return 2
    if not USDA_DB.is_file():
        print(f"ERROR: no food DB at {USDA_DB} — run `cli.py build-nutrition-db` first.")
        return 2

    doc = yaml.safe_load(SEED_FILE.read_text(encoding="utf-8")) or {}
    entries = doc.get("aliases") or []
    if not entries:
        print("Nothing to seed.")
        return 0

    con = sqlite3.connect(USDA_DB)
    cur = con.cursor()

    seeded = skipped = bad = 0
    print(f"Seeding from {SEED_FILE.name} ({len(entries)} entries)\n")
    for e in entries:
        name, fdc_id = e.get("canonical_name"), e.get("fdc_id")
        if not name or not isinstance(fdc_id, int):
            print(f"  BAD    {e!r}")
            bad += 1
            continue

        # Every id must resolve in the BUILT database — a typo here would pin a
        # wrong food for the entire book, which is worse than no seed at all.
        row = cur.execute(
            "SELECT description, sodium_mg FROM food WHERE fdc_id = ?", (fdc_id,)
        ).fetchone()
        if row is None:
            print(f"  BAD    {fdc_id} not in the food DB — {name!r}")
            bad += 1
            continue
        desc, na = row
        na_s = "--" if na is None else f"{na:.0f}"

        existing = get_alias(name)
        if existing is not None and existing != fdc_id:
            print(f"  KEEP   {name[:52]:52s} already pinned to {existing} (not {fdc_id})")
            skipped += 1
            continue
        if existing == fdc_id:
            print(f"  OK     {name[:52]:52s} -> {fdc_id}  Na={na_s:>4s}")
            skipped += 1
            continue

        if not dry_run:
            register_alias(name, fdc_id)
        print(f"  {'WOULD' if dry_run else 'SEED '}  {name[:52]:52s} -> {fdc_id}  "
              f"Na={na_s:>4s}  {desc[:44]}")
        seeded += 1

    verb = "would seed" if dry_run else "seeded"
    print(f"\n{verb} {seeded}, unchanged {skipped}, invalid {bad}")
    if bad:
        print("FAILED — fix the invalid entries; a wrong id pins a wrong food for the whole book.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
