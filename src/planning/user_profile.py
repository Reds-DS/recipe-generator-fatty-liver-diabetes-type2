"""Load / save user profiles (`data/users/{name}.json`)."""
import re
import unicodedata
from pathlib import Path

from src.config import GENERATED_DIR
from src.models.meal_plan import UserProfile

PROFILES_DIRNAME = "users"


def profiles_dir() -> Path:
    """Project-wide users folder, sibling of generated_recipes."""
    return GENERATED_DIR.parent / PROFILES_DIRNAME


def default_path(name: str) -> Path:
    return profiles_dir() / f"{name}.json"


def slugify(name: str) -> str:
    """Convert a profile display name to a filesystem-friendly slug.

    'Catherine CALMEL-MAINGUET' → 'catherine-calmel-mainguet'
    'Élise O''Brien_42'         → 'elise-obrien-42'
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    # Replace any run of non-alphanumeric characters with a single dash.
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "profile"


def output_dir_for(name: str) -> Path:
    """Folder where personalized meal-plan outputs are written."""
    return profiles_dir() / slugify(name)


def output_stem_for(name: str) -> str:
    """Filename stem (without extension) for personalized meal-plan outputs."""
    return f"meal_plan_{slugify(name)}"


def load(name_or_path: str | Path) -> UserProfile:
    """Resolve `name_or_path` to a JSON file and parse it as `UserProfile`.

    Resolution rules:
      - A bare name like ``reda`` → ``data/users/reda.json``.
      - A bare name with .json suffix like ``reda.json`` → also resolves to
        ``data/users/reda.json`` (the suffix is dropped, not treated as a path).
      - Anything containing a path separator → used verbatim.
    """
    raw = str(name_or_path)
    has_separator = "/" in raw or "\\" in raw
    path = Path(raw)
    if not has_separator:
        # Bare name — strip an optional .json suffix and resolve via default_path.
        stem = path.stem if path.suffix.lower() == ".json" else raw
        path = default_path(stem)
    if not path.exists():
        raise FileNotFoundError(
            f"User profile not found: {path}. "
            f"Create it with: init-profile --name {path.stem}"
        )
    return UserProfile.model_validate_json(path.read_text(encoding="utf-8"))


def save(profile: UserProfile) -> Path:
    """Write `profile` to `data/users/{profile.name}.json` (pretty JSON)."""
    path = default_path(profile.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    return path
