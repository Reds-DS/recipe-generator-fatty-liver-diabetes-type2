"""
Pipeline orchestrator — wires all stages together.
"""
from pathlib import Path

from rich.console import Console

from src.config import settings
from src.cooking.quantity_checker import build_correction_prompt as build_quantity_correction
from src.cooking.quantity_checker import check_quantities
from src.dedup.checker import (
    check_cross_meal_diversity,
    check_diversity,
    check_same_meal_diversity,
    get_existing_summary,
)

# Meal types with a narrow ingredient vocabulary that benefit from stricter,
# meal-type-scoped diversity (same-ingredient, same-format rejection).
STRICT_DIVERSITY_MEAL_TYPES = {"dessert"}
from src.models.recipe import Recipe, RecipeBrief, RecipeLog, StageLogEntry
from src.recipe_pipeline import (
    stage_01_ideation,
    stage_02_draft,
    stage_03_diet_check,
    stage_04_nutrition,
    stage_05_cooking,
    stage_05b_critic,
    stage_06_format,
    stage_07_image,
)
from src.recipe_pipeline.stage_07_image import ImageResult

console = Console()
MAX_CORRECTION_LOOPS = 2
MAX_CRITIC_LOOPS = 2  # original + 2 retries = 3 total critic attempts
MAX_DIVERSITY_RETRIES = 3


def ideate_only(
    *,
    main_ingredient: str | None = None,
    cuisine_hint: str | None = None,
    exclusions: list[str] | None = None,
    meal_type: str = "dinner",
    chapter: str = "poultry_meat_dinners",
    dedup_db_path: Path | None = None,
) -> tuple[RecipeBrief, int]:
    """Run Stage 1 ideation with diversity-aware retry loop. Returns (brief, attempts_used)."""
    existing_summary = get_existing_summary(db_path=dedup_db_path, meal_type=meal_type)
    strict = meal_type in STRICT_DIVERSITY_MEAL_TYPES

    def _build_diversity_context(extra: str = "") -> str:
        block = existing_summary.to_prompt_block() + existing_summary.to_cross_meal_block()
        if strict:
            block += existing_summary.to_same_meal_block()
        return block + extra

    diversity_context = _build_diversity_context()

    brief: RecipeBrief | None = None
    diversity_attempt = 0
    for diversity_attempt in range(1, MAX_DIVERSITY_RETRIES + 1):
        with console.status(f"[bold cyan]Step 1/6 — Ideation (attempt {diversity_attempt})..."):
            try:
                brief = stage_01_ideation.run(
                    main_ingredient=main_ingredient,
                    cuisine_hint=cuisine_hint,
                    exclusions=exclusions,
                    meal_type=meal_type,
                    chapter=chapter,
                    diversity_context=diversity_context,
                )
            except (ValueError, Exception) as e:
                console.print(f"[yellow]⚠ Parsing error (attempt {diversity_attempt}): {e}[/yellow]")
                if diversity_attempt < MAX_DIVERSITY_RETRIES:
                    diversity_context = _build_diversity_context(
                        "\n\nPREVIOUS ATTEMPT FAILED (technical error). Try again."
                    )
                    continue
                raise

        div_result = check_diversity(brief.main_ingredient, brief.ingredients_sketch, db_path=dedup_db_path)
        if div_result.is_diverse:
            cross_result = check_cross_meal_diversity(
                brief.main_ingredient, brief.ingredients_sketch, meal_type, db_path=dedup_db_path,
            )
            if cross_result.is_diverse:
                if strict:
                    same_result = check_same_meal_diversity(
                        brief.main_ingredient,
                        brief.ingredients_sketch,
                        brief.technique,
                        meal_type,
                        db_path=dedup_db_path,
                    )
                    if same_result.is_diverse:
                        break
                    div_result = same_result
                else:
                    break
            else:
                div_result = cross_result
        console.print(f"[yellow]⚠ Not diverse enough (attempt {diversity_attempt}): {div_result.reason}[/yellow]")
        if diversity_attempt < MAX_DIVERSITY_RETRIES:
            diversity_context = _build_diversity_context(
                f"\n\nPREVIOUS ATTEMPT REJECTED: {div_result.reason}"
            )

    assert brief is not None
    console.print(f"[green]✓[/green] Idea: [bold]{brief.title_candidate}[/bold]")
    return brief, diversity_attempt


