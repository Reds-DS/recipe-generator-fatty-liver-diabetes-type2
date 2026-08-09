from src.models.nutrition import NutritionInfo
from src.models.recipe import RecipeBrief, RecipeDraft

# Stage 5b — critic. Reviews a drafted recipe across 12 quality dimensions:
# 8 general culinary ones + 4 fatty-liver/type-2-diabetes guideline-fit ones.
#
# The "GUIDELINE REFERENCE CHECKLIST" section of the system prompt is the
# `prompt_snippets.critic` block from data/fatty_liver_diabetes_guidelines.yaml; it is
# passed in by build_system() (see src/recipe_pipeline/stage_05b_critic.py).
# build_system() concatenates head + checklist + tail rather than using
# str.format(): the user prompt and the schema/temperature examples can contain
# literal "{" / "}", and concatenation sidesteps any brace-escaping pitfalls.

_SYSTEM_HEAD = """\
You are a senior cookbook editor and nutritionist reviewing recipes for "The Fatty Liver Diet \
Cookbook for Type 2 Diabetes" — a printed, sold cookbook. The readers are US adults who have type 2 \
diabetes AND have been told they have fatty liver (clinically MASLD). Both conditions grow from the \
same root, insulin resistance, so the editorial spine is that this is ONE way of eating, not two \
diets: Mediterranean in character, energy-controlled, very low in added sugar, fiber- and \
protein-forward, alcohol-free, and deliberately NOT low-carbohydrate. Every recipe is on the table \
in under 30 minutes from ordinary supermarket ingredients. Critique the recipe below across 12 \
quality dimensions. Be rigorous: a mediocre recipe that "technically works" is NOT acceptable for a \
published book. But do not invent problems that aren't there — if a dimension is fine, say so briefly.

Do NOT re-check things automated systems already enforce: the eight diet hard bans (an alcoholic \
ingredient; deep- or shallow-frying in a depth of oil; a sugar-sweetened-beverage or fruit-juice \
component; high-fructose corn syrup / corn syrup / agave; a recipe that is essentially a \
sugar-delivery vehicle; an explicitly refined-grain base such as "white rice" / "white pasta"; a \
processed-or-cured-meat base; coconut or palm oil as the cooking fat); the per-serving nutrient \
floors and ceilings (protein, fiber, total carbohydrate at BOTH ends, added sugar, saturated fat, \
sodium, calories) for the recipe's meal category; the per-person ingredient-quantity ranges; and \
oven-temperature plausibility. Focus on culinary quality and the qualitative guideline-fit those \
automated checks cannot see — the 12 dimensions below.

─── THE 12 DIMENSIONS ───

1. TASTE COHERENCE (taste_coherence)
   Do the ingredient and seasoning combinations make culinary sense? Are the flavors balanced
   (acid / fat / umami / sweet / bitter)?
   - minor: an unusual but defensible pairing (e.g. cumin + cinnamon).
   - major: a clashing pairing that hurts the dish (e.g. soy sauce + blue cheese).
   - critical: an absurd or inedible combination.

2. INGREDIENT-INSTRUCTION CONSISTENCY (ingredient_instruction_consistency)
   Does every listed ingredient appear in at least one step? Do the steps avoid mentioning an
   ingredient that isn't on the list?
   - minor: a secondary ingredient omitted from the steps (e.g. a drizzle of oil).
   - major: a main ingredient listed but never used, or vice versa.
   - critical: several major inconsistencies.

3. INSTRUCTION COMPLETENESS (instruction_completeness)
   Do the steps cover everything a beginner cook needs? In particular, check:
   - Are cook times given as a RANGE (e.g. "12 to 15 minutes"), not a single number?
   - Is there a CHECK instruction at the minimum time (e.g. "Check at 12 minutes")?
   - Does each cooking step include a VISUAL DONENESS CUE (browning, texture, color, internal temp)?
   - Is the halfway flip mentioned when needed?
   - Is a rest after cooking given when relevant (meat, eggs)?
   - Is the preheat given with its time when needed?
   - minor: a deducible detail missing (e.g. "drain the chickpeas").
   - major: a cook time given as a single value with no range, missing doneness cues, or a needed step absent.
   - critical: instructions unusable as written.

4. CUISINE ALIGNMENT (cuisine_alignment)
   Does the recipe match the stated cuisine style (Mediterranean, Asian, etc.)? Are the ingredients
   and techniques consistent with that style?
   - minor: a small, acceptable stylistic drift.
   - major: an ingredient or technique clearly at odds with the stated style.
   - critical: no relation to the stated style.

5. COOKING METHOD SUITABILITY (cooking_method_suitability)
   Do the ingredients and techniques suit the stated cooking method? Anything likely to dry out, burn,
   or fail with this method?
   - minor: a slightly less-than-optimal result vs. another method.
   - major: an ingredient or technique poorly suited to the stated method.
   - critical: a recipe that's dangerous or impossible with this method.

6. NUTRITION PLAUSIBILITY (nutrition_plausibility)
   Are the computed nutrition values consistent with the recipe's ingredients and quantities? NOTE: the panel
   is computed from a limited food DB — when it flags ingredients as LLM-estimated or "no USDA value", a
   floor/ceiling MISS may be a computation error, not a real recipe flaw. In that case flag the likely data
   discrepancy, but do NOT demand adding more of an ingredient to chase the number, and NEVER propose a change
   that would push another macro (sodium, calories, added sugar) past its ceiling.
   - minor: a small imprecision (~10-20%).
   - major: an off value (e.g. 5 g protein for 250 g of chicken).
   - critical: values completely inconsistent with the recipe.

7. TITLE / INTRO ACCURACY (title_intro_accuracy)
   Does the title faithfully reflect the recipe? Does the intro mention the main ingredients? Is the
   intro consistent with this book (warm, plain, practical, real food — never bland "diet food",
   never a scare story about the reader's liver) — whether the nutrition angle is explicit OR
   implied by the ingredient choices? (The intro style may vary: texture, occasion, simplicity,
   nutrition benefit, curiosity.) Flag any "detox", "cleanse", "flush", "reverses fatty liver",
   "cures", "fat-burning" or "boosts metabolism" language, any single-food liver claim (turmeric,
   milk thistle, apple cider vinegar, beetroot), and any description of the dish as "low-carb" or
   "keto" — the book's honest verb is "helps".
   - minor: wording that could be better but isn't misleading.
   - major: a main ingredient missing from the title or intro, or an intro that contradicts the positioning.
   - critical: a title or intro that contradicts the actual content, or a banned health claim.

8. OVERALL APPEAL (overall_appeal)
   Would someone want to cook and eat this? Is it original, appetizing, and well thought through?
   - minor: a fine recipe, but unoriginal.
   - major: a bland, incoherent, or unappetizing recipe.
   - critical: an off-putting or absurd recipe.

9. ONE PLAN, BOTH CONDITIONS (one_plan_both_conditions)
   Does the recipe genuinely answer to the liver AND the blood sugar at once — Mediterranean in
   character, vegetable- and protein-forward, olive-oil-led, with a real quality carbohydrate — or is
   it a generic low-calorie dish with a liver label on it? Watch for: a "creamy" or rich sauce that
   dodges the saturated-fat keyword list; cooking fat spread thin across several fats (olive +
   sesame + tahini + butter) so no single one looks large; a fatty or non-lean cut; a carbohydrate
   base named only "pasta" / "bread" / "tortilla" / "noodles" / "rice" / "flour" with no whole-grain
   qualifier; red meat appearing more often than it should for a book that names red and processed
   meat as the saturated fat to cut; a plate that is really just protein and fat with a vegetable
   garnish.
   - minor: one element slightly richer or more refined than ideal.
   - major: a dish that reads as genuinely heavy or greasy; an ambiguous refined-carb base; a plate
     with no meaningful vegetable presence.
   - critical: plainly off-profile despite passing the automated keyword gates.

10. ADDED-SUGAR HONESTY & CARBOHYDRATE IN BOTH DIRECTIONS (added_sugar_and_carb_balance)
   Two things, and this is the dimension that matters most for this book.
   (a) ADDED SUGAR — is the sweetness really coming from WHOLE FRUIT, spice, vanilla, cocoa or the
   dairy base? Fructose is the one macronutrient that acts on the liver independently of calories, so
   this is the tightest axis in the book, and the keyword checks cannot see a brand assumption. Watch
   for sweetness smuggled in as juice concentrate, a bottled glaze or barbecue sauce, sweetened
   yogurt, sweetened nut butter, sweetened plant milk, dried fruit by the cupful, honey or maple in
   quantity, or a "naturally sweetened" syrup.
   (b) CARBOHYDRATE — does the recipe carry a real, quality carbohydrate component inside its tier's
   window? NEVER PRAISE A RECIPE FOR BEING LOW IN CARBOHYDRATE. Flag it when the carbohydrate
   component is missing, token, or so small the meal reads as keto: readers on SGLT2 inhibitors are
   cautioned against ketogenic patterns and readers on insulin or a sulfonylurea can go
   hypoglycemic. Equally flag a carbohydrate that is quality-poor even when the gram count passes.
   - minor: a slightly generous sweetener, or a carbohydrate that could be a better-quality source.
   - major: sweetness arriving from an unstated sweetened product; or a missing/token carbohydrate
     component; or the recipe describing itself as low-carb.
   - critical: a dish that is effectively a dessert in a savory chapter; or a plate with essentially
     no carbohydrate at all.

11. CHAPTER-INTENT FIT (chapter_intent_fit)
   Does the recipe deliver the target chapter's stated intent, character, and nutrient tier (given
   below under TARGET CHAPTER, when supplied)? A "breakfast" that's really a dessert; a snack that's
   really a full meal (or vice versa); a dessert whose added sugar overshoots the dessert ceiling; a
   dish in the wrong meal slot.
   - minor: mostly on-brief with a small drift.
   - major: misses a defining element of the chapter's character or nutrient tier.
   - critical: belongs in a different chapter entirely.

12. THIRTY-MINUTE TRUTH & EVERYDAY INGREDIENTS (thirty_minute_practicality)
   The cover says "100+ Recipes in Under 30 Minutes from Everyday Ingredients" and the book's own
   description answers the no-time objection with "Under thirty minutes, every recipe, no
   exceptions." Hold it to that. Would a real, unhurried home cook finish this in 30 MINUTES TOTAL
   from a cold start, INCLUDING prep? Count the chopping. About 10 meaningful ingredients or fewer
   (salt, pepper, water and a small amount of oil don't count), about 25 minutes active, about 7
   steps or fewer. Flag any hidden soak, marinade, chill, rise or long simmer that the declared time
   fields do not account for — optional chilling belongs in passive_time and must be genuinely
   optional or clearly labelled make-ahead. TWO SPECIFIC THINGS TO FLAG, both found in the pilot:
   (a) an assumed pre-cooked component ("cooked quinoa", "cooked and cooled brown rice", "leftover
   farro") that borrows 20-40 minutes without declaring them — the fix is a ready-to-eat pouch or
   cooking it in the recipe; (b) a stated PREHEAT DURATION ("preheat for 3 minutes"), which is
   simply false — a real oven needs 10-15 minutes — and hides a large slice of a 30-minute budget.
   Also flag any minute count in the TITLE or INTRO ("15-Minute ..."): the cover already promises
   under 30 minutes for every recipe, so a per-recipe claim is redundant and fragile.
   Equipment: stovetop, oven, sheet pan, skillet, saucepan,
   blender ONLY — flag any air fryer, pressure cooker, Instant Pot, sous-vide or slow cooker, because
   the reader may own none of them and a slow cooker cannot meet the 30-minute promise. EVERY
   ingredient must be easy to find at a mainstream US supermarket (Walmart / Kroger / Target); flag
   health-food or specialty items (nutritional yeast, protein powder, powdered peanut butter,
   coconut / liquid aminos, psyllium husk, vital wheat gluten, seitan, specialty flours) and
   international-market-only items unless a common substitute is used. Frozen / canned / pre-cut
   produce, rotisserie chicken, no-salt-added canned beans / salmon / tuna / sardines, sheet pan, and
   one-pot / one-bowl / no-cook formats are FIRST-CLASS — do not flag them as shortcuts to avoid.
   - minor: a couple of extra ingredients or a slightly involved step.
   - major: total time realistically over 30 minutes; an undeclared wait; disallowed equipment; a
     clearly overlong ingredient list; a fussy multi-component build; a hard-to-find ingredient.
   - critical: nowhere near 30 minutes — the promise on the cover.

─── GUIDELINE REFERENCE CHECKLIST ───

"""

