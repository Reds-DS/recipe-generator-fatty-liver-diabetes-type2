from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
GENERATED_DIR = DATA_DIR / "generated_recipes"


def _newest_usda_source_dir() -> Path:
    """Locate the unzipped USDA FoodData Central CSV bundle.

    Accepts either layout: the CSVs unzipped directly into ``usda_source_data/``
    (so ``usda_source_data/food.csv`` exists), or kept inside the download's own
    ``FoodData_Central_csv_*`` subfolder (the newest is used). Returns a
    non-existent sentinel if neither is present — ``build-nutrition-db`` then
    prints a helpful download hint."""
    root = BASE_DIR / "usda_source_data"
    if (root / "food.csv").exists():
        return root
    dirs = sorted((p for p in root.glob("FoodData_Central_csv_*") if p.is_dir()), reverse=True)
    return dirs[0] if dirs else root / "FoodData_Central_csv"


# USDA FoodData Central — the source CSV bundle + the built local databases
USDA_SOURCE_DIR = _newest_usda_source_dir()
USDA_DB = DATA_DIR / "usda.db"
USDA_ALIAS_DB = DATA_DIR / "usda_alias.db"

DEDUP_DB = DATA_DIR / "dedup.db"
GUIDELINES = DATA_DIR / "fatty_liver_diabetes_guidelines.yaml"
BATCH_STATE_DIR = DATA_DIR / "batch_state"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    llm_provider: str = "google"  # "google" or "anthropic"
    google_api_key: str = ""
    anthropic_api_key: str = ""
    # Gemini 3.1 preview IDs — current in this project's Google account and the
    # same IDs run in production in recipe-generator-v2. Override via .env if needed.
    llm_model: str = "gemini-3.1-pro-preview"

    # Image pipeline models
    image_prompt_model: str = "gemini-3.1-flash-lite-preview"
    image_generation_model: str = "gemini-3.1-flash-image-preview"
    image_generation_fallback_model: str = "gemini-2.5-flash-image"
    image_critic_model: str = "gemini-3.1-pro-preview"
    # "512", "1K", "2K", or "4K". 1K DECIDED 2026-08-09 — do not "tidy" it.
    # KDP prints at ~300 DPI, so 1024 px is good to ~3.4 in wide and 2048 px to
    # ~6.8 in. The interior layout for this book is a column-width / half-page
    # inset beside the recipe text, which 1K covers. THE ASYMMETRY THAT MATTERS:
    # 2K downscales to 1K cleanly, but 1K does NOT upscale to 2K. If the layout
    # ever goes full-width or full-page, set IMAGE_SIZE=2K in .env BEFORE
    # generating — discovering it afterwards means regenerating all 106 images.
    # Bonus at 1K: the fallback image model is 1K-only, so a fallback costs no
    # resolution.
    image_size: str = "1K"
    image_generation_enabled: bool = True


settings = Settings()  # type: ignore[call-arg]
