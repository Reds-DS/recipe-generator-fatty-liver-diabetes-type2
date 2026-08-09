"""Integration-style tests for pipeline stages — no LLM or API calls."""
import pytest
from pydantic import ValidationError

from src.cooking.method_checker import (
    check_equipment,
    check_everyday_ingredients,
    check_grain_base,
    check_thirty_minutes,
)
from src.cooking.quantity_checker import _classify, build_correction_prompt, check_quantities
from src.diet_rules import spec
from src.llm.output_schemas import CriticDimensionVerdict, CriticOutput
from src.llm.prompts import critic as critic_prompts
from src.models.nutrition import NutritionInfo
from src.models.recipe import Ingredient, RecipeBrief, RecipeDraft
from src.recipe_pipeline import stage_03_diet_check, stage_05b_critic


def _make_draft(**overrides) -> RecipeDraft:
    base: dict = dict(
        title="Roast chicken with vegetables",
        intro="A simple, filling plate.",
        meal_type="dinner",
        servings=2,
        prep_time_min=10,
        cook_time_min=20,
        cook_time_max_min=25,
        ingredients=[
            Ingredient(
                name="chicken breast", canonical_name="chicken breast",
                quantity_g=300, quantity_display="300 g",
                nutrition_source="missing",
            ),
            Ingredient(
                name="zucchini", canonical_name="zucchini",
                quantity_g=250, quantity_display="250 g",
                nutrition_source="missing",
            ),
        ],
        instructions=["Prep the ingredients.", "Cook.", "Serve."],
    )
    base.update(overrides)
    return RecipeDraft(**base)


def _nutrition(**overrides) -> NutritionInfo:
    base: dict = dict(
        calories_kcal=420, protein_g=28, carbs_g=30, fat_g=14, fiber_g=6,
        sodium_mg=300, sugar_g=5, source="llm_usda", confidence="high",
    )
    base.update(overrides)
    return NutritionInfo(**base)


