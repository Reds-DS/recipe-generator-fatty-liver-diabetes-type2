"""
The Fatty Liver Diet Cookbook for Type 2 Diabetes — recipe generator CLI entry point
Usage: docker compose run app [COMMAND] [OPTIONS]
"""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from src.constants import (
    MEAL_TYPE_DEFAULT_CHAPTER as _MEAL_TYPE_DEFAULT_CHAPTER,
)
from src.constants import (
    MEAL_TYPE_FOLDERS,
)
from src.constants import (
    RECIPE_CHAPTER_MEAL_TYPES as _CHAPTER_MEAL_TYPES,
)
from src.constants import (
    RECIPE_CHAPTERS as _RECIPE_CHAPTERS,
)
from src.constants import (
    VALID_MEAL_TYPES as _VALID_MEAL_TYPES,
)

app = typer.Typer(
    help="Recipe generator for 'The Fatty Liver Diet Cookbook for Type 2 Diabetes'."
)
console = Console()


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write `content` to `path` atomically: tmp file + os.replace."""
    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _parse_distribution(distribution: str) -> list[tuple[str, str]]:
    """Parse a distribution string like '20 breakfasts, 15 lunch, 10 snack, 18 dinner'
    (preferred — book-chapter slugs) or the meal-type form '2 breakfast, 3 lunch'.

    Each token is either a book-chapter slug or a planner meal-type key. Returns a flat list of
    (meal_type, chapter) pairs.
    """
    pairs: list[tuple[str, str]] = []
    for part in distribution.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if len(tokens) != 2:
            raise typer.BadParameter(
                f"Invalid format: '{part}'. Expected 'N category' "
                f"(e.g. '20 breakfasts' or '3 lunch')."
            )
        count_str, key = tokens
        try:
            count = int(count_str)
        except ValueError:
            raise typer.BadParameter(f"'{count_str}' is not a valid number in '{part}'.")
        if key in _RECIPE_CHAPTERS:
            mt, ch = _CHAPTER_MEAL_TYPES[key][0], key
        elif key in _VALID_MEAL_TYPES:
            mt, ch = key, _MEAL_TYPE_DEFAULT_CHAPTER[key]
        else:
            raise typer.BadParameter(
                f"'{key}' is neither a known chapter ({', '.join(_RECIPE_CHAPTERS)}) "
                f"nor a meal type ({', '.join(sorted(_VALID_MEAL_TYPES))})."
            )
        pairs.extend([(mt, ch)] * count)
    return pairs


def _save_realtime_output(
    *,
    recipe,
    rlog,
    image_result,
    meal_type: str,
    book_dir: Path,
    dedup_db_path: Path,
    output: str,
    save: bool,
    label: str = "",
) -> bool:
    """Run dedup check, render, save files, and register. Returns False if duplicate."""
    from src.dedup import checker as dedup
    from src.output import formatter

    dedup_result = dedup.check(recipe, db_path=dedup_db_path)
    if dedup_result.is_duplicate:
        console.print(f"[bold red]{label}Duplicate detected:[/bold red] {dedup_result.reason}")
        return False
    if dedup_result.reason:
        console.print(f"[yellow]⚠ {dedup_result.reason}[/yellow]")

    rendered = formatter.to_json(recipe) if output == "json" else formatter.to_markdown(recipe)
    console.print("\n" + rendered)

    if not save:
        return True

    filename = recipe.title.lower().replace(" ", "_").replace("/", "-")[:60]
    folder_name = MEAL_TYPE_FOLDERS[meal_type]

    if image_result and image_result.image_bytes:
        img_dir = book_dir / folder_name / "IMG"
        img_dir.mkdir(parents=True, exist_ok=True)
        img_path = img_dir / f"{filename}.png"
        img_path.write_bytes(image_result.image_bytes)
        recipe = recipe.model_copy(update={"image_path": str(img_path)})
        status = "[green]✓[/green]" if image_result.success else "[yellow]⚠[/yellow]"
        console.print(f"{status} Image saved: {img_path}")

    md_dir = book_dir / folder_name / "Md"
    json_dir = book_dir / folder_name / "JSON"
    log_dir = book_dir / folder_name / "LOG"
    md_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    md_path = md_dir / f"{filename}.md"
    md_path.write_text(formatter.to_markdown(recipe), encoding="utf-8")
    json_path = json_dir / f"{filename}.json"
    json_path.write_text(formatter.to_json(recipe), encoding="utf-8")
    console.print(f"[green]✓ Saved: {md_path}[/green]")
    console.print(f"[green]✓ Saved: {json_path}[/green]")
    log_path = formatter.write_log(recipe, rlog, md_path, log_dir=log_dir)

    if recipe.validation_warnings:
        console.print(
            f"[yellow]⚠ Log written: {log_path} "
            f"({len(recipe.validation_warnings)} warning(s))[/yellow]"
        )
    else:
        console.print(f"[dim]Log written: {log_path}[/dim]")

    ideation_details = {}
    for stage in rlog.stages:
        if stage.stage == "ideation":
            ideation_details = stage.details
            break
    dedup.register(
        recipe,
        main_ingredient=ideation_details.get("main_ingredient", ""),
        cuisine_style=ideation_details.get("cuisine_style", ""),
        ingredients_sketch=ideation_details.get("ingredients_sketch", []),
        meal_type=rlog.meal_type,
        technique=ideation_details.get("technique", ""),
        db_path=dedup_db_path,
    )
    return True


def _generate_one(
    *,
    main_ingredient: str | None,
    cuisine: str | None,
    exclusions: list[str],
    meal_type: str,
    chapter: str = "poultry_meat_dinners",
    output: str,
    save: bool,
    book_name: str = "default",
    recipe_num: int | None = None,
    total: int | None = None,
    generate_image: bool = True,
) -> bool:
    """Generate a single recipe. Returns True on success, False on failure."""
    from src.config import GENERATED_DIR
    from src.recipe_pipeline import orchestrator

    label = f"[{recipe_num}/{total}] " if recipe_num and total else ""

    book_dir = GENERATED_DIR / book_name
    book_dir.mkdir(parents=True, exist_ok=True)
    dedup_db_path = book_dir / "dedup.db"

    try:
        recipe, rlog, image_result = orchestrator.generate(
            main_ingredient=main_ingredient,
            cuisine_hint=cuisine,
            exclusions=exclusions,
            meal_type=meal_type,
            chapter=chapter,
            dedup_db_path=dedup_db_path,
            generate_image=generate_image,
        )
    except RuntimeError as e:
        console.print(f"[bold red]{label}Error:[/bold red] {e}")
        return False

    return _save_realtime_output(
        recipe=recipe,
        rlog=rlog,
        image_result=image_result,
        meal_type=meal_type,
        book_dir=book_dir,
        dedup_db_path=dedup_db_path,
        output=output,
        save=save,
        label=label,
    )


@app.command()
def generate(
    main_ingredient: Annotated[str | None, typer.Option("--main-ingredient", "-i", help="Main ingredient")] = None,
    cuisine: Annotated[str | None, typer.Option("--cuisine", "-c", help="Desired cuisine style")] = None,
    exclude: Annotated[str | None, typer.Option("--exclude", "-e", help="Ingredients to exclude, comma-separated")] = None,
    output: Annotated[str, typer.Option("--output", "-o", help="Format: markdown, json, text")] = "markdown",
    save: Annotated[bool, typer.Option("--save/--no-save", help="Save to data/generated_recipes/")] = True,
    chapter: Annotated[str | None, typer.Option(
        "--chapter",
        help="Book chapter / recipe category: breakfasts, soups_salads, lunches, "
             "poultry_meat_dinners, fish_seafood_dinners, vegetable_meatless_dinners, "
             "snacks_sides, desserts "
             "(default: inferred from --meal-type, else poultry_meat_dinners).",
    )] = None,
    meal_type: Annotated[str | None, typer.Option(
        "--meal-type", "-m",
        help="Meal-plan slot (default: inferred from the chapter): "
             "breakfast, lunch, snack, dinner, dessert",
    )] = None,
    count: Annotated[int, typer.Option("--count", "-n", help="Number of recipes to generate")] = 1,
    distribution: Annotated[str | None, typer.Option(
        "--distribution", "-d",
        help="Distribution: '20 breakfasts, 15 lunch, 10 snack, 18 dinner' "
             "(chapter slugs or meal-type keys)",
    )] = None,
    book: Annotated[str, typer.Option(
        "--book", "-b",
        help="Book name (folder under data/generated_recipes/). Diversity is scoped to the book."
    )] = "default",
    no_image: Annotated[bool, typer.Option(
        "--no-image",
        help="Disable image generation for the recipe."
    )] = False,
    review: Annotated[bool, typer.Option(
        "--review",
        help="Pause after ideation: write a review file, then exit. "
             "Resume with: generate-resume <run_id>."
    )] = False,
) -> None:
    """Generate one or more recipes (always for 2 people) for a book chapter.

    Examples:
      generate                                     # 1 chicken/turkey/lean-meat dinner
      generate --count 5 --chapter breakfasts      # 5 breakfasts
      generate --chapter snacks_sides
      generate -d "16 breakfasts, 14 soups_salads, 14 lunches, 13 poultry_meat_dinners, \\
                   11 fish_seafood_dinners, 10 vegetable_meatless_dinners, \\
                   12 snacks_sides, 10 desserts"   # the full 100-recipe book (from EMPTY)
    """
    exclusions = [e.strip() for e in exclude.split(",")] if exclude else []

    # Build the (meal_type, chapter) list to generate
    if distribution:
        pairs = _parse_distribution(distribution)
    else:
        if meal_type is not None and meal_type not in _VALID_MEAL_TYPES:
            console.print(
                f"[bold red]Error:[/bold red] --meal-type '{meal_type}' is invalid. "
                f"Accepted values: {', '.join(sorted(_VALID_MEAL_TYPES))}"
            )
            raise typer.Exit(1)
        # Resolve the (chapter, meal_type) pair. Explicit --chapter wins; otherwise infer the
        # chapter from --meal-type; otherwise fall back to a quick & easy dinner (so bare
        # `generate` works, and `--meal-type breakfast` ⇒ a breakfast chapter).
        if chapter is None:
            ch = _MEAL_TYPE_DEFAULT_CHAPTER[meal_type] if meal_type is not None else "poultry_meat_dinners"
        else:
            ch = chapter
        if ch not in _RECIPE_CHAPTERS:
            console.print(
                f"[bold red]Error:[/bold red] --chapter '{ch}' is invalid. "
                f"Accepted values: {', '.join(_RECIPE_CHAPTERS)}"
            )
            raise typer.Exit(1)
        mt = meal_type if meal_type is not None else _CHAPTER_MEAL_TYPES[ch][0]
        pairs = [(mt, ch)] * count

    total = len(pairs)
    if total == 0:
        console.print("[yellow]Nothing to generate (empty distribution).[/yellow]")
        return

    if total > 1:
        from collections import Counter
        dist = Counter(ch for _mt, ch in pairs)
        summary = ", ".join(f"{v} {k}" for k, v in sorted(dist.items()))
        console.print(f"\n[bold cyan]Generating {total} recipes: {summary}[/bold cyan]\n")

    # ── Real-time + review : run only ideation, then pause ──
    if review:
        from src.config import BATCH_STATE_DIR, GENERATED_DIR
        from src.recipe_pipeline import orchestrator
        from src.recipe_pipeline import review as review_mod
        from src.recipe_pipeline.batch_state import BatchRunState, RecipeSlot

        book_dir = GENERATED_DIR / book
        book_dir.mkdir(parents=True, exist_ok=True)
        dedup_db_path = book_dir / "dedup.db"

        slots: list[RecipeSlot] = []
        for i, (mt, ch) in enumerate(pairs):
            console.print(f"\n[bold cyan]Ideation {i+1}/{total} — {ch} ({mt})[/bold cyan]")
            try:
                brief, attempts = orchestrator.ideate_only(
                    main_ingredient=main_ingredient,
                    cuisine_hint=cuisine,
                    exclusions=exclusions,
                    meal_type=mt,
                    chapter=ch,
                    dedup_db_path=dedup_db_path,
                )
                slots.append(RecipeSlot(
                    index=i,
                    meal_type=mt,
                    chapter=ch,
                    main_ingredient=main_ingredient,
                    cuisine_hint=cuisine,
                    brief_json=brief.model_dump_json(),
                    status="stage2",
                    diversity_attempts=attempts,
                ))
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]✗ Ideation failed for {ch}: {e}[/red]")
                slots.append(RecipeSlot(
                    index=i, meal_type=mt, chapter=ch,
                    main_ingredient=main_ingredient, cuisine_hint=cuisine,
                    status="failed", error=str(e),
                ))

        state = BatchRunState(
            book_name=book,
            exclusions=exclusions,
            generate_image=not no_image,
            pause_after_ideation=True,
            current_wave="review_pending",
            slots=slots,
        )
        state.save(BATCH_STATE_DIR)
        review_path = review_mod.write_review_file(state, BATCH_STATE_DIR)
        console.print(f"\n[bold cyan]Review file: {review_path}[/bold cyan]")
        console.print(
            f"[dim]Uncheck the recipes to reject, then:[/dim] "
            f"docker compose run app generate-resume {state.run_id}"
        )
        return

    # ── Real-time mode (default) ──────────────────────
    success = 0
    failed = 0

    for i, (mt, ch) in enumerate(pairs, 1):
        if total > 1:
            console.print(f"\n[bold]{'═' * 60}[/bold]")
            console.print(f"[bold cyan]Recipe {i}/{total} — {ch} ({mt})[/bold cyan]")
            console.print(f"[bold]{'═' * 60}[/bold]")

        ok = _generate_one(
            main_ingredient=main_ingredient,
            cuisine=cuisine,
            exclusions=exclusions,
            meal_type=mt,
            chapter=ch,
            output=output,
            save=save,
            book_name=book,
            recipe_num=i if total > 1 else None,
            total=total if total > 1 else None,
            generate_image=not no_image,
        )
        if ok:
            success += 1
        else:
            failed += 1

    if total > 1:
        console.print(f"\n[bold]{'═' * 60}[/bold]")
        console.print(
            f"[bold green]✓ {success} recipe(s) generated[/bold green]"
            + (f" [bold red]| {failed} failure(s)[/bold red]" if failed else "")
        )


@app.command("build-nutrition-db")
def build_nutrition_db() -> None:
    """Build the local SQLite food DB (data/usda.db) from the USDA FoodData Central CSV bundle."""
    from src.config import USDA_SOURCE_DIR
    from src.nutrition.usda_loader import build_db

    if not (USDA_SOURCE_DIR / "food.csv").exists() or not (USDA_SOURCE_DIR / "food_nutrient.csv").exists():
        console.print(
            "[bold red]Error:[/bold red] USDA FoodData Central CSV files not found in "
            f"{USDA_SOURCE_DIR}.\n"
            "Download the 'Full Download' CSV bundle from "
            "https://fdc.nal.usda.gov/download-datasets and unzip it under usda_source_data/ "
            "(so that usda_source_data/FoodData_Central_csv_<date>/food.csv exists)."
        )
        raise typer.Exit(1)

    console.print(f"[dim]USDA source: {USDA_SOURCE_DIR}[/dim]")
    with console.status("Building the USDA food database (streaming the CSVs)…"):
        build_db()
    console.print("[green]✓ USDA food database ready.[/green]")


@app.command("nutrition-lookup")
def nutrition_lookup(
    ingredient: Annotated[str, typer.Argument(help="Ingredient name (English)")],
    technique: Annotated[str, typer.Option(help="Cooking technique: oven, grill, pan_fry, steamed, boiled, poached")] = "",
) -> None:
    """Show the best-matching USDA food for an ingredient (per-100 g panel + fdc_id)."""
    from src.nutrition import usda_loader

    candidates = usda_loader.lookup_candidates(ingredient, technique=technique, limit=1)
    if not candidates:
        console.print(f"[red]No USDA match found for '{ingredient}'.[/red]")
        return
    c = candidates[0]

    def _v(x: float | None, unit: str, dec: int = 1) -> str:
        return "—" if x is None else f"{round(x, dec)} {unit}"

    t = Table(title=f"USDA [{c.fdc_id}] {c.description} ({c.data_type}) — per 100 g")
    t.add_column("Nutrient")
    t.add_column("Value", justify="right")
    t.add_row("Calories", _v(c.calories_kcal, "kcal", 0))
    t.add_row("Protein", _v(c.protein_g, "g"))
    t.add_row("Total carbohydrate", _v(c.carbs_g, "g"))
    t.add_row("  Dietary fiber", _v(c.fiber_g, "g"))
    t.add_row("  Total sugars", _v(c.total_sugar_g, "g"))
    t.add_row("Total fat", _v(c.total_fat_g, "g"))
    t.add_row("  Saturated fat", _v(c.saturated_fat_g, "g"))
    t.add_row("  Trans fat", _v(c.trans_fat_g, "g"))
    t.add_row("  Monounsaturated", _v(c.mufa_g, "g"))
    t.add_row("  Polyunsaturated", _v(c.pufa_g, "g"))
    t.add_row("Cholesterol", _v(c.cholesterol_mg, "mg", 0))
    t.add_row("Sodium", _v(c.sodium_mg, "mg", 0))
    t.add_row("Potassium", _v(c.potassium_mg, "mg", 0))
    t.add_row("Calcium", _v(c.calcium_mg, "mg", 0))
    t.add_row("Iron", _v(c.iron_mg, "mg", 2))
    t.add_row("Vitamin D", _v(c.vitamin_d_mcg, "mcg", 2))
    console.print(t)


@app.command("usda-lookup")
def usda_lookup(
    ingredient: Annotated[str, typer.Argument(help="Ingredient name to search in USDA FoodData Central")],
    technique: Annotated[str, typer.Option("--technique", "-t", help="Cooking technique: oven, grill, pan_fry, steamed, boiled, poached")] = "",
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max candidates to show")] = 8,
) -> None:
    """Debug the Stage-4 matcher: show the search tokens and the ranked USDA candidate list."""
    from src.nutrition import usda_loader

    tokens = usda_loader._tokens(ingredient)
    console.print(f"[dim]Input:[/dim] {ingredient}")
    console.print(f"[dim]Search tokens:[/dim] {tokens}")
    console.print(f"[dim]Technique:[/dim] {technique or '(none)'}\n")

    candidates = usda_loader.lookup_candidates(ingredient, technique=technique, limit=limit)
    if not candidates:
        console.print("[red]No candidates.[/red]")
        return

    t = Table(title=f"USDA candidates ({len(candidates)})")
    t.add_column("fdc_id", style="cyan")
    t.add_column("type")
    t.add_column("description")
    t.add_column("kcal", justify="right")
    t.add_column("P", justify="right")
    t.add_column("C", justify="right")
    t.add_column("fat", justify="right")
    t.add_column("fiber", justify="right")

    def _f(x: float | None, dec: int = 1) -> str:
        return "—" if x is None else f"{round(x, dec)}"

    for c in candidates:
        t.add_row(
            str(c.fdc_id), c.data_type.replace("_food", ""), c.description,
            _f(c.calories_kcal, 0), _f(c.protein_g), _f(c.carbs_g), _f(c.total_fat_g), _f(c.fiber_g),
        )
    console.print(t)


@app.command("validate-recipe")
def validate_recipe(
    file: Annotated[Path, typer.Argument(help="Path to a recipe JSON file")]
) -> None:
    """Validate an existing recipe (JSON file) without regenerating it."""
    from src.models.recipe import RecipeDraft
    from src.recipe_pipeline import stage_03_diet_check, stage_04_nutrition, stage_05_cooking

    if not file.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    draft = RecipeDraft.model_validate_json(file.read_text(encoding="utf-8"))

    with console.status("Computing nutrition..."):
        nutrition, warnings = stage_04_nutrition.run(draft)
    for w in warnings:
        console.print(f"[yellow]⚠ {w}[/yellow]")

    report = stage_03_diet_check.run_post_nutrition(draft, nutrition)
    draft, cooking_warnings, corrections = stage_05_cooking.run(draft)

    console.print(f"\n[bold]Diet check:[/bold] {'✓ VALID' if report.overall_passed else '✗ INVALID'}")
    for v in report.blocking_violations:
        console.print(f"  [red]✗[/red] {v}")
    for w in report.warnings + cooking_warnings:
        console.print(f"  [yellow]⚠[/yellow] {w}")
    for c in corrections:
        console.print(f"  [cyan]→[/cyan] {c}")

    console.print("\n[bold]Nutrition per serving:[/bold]")
    console.print(
        f"  {nutrition.calories_kcal} kcal | protein {nutrition.protein_g} g | "
        f"carbs {nutrition.carbs_g} g | fat {nutrition.fat_g} g | "
        f"fiber {nutrition.fiber_g} g | sodium {nutrition.sodium_mg} mg"
    )
    console.print(f"  Source: {nutrition.source} (confidence: {nutrition.confidence})")


@app.command("create-book")
def create_book(
    name: Annotated[str, typer.Argument(help="Book name (folder to create)")],
) -> None:
    """Create the folder structure for a new recipe book."""
    from src.config import GENERATED_DIR

    book_dir = GENERATED_DIR / name
    if book_dir.exists():
        console.print(f"[yellow]⚠ The folder '{name}' already exists.[/yellow]")
        raise typer.Exit(1)

    for folder in MEAL_TYPE_FOLDERS.values():
        for sub in ("JSON", "Md", "LOG", "IMG"):
            (book_dir / folder / sub).mkdir(parents=True, exist_ok=True)
    (book_dir / "Export").mkdir(parents=True, exist_ok=True)

    console.print(f"[green]✓ Book created: {book_dir}[/green]")
    for folder in MEAL_TYPE_FOLDERS.values():
        console.print(f"  📁 {folder}/  (JSON/, Md/, LOG/, IMG/)")
    console.print("  📁 Export/")


@app.command("recompute-nutrition")
def recompute_nutrition(
    source: Annotated[str, typer.Argument(help="Source book (folder in data/generated_recipes/)")],
    dest: Annotated[str, typer.Argument(help="Destination book (created, or overwritten with --force)")],
    force: Annotated[bool, typer.Option("--force", help="Overwrite the destination book if it exists.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Compute without writing any files.")] = False,
    technique: Annotated[str, typer.Option("--technique", "-t", help="Cooking technique (passed to the USDA candidate search).")] = "",
    all_recipes: Annotated[bool, typer.Option(
        "--all",
        help="Recompute every recipe, including ones already on the current Stage 4 "
             "source. Use after rebuilding data/usda.db.",
    )] = False,
) -> None:
    """Copy a book and recompute its nutrition values via the current Stage 4.

    Replaces only `nutrition_per_serving` and `validation_warnings` in each JSON,
    rewrites `image_path` to point at the new book, and re-renders the .md. Images,
    logs, dedup.db, and all other fields are kept as-is.
    """
    import shutil
    from collections import Counter

    from src.config import GENERATED_DIR
    from src.models.recipe import Recipe, RecipeDraft
    from src.output import formatter
    from src.recipe_pipeline import stage_04_nutrition

    src_dir = GENERATED_DIR / source
    dst_dir = GENERATED_DIR / dest

    if not src_dir.exists():
        console.print(f"[bold red]Error:[/bold red] source book '{source}' not found.")
        raise typer.Exit(1)

    if dst_dir.exists() and not force and not dry_run:
        console.print(
            f"[bold red]Error:[/bold red] '{dest}' already exists. "
            "Use --force to overwrite, or --dry-run to simulate."
        )
        raise typer.Exit(1)

    # 1. Recursive copy. If the destination already exists (resume with --force),
    # do NOT re-copy from the source — that would overwrite the already-recomputed
    # JSON with the original values. Operate in place.
    if dry_run:
        console.print("[dim]-- dry-run: no copy --[/dim]")
    elif dst_dir.exists():
        console.print(f"[cyan]📁 Resuming in place: {dst_dir}[/cyan]")
    else:
        shutil.copytree(src_dir, dst_dir)
        console.print(f"[cyan]📁 Copied: {src_dir} → {dst_dir}[/cyan]")

    # 2. Collect the JSON files to process.
    target_dir = dst_dir if not dry_run else src_dir
    json_files: list[tuple[str, Path]] = []  # (meal_folder, json_path)
    for meal_folder in MEAL_TYPE_FOLDERS.values():
        json_dir = target_dir / meal_folder / "JSON"
        if not json_dir.exists():
            continue
        for p in sorted(json_dir.glob("*.json")):
            json_files.append((meal_folder, p))

    total = len(json_files)
    if total == 0:
        console.print("[yellow]No recipes to process.[/yellow]")
        return

    console.print(f"[bold cyan]{total} recipes to recompute[/bold cyan]\n")

    # 3. Main loop.
    failures: list[tuple[Path, str]] = []
    confidence_counts: Counter = Counter()
    total_ingredients = 0
    total_db_hits = 0
    total_alias_hits = 0
    total_matcher_hits = 0

    skipped_already_done = 0
    for idx, (meal_folder, json_path) in enumerate(json_files, 1):
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            draft = RecipeDraft.model_validate(raw)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red][{idx}/{total}] ✗ {json_path.name} — parse failed: {e}[/red]")
            failures.append((json_path, f"parse: {e}"))
            continue

        # Idempotence: if the recipe is already on "llm_usda", skip it. This guards the
        # one-time migration off an older source — it does NOT know whether usda.db has
        # been rebuilt since, so --all is required to re-derive against a new database.
        existing_source = (raw.get("nutrition_per_serving") or {}).get("source")
        if existing_source == "llm_usda" and not all_recipes:
            skipped_already_done += 1
            console.print(f"[dim][{idx}/{total}] ⊘ {draft.title} — already recomputed[/dim]")
            continue

        try:
            nutrition, warnings = stage_04_nutrition.run(draft, technique=technique)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red][{idx}/{total}] ✗ {draft.title} — Stage 4 failed: {e}[/red]")
            failures.append((json_path, f"stage4: {e}"))
            continue

        alias_hits = getattr(draft, "_nutrition_alias_hits", 0)
        matcher_hits = getattr(draft, "_nutrition_matcher_hits", 0)
        db_hits = alias_hits + matcher_hits
        ing_count = len(draft.ingredients) or 1
        confidence_counts[nutrition.confidence] += 1
        total_ingredients += ing_count
        total_db_hits += db_hits
        total_alias_hits += alias_hits
        total_matcher_hits += matcher_hits

        console.print(
            f"[{idx}/{total}] [green]✓[/green] {draft.title} — "
            f"{nutrition.confidence} ({db_hits}/{ing_count} USDA, "
            f"{alias_hits} alias)"
        )

        if dry_run:
            continue

        # 4. Update the JSON.
        raw["nutrition_per_serving"] = nutrition.model_dump()
        raw["validation_warnings"] = list(warnings)  # replace with the Stage 4 warnings
        if raw.get("image_path") and source in raw["image_path"]:
            raw["image_path"] = raw["image_path"].replace(source, dest, 1)
        json_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 5. Re-render the markdown.
        try:
            recipe = Recipe.model_validate(raw)
            md_dir = target_dir / meal_folder / "Md"
            md_dir.mkdir(parents=True, exist_ok=True)
            md_path = md_dir / f"{json_path.stem}.md"
            md_path.write_text(formatter.to_markdown(recipe), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            console.print(f"[yellow]  ⚠ markdown re-render failed: {e}[/yellow]")

    # 6. Summary.
    console.print(f"\n[bold]{'═' * 60}[/bold]")
    processed = total - len(failures) - skipped_already_done
    console.print(
        f"[bold]Done — {processed} recomputed, "
        f"{skipped_already_done} already done, {len(failures)} failures (of {total})[/bold]"
    )
    console.print(
        f"  Confidence: "
        f"[green]high {confidence_counts['high']}[/green]  "
        f"[yellow]medium {confidence_counts['medium']}[/yellow]  "
        f"[red]low {confidence_counts['low']}[/red]"
    )
    if total_ingredients:
        console.print(
            f"  USDA hits: {total_db_hits}/{total_ingredients} "
            f"({100 * total_db_hits / total_ingredients:.1f}%) — "
            f"{total_alias_hits} via alias, {total_matcher_hits} via matcher"
        )
    if failures:
        console.print(f"\n[red]Failures ({len(failures)}):[/red]")
        for p, reason in failures:
            console.print(f"  • {p.name} — {reason}")


@app.command("export-book")
def export_book(
    name: Annotated[str, typer.Argument(help="Name of the book to export")],
    host_data_path: Annotated[str, typer.Option("--host-data-path", help="Windows path to the data/ folder (for image paths)")] = "",
) -> None:
    """Export all recipes of a book to a CSV file (tab-delimited, UTF-16)."""
    from src.config import GENERATED_DIR
    from src.output.csv_export import build_indesign_txt

    book_dir = GENERATED_DIR / name
    if not book_dir.exists():
        console.print(f"[bold red]Error:[/bold red] folder '{name}' not found in {GENERATED_DIR}")
        raise typer.Exit(1)

    source_dirs = [book_dir / folder / "Md" for folder in MEAL_TYPE_FOLDERS.values()]
    output_dir = book_dir / "Export"

    count = build_indesign_txt(source_dirs, output_dir, host_base_path=host_data_path)
    if count == 0:
        console.print("[yellow]No .md recipes found in the book.[/yellow]")
    else:
        console.print(f"[green]✓ Export created in {output_dir}/ ({count} recipes)[/green]")


@app.command("export-recipes-pdf")
def export_recipes_pdf(
    book: Annotated[str, typer.Option("--book", "-b", help="Book name")],
    meal_type: Annotated[str | None, typer.Option("--meal-type", "-m", help="Meal type to export (e.g. dessert). Omitted = all.")] = None,
    title: Annotated[str | None, typer.Option("--title", "-t", help="Displayed book name (default: folder name).")] = None,
) -> None:
    """Export a book's recipes (or one meal type) to a professional PDF."""
    from src.config import GENERATED_DIR
    from src.constants import MEAL_TYPE_LABELS
    from src.planning import recipe_loader

    book_dir = GENERATED_DIR / book
    if not book_dir.exists():
        console.print(f"[bold red]Error:[/bold red] book not found: {book_dir}")
        raise typer.Exit(1)

    console.print(f"[cyan]Loading recipes from {book_dir}...[/cyan]")
    recipes_by_meal = recipe_loader.load_cookbook(book_dir)

    if meal_type:
        if meal_type not in _VALID_MEAL_TYPES:
            console.print(
                f"[bold red]Error:[/bold red] --meal-type '{meal_type}' is invalid. "
                f"Accepted values: {', '.join(sorted(_VALID_MEAL_TYPES))}"
            )
            raise typer.Exit(1)
        recipes = sorted(recipes_by_meal.get(meal_type, []), key=lambda r: r.title)
        section_title = MEAL_TYPE_LABELS.get(meal_type, meal_type).title() + "s"
        filename = f"{meal_type}_recipes.pdf"
    else:
        recipes = sorted(
            [r for lst in recipes_by_meal.values() for r in lst],
            key=lambda r: r.title,
        )
        section_title = "All recipes"
        filename = "all_recipes.pdf"

    if not recipes:
        console.print("[yellow]No recipes found.[/yellow]")
        raise typer.Exit(1)

    console.print(f"[cyan]{len(recipes)} recipes to export...[/cyan]")

    try:
        from src.output.pdf import render_recipe_book_pdf
    except ImportError as e:
        console.print(
            f"[bold red]Error:[/bold red] WeasyPrint is not installed ({e}). "
            f"Rebuild the Docker image to enable PDF output."
        )
        raise typer.Exit(1)

    with console.status("[bold cyan]Generating the PDF..."):
        pdf_bytes = render_recipe_book_pdf(
            recipes=recipes,
            book_dir=book_dir,
            section_title=section_title,
            book_name=title or book,
        )

    out_dir = book_dir / "Export"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    out_path.write_bytes(pdf_bytes)
    console.print(f"[green]✓ PDF exported: {out_path} ({len(recipes)} recipes)[/green]")