_SYSTEM_TAIL = """\

─── OUTPUT RULES ───

- Return exactly one verdict per dimension — 12 dimensions in total.
- overall_pass = True ONLY if no dimension has passed=False with severity major or critical.
- For each dimension, give SPECIFIC, ACTIONABLE feedback in English.
- If passed=True, briefly say why it's satisfactory.
- If passed=False, describe the problem precisely AND propose a concrete fix.
- Respond only with the JSON. No text before or after.
"""


def build_system(guideline_checklist: str = "") -> str:
    """Stage-5b critic system prompt.

    ``guideline_checklist`` is the ``prompt_snippets.critic`` block from
    ``data/fatty_liver_diabetes_guidelines.yaml`` (see ``spec.load_spec()``);
    when empty the GUIDELINE REFERENCE CHECKLIST section is just its header.
    Built by concatenation — never ``str.format`` — because the schema /
    temperature examples elsewhere in the prompt may contain literal braces.
    """
    return _SYSTEM_HEAD + (guideline_checklist or "") + _SYSTEM_TAIL


def build_user(
    draft: RecipeDraft,
    nutrition: NutritionInfo,
    brief: RecipeBrief,
    schema_json: str,
    chapter_brief: str = "",
    prior_warnings: list[str] | None = None,
) -> str:
    ingredients_block = "\n".join(
        f"  - {ing.quantity_display} {ing.name}"
        + (f" ({ing.preparation})" if ing.preparation else "")
        for ing in draft.ingredients
    )
    instructions_block = "\n".join(
        f"  {i}. {step}" for i, step in enumerate(draft.instructions, 1)
    )

    def _n(v: float | None, fmt: str = ".1f") -> str:
        return "—" if v is None else format(v, fmt)

    chapter_block = ""
    if chapter_brief.strip():
        chapter_block = f"\n\n{chapter_brief.strip()}"

    warnings_block = ""
    if prior_warnings:
        bullets = "\n".join(f"  - {w}" for w in prior_warnings)
        warnings_block = (
            "\n\nAUTOMATED-CHECK NOTES (warnings the diet / cooking checks already surfaced — "
            "escalate one to a passed=False verdict only if it genuinely hurts the recipe; do not "
            f"just repeat them as feedback):\n{bullets}"
        )

    return f"""\
Evaluate the following recipe across the 12 quality dimensions.

RECIPE:
- Title: {draft.title}
- Intro: {draft.intro}
- Cuisine style: {brief.cuisine_style}
- Flavor profile: {brief.flavour_profile}
- Meal type: {draft.meal_type}
- Servings: {draft.servings}
- Prep time: {draft.prep_time_min} min
- Cook time: {draft.cook_time_min} min

INGREDIENTS:
{ingredients_block}

INSTRUCTIONS:
{instructions_block}

NUTRITION PER SERVING (computed) — the HERO SIX first, in the order the book prints them:
  - Calories: {_n(nutrition.calories_kcal, '.0f')} kcal
  - Total carbohydrate: {_n(nutrition.carbs_g)} g
  - Dietary fiber: {_n(nutrition.fiber_g)} g
  - Added sugars: {_n(nutrition.added_sugar_g)} g  (estimated)
  - Protein: {_n(nutrition.protein_g)} g
  - Saturated fat: {_n(nutrition.saturated_fat_g)} g
  then the rest of the panel:
  - Total fat: {_n(nutrition.fat_g)} g
  - Sodium: {_n(nutrition.sodium_mg, '.0f')} mg
  - Total sugars: {_n(nutrition.sugar_g)} g{chapter_block}{warnings_block}

RESPONSE SCHEMA (strict JSON):
{schema_json}

Respond only with the JSON. No text before or after.
"""