class TestDietCheckStage:
    """The fatty-liver + type-2-diabetes diet engine (src/diet_rules/): structural hard blocks (run
    pre- and post-nutrition) plus, once nutrition is attached, per-chapter nutrient-tier warnings.
    A plain chicken-and-zucchini draft trips no hard block, so it passes."""

    def test_pre_nutrition_passes_clean_draft(self):
        report = stage_03_diet_check.run_pre_nutrition(_make_draft())
        assert report.overall_passed
        assert report.blocking_violations == []

    def test_post_nutrition_passes_clean_draft(self):
        report = stage_03_diet_check.run_post_nutrition(_make_draft())
        assert report.overall_passed
        assert report.blocking_violations == []

    def test_processed_meat_base_is_blocked(self):
        draft = _make_draft(ingredients=[
            Ingredient(name="smoked bacon", canonical_name="bacon", quantity_g=200,
                       quantity_display="200 g", nutrition_source="missing"),
            Ingredient(name="onion", canonical_name="onion", quantity_g=120,
                       quantity_display="120 g", nutrition_source="missing"),
        ])
        report = stage_03_diet_check.run_pre_nutrition(draft)
        assert not report.overall_passed
        assert report.blocking_violations  # non-empty

    @pytest.mark.parametrize("name", [
        "dark chocolate (70-85% cacao)",  # "cola" inside "cho-cola-te"
        "semisweet chocolate chips",
        "baking soda",                    # leavening, not a drink
        "bicarbonate of soda",
        "club soda",                      # unsweetened mixer
    ])
    def test_chocolate_and_baking_soda_are_not_sugar_sweetened_beverages(self, name):
        # Regression: a plain substring match blocked every chocolate / baked dessert.
        draft = _make_draft(
            chapter="desserts", meal_type="dessert",
            ingredients=[
                Ingredient(name=name, canonical_name=name, quantity_g=30,
                           quantity_display="30 g", nutrition_source="missing"),
                Ingredient(name="greek yogurt", canonical_name="greek yogurt", quantity_g=200,
                           quantity_display="200 g", nutrition_source="missing"),
            ],
        )
        report = stage_03_diet_check.run_pre_nutrition(draft)
        assert report.overall_passed
        assert report.blocking_violations == []

    @pytest.mark.parametrize("name", ["cola", "orange soda", "lemonade", "gatorade"])
    def test_real_sugar_sweetened_beverages_are_still_blocked(self, name):
        draft = _make_draft(ingredients=[
            Ingredient(name=name, canonical_name=name, quantity_g=200,
                       quantity_display="200 ml", nutrition_source="missing"),
        ])
        report = stage_03_diet_check.run_pre_nutrition(draft)
        assert not report.overall_passed
        assert report.blocking_violations

    def test_keyword_match_still_catches_inflections(self):
        # The word-start anchor must not break plurals: "sausage" → "sausages".
        draft = _make_draft(ingredients=[
            Ingredient(name="turkey sausages", canonical_name="sausages", quantity_g=200,
                       quantity_display="200 g", nutrition_source="missing"),
        ])
        report = stage_03_diet_check.run_pre_nutrition(draft)
        assert not report.overall_passed

    def test_low_protein_warns_post_nutrition(self):
        # the default chapter maps to the `main` tier → protein floor 26 g/serving
        # (the ~25-30 g per-meal satiety + MPS threshold)
        report = stage_03_diet_check.run_post_nutrition(
            _make_draft(), _nutrition(protein_g=8)
        )
        assert report.overall_passed  # soft target → a warning, not a blocker
        assert any("protein" in w.lower() for w in report.warnings)

    def test_high_saturated_fat_warns_post_nutrition(self):
        # `main` tier saturated_fat_g_max = 5 g/serving
        report = stage_03_diet_check.run_post_nutrition(
            _make_draft(), _nutrition(saturated_fat_g=12)
        )
        assert report.overall_passed  # soft
        assert any("saturated fat" in w.lower() for w in report.warnings)

    def test_high_added_sugar_warns_for_dessert(self):
        # `dessert` tier added_sugar_g_max = 7 g/serving
        draft = _make_draft(chapter="desserts", meal_type="dessert")
        report = stage_03_diet_check.run_post_nutrition(draft, _nutrition(added_sugar_g=20))
        assert report.overall_passed  # soft
        assert any("added sugar" in w.lower() for w in report.warnings)

    def test_added_sugar_proxy_from_sweetener_when_not_computed(self):
        # No computed added_sugar_g → fall back to the added-sweetener ingredient-gram proxy.
        draft = _make_draft(
            chapter="desserts", meal_type="dessert",
            ingredients=[
                Ingredient(name="rolled oats", canonical_name="rolled oats", quantity_g=120,
                           quantity_display="120 g", nutrition_source="missing"),
                Ingredient(name="sugar", canonical_name="sugar", quantity_g=80,
                           quantity_display="80 g", nutrition_source="missing"),
            ],
        )
        report = stage_03_diet_check.run_post_nutrition(draft, _nutrition(added_sugar_g=None))
        # 80 g sweetener / 2 servings = 40 g/serving > 10 g ceiling.
        assert report.overall_passed
        assert any("estimated from sweetener" in w.lower() for w in report.warnings)

    def test_correction_prompt_is_a_string(self):
        report = stage_03_diet_check.run_pre_nutrition(_make_draft())
        prompt = stage_03_diet_check.build_correction_prompt(report)
        assert isinstance(prompt, str)
        assert "Required corrections" in prompt


class TestServingsConstraint:
    def test_servings_always_2(self):
        assert _make_draft().servings == 2

    def test_cannot_set_servings_to_4(self):
        """The Literal[2] type prevents setting servings to any other value."""
        with pytest.raises(Exception):
            _make_draft(servings=4)


# ---------------------------------------------------------------------------
# Guideline-fit critic (Stage 5b) — schema, prompt builders, parsing
# ---------------------------------------------------------------------------

_NEW_CRITIC_DIMENSIONS = (
    "one_plan_both_conditions", "added_sugar_and_carb_balance",
    "chapter_intent_fit", "thirty_minute_practicality",
)


def _brief(**overrides) -> RecipeBrief:
    base: dict = dict(
        title_candidate="Roast chicken with vegetables",
        main_ingredient="chicken breast",
        cuisine_style="classic American",
        technique="roasting",
        flavour_profile="savory, lemony",
        ingredients_sketch=["chicken breast", "zucchini", "lemon", "olive oil"],
        unique_angle="one-pan weeknight dinner",
        forbidden_items=[],
        meal_type="dinner",
        chapter="poultry_meat_dinners",
    )
    base.update(overrides)
    return RecipeBrief(**base)


def _dims(n: int, *, one_failing_major: bool = False) -> list[CriticDimensionVerdict]:
    out: list[CriticDimensionVerdict] = []
    for i in range(n):
        if one_failing_major and i == 0:
            out.append(CriticDimensionVerdict(
                dimension="one_plan_both_conditions", passed=False, severity="major",
                feedback="The sauce reads as rich/creamy despite dodging the keyword list.",
            ))
        else:
            out.append(CriticDimensionVerdict(
                dimension=f"dim_{i}", passed=True, severity="minor", feedback="Fine.",
            ))
    return out