@app.command("batch-status")
def batch_status(
    run_id: Annotated[str | None, typer.Argument(help="Batch ID (optional; lists all if omitted)")] = None,
) -> None:
    """Show a batch's status, or list all batches."""
    from src.config import BATCH_STATE_DIR
    from src.recipe_pipeline.batch_state import BatchRunState

    if run_id is None:
        runs = BatchRunState.list_runs(BATCH_STATE_DIR)
        if not runs:
            console.print("[dim]No batches found.[/dim]")
            return
        t = Table(title="Generation batches")
        t.add_column("Run ID", style="cyan")
        t.add_column("Book")
        t.add_column("Wave")
        t.add_column("Total", justify="right")
        t.add_column("Done", justify="right", style="green")
        t.add_column("Failed", justify="right", style="red")
        t.add_column("Skipped", justify="right", style="dim")
        t.add_column("In progress", justify="right", style="yellow")
        for r in runs:
            t.add_row(
                r["run_id"][:12] + "...",
                r["book_name"],
                r["current_wave"],
                str(r["total"]),
                str(r["done"]),
                str(r["failed"]),
                str(r.get("skipped", 0)),
                str(r["in_progress"]),
            )
        console.print(t)
        return

    try:
        state = BatchRunState.load(BATCH_STATE_DIR, run_id)
    except FileNotFoundError:
        console.print(f"[red]Batch {run_id} not found.[/red]")
        raise typer.Exit(1)

    t = Table(title=f"Batch {state.run_id}")
    t.add_column("#", style="dim")
    t.add_column("Meal")
    t.add_column("Status")
    t.add_column("Attempts D/C/I")
    t.add_column("Error")

    for slot in state.slots:
        status_icon = {
            "done": "[green]✓[/green]",
            "failed": "[red]✗[/red]",
            "skipped": "[dim]⊘ skipped[/dim]",
        }.get(slot.status, f"[yellow]{slot.status}[/yellow]")
        t.add_row(
            str(slot.index),
            slot.meal_type,
            status_icon,
            f"{slot.diversity_attempts}/{slot.correction_attempts}/{slot.image_attempts}",
            slot.error or "",
        )
    console.print(t)
    console.print(f"Current wave: [cyan]{state.current_wave}[/cyan]")


