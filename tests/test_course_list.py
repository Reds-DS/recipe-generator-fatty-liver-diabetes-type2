"""Shopping-list aggregation and aisle categorisation (offline, no LLM).

Every case here comes from a real defect in the 60-day plan built off
``recipes-cookbook-v1``: seasonings were printed in the produce aisle, whole
items fell through to "Other", and plural/singular spellings of the same
grocery were printed as two separate lines.
"""
import pytest

from src.models.recipe import Ingredient
from src.planning.course_list import (
    UNCATEGORIZED,
    _agg_key,
    _categorize,
    _display_case,
    _load_category_map,
    _reject_unsafe_merges,
    _singularise,
    _strip_qualifiers_from_display,
)


def _key(name: str) -> str:
    return _agg_key(Ingredient(
        name=name, canonical_name=name, quantity_g=100, quantity_display="100 g",
    ))


def _cat(name: str) -> str:
    return _categorize(_key(name), _load_category_map())


class TestSingularise:
    @pytest.mark.parametrize("plural,singular", [
        ("raspberries", "raspberry"),
        ("blueberries", "blueberry"),
        ("cherries", "cherry"),
        ("berries", "berry"),
        ("tomatoes", "tomato"),
        ("potatoes", "potato"),
        ("onions", "onion"),
        ("eggs", "egg"),
        ("peas", "pea"),
        ("squashes", "squash"),
    ])
    def test_regular_plurals(self, plural, singular):
        assert _singularise(plural) == singular

    @pytest.mark.parametrize("word", [
        "hummus", "asparagus", "couscous", "molasses", "watercress", "oat",
    ])
    def test_words_that_only_look_plural_are_left_alone(self, word):
        assert _singularise(word) == word


class TestAggregationMerging:
    """Plural and singular spellings must land on one shopping line."""

    @pytest.mark.parametrize("a,b", [
        ("tomato", "tomatoes"),
        ("raspberry", "raspberries"),
        ("red onion", "red onions"),
        ("green bean", "green beans"),
    ])
    def test_same_grocery_shares_a_key(self, a, b):
        assert _key(a) == _key(b)


class TestCategorisation:
    """A more specific keyword must win over a generic one in another aisle."""

    @pytest.mark.parametrize("name", [
        "Black pepper",
        "Red pepper flakes",
        "Garlic powder",
        "Onion powder",
        "Pumpkin pie spice",
        "Cajun seasoning",
        "Everything bagel seasoning",
        "Low-sodium taco seasoning",
        "Herbes de Provence",
    ])
    def test_seasonings_are_not_produce(self, name):
        assert _cat(name) == "Herbs & Spices"

    @pytest.mark.parametrize("name,category", [
        ("Tomato paste", "Condiments & Sauces"),
        ("No-salt-added tomato paste", "Condiments & Sauces"),
        ("Prepared horseradish", "Condiments & Sauces"),
        ("Classic hummus", "Condiments & Sauces"),
        ("Red curry paste", "Condiments & Sauces"),
        ("Cornstarch", "Pantry & Baking"),
        ("Espresso powder", "Pantry & Baking"),
        ("Unflavored gelatin powder", "Pantry & Baking"),
        ("Firm tofu", "Grains, Starches & Legumes"),
        ("Tempeh", "Grains, Starches & Legumes"),
        ("Lean flank steak", "Meat & Poultry"),
        ("Lean bison", "Meat & Poultry"),
        ("Mahi-mahi fillets", "Fish & Seafood"),
        ("Untreated flounder fillets", "Fish & Seafood"),
        ("Hemp hearts", "Nuts & Seeds"),
        ("Unsalted pumpkin seeds", "Nuts & Seeds"),
        ("Brussels sprouts", "Produce — Vegetables"),
        ("Jalapeño", "Produce — Vegetables"),
        ("Chopped collard greens", "Produce — Vegetables"),
        ("Red bell pepper", "Produce — Vegetables"),
        ("Mini peppers", "Produce — Vegetables"),
        ("Raspberries", "Produce — Fruit"),
        ("Tart cherries", "Produce — Fruit"),
        # Generic tokens must not drag a specific product into the wrong aisle:
        # "sprout" once pulled sprouted bread into produce, and "pepper" beat
        # "hummus" on a length tie.
        ("Sprouted whole-grain bread", "Grains, Starches & Legumes"),
        ("Red pepper hummus", "Condiments & Sauces"),
    ])
    def test_lands_in_the_right_aisle(self, name, category):
        assert _cat(name) == category

    def test_unknown_item_falls_through(self):
        assert _cat("zzz nonexistent foodstuff") == UNCATEGORIZED