class TestGuidelineSpec:
    def test_prompt_snippets_has_critic_and_no_dead_key(self):
        s = spec.load_spec()
        assert s.prompt_snippets.get("critic", "").strip()
        assert "diet_check_summary" not in s.prompt_snippets
        assert sorted(s.prompt_snippets) == ["critic", "drafting", "ideation"]

    def test_schema_version_is_current(self):
        # Bump this when the YAML schema_version changes. Current: 1
        # (this book's spec was authored fresh at schema_version 1 —
        # see data/fatty_liver_diabetes_guidelines.yaml meta.schema_version).
        assert spec.load_spec().schema_version == 1

    def test_chapter_slugs_agree_across_all_three_places(self):
        """The three-place chapter coupling: the YAML `recipe_categories`, the
        `RECIPE_CHAPTERS` tuple in src/constants.py, and the `RecipeChapter`
        Literal in src/models/recipe.py. Drift makes Pydantic reject valid values,
        or makes the diet rules silently resolve an empty envelope that "passes"
        everything. Nothing else catches this."""
        from typing import get_args

        from src.constants import (
            MEAL_TYPE_DEFAULT_CHAPTER,
            RECIPE_CHAPTER_MEAL_TYPES,
            RECIPE_CHAPTER_NUTRIENT_TIER,
            RECIPE_CHAPTER_TITLES,
            RECIPE_CHAPTERS,
        )
        from src.models.recipe import RecipeChapter

        yaml_slugs = set(spec.load_spec().recipe_categories)
        assert yaml_slugs == set(RECIPE_CHAPTERS)
        assert yaml_slugs == set(get_args(RecipeChapter))
        # …and the four companion maps in constants.py.
        assert yaml_slugs == set(RECIPE_CHAPTER_TITLES)
        assert yaml_slugs == set(RECIPE_CHAPTER_MEAL_TYPES)
        assert yaml_slugs == set(RECIPE_CHAPTER_NUTRIENT_TIER)
        assert set(MEAL_TYPE_DEFAULT_CHAPTER.values()) <= yaml_slugs

    def test_every_chapter_tier_resolves_to_a_defined_tier(self):
        s = spec.load_spec()
        for slug, cat in s.recipe_categories.items():
            assert cat.nutrient_tier in s.meal_categories, f"{slug} → unknown tier {cat.nutrient_tier}"

    def test_declared_hard_blocks_are_all_implemented(self):
        """A rule id declared in the YAML with no matching class in rules.py is a
        SILENT no-op — the spec claims a ban the engine never enforces. Guard both
        directions."""
        from src.diet_rules.rules import _HARD_BLOCK_RULES

        declared = {hb.rule for hb in spec.load_spec().hard_blocks}
        implemented = {r.name.split(".", 1)[1] for r in _HARD_BLOCK_RULES}
        assert declared == implemented, (
            f"declared-only: {sorted(declared - implemented)}; "
            f"implemented-only: {sorted(implemented - declared)}"
        )


class TestCriticPromptBuilders:
    def test_build_system_includes_12_dimensions_and_checklist(self):
        checklist = spec.load_spec().prompt_snippets["critic"]
        built = critic_prompts.build_system(checklist)
        assert "12" in built
        for name in _NEW_CRITIC_DIMENSIONS:
            assert name in built
        # The checklist is concatenated verbatim — a representative line should appear.
        assert "one_plan_both_conditions" in built
        assert "carbohydrate_both_directions" in built
        # No unfilled template placeholder (build_system uses concatenation, not str.format).
        assert "{" not in built

    def test_build_system_works_without_checklist(self):
        built = critic_prompts.build_system()
        assert "THE 12 DIMENSIONS" in built
        assert "OUTPUT RULES" in built

    def test_build_user_includes_chapter_brief_and_prior_warnings(self):
        draft = _make_draft()
        nutrition = _nutrition()
        user = critic_prompts.build_user(
            draft, nutrition, _brief(), schema_json="{}",
            chapter_brief="TARGET CHAPTER: Super Simple Weeknight Dinners (made up).",
            prior_warnings=["protein below the meal-category floor", "carb base looks ambiguous"],
        )
        assert "TARGET CHAPTER: Super Simple Weeknight Dinners (made up)." in user
        assert "protein below the meal-category floor" in user
        assert "carb base looks ambiguous" in user
        assert "AUTOMATED-CHECK NOTES" in user

    def test_build_user_omits_blocks_when_empty(self):
        user = critic_prompts.build_user(_make_draft(), _nutrition(), _brief(), schema_json="{}")
        assert "TARGET CHAPTER" not in user
        assert "AUTOMATED-CHECK NOTES" not in user


