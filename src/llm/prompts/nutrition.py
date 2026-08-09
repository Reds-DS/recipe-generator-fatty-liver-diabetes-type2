"""
Stage 4 — nutrition. The LLM picks the best-matching USDA FoodData Central food
per ingredient (from a pre-filtered shortlist) and estimates the recipe's added
sugar; the application does all the per-serving arithmetic.
"""
from src.nutrition.usda_loader import UsdaFood

SYSTEM = """You are a nutrition expert. You receive a recipe's ingredients (quantities in
grams; the recipe always serves 2) and, for each ingredient, a shortlist of USDA FoodData
Central foods with their per-100 g values.

For each ingredient:
  1. Pick the `fdc_id` of the candidate that best matches the *real* ingredient. Prefer a
     generic single food over a branded product. Two qualifiers are BINDING, because each
     one changes the per-100 g basis and would silently distort the whole panel:

     * COOKING STATE — an ingredient's gram weight is the weight as BOUGHT AND ADDED, not
       the weight it ends up as. If the ingredient is added uncooked (and the pan does the
       cooking), pick the RAW record even though the finished dish is cooked. Pick a cooked
       record only when the ingredient itself is already cooked when measured ("cooked
       quinoa", "shredded rotisserie chicken"). 340 g of raw ground turkey is NOT 340 g of
       browned crumbles — the cooked record is ~40% denser per gram.

     * SALT — if the ingredient says "no-salt-added", "low-sodium", "without salt" or
       "unsalted", you MUST pick a record that says the same. Never substitute a regular or
       salted record, and do not assume an unmarked record is unsalted: many salted USDA
       foods carry no salt word at all. If no candidate is explicitly unsalted, set
       `fdc_id` to null and estimate instead.

  2. ONLY if no candidate is a reasonable match, set `fdc_id` to null and fill
     `estimate_per_100g` with your best per-100 g estimate of the core nutrients.
  3. Set `fdc_description` to the chosen food's description; add a one-clause `note` only
     if the pick was a stretch or you estimated.

Then estimate `added_sugar_g_recipe_total`: the total grams of ADDED sugar in the whole
2-serving recipe — sugar from added sweeteners (table/brown sugar, honey, maple syrup,
agave, molasses, syrups, fruit-juice concentrate used as a sweetener, etc.), NOT the sugar
naturally present in fruit, milk, or vegetables. Use 0 if the recipe has no added sweetener.

Do NOT compute anything else — the application multiplies by the quantities and divides by
the servings. Respond with JSON matching the schema, and nothing else."""


def build_system() -> str:
    return SYSTEM


def _num(v: float | None, fmt: str = ".1f") -> str:
    return "?" if v is None else format(v, fmt)


def _format_candidates(candidates: list[UsdaFood]) -> str:
    if not candidates:
        return "    (no USDA candidate — estimate the values)"
    lines = []
    for c in candidates:
        lines.append(
            f"    - [{c.fdc_id}] ({c.data_type}) {c.description} | "
            f"{_num(c.calories_kcal, '.0f')} kcal, "
            f"P {_num(c.protein_g)}g, C {_num(c.carbs_g)}g, fat {_num(c.total_fat_g)}g, "
            f"fiber {_num(c.fiber_g)}g, sat {_num(c.saturated_fat_g)}g, sugar {_num(c.total_sugar_g)}g"
        )
    return "\n".join(lines)


def build_user(
    ingredients: list[dict],
    candidates_by_name: dict[str, list[UsdaFood]],
    schema_json: str,
    technique: str,
    recipe_title: str = "",
) -> str:
    """Build the Stage 4 user prompt.

    ingredients: [{name, canonical_name, quantity_g, quantity_display}, ...]
    candidates_by_name: {canonical_name: list[UsdaFood]}
    """
    blocks: list[str] = []
    for i, ing in enumerate(ingredients, 1):
        cands = candidates_by_name.get(ing["canonical_name"], [])
        blocks.append(
            f"{i}. {ing['name']} (canonical: {ing['canonical_name']}) — "
            f"{ing['quantity_g']:.1f} g for 2 servings\n"
            f"   USDA candidates (per 100 g):\n"
            f"{_format_candidates(cands)}"
        )

    header = f"RECIPE: {recipe_title}\n\n" if recipe_title else ""
    return (
        f"{header}"
        f"Cooking method: {technique or 'unspecified'}\n\n"
        f"INGREDIENTS AND USDA CANDIDATES:\n\n"
        + "\n\n".join(blocks)
        + "\n\nRESPONSE SCHEMA (strict JSON):\n"
        + schema_json
        + "\n\nRespond only with the JSON. No text before or after."
    )