def generate_from_brief(
    brief: RecipeBrief,
    *,
    exclusions: list[str] | None = None,
    meal_type: str = "dinner",
    main_ingredient: str | None = None,
    generate_image: bool = True,
    diversity_attempts: int = 0,
    ideation_source: str = "pre-reviewed",
) -> tuple[Recipe, RecipeLog, ImageResult | None]:
    """Run Stages 2–7 from an already-accepted brief.

    Used by both the live `generate()` path (after `ideate_only`) and the
    review-resume path (where briefs were ideated in a prior session).
    """
    rlog = RecipeLog(
        main_ingredient=main_ingredient or brief.main_ingredient,
        meal_type=meal_type,
        chapter=brief.chapter,
        exclusions=exclusions or [],
    )
    rlog.stages.append(StageLogEntry(
        stage="ideation",
        status="ok",
        details={
            "title_candidate": brief.title_candidate,
            "main_ingredient": brief.main_ingredient,
            "technique": brief.technique,
            "flavour_profile": brief.flavour_profile,
            "cuisine_style": brief.cuisine_style,
            "ingredients_sketch": brief.ingredients_sketch,
            "diversity_attempts": diversity_attempts,
            "source": ideation_source,
        },
    ))

    # ── Outer critic loop (Stage 2 → 5b) ──────────────────────
    critic_feedback = ""
    critic_passed = True
    all_warnings: list[str] = []
    corrections: list[str] = []
    draft = None
    nutrition = None
    post_report = None

    for critic_attempt in range(MAX_CRITIC_LOOPS + 1):

        # Stage 2 + 3a inner correction loop
        correction_feedback = critic_feedback  # critic feedback seeds first draft
        draft = None
        draft_log_entries: list[StageLogEntry] = []

        for loop in range(MAX_CORRECTION_LOOPS + 1):
            # Stage 2 — Draft generation
            with console.status(f"[bold cyan]Step 2 — Drafting the recipe (attempt {loop+1})..."):
                draft = stage_02_draft.run(brief, correction_feedback=correction_feedback)

            # Stage 2b — Quantity plausibility check (blocking, before expensive stages).
            # Bounds are keyed on the recipe's nutrient tier (derived from draft.chapter).
            qty_result = check_quantities(draft)

            # Stage 3a — Diet validation (Layer 1 only, pre-nutrition)
            pre_report = stage_03_diet_check.run_pre_nutrition(draft)

            attempt_entry = StageLogEntry(
                stage=f"draft_attempt_{loop+1}",
                status="ok",
                details={
                    "correction_feedback": correction_feedback or None,
                    "quantity_check_passed": qty_result.passed,
                    "pre_diet_check_passed": pre_report.overall_passed,
                    "critic_attempt": critic_attempt + 1,
                },
            )

            if not qty_result.passed:
                attempt_entry.status = "failed"
                attempt_entry.warnings.extend(qty_result.warnings)
            if not pre_report.overall_passed:
                attempt_entry.status = "failed"
                attempt_entry.warnings.extend(pre_report.blocking_violations)

            draft_log_entries.append(attempt_entry)

            if qty_result.passed and pre_report.overall_passed:
                break
            if loop == MAX_CORRECTION_LOOPS:
                failure_lines: list[str] = []
                if not qty_result.passed:
                    failure_lines.append("Invalid quantities:")
                    failure_lines.extend(qty_result.warnings)
                if not pre_report.overall_passed:
                    failure_lines.append("Diet violations:")
                    failure_lines.extend(pre_report.blocking_violations)
                raise RuntimeError(
                    f"Failed: the recipe doesn't meet the constraints after "
                    f"{MAX_CORRECTION_LOOPS + 1} attempts.\n"
                    + "\n".join(failure_lines)
                )

            feedback_parts: list[str] = []
            if not qty_result.passed:
                console.print(
                    f"[yellow]⚠[/yellow] Wrong quantities (attempt {loop+1}). Correcting..."
                )
                feedback_parts.append(build_quantity_correction(qty_result))
            if not pre_report.overall_passed:
                console.print(
                    f"[yellow]⚠[/yellow] Diet violations detected (attempt {loop+1}). Correcting..."
                )
                feedback_parts.append(stage_03_diet_check.build_correction_prompt(pre_report))
            correction_feedback = "\n\n".join(feedback_parts)

        assert draft is not None
        rlog.draft_attempts = len(draft_log_entries)
        rlog.stages.extend(draft_log_entries)

        # Stage 4 — Nutrition (the LLM picks USDA foods; Python computes the panel)
        with console.status("[bold cyan]Step 4 — Nutrition (USDA via LLM)..."):
            nutrition, nutrition_warnings = stage_04_nutrition.run(draft, technique=brief.technique)

        console.print(
            f"[green]✓[/green] Nutrition ({nutrition.source}, {nutrition.confidence}) — "
            f"{nutrition.calories_kcal:.0f} kcal/serving"
        )
        for w in nutrition_warnings:
            console.print(f"[yellow]  ⚠ {w}[/yellow]")

        total_ings = len(draft.ingredients) or 1
        alias_hits = getattr(draft, "_nutrition_alias_hits", 0)
        matcher_hits = getattr(draft, "_nutrition_matcher_hits", 0)
        match_sources = getattr(draft, "_nutrition_match_sources", [])
        rlog.stages.append(StageLogEntry(
            stage="nutrition",
            status="ok" if nutrition.confidence != "low" else "warning",
            warnings=nutrition_warnings,
            details={
                "source": nutrition.source,
                "confidence": nutrition.confidence,
                "missing_ingredients": nutrition.missing_ingredients,
                "nutrition": nutrition.model_dump(),
                "alias_hits": alias_hits,
                "matcher_hits": matcher_hits,
                "food_db_hit_rate": round((alias_hits + matcher_hits) / total_ings, 3),
                "alias_hit_rate": round(alias_hits / total_ings, 3),
                "match_sources": match_sources,
            },
        ))

        # Stage 3b — Full diet validation (hard blocks + per-tier nutrient targets, post-nutrition)
        with console.status("[bold cyan]Step 3 — Full diet validation..."):
            post_report = stage_03_diet_check.run_post_nutrition(draft, nutrition)

        all_warnings = list(nutrition_warnings)
        all_warnings.extend(post_report.warnings)

        if not post_report.overall_passed:
            console.print("[yellow]⚠ Post-nutrition diet violations:[/yellow]")
            for v in post_report.blocking_violations:
                console.print(f"  [red]✗[/red] {v}")
            all_warnings.extend(post_report.blocking_violations)

        diet_details: dict = {
            "overall_passed": post_report.overall_passed,
            "rules": [],
        }
        for rr in post_report.rule_results:
            diet_details["rules"].append({
                "rule_name": rr.rule_name,
                "passed": rr.passed,
                "violations": rr.violations,
                "warnings": rr.warnings,
            })
        rlog.stages.append(StageLogEntry(
            stage="diet_post_nutrition",
            status="ok" if post_report.overall_passed else "warning",
            warnings=post_report.warnings + post_report.blocking_violations,
            details=diet_details,
        ))

        # Stage 5 — Cooking sanity check
        with console.status("[bold cyan]Step 5 — Cooking sanity check..."):
            draft, cooking_warnings, corrections = stage_05_cooking.run(draft)

        all_warnings.extend(cooking_warnings)
        for c in corrections:
            console.print(f"[yellow]  ⚠ Correction: {c}[/yellow]")

        cooking_status = "ok"
        if corrections:
            cooking_status = "corrected"
        elif cooking_warnings:
            cooking_status = "warning"
        rlog.stages.append(StageLogEntry(
            stage="cooking",
            status=cooking_status,
            warnings=list(cooking_warnings),
            corrections=list(corrections),
        ))

        # Stage 5b — Critic (LLM quality review). Feed it the target-chapter brief and
        # the soft Stage-3b / Stage-5 warnings so it can judge chapter fit and decide
        # whether a soft miss warrants a re-draft.
        with console.status("[bold cyan]Step 5b — Quality critique..."):
            critic_result = stage_05b_critic.run(
                draft, nutrition, brief,
                chapter=brief.chapter,
                prior_warnings=[*post_report.warnings, *cooking_warnings],
            )

        critic_log_details: dict = {"summary": ""}
        if critic_result.raw_output:
            critic_log_details = {
                "summary": critic_result.raw_output.summary,
                "dimensions": [
                    {
                        "dimension": d.dimension,
                        "passed": d.passed,
                        "severity": d.severity,
                        "feedback": d.feedback,
                    }
                    for d in critic_result.raw_output.dimensions
                ],
            }

        rlog.stages.append(StageLogEntry(
            stage=f"critic_attempt_{critic_attempt + 1}",
            status="ok" if critic_result.passed else "failed",
            warnings=critic_result.warnings,
            details=critic_log_details,
        ))

        if critic_result.passed:
            if critic_result.warnings:
                for w in critic_result.warnings:
                    console.print(f"[yellow]  ⚠ Critic (minor): {w}[/yellow]")
                all_warnings.extend(critic_result.warnings)
            console.print("[green]✓[/green] Quality critique passed")
            critic_passed = True
            break

        # Critic rejected — retry or proceed with warnings
        if critic_attempt == MAX_CRITIC_LOOPS:
            console.print(
                "[yellow]⚠ The critic flagged unresolved problems. "
                "Recipe kept with warnings.[/yellow]"
            )
            all_warnings.extend(critic_result.blocking_feedback)
            all_warnings.extend(critic_result.warnings)
            critic_passed = False
            break

        console.print(
            f"[yellow]⚠ Critic not satisfied (attempt {critic_attempt + 1}). "
            f"Regenerating...[/yellow]"
        )
        for fb in critic_result.blocking_feedback:
            console.print(f"  [red]✗[/red] {fb}")
        critic_feedback = stage_05b_critic.build_correction_prompt(critic_result)

    assert draft is not None
    assert nutrition is not None
    assert post_report is not None
    rlog.critic_attempts = critic_attempt + 1  # type: ignore[possibly-undefined]

    # ── Stage 6 — Final formatting ────────────────────────────
    with console.status("[bold cyan]Step 6 — Final formatting..."):
        recipe = stage_06_format.run(draft, nutrition)

    # Detect if prose rewrite was applied (intro changed from draft)
    prose_rewritten = recipe.intro != draft.intro
    rlog.stages.append(StageLogEntry(
        stage="formatting",
        status="ok",
        details={"prose_rewritten": prose_rewritten},
    ))

    recipe = recipe.model_copy(
        update={
            "validation_passed": post_report.overall_passed and critic_passed,
            "validation_warnings": all_warnings,
        }
    )

    # ── Stage 7 — Image generation (optional) ────────────────
    image_result: ImageResult | None = None
    if generate_image and settings.image_generation_enabled:
        with console.status("[bold cyan]Step 7 — Image generation..."):
            image_result = stage_07_image.run(recipe)

        if image_result.success:
            console.print(f"[green]✓[/green] Image generated ({image_result.attempts} attempt(s))")
        else:
            console.print(f"[yellow]⚠ Image generation failed: {image_result.failure_reason}[/yellow]")

        rlog.stages.append(StageLogEntry(
            stage="image_generation",
            status="ok" if image_result.success else "failed",
            details={
                "attempts": image_result.attempts,
                "image_prompt": image_result.image_prompt,
                "failure_reason": image_result.failure_reason,
            },
        ))

    # Finalize log
    rlog.recipe_title = recipe.title
    rlog.recipe_id = recipe.id
    rlog.generation_id = recipe.generation_id
    rlog.llm_model = draft.llm_model
    rlog.created_at = recipe.created_at
    rlog.validation_passed = recipe.validation_passed
    rlog.total_warnings = len(all_warnings)
    rlog.total_corrections = len(corrections)

    console.print(f"\n[bold green]✓ Recipe generated: {recipe.title}[/bold green]")
    return recipe, rlog, image_result


def generate(
    main_ingredient: str | None = None,
    cuisine_hint: str | None = None,
    exclusions: list[str] | None = None,
    meal_type: str = "dinner",
    chapter: str = "poultry_meat_dinners",
    dedup_db_path: Path | None = None,
    generate_image: bool = True,
) -> tuple[Recipe, RecipeLog, ImageResult | None]:
    brief, diversity_attempts = ideate_only(
        main_ingredient=main_ingredient,
        cuisine_hint=cuisine_hint,
        exclusions=exclusions,
        meal_type=meal_type,
        chapter=chapter,
        dedup_db_path=dedup_db_path,
    )
    return generate_from_brief(
        brief,
        exclusions=exclusions,
        meal_type=meal_type,
        main_ingredient=main_ingredient,
        generate_image=generate_image,
        diversity_attempts=diversity_attempts,
        ideation_source="live",
    )