class TestSameGroceryOneLine:
    """The user-facing rule: one grocery, one name, one quantity."""

    @pytest.mark.parametrize("a,b", [
        # size / prep-cut wording
        ("Medium zucchini", "Zucchinis"),
        ("Cremini mushrooms", "Pre-sliced cremini mushrooms"),
        ("Shredded cheddar", "Pre-shredded cheddar"),
        ("Bagged shredded carrots", "Matchstick carrots"),
        ("Red cabbage", "Bagged shredded red cabbage"),
        # market synonyms
        ("Scallions", "Green onions"),
        ("Garlic", "Garlic cloves"),
        ("English cucumber", "Cucumber"),
        ("Hass avocado", "Avocado"),
        ("Raw pepitas", "Raw pumpkin seeds"),
        ("Hemp hearts", "Hulled hemp seeds"),
        ("Chickpeas", "Garbanzo beans"),
        # equivalent label claims
        ("Reduced-sodium soy sauce", "Low-sodium soy sauce"),
        ("Reduced-fat cheddar", "Low-fat cheddar"),
        ("Non-fat Greek yogurt", "Nonfat Greek yogurt"),
        ("Salt-free Cajun seasoning", "No-salt-added Cajun seasoning"),
        # marketing words that don't change the purchase
        ("Maple syrup", "Pure maple syrup"),
        ("Vanilla extract", "Pure vanilla extract"),
        ("Almond flour", "Blanched almond flour"),
        ("Natural peanut butter", "Natural creamy peanut butter"),
        ("Rice vinegar", "Unseasoned rice vinegar"),
        # punctuation and parentheticals
        ("Salt, divided", "Salt"),
        ("Boneless, skinless chicken breast", "Boneless skinless chicken breasts"),
        ("Low-fat cottage cheese (2% milkfat)", "Low-fat cottage cheese"),
        ("Liquid egg whites (carton)", "Pasteurized liquid egg whites"),
        ("No-salt-added black beans, rinsed and drained", "No-salt-added black beans"),
        ("Fresh or frozen cod fillets", "Cod fillets"),
        ("Whole eggs", "Eggs"),
        # word order / tail collapse
        ("Frozen riced cauliflower", "Frozen cauliflower rice"),
        ("Tricolor coleslaw mix", "Pre-shredded cabbage coleslaw mix"),
    ])
    def test_merges_to_one_line(self, a, b):
        assert _key(a) == _key(b), f"{a!r} and {b!r} should share a shopping line"

    @pytest.mark.parametrize("a,b", [
        # diet-critical markers — the book's sodium targets depend on these
        ("No-salt-added kidney beans", "Canned kidney beans"),
        ("No-salt-added black beans", "Low-sodium black beans"),
        ("Unsalted almonds", "Salted almonds"),
        ("Low-sodium chicken broth", "Chicken broth"),
        # preservation form — different aisle, different product
        ("Fresh raspberries", "Frozen raspberries"),
        ("Fresh dill", "Dried dill"),
        ("Dry brown lentils", "Canned brown lentils"),
        ("Crushed tomatoes", "Diced tomatoes"),
        # form / cut that really is a different purchase
        ("Ground chicken breast", "Raw chicken breast"),
        ("Chicken breast tenders", "Chicken breast"),
        ("Raw almonds", "Sliced almonds"),
        ("Sliced almonds", "Slivered almonds"),
        ("Sweet potato", "Potato"),
        ("Silken tofu", "Firm tofu"),
        ("Mini cucumbers", "Cucumber"),
        ("Olive oil cooking spray", "Olive oil"),
        ("Rolled oats", "Quick oats"),
    ])
    def test_stays_separate(self, a, b):
        assert _key(a) != _key(b), f"{a!r} and {b!r} are different purchases"


