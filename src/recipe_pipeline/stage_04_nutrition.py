"""
Stage 4 — Nutrition.

The LLM picks the best-matching USDA FoodData Central food per ingredient (from a
pre-filtered shortlist + the alias cache) and estimates the recipe's added sugar;
this module then does *all* the per-serving arithmetic deterministically —
``value_per_100g × ingredient.quantity_g / 100`` summed across ingredients, then
divided by 2 (every recipe serves 2). A nutrient no USDA food carries for any of
the recipe's ingredients is left ``None`` on the panel (for the optional fields);
the always-present core macros fall back to ``0`` + a warning in the (vanishingly
rare) case nothing supplies them. Trans fat (~31 % USDA coverage) and vitamin D
(~78 %) are expected to be partial — no warning is emitted for those two.
"""
import json

from src.llm import client as llm
from src.llm.output_schemas import NutritionOutput
from src.llm.prompts import nutrition as nutrition_prompts
from src.models.nutrition import NutritionInfo
from src.models.recipe import RecipeDraft
from src.nutrition import qualifiers, usda_loader

SERVINGS = 2
CANDIDATES_PER_INGREDIENT = 8
PARTIAL_WEIGHT_THRESHOLD = 0.10  # warn if ≥10% of recipe weight lacks a (core-ish) nutrient
MAX_NUTRITION_RETRIES = 2  # a long per-ingredient JSON can truncate; retry before failing the recipe

# NutritionInfo field  ←  per-100 g attribute on UsdaFood / the LLM estimate dict
_NUTRIENT_MAP: tuple[tuple[str, str], ...] = (
    ("calories_kcal", "calories_kcal"),
    ("protein_g", "protein_g"),
    ("carbs_g", "carbs_g"),
    ("fat_g", "total_fat_g"),
    ("fiber_g", "fiber_g"),
    ("sodium_mg", "sodium_mg"),
    ("sugar_g", "total_sugar_g"),
    ("saturated_fat_g", "saturated_fat_g"),
    ("cholesterol_mg", "cholesterol_mg"),
    ("potassium_mg", "potassium_mg"),
    ("trans_fat_g", "trans_fat_g"),
    ("mufa_g", "mufa_g"),
    ("pufa_g", "pufa_g"),
    ("calcium_mg", "calcium_mg"),
    ("iron_mg", "iron_mg"),
    ("vitamin_d_mcg", "vitamin_d_mcg"),
)
# always-present core macros — fall back to 0 (never None) on the panel
_CORE_FIELDS = {"calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg", "sugar_g"}
# emit a "partial data" warning for these when ≥PARTIAL_WEIGHT_THRESHOLD of recipe weight lacks the nutrient
_WARN_IF_PARTIAL = _CORE_FIELDS | {"saturated_fat_g", "cholesterol_mg", "potassium_mg", "calcium_mg", "iron_mg"}


def _per100_from_food(food: usda_loader.UsdaFood) -> dict[str, float | None]:
    return {usda_attr: getattr(food, usda_attr) for _, usda_attr in _NUTRIENT_MAP}


def _reject_reason(
    ing, food: usda_loader.UsdaFood, shortlist: list[usda_loader.UsdaFood]
) -> str | None:
    """Why ``food`` must not be used for ``ing``, else None. See src/nutrition/qualifiers.py."""
    return qualifiers.mismatch_reason(
        request_name=f"{ing.name} {ing.canonical_name or ''}",
        request_preparation=getattr(ing, "preparation", None),
        candidate_description=food.description,
        candidate_sodium_mg=food.sodium_mg,
        unsalted_alternative_exists=any(
            qualifiers.salt_polarity(c.description) == "unsalted" for c in shortlist
        ),
    )


def _enforce_qualifiers(
    ing, food: usda_loader.UsdaFood, shortlist: list[usda_loader.UsdaFood]
) -> tuple[usda_loader.UsdaFood, str | None]:
    """Deterministic backstop on the LLM's pick.

    A salt or raw/cooked qualifier changes the per-100 g basis, so a mismatched pick is
    silently wrong rather than approximately right. Substitute the best candidate that does
    satisfy the qualifier; if none does, keep the pick (zeroing the ingredient would be
    worse) and return a warning naming the distortion.
    """
    reason = _reject_reason(ing, food, shortlist)
    if reason is None:
        return food, None

    for cand in shortlist:
        if cand.fdc_id != food.fdc_id and _reject_reason(ing, cand, shortlist) is None:
            return cand, (
                f"'{ing.name}': {reason} — switched from [{food.fdc_id}] {food.description} "
                f"to [{cand.fdc_id}] {cand.description}."
            )

    return food, (
        f"'{ing.name}': {reason}. No candidate in the USDA shortlist satisfies it, so "
        f"[{food.fdc_id}] {food.description} was kept — treat this ingredient's "
        f"contribution as an over-statement."
    )