def _resume_realtime(state, book_dir: Path, dedup_db_path: Path, output: str, save: bool) -> None:
    """Resume a real-time run after review: draft + save kept slots."""
    from src.config import BATCH_STATE_DIR
    from src.models.recipe import RecipeBrief
    from src.recipe_pipeline import orchestrator

    pending = [s for s in state.slots if s.status == "stage2" and s.brief_json]
    total = len(pending)
    success = 0
    failed = 0

    for i, slot in enumerate(pending, 1):
        console.print(f"\n[bold]{'═' * 60}[/bold]")
        console.print(f"[bold cyan]Recipe {i}/{total} — {slot.chapter} ({slot.meal_type})[/bold cyan]")
        console.print(f"[bold]{'═' * 60}[/bold]")

        brief = RecipeBrief.model_validate_json(slot.brief_json)
        try:
            recipe, rlog, image_result = orchestrator.generate_from_brief(
                brief,
                exclusions=state.exclusions,
                meal_type=slot.meal_type,
                main_ingredient=slot.main_ingredient,
                generate_image=state.generate_image,
                diversity_attempts=slot.diversity_attempts,
                ideation_source="reviewed",
            )
        except RuntimeError as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            slot.status = "failed"
            slot.error = str(e)
            state.save(BATCH_STATE_DIR)
            failed += 1
            continue

        ok = _save_realtime_output(
            recipe=recipe,
            rlog=rlog,
            image_result=image_result,
            meal_type=slot.meal_type,
            book_dir=book_dir,
            dedup_db_path=dedup_db_path,
            output=output,
            save=save,
            label=f"[{i}/{total}] ",
        )
        if ok:
            slot.status = "done"
            success += 1
        else:
            slot.status = "failed"
            failed += 1
        state.save(BATCH_STATE_DIR)

    state.current_wave = "completed"
    state.save(BATCH_STATE_DIR)

    console.print(f"\n[bold]{'═' * 60}[/bold]")
    console.print(
        f"[bold green]✓ {success} recipe(s) generated[/bold green]"
        + (f" [bold red]| {failed} failure(s)[/bold red]" if failed else "")
    )


