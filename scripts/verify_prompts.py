#!/usr/bin/env python3
"""Render the real prompts and assert they carry this book's identity — and none of
the corruption signatures a previous engine in this lineage acquired.

Why this exists. The prompts are the only place the cookbook's *voice and rules*
reach the model, and two classes of damage there are invisible to the test suite:

  1. **Stale identity.** A prompt still naming the parent cookbook parses fine, passes
     every test, and quietly generates recipes for the wrong book.
  2. **Silent literal corruption.** An automated line-re-wrapping script once ran over
     four prompt files in this lineage to clear a handful of E501s. It split f-strings
     and string literals mid-token, breaking two files outright and silently corrupting
     two more that still parsed. The nastiest: ``SYSTEM_STATIC = \"\"\"\\`` (a line
     continuation) became a literal backslash-n escape, putting a blank first line into
     the ideation prompt — legal Python, no test failure, and invisible unless you print
     ``repr()`` of the rendered string. **Do not run automated re-wrapping over
     src/llm/prompts/.** Run this after touching any prompt.

Usage:  uv run python scripts/verify_prompts.py
Exit 0 = clean, 1 = problems found.
"""
from __future__ import annotations

import sys

from src.diet_rules import spec
from src.diet_rules.engine import DietRuleEngine
from src.llm.prompts import critic as critic_prompts
from src.llm.prompts import draft as draft_prompts
from src.llm.prompts import format as format_prompts
from src.llm.prompts import ideation as ideation_prompts

BOOK = "The Fatty Liver Diet Cookbook for Type 2 Diabetes"

# Phrases that MUST appear somewhere in the rendered prompt set.
#
# NOTE the banned-claim vocabulary ("detox", "fat-burning", …) is REQUIRED here, not
# forbidden: the model can only avoid a phrase it has been shown. A prompt that never
# mentions "detox" is a prompt that will happily write it.
REQUIRED: dict[str, list[str]] = {
    "ideation": [
        BOOK, "fatty liver", "type 2 diabetes", "ONE WAY OF EATING",
        "MEDITERRANEAN", "ADDED SUGAR", "ALCOHOL-FREE", "DEFECT",
        "30 MINUTES", "extra-virgin olive oil",
        # the banned-claims vocabulary
        "detox", "cleanse", "fat-burning", "boosts metabolism", "milk thistle",
    ],
    "draft": [
        BOOK, "NO ALCOHOL", "NO FRUCTOSE SYRUPS", "NO COCONUT OIL",
        "WINDOW", "30 MINUTES TOTAL", "EXACTLY 2 people",
        '"net carbs"',  # present only as a ban — see ONLY_IF_NEGATED below
        "detox", "reverses fatty liver", "low-carb or keto",
    ],
    "critic": [
        BOOK, "12", "one_plan_both_conditions", "added_sugar_and_carb_balance",
        "thirty_minute_practicality", "NEVER PRAISE A RECIPE FOR BEING LOW IN CARBOHYDRATE",
        "detox", "reverses fatty liver", "milk thistle",
    ],
    "format": [BOOK, "detox", "low-carb"],
}

# Strings that must NOT appear anywhere: the PARENT cookbook's identity. This is the
# check that catches "the migration looked done but a prompt still names the old book".
FORBIDDEN: list[str] = [
    "High-Protein High-Fiber", "high-protein high-fiber",
    "Super Easy & Complete", "Cookbook for Weight Loss",
    "preserve or build muscle",
]

# Phrases that may only appear in a NEGATED context. Each is (phrase, negation cues):
# the phrase is allowed, but only within ~140 characters of one of its cues.
# Cue matching is case-insensitive and newline-insensitive (the prompt files wrap).
ONLY_IF_NEGATED: list[tuple[str, tuple[str, ...]]] = [
    ("net carbs", ("do not", "never", "not an fda", "deliberately not")),
    ("air fryer", ("no air fryer", "does not allow", "flag any", "book does not")),
]


def _render() -> dict[str, str]:
    engine = DietRuleEngine(chapter="poultry_meat_dinners")
    return {
        "ideation": ideation_prompts.build_system(engine.constraint_text("ideation")),
        "draft": draft_prompts.build_system(engine.constraint_text("drafting")),
        "critic": critic_prompts.build_system(spec.load_spec().prompt_snippets["critic"]),
        "format": format_prompts.SYSTEM,
    }


def main() -> int:
    problems: list[str] = []
    rendered = _render()

    for name, text in rendered.items():
        # --- corruption signatures -------------------------------------------
        if text.startswith("\n") or text.startswith(" "):
            problems.append(f"{name}: prompt starts with whitespace/newline — "
                            f"a backslash line-continuation was probably mangled. "
                            f"repr(head)={text[:40]!r}")
        if "\\n" in text:
            problems.append(f"{name}: contains a LITERAL backslash-n — a string literal "
                            f"was split by an automated re-wrap.")
        if "{" in text or "}" in text:
            # build_system uses concatenation, never str.format — a stray brace means
            # an unfilled placeholder leaked in.
            problems.append(f"{name}: contains a brace — check for an unfilled template "
                            f"placeholder (these builders never use str.format).")
        if len(text) < 400:
            problems.append(f"{name}: suspiciously short ({len(text)} chars) — truncated?")

        # --- required identity + rules ---------------------------------------
        for phrase in REQUIRED[name]:
            if phrase not in text:
                problems.append(f"{name}: MISSING required phrase {phrase!r}")

        # --- forbidden leftovers (the parent cookbook's identity) -------------
        for phrase in FORBIDDEN:
            if phrase in text:
                problems.append(f"{name}: still names the PARENT cookbook — {phrase!r}")

        # --- phrases allowed only in a negated context ------------------------
        for phrase, cues in ONLY_IF_NEGATED:
            start = 0
            while (idx := text.find(phrase, start)) != -1:
                window = " ".join(text[max(0, idx - 140): idx + 140].split()).lower()
                if not any(cue in window for cue in cues):
                    problems.append(
                        f"{name}: {phrase!r} appears WITHOUT a negation cue nearby — "
                        f"context: ...{text[max(0, idx - 60): idx + 60]!r}..."
                    )
                start = idx + len(phrase)

    # --- the per-chapter brief the model also sees ---------------------------
    for slug in spec.load_spec().recipe_categories:
        brief = spec.chapter_brief(slug)
        if "TARGET CHAPTER" not in brief:
            problems.append(f"chapter_brief({slug}): missing the TARGET CHAPTER header")
        if "Per-serving targets" not in brief:
            problems.append(f"chapter_brief({slug}): no per-serving targets rendered — "
                            f"the chapter's nutrient tier probably doesn't resolve")
        if "A WINDOW" not in brief:
            problems.append(f"chapter_brief({slug}): carbohydrate is not rendered as a "
                            f"window — the floor is not reaching the model")

    print(f"Book: {BOOK}")
    for name, text in rendered.items():
        print(f"  {name:9s} {len(text):6,d} chars  head={text[:56]!r}")
    print()
    for slug, cat in spec.load_spec().recipe_categories.items():
        print(f"  chapter {slug:28s} tier={cat.nutrient_tier:11s} target={cat.target_count}")
    print()

    if problems:
        for p in problems:
            print(f"  PROBLEM  {p}")
        print(f"\nFAILED — {len(problems)} problem(s).")
        return 1
    print("OK — prompts carry the right book identity and show no corruption signatures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