class TestCriticOutputSchema:
    @pytest.mark.parametrize("n", [8, 12, 14])
    def test_accepts_8_to_14_dimensions(self, n):
        out = CriticOutput(overall_pass=True, dimensions=_dims(n), summary="ok")
        assert len(out.dimensions) == n

    @pytest.mark.parametrize("n", [7, 15])
    def test_rejects_out_of_range_dimension_counts(self, n):
        with pytest.raises(ValidationError):
            CriticOutput(overall_pass=True, dimensions=_dims(n), summary="ok")


class TestCriticParseResponse:
    def test_twelve_dims_one_major_failure_is_blocking(self):
        out = CriticOutput(
            overall_pass=False, dimensions=_dims(12, one_failing_major=True), summary="needs work",
        )
        result = stage_05b_critic.parse_response(out.model_dump_json())
        assert result.passed is False
        assert len(result.blocking_feedback) == 1
        assert "one_plan_both_conditions" in result.blocking_feedback[0]

    def test_all_passing_dims_is_not_blocking(self):
        out = CriticOutput(overall_pass=True, dimensions=_dims(12), summary="great")
        result = stage_05b_critic.parse_response(out.model_dump_json())
        assert result.passed is True
        assert result.blocking_feedback == []

    def test_minor_only_failure_is_a_warning_not_blocking(self):
        dims = _dims(12)
        dims[3] = CriticDimensionVerdict(
            dimension="overall_appeal", passed=False, severity="minor", feedback="A touch plain.",
        )
        out = CriticOutput(overall_pass=True, dimensions=dims, summary="fine, minor nit")
        result = stage_05b_critic.parse_response(out.model_dump_json())
        assert result.passed is True
        assert result.blocking_feedback == []
        assert any("overall_appeal" in w for w in result.warnings)


class TestCriticBuildRequest:
    def test_user_prompt_carries_the_target_chapter_title(self):
        book_title = spec.load_spec().category("snacks_sides").book_title
        system, user, max_tokens, thinking_budget = stage_05b_critic.build_request(
            _make_draft(chapter="snacks_sides", meal_type="snack"),
            _nutrition(),
            _brief(chapter="snacks_sides", meal_type="snack"),
            chapter="snacks_sides",
        )
        assert book_title in user
        assert "12" in system
        assert max_tokens == 6144 and thinking_budget == 4000


# ---------------------------------------------------------------------------
# Deterministic Stage-5 advisory checks (30-minute overshoot, equipment,
# ambiguous grain base, everyday ingredients)
# ---------------------------------------------------------------------------

def _ing(name: str, grams: float) -> Ingredient:
    return Ingredient(
        name=name, canonical_name=name, quantity_g=grams,
        quantity_display=f"{grams:g} g", nutrition_source="missing",
    )


class TestThirtyMinuteCheck:
    def test_long_ingredient_list_warns(self):
        many = [_ing(f"vegetable {i}", 40) for i in range(14)]
        warnings = check_thirty_minutes(_make_draft(ingredients=many)).warnings
        assert any("ingredient" in w.lower() for w in warnings)

    def test_freebies_and_small_oil_do_not_count(self):
        # 12 "meaningful" + salt + pepper + water + 5 g oil = 16 listed, 12 meaningful → no warning.
        ings = [_ing(f"vegetable {i}", 40) for i in range(12)]
        ings += [_ing("salt", 3), _ing("black pepper", 1), _ing("water", 60), _ing("olive oil", 5)]
        assert check_thirty_minutes(_make_draft(ingredients=ings)).warnings == []

    def test_long_prep_time_warns(self):
        warnings = check_thirty_minutes(_make_draft(prep_time_min=40)).warnings
        assert any("active time" in w.lower() for w in warnings)

    def test_over_thirty_minutes_warns_with_no_set_and_forget_exemption(self):
        """The parent cookbook exempted slow-cooker recipes from its time cap.
        THIS BOOK HAS NO SUCH EXEMPTION — "in Under 30 Minutes" is on the cover and
        the description says "no exceptions". A long recipe always warns."""
        long_draft = _make_draft(prep_time_min=15, cook_time_min=30, cook_time_max_min=35)
        assert any("30-minute" in w for w in check_thirty_minutes(long_draft).warnings)
        slow = _make_draft(
            prep_time_min=15, cook_time_min=180, cook_time_max_min=240,
            instructions=["Brown the meat.", "Transfer to the slow cooker and cook on low.", "Serve."],
        )
        assert any("30-minute" in w for w in check_thirty_minutes(slow).warnings)

    def test_clean_small_draft_has_no_warnings(self):
        assert check_thirty_minutes(_make_draft()).warnings == []


