"""One-off script: run image generation on an existing recipe JSON."""
import sys
from pathlib import Path

from src.models.recipe import Recipe
from src.recipe_pipeline import stage_07_image


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_image_only.py <recipe.json>")
        sys.exit(1)

    recipe_path = Path(sys.argv[1])
    recipe = Recipe.model_validate_json(recipe_path.read_text(encoding="utf-8"))
    print(f"Recipe loaded: {recipe.title}")

    result = stage_07_image.run(recipe)
    print(f"Success: {result.success}")
    print(f"Attempts: {result.attempts}")
    if result.failure_reason:
        print(f"Failure: {result.failure_reason}")
    if result.image_bytes:
        img_path = recipe_path.parent.parent / "IMG" / f"{recipe_path.stem}.png"
        img_path.parent.mkdir(parents=True, exist_ok=True)
        img_path.write_bytes(result.image_bytes)
        print(f"Image saved: {img_path} ({len(result.image_bytes)} bytes)")


if __name__ == "__main__":
    main()
