"""
Renders a validated Recipe to Markdown, JSON, or plain text.
"""
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from src.models.recipe import Recipe, RecipeLog, StageLogEntry

_NBSP = "&nbsp;&nbsp;"


def to_json(recipe: Recipe) -> str:
    return recipe.model_dump_json(indent=2, exclude_none=False)


def _fmt(value: float | None, unit: str, decimals: int = 1, est: bool = False) -> str:
    """Format a nutrition value for the panel — `—` when unknown, otherwise the rounded
    value + unit (+ `*` if it's an estimate)."""
    if value is None:
        return "—"
    rounded = round(value, decimals)
    if decimals == 0:
        rounded = int(rounded)
    return f"{rounded} {unit}{'*' if est else ''}"


def _nutrition_lines(n) -> list[str]:
    """FDA-Nutrition-Facts-style per-serving panel as a Markdown key/value table."""
    confidence_note = "" if n.confidence == "high" else f" *(confidence: {n.confidence})*"
    good_fats = None
    if n.mufa_g is not None or n.pufa_g is not None:
        good_fats = (n.mufa_g or 0.0) + (n.pufa_g or 0.0)
    potassium_cell = _fmt(n.potassium_mg, "mg", 0) + ("†" if n.potassium_mg is not None else "")

    # PANEL ORDER IS THE BOOK'S THESIS. The HERO SIX lead: Calories, Total
    # Carbohydrate, Dietary Fiber, Added Sugars, Protein, Saturated Fat — three
    # liver levers (calories, added sugars, saturated fat) and three blood-sugar
    # levers (total carbohydrate, fiber, protein). Carbohydrate therefore sits
    # SECOND, not below cholesterol as in the parent engine.
    # NET CARBS IS DELIBERATELY ABSENT — see `nutrition_panel` in the spec. It has
    # no FDA definition, the ADA counts total carbohydrate, and a reader dosing
    # insulin against a subtracted number is a safety problem. Do not "restore" it.
    lines = [
        f"## Nutrition (per serving){confidence_note}",
        "| | |",
        "|---|---|",
        f"| **Calories** | {_fmt(n.calories_kcal, 'kcal', 0)} |",
        f"| **Total carbohydrate** | {_fmt(n.carbs_g, 'g')} |",
        f"| {_NBSP}Dietary fiber | {_fmt(n.fiber_g, 'g')} |",
        f"| {_NBSP}Total sugars | {_fmt(n.sugar_g, 'g')} |",
        f"| {_NBSP}{_NBSP}incl. added sugars | {_fmt(n.added_sugar_g, 'g', est=True)} |",
        f"| **Protein** | {_fmt(n.protein_g, 'g')} |",
        f"| **Total fat** | {_fmt(n.fat_g, 'g')} |",
        f"| {_NBSP}Saturated fat | {_fmt(n.saturated_fat_g, 'g')} |",
        f"| {_NBSP}Trans fat | {_fmt(n.trans_fat_g, 'g')} |",
        f"| {_NBSP}of which good fats (mono + poly) | {_fmt(good_fats, 'g')} |",
        f"| **Sodium** | {_fmt(n.sodium_mg, 'mg', 0)} |",
        f"| **Cholesterol** | {_fmt(n.cholesterol_mg, 'mg', 0)} |",
        f"| **Potassium** | {potassium_cell} |",
        f"| **Calcium** | {_fmt(n.calcium_mg, 'mg', 0)} |",
        f"| **Iron** | {_fmt(n.iron_mg, 'mg', 2)} |",
        f"| **Vitamin D** | {_fmt(n.vitamin_d_mcg, 'mcg', 2)} |",
    ]
    notes: list[str] = ["Count TOTAL carbohydrate — it is what the label and your care team use."]
    if n.added_sugar_g is not None:
        notes.append("*Added sugars are an estimate.")
    if n.potassium_mg is not None:
        notes.append("†Potassium needs may be lower with chronic kidney disease — ask your care team.")
    if n.missing_ingredients:
        notes.append(f"Ingredients without nutrition data: {', '.join(n.missing_ingredients)}.")
    if notes:
        lines.append("")
        for note in notes:
            lines.append(f"> {note}")
    return lines


def _sentence_case(name: str) -> str:
    """Capitalize the first letter only — fixes 'large eggs' -> 'Large eggs' without
    lowercasing proper nouns like 'Greek' or 'Dijon'."""
    s = name.strip()
    return (s[:1].upper() + s[1:]) if s else s