@app.command("generate-resume")
def generate_resume(
    run_id: Annotated[str, typer.Argument(help="ID of the run to resume")],
    output: Annotated[str, typer.Option("--output", "-o", help="Format: markdown, json")] = "markdown",
    save: Annotated[bool, typer.Option("--save/--no-save", help="Save to data/generated_recipes/")] = True,
) -> None:
    """Resume a run after reviewing the ideations (--review).

    Reads `data/batch_state/{run_id}_review.md`, applies the choices (unchecked lines →
    skipped recipes), then generates the kept recipes.
    """
    from src.config import BATCH_STATE_DIR, GENERATED_DIR
    from src.recipe_pipeline import review as review_mod
    from src.recipe_pipeline.batch_state import BatchRunState

    try:
        state = BatchRunState.load(BATCH_STATE_DIR, run_id)
    except FileNotFoundError:
        console.print(f"[red]Run {run_id} not found.[/red]")
        raise typer.Exit(1)

    book_dir = GENERATED_DIR / state.book_name
    book_dir.mkdir(parents=True, exist_ok=True)
    dedup_db_path = book_dir / "dedup.db"

    if state.pause_after_ideation and not state.review_applied:
        review_path = BATCH_STATE_DIR / f"{run_id}_review.md"
        if not review_path.exists():
            console.print(f"[red]Review file not found: {review_path}[/red]")
            raise typer.Exit(1)
        decisions = review_mod.parse_review_file(review_path)
        kept, skipped = review_mod.apply_review_decisions(state, decisions)
        state.save(BATCH_STATE_DIR)
        console.print(f"[cyan]Review applied: {kept} kept, {skipped} rejected[/cyan]")
        if kept == 0:
            console.print("[yellow]No recipes kept. Stopping.[/yellow]")
            return

    _resume_realtime(state, book_dir, dedup_db_path, output, save)