class TestEquipmentCheck:
    @pytest.mark.parametrize("phrase", [
        "Cook in the air fryer at 200C.",
        "Transfer to the slow cooker and cook on low.",
        "Seal in the pressure cooker for 8 minutes.",
        "Set the Instant Pot to saute.",
        "Finish sous vide at 55C.",
    ])
    def test_disallowed_equipment_is_flagged(self, phrase):
        draft = _make_draft(instructions=["Prep the ingredients.", phrase, "Serve."])
        assert check_equipment(draft).warnings

    def test_allowed_equipment_passes(self):
        draft = _make_draft(instructions=[
            "Preheat the oven to 400F / 205C.",
            "Roast on a sheet pan, then finish in a skillet over medium heat.",
            "Blend the sauce and serve.",
        ])
        assert check_equipment(draft).warnings == []


class TestEverydayIngredientsCheck:
    @pytest.mark.parametrize("name", [
        "nutritional yeast", "coconut aminos", "psyllium husk", "vital wheat gluten",
        "seitan", "teff flour", "powdered peanut butter",
    ])
    def test_specialty_ingredient_flagged(self, name):
        draft = _make_draft(ingredients=[_ing(name, 20), _ing("chicken breast", 300)])
        warnings = check_everyday_ingredients(draft).warnings
        assert warnings and name.split()[0] in warnings[0].lower()

    def test_common_ingredients_pass(self):
        # chicken + zucchini (the default draft) are supermarket staples
        assert check_everyday_ingredients(_make_draft()).warnings == []


class TestGrainBaseCheck:
    def test_bare_pasta_warns(self):
        draft = _make_draft(ingredients=[_ing("pasta", 120), _ing("tomato", 200)])
        warnings = check_grain_base(draft).warnings
        assert len(warnings) == 1
        assert "whole grain" in warnings[0].lower()

    @pytest.mark.parametrize("name", ["whole-wheat pasta", "brown rice", "100% whole-grain tortilla"])
    def test_qualified_grain_base_is_fine(self, name):
        draft = _make_draft(ingredients=[_ing(name, 120), _ing("tomato", 200)])
        assert check_grain_base(draft).warnings == []

    def test_small_amount_below_floor_is_ignored(self):
        # 30 g total (<50 g) → a garnish, not a carb base.
        draft = _make_draft(ingredients=[_ing("pasta", 30), _ing("chicken breast", 300)])
        assert check_grain_base(draft).warnings == []

    def test_non_grain_ingredient_does_not_match(self):
        assert check_grain_base(_make_draft()).warnings == []  # chicken + zucchini

    def test_qualifier_on_the_DISPLAY_name_counts_even_when_canonical_name_lacks_it(self):
        """Regression, found live during the 20-recipe run.

        `canonical_name` is the USDA-style LOOKUP string and deliberately drops
        variant qualifiers so the food DB matches: a "Whole wheat couscous, dry"
        ingredient carries canonical_name "Couscous, dry". Reading canonical_name
        alone made this advisory contradict the hard block — which reads BOTH names
        and correctly passed the same ingredient."""
        ing = Ingredient(
            name="Whole wheat couscous, dry", canonical_name="Couscous, dry",
            quantity_g=85, quantity_display="1/2 cup (85 g)", nutrition_source="missing",
        )
        assert check_grain_base(_make_draft(ingredients=[ing, _ing("cod fillet", 340)])).warnings == []

    def test_a_genuinely_ambiguous_base_still_warns_when_neither_name_qualifies(self):
        ing = Ingredient(
            name="couscous", canonical_name="Couscous, dry",
            quantity_g=85, quantity_display="1/2 cup (85 g)", nutrition_source="missing",
        )
        assert check_grain_base(_make_draft(ingredients=[ing, _ing("cod fillet", 340)])).warnings


# ---------------------------------------------------------------------------
# Stage-2b quantity plausibility — tier-keyed bounds + classification
# ---------------------------------------------------------------------------

