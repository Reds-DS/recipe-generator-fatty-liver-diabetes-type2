"""Load / save the per-cookbook manifest (`cookbook.json`)."""
from pathlib import Path

from src.diet_rules import spec
from src.models.meal_plan import CookbookManifest

MANIFEST_FILENAME = "cookbook.json"


def manifest_path(cookbook_dir: Path) -> Path:
    return cookbook_dir / MANIFEST_FILENAME


def load(cookbook_dir: Path) -> CookbookManifest:
    """Load and validate `cookbook.json` from a cookbook folder."""
    path = manifest_path(cookbook_dir)
    if not path.exists():
        raise FileNotFoundError(
            f"Manifest not found: {path}. "
            f"Run: init-manifest --book {cookbook_dir.name}"
        )
    return CookbookManifest.model_validate_json(path.read_text(encoding="utf-8"))


def save(manifest: CookbookManifest, cookbook_dir: Path) -> Path:
    """Write manifest as pretty JSON."""
    path = manifest_path(cookbook_dir)
    path.write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return path


def default_for(
    cookbook_name: str,
    *,
    objective: str | None = None,
    daily_kcal: int | None = None,
    diet_tags: list[str] | None = None,
) -> CookbookManifest:
    """Sensible defaults for a new cookbook, overridable by caller."""
    tags = diet_tags or []
    guessed_objective = objective or _guess_objective(cookbook_name, tags)
    return CookbookManifest(
        name=cookbook_name,
        objective=guessed_objective,
        diet_tags=tags,
        servings_per_recipe=2,
        # ~1,700 kcal is this book's printed plan day: a 500-1,000 kcal deficit
        # for a reader whose maintenance sits at 2,150-2,700, which is the AGA's
        # route to the >=7-10% weight loss the liver needs. See
        # `daily_targets.energy_kcal_per_day` in the spec.
        target_daily_kcal=daily_kcal or 1700,
        kcal_tolerance=200,
        max_repeat_window_days=7,
        # Dessert is in the default structure: it is a real slot in this book
        # (the description sells it), and the day arithmetic in the spec is
        # computed with it present. Snack is NOT optional — see
        # OPTIONAL_MEAL_TYPES in src/constants.py.
        meal_structure=["breakfast", "lunch", "snack", "dinner", "dessert"],
        recipe_targets=spec.chapter_target_counts(),
    )


def target_recipe_counts(manifest: CookbookManifest) -> dict[str, int]:
    """Per-chapter target recipe counts for this cookbook: the YAML defaults
    (``data/fatty_liver_diabetes_guidelines.yaml``) overridden by anything set in the manifest's
    ``recipe_targets``."""
    return {**spec.chapter_target_counts(), **manifest.recipe_targets}


def _guess_objective(cookbook_name: str, diet_tags: list[str]) -> str:
    """Produce a friendly default objective from the book name + tags."""
    name_lc = cookbook_name.lower()
    tags = {t.lower() for t in diet_tags}
    if (
        "liver" in name_lc or "masld" in name_lc or "nafld" in name_lc
        or "diabet" in name_lc or "fatty" in name_lc
        or "masld" in tags or "fatty-liver" in tags or "type-2-diabetes" in tags
        or "mediterranean" in tags
    ):
        return (
            "30-day plan for adults with type 2 diabetes and fatty liver — one way of eating for "
            "both: Mediterranean in character, energy-controlled for the 7-10% weight loss the "
            "liver needs, very low in added sugar, fiber- and protein-forward, and alcohol-free."
        )
    return f"Meal program based on {cookbook_name}."