@app.command("init-manifest")
def init_manifest(
    book: Annotated[str, typer.Option("--book", "-b", help="Book name (folder under data/generated_recipes/)")],
    objective: Annotated[str | None, typer.Option("--objective", help="Book objective (free text)")] = None,
    daily_kcal: Annotated[int | None, typer.Option("--daily-kcal", help="Daily kcal target for the plan")] = None,
    force: Annotated[bool, typer.Option("--force/--no-force", help="Overwrite an existing manifest")] = False,
) -> None:
    """Create the cookbook.json file in the book's folder."""
    from src.config import GENERATED_DIR
    from src.planning import manifest as manifest_mod

    book_dir = GENERATED_DIR / book
    if not book_dir.exists():
        console.print(f"[bold red]Error:[/bold red] book not found: {book_dir}")
        raise typer.Exit(1)

    path = manifest_mod.manifest_path(book_dir)
    if path.exists() and not force:
        console.print(
            f"[yellow]⚠ Manifest already exists: {path}. "
            f"Use --force to overwrite.[/yellow]"
        )
        raise typer.Exit(1)

    manifest = manifest_mod.default_for(
        cookbook_name=book,
        objective=objective,
        daily_kcal=daily_kcal,
    )
    written = manifest_mod.save(manifest, book_dir)
    console.print(f"[green]✓ Manifest written: {written}[/green]")
    console.print(f"  Objective: {manifest.objective}")
    console.print(f"  Daily kcal target: {manifest.target_daily_kcal}")


