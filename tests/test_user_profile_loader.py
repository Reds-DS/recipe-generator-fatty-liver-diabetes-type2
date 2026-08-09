"""Tests for the user-profile JSON loader path-resolver behavior."""

import pytest

from src.models.meal_plan import UserProfile
from src.planning import user_profile as user_profile_mod


@pytest.fixture
def isolated_users_dir(tmp_path, monkeypatch):
    """Redirect data/users/ to a tmp directory for the test."""
    fake_data = tmp_path / "data"
    fake_generated = fake_data / "generated_recipes"
    fake_generated.mkdir(parents=True)
    monkeypatch.setattr(user_profile_mod, "GENERATED_DIR", fake_generated)
    return fake_data / "users"


def _persist_default_profile(name: str) -> UserProfile:
    p = UserProfile(
        name=name, sex="M", age=35, height_cm=175,
        weight_kg=80, target_weight_kg=73,
        activity_level="moderate", weekly_loss_kg=0.5,
    )
    user_profile_mod.save(p)
    return p


def test_load_by_bare_name(isolated_users_dir):
    _persist_default_profile("reda")
    loaded = user_profile_mod.load("reda")
    assert loaded.name == "reda"


def test_load_by_name_with_json_suffix(isolated_users_dir):
    """Fix 7: 'reda.json' should resolve to data/users/reda.json, not literal."""
    _persist_default_profile("reda")
    loaded = user_profile_mod.load("reda.json")
    assert loaded.name == "reda"


def test_load_by_explicit_path(isolated_users_dir, tmp_path):
    """Paths with separators are still treated literally."""
    p = _persist_default_profile("reda")
    explicit_path = isolated_users_dir / "reda.json"
    loaded = user_profile_mod.load(str(explicit_path))
    assert loaded.name == "reda"


def test_load_missing_profile_raises_with_helpful_hint(isolated_users_dir):
    with pytest.raises(FileNotFoundError, match="init-profile"):
        user_profile_mod.load("nonexistent")


def test_load_missing_profile_with_json_suffix_still_helpful(isolated_users_dir):
    """The hint should suggest the right name even when the suffix was given."""
    with pytest.raises(FileNotFoundError) as exc:
        user_profile_mod.load("nonexistent.json")
    assert "nonexistent" in str(exc.value)


# ---------------------------------------------------------------------------
# slugify + output paths
# ---------------------------------------------------------------------------

def test_slugify_canonical_full_name():
    assert user_profile_mod.slugify("Catherine CALMEL-MAINGUET") == "catherine-calmel-mainguet"


def test_slugify_strips_accents():
    assert user_profile_mod.slugify("Élise Dupré") == "elise-dupre"


def test_slugify_collapses_punctuation():
    assert user_profile_mod.slugify("O'Brien_42!!") == "o-brien-42"


def test_slugify_falls_back_for_empty_input():
    assert user_profile_mod.slugify("   ") == "profile"
    assert user_profile_mod.slugify("###") == "profile"


def test_output_dir_for_uses_slug_under_users(isolated_users_dir):
    out = user_profile_mod.output_dir_for("Catherine CALMEL-MAINGUET")
    assert out.name == "catherine-calmel-mainguet"
    assert out.parent == isolated_users_dir


def test_output_stem_for_uses_slug():
    assert (
        user_profile_mod.output_stem_for("Catherine CALMEL-MAINGUET")
        == "meal_plan_catherine-calmel-mainguet"
    )
