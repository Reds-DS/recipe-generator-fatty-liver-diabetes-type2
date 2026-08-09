"""The per-serving numbers live in THREE places by design. This asserts they agree.

The three surfaces:

  1. ``data/fatty_liver_diabetes_guidelines.yaml`` → ``per_recipe_constraints.meal_categories``
     — what the deterministic rules actually enforce.
  2. the same YAML's ``prompt_snippets.drafting`` prose — what the DRAFTING MODEL is
     told, and therefore what the recipes are actually built to.
  3. section 4 of ``docs/fatty_liver_diabetes_guidelines.md`` — what a human editor
     makes decisions from.

Surface 3 is the one most likely to rot quietly, because **nothing imports the
dossier**: a stale number there fails no build and is discovered only when an editor
trusts it. Surface 2 is the one that silently changes the book: edit a ceiling in
(1) and forget (2) and every recipe is still drafted to the old number.

This file also pins the DAY ARITHMETIC. The envelope was derived by splitting daily
authority targets across the day's eating occasions, and the derivation only holds
if the tiers still sum the way they did — see the arithmetic block in section 4 of
the dossier. A retune that quietly breaks one of these sums breaks the book's claim
to follow the guideline it cites.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from src.config import BASE_DIR, GUIDELINES

DOSSIER = BASE_DIR / "docs" / "fatty_liver_diabetes_guidelines.md"

TIERS = ("main", "light_main", "snack", "dessert")

# The day the envelope was derived from. Day A = 3 mains + snack + dessert;
# Day B swaps the lunch main for a light_main (a soup or salad).
DAY_A = ("main", "main", "main", "snack", "dessert")
DAY_B = ("main", "light_main", "main", "snack", "dessert")


@pytest.fixture(scope="module")
def spec_yaml() -> dict:
    return yaml.safe_load(GUIDELINES.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tiers(spec_yaml: dict) -> dict:
    return spec_yaml["per_recipe_constraints"]["meal_categories"]


@pytest.fixture(scope="module")
def dossier() -> str:
    return DOSSIER.read_text(encoding="utf-8")


def _nums(text: str) -> list[float]:
    """Every number in a chunk of prose or a table cell, in order."""
    return [float(m) for m in re.findall(r"\d+(?:\.\d+)?", text)]


# ---------------------------------------------------------------------------
# 1. The spec's own internal shape
# ---------------------------------------------------------------------------

def test_all_four_tiers_exist(tiers: dict):
    assert set(tiers) == set(TIERS)


@pytest.mark.parametrize("tier", TIERS)
def test_every_tier_constrains_every_axis(tiers: dict, tier: str):
    """No axis may be silently dropped from a tier — an absent axis is an
    unconstrained one, and the loader returns None for it without complaint."""
    env = tiers[tier]
    for axis in (
        "protein_g", "fiber_g", "total_carbs_g", "added_sugar_g_max",
        "saturated_fat_g_max", "sodium_mg_max", "added_oil_tbsp_max", "energy_kcal",
    ):
        assert axis in env, f"tier '{tier}' has no {axis}"


@pytest.mark.parametrize("tier", TIERS)
def test_carbohydrate_window_is_ordered(tiers: dict, tier: str):
    c = tiers[tier]["total_carbs_g"]
    assert c["floor"] < c["target"] < c["max"], f"tier '{tier}' carbohydrate window is out of order"


@pytest.mark.parametrize("tier", TIERS)
def test_protein_and_fiber_targets_sit_above_their_floors(tiers: dict, tier: str):
    for axis in ("protein_g", "fiber_g"):
        f = tiers[tier][axis]
        assert f["floor"] <= f["target"], f"tier '{tier}' {axis}: target below floor"


def test_no_net_carbs_axis_anywhere_in_the_spec(spec_yaml: dict, tiers: dict):
    """Deliberate divergence from the parent engine — the ADA and FDA both count
    TOTAL carbohydrate and a reader dosing insulin must not be shown a subtracted
    number. If this ever fails, someone re-introduced the axis."""
    for tier, env in tiers.items():
        assert "net_carbs_g_max" not in env, f"tier '{tier}' re-introduced a net-carbs ceiling"
    panel = spec_yaml["nutrition_panel"]["nutrients"]
    net = [n for n in panel if n["key"] == "net_carbs_g"]
    assert net, "net_carbs_g should still be listed (documented as NOT printed)"
    assert net[0]["on_recipe_panel"] is False, "net carbs must not be printed on the panel"


# ---------------------------------------------------------------------------
# 2. YAML envelope  ↔  prompt_snippets.drafting prose
# ---------------------------------------------------------------------------

_DRAFTING_LINE_PREFIX = {
    "main": "- MAIN",
    "light_main": "- LIGHT MAIN",
    "snack": "- SNACK / SIDE",
    "dessert": "- DESSERT",
}


def _drafting_block(spec_yaml: dict, tier: str) -> str:
    """The (possibly wrapped) drafting-prose block for one tier."""
    lines = spec_yaml["prompt_snippets"]["drafting"].splitlines()
    prefix = _DRAFTING_LINE_PREFIX[tier]
    start = next((i for i, ln in enumerate(lines) if ln.strip().startswith(prefix)), None)
    assert start is not None, f"drafting snippet has no '{prefix}' line"
    block = [lines[start]]
    for ln in lines[start + 1:]:
        if ln.strip().startswith("- ") or not ln.strip():
            break
        block.append(ln)
    return " ".join(block)


@pytest.mark.parametrize("tier", TIERS)
def test_drafting_prose_restates_the_tier_numbers(spec_yaml: dict, tiers: dict, tier: str):
    """Every number in the tier's envelope must appear in the prose the drafting
    model actually reads. THIS is the test that catches "I retuned the YAML and
    forgot the prompt" — the failure mode where the rules and the recipes disagree."""
    block = _drafting_block(spec_yaml, tier)
    present = set(_nums(block))
    env = tiers[tier]
    expected = {
        env["protein_g"]["floor"], env["protein_g"]["target"],
        env["fiber_g"]["floor"], env["fiber_g"]["target"],
        env["total_carbs_g"]["floor"], env["total_carbs_g"]["target"], env["total_carbs_g"]["max"],
        env["added_sugar_g_max"]["value"],
        env["saturated_fat_g_max"]["value"],
        env["sodium_mg_max"]["value"],
        env["energy_kcal"]["min"], env["energy_kcal"]["max"],
    }
    missing = sorted(float(v) for v in expected if float(v) not in present)
    assert not missing, f"tier '{tier}': {missing} are in the envelope but not in the drafting prose"