def _passive_detail(passive_time: str) -> str:
    """Render a passive-time phrase ('Chill 30-45 min') as a 'Label time: value' detail line."""
    parts = passive_time.strip().split(None, 1)
    if len(parts) == 2 and parts[0][:1].isalpha():
        return f"- **{parts[0].capitalize()} time:** {parts[1]}"
    return f"- **Hands-off:** {passive_time.strip()}"


def to_markdown(recipe: Recipe) -> str:
    lines: list[str] = []
    n = recipe.nutrition_per_serving

    lines.append(f"# {recipe.title}")
    lines.append("")
    if recipe.image_path:
        lines.append(f"![{recipe.title}]({recipe.image_path})")
        lines.append("")
    lines.append(recipe.intro)
    lines.append("")

    if recipe.cook_time_min == 0 and not recipe.cook_time_max_min:
        cook_time_display = "none (no-cook)"
    elif recipe.cook_time_max_min and recipe.cook_time_max_min != recipe.cook_time_min:
        cook_time_display = f"{recipe.cook_time_min}–{recipe.cook_time_max_min} min"
    else:
        cook_time_display = f"{recipe.cook_time_min} min"

    lines.append("## Details")
    lines.append(f"- **Cook time:** {cook_time_display}")
    lines.append(f"- **Prep time:** {recipe.prep_time_min} min")
    if recipe.passive_time:
        lines.append(_passive_detail(recipe.passive_time))
    lines.append(f"- **Servings:** {recipe.servings}")
    lines.append("")

    lines.append("## Ingredients")
    for ing in recipe.ingredients:
        prep = f", {ing.preparation}" if ing.preparation else ""
        optional = " *(optional)*" if ing.is_optional else ""
        lines.append(f"- {ing.quantity_display} **{_sentence_case(ing.name)}**{prep}{optional}")
    lines.append("")

    lines.append("## Instructions")
    for i, step in enumerate(recipe.instructions, 1):
        lines.append(f"{i}. {step}")
    lines.append("")

    if recipe.variation:
        lines.append("## Variation")
        lines.append(recipe.variation)
        lines.append("")

    if recipe.conservation:
        lines.append("## Storage")
        lines.append(recipe.conservation)
        lines.append("")

    if n:
        lines.extend(_nutrition_lines(n))
        lines.append("")

    if recipe.validation_warnings:
        lines.append("## Warnings")
        for w in recipe.validation_warnings:
            lines.append(f"- {w}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Structured per-recipe log
# ---------------------------------------------------------------------------

def _render_stage(entry: StageLogEntry) -> list[str]:
    """Render a single stage log entry as human-readable lines."""
    lines: list[str] = []
    details = entry.details

    if entry.stage == "ideation":
        lines.append("--- Ideation ---")
        lines.append(f"Title candidate : {details.get('title_candidate', '?')}")
        lines.append(f"Technique       : {details.get('technique', '?')}")
        lines.append(f"Cuisine style   : {details.get('cuisine_style', '?')}")
        lines.append(f"Flavour profile : {details.get('flavour_profile', '?')}")
        sketch = details.get("ingredients_sketch", [])
        if sketch:
            lines.append(f"Sketch          : {', '.join(sketch)}")

    elif entry.stage.startswith("draft_attempt_"):
        attempt_num = entry.stage.split("_")[-1]
        status_label = "Accepted" if entry.status == "ok" else "Rejected"
        lines.append(f"  [Attempt {attempt_num}] {status_label}")
        feedback = details.get("correction_feedback")
        if feedback:
            preview = feedback[:200] + "..." if len(feedback) > 200 else feedback
            lines.append(f"    Feedback: {preview}")
        if entry.warnings:
            for w in entry.warnings:
                lines.append(f"    [WARN] {w}")

    elif entry.stage == "nutrition":
        lines.append("--- Nutrition ---")
        lines.append(f"Source   : {details.get('source', '?')} (confidence {details.get('confidence', '?')})")
        missing = details.get("missing_ingredients", [])
        lines.append(f"Missing  : {', '.join(missing) if missing else 'none'}")
        per_ing = details.get("per_ingredient_source", [])
        if per_ing:
            lines.append("Per-ingredient sources:")
            for item in per_ing:
                lines.append(f"  - {item['name']} : {item['source']}")
        for w in entry.warnings:
            lines.append(f"  [WARN] {w}")

    elif entry.stage == "diet_post_nutrition":
        lines.append("--- Diet check (post-nutrition) ---")
        lines.append(f"Overall status : {'PASS' if details.get('overall_passed') else 'FAIL'}")
        for rule in details.get("rules", []):
            status_icon = "OK" if rule["passed"] else "FAIL"
            lines.append(f"  [{rule['rule_name']}] {status_icon}")
            for v in rule.get("violations", []):
                lines.append(f"    [VIOLATION] {v}")
            for w in rule.get("warnings", []):
                lines.append(f"    [WARN] {w}")

    elif entry.stage == "cooking":
        lines.append("--- Cooking sanity check ---")
        if not entry.corrections and not entry.warnings:
            lines.append("Status : OK — no corrections needed")
        for c in entry.corrections:
            lines.append(f"  [CORRECTION] {c}")
        for w in entry.warnings:
            lines.append(f"  [WARN] {w}")

    elif entry.stage == "formatting":
        lines.append("--- Formatting ---")
        rewritten = details.get("prose_rewritten", False)
        lines.append(f"Prose rewrite : {'OK' if rewritten else 'Fallback (original text kept)'}")

    elif entry.stage == "image_generation":
        lines.append("--- Image generation ---")
        lines.append(f"Status    : {'OK' if entry.status == 'ok' else 'FAILED'}")
        lines.append(f"Attempts  : {details.get('attempts', '?')}")
        if details.get("failure_reason"):
            lines.append(f"Reason    : {details['failure_reason']}")
        prompt = details.get("image_prompt", "")
        if prompt:
            preview = prompt[:200] + "..." if len(prompt) > 200 else prompt
            lines.append(f"Prompt    : {preview}")

    else:
        lines.append(f"--- {entry.stage} ---")
        lines.append(f"Status : {entry.status}")

    return lines


def to_log(recipe: Recipe, rlog: RecipeLog) -> str:
    """Produces a structured human-readable log for a generated recipe."""
    lines: list[str] = []

    lines.append(f"=== RECIPE LOG: {recipe.title} ===")
    lines.append(f"ID            : {recipe.id}")
    lines.append(f"Generation ID : {rlog.generation_id}")
    lines.append(f"Generated     : {recipe.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"LLM model     : {rlog.llm_model or '?'}")
    lines.append(f"Validation    : {'PASS' if recipe.validation_passed else 'FAIL'}")
    lines.append(f"Warnings      : {rlog.total_warnings}")
    lines.append(f"Corrections   : {rlog.total_corrections}")
    lines.append("")

    lines.append("--- Parameters ---")
    lines.append(f"Main ingredient : {rlog.main_ingredient or 'random'}")
    lines.append(f"Meal type       : {rlog.meal_type}")
    lines.append(f"Exclusions      : {', '.join(rlog.exclusions) if rlog.exclusions else 'none'}")
    lines.append("")

    draft_entries = [e for e in rlog.stages if e.stage.startswith("draft_attempt_")]
    other_entries = [e for e in rlog.stages if not e.stage.startswith("draft_attempt_")]

    for entry in other_entries:
        if entry.stage == "ideation":
            lines.extend(_render_stage(entry))
            lines.append("")
            if draft_entries:
                lines.append(f"--- Draft ({len(draft_entries)} attempt(s)) ---")
                for de in draft_entries:
                    lines.extend(_render_stage(de))
                lines.append("")
        else:
            lines.extend(_render_stage(entry))
            lines.append("")

    return "\n".join(lines)


def to_log_json(rlog: RecipeLog) -> str:
    """Produces a machine-readable JSON log."""
    data = asdict(rlog)
    if isinstance(data.get("created_at"), datetime):
        data["created_at"] = data["created_at"].isoformat()
    return json.dumps(data, ensure_ascii=False, indent=2)


def write_log(recipe: Recipe, rlog: RecipeLog, recipe_path: Path, log_dir: Path | None = None) -> Path:
    """
    Writes both a .log (human-readable) and .log.json (machine-readable)
    file. If log_dir is provided, writes there; otherwise alongside the recipe file.
    """
    filename = recipe_path.stem
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{filename}.log"
        json_log_path = log_dir / f"{filename}.log.json"
    else:
        log_path = recipe_path.with_suffix(".log")
        json_log_path = recipe_path.with_suffix(".log.json")

    log_path.write_text(to_log(recipe, rlog), encoding="utf-8")
    json_log_path.write_text(to_log_json(rlog), encoding="utf-8")

    return log_path