class TestQuantityClassify:
    @pytest.mark.parametrize("name", [
        "large eggs", "egg whites", "plain greek yogurt", "low-fat cottage cheese",
        "halibut fillet", "canned cannellini beans", "edamame", "ground chicken",
    ])
    def test_protein_sources_classify_as_protein(self, name):
        assert _classify(_ing(name, 100)) == "protein"

    def test_eggplant_is_not_protein(self):
        # The word-boundary fix: "egg" must not match inside "eggplant".
        assert _classify(_ing("eggplant", 200)) is None

    def test_fats_classify_as_oil(self):
        assert _classify(_ing("extra-virgin olive oil", 14)) == "oil"
        assert _classify(_ing("natural peanut butter", 30)) == "oil"  # fat-dominant → oil, not protein

    def test_salty_condiments_classify_as_salt(self):
        assert _classify(_ing("low-sodium soy sauce", 30)) == "salt"
        assert _classify(_ing("kosher salt", 4)) == "salt"

    def test_plain_vegetable_classifies_as_none(self):
        assert _classify(_ing("zucchini", 200)) is None

    def test_broth_and_stock_are_not_protein_sources(self):
        """Regression for the Soups & Salads chapter: "chicken broth" matches
        "chicken", and a soup carries broth by the litre — without the guard, every
        soup blew the per-person protein ceiling."""
        assert _classify(_ing("low-sodium chicken broth", 900)) is None
        assert _classify(_ing("beef stock", 700)) is None
        assert _classify(_ing("vegetable bouillon", 400)) is None
        # real protein sources still classify
        assert _classify(_ing("chicken breast", 250)) == "protein"

    def test_no_salt_added_items_are_not_salt(self):
        # "no-salt-added" / "salt-free" ingredients must not be misread as a salt source (the word
        # "salt" is only a negation) — else the sodium-conscious naming trips the flat salt cap.
        assert _classify(_ing("no-salt-added diced tomatoes", 200)) is None
        assert _classify(_ing("salt-free roasted red peppers", 80)) is None
        assert _classify(_ing("no-salt-added black beans", 150)) == "protein"  # beans match first
        # real salt sources still classify
        assert _classify(_ing("table salt", 5)) == "salt"
        assert _classify(_ing("low-sodium soy sauce", 30)) == "salt"


class TestQuantityCheck:
    def test_clean_default_draft_passes(self):
        result = check_quantities(_make_draft())  # 550 g total, chapter "dinner" → "main" tier
        assert result.passed is True
        assert result.warnings == []

    def test_snack_tier_uses_smaller_bounds_than_main(self):
        # 420 g total → 210 g/person: fine for the `snack` tier, but below the `main` floor.
        ings = [_ing("salmon fillet", 220), _ing("asparagus", 200)]
        snack = check_quantities(_make_draft(chapter="snacks_sides", meal_type="snack", ingredients=ings))
        assert snack.passed is True
        as_main = check_quantities(_make_draft(chapter="poultry_meat_dinners", meal_type="dinner", ingredients=ings))
        assert as_main.passed is False
        assert any("too low" in w.lower() for w in as_main.warnings)

    def test_four_person_recipe_is_flagged(self):
        draft = _make_draft(chapter="poultry_meat_dinners", ingredients=[_ing("chicken breast", 2000), _ing("rice", 400)])
        result = check_quantities(draft)
        assert result.passed is False
        assert any("4 people" in w for w in result.warnings)

    def test_dairy_heavy_breakfast_does_not_false_positive_on_protein(self):
        ings = [_ing("plain greek yogurt", 300), _ing("cottage cheese", 150), _ing("blueberries", 100)]
        result = check_quantities(_make_draft(chapter="breakfasts", meal_type="breakfast", ingredients=ings))
        assert result.passed is True
        assert not any("protein" in w.lower() for w in result.warnings)

    def test_excess_protein_is_flagged(self):
        draft = _make_draft(chapter="poultry_meat_dinners", ingredients=[_ing("chicken breast", 900), _ing("broccoli", 200)])
        result = check_quantities(draft)
        assert result.passed is False
        assert any("suspect protein amount" in w.lower() for w in result.warnings)

    def test_high_oil_is_flagged(self):
        draft = _make_draft(ingredients=[_ing("chicken breast", 300), _ing("zucchini", 250), _ing("olive oil", 50)])
        result = check_quantities(draft)
        assert result.passed is False
        assert any("high oil" in w.lower() for w in result.warnings)

    def test_high_salt_is_flagged(self):
        draft = _make_draft(ingredients=[_ing("chicken breast", 300), _ing("zucchini", 250), _ing("table salt", 12)])
        result = check_quantities(draft)
        assert result.passed is False
        assert any("high salt" in w.lower() for w in result.warnings)

    def test_correction_prompt_mentions_two_servings(self):
        result = check_quantities(_make_draft(ingredients=[_ing("chicken breast", 200), _ing("broccoli", 50)]))
        prompt = build_correction_prompt(result)
        assert isinstance(prompt, str)
        assert "2 servings" in prompt

    def test_light_main_tier_tolerates_a_brothy_soup(self):
        """`light_main` has the HIGHEST raw-weight ceiling in the book despite being
        the lighter tier: a soup for two is mostly water by weight. Judging Soups &
        Salads against `main`'s ceiling would bounce the whole chapter."""
        ings = [_ing("low-sodium chicken broth", 900), _ing("chicken breast", 250),
                _ing("carrot", 150), _ing("pearl barley", 90)]
        soup = check_quantities(_make_draft(chapter="soups_salads", meal_type="lunch", ingredients=ings))
        assert soup.passed is True