def test_drafting_prose_states_the_carbohydrate_floor_is_load_bearing(spec_yaml: dict):
    """A number alone isn't enough — the model has to be told that going UNDER is a
    failure, or it will read every ceiling as "less is better" and drift keto."""
    drafting = spec_yaml["prompt_snippets"]["drafting"].upper()
    assert "WINDOW" in drafting
    assert "DEFECT" in drafting
    assert "FLOOR" in drafting


def test_ideation_and_critic_snippets_carry_the_book_identity(spec_yaml: dict):
    ideation = spec_yaml["prompt_snippets"]["ideation"]
    critic = spec_yaml["prompt_snippets"]["critic"]
    assert "Fatty Liver Diet Cookbook for Type 2 Diabetes" in ideation
    for banned_topic in ("alcohol", "added sugar", "carbohydrate"):
        assert banned_topic.lower() in ideation.lower()
    # The critic must be told never to praise a low-carbohydrate recipe.
    assert "NEVER PRAISE A RECIPE FOR BEING LOW IN CARBOHYDRATE" in critic


# ---------------------------------------------------------------------------
# 3. YAML envelope  ↔  the dossier's section-4 table
# ---------------------------------------------------------------------------

_DOSSIER_ROW_LABEL = {
    "protein": "**Protein**",
    "carbs": "**Total carbohydrate**",
    "fiber": "**Dietary fiber**",
    "added_sugar": "**Added sugars**",
    "sat_fat": "**Saturated fat**",
    "sodium": "**Sodium**",
    "energy": "**Energy**",
}


