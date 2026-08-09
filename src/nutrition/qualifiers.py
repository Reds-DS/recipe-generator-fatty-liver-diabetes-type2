"""Ingredient qualifiers that change the per-100 g basis of a USDA match.

A recipe's ingredient text carries qualifiers the nutrition arithmetic must respect.
"No-salt-added" canned beans are a different USDA food from regular canned beans
(≈5 mg vs ≈340 mg sodium per 100 g), and 340 g of *raw* ground turkey is not 340 g of
pan-broiled crumbles (158 vs 220 kcal per 100 g). FoodData Central carries a separate
record for each; picking the wrong one silently shifts the whole panel — and the number
still looks authoritative, which is what makes it dangerous.

Two dimensions are modelled, both as a polarity that is either present or unknown:

  * **salt**  — ``unsalted`` / ``salted`` / ``None``
  * **state** — ``raw`` / ``cooked`` / ``None``

Matching is word-boundary based, and the "unsalted" phrases are always tested first:
"no sodium added" contains "sodium added", and "unsalted" contains "salted", so a naive
substring test flips the answer.

This module deliberately imports nothing from the project — Stage 4 and the candidate
matcher both call in, and it stays unit-testable with no database or network.
"""
import re

# ── salt ───────────────────────────────────────────────────────
# Checked in this order; the first hit wins.
_UNSALTED_RE = re.compile(
    r"\b(?:no salt added|without salt|no added salt|salt free|unsalted"
    r"|no sodium added|low sodium|lower sodium|reduced sodium|sodium free)\b"
)
# "salt added" / "with salt" are only reached when no unsalted phrase matched above, so
# "no salt added" and "without salt" cannot fall through to here.
_SALTED_RE = re.compile(
    r"\b(?:salted|sodium added|salt added|with salt|in brine|brined|packed in brine)\b"
)

# SQL ``LIKE`` fragments for the candidate matcher — matched against ``description_norm``,
# which is the lowercased description with punctuation intact.
UNSALTED_LIKE: tuple[str, ...] = (
    "no salt added", "without salt", "unsalted", "no sodium added",
    "low sodium", "reduced sodium",
)

# A product sold as "no-salt-added" sits far below this: canned legumes and vegetables run
# from single digits to ~30 mg/100 g, canned fish without salt ~75 mg/100 g. Their regular
# counterparts run 200-400+. The gap is wide, so the threshold only fires on a clear miss.
SODIUM_MAX_UNSALTED_PER_100G = 140.0

# ── preservation ───────────────────────────────────────────────
# Canned legumes carry more water than the same legume boiled from dry (≈114 vs ≈139
# kcal/100 g), so the two are not interchangeable at a fixed gram weight.
_CANNED_RE = re.compile(r"\bcanned\b")

# ── cooking state ──────────────────────────────────────────────
# "raw" needs a word boundary — "strawberries" contains "raw".
_RAW_RE = re.compile(r"\b(?:raw|uncooked)\b")
_COOKED_RE = re.compile(
    r"\b(?:cooked|boiled|broiled|pan-broiled|roasted|baked|grilled|fried|pan-fried"
    r"|steamed|stewed|braised|poached|simmered|crumbles|patties)\b"
)


def _flatten(text: str | None) -> str:
    """Lowercase and turn hyphens/underscores into spaces so "no-salt-added" and
    "no salt added" are the same string to the matchers."""
    if not text:
        return ""
    return re.sub(r"[-_/]+", " ", text.lower())


def salt_polarity(text: str | None) -> str | None:
    """``"unsalted"``, ``"salted"``, or ``None`` when the text says nothing about salt.

    ``None`` is genuinely unknown, not "regular": many USDA records for salted products
    ("Fish, salmon, pink, canned, drained solids") carry no salt word at all.
    """
    flat = _flatten(text)
    if _UNSALTED_RE.search(flat):
        return "unsalted"
    if _SALTED_RE.search(flat):
        return "salted"
    return None


def state_polarity(text: str | None) -> str | None:
    """``"raw"``, ``"cooked"``, or ``None`` when the text does not say."""
    flat = _flatten(text)
    if _RAW_RE.search(flat):
        return "raw"
    if _COOKED_RE.search(flat):
        return "cooked"
    return None


def mismatch_reason(
    *,
    request_name: str,
    request_preparation: str | None,
    candidate_description: str,
    candidate_sodium_mg: float | None,
    unsalted_alternative_exists: bool,
) -> str | None:
    """Why ``candidate_description`` must not be used for this ingredient, else ``None``.

    ``request_name`` should be the ingredient's name and canonical name joined; salt is
    also read from ``request_preparation`` ("rinsed and drained"), but cooking state is
    NOT — preparation describes what the cook does to the ingredient, while the stated
    gram weight is what was bought. "Sliced almonds, toasted" is bought raw.
    """
    # ── salt ──
    if salt_polarity(f"{request_name} {request_preparation or ''}") == "unsalted":
        got = salt_polarity(candidate_description)
        if got == "salted":
            return (
                "recipe asks for a no-salt-added/low-sodium product "
                "but the match is a salted one"
            )
        if got != "unsalted":
            if unsalted_alternative_exists:
                return (
                    "recipe asks for a no-salt-added/low-sodium product and the match does "
                    "not say so, while an explicitly unsalted candidate is available"
                )
            if (candidate_sodium_mg or 0.0) > SODIUM_MAX_UNSALTED_PER_100G:
                return (
                    f"recipe asks for a no-salt-added/low-sodium product but the match carries "
                    f"{candidate_sodium_mg:.0f} mg sodium/100 g"
                )

    # ── preservation ──
    if _CANNED_RE.search(_flatten(request_name)):
        cand = _flatten(candidate_description)
        if not _CANNED_RE.search(cand) and _COOKED_RE.search(cand):
            return (
                "the recipe uses a canned product but the match is cooked from dry "
                "(different water content, so a different weight basis)"
            )

    # ── cooking state ──
    want_state = state_polarity(request_name)
    if want_state is not None:
        got_state = state_polarity(candidate_description)
        if got_state is not None and got_state != want_state:
            return (
                f"the ingredient is measured {want_state} but the match is a "
                f"{got_state} form (different weight basis)"
            )

    return None