# A NULL here is summed as zero (see the per-serving compute below), so an otherwise-fine
# match that simply wasn't assayed for fiber silently erases it — USDA records 34.4 g
# fiber/100 g for chia, but the Foundation record for it carries no fiber value at all.
_COMPLETENESS_FIELDS: tuple[str, ...] = ("fiber_g", "protein_g", "calories_kcal")


def _prefer_complete(
    ing, food: usda_loader.UsdaFood, shortlist: list[usda_loader.UsdaFood]
) -> tuple[usda_loader.UsdaFood, str | None]:
    """Swap an incomplete match for an equally valid one that carries the missing nutrient.

    Only considers candidates the qualifier guard already accepts, and takes the first —
    the shortlist is relevance-ranked, so that is the closest complete match.
    """
    missing = [f for f in _COMPLETENESS_FIELDS if getattr(food, f) is None]
    if not missing:
        return food, None

    for cand in shortlist:
        if cand.fdc_id == food.fdc_id:
            continue
        if any(getattr(cand, f) is None for f in missing):
            continue
        if _reject_reason(ing, cand, shortlist) is not None:
            continue
        return cand, (
            f"'{ing.name}': [{food.fdc_id}] {food.description} has no USDA value for "
            f"{', '.join(missing)} (which would be summed as zero) — switched to "
            f"[{cand.fdc_id}] {cand.description}."
        )

    return food, None


def _per100_from_estimate(est) -> dict[str, float | None]:
    """LLM estimates only carry the core 7 (+ optional saturated fat); the rest stay unknown."""
    out: dict[str, float | None] = {usda_attr: None for _, usda_attr in _NUTRIENT_MAP}
    out.update({
        "calories_kcal": est.calories_kcal,
        "protein_g": est.protein_g,
        "carbs_g": est.carbs_g,
        "total_fat_g": est.fat_g,
        "fiber_g": est.fiber_g,
        "total_sugar_g": est.total_sugar_g,
        "sodium_mg": est.sodium_mg,
        "saturated_fat_g": est.saturated_fat_g,
    })
    return out


def _candidates_with_alias(
    canonical_name: str, technique: str, limit: int
) -> tuple[list[usda_loader.UsdaFood], int | None]:
    """Return (candidates, alias_fdc_id). If an alias exists, ensure its row is first so the
    LLM sees the prior pick at the top of the shortlist."""
    alias_id = usda_loader.get_alias(canonical_name)
    cands = usda_loader.lookup_candidates(canonical_name, technique=technique, limit=limit)
    if alias_id is None:
        return cands, None
    already = next((c for c in cands if c.fdc_id == alias_id), None)
    if already is not None:
        cands = [already] + [c for c in cands if c.fdc_id != alias_id]
    else:
        fetched = usda_loader.fetch_by_id(alias_id)
        if fetched is not None:
            cands = [fetched] + cands[: max(0, limit - 1)]
    return cands, alias_id


