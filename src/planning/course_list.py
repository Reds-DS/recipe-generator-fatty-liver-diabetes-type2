"""Aggregate recipe ingredients across a meal plan into a course list."""
import json
import re
import unicodedata
from pathlib import Path

from rich.console import Console

from src.config import DATA_DIR
from src.models.meal_plan import (
    CourseItem,
    CourseItemSource,
    CourseList,
    MealPlan,
)
from src.models.recipe import Ingredient, Recipe

CATEGORY_FILE = DATA_DIR / "ingredient_categories.json"
UNCATEGORIZED = "Other"

# Nobody shops for tap water or ice. Matched against the aggregation key, so
# these are already accent-folded, lowercased and singularised.
_SHOPPING_SKIP_KEYS: frozenset[str] = frozenset({
    "water", "cold water", "warm water", "hot water", "filtered water",
    "tap water", "ice", "ice cube", "ice water", "boiling water",
})

_console = Console()


def build_course_list(
    plan: MealPlan,
    recipes_by_id: dict[str, Recipe],
    *,
    book_dir: Path | None = None,
    use_llm_aliases: bool = False,
    display_overrides: dict[str, str] | None = None,
) -> CourseList:
    """Collect ingredients across every slot; group, sum, categorise, format.

    When `use_llm_aliases=True` (and `book_dir` is given), an extra LLM-backed
    pass clusters look-alike rule-based keys and merges those that the LLM
    confirms are the same product. Decisions are cached in `<book>/aliases.db`
    so subsequent runs are deterministic + free.

    `display_overrides` pins `{canonical_name: printed name}`. Without it the
    printed name is chosen from whichever recipes happen to fall in this slice,
    so the same ingredient can appear as "Extra-virgin olive oil" one week and
    "Olive oil" the next. Callers building several weeks of one plan should
    resolve the names once over the whole plan and pass them in — see
    `week_slicer.build_weeks`.
    """
    main = _collect(plan, recipes_by_id, optional_bucket=False)
    optional = _collect(plan, recipes_by_id, optional_bucket=True)

    if use_llm_aliases and book_dir is not None:
        main = _resolve_aliases(main, book_dir, plan.manifest.objective, "main")
        optional = _resolve_aliases(optional, book_dir, plan.manifest.objective, "optional")

    category_map = _load_category_map()

    items_by_category: dict[str, list[CourseItem]] = {}
    for agg in main.values():
        item = agg.to_course_item(
            is_optional=False, category_map=category_map,
            display_overrides=display_overrides,
        )
        items_by_category.setdefault(item.category, []).append(item)

    for cat in items_by_category:
        items_by_category[cat].sort(key=lambda i: i.display_name.lower())

    optional_items = [
        agg.to_course_item(
            is_optional=True, category_map=category_map,
            display_overrides=display_overrides,
        )
        for agg in optional.values()
    ]
    optional_items.sort(key=lambda i: i.display_name.lower())

    return CourseList(
        cookbook_name=plan.cookbook_name,
        plan_days=len(plan.days),
        items_by_category=items_by_category,
        optional_items=optional_items,
    )


def _collect(
    plan: MealPlan,
    recipes_by_id: dict[str, Recipe],
    *,
    optional_bucket: bool,
) -> dict[str, "_Aggregate"]:
    """First-pass aggregation using only rule-based keys."""
    out: dict[str, _Aggregate] = {}
    for day in plan.days:
        for slot in day.slots:
            recipe = recipes_by_id.get(slot.recipe_id)
            if recipe is None:
                continue
            for ing in recipe.ingredients:
                if ing.is_optional != optional_bucket:
                    continue
                key = _agg_key(ing)
                if key in _SHOPPING_SKIP_KEYS:
                    continue
                agg = out.setdefault(
                    key,
                    _Aggregate(canonical_name=key, display_name=ing.name),
                )
                if _display_score(ing.name) < _display_score(agg.display_name):
                    agg.display_name = ing.name
                agg.total_g += float(ing.quantity_g)
                agg.sources.append(CourseItemSource(
                    day=slot.day,
                    meal_type=slot.meal_type,
                    recipe_title=slot.recipe_title,
                    quantity_g=float(ing.quantity_g),
                ))
    return out


# Markers the book's diet rules depend on. If an ingredient carries one, it may
# only merge into a key that carries it too — otherwise the shopper is sent home
# with the salted can and the plan's sodium targets are quietly broken.
_PROTECTED_MARKERS: tuple[str, ...] = (
    "no salt added", "low sodium", "salt free", "unsalted", "untreated",
    "no added sugar", "unsweetened", "sugar free",
)