def _dossier_row(dossier: str, label: str) -> list[list[float]]:
    """The four tier cells of one row of the section-4 envelope table, as numbers."""
    for line in dossier.splitlines():
        s = line.strip()
        if s.startswith("|") and s.split("|")[1].strip() == label:
            cells = [c.strip() for c in s.split("|")[1:-1]]
            return [_nums(c) for c in cells[1:5]]
    raise AssertionError(f"dossier section 4 has no row labelled {label!r}")


@pytest.mark.parametrize("tier,idx", list(zip(TIERS, range(4))))
def test_dossier_table_matches_the_spec(dossier: str, tiers: dict, tier: str, idx: int):
    """Nothing imports the dossier, so a stale number there fails no build — it is
    only discovered when a human editor makes a decision from it. This is the guard."""
    env = tiers[tier]
    assert _dossier_row(dossier, _DOSSIER_ROW_LABEL["protein"])[idx] == [
        env["protein_g"]["floor"], env["protein_g"]["target"]]
    assert _dossier_row(dossier, _DOSSIER_ROW_LABEL["carbs"])[idx] == [
        env["total_carbs_g"]["floor"], env["total_carbs_g"]["target"], env["total_carbs_g"]["max"]]
    assert _dossier_row(dossier, _DOSSIER_ROW_LABEL["fiber"])[idx] == [
        env["fiber_g"]["floor"], env["fiber_g"]["target"]]
    assert _dossier_row(dossier, _DOSSIER_ROW_LABEL["added_sugar"])[idx] == [
        env["added_sugar_g_max"]["value"]]
    assert _dossier_row(dossier, _DOSSIER_ROW_LABEL["sat_fat"])[idx] == [
        env["saturated_fat_g_max"]["value"]]
    assert _dossier_row(dossier, _DOSSIER_ROW_LABEL["sodium"])[idx] == [
        env["sodium_mg_max"]["value"]]
    assert _dossier_row(dossier, _DOSSIER_ROW_LABEL["energy"])[idx] == [
        env["energy_kcal"]["min"], env["energy_kcal"]["max"]]


def test_dossier_lists_every_chapter_with_its_printed_title(dossier: str, spec_yaml: dict):
    for slug, cat in spec_yaml["recipe_categories"].items():
        assert slug in dossier or cat["book_title"] in dossier, f"chapter {slug} missing from the dossier"


def test_dossier_documents_every_hard_block(dossier: str, spec_yaml: dict):
    """A ban the engine enforces but the dossier never mentions is an unauditable
    editorial decision."""
    low = dossier.lower()
    topics = {
        "no_alcohol_ingredient": "alcohol",
        "no_deep_fried": "deep-fried",
        "no_sugar_sweetened_beverage_or_juice_component": "juice",
        "no_high_fructose_sweetener": "agave",
        "no_added_sugar_primary_base": "sugar-delivery vehicle",
        "no_refined_grain_base": "refined-grain",
        "no_processed_cured_meat_base": "processed",
        "no_tropical_saturated_fat_base": "coconut",
    }
    declared = {hb["rule"] for hb in spec_yaml["per_recipe_constraints"]["hard_blocks"]}
    assert declared == set(topics), "a hard block was added/removed without updating this test"
    for rule, topic in topics.items():
        assert topic in low, f"hard block {rule} ({topic!r}) is not discussed in the dossier"


# ---------------------------------------------------------------------------
# 4. The day arithmetic the envelope was derived from
# ---------------------------------------------------------------------------

