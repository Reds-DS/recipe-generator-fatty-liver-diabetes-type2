"""Tests for small CLI parsers/helpers in cli.py — pure functions, no Typer."""
import pytest

from cli import _parse_meal_share, _parse_meal_structure

MS = ["breakfast", "lunch", "snack", "dinner"]
AVAILABLE = {"breakfast", "lunch", "snack", "dinner"}


def test_meal_share_parses_canonical_spec():
    out = _parse_meal_share("breakfast=0.20,lunch=0.40,snack=0.10,dinner=0.30", MS)
    assert out == {"breakfast": 0.20, "lunch": 0.40, "snack": 0.10, "dinner": 0.30}


def test_meal_share_tolerates_whitespace():
    out = _parse_meal_share(" breakfast = 0.25 , lunch=0.35,snack=0.10,dinner=0.30 ", MS)
    assert out["breakfast"] == 0.25


def test_meal_share_rejects_missing_meal_type():
    with pytest.raises(ValueError, match="missing"):
        _parse_meal_share("breakfast=0.30,lunch=0.40,dinner=0.30", MS)


def test_meal_share_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown keys"):
        _parse_meal_share(
            "breakfast=0.20,lunch=0.40,snack=0.10,dinner=0.20,brunch=0.10",
            MS,
        )


def test_meal_share_rejects_non_numeric_value():
    with pytest.raises(ValueError, match="non-numeric"):
        _parse_meal_share("breakfast=zero,lunch=0.40,snack=0.10,dinner=0.30", MS)


def test_meal_share_rejects_sum_not_one():
    with pytest.raises(ValueError, match="sum to"):
        _parse_meal_share("breakfast=0.50,lunch=0.50,snack=0.10,dinner=0.30", MS)


def test_meal_share_rejects_malformed_segment():
    with pytest.raises(ValueError, match="invalid segment"):
        _parse_meal_share("breakfast-0.25,lunch=0.40,snack=0.10,dinner=0.30", MS)


# ---------------------------------------------------------------------------
# _parse_meal_structure
# ---------------------------------------------------------------------------

def test_meal_structure_parses_canonical_3_meals():
    out = _parse_meal_structure("breakfast,lunch,dinner", AVAILABLE)
    assert out == ["breakfast", "lunch", "dinner"]


def test_meal_structure_preserves_order():
    out = _parse_meal_structure("dinner,breakfast,lunch", AVAILABLE)
    assert out == ["dinner", "breakfast", "lunch"]


def test_meal_structure_tolerates_whitespace_and_trailing_comma():
    out = _parse_meal_structure(" breakfast , lunch , dinner , ", AVAILABLE)
    assert out == ["breakfast", "lunch", "dinner"]


def test_meal_structure_rejects_empty():
    with pytest.raises(ValueError, match="empty list"):
        _parse_meal_structure("", AVAILABLE)
    with pytest.raises(ValueError, match="empty list"):
        _parse_meal_structure(" , , ", AVAILABLE)


def test_meal_structure_rejects_unknown_type():
    with pytest.raises(ValueError, match="unknown meal types"):
        _parse_meal_structure("breakfast,brunch,dinner", AVAILABLE)


def test_meal_structure_rejects_duplicates():
    with pytest.raises(ValueError, match="duplicate meal types"):
        _parse_meal_structure("breakfast,lunch,lunch,dinner", AVAILABLE)


def test_meal_structure_rejects_meal_type_without_recipes():
    """If 'dessert' is valid but the cookbook has no dessert recipes, fail fast."""
    available_no_dessert = {"breakfast", "lunch", "snack", "dinner"}
    with pytest.raises(ValueError, match="no recipes in this book"):
        _parse_meal_structure("breakfast,dessert,dinner", available_no_dessert)


def test_meal_structure_accepts_dessert_when_available():
    available_with_dessert = AVAILABLE | {"dessert"}
    out = _parse_meal_structure(
        "breakfast,lunch,snack,dinner,dessert",
        available_with_dessert,
    )
    assert "dessert" in out
    assert len(out) == 5
