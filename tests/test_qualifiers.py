"""Ingredient-qualifier polarity + the Stage 4 mismatch guard (offline, no DB/LLM).

Every case here is drawn from a real test4 miss: the salmon salad matched a salted record
for a no-salt-added ingredient (+954 mg sodium/serving) and the taco bowl matched broiled
patties for raw ground turkey (+100 kcal/serving).
"""
import pytest

from src.nutrition.qualifiers import (
    SODIUM_MAX_UNSALTED_PER_100G,
    mismatch_reason,
    salt_polarity,
    state_polarity,
)


class TestSaltPolarity:
    @pytest.mark.parametrize("text", [
        "No-salt-added canned black beans",
        "canned pink salmon, no-salt-added, drained",
        "tomatoes, red, ripe, canned, packed in tomato juice, no salt added",
        "fish, salmon, pink, canned, without salt, solids with bone and liquid",
        "beans, black, mature seeds, canned, low sodium",
        "cheese, cottage, lowfat, 1% milkfat, no sodium added",
        "nuts, almonds, dry roasted, without salt added",
    ])
    def test_unsalted(self, text):
        assert salt_polarity(text) == "unsalted"

    @pytest.mark.parametrize("text", [
        "beans, black, canned, sodium added, drained and rinsed",
        "nuts, almonds, dry roasted, with salt added",
        "anchovies, canned in brine",
    ])
    def test_salted(self, text):
        assert salt_polarity(text) == "salted"

    @pytest.mark.parametrize("text", [
        "fish, salmon, pink, canned, drained solids",   # salted in fact, unmarked in name
        "beans, white, mature seeds, canned",
        "salt, table, iodized",                         # the ingredient *is* salt
        "spinach, baby",
        None,
        "",
    ])
    def test_unspecified(self, text):
        assert salt_polarity(text) is None

    def test_no_sodium_added_is_not_read_as_sodium_added(self):
        """'no sodium added' contains 'sodium added'; order of testing must not flip it."""
        assert salt_polarity("no sodium added") == "unsalted"

    def test_unsalted_is_not_read_as_salted(self):
        """'unsalted' contains 'salted'; word boundaries must not flip it."""
        assert salt_polarity("unsalted butter") == "unsalted"


class TestStatePolarity:
    @pytest.mark.parametrize("text,expected", [
        ("turkey, ground, 93% lean, 7% fat, raw", "raw"),
        ("turkey, ground, 93% lean, 7% fat, patties, broiled", "cooked"),
        ("turkey, ground, 93% lean, 7% fat, pan-broiled crumbles", "cooked"),
        ("beans, black, mature seeds, cooked, boiled", "cooked"),
        ("spinach, baby", None),
        ("oil, olive, extra virgin", None),
        (None, None),
    ])
    def test_polarity(self, text, expected):
        assert state_polarity(text) == expected

    def test_straw_does_not_match_raw(self):
        """Substring matching would read 'strawberries' as raw."""
        assert state_polarity("strawberries, frozen, unsweetened") is None
        assert state_polarity("strawberries, raw") == "raw"


def _reason(name, desc, *, prep=None, sodium=0.0, alt=False):
    return mismatch_reason(
        request_name=name,
        request_preparation=prep,
        candidate_description=desc,
        candidate_sodium_mg=sodium,
        unsalted_alternative_exists=alt,
    )


class TestMismatchGuard:
    def test_accepts_a_matching_unsalted_pick(self):
        assert _reason(
            "canned pink salmon, no-salt-added, drained",
            "fish, salmon, pink, canned, without salt, solids with bone and liquid",
            sodium=75.0,
        ) is None

    def test_rejects_an_explicitly_salted_pick(self):
        r = _reason(
            "No-salt-added canned black beans",
            "beans, black, canned, sodium added, drained and rinsed",
            prep="rinsed and drained", sodium=217.9,
        )
        assert r is not None and "salted" in r

    def test_rejects_an_unmarked_pick_when_an_unsalted_one_exists(self):
        """The salmon miss: the chosen record carried no salt word, but 174225 did."""
        r = _reason(
            "canned pink salmon, no-salt-added, drained",
            "fish, salmon, pink, canned, drained solids",
            sodium=381.0, alt=True,
        )
        assert r is not None and "explicitly unsalted candidate is available" in r

    def test_rejects_an_unmarked_pick_that_is_plainly_salty(self):
        """The cannellini miss: no unsalted sibling exists, so sodium is the backstop."""
        r = _reason(
            "canned cannellini beans, no-salt-added",
            "beans, white, mature seeds, canned",
            sodium=340.0, alt=False,
        )
        assert r is not None and "340 mg sodium" in r

    def test_allows_an_unmarked_pick_that_is_genuinely_low_sodium(self):
        assert _reason(
            "no-salt-added canned tomatoes",
            "tomatoes, red, ripe, canned",
            sodium=SODIUM_MAX_UNSALTED_PER_100G - 1, alt=False,
        ) is None

    def test_rejects_a_cooked_record_for_a_raw_weight(self):
        """The taco bowl miss: 340 g raw turkey priced as broiled patties."""
        r = _reason(
            "Lean ground turkey (93% lean) Turkey, ground, 93% lean, 7% fat, raw",
            "turkey, ground, 93% lean, 7% fat, patties, broiled",
        )
        assert r is not None and "measured raw" in r

    def test_accepts_the_raw_record_for_a_raw_weight(self):
        assert _reason(
            "Lean ground turkey (93% lean) Turkey, ground, 93% lean, 7% fat, raw",
            "turkey, ground, 93% lean, 7% fat, raw",
        ) is None

    def test_preparation_does_not_set_cooking_state(self):
        """'toasted' is what the cook does; the almonds are still bought raw."""
        assert _reason(
            "Sliced almonds Nuts, almonds",
            "nuts, almonds, whole, raw",
            prep="toasted",
        ) is None

    def test_silent_request_accepts_anything(self):
        assert _reason("baby spinach Spinach, raw", "spinach, baby") is None

    def test_rejects_cooked_from_dry_for_a_canned_ingredient(self):
        """Canned beans carry more water than the same bean boiled from dry."""
        r = _reason(
            "canned cannellini beans, no-salt-added Beans, white, mature seeds, canned",
            "beans, white, mature seeds, cooked, boiled, without salt",
            sodium=6.0,
        )
        assert r is not None and "cooked from dry" in r

    def test_accepts_a_canned_match_for_a_canned_ingredient(self):
        assert _reason(
            "No-salt-added canned black beans Beans, black, mature seeds, canned, low sodium",
            "beans, black, mature seeds, canned, low sodium",
            prep="rinsed and drained", sodium=138.0,
        ) is None