def run(draft: RecipeDraft, technique: str = "") -> tuple[NutritionInfo, list[str]]:
    """Return (NutritionInfo, warnings) for a 2-serving draft."""
    warnings: list[str] = []
    ings = list(draft.ingredients)

    # 1. Per ingredient: top-N USDA candidates + the alias-cached prior pick (if any).
    ingredients_payload: list[dict] = []
    candidates_by_name: dict[str, list[usda_loader.UsdaFood]] = {}
    alias_ids: list[int | None] = []
    for ing in ings:
        cands, alias_id = _candidates_with_alias(ing.canonical_name, technique, CANDIDATES_PER_INGREDIENT)
        candidates_by_name[ing.canonical_name] = cands
        alias_ids.append(alias_id)
        ingredients_payload.append({
            "name": ing.name,
            "canonical_name": ing.canonical_name,
            "quantity_g": float(ing.quantity_g),
            "quantity_display": ing.quantity_display,
        })

    # 2. LLM call — pick an fdc_id per ingredient (or estimate) + estimate added sugar.
    system = nutrition_prompts.build_system()
    schema_json = json.dumps(NutritionOutput.model_json_schema(), ensure_ascii=False, indent=2)
    user = nutrition_prompts.build_user(
        ingredients=ingredients_payload,
        candidates_by_name=candidates_by_name,
        schema_json=schema_json,
        technique=technique,
        recipe_title=draft.title,
    )
    # A per-ingredient JSON array can get long; give the (thinking) model ample output
    # room and retry on a truncated / malformed response rather than failing the whole recipe.
    output: NutritionOutput | None = None
    last_error: Exception | None = None
    for _attempt in range(MAX_NUTRITION_RETRIES + 1):
        raw = llm.create_message(system, user, max_tokens=8192, thinking_budget=2000)
        try:
            output = NutritionOutput.model_validate_json(raw)
            break
        except Exception as e:  # noqa: BLE001
            last_error = e
    if output is None:
        raise RuntimeError(
            f"Stage 4 LLM response could not be parsed as NutritionOutput after "
            f"{MAX_NUTRITION_RETRIES + 1} attempts: {last_error}"
        ) from last_error

    picks = output.per_ingredient
    if len(picks) != len(ings):
        warnings.append(
            f"Stage 4: LLM returned {len(picks)} ingredient picks for {len(ings)} ingredients — aligning by position."
        )

    # 3. Resolve a per-100 g panel for each ingredient (USDA food or LLM estimate).
    per100_list: list[dict[str, float | None]] = []
    match_sources: list[str] = []  # "alias" | "matcher" | "llm_estimate"
    alias_hits = matcher_hits = 0
    missing_names: list[str] = []
    for idx, ing in enumerate(ings):
        pick = picks[idx] if idx < len(picks) else None
        alias_id = alias_ids[idx]
        fdc_id = pick.fdc_id if pick is not None else None
        food = usda_loader.fetch_by_id(int(fdc_id)) if fdc_id else None
        if food is not None:
            shortlist = candidates_by_name.get(ing.canonical_name, [])
            food, qual_warning = _enforce_qualifiers(ing, food, shortlist)
            if qual_warning:
                warnings.append(f"Stage 4 qualifier: {qual_warning}")
            food, complete_warning = _prefer_complete(ing, food, shortlist)
            if complete_warning:
                warnings.append(f"Stage 4 coverage: {complete_warning}")
        if food is not None:
            per100_list.append(_per100_from_food(food))
            object.__setattr__(ing, "fdc_id", food.fdc_id)
            object.__setattr__(ing, "nutrition_source", "usda")
            usda_loader.register_alias(ing.canonical_name, food.fdc_id)
            if alias_id is not None and food.fdc_id == alias_id:
                object.__setattr__(ing, "match_source", "alias")
                match_sources.append("alias")
                alias_hits += 1
            else:
                object.__setattr__(ing, "match_source", "matcher")
                match_sources.append("matcher")
                matcher_hits += 1
        else:
            est = pick.estimate_per_100g if pick is not None else None
            per100_list.append(
                _per100_from_estimate(est) if est is not None
                else {usda_attr: None for _, usda_attr in _NUTRIENT_MAP}
            )
            object.__setattr__(ing, "fdc_id", None)
            object.__setattr__(ing, "nutrition_source", "llm_estimate")
            object.__setattr__(ing, "match_source", "llm_estimate")
            match_sources.append("llm_estimate")
            missing_names.append(ing.name)
            if pick is not None and est is None and fdc_id:
                warnings.append(f"Stage 4: unknown USDA fdc_id {fdc_id} for '{ing.name}' and no estimate — its nutrients are 0.")
            elif pick is not None and est is None:
                warnings.append(f"Stage 4: no USDA match and no estimate for '{ing.name}' — its nutrients are 0.")
            else:
                warnings.append(f"No USDA candidate for '{ing.name}' — values estimated by the LLM.")

    # 4. Deterministic per-serving compute.
    total_grams = sum(ing.quantity_g for ing in ings) or 1.0
    panel: dict[str, float | None] = {}
    partial = False
    for info_field, usda_attr in _NUTRIENT_MAP:
        contribs: list[float] = []
        missing_grams = 0.0
        for ing, per100 in zip(ings, per100_list):
            v = per100.get(usda_attr)
            if v is None:
                missing_grams += ing.quantity_g
            else:
                contribs.append(v * ing.quantity_g / 100.0)
        if contribs:
            if info_field in _WARN_IF_PARTIAL and missing_grams / total_grams >= PARTIAL_WEIGHT_THRESHOLD:
                warnings.append(
                    f"{info_field}: partial data — {missing_grams / total_grams * 100:.0f}% of recipe weight "
                    "has no USDA value for it."
                )
                partial = True
            panel[info_field] = round(sum(contribs) / SERVINGS, 1)
        elif info_field in _CORE_FIELDS:
            warnings.append(f"{info_field}: no USDA value for any ingredient — set to 0.")
            partial = True
            panel[info_field] = 0.0
        else:
            panel[info_field] = None

    panel["added_sugar_g"] = round(output.added_sugar_g_recipe_total / SERVINGS, 1)

    # 5. Confidence.
    n_null = sum(1 for s in match_sources if s == "llm_estimate")
    if n_null == 0 and not partial:
        confidence = "high"
    elif ings and n_null * 2 > len(ings):
        confidence = "low"
    else:
        confidence = "medium"

    nutrition = NutritionInfo(
        **panel,
        source="llm_usda",
        confidence=confidence,
        missing_ingredients=missing_names,
    )

    # Telemetry attached on the draft so the orchestrator's StageLogEntry can surface it.
    object.__setattr__(draft, "_nutrition", nutrition)
    object.__setattr__(draft, "_nutrition_match_sources", match_sources)
    object.__setattr__(draft, "_nutrition_alias_hits", alias_hits)
    object.__setattr__(draft, "_nutrition_matcher_hits", matcher_hits)
    return nutrition, warnings
