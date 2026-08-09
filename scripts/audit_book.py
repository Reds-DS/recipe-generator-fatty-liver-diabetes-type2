#!/usr/bin/env python3
"""PUBLICATION GATE — audit a generated book for anything that must not go to print.

The nutrient envelope is enforced *softly* during generation, on purpose: nutrition is
computed after drafting, so blocking there would discard finished work over food-database
noise. This script is the other half of that bargain — the hard look, before print.

It separates two very different things:

  * **BLOCKERS** — a reader would be misled, misinformed, or unable to cook the recipe.
    A fabricated preheat duration, a title promising a time the recipe does not meet, an
    undeclared 2-hour chill, a banned health claim, a missing panel or photo. These are
    not opinions; each one is a factual defect on a printed page.
  * **ADVISORIES** — the recipe misses a per-serving target. These are editorial calls.
    A main at 545 kcal against a 540 band is not a defect, it is a judgement.

Usage:
    uv run python scripts/audit_book.py [book]        # default: cookbook-recipes
    uv run python scripts/audit_book.py [book] --verbose
Exit 0 = no blockers, 1 = blockers found.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from src.config import GENERATED_DIR
from src.constants import RECIPE_CHAPTER_NUTRIENT_TIER
from src.diet_rules import spec

# --- blocker patterns -------------------------------------------------------
# A minute count in the title or intro. The cover already guarantees under 30
# minutes for every recipe, so a per-recipe claim is redundant AND becomes a lie
# the moment the timing shifts. ("30-Minute" in a chapter title is not a recipe.)
# Numbers appear SPELLED OUT as often as in digits ("ready in under ten minutes"),
# and a digits-only pattern walked straight past exactly that line on the first run.
_NUM_WORD = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|twenty|twenty-five|thirty|forty|forty-five|fifty|sixty)"
)
_TIME_CLAIM = re.compile(rf"\b(?:\d+|{_NUM_WORD})[- ]?(?:minute|min)\b", re.I)
# "Preheat ... for N minutes" — factually false: a real oven needs 10-15 min.
_PREHEAT_DURATION = re.compile(r"preheat[^.]{0,80}?\bfor\s+\d+\s*(?:to\s*\d+\s*)?minute", re.I)
# Claims the dossier (section 8) forbids outright.
_BANNED_CLAIMS = (
    "detox", "detoxif", "cleanse", "flush the liver", "flush out",
    "reverses fatty liver", "reverse fatty liver", "cures", "cure your",
    "fat-burning", "fat burning", "melts fat", "torch", "boosts metabolism",
    "boost your metabolism", "supercharge", "milk thistle", "apple cider vinegar cure",
    "superfood", "miracle",
)
# Ingredients that should never appear — the hard blocks, re-checked on the
# FINISHED recipe in case a block was added after some recipes were generated.
_BANNED_INGREDIENTS = (
    "white wine", "red wine", "cooking wine", "beer", "sherry", "mirin", "sake",
    "brandy", "rum", "bourbon", "vodka", "liqueur",
    "high-fructose corn syrup", "corn syrup", "agave",
    "coconut oil", "palm oil", "coconut cream",
)
_BANNED_INGREDIENT_GUARDS = (
    "wine vinegar", "sherry vinegar", "cider vinegar", "champagne vinegar",
    "coconut water", "coconut aminos", "coconut flour", "coconut extract",
    "shredded coconut", "hearts of palm", "non-alcoholic", "vanilla extract",
)
# An intro implying a WAIT, with no passive_time declared.
#
# This must require an actual make-ahead ACTION, not merely the word "chilled".
# A first version matched bare `chill(ed)` and flagged "...complements CHILLED
# nonfat Greek yogurt..." — an adjective describing an ingredient straight from
# the fridge, not a step the reader has to wait through.
_MAKE_AHEAD_HINT = re.compile(
    r"\bmake[- ]ahead\b"
    r"|\bovernight\b"
    r"|\bchill(?:s|ing)?\s+(?:it\s+|them\s+)?(?:for\s+|at least\s+)*\d"
    r"|\brefrigerate[sd]?\s+(?:for\s+|at least\s+)*\d"
    r"|\bfreeze[sd]?\s+(?:for\s+|at least\s+)*\d"
    r"|\bset(?:s)?\s+in the (?:fridge|refrigerator)\b",
    re.I,
)
MAX_TOTAL_MIN = 30


def _norm(s: str | None) -> str:
    return (s or "").lower()


def audit(book: str, verbose: bool = False) -> int:
    root = GENERATED_DIR / book
    if not root.is_dir():
        print(f"No such book: {root}")
        return 2

    s = spec.load_spec()
    blockers: dict[str, list[str]] = defaultdict(list)
    advisories: dict[str, list[str]] = defaultdict(list)
    kinds: Counter[str] = Counter()
    titles: Counter[str] = Counter()
    n = 0

    for p in sorted(root.rglob("JSON/*.json")):
        if p.name.endswith(".log.json"):
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        n += 1
        title = r.get("title", p.stem)
        titles[title.lower()] += 1
        intro = _norm(r.get("intro"))
        steps = " ".join(r.get("instructions") or [])
        ing_text = " ".join(
            f"{i.get('name', '')} {i.get('canonical_name', '')}" for i in (r.get("ingredients") or [])
        ).lower()

        def blk(kind: str, msg: str) -> None:
            blockers[title].append(msg)
            kinds[kind] += 1

        # 1. completeness
        for field, label in (("nutrition_per_serving", "nutrition panel"),
                             ("image_path", "image"), ("instructions", "instructions")):
            if not r.get(field):
                blk("missing", f"missing {label}")
        if r.get("image_path") and not Path(r["image_path"]).is_file():
            blk("missing", f"image file not on disk: {r['image_path']}")

        # 2. time claims in title / intro / filename
        if _TIME_CLAIM.search(title):
            blk("time-claim", f'time claim in TITLE: "{title}"')
        if _TIME_CLAIM.search(intro):
            m = _TIME_CLAIM.search(intro)
            blk("time-claim", f'time claim in INTRO: "...{intro[max(0, m.start() - 40):m.end() + 20]}..."')
        if _TIME_CLAIM.search(p.stem):
            blk("time-claim", f"time claim in FILENAME: {p.stem}")

        # 3. fabricated preheat duration
        for m in _PREHEAT_DURATION.finditer(steps):
            blk("preheat", f'fabricated preheat duration: "{m.group(0).strip()}"')

        # 4. the 30-minute cover promise
        total = (r.get("prep_time_min") or 0) + (r.get("cook_time_max_min") or r.get("cook_time_min") or 0)
        if total > MAX_TOTAL_MIN:
            blk("over-30-min", f"declared total time {total} min > the {MAX_TOTAL_MIN} min cover promise")

        # 5. undeclared passive time
        if _MAKE_AHEAD_HINT.search(intro) and not (r.get("passive_time") or "").strip():
            blk("undeclared-wait", "intro implies a wait (chill/make-ahead) but passive_time is empty")

        # 6. banned health claims
        for phrase in _BANNED_CLAIMS:
            for field, txt in (("intro", intro), ("title", _norm(title)), ("steps", _norm(steps))):
                if phrase in txt:
                    blk("banned-claim", f'banned claim "{phrase}" in {field}')

        # 7. banned ingredients (hard blocks re-checked on the finished recipe).
        # WORD-BOUNDARY matching, exactly as `_kw_pattern` does in
        # src/diet_rules/rules.py. A plain substring test flagged "rum" inside
        # "Crumbled feta cheese" on the first run of this script — the same class of
        # bug the rules module documents ("egg" must not match "eggplant").
        for phrase in _BANNED_INGREDIENTS:
            if not re.search(rf"\b{re.escape(phrase)}", ing_text):
                continue
            if any(g in ing_text for g in _BANNED_INGREDIENT_GUARDS):
                continue
            blk("banned-ingredient", f'banned ingredient matched: "{phrase}"')

        # --- advisories: the per-serving envelope ---------------------------
        env = s.envelope_for_chapter(r.get("chapter", ""))
        tier = RECIPE_CHAPTER_NUTRIENT_TIER.get(r.get("chapter", ""), "main")
        nut = r.get("nutrition_per_serving") or {}

        def g(k: str) -> float | None:
            v = nut.get(k)
            return float(v) if isinstance(v, (int, float)) else None

        for label, val, bound, over in (
            ("protein below floor", g("protein_g"), env.protein_g_floor, False),
            ("fiber below floor", g("fiber_g"), env.fiber_g_floor, False),
            ("carbohydrate below floor", g("carbs_g"), env.total_carbs_g_floor, False),
            ("carbohydrate over ceiling", g("carbs_g"), env.total_carbs_g_max, True),
            ("added sugar over ceiling", g("added_sugar_g"), env.added_sugar_g_max, True),
            ("saturated fat over ceiling", g("saturated_fat_g"), env.saturated_fat_g_max, True),
            ("sodium over ceiling", g("sodium_mg"), env.sodium_mg_max, True),
            ("energy over band", g("calories_kcal"), env.energy_kcal_max, True),
            ("energy under band", g("calories_kcal"), env.energy_kcal_min, False),
        ):
            if val is None or bound is None:
                continue
            if (val > bound) if over else (val < bound):
                advisories[title].append(f"{label} ({val:g} vs {bound:g}, tier {tier})")

    dupes = [t for t, c in titles.items() if c > 1]

    # --- report ---------------------------------------------------------
    print(f"PUBLICATION AUDIT — book '{book}', {n} recipes\n")
    print(f"BLOCKERS: {len(blockers)} recipe(s) affected, {sum(kinds.values())} issue(s)")
    for kind, c in kinds.most_common():
        print(f"  {kind:20s} {c}")
    if dupes:
        print(f"  {'duplicate-title':20s} {len(dupes)}")
    print()
    for title, msgs in blockers.items():
        print(f"  [BLOCK] {title}")
        for m in msgs:
            print(f"          - {m}")
    if not blockers:
        print("  none — nothing in this book misleads or misinforms the reader.\n")

    adv_count = sum(len(v) for v in advisories.values())
    print(f"\nADVISORIES (envelope misses — editorial calls, not defects): "
          f"{len(advisories)} recipe(s), {adv_count} miss(es)")
    if verbose:
        for title, msgs in advisories.items():
            print(f"  [adv] {title}")
            for m in msgs:
                print(f"        - {m}")
    else:
        print("  (re-run with --verbose to list them)")

    clean = n - len(blockers)
    print(f"\nPUBLISHABLE AS-IS: {clean}/{n}    NEED WORK: {len(blockers)}/{n}")
    return 1 if blockers else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(audit(args[0] if args else "cookbook-recipes", "--verbose" in sys.argv))