@app.command("meal-plan")
def meal_plan(
    book: Annotated[str, typer.Option("--book", "-b", help="Book name")],
    days: Annotated[int, typer.Option("--days", help="Number of days in the plan")] = 60,
    seed: Annotated[int, typer.Option("--seed", help="Random seed for reproducibility")] = 42,
    output: Annotated[str, typer.Option("--output", "-o", help="Output format: md, json, csv, pdf, all")] = "all",
    use_llm_aliases: Annotated[bool, typer.Option(
        "--use-llm-aliases/--no-llm-aliases",
        help="Use an LLM to merge similar ingredients (persistent cache)"
    )] = True,
    reset_aliases: Annotated[bool, typer.Option(
        "--reset-aliases",
        help="Clear the alias cache before generating (forces an LLM recompute)"
    )] = False,
    profile_name: Annotated[str | None, typer.Option(
        "--profile", help="Name of a user profile in data/users/{name}.json"
    )] = None,
    sex: Annotated[str | None, typer.Option("--sex", help="Biological sex: M or F")] = None,
    age: Annotated[int | None, typer.Option("--age", help="Age in years")] = None,
    height: Annotated[float | None, typer.Option("--height", help="Height in cm")] = None,
    weight: Annotated[float | None, typer.Option("--weight", help="Current weight in kg")] = None,
    target_weight: Annotated[float | None, typer.Option(
        "--target-weight", help="Target weight in kg (with --target-date, used to compute the pace)"
    )] = None,
    activity: Annotated[str | None, typer.Option(
        "--activity",
        help="Activity level: sedentary, light, moderate, active, very_active"
    )] = None,
    weekly_loss: Annotated[float | None, typer.Option(
        "--weekly-loss", help="Weekly loss in kg/week (optional if --target-date is given)"
    )] = None,
    target_date: Annotated[datetime | None, typer.Option(
        "--target-date",
        formats=["%Y-%m-%d"],
        help="Date to reach the target (YYYY-MM-DD) — automatically computes the pace",
    )] = None,
    per_meal_cap: Annotated[float | None, typer.Option(
        "--per-meal-cap",
        help="Per-meal kcal cap as a multiple of the target (default 1.15)"
    )] = None,
    meal_share: Annotated[str | None, typer.Option(
        "--meal-share",
        help="Per-meal override, e.g. 'breakfast=0.20,lunch=0.40,snack=0.10,dinner=0.30'",
    )] = None,
    meal_structure: Annotated[str | None, typer.Option(
        "--meal-structure",
        help="Per-run meal-structure override, e.g. 'breakfast,lunch,dinner' (does not modify cookbook.json)",
    )] = None,
    force: Annotated[bool, typer.Option(
        "--force/--no-force",
        help="Generate the plan even if the book's capacity is below the kcal target",
    )] = False,
) -> None:
    """Build an N-day plan + shopping list for a book."""
    from datetime import datetime as _dt

    from src.config import GENERATED_DIR
    from src.output import meal_plan_formatter
    from src.planning import manifest as manifest_mod
    from src.planning import meal_planner, personalization, recipe_loader
    from src.planning import user_profile as user_profile_mod

    book_dir = GENERATED_DIR / book
    if not book_dir.exists():
        console.print(f"[bold red]Error:[/bold red] book not found: {book_dir}")
        raise typer.Exit(1)

    try:
        manifest = manifest_mod.load(book_dir)
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)

    console.print(f"[cyan]Loading recipes from {book_dir}...[/cyan]")
    recipes_by_meal = recipe_loader.load_cookbook(book_dir)
    totals = {mt: len(lst) for mt, lst in recipes_by_meal.items()}
    summary = ", ".join(f"{v} {k}" for k, v in totals.items())
    console.print(f"[dim]{summary}[/dim]")

    # Per-run meal_structure override (transient — never written to cookbook.json).
    # Must run before --meal-share parsing because the share validates against it.
    if meal_structure is not None:
        available_types = {mt for mt, lst in recipes_by_meal.items() if lst}
        try:
            parsed_structure = _parse_meal_structure(meal_structure, available_types)
        except ValueError as e:
            console.print(f"[bold red]Error:[/bold red] --meal-structure: {e}")
            raise typer.Exit(1)
        manifest = manifest.model_copy(
            update={"meal_structure": parsed_structure, "meal_share": None}
        )

    if meal_share is not None:
        try:
            parsed_share = _parse_meal_share(meal_share, manifest.meal_structure)
        except ValueError as e:
            console.print(f"[bold red]Error:[/bold red] --meal-share: {e}")
            raise typer.Exit(1)
        manifest = manifest.model_copy(update={"meal_share": parsed_share})

    profile = _resolve_user_profile(
        profile_name=profile_name,
        sex=sex, age=age, height=height, weight=weight,
        target_weight=target_weight, activity=activity,
        weekly_loss=weekly_loss, per_meal_cap=per_meal_cap,
        target_date=target_date.date() if target_date is not None else None,
        user_profile_mod=user_profile_mod,
    )

    targets = None
    if profile is not None:
        try:
            targets = personalization.compute_targets(profile, manifest)
        except ValueError as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            raise typer.Exit(1)
        _print_personalization_summary(profile, targets)

    if targets is not None:
        capacity = personalization.check_cookbook_capacity(recipes_by_meal, targets, manifest)
        if capacity.blocking and not force:
            console.print(f"[bold red]✗ {capacity.message}[/bold red]")
            raise typer.Exit(2)
        if capacity.shortfall_pct > 0.05:
            console.print(f"[yellow]⚠ {capacity.message}[/yellow]")

    console.print(f"[cyan]Building the {days}-day plan (seed={seed})...[/cyan]")
    try:
        plan = meal_planner.build_plan(
            recipes_by_meal=recipes_by_meal,
            manifest=manifest,
            days=days,
            seed=seed,
            targets=targets,
            profile=profile,
        )
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)

    # kcal-tolerance check (Fix 9): warn when avg daily kcal is far from target.
    avg_kcal_check = plan.avg_daily_nutrition.calories_kcal
    target_for_check = targets.daily_kcal if targets is not None else manifest.target_daily_kcal
    tolerance = (
        targets.daily_kcal * 0.10 if targets is not None
        else float(manifest.kcal_tolerance)
    )
    if abs(avg_kcal_check - target_for_check) > tolerance:
        delta = avg_kcal_check - target_for_check
        sense = "above" if delta > 0 else "below"
        plan.generation_warnings.append(
            f"On average, this plan provides {avg_kcal_check:.0f} calories per day "
            f"({abs(delta):.0f} {sense} your target of {target_for_check} calories)."
        )

    if reset_aliases:
        from src.planning.alias_cache import AliasCache
        AliasCache(book_dir).reset()
        console.print(f"[yellow]Alias cache cleared: {book_dir / 'aliases.db'}[/yellow]")

    recipes_by_id = recipe_loader.flat_index(recipes_by_meal)
    from src.planning import week_slicer

    if use_llm_aliases:
        console.print("[cyan]Resolving ingredient aliases (LLM)...[/cyan]")
    weeks = week_slicer.build_weeks(
        plan, recipes_by_id,
        book_dir=book_dir,
        use_llm_aliases=use_llm_aliases,
    )
    # Lift the shelf-stable staples into a front-matter pantry page and demote
    # them out of each week's aisles, so a weekly list is the fresh food to buy.
    from src.planning import pantry as pantry_mod

    pantry = pantry_mod.build_pantry_list(weeks)
    weeks = pantry_mod.split_week_course_lists(weeks, pantry)
    plan = plan.model_copy(update={"weeks": weeks, "pantry": pantry})
    console.print(
        f"[dim]  pantry staples: {pantry.total_items} items "
        f"(kept off the weekly lists)[/dim]"
    )
    for w in weeks:
        n_items = sum(len(v) for v in w.course_list.items_by_category.values())
        console.print(
            f"[dim]  week {w.week_number}: {n_items} items "
            f"+ {len(w.course_list.pantry_items)} pantry[/dim]"
        )

    # Output location: per-user folder when personalized, cookbook MealPlan/ otherwise.
    # Personalized runs always write only PDF + JSON (md/csv are skipped by design).
    if profile is not None:
        out_dir = user_profile_mod.output_dir_for(profile.name)
        stem = user_profile_mod.output_stem_for(profile.name)
        if output in ("md", "csv"):
            console.print(
                f"[bold red]Error:[/bold red] --output {output} is not supported "
                f"with --profile (only pdf and json are produced in personalized mode)."
            )
            raise typer.Exit(1)
    else:
        out_dir = book_dir / "MealPlan"
        date_tag = _dt.now().strftime("%Y-%m-%d")
        stem = f"meal_plan_{date_tag}_seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)

    wrote: list[Path] = []
    if profile is None and output in ("md", "all"):
        p = out_dir / f"{stem}.md"
        p.write_text(meal_plan_formatter.to_markdown(plan), encoding="utf-8")
        wrote.append(p)
    if output in ("json", "all"):
        p = out_dir / f"{stem}.json"
        p.write_text(meal_plan_formatter.to_json(plan), encoding="utf-8")
        wrote.append(p)
    if profile is None and output in ("csv", "all"):
        p = out_dir / f"{stem}.csv"
        p.write_text(meal_plan_formatter.to_csv(plan), encoding="utf-8")
        wrote.append(p)
    if output in ("pdf", "all"):
        try:
            from src.output.pdf import render_to_pdf
        except ImportError as e:
            console.print(
                f"[bold red]Error:[/bold red] WeasyPrint is not installed ({e}). "
                f"Rebuild the Docker image to enable PDF output."
            )
            raise typer.Exit(1)
        p = out_dir / f"{stem}.pdf"
        p.write_bytes(render_to_pdf(plan, book_dir, recipes_by_id))
        wrote.append(p)

    for p in wrote:
        console.print(f"[green]OK: {p}[/green]")

    avg_kcal = plan.avg_daily_nutrition.calories_kcal
    week_counts = [
        sum(len(v) for v in w.course_list.items_by_category.values())
        for w in weeks
    ]
    target_kcal = targets.daily_kcal if targets is not None else manifest.target_daily_kcal
    console.print(
        f"\n[bold cyan]Plan:[/bold cyan] {len(plan.days)} days, "
        f"{avg_kcal:.0f} kcal/day on average "
        f"(target: {target_kcal}), {len(weeks)} weeks"
    )
    console.print(
        f"[bold cyan]Shopping lists:[/bold cyan] "
        f"per week: {', '.join(str(c) for c in week_counts)}"
    )

    if plan.generation_warnings:
        console.print()
        if len(plan.generation_warnings) <= 5:
            for w in plan.generation_warnings:
                console.print(f"[yellow]⚠ {w}[/yellow]")
        else:
            console.print(
                f"[yellow]⚠ {len(plan.generation_warnings)} automatic adjustments "
                f"during generation — see plan.json for the details.[/yellow]"
            )
            for w in plan.generation_warnings[:3]:
                console.print(f"[yellow]  · {w}[/yellow]")