# Words the LLM may never drop when merging. Each one names the product rather
# than describing it: dropping "pork" turned five different meats into one
# "Ground meat" line, dropping "thigh" filed chicken thighs under breasts, and
# dropping "frozen" undid the fresh/frozen split the rules deliberately make.
_UNDROPPABLE_TOKENS: frozenset[str] = frozenset({
    # preservation / form the rule layer keeps on purpose
    "frozen", "dried", "dry", "ground", "roasted", "smoked", "crushed", "spray",
    "sliced", "slivered", "liquid", "chip",
    # derived-from, not the thing itself
    "zest", "juice",
    # cut / part
    "thigh", "breast", "tender", "tenderloin", "drumstick", "wing", "ball",
    # base identity — a broth or a mince is defined by what it is made of
    "chicken", "beef", "pork", "turkey", "bison", "lamb", "veal", "vegetable",
    "salmon", "tuna", "shrimp", "cod", "meat",
    # varieties sold as separate packs
    "cherry", "grape", "roma",
})


def _reject_unsafe_merges(
    remap: dict[str, str],
    valid_keys: set[str],
) -> tuple[dict[str, str], list[str]]:
    """Keep only LLM merges that are safe to put on a shopping list.

    Two rules, both learned from real damage in this book's lists:

    1. **The target must already exist as an ingredient key.** The LLM likes to
       invent a generalisation — five ``lean ground <animal>`` keys became one
       invented ``ground meat``. It may merge A into B, never into a category.
    2. **No product-identifying word may be dropped** (`_UNDROPPABLE_TOKENS`,
       plus the diet markers in `_PROTECTED_MARKERS`). This is what stops
       ``low sodium chicken broth`` becoming ``low sodium broth``.

    Merges that only shed a descriptive word still go through, so the useful
    ones ("kosher salt" → "salt", "english cucumber" → "cucumber") survive.
    """
    kept: dict[str, str] = {}
    rejected: list[str] = []
    for raw, canonical in remap.items():
        if canonical == raw:
            kept[raw] = canonical
            continue
        if canonical not in valid_keys:
            rejected.append(raw)
            continue
        if any(m in raw and m not in canonical for m in _PROTECTED_MARKERS):
            rejected.append(raw)
            continue
        dropped = set(raw.split()) - set(canonical.split())
        if dropped & _UNDROPPABLE_TOKENS:
            rejected.append(raw)
            continue
        kept[raw] = canonical
    return kept, rejected


def _resolve_aliases(
    buckets: dict[str, "_Aggregate"],
    book_dir: Path,
    cookbook_objective: str,
    label: str,
) -> dict[str, "_Aggregate"]:
    """LLM-backed merge pass over rule-based aggregation buckets.

    Caches every decision in `<book>/aliases.db`. Falls back gracefully (no
    error to caller) if the LLM call fails — the rule-based result is used.
    """
    from src.planning.alias_cache import AliasCache, jaccard_clusters

    cache = AliasCache(book_dir)
    raw_keys = list(buckets.keys())

    # 1. Pull cached decisions.
    remap: dict[str, str] = {}             # raw_key -> canonical_key
    cached_displays: dict[str, str] = {}   # canonical_key -> display
    for raw in raw_keys:
        hit = cache.get(raw)
        if hit:
            canonical_key, canonical_display = hit
            remap[raw] = canonical_key
            if canonical_display:
                cached_displays.setdefault(canonical_key, canonical_display)

    # 2. Cluster the unresolved keys.
    unresolved = [k for k in raw_keys if k not in remap]
    clusters = jaccard_clusters(unresolved, threshold=0.5)
    _console.print(
        f"[dim]  alias ({label}): {len(raw_keys)} keys, "
        f"{len(unresolved)} unresolved, {len(clusters)} clusters[/dim]"
    )

    # 3. Ask the LLM about the unresolved clusters (single batched call).
    if clusters:
        _console.print(f"[dim]  alias ({label}): LLM call on {len(clusters)} clusters...[/dim]")
        try:
            llm_remap, llm_displays = _llm_resolve_clusters(
                clusters, cookbook_objective, buckets,
            )
            llm_remap, rejected = _reject_unsafe_merges(llm_remap, set(raw_keys))
            _console.print(f"[dim]  alias ({label}): LLM OK, {len(llm_remap)} mappings[/dim]")
            if rejected:
                _console.print(
                    f"[yellow]  alias ({label}): rejected {len(rejected)} unsafe "
                    f"merge(s) — would have put a different product on the same "
                    f"line ({', '.join(sorted(rejected)[:3])}…)[/yellow]"
                )
            remap.update(llm_remap)
            cached_displays.update(llm_displays)

            # Persist for next run.
            to_register: dict[str, tuple[str, str | None, str]] = {}
            for raw in {r for cluster in clusters for r in cluster}:
                canonical = remap.get(raw, raw)
                display = cached_displays.get(canonical)
                to_register[raw] = (canonical, display, "llm")
            cache.bulk_register(to_register)
        except Exception as e:  # noqa: BLE001
            _console.print(
                f"[yellow]LLM alias resolution ({label}) failed — "
                f"keeping the rule-based merge. Detail: {e!r}[/yellow]"
            )

    # 4. Identity remap for everything still untouched (rule-only).
    rule_register: dict[str, tuple[str, str | None, str]] = {}
    for raw in raw_keys:
        if raw not in remap:
            remap[raw] = raw
            rule_register[raw] = (raw, None, "rule")
    cache.bulk_register(rule_register)

    # 5. Re-bucket using the remap.
    merged: dict[str, _Aggregate] = {}
    for raw, agg in buckets.items():
        canonical_key = remap[raw]
        target = merged.get(canonical_key)
        if target is None:
            new_display = cached_displays.get(canonical_key, agg.display_name)
            target = _Aggregate(canonical_name=canonical_key, display_name=new_display)
            merged[canonical_key] = target
        # Prefer the cached/LLM-suggested display, otherwise reuse the
        # rule-based "best" name from the source aggregate.
        candidate = cached_displays.get(canonical_key, agg.display_name)
        if _display_score(candidate) < _display_score(target.display_name):
            target.display_name = candidate
        target.total_g += agg.total_g
        target.sources.extend(agg.sources)
    return merged