def _day(tiers: dict, shape: tuple[str, ...], axis_path: tuple[str, ...]) -> float:
    total = 0.0
    for tier in shape:
        node = tiers[tier]
        for key in axis_path:
            node = node[key]
        total += float(node)
    return total


def _day_energy(tiers: dict, shape: tuple[str, ...], which: str) -> float:
    return sum(float(tiers[t]["energy_kcal"][which]) for t in shape)


def _day_energy_mid(tiers: dict, shape: tuple[str, ...]) -> float:
    return (_day_energy(tiers, shape, "min") + _day_energy(tiers, shape, "max")) / 2.0


@pytest.mark.parametrize("shape", [DAY_A, DAY_B], ids=["day_A_3_mains", "day_B_with_a_soup_lunch"])
def test_a_day_of_floor_hugging_recipes_still_clears_the_very_low_carb_line(tiers: dict, shape):
    """THE POINT OF THE CARBOHYDRATE FLOOR. A reader who cooks nothing but
    floor-hugging recipes for a whole day must still eat more than 26% of energy as
    carbohydrate — the line ADA's ketogenic caution keys on. Below it, a reader on an
    SGLT2 inhibitor is in the pattern their guideline tells clinicians to discourage.
    """
    carb_floor_g = _day(tiers, shape, ("total_carbs_g", "floor"))
    pct = carb_floor_g * 4 / _day_energy_mid(tiers, shape) * 100
    assert pct > 26.0, f"a floor-hugging day is only {pct:.1f}% carbohydrate — below the 26% line"


@pytest.mark.parametrize("shape", [DAY_A, DAY_B], ids=["day_A_3_mains", "day_B_with_a_soup_lunch"])
def test_a_day_of_maxed_recipes_stays_inside_the_amdr(tiers: dict, shape):
    carb_max_g = _day(tiers, shape, ("total_carbs_g", "max"))
    pct = carb_max_g * 4 / _day_energy_mid(tiers, shape) * 100
    assert 45.0 <= pct <= 65.0, f"a maxed day is {pct:.1f}% carbohydrate — outside the 45-65% AMDR"


@pytest.mark.parametrize("shape", [DAY_A, DAY_B], ids=["day_A_3_mains", "day_B_with_a_soup_lunch"])
def test_day_fiber_floors_clear_the_ada_route(tiers: dict, shape):
    """ADA: at least 14 g of fiber per 1,000 kcal. Checked against the FLOORS, so the
    promise survives a day of recipes that only just qualify."""
    fiber_g = _day(tiers, shape, ("fiber_g", "floor"))
    per_1000 = fiber_g / _day_energy_mid(tiers, shape) * 1000
    assert per_1000 >= 14.0, f"{per_1000:.1f} g fiber per 1,000 kcal — under ADA's 14"


@pytest.mark.parametrize("shape", [DAY_A, DAY_B], ids=["day_A_3_mains", "day_B_with_a_soup_lunch"])
def test_day_sodium_ceilings_sum_under_2300(tiers: dict, shape):
    """DGA 2025-2030 and ADA both cap sodium at <2,300 mg/day. Checked against the
    CEILINGS with margin, because brand and database variability eat a thin one."""
    total = _day(tiers, shape, ("sodium_mg_max", "value"))
    assert total <= 2300, f"day sodium ceilings sum to {total:.0f} mg"
    assert total <= 2300 * 0.95, f"only a {(1 - total / 2300) * 100:.1f}% margin under 2,300 mg"


@pytest.mark.parametrize("shape", [DAY_A, DAY_B], ids=["day_A_3_mains", "day_B_with_a_soup_lunch"])
def test_day_added_sugar_ceilings_stay_under_the_aha_limit(tiers: dict, shape):
    """AHA: no more than 25 g/day for women, 36 g for men. Added sugar is the
    liver-specific axis, so the tighter of the two is the one to hold."""
    total = _day(tiers, shape, ("added_sugar_g_max", "value"))
    assert total <= 25, f"day added-sugar ceilings sum to {total:.0f} g — over the AHA 25 g limit"


