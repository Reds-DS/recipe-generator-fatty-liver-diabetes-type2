#!/usr/bin/env python3
"""Summarise a generated book against this book's per-serving envelope.

Reads every recipe JSON under ``data/generated_recipes/<book>/`` and reports, per
recipe and in aggregate, how the computed panel sits against its chapter's tier —
so a pilot can be tuned from real numbers rather than from the impression the logs
leave.

It is deliberately opinionated about ONE thing: **under-carbohydrate is reported
separately and first.** In this book a recipe far below its carbohydrate floor is a
defect, not a success, and it is the failure mode most likely to appear at scale
(the model has years of "diabetes cookbook = low carb" prior working against the
floor). Every other axis is reported as a plain over/under count.

Usage:
    uv run python scripts/analyse_pilot.py [book]      # default: test-pilot
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from src.config import GENERATED_DIR
from src.constants import RECIPE_CHAPTER_NUTRIENT_TIER
from src.diet_rules import spec


def _load(book: str) -> list[tuple[Path, dict]]:
    root = GENERATED_DIR / book
    if not root.is_dir():
        print(f"No such book: {root}")
        return []
    out: list[tuple[Path, dict]] = []
    for p in sorted(root.rglob("JSON/*.json")):
        try:
            out.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError) as e:  # pragma: no cover - operator tool
            print(f"  ! unreadable: {p.name} ({e})")
    return out


def main() -> int:
    book = sys.argv[1] if len(sys.argv) > 1 else "test-pilot"
    recipes = _load(book)
    if not recipes:
        return 1

    s = spec.load_spec()
    under_carb: list[str] = []
    misses: Counter[str] = Counter()
    warn_kinds: Counter[str] = Counter()
    no_image = 0
    not_passed = 0

    print(f"Book: {book} — {len(recipes)} recipes\n")
    header = (f"{'recipe':46s} {'tier':11s} {'kcal':>5s} {'carb':>6s} {'fib':>5s} "
              f"{'sug':>5s} {'prot':>5s} {'sat':>5s} {'Na':>5s}")
    print(header)
    print("-" * len(header))

    for path, r in recipes:
        chapter = r.get("chapter", "?")
        tier = RECIPE_CHAPTER_NUTRIENT_TIER.get(chapter, "main")
        env = s.envelope_for_chapter(chapter)
        n = r.get("nutrition_per_serving") or {}

        def g(key: str) -> float | None:
            v = n.get(key)
            return float(v) if isinstance(v, (int, float)) else None

        kcal, carb = g("calories_kcal"), g("carbs_g")
        fib, sug = g("fiber_g"), g("added_sugar_g")
        prot, sat, na = g("protein_g"), g("saturated_fat_g"), g("sodium_mg")

        flag = ""
        if carb is not None and env.total_carbs_g_floor and carb < env.total_carbs_g_floor:
            flag = "  <-- UNDER-CARB"
            under_carb.append(f"{r.get('title', path.stem)} — {carb:.0f} g "
                              f"(floor {env.total_carbs_g_floor:g}, tier {tier})")
        for label, val, bound, over in (
            ("protein<floor", prot, env.protein_g_floor, False),
            ("fiber<floor", fib, env.fiber_g_floor, False),
            ("carb>ceiling", carb, env.total_carbs_g_max, True),
            ("addedsugar>max", sug, env.added_sugar_g_max, True),
            ("satfat>max", sat, env.saturated_fat_g_max, True),
            ("sodium>max", na, env.sodium_mg_max, True),
            ("kcal>max", kcal, env.energy_kcal_max, True),
            ("kcal<min", kcal, env.energy_kcal_min, False),
        ):
            if val is None or bound is None:
                continue
            if (val > bound) if over else (val < bound):
                misses[label] += 1

        def f(v: float | None, w: int = 5, d: int = 0) -> str:
            return f"{'--':>{w}s}" if v is None else f"{v:{w}.{d}f}"

        title = (r.get("title") or path.stem)[:45]
        print(f"{title:46s} {tier:11s} {f(kcal)} {f(carb, 6)} {f(fib)} "
              f"{f(sug)} {f(prot)} {f(sat)} {f(na)}{flag}")

        if not r.get("image_path"):
            no_image += 1
        if not r.get("validation_passed"):
            not_passed += 1
        for w in r.get("validation_warnings") or []:
            warn_kinds[w.split(":")[0].split("(")[0].strip()[:70]] += 1

    print()
    if under_carb:
        print(f"UNDER-CARBOHYDRATE — {len(under_carb)}/{len(recipes)} recipes. In this book that "
              f"is a DEFECT, not a success:")
        for line in under_carb:
            print(f"  - {line}")
        print("  Fix by strengthening the drafting snippet, NOT by lowering the floor.\n")
    else:
        print("UNDER-CARBOHYDRATE: none. The floor is holding.\n")

    print("Envelope misses (soft warnings — recipes are kept):")
    for label, count in misses.most_common():
        print(f"  {label:18s} {count}")
    if not misses:
        print("  none")

    print("\nMost common validation warnings:")
    for text, count in warn_kinds.most_common(12):
        print(f"  {count:3d}  {text}")
    if not warn_kinds:
        print("  none")

    print(f"\nvalidation_passed=False : {not_passed}/{len(recipes)}")
    print(f"missing image           : {no_image}/{len(recipes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