def _llm_resolve_clusters(
    clusters: list[list[str]],
    cookbook_objective: str,
    buckets: dict[str, "_Aggregate"],
) -> tuple[dict[str, str], dict[str, str]]:
    """Ask the LLM to split each cluster into product-level groups.

    Sends the *display names* (more readable for the LLM than the
    accent-folded keys) and reverse-maps the response back to keys.
    """
    import json as _json

    from src.config import settings
    from src.llm import client as llm
    from src.llm.output_schemas import AliasResolverOutput
    from src.llm.prompts import alias_resolver

    # Display name → raw key. If a display collides across keys, last wins —
    # the LLM is told to act on display names, so collisions are inherently merged.
    display_to_key: dict[str, str] = {}
    display_clusters: list[list[str]] = []
    for cluster in clusters:
        display_cluster: list[str] = []
        for raw_key in cluster:
            display = buckets[raw_key].display_name
            display_to_key[display] = raw_key
            display_cluster.append(display)
        display_clusters.append(sorted(set(display_cluster)))

    schema_json = _json.dumps(
        AliasResolverOutput.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )
    user = alias_resolver.build_user(display_clusters, cookbook_objective, schema_json)

    # Alias resolution is a name-matching task — Flash Lite is fast and accurate
    # enough; using Pro thinking on 30 clusters takes minutes and can time out.
    raw_response = llm.create_message_with_model(
        alias_resolver.SYSTEM,
        user,
        model=settings.image_prompt_model,
        max_tokens=4096,
        thinking_budget=2000,
    )
    parsed = AliasResolverOutput.model_validate_json(raw_response)

    # Build remap: every member's key → a synthetic canonical key derived from
    # the LLM's chosen canonical display (run it through _normalise_for_key
    # so it matches our naming convention; equal displays → equal keys).
    remap: dict[str, str] = {}
    displays: dict[str, str] = {}
    for group in parsed.groups:
        canonical_key = _normalise_for_key(group.canonical) or group.canonical.lower()
        displays[canonical_key] = group.canonical
        for member in group.members:
            raw_key = display_to_key.get(member)
            if raw_key is None:
                # LLM returned a name we didn't send — best-effort reverse lookup.
                raw_key = _normalise_for_key(member)
            remap[raw_key] = canonical_key
    return remap, displays


# ── Aggregation helper ──────────────────────────────────────────

class _Aggregate:
    __slots__ = ("canonical_name", "display_name", "total_g", "sources")

    def __init__(self, canonical_name: str, display_name: str) -> None:
        self.canonical_name = canonical_name
        self.display_name = display_name
        self.total_g = 0.0
        self.sources: list[CourseItemSource] = []

    def to_course_item(
        self,
        is_optional: bool,
        category_map: dict[str, list[str]],
        display_overrides: dict[str, str] | None = None,
    ) -> CourseItem:
        pinned = (display_overrides or {}).get(self.canonical_name)
        clean = pinned or _display_case(
            _strip_qualifiers_from_display(self.display_name)
        )
        return CourseItem(
            canonical_name=self.canonical_name,
            display_name=clean,
            total_quantity_g=round(self.total_g, 1),
            total_quantity_display=format_quantity(self.total_g),
            category=_categorize(self.canonical_name, category_map),
            is_optional=is_optional,
            source_recipes=self.sources,
        )