class TestPrintedNameIsHonest:
    """Stripping a qualifier must never send the shopper to the wrong aisle."""

    @pytest.mark.parametrize("raw,expected", [
        ("Low-fat cottage cheese (2% milkfat)", "Low-fat cottage cheese"),
        ("Extra-lean ground beef (96% lean)", "Extra-lean ground beef"),
        ("Salt, divided", "Salt"),
        ("No-salt-added black beans, rinsed and drained", "No-salt-added black beans"),
    ])
    def test_cleaned(self, raw, expected):
        assert _strip_qualifiers_from_display(raw) == expected

    @pytest.mark.parametrize("raw,word", [
        ("Jarred roasted red peppers", "roasted"),
        ("Lean ground chicken", "ground"),
        ("Frozen blackberries", "Frozen"),
        ("Dried tart cherries", "Dried"),
        ("Olive oil cooking spray", "spray"),
        ("Canned sardines in water", "water"),
    ])
    def test_product_identifying_word_survives(self, raw, word):
        assert word in _strip_qualifiers_from_display(raw)


class TestUnsafeMergeGuard:
    """The LLM merge pass clusters on token overlap and over-generalises. Every
    case here was produced by it against this book and would have put a
    different product on the shopping line."""

    ALL_KEYS = {
        "kidney bean", "no salt added kidney bean", "no salt added dark red kidney bean",
        "almond", "unsalted almond", "sliced almond", "soy sauce",
        "low sodium soy sauce", "cucumber", "english cucumber", "salt", "kosher salt",
        "chicken breast", "boneless skinless chicken thigh", "ground chicken breast",
        "low sodium chicken broth", "low sodium vegetable broth",
        "raspberry", "frozen raspberry", "dill", "dried dill", "tomato", "roma tomato",
        "lean ground pork", "lean ground beef",
    }

    @pytest.mark.parametrize("raw,canonical,reason", [
        # invented category that is not a real ingredient key
        ("lean ground pork", "ground meat", "invented target"),
        ("lean ground beef", "ground meat", "invented target"),
        ("low sodium chicken broth", "low sodium broth", "invented target"),
        # drops a diet-critical marker
        ("no salt added kidney bean", "kidney bean", "loses no-salt-added"),
        ("unsalted almond", "almond", "loses unsalted"),
        ("low sodium soy sauce", "soy sauce", "loses low-sodium"),
        # drops a product-identifying word
        ("boneless skinless chicken thigh", "chicken breast", "thigh is not breast"),
        ("ground chicken breast", "chicken breast", "ground is not whole"),
        ("frozen raspberry", "raspberry", "frozen is not fresh"),
        ("dried dill", "dill", "dried is not fresh"),
        ("sliced almond", "almond", "different bag"),
        ("roma tomato", "tomato", "different pack"),
    ])
    def test_rejects(self, raw, canonical, reason):
        kept, rejected = _reject_unsafe_merges({raw: canonical}, self.ALL_KEYS)
        assert kept == {}, f"should have rejected ({reason})"
        assert rejected == [raw]

    @pytest.mark.parametrize("raw,canonical", [
        ("kosher salt", "salt"),
        ("english cucumber", "cucumber"),
        ("no salt added dark red kidney bean", "no salt added kidney bean"),
    ])
    def test_keeps_genuine_merges(self, raw, canonical):
        kept, rejected = _reject_unsafe_merges({raw: canonical}, self.ALL_KEYS)
        assert kept == {raw: canonical}
        assert rejected == []


class TestDisplayCase:
    @pytest.mark.parametrize("raw,shown", [
        ("arugula", "Arugula"),
        ("red bell pepper", "Red bell pepper"),
        ("Celery", "Celery"),
        ("  spinach", "Spinach"),
    ])
    def test_sentence_cased(self, raw, shown):
        assert _display_case(raw) == shown

    def test_interior_proper_nouns_survive(self):
        assert _display_case("greek yogurt, Dijon mustard") == "Greek yogurt, Dijon mustard"

    def test_empty_is_safe(self):
        assert _display_case("") == ""