def _parse_meal_structure(spec: str, available_types: set[str]) -> list[str]:
    """Parse '--meal-structure' into an ordered list of meal-type keys.

    Format: 'breakfast,lunch,dinner'.
    Validates: non-empty, every token is in `VALID_MEAL_TYPES`, no duplicates,
    every requested type has at least one recipe in `available_types`.
    """
    from src.constants import VALID_MEAL_TYPES

    parts = [p.strip() for p in spec.split(",") if p.strip()]
    if not parts:
        raise ValueError("empty list — give at least one meal type.")

    seen: set[str] = set()
    duplicates: list[str] = []
    unknown: list[str] = []
    missing_recipes: list[str] = []
    out: list[str] = []
    for token in parts:
        if token not in VALID_MEAL_TYPES:
            unknown.append(token)
            continue
        if token in seen:
            duplicates.append(token)
            continue
        if token not in available_types:
            missing_recipes.append(token)
            continue
        seen.add(token)
        out.append(token)

    if unknown:
        raise ValueError(
            f"unknown meal types: {unknown}. "
            f"Accepted values: {sorted(VALID_MEAL_TYPES)}."
        )
    if duplicates:
        raise ValueError(f"duplicate meal types: {duplicates}.")
    if missing_recipes:
        raise ValueError(
            f"no recipes in this book for: {missing_recipes}. "
            f"Available types: {sorted(available_types)}."
        )
    return out


def _parse_meal_share(spec: str, meal_structure: list[str]) -> dict[str, float]:
    """Parse '--meal-share' into a {meal_type: fraction} dict.

    Format: 'breakfast=0.20,lunch=0.40,snack=0.10,dinner=0.30'.
    All meal types in `meal_structure` must be present and the sum must be ~1.0.
    """
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    parsed: dict[str, float] = {}
    for p in parts:
        if "=" not in p:
            raise ValueError(f"invalid segment '{p}' — expected 'meal_type=fraction'.")
        key, val = p.split("=", 1)
        key = key.strip()
        try:
            parsed[key] = float(val.strip())
        except ValueError as e:
            raise ValueError(f"non-numeric value for '{key}': {val!r}.") from e
    missing = [mt for mt in meal_structure if mt not in parsed]
    if missing:
        raise ValueError(f"missing {missing} to cover meal_structure.")
    extra = [k for k in parsed if k not in meal_structure]
    if extra:
        raise ValueError(f"unknown keys {extra} (not in meal_structure).")
    total = sum(parsed[mt] for mt in meal_structure)
    if not 0.99 <= total <= 1.01:
        raise ValueError(f"fractions must sum to ~1.0 (got {total:.3f}).")
    return parsed


def _resolve_user_profile(
    *,
    profile_name,
    sex, age, height, weight, target_weight, activity, weekly_loss, per_meal_cap,
    target_date,
    user_profile_mod,
):
    """Resolve a UserProfile from --profile + inline overrides.

    Precedence: inline flag > profile JSON > Pydantic default.
    Returns None when neither --profile nor any biometric flag was given.
    Exits the CLI with a clear error message on validation failure.
    """
    from pydantic import ValidationError

    from src.models.meal_plan import UserProfile

    inline_fields = {
        "sex": sex, "age": age, "height_cm": height, "weight_kg": weight,
        "target_weight_kg": target_weight, "activity_level": activity,
    }
    optional_inline = {
        "weekly_loss_kg": weekly_loss, "per_meal_kcal_cap_pct": per_meal_cap,
        "target_date": target_date,
    }
    any_inline = (
        any(v is not None for v in inline_fields.values())
        or any(v is not None for v in optional_inline.values())
    )
    if profile_name is None and not any_inline:
        return None

    base: dict = {}
    if profile_name is not None:
        try:
            loaded = user_profile_mod.load(profile_name)
        except FileNotFoundError as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            raise typer.Exit(1)
        base = loaded.model_dump()

    for key, val in {**inline_fields, **optional_inline}.items():
        if val is not None:
            base[key] = val
    # When target_date is set inline, blank out any stored weekly_loss_kg from
    # the loaded profile so derive_weekly_loss honors the new date instead of
    # falling through to the persisted explicit rate.
    if target_date is not None and weekly_loss is None:
        base["weekly_loss_kg"] = None
    base.setdefault("name", profile_name or "ad-hoc")

    try:
        return UserProfile.model_validate(base)
    except ValidationError as e:
        console.print(
            "[bold red]Error:[/bold red] profile parameters are incomplete or invalid. "
            "With --profile, supply overrides; without --profile, supply "
            "--sex/--age/--height/--weight/--target-weight/--activity and either "
            "--weekly-loss or --target-date."
        )
        console.print(f"[dim]{e}[/dim]")
        raise typer.Exit(1)