# ── Category map + matching ─────────────────────────────────────

_CATEGORY_MAP_CACHE: dict[str, list[str]] | None = None
# Flattened (keyword, category) pairs, most-specific keyword first. See
# `_categorize` for why the ranking has to be global rather than per-category.
_CATEGORY_RANKED_CACHE: list[tuple[str, str]] | None = None


def _load_category_map() -> dict[str, list[str]]:
    """Load `ingredient_categories.json` once; keywords are pre-normalised."""
    global _CATEGORY_MAP_CACHE
    if _CATEGORY_MAP_CACHE is not None:
        return _CATEGORY_MAP_CACHE

    if not CATEGORY_FILE.exists():
        _CATEGORY_MAP_CACHE = {}
        return _CATEGORY_MAP_CACHE

    raw = json.loads(CATEGORY_FILE.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for category, keywords in raw.get("categories", {}).items():
        out[category] = sorted(
            {_normalise_keyword(k) for k in keywords},
            key=lambda s: -len(s),  # longest first — avoids prefix collisions
        )
    _CATEGORY_MAP_CACHE = out
    return out


def _ranked_keywords(category_map: dict[str, list[str]]) -> list[tuple[str, str]]:
    """`(keyword, category)` pairs ordered longest keyword first.

    Ties keep the category order of the JSON file, which is the aisle order a
    shopper walks, so equally-specific matches stay stable.
    """
    global _CATEGORY_RANKED_CACHE
    if _CATEGORY_RANKED_CACHE is not None and category_map is _CATEGORY_MAP_CACHE:
        return _CATEGORY_RANKED_CACHE

    pairs = [
        (kw, category)
        for order, (category, keywords) in enumerate(category_map.items())
        for kw in keywords
        if kw
    ]
    order_of = {c: i for i, c in enumerate(category_map)}
    pairs.sort(key=lambda p: (-len(p[0]), order_of[p[1]], p[0]))
    if category_map is _CATEGORY_MAP_CACHE:
        _CATEGORY_RANKED_CACHE = pairs
    return pairs


def _categorize(canonical_name: str, category_map: dict[str, list[str]]) -> str:
    """Assign a shopping aisle by the *most specific* keyword that matches.

    Ranking has to be global, not per-category: several categories share a
    generic token, and the first category in file order used to win outright.
    "Black pepper" matched Produce's bare "pepper" before Herbs & Spices'
    "black pepper" was ever considered, so seasonings were sent to the produce
    aisle. Longest keyword across all categories wins instead.
    """
    haystack = _normalise(canonical_name)
    if not haystack:
        return UNCATEGORIZED
    for kw, category in _ranked_keywords(category_map):
        if kw in haystack:
            return category
    return UNCATEGORIZED


def _agg_key(ing: Ingredient) -> str:
    """Normalised key for shopping-list aggregation.

    Uses the user-facing `name` (e.g. "plain yogurt") rather than the USDA
    `canonical_name` (e.g. "Yogurt, plain, whole milk") because the canonical
    is far too granular for grocery shopping — several USDA entries map to the
    same item on a shopping list.

    Normalisation merges case / underscore / plural variants:
      "lemon_juice" + "Lemon juice"      → "lemon juice"
      "red onions" + "red onion"         → "red onion"
    """
    base = ing.name.strip() or ing.canonical_name.strip()
    return _normalise_for_key(base)


# ── Pre-tokenisation cleanup ────────────────────────────────────
# Recipe authors write the same grocery a dozen ways. These run on the raw
# lowercased string, before it is split into tokens, because each one is about
# punctuation or word order rather than individual words.

# "(96% lean)", "(2% milkfat)", "(carton)", "(8 inch)", "(pepitas)". Removing
# the whole parenthetical also avoids the empty "( )" left behind when the
# percentage inside it is stripped.
_PAREN_RE = re.compile(r"\([^)]*\)")

# "Fresh or frozen raspberries" → tokenising left a phantom "or raspberry"
# entry sitting alongside the real one.
_FRESH_OR_RE = re.compile(
    r"\b(?:fresh|frozen|thawed|chilled)\s+or\s+(?:fresh|frozen|thawed|chilled)\b"
)

# "canned sardines in water" → "canned sardines" (the packing medium is not a
# separate grocery, and leaving it in printed "Sardines water").
_PACKING_RE = re.compile(
    r"\b(?:packed\s+)?in\s+(?:its\s+own\s+)?(?:water|juice|brine|olive\s+oil|oil)\b"
)
_WATER_PACKED_RE = re.compile(r"\bwater[\s-]packed\b")

# "Tomatoes, no-salt-added" must land on the same key as "No-salt-added
# tomatoes" — same can, qualifier written at the other end.
_TRAILING_QUAL_RE = re.compile(
    r"^(?P<head>.*?),\s*(?P<qual>no[\s-]salt[\s-]added|low[\s-]sodium|unsalted|"
    r"no[\s-]sugar[\s-]added|no[\s-]added[\s-]sugar)\s*$"
)


def _pre_clean(folded_lc: str) -> str:
    """Punctuation- and word-order-level tidying, before tokenisation."""
    out = _FRESH_OR_RE.sub(" ", folded_lc)
    out = _PAREN_RE.sub(" ", out)
    out = _WATER_PACKED_RE.sub(" ", out)
    out = _PACKING_RE.sub(" ", out)
    out = re.sub(r"\b\d+\s*%", " ", out)               # "0%", "20 %" → ""
    # Reorder a trailing qualifier to the front. Runs while commas survive.
    match = _TRAILING_QUAL_RE.match(" ".join(out.split()))
    if match:
        out = f"{match.group('qual')} {match.group('head')}"
    return out


def _normalise_for_key(text: str) -> str:
    """NFD accent-fold + lowercase + punctuation→space + plural strip + drop qualifiers.

    Drops cooking-state, packaging, and quality tokens
    ("cooked", "raw", "canned", "whole-grain", "0%"…) and key-only
    markers ("plain", "organic") so visually-similar groceries collapse to one
    item. Colour tokens (white/red/black/green/yellow) stay — they identify
    the variety, and so do preservation words ("frozen") and forms ("ground"),
    because those send you to a different aisle.

    Special collapses:
      - leading "slices of" / "slice of" stripped
      - "powdered" alias to "powder" ("garlic powdered" + "garlic powder" merge)
      - "lemon zest <anything>" truncated to "lemon zest"
      - multi-word synonyms via `_PHRASE_ALIASES` ("green onion" → "scallion")
    """
    folded = "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )
    folded = _pre_clean(folded.lower())
    # Commas and slashes separate tokens too — "boneless, skinless chicken" and
    # "Salt, divided" were each producing their own shopping line.
    folded = re.sub(r"[_\-'`’,;/]", " ", folded)
    folded = " ".join(folded.split())
    folded = _strip_prefix(folded)

    words = [_singularise(w) for w in folded.split()]
    words = [_KEY_ALIASES.get(w, w) for w in words]
    words = _apply_phrase_aliases(words)
    head = [w for w in words
            if w not in _STRIP_BOTH and w not in _STRIP_KEY_ONLY]
    if not head:
        head = words

    # Collapse "lemon zest *" → "lemon zest"
    if head[:2] == ["lemon", "zest"]:
        head = ["lemon", "zest"]

    # "… coleslaw mix" is one bag however it is described.
    for tail in _COLLAPSE_TO_TAIL:
        if len(head) > len(tail) and tuple(head[-len(tail):]) == tail:
            head = list(tail)
            break

    return " ".join(head)


def _strip_prefix(folded_lc: str) -> str:
    """Remove leading 'slices of' / 'slice of' (already accent-folded, lc)."""
    for prefix in ("slices of ", "slice of "):
        if folded_lc.startswith(prefix):
            return folded_lc[len(prefix):]
    return folded_lc


# Words ending this way are not plurals — "hummus", "asparagus", "couscous",
# "watercress", "molasses". Stripping the -s would both split the shopping line
# and stop the category keywords matching. "sses" is listed separately from
# "ss" so that genuine plurals like "cheeses" still reduce to "cheese".
#
# "is" is NOT a suffix rule: it would protect "zucchinis" and "kiwis", which are
# ordinary plurals. The handful of real -is words are listed explicitly instead.
_NON_PLURAL_ENDINGS = ("us", "ss", "sses")
_NON_PLURAL_WORDS: frozenset[str] = frozenset({
    "analysis", "basis", "oasis", "iris", "chassis",
})


def _singularise(word: str) -> str:
    """Reduce an English plural to its singular for merging and keyword matching.

    A bare "drop the trailing -s" is not enough: it turns "raspberries" into
    "raspberrie" and "tomatoes" into "tomatoe", neither of which matches the
    singular spelling. That silently split shopping lines ("tomato" and
    "tomatoes" as two entries) and left whole items uncategorised. Handle the
    regular -ies/-oes/-es patterns explicitly; the length guard keeps short
    tokens like "oat" intact.
    """
    if len(word) <= 3 or not word.endswith("s"):
        return word
    if word.endswith(_NON_PLURAL_ENDINGS) or word in _NON_PLURAL_WORDS:
        return word
    if len(word) > 4:
        if word.endswith("ies"):
            return word[:-3] + "y"          # raspberries → raspberry
        if word.endswith("oes"):
            return word[:-2]                # tomatoes → tomato
        if word.endswith(("ches", "shes", "xes", "zes")):
            return word[:-2]                # squashes → squash
    return word[:-1]


def _normalise_keyword(text: str) -> str:
    """Normalise a category keyword the same way the haystack is normalised.

    The haystack reaching `_categorize` has been through `_normalise_for_key`,
    which singularises every word. Keywords have to be singularised too or a
    plural-only keyword ("anchovies") can never match its own item.
    Deliberately does *not* strip qualifier tokens the way `_normalise_for_key`
    does — that would flatten "ground beef" to "beef" and lose specificity.
    """
    folded = "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )
    folded = re.sub(r"[_\-'`’]", " ", folded.lower())
    return " ".join(_singularise(w) for w in folded.split())


# Tokens stripped from BOTH key and display.
# Stored in their singularised, accent-folded form (that's what _normalise_for_key produces).
# Colour tokens (white/red/black/green/yellow) are intentionally absent — they identify variety.
_STRIP_BOTH: frozenset[str] = frozenset({
    # cooking state
    "raw",
    "cooked", "uncooked", "precooked",
    "boiled", "baked", "grilled", "steamed", "sauteed",
    # NOTE: "roasted", "smoked", "ground", "crushed", "spray" and "frozen" are
    # deliberately absent. Each names the product, not a detail of it: dropping
    # them printed "Jarred roasted red peppers" as "Red peppers", "Lean ground
    # chicken" as "Lean chicken", and pooled frozen berries with fresh ones.
    "fresh",            # unmarked produce is fresh — "fresh apples" == "apples"
    # NOTE: "dried"/"dry" are absent for the same reason as "frozen". Dried dill
    # is a spice jar and fresh dill is a herb bunch; dry lentils need 25 minutes
    # of simmering and canned ones do not. Stripping it merged both pairs.
    "drain", "drained",
    # quality / processing
    "wholegrain", "wholewheat",
    "lowfat", "lite", "light", "reduced",
    "skinles", "skinnles", "boneles",  # "skinless" / "boneless" minus the -s
    "cracked",
    "refined", "unrefined",
    "iodized", "iodised",
    "virgin",
    "extra",
    # "sweet" is deliberately NOT stripped: it collapsed "sweet potato" into
    # "potato", putting two different vegetables on one shopping line. Losing
    # the "sweet corn"/"corn" merge is a far smaller cost than sending someone
    # home with the wrong potato.
    "sea",              # "sea salt"
    "fine", "coarse",   # "fine salt", "coarse salt"
    # variety qualifiers that don't change what you buy
    "small", "medium", "large", "big",
    "long", "round", "short",
    "baby",
    # how it was cut — the cut is not the product. "sliced" and "slivered" are
    # excluded on purpose: raw / sliced / slivered almonds are three bags.
    "chopped", "minced", "cubed", "crumbled", "grated", "matchstick",
    "halved", "quartered", "halve", "floret", "spear", "stalk", "cap",
    "shredded", "piece", "chunk",
    "thin", "thick",
    # packaging nouns
    "bagged", "bag", "package", "packaged", "packet", "carton",
    "container", "box", "boxed", "pouch", "tub", "bunch", "head",
    # orphan left by "pre-sliced" / "pre-shredded" / "pre-cooked" once the
    # hyphen becomes a space
    "pre",
    "store", "bought", "microwavable",
    # prep done at home, not at the shop
    "rinsed", "rinse", "peeled", "deveined", "trimmed", "pitted",
    "stemmed", "washed", "shelled", "hulled", "blanched", "toasted",
    "divided", "packed",
    # marketing filler
    "style", "blend", "classic",
})

# Tokens stripped from KEY ONLY (kept in display so user sees the quality marker).
# These collapse the merge but leave the badge visible.
#
# Diet-critical markers are NOT here on purpose. "unsalted", "untreated",
# "no salt added" and "low sodium" must keep their own key — the book's sodium
# targets depend on buying that version, so merging them into the plain product
# would put the wrong can in the basket.
_STRIP_KEY_ONLY: frozenset[str] = frozenset({
    "plain", "unsweetened",
    "organic",
    "pure",                       # "Pure maple syrup" == "maple syrup"
    "natural", "creamy", "smooth",
    "unseasoned",
    "pasteurized", "pasteurised",
    "mild",                       # canned diced green chiles are mild by default
    "prepared",
    # merge-but-keep-visible: these were mangling printed names
    # ("Canned sardines in water" → "Sardines water")
    "canned", "can", "jarred", "jar", "bottled", "bottle",
    "and", "of", "in", "the",
})

# Token aliases applied during key normalisation AND display rebuild —
# powdered ⇌ powder lets "Garlic powdered" and "Garlic powder" share a key.
# One word in, one word out; anything else needs `_PHRASE_ALIASES`.
_KEY_ALIASES: dict[str, str] = {
    "powdered": "powder",
    # UK / market-name synonyms for the same item
    "garbanzo": "chickpea",
    "courgette": "zucchini",
    "aubergine": "eggplant",
    "rocket": "arugula",
    "prawn": "shrimp",
    "beetroot": "beet",
}
_DISPLAY_ALIASES: dict[str, str] = dict(_KEY_ALIASES)

# Multi-word synonyms, word-order fixes, and equivalent label claims. Applied
# to the token list (longest phrase first) BEFORE the strip pass, so that e.g.
# "reduced fat" → "low fat" never leaves an orphan "fat" behind.
#
# Deliberately absent: coriander → cilantro. Ground coriander is a dry spice
# and cilantro is the fresh herb; they are not interchangeable purchases.
_PHRASE_ALIASES: dict[tuple[str, ...], tuple[str, ...]] = {
    # market synonyms
    ("green", "onion"): ("scallion",),
    ("spring", "onion"): ("scallion",),
    ("garlic", "clove"): ("garlic",),          # NOT a bare "clove" — that's a spice
    ("english", "cucumber"): ("cucumber",),
    ("hass", "avocado"): ("avocado",),
    ("pepita",): ("pumpkin", "seed"),
    ("hemp", "heart"): ("hemp", "seed"),
    ("pita", "bread"): ("pita",),
    ("chickpea", "bean"): ("chickpea",),   # after garbanzo → chickpea
    ("whole", "egg"): ("egg",),
    ("basil", "leave"): ("basil",),
    # word-order normalisation — same bag, described backwards
    ("riced", "cauliflower"): ("cauliflower", "rice"),
    ("flaked", "coconut"): ("coconut",),
    ("shredded", "coconut"): ("coconut",),
    ("coconut", "flake"): ("coconut",),
    # equivalent label claims
    ("non", "fat"): ("nonfat",),
    ("fat", "free"): ("nonfat",),
    ("reduced", "fat"): ("low", "fat"),
    ("reduced", "sodium"): ("low", "sodium"),
    ("salt", "free"): ("no", "salt", "added"),
    ("no", "added", "sugar"): (),
    ("no", "sugar", "added"): (),
    # variety words that don't change what you put in the basket
    ("sweet", "corn"): ("corn",),
    ("sweet", "pea"): ("pea",),
    ("green", "pea"): ("pea",),
    ("dark", "red", "kidney", "bean"): ("kidney", "bean"),
    ("bell", "pepper", "onion"): ("pepper", "onion"),
    ("sliced", "bell", "pepper"): ("bell", "pepper"),
    ("mini", "sweet", "bell", "pepper"): ("mini", "sweet", "pepper"),
    ("turkey", "breast", "tenderloin"): ("turkey", "tenderloin"),
    ("old", "fashioned", "rolled", "oat"): ("rolled", "oat"),
    ("thin", "sliced"): (),
    # A convenience pre-cut, not a different product. Handled as a phrase so
    # that bare "sliced" stays meaningful — raw / sliced / slivered almonds are
    # three different bags on the shelf.
    ("pre", "sliced"): (),
    ("pre", "shredded"): (),
}

# Longest first so "mini sweet bell pepper" wins over "bell pepper".
_PHRASE_ALIAS_ORDER: tuple[tuple[str, ...], ...] = tuple(
    sorted(_PHRASE_ALIASES, key=len, reverse=True)
)

# A key ENDING with one of these collapses to it entirely — "tricolor coleslaw
# mix", "pre-shredded cabbage coleslaw mix" and friends are all one bag.
_COLLAPSE_TO_TAIL: tuple[tuple[str, ...], ...] = (
    ("coleslaw", "mix"),
)


def _apply_phrase_aliases(words: list[str]) -> list[str]:
    """Rewrite multi-word synonyms in a token list, longest phrase first."""
    out = list(words)
    for phrase in _PHRASE_ALIAS_ORDER:
        n = len(phrase)
        if n > len(out):
            continue
        replacement = _PHRASE_ALIASES[phrase]
        i = 0
        rebuilt: list[str] = []
        while i < len(out):
            if tuple(out[i:i + n]) == phrase:
                rebuilt.extend(replacement)
                i += n
            else:
                rebuilt.append(out[i])
                i += 1
        out = rebuilt
    return out


def _is_strip_both_word(word: str) -> bool:
    """Check if a single word is a 'strip from display' qualifier."""
    folded = "".join(
        ch for ch in unicodedata.normalize("NFD", word.lower())
        if unicodedata.category(ch) != "Mn"
    )
    folded = re.sub(r"[_\-'`’]", " ", folded).strip()
    if not folded:
        return False
    return _singularise(folded) in _STRIP_BOTH


def _display_score(name: str) -> tuple[int, int]:
    """Lower is better: (qualifier-token count, total length).

    Counts only _STRIP_BOTH qualifiers (so 'plain tomato puree' beats
    'tomato puree' — both have zero strip-both qualifiers, longer wins
    because we want to keep the 'plain' marker visible)."""
    tokens = name.split()
    quals = sum(1 for t in tokens if _is_strip_both_word(t))
    # We want to KEEP nature/bio in display, so prefer the variant
    # that includes them (longer name, fewer tokens to strip later).
    return (quals, -len(name))


def _display_case(name: str) -> str:
    """Sentence-case a shopping-list entry.

    Recipe authors write ingredient names inconsistently ("arugula" next to
    "Celery"), which reads as sloppy once they are alphabetised side by side on
    a printed list. Only the first character is touched, so proper nouns and
    brand-style casing inside the name ("Greek yogurt", "Dijon mustard") are
    left alone.
    """
    stripped = name.lstrip()
    if not stripped:
        return name
    return stripped[0].upper() + stripped[1:]


_PREFIX_DISPLAY_RE = re.compile(r"^\s*[Ss]lices?\s+[Oo]f\s+")
_PERCENT_DISPLAY_RE = re.compile(r"\s*\b\d+\s*%")


def _strip_qualifiers_from_display(name: str) -> str:
    """Clean a display name: strip prefix, percentages, qualifier words, apply aliases.

    Preserves casing of the kept words. Falls back to the original name if
    every word would be stripped.
    """
    prefix_stripped = _PREFIX_DISPLAY_RE.sub("", name) != name
    name = _PREFIX_DISPLAY_RE.sub("", name)
    # Same parenthetical/packing tidy-up the key gets — otherwise a stripped
    # percentage leaves the shopper reading "Low-fat cottage cheese ( milkfat)".
    name = _PAREN_RE.sub(" ", name)
    name = _FRESH_OR_RE.sub(" ", _WATER_PACKED_RE.sub(" ", name))
    name = _PERCENT_DISPLAY_RE.sub("", name)
    name = re.sub(r"\s*,\s*(?:divided|rinsed(?:\s+and\s+drained)?|drained)\s*$", "", name,
                  flags=re.IGNORECASE)
    out: list[str] = []
    for w in name.split():
        if _is_strip_both_word(w):
            continue
        alias = _DISPLAY_ALIASES.get(w.lower())
        if alias:
            out.append(alias.capitalize() if w[:1].isupper() else alias)
        else:
            out.append(w)

    if not out:
        return name

    # If we stripped a prefix and the new first word is lowercase, capitalise it
    # so "slices of rye bread" → "Rye bread".
    if prefix_stripped and out[0][:1].islower():
        out[0] = out[0][0].upper() + out[0][1:]

    # Special: "Lemon zest <anything>" → "Lemon zest"
    if len(out) >= 2 and [w.lower() for w in out[:2]] == ["lemon", "zest"]:
        out = out[:2]

    return " ".join(out)


def _normalise(text: str) -> str:
    """Lighter normaliser used for category keyword matching."""
    folded = "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )
    return " ".join(folded.lower().split())


# ── Quantity formatting ─────────────────────────────────────────

def format_quantity(grams: float) -> str:
    """Render a total quantity in grocery-friendly units."""
    if grams <= 0:
        return "0 g"
    if grams >= 1000:
        kg = grams / 1000
        return f"{kg:.1f} kg".replace(".0 kg", " kg")
    if grams >= 100:
        rounded = int(round(grams / 10.0) * 10)
        return f"{rounded} g"
    rounded = int(round(grams / 5.0) * 5)
    if rounded == 0:
        rounded = 5
    return f"{rounded} g"