# ---------------------------------------------------------------------------
# The eight hard blocks — one pass and one fail each, plus the false-friend
# guards whose ORDER is load-bearing (see the docstring of src/diet_rules/rules.py)
# ---------------------------------------------------------------------------

def _blocked(**overrides) -> bool:
    report = stage_03_diet_check.run_pre_nutrition(_make_draft(**overrides))
    return not report.overall_passed


class TestAlcoholHardBlock:
    """The signature rule of this book: alcohol fails at ANY quantity."""

    @pytest.mark.parametrize("name", [
        "dry white wine", "red wine", "lager beer", "dry sherry", "marsala wine",
        "mirin", "sake", "dark rum", "bourbon", "brandy", "cooking wine",
        "Grand Marnier", "amaretto liqueur", "hard cider",
    ])
    def test_alcoholic_ingredients_are_blocked_at_any_quantity(self, name):
        assert _blocked(ingredients=[_ing(name, 5), _ing("chicken breast", 300)])

    @pytest.mark.parametrize("name", [
        "red wine vinegar", "white wine vinegar", "rice wine vinegar", "sherry vinegar",
        "champagne vinegar", "apple cider vinegar", "bourbon vanilla extract",
        "vanilla extract", "almond extract",
    ])
    def test_vinegars_and_extracts_are_not_alcohol(self, name):
        """FALSE-FRIEND ORDER IS LOAD-BEARING: "wine vinegar" contains "wine".
        This book leans on acid as its main salt replacement, so a wine block that
        swallowed the vinegars would make most recipes undraftable."""
        assert not _blocked(ingredients=[_ing(name, 15), _ing("chicken breast", 300)])

    def test_ginger_is_not_gin(self):
        # `\bgin` would match the start of "ginger" — bare "gin" is deliberately
        # absent from the keyword list for exactly this reason.
        assert not _blocked(ingredients=[_ing("fresh ginger", 10), _ing("chicken breast", 300)])

    def test_portobello_is_not_port(self):
        # Same trap: bare "port" would match "portobello". Only "port wine" is listed.
        assert not _blocked(ingredients=[_ing("portobello mushrooms", 200), _ing("chicken breast", 300)])

    def test_deglazing_with_wine_in_the_instructions_is_blocked(self):
        assert _blocked(instructions=[
            "Sear the chicken.", "Deglaze with wine and reduce.", "Serve.",
        ])


class TestHighFructoseHardBlock:
    @pytest.mark.parametrize("name", [
        "high-fructose corn syrup", "corn syrup", "agave nectar", "agave syrup",
        "light corn syrup", "crystalline fructose",
    ])
    def test_fructose_syrups_are_blocked_at_any_quantity(self, name):
        assert _blocked(ingredients=[_ing(name, 4), _ing("greek yogurt", 200)])

    @pytest.mark.parametrize("name", ["maple syrup", "honey", "cane sugar"])
    def test_ordinary_sweeteners_in_small_amounts_pass_the_hard_block(self, name):
        # They still count against the tier's soft added-sugar ceiling — this rule
        # is only about the *fructose syrups*.
        assert not _blocked(ingredients=[_ing(name, 8), _ing("greek yogurt", 250)])


class TestJuiceAndSSBHardBlock:
    @pytest.mark.parametrize("name", ["orange juice", "apple juice", "apple cider", "grape juice"])
    def test_fruit_juice_as_a_component_is_blocked(self, name):
        assert _blocked(ingredients=[_ing(name, 120), _ing("chicken breast", 300)])

    @pytest.mark.parametrize("name", ["lemon juice", "lime juice", "tomato juice"])
    def test_lemon_and_lime_juice_pass(self, name):
        """The book's main salt replacement — must never trip the juice block."""
        assert not _blocked(ingredients=[_ing(name, 60), _ing("chicken breast", 300)])

    def test_a_splash_of_juice_below_the_floor_passes(self):
        assert not _blocked(ingredients=[_ing("orange juice", 15), _ing("chicken breast", 300)])