@pytest.mark.parametrize("tier", TIERS)
def test_every_single_recipe_clears_the_dga_per_meal_added_sugar_figure(tiers: dict, tier: str):
    """DGA 2025-2030 sets a PER-MEAL figure: no more than 10 g of added sugars."""
    assert tiers[tier]["added_sugar_g_max"]["value"] <= 10


@pytest.mark.parametrize("shape", [DAY_A, DAY_B], ids=["day_A_3_mains", "day_B_with_a_soup_lunch"])
def test_day_saturated_fat_ceilings_stay_under_ten_percent_of_energy(tiers: dict, shape):
    """DGA: saturated fat under 10% of calories. Checked in the worst case — every
    recipe sitting exactly on its ceiling."""
    grams = _day(tiers, shape, ("saturated_fat_g_max", "value"))
    pct = grams * 9 / _day_energy_mid(tiers, shape) * 100
    assert pct < 10.0, f"a day at every saturated-fat ceiling is {pct:.1f}% of energy"


@pytest.mark.parametrize("shape", [DAY_A, DAY_B], ids=["day_A_3_mains", "day_B_with_a_soup_lunch"])
def test_the_plan_day_is_hypocaloric_for_this_reader(tiers: dict, shape):
    """Weight loss is the therapy (>=5% liver fat / 7-10% inflammation / >=10%
    fibrosis). The printed day must be a real deficit against a typical maintenance
    of 2,150-2,700 kcal for this readership, without dropping below the WHO/EFSA
    floors the personalization module enforces."""
    mid = _day_energy_mid(tiers, shape)
    assert 1500 <= mid <= 1800, f"plan day is {mid:.0f} kcal"


@pytest.mark.parametrize("shape", [DAY_A, DAY_B], ids=["day_A_3_mains", "day_B_with_a_soup_lunch"])
def test_day_protein_targets_land_in_the_dga_band_for_a_70kg_reader(tiers: dict, shape):
    """DGA 2025-2030: 1.2-1.6 g/kg/day. The FLOORS are the warning line, not the
    design point — the TARGETS are what the plan aims at."""
    targets = _day(tiers, shape, ("protein_g", "target"))
    assert 1.2 <= targets / 70.0 <= 1.6, f"day protein targets = {targets:.0f} g = {targets / 70:.2f} g/kg"


def test_optional_meal_types_is_dessert_only():
    """The snack slot is deliberately NOT optional: the ADA names skipped meals as a
    hypoglycemia driver, and the snack carries part of the day's carbohydrate floor.
    Guarded because "tidying" it back to {snack, dessert} is a one-word change."""
    from src.constants import OPTIONAL_MEAL_TYPES

    assert OPTIONAL_MEAL_TYPES == frozenset({"dessert"})


def test_the_day_left_after_skipping_dessert_still_clears_the_carb_line(tiers: dict):
    """OPTIONAL_MEAL_TYPES is a promise to the reader — the day has to survive it."""
    shape = tuple(t for t in DAY_A if t != "dessert")
    carb_floor_g = _day(tiers, shape, ("total_carbs_g", "floor"))
    pct = carb_floor_g * 4 / _day_energy_mid(tiers, shape) * 100
    assert pct > 26.0, f"skipping dessert leaves a {pct:.1f}% carbohydrate day"


def test_the_dossier_and_the_spec_agree_on_the_review_date(spec_yaml: dict, dossier: str):
    assert spec_yaml["meta"]["last_reviewed"] in dossier


def test_companion_doc_pointer_resolves(spec_yaml: dict):
    assert (BASE_DIR / Path(spec_yaml["meta"]["companion_doc"])).is_file()