def _print_personalization_summary(profile, targets) -> None:
    from src.planning.personalization import ACTIVITY_LABELS, SEX_LABELS
    bmi = profile.weight_kg / (profile.height_cm / 100.0) ** 2
    console.print(
        f"\n[bold cyan]Profile:[/bold cyan] {profile.name} "
        f"({SEX_LABELS[profile.sex]}, {profile.age} y/o, {profile.height_cm:.0f} cm, "
        f"{profile.weight_kg:.1f} → {profile.target_weight_kg:.1f} kg, "
        f"BMI {bmi:.1f}, activity '{ACTIVITY_LABELS[profile.activity_level]}')"
    )
    if profile.target_date is not None:
        from src.planning.personalization import derive_weekly_loss
        derived_rate, _ = derive_weekly_loss(profile)
        console.print(
            f"[bold cyan]Pace:[/bold cyan] target "
            f"{profile.target_weight_kg:.1f} kg by "
            f"{profile.target_date.isoformat()} → {derived_rate:+.2f} kg/week"
        )
    elif profile.weekly_loss_kg is not None:
        console.print(
            f"[bold cyan]Pace:[/bold cyan] {profile.weekly_loss_kg:+.2f} kg/week"
        )
    console.print(
        f"[bold cyan]Targets:[/bold cyan] "
        f"BMR {targets.bmr:.0f} · TDEE {targets.tdee:.0f} · "
        f"{targets.daily_kcal} kcal/day · "
        f"{targets.protein_g:.0f}P / {targets.carbs_g:.0f}C / "
        f"{targets.fat_g:.0f}F / {targets.fiber_g:.0f} fiber (g/day)"
    )
    for w in targets.warnings:
        console.print(f"[yellow]⚠ {w}[/yellow]")


@app.command("init-profile")
def init_profile(
    name: Annotated[str, typer.Option("--name", "-n", help="Short profile name (used as the file name)")],
    sex: Annotated[str, typer.Option("--sex", help="Biological sex: M or F")],
    age: Annotated[int, typer.Option("--age", help="Age in years")],
    height: Annotated[float, typer.Option("--height", help="Height in cm")],
    weight: Annotated[float, typer.Option("--weight", help="Current weight in kg")],
    target_weight: Annotated[float, typer.Option("--target-weight", help="Target weight in kg")],
    activity: Annotated[str, typer.Option(
        "--activity",
        help="Activity level: sedentary, light, moderate, active, very_active"
    )],
    weekly_loss: Annotated[float | None, typer.Option(
        "--weekly-loss",
        help="Weekly loss in kg (optional if --target-date is given)"
    )] = None,
    target_date: Annotated[datetime | None, typer.Option(
        "--target-date",
        formats=["%Y-%m-%d"],
        help="Date to reach the target (YYYY-MM-DD) — automatically computes the pace",
    )] = None,
    per_meal_cap: Annotated[float, typer.Option(
        "--per-meal-cap", help="Per-meal kcal cap (multiple of the target)"
    )] = 1.15,
    force: Annotated[bool, typer.Option("--force/--no-force", help="Overwrite an existing profile")] = False,
) -> None:
    """Create a user profile in data/users/{name}.json.

    Supply either --target-date (the pace is computed) or --weekly-loss.
    With neither, a default pace of 0.5 kg/week is used in the implied
    direction (lose if target < current).
    """
    from pydantic import ValidationError

    from src.models.meal_plan import UserProfile
    from src.planning import user_profile as user_profile_mod

    path = user_profile_mod.default_path(name)
    if path.exists() and not force:
        console.print(
            f"[yellow]⚠ Profile already exists: {path}. Use --force to overwrite.[/yellow]"
        )
        raise typer.Exit(1)

    try:
        profile = UserProfile(
            name=name,
            sex=sex,  # type: ignore[arg-type]
            age=age,
            height_cm=height,
            weight_kg=weight,
            target_weight_kg=target_weight,
            activity_level=activity,  # type: ignore[arg-type]
            weekly_loss_kg=weekly_loss,
            target_date=target_date.date() if target_date is not None else None,
            per_meal_kcal_cap_pct=per_meal_cap,
        )
    except ValidationError as e:
        console.print(f"[bold red]Error:[/bold red] invalid values.\n[dim]{e}[/dim]")
        raise typer.Exit(1)

    written = user_profile_mod.save(profile)
    console.print(f"[green]✓ Profile written: {written}[/green]")
    bmi = profile.weight_kg / (profile.height_cm / 100.0) ** 2
    from src.planning.personalization import SEX_LABELS
    if profile.target_date is not None:
        from src.planning.personalization import derive_weekly_loss
        derived, _ = derive_weekly_loss(profile)
        pace = f"target date {profile.target_date.isoformat()} → {derived:+.2f} kg/week"
    else:
        pace = f"pace {profile.weekly_loss_kg:+.2f} kg/week"
    console.print(
        f"  {SEX_LABELS[profile.sex]}, {profile.age} y/o, {profile.height_cm:.0f} cm — "
        f"BMI {bmi:.1f}, {pace}"
    )


@app.command("regenerate-missing-images")
def regenerate_missing_images(
    book: Annotated[str, typer.Option("--book", "-b", help="Book name")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="List only, generate nothing")] = False,
) -> None:
    """Generate only the missing images (Stage 7) for a book's recipes."""
    import json as _json

    from src.config import GENERATED_DIR
    from src.models.recipe import Recipe
    from src.recipe_pipeline import stage_07_image

    book_dir = GENERATED_DIR / book
    if not book_dir.exists():
        console.print(f"[bold red]Error:[/bold red] book not found: {book_dir}")
        raise typer.Exit(1)

    # Find recipes whose image_path is None or whose target file is missing.
    targets: list[tuple[Recipe, Path, Path]] = []  # (recipe, json_path, expected_image_path)
    for meal_key, folder_name in MEAL_TYPE_FOLDERS.items():
        json_dir = book_dir / folder_name / "JSON"
        img_dir = book_dir / folder_name / "IMG"
        if not json_dir.exists():
            continue
        from src.planning.recipe_loader import _normalise_legacy_fields
        for jp in sorted(json_dir.glob("*.json")):
            try:
                raw = _json.loads(jp.read_text(encoding="utf-8"))
                _normalise_legacy_fields(raw)
                recipe = Recipe.model_validate(raw)
            except Exception as e:  # noqa: BLE001
                console.print(f"[yellow]Invalid recipe skipped: {jp.name} ({e})[/yellow]")
                continue
            existing = Path(recipe.image_path) if recipe.image_path else None
            if existing and existing.is_file():
                continue
            slug = recipe.title.lower().replace(" ", "_").replace("/", "-")[:60]
            targets.append((recipe, jp, img_dir / f"{slug}.png"))

    if not targets:
        console.print("[green]Every recipe already has an image. Nothing to do.[/green]")
        return

    console.print(f"[cyan]{len(targets)} recipe(s) without an image:[/cyan]")
    for r, _, p in targets:
        console.print(f"  - {r.title}  ->  {p.name}")

    if dry_run:
        console.print("[dim](--dry-run: no images generated)[/dim]")
        return

    successes = failures = 0
    for i, (recipe, json_path, img_path) in enumerate(targets, start=1):
        console.print(f"\n[bold cyan][{i}/{len(targets)}] {recipe.title}[/bold cyan]")
        try:
            result = stage_07_image.run(recipe)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Failed: {e}[/red]")
            failures += 1
            continue

        if not result.image_bytes:
            console.print(f"[red]No image returned: {result.failure_reason}[/red]")
            failures += 1
            continue

        img_path.parent.mkdir(parents=True, exist_ok=True)
        img_path.write_bytes(result.image_bytes)

        # Update the JSON in place with the new image_path.
        raw = _json.loads(json_path.read_text(encoding="utf-8"))
        raw["image_path"] = str(img_path)
        json_path.write_text(_json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

        status = "OK" if result.success else "OK (critic did not pass)"
        console.print(f"[green]{status}: {img_path}[/green]")
        successes += 1

    console.print(
        f"\n[bold cyan]Done:[/bold cyan] {successes} generated, {failures} failure(s)"
    )


if __name__ == "__main__":
    app()