class TestTropicalFatHardBlock:
    @pytest.mark.parametrize("name", ["coconut oil", "palm oil", "palm kernel oil", "coconut cream"])
    def test_tropical_fats_are_blocked(self, name):
        assert _blocked(ingredients=[_ing(name, 14), _ing("chicken breast", 300)])

    @pytest.mark.parametrize("name", [
        "coconut water", "coconut aminos", "coconut flour", "unsweetened shredded coconut",
        "hearts of palm", "coconut extract",
    ])
    def test_coconut_false_friends_pass(self, name):
        assert not _blocked(ingredients=[_ing(name, 30), _ing("chicken breast", 300)])

    def test_light_coconut_milk_passes_and_full_fat_at_base_weight_does_not(self):
        assert not _blocked(ingredients=[_ing("light coconut milk", 200), _ing("chicken breast", 300)])
        assert _blocked(ingredients=[_ing("coconut milk", 200), _ing("chicken breast", 300)])

    def test_a_small_amount_of_full_fat_coconut_milk_passes(self):
        assert not _blocked(ingredients=[_ing("coconut milk", 60), _ing("chicken breast", 300)])


class TestRefinedGrainHardBlock:
    @pytest.mark.parametrize("name", ["white rice", "white bread", "couscous", "flour tortilla"])
    def test_refined_grain_base_is_blocked(self, name):
        assert _blocked(ingredients=[_ing(name, 120), _ing("chicken breast", 300)])

    @pytest.mark.parametrize("name", [
        "whole-wheat couscous", "whole wheat flour tortilla", "brown rice", "pearl barley",
    ])
    def test_whole_grain_versions_pass(self, name):
        assert not _blocked(ingredients=[_ing(name, 120), _ing("chicken breast", 300)])

    def test_a_small_amount_of_a_refined_grain_passes(self):
        # 30 g total < the 50 g base floor → a garnish, not the carbohydrate base.
        assert not _blocked(ingredients=[_ing("white bread", 30), _ing("chicken breast", 300)])


# ---------------------------------------------------------------------------
# The carbohydrate WINDOW — the axis that warns in BOTH directions
# ---------------------------------------------------------------------------

class TestCarbohydrateWindow:
    def test_under_the_floor_warns_and_says_it_is_a_defect(self):
        """A recipe that is impressively low in carbohydrate is a DEFECT in this
        book. The warning text has to say so, because an editor reading the log
        would otherwise read a low number as a success."""
        report = stage_03_diet_check.run_post_nutrition(_make_draft(), _nutrition(carbs_g=12))
        assert report.overall_passed  # soft → warning, not a blocker
        under = [w for w in report.warnings if "UNDER-CARBOHYDRATE" in w]
        assert under, report.warnings
        assert "DEFECT" in under[0]

    def test_over_the_ceiling_warns(self):
        report = stage_03_diet_check.run_post_nutrition(_make_draft(), _nutrition(carbs_g=95))
        assert any("total carbohydrate" in w.lower() and "ceiling" in w.lower()
                   for w in report.warnings)

    def test_inside_the_window_is_silent(self):
        report = stage_03_diet_check.run_post_nutrition(_make_draft(), _nutrition(carbs_g=45))
        assert not any("carbohydrate" in w.lower() for w in report.warnings)

    def test_every_tier_has_both_ends_of_the_window(self):
        s = spec.load_spec()
        for tier, env in s.meal_categories.items():
            assert env.total_carbs_g_floor is not None, f"{tier} has no carbohydrate FLOOR"
            assert env.total_carbs_g_max is not None, f"{tier} has no carbohydrate ceiling"
            assert env.total_carbs_g_floor < env.total_carbs_g_max

    def test_render_envelope_prints_carbohydrate_as_a_window(self):
        line = spec.render_envelope(spec.load_spec().envelope_for_chapter("poultry_meat_dinners"))
        assert "A WINDOW" in line
        assert "defect" in line.lower()

    def test_no_net_carbs_axis_exists(self):
        """Deliberate divergence from the parent engine: the ADA and FDA both count
        TOTAL carbohydrate, and a reader dosing insulin must not be shown a
        subtracted number."""
        env = spec.load_spec().envelope_for_chapter("poultry_meat_dinners")
        assert not hasattr(env, "net_carbs_g_max")
        assert "net carb" not in spec.render_envelope(env).lower()
