# Fatty Liver (MASLD) + Type 2 Diabetes — Recipe Generator

AI-powered recipe + meal-plan generator for the cookbook:

> **The Fatty Liver Diet Cookbook for Type 2 Diabetes**
> *100+ Recipes in Under 30 Minutes from Everyday Ingredients, with a Personalized 30-Day Meal Plan to Help Lower Liver Fat and Keep Your Blood Sugar Steady*

**Audience:** US adults with **type 2 diabetes** who have been told they have **fatty liver** —
clinically *metabolic dysfunction-associated steatotic liver disease* (**MASLD**), or its
inflammatory form **MASH**. Usually overweight or living with obesity, commonly on metformin and
often on a GLP-1 receptor agonist, SGLT2 inhibitor, insulin or a sulfonylurea. They cook ordinary
supermarket food and have about half an hour. English / USA. Written for the **pre-cirrhotic**
reader.

## The premise that governs everything else

**Fatty liver and type 2 diabetes are the same metabolic problem seen from two sides.** Insulin
resistance leaves fat in the liver and glucose in the blood, so the levers overlap almost
completely. Pooled global MASLD prevalence in type 2 diabetes is **65.33%** (72.65% in Western
countries); the ADA's own consensus report puts it near **70%** of US adults with T2D. *One way of
eating, both conditions* is an epidemiological fact, not a marketing line — and it is the sentence
every recipe has to earn.

The reader left an appointment with a diagnosis and no menu, then found the internet arguing with
itself: cut all carbs, cut all fat, try keto, juice everything. **This book is the calm, specific
answer, and it explicitly refuses that advice.**

## Key constraints

- **2 servings**, always — never change this (per-serving arithmetic assumes it in
  `cooking/quantity_checker.py`, `stage_04_nutrition.py`, `diet_rules/rules.py`,
  `llm/output_schemas.py`, `models/recipe.py` and several prompts).
- **Diet profile** — Mediterranean in character, energy-controlled for weight loss, **very low in
  added sugar**, fiber- and protein-forward, **alcohol-free**, and deliberately **NOT
  low-carbohydrate**. Ground truth: `docs/fatty_liver_diabetes_guidelines.md` (dossier, 27 sources)
  + `data/fatty_liver_diabetes_guidelines.yaml` (machine spec). Deterministic checks in
  `src/diet_rules/` (`spec.py` loads the YAML, `rules.py` implements the 8 hard blocks + per-tier
  soft targets, `engine.py` registers the `masld` diet) and run in Stage 3.
- **Nutrition** — per-serving panel computed via **USDA FoodData Central**. The LLM only *picks* a
  food per ingredient; Python does the arithmetic. `src/nutrition/qualifiers.py` enforces the
  salted/unsalted and raw/cooked basis of each pick. Added sugars stay LLM-estimated (USDA carries
  no added-sugars value for generic foods) and are flagged as estimated on the panel.
- **Under 30 minutes, no exceptions** — the cover promise, and the one editorial cap that is
  *tighter* than the engine's parent cookbook (which allowed 45 min).
- **Language:** English. **LLM:** Google Gemini by default (`src/config.py`); Anthropic optional.

## Setup

Python 3.12, managed with **`uv`**. Run everything through `uv run`.

```bash
uv sync                                     # install deps (creates .venv)
cp .env.example .env                        # set GOOGLE_API_KEY (or ANTHROPIC_API_KEY)
# usda_source_data/ is a JUNCTION to the shared FDC bundle in the sibling HPHF repo
# (FoodData_Central_csv_2026-04-30). To get your own: download the FoodData Central
# "Full Download / All Foods" CSV bundle (~3 GB) from
# https://fdc.nal.usda.gov/download-datasets and unzip it there.
uv run python cli.py build-nutrition-db     # -> data/usda.db (+ FTS5), data/usda_alias.db
```

## Run

```bash
uv run python cli.py generate --distribution "..."       # see the distribution below
uv run python cli.py regenerate-missing-images --book <book>
uv run python cli.py meal-plan --book <book> --days 30
uv run python cli.py nutrition-lookup "<ingredient>"
uv run python cli.py validate-recipe data/generated_recipes/<recipe>.json
uv run python cli.py --help

uv run pytest -q                            # offline suite (no LLM/DB calls) — 471 tests
uv run ruff check .                         # lint
```

**Windows:** the CLI prints `✓`/`⚠`; when stdout is redirected, cp1252 raises
`UnicodeEncodeError`. Prefix long/backgrounded runs with `PYTHONIOENCODING=utf-8`.

**Docker (alternative)** — `docker compose build && docker compose run app <command>`. `cli.py` and
`src/` are baked into the image (compose mounts only `./data`), so rebuild with
`docker compose build app` before new behavior is visible.

## Architecture

Per-recipe 8-stage pipeline in `src/recipe_pipeline/` (driven by `orchestrator.py`; batch/resume in
`batch_state.py`; interactive review gate in `review.py`):

1. Ideation — `stage_01_ideation.py` (diversity/dedup retry loop, `MAX_DIVERSITY_RETRIES=3`)
2. Draft — `stage_02_draft.py` — then the deterministic quantity gate
   (`src/cooking/quantity_checker.py`, **blocking**) inside the correction loop
   (`MAX_CORRECTION_LOOPS=2`)
3. Diet check — `stage_03_diet_check.py` (structural hard blocks pre-nutrition, **blocking**;
   per-tier soft targets post-nutrition, warnings)
4. Nutrition — `stage_04_nutrition.py` (LLM picks a food id per ingredient; Python computes the panel)
5. Cooking sanity — `stage_05_cooking.py` (advisory only — **6** checks)
6. Critic — `stage_05b_critic.py` (12 dimensions: 8 culinary + 4 guideline-fit; `MAX_CRITIC_LOOPS=2`)
7. Format — `stage_06_format.py`
8. Image — `stage_07_image.py` (one hero image per recipe)

**Only the 8 hard blocks and the Stage-2b quantity gate reject a recipe.** Every nutrient floor and
ceiling is a warning that keeps it — nutrition is computed *after* drafting, so blocking there
discards finished work over food-database noise.

On top of recipes, `src/planning/` builds the meal plan + shopping lists + per-user
personalization. Prompts in `src/llm/prompts/`; models in `src/models/`; chapter/meal-type
constants in `src/constants.py`. The cookbook enters the pipeline only through `DietRuleEngine`
(`constraint_text` + `chapter_brief`, both reading the YAML) and the constants tables.

### The 8 hard blocks (`src/diet_rules/rules.py`)

| Rule | Why it blocks rather than warns |
|---|---|
| `no_alcohol_ingredient` | **The signature rule.** Any quantity fails. The AGA asks readers to restrict or eliminate alcohol; AASLD reports that *moderate* use increases the probability of advanced fibrosis. Retention after cooking is unreliable, so "it cooks off" is not a defence. |
| `no_deep_fried` | Also catches shallow-frying in a depth of oil. |
| `no_sugar_sweetened_beverage_or_juice_component` | **Fruit juice counts as an SSB here.** NIDDK names juices alongside soda as the source of the simple sugars — chiefly fructose — to avoid. Lemon/lime juice exempt: they are the book's main salt replacement. |
| `no_high_fructose_sweetener` | HFCS, corn syrup, agave. Any quantity. Fructose raises MASLD/MASH/fibrosis risk *independent of calorie intake*; agave is ~85% fructose and arrives disguised as the healthy option. |
| `no_added_sugar_primary_base` | Not a sugar-delivery vehicle. |
| `no_refined_grain_base` | ≥50 g. Includes plain couscous and flour tortillas. |
| `no_processed_cured_meat_base` | ≥60 g. The AGA names red *and processed* meat specifically. |
| `no_tropical_saturated_fat_base` | Coconut oil (~82-90% saturated), palm oil, coconut cream at any culinary amount; full-fat coconut milk at ≥120 g. The healthy-sounding fats that quietly break the <10%-of-energy rule. |

### The per-serving envelope

| axis | main | light_main | snack/side | dessert |
|---|---|---|---|---|
| energy kcal | 380-540 | 300-440 | 120-230 | 120-220 |
| protein g (floor/target) | 26 / 31 | 20 / 24 | 5 / 8 | 4 / 6 |
| **total carbohydrate g (floor/target/max)** | **32 / 45 / 55** | **25 / 35 / 45** | **10 / 16 / 24** | **14 / 20 / 28** |
| fiber g floor | 7 | 6 | 3 | 2 |
| added sugar g max | 4 | 4 | 3 | 7 |
| saturated fat g max | 5 | 4 | 2 | 2 |
| sodium mg max | 550 | 500 | 250 | 150 |

Day A (3 mains + snack + dessert) = 1,725 kcal; Day B (a soup/salad lunch) = 1,635 kcal. Both are
pinned by `tests/test_spec_coherence.py`: carbohydrate floors clear **27.6-27.8%** of energy,
fiber floors clear ADA's 14 g/1,000 kcal, sodium sums to 2,000-2,050 mg, added sugar to 22 g, and
saturated fat to 9.9% of energy *even with every recipe at its ceiling*.

### Things that will look like bugs and are not

- **The carbohydrate FLOOR is the point, not an oversight.** A recipe that is impressively low in
  carbohydrate is a **DEFECT** in this book. The floors are sized so a day built entirely of
  floor-hugging recipes still clears the **<26%-of-energy** very-low-carbohydrate line. That
  protects the reader on an **SGLT2 inhibitor** (ketogenic patterns are discouraged — euglycemic
  ketoacidosis) and the reader on **insulin or a sulfonylurea** (hypoglycemia), and it is the
  book's editorial position: the reader came here *because* the internet told them to cut all carbs.
  `render_envelope()` prints carbohydrate as a window with the word "defect" in it, `rules.py` warns
  in **both** directions, and the critic is told never to praise a low-carbohydrate recipe.
- **There is no `net_carbs` anywhere, and that is deliberate.** It has no FDA definition, the ADA
  counts *total* carbohydrate, and a reader dosing insulin against a subtracted number is a safety
  problem. The parent engine featured it as a hero metric; here the field survives only on
  `NutritionInfo` for legacy-JSON validation, with `on_recipe_panel: false`. A test asserts it stays
  off the panel.
- **Added sugar is tighter than carbohydrate, and that inversion is the whole liver argument.**
  Fructose drives hepatic de novo lipogenesis *independently of calories* (7-week RCT: 80 g/day of
  fructose- or sucrose-sweetened beverage raised basal hepatic fatty-acid synthesis at stable
  calorie intake; glucose did not). Total carbohydrate carries no equivalent liver-specific signal.
- **`OPTIONAL_MEAL_TYPES` is `{dessert}` only — the snack is NOT optional.** The ADA names skipped
  meals as a hypoglycemia driver, and the snack tier carries part of the day's carbohydrate floor.
  Guarded by a test.
- **Broth is excluded from the protein tally in `quantity_checker._classify`.** "Chicken broth"
  matches "chicken", and a soup carries broth by the litre — without the guard every recipe in the
  Soups & Salads chapter blew the per-person protein ceiling. Regression-tested.
- **`light_main` has the HIGHEST raw-weight ceiling in the book** despite being the lighter tier: a
  brothy soup for two is mostly water by weight.
- **`snack` holds SIDES as well as snacks**, so its protein floor is a nudge (5 g), not a gate. A
  tray of roasted vegetables is legitimately low in protein and that is correct.
- **False-friend ORDER is load-bearing** in `rules.py`, exactly as in `qualifiers.py`. Wine, sherry,
  champagne, rice-wine and apple-cider **vinegars** must escape the alcohol block — this book leans
  on acid as its main salt replacement, so a wine block that swallowed them would make most recipes
  undraftable. Bare `"gin"` is absent from the keyword list because `\bgin` matches "ginger"; bare
  `"port"` because it matches "portobello"; bare `"ale"` because it matches "aleppo". Tested.
- **`couscous` is in the refined-grain block.** Standard couscous is refined durum semolina;
  whole-wheat couscous escapes via the false-friend list. Bulgur, barley, quinoa and brown rice are
  the everyday-supermarket alternatives.
- **No air fryer, pressure cooker, Instant Pot, sous-vide or slow cooker.** The parent cookbook only
  banned the air fryer; this book's "everyday, under 30 minutes" positioning rules out the rest, and
  a slow cooker cannot meet the 30-minute promise. `check_equipment` is the deterministic backstop.
- **There is no set-and-forget time exemption.** The parent exempted slow-cooker recipes from its
  time cap. The cover here says "in Under 30 Minutes" and the description answers the no-time
  objection with "no exceptions", so a long recipe always warns.
- **Do not run automated line-re-wrapping over `src/llm/prompts/*.py`.** Their long rendered lines
  come from deliberate backslash continuations; a wrapping script has previously split f-strings
  mid-token in this engine's lineage, breaking two files outright and silently corrupting two more
  that still parsed. The E501 count in those files is inherited and accepted.
- **`IMAGE_SIZE` stays at 1K** — see the comment on `Settings.image_size` in `src/config.py`. The
  asymmetry that makes it urgent rather than adjustable later: 2K downscales to 1K cleanly, but 1K
  does **not** upscale to 2K. If the interior layout ever goes full-width or full-page, set
  `IMAGE_SIZE=2K` in `.env` **before** generating, or all 100 images get regenerated.
- **Saved photos are JPEG bytes with a `.png` filename.** Gemini returns JPEG; every save path names
  it `.png`. Harmless for the PDF pipeline, but anything sniffing by suffix needs the real type.
- **The "Stage 4 coverage: 'Extra-virgin olive oil' … switched to" warning is NOISE, not a defect.**
  It fires on nearly every recipe. The model picks `[748608] Oil, olive, extra virgin`, a Foundation
  record carrying no `fiber_g`/`protein_g`; Stage 4 notices those would be summed as zero and swaps
  to a fully-populated record. For oil, fibre and protein genuinely ARE zero, so the original would
  have been fine — but the engine cannot know that, and preferring a complete record is right. All
  the olive-oil records in the DB are within 884-900 kcal and 13.8-15.5 g saturated per 100 g, so
  **the fat numbers are trustworthy whichever wins.** Same pattern on Greek yogurt. Seeding the
  alias removes the noise. Do not spend an afternoon re-diagnosing this.

### Claims the book must NOT make

Recorded in §8 of the dossier and enforced in the prompts + critic: no **detox / cleanse / flush**;
no **cure or reversal** promise (the weight-loss thresholds are dose-response probabilities, and
"helps lower liver fat" is the honest verb); no per-recipe **glycemic index or load** (not reliably
computable for a mixed dish; endorsed by no guideline body — build on fiber instead); no **vitamin
E** recommendation (AASLD's 800 IU evidence is for **non-diabetic** patients — the opposite of this
reader); no named **liver superfoods**; no "**a little alcohol is fine**"; **coffee** is an
observational association mentionable once in front matter, never a treatment claim; no **net
carbs**; no **fat-burning / metabolism-boosting** language.

## Recipe chapters

**8 chapters, 100 recipes** (satisfies the cover's "100+ Recipes"). Slugs live in THREE synced places: the YAML `recipe_categories`,
`src/constants.py` `RECIPE_CHAPTERS`, and the `RecipeChapter` Literal in `src/models/recipe.py`.
(`tests/test_recipe_pipeline.py::TestGuidelineSpec::test_chapter_slugs_agree_across_all_three_places`
guards the coupling, and a companion test asserts the declared hard blocks equal the implemented ones.)

| slug | book title | meal slot | tier | target |
|---|---|---|---|---|
| `breakfasts` | Breakfasts | breakfast | `main` | 16 |
| `soups_salads` | Soups & Salads | lunch | `light_main` | 14 |
| `lunches` | Lunches | lunch | `main` | 14 |
| `poultry_meat_dinners` | Chicken, Turkey & Lean Meat Dinners | dinner | `main` | 13 |
| `fish_seafood_dinners` | Fish & Seafood Dinners | dinner | `main` | 11 |
| `vegetable_meatless_dinners` | Vegetable & Meatless Dinners | dinner | `main` | 10 |
| `snacks_sides` | Snacks & Sides | snack | `snack` | 12 |
| `desserts` | Desserts | dessert | `dessert` | 10 |

Default chapter: **`poultry_meat_dinners`**. Three chapters share the `dinner` slot and two share
`lunch`, so `RECIPE_CHAPTER_MEAL_TYPES` is not a bijection — `MEAL_TYPE_DEFAULT_CHAPTER` nominates
one chapter per slot.

**Why the counts sit where they do (target cut 106 → 100 on 2026-08-09).** The book is sized against
its own 30-day plan, so what matters per chapter is how often a reader repeats a recipe: breakfast
~1.9×, lunch ~1.1×, **dinner ~0.9×**, snack 2.5×, dessert 3×. Dinner was the ONLY block covering its
slots without repeating (40 recipes for 30 slots), so the whole 6-recipe trim came out of the three
dinner chapters — two each — rather than being spread evenly. Dessert repeats most, but it is the
one **optional** slot, so a reader who skips it never notices. Section 9 of the dossier carries the
same table.

**`generate --distribution` produces EXACTLY the counts you give it — it does NOT top up to a
target.** Running the full-book distribution against a non-empty book over-generates. Compute the
remainder from what is on disk first (`scripts/analyse_pilot.py <book>` lists what exists).

**The full book distribution, from an EMPTY book:**

```bash
uv run python cli.py generate --book cookbook-recipes --distribution \
  "16 breakfasts, 14 soups_salads, 14 lunches, 13 poultry_meat_dinners, \
   11 fish_seafood_dinners, 10 vegetable_meatless_dinners, 12 snacks_sides, 10 desserts"
```

## Session state / RESUME HERE

**Checkpoint convention.** This section is the single source of truth for where the build stopped.
Update it at the end of every milestone (and before any long-running command), so a session killed
by a rate limit can be resumed from this file alone. Nothing else records it.

### Where this build came from (decision, 2026-08-09)

Cloned from **`../recipe-generator-high-protein-high-fiber`**, as the `cookbook-recipe-system` skill
nominates — *not* from the sibling `recipe-generator-ckd3-diabetes-seniors`, even though that one is
newer and carries a type-2-diabetes layer. Reason: the CKD3 repo's whole architecture is built
around **renal minerals** (potassium and phosphorus axes, KCl-substitute and phosphate-additive hard
blocks, a phosphorus-to-protein ratio gate), none of which applies here and some of which would be
actively wrong. HPHF's nutrient axis set — protein, fiber, carbohydrate, added sugar, saturated fat,
sodium, added oil, energy — maps almost exactly onto what a MASLD + T2D book needs.

Two things were worth borrowing from the CKD3 build anyway, and were:
- the **spec/dossier coherence test** pattern (`tests/test_spec_coherence.py`), which guards the #1
  documented trap — the same numbers living in the YAML envelope, the drafting prose, and the
  dossier table;
- the **declared-vs-implemented hard-block drift test**, which catches a rule id declared in the
  spec with no class behind it (a silent no-op).

### DONE

- [x] **Phase 0 research.** Tier-1 sources: EASL-EASD-EASO 2024, AASLD 2023 (Rinella), AGA 2021
      lifestyle CPU, ADA MASLD consensus report 2025, ADA Standards of Care 2026 §4/§5, DGA
      2025-2030 (published 2026-01-07), FDA labeling, AHA, NIDDK, plus named RCTs and meta-analyses
      (Geidl-Flueck fructose RCT, Ryan Mediterranean cross-over, Markova isocaloric protein,
      Younossi T2D prevalence, Henney UPF meta-analysis, ESSENCE semaglutide).
      **Fetch failures are recorded in §10 of the dossier and in `meta.review_notes`** — re-verify
      before print, especially the DGA's "**no more than 10 g of added sugars per meal**" figure,
      which is load-bearing for the added-sugar ceilings.
- [x] **Spec pair authored.** `docs/fatty_liver_diabetes_guidelines.md` (12 sections, 27 sources) +
      `data/fatty_liver_diabetes_guidelines.yaml` (schema_version 1, 4 tiers, 8 chapters, 8 hard
      blocks, 27 sources). Validates **0 errors, 0 warnings**.
- [x] **Clone + scrub.** No `.git`, `.venv`, caches, `.env`, `data/generated_recipes/` or `*.db`
      carried over (~1 MB on disk). `usda_source_data/` is a **junction** to the shared FDC bundle in
      the HPHF repo, not a copy. The inherited HPHF spec and dossier were deleted.
      `pyproject.toml` `[project].name` → `recipe-generator-fatty-liver-diabetes`.
- [x] **Green baseline twice**: `uv sync` then `uv run pytest -q` → **340 passed** before any change.
- [x] **Diet id** `hphf` → `masld` (`engine.py` `DIET_ID`/`SUPPORTED_DIETS` + guards, the `masld.*`
      rule-name prefixes in `rules.py`, `planning/manifest.py` diet-tag sniff).
- [x] **Chapters wired into all three coupled places** + the four companion maps in `constants.py`.
- [x] **The carbohydrate axis wired end to end**: `NutrientEnvelope.total_carbs_g_{floor,target,max}`
      → `_parse_envelope` → a window-printing `render_envelope()` → a two-sided soft rule in
      `rules.py`. `net_carbs_g_max` **removed** rather than left unused.
- [x] **`rules.py` re-authored**: 8 hard blocks with false-friend guards, plus the two soft per-tier
      rules. **Note the docstring** — the false-friend order is load-bearing.
- [x] **All four prompt files re-authored** (`ideation`, `draft`, `critic`, `format`) plus
      `output_schemas.py` field prose. The stale "High-Protein High-Fiber / Weight Loss" identity is
      gone. New content: the one-plan-both-conditions premise; the carbohydrate FLOOR; the alcohol,
      juice, fructose-syrup and tropical-fat bans; the 30-minute promise; the banned-claims list.
- [x] **Critic dimensions 9-12 re-authored**: `one_plan_both_conditions`,
      `added_sugar_and_carb_balance` (which explicitly says *never praise a recipe for being low in
      carbohydrate*), `chapter_intent_fit`, `thirty_minute_practicality`.
- [x] **`method_checker.py`**: `check_super_easy` → `check_thirty_minutes` (caps 12/30/38, no
      set-and-forget exemption) plus a NEW `check_equipment`. Both wired into Stage 5, which now
      runs 6 advisory checks.
- [x] **`quantity_checker.py`**: `light_main` tier added, bounds retuned, and broth/stock excluded
      from the protein tally.
- [x] **Panel order fixed** in `output/formatter.py` + `csv_export.py` + the critic's nutrition
      block: the HERO SIX (calories, total carbohydrate, fiber, added sugars, protein, saturated
      fat) now lead, and net carbs is gone from the printed panel.
- [x] **`planning/personalization.py`**: `DEFAULT_MEAL_SHARE` re-derived from this book's tier energy
      bands (the inherited split aimed 35% of the day at lunch, which no tier here supports);
      `PROTEIN_G_PER_KG` 1.6 → **1.5**; `FAT_PCT_OF_KCAL` 0.275 → **0.35** (Mediterranean shape, and
      it makes the residual carbohydrate land at ~40% of energy, matching the spec);
      `_diet_note()` re-authored. `manifest.py` + `models/meal_plan.py` defaults → 1,700 kcal and a
      five-slot day.
- [x] **Tests: 471 passed.** New: the three-place chapter coupling, the hard-block drift test,
      pass/fail tests for all eight hard blocks (including every false-friend guard), the
      carbohydrate-window tests, the equipment check, the broth regression, and the whole of
      `tests/test_spec_coherence.py` (50 tests pinning the YAML↔prose↔dossier agreement and the day
      arithmetic). **Lint: 345** (parent 326; the delta is E501 in prose/comments only —
      see the re-wrapping warning above).
- [x] **`data/usda.db` BUILT** — 13,694 generic foods from 27,195,013 nutrient rows (the Full
      "All Foods" bundle, not the 469-food Foundation subset). Coverage on this book's axes:
      calories 99.8%, protein 99.7%, carbohydrate 99.3%, **fiber 94.3%**, total sugars 84.9%,
      saturated fat 95.2%, sodium 98.9%, MUFA 93.9%. The sparse ones are trans fat (31.3%) and
      vitamin D (78.0%) — both are `None`-tolerant panel extras. (`data/*.db` is gitignored;
      rebuild with `build-nutrition-db`.)
- [x] **`scripts/verify_prompts.py` added** — renders the four real system prompts plus every
      chapter brief and asserts they carry this book's identity, name the banned-claims
      vocabulary, keep "net carbs" and "air fryer" only in a negated context, and show none of
      the literal-corruption signatures a re-wrapping script once left in this lineage.
      **Run it after touching any prompt.** Currently clean.

- [x] **`.env` in place (2026-08-09)** — copied from `../recipe-generator-ckd-stage3-renal` at the
      user's instruction. `GOOGLE_API_KEY` is real; `ANTHROPIC_API_KEY` is still the placeholder,
      which is fine because Google is the default provider. Verified through `src.config.settings`.
      `.env` is line 1 of `.gitignore`.

### THE PILOT RAN AND PASSED (2026-08-09) — 8/8, one per chapter

Output in `data/generated_recipes/test-pilot/` (gitignored). Log: `data/pilot_run.log`.
Re-read with `uv run python scripts/analyse_pilot.py test-pilot`.

```
recipe                                   tier         kcal  carb  fib  sug  prot  sat   Na
Chickpea and Spinach Shakshuka           main          445    42    9    0    28    4  459
Tofu and Edamame Stir-Fry                main          511    48   10    0    32    4  228
Turkey and Quinoa Skillet                main          540    49    8    0    41    5  475
Sheet-Pan Salmon, Potatoes, Green Beans  main          470    47    8    0    36    2  457
Tuna and White Bean Pita Pockets         main          483   61!   10    0    40    2  331
Chicken and Black Bean Jar Salad         light_main    379    35    9    0    35    2  460
Cinnamon-Berry Greek Yogurt Bowl         snack         202    21    3    0    20    0   62
Broiled Peaches with Vanilla Ricotta     dessert       166    22    3    3     6    2   31
```

8/8 images (one needed 2 attempts), 0 `validation_passed=False`, **1 envelope miss in ~56 axis
checks**, 0 hard-block rejections, 1 quantity-gate correction (resolved in one retry).

**THE HEADLINE RESULT: the carbohydrate floor held on all eight.** Mains landed 42-61 g against a
32 g floor, clustering near the 45 g target. That was the single biggest design risk in this book
and it did not materialise. **Added sugar was 0 g on seven of eight**, with the dessert at 3 g
against a 7 g ceiling — the tightest axis in the book is under no strain at all.

A real day from these recipes (shakshuka + salad + yogurt bowl + turkey skillet + peaches) =
**1,732 kcal**, essentially exactly the spec's modelled day. The lighter tiers absorb the mains,
which do run upper-half (445/470/483/511/540, mean 490 vs a 460 midpoint).

**Guards that were proven, not just written:**
- `\bgin` does NOT match "ginger" — the ginger-garlic stir-fry drafted without an alcohol block.
- The tropical-fat block matches `coconut cream`, never bare `cream` — "Vanilla Ricotta Cream"
  passed. (The sibling CKD3 build was bitten by exactly this class of bug.)
- The Stage-2b quantity gate caught **11.5 g/person of soy sauce** in the stir-fry — ~670 mg
  sodium from the condiment alone, which would have blown the 550 mg ceiling by itself. Caught
  *before* nutrition and the critic ran. Note `quantity_checker`'s docstring calls that 5 g salt cap
  "coarse, only catches a gross typo" — on THIS book, with a 550 mg ceiling instead of the parent's
  700, it catches realistic recipes.

### FIXES THE PILOT EARNED (all applied)

1. **The inherited fabricated-preheat instruction is gone.** `draft.py` used to say a preheat
   *"gives its exact time in minutes (e.g. Preheat to 375°F / 190°C for 3 minutes)"*. No oven does
   that — the real figure is 10-15 min. It put **false information in a printed cookbook** and, worse
   here, let the model hide 10-15 minutes of a 30-minute budget. Now: never state a preheat duration;
   preheat in step 1 so it heats during prep, or count the wait in `prep_time_min`.
2. **No time claims in titles or intros.** The pilot produced "15-Minute Chickpea and Spinach
   Shakshuka" and an intro claiming "ready in under ten minutes". The cover already guarantees under
   30 minutes, so a per-recipe minute count is redundant AND becomes a lie when timing shifts.
3. **Ready-to-eat cooked grain pouches are now a named first-class shortcut**, and assuming an
   undeclared pre-cooked component is explicitly banned. The pilot's salad relied on "cooked and
   cooled quinoa", borrowing ~25 minutes it never declared.
4. **Critic dimension 12 now names all three** of the above as things to flag.
5. **`data/usda_aliases.seed.yaml` + `scripts/seed_usda_aliases.py` added, and seeded (18 entries).**
   See the next section — this one has real sodium consequences.

### THE CANNED-GOODS FINDING — read before trusting a sodium number

Two distinct failures, both on canned goods, both landing on sodium:

- **The drafting model INVENTS plausible USDA descriptions.** It wrote `Beans, white, mature seeds,
  canned, no salt added` — which **does not exist** in FoodData Central. Stage 4 correctly fell back
  to a cooked-from-dry record; that is a different water basis, so protein/fibre/calories are
  slightly overstated on that ingredient.
- **The shortlist misses a no-salt-added record that DOES exist.** The pilot logged *"No USDA
  candidate for 'No-salt-added canned diced tomatoes'"* — yet `170138` sits in the DB at **10 mg
  sodium/100 g**, against the 125-186 mg records the engine settles for. On a recipe carrying 200 g
  of tomato per serving that is a **230-350 mg error against a 550 mg ceiling**: the panel
  OVERSTATES sodium, so recipes look far closer to the ceiling than they are.

Both are now fixed by seeding. **Re-run `scripts/seed_usda_aliases.py` after every
`build-nutrition-db`** — that command recreates the alias DB.

Worth knowing from the same query: genuine low-sodium canned records exist for **black (138 mg),
kidney (117), pinto (146) and great northern (177)** beans — and **do not exist for cannellini/white
or navy**, where 340/336 mg is the only option. Prefer the former in recipes.

### OPEN QUESTIONS FOR THE NEXT BATCH (3-5 per chapter)

- [ ] **Protein is overshooting by ~25%.** A day from the pilot carries **130 g protein** against the
      ~97-107 g the spec models — the snack alone delivered 20 g against an 8 g target. No rule was
      broken (floors are `>=` with no ceiling), and 130 g is safe for healthy adults, BUT this
      readership has elevated diabetic-kidney-disease risk and the dossier's own `daily_targets` claim
      1.2-1.6 g/kg. At 70 kg, 130 g is 1.86 g/kg. Decide at the next batch: raise the tier targets to
      match reality, or damp the drafting prompt's protein enthusiasm. Do not ignore it — it is a
      coherence problem between the book's front matter and its recipes.
- [ ] **Bread/wrap + legume stacks carbohydrate.** The one envelope miss (pita 61 g vs a 55 g ceiling)
      came from pita **plus** white beans. Watch whether it recurs; the fix is a chapter-brief nudge,
      not a ceiling change.
- [ ] **A vegetable SIDE was never generated** — `snacks_sides` produced a snack both times it could
      have gone either way. The tier's 5 g protein floor was designed to be a nudge that a side
      legitimately misses. Generate a few sides deliberately and confirm the warning is not being
      escalated by the critic.

### THE 8 PILOT RECIPES WERE MOVED INTO `cookbook-recipes/` (2026-08-09, user instruction)

`data/generated_recipes/test-pilot/` no longer exists; its five meal-type folders and `dedup.db`
were moved to `data/generated_recipes/cookbook-recipes/`. **Two things follow that are easy to miss:**

1. **`cookbook-recipes/` is the GIT-TRACKED folder** — `.gitignore` carries
   `data/generated_recipes/*` plus `!data/generated_recipes/cookbook-recipes/`. Anything in there is
   committed, and published if this repo is ever made public.
2. **These 8 were generated BEFORE the prompt fixes**, so two of them carry the defects the pilot
   found. Concretely, `Dessert/Md/broiled_cinnamon_peaches_with_vanilla_ricotta_cream.md` contains
   *"Preheat the oven broiler to High (500°F / 260°C) **for 3 minutes**"* (false — a broiler needs
   10-15) and an intro claiming *"ready in under 15 minutes"* against its own declared 15-17 min.
   `Breakfast/…/15-minute_chickpea_and_spinach_shakshuka` carries a time claim in its title and
   filename. **Regenerate these two at minimum before print**, or regenerate all 8 with the fixed
   prompts as part of the full run.

**The move required rewriting embedded absolute paths**, which a plain `Move-Item` does NOT do: every
recipe's markdown `![](…)` and JSON `image_path` hard-code the book folder. Markdown uses single
backslashes, JSON uses escaped double backslashes — **both forms must be replaced** or the JSON
silently keeps pointing at the old folder. Verified: 0 stale references, 8/8 image paths resolve.
Any future book-folder rename has to do the same.

`dedup.db` moved with them, so a subsequent `--book cookbook-recipes` run will avoid duplicating
these 8. If they are regenerated instead, that DB should be deleted first or it will block
near-identical replacements.

### OPERATIONAL: BACKGROUND TASKS DO NOT SURVIVE — GENERATE IN THE FOREGROUND

Measured four times on 2026-08-09, all into `cookbook-recipes`:

| run | shell | requested | elapsed | completed | outcome |
|---|---|---|---|---|---|
| 1 | PowerShell bg | 20 | 29.4 min | 6 | **killed** |
| 2 | PowerShell bg | 14 | 19.4 min | 5 | **killed** |
| 3 | PowerShell bg | 3 | **1 sec** | 0 | **killed** |
| 4 | **Bash** bg | 9 | **1 sec** | 0 | **killed** |

Every one died cleanly: the previous recipe fully saved, the next one's header printed, then nothing.
**No exception, no rate-limit signature, no corrupt or partial files, ever.**

**Two hypotheses were tested and BOTH FALSIFIED** — record them so nobody re-runs the experiment:
1. *"It's a ~20-30 min duration limit, so use short batches."* Wrong — run 3 was a 3-recipe batch and
   died in one second.
2. *"My own foreground shell calls are killing it."* Wrong — run 4 was launched via Bash and died
   with **zero** tool calls from this session in between.

**What actually works: FOREGROUND calls.** Every foreground `generate` succeeded, all session. The
constraint is the 10-minute per-call limit, so at ~5 min/recipe run **1-2 recipes per call** and
repeat. The remaining 72 recipes are therefore ~40-70 foreground calls — tedious, but reliable.

```bash
# the working pattern (repeat, recomputing the remainder as you go)
uv run python cli.py generate --book cookbook-recipes --distribution "2 desserts"
```

This costs wall-clock, not work: **progress accumulates correctly across kills.** Recipes are written
as each finishes and `dedup.db` updates per-recipe, so a re-launch simply makes new ones — nothing is
lost or duplicated. Recompute the remainder from disk before each batch
(`scripts/analyse_pilot.py <book>`); `--distribution` does not top up to a target.

Ruled out as causes: the engine (every completed recipe is intact and valid) and the API (no quota or
rate-limit signature in any log).

### THE 20-RECIPE BATCH LANDED (2026-08-09) — 28 recipes on disk, 72 to go

Verified 20/20, exactly 4 per meal type, **0 incomplete files** (every recipe has a panel, an image
and instructions). First batch generated with the corrected prompts + seeded aliases.

**What the fixes bought:**
- **Zero time claims** in any new title or intro; **zero stated oven-preheat durations.** Both
  confirmed by grep over the post-fix recipes only. (The pre-fix pilot recipes still carry theirs.)
- **The alias seeding is visibly working.** The tomato-based stew came in at **244 mg** sodium while
  the white-bean soup sits at **447** — a gap that tracks exactly the record availability documented
  in `usda_aliases.seed.yaml` (canned tomatoes now resolve to the 10 mg no-salt-added record;
  cannellini has no low-sodium record at all).
- **The carbohydrate floor held on all 28.** Still the headline result.
- **Desserts are excellent**: 157-214 kcal on **2-4 g added sugar** against a 7 g ceiling.
- **The `snacks_sides` two-kinds-of-recipe design proved out.** Two genuine vegetable SIDES appeared
  (Brussels slaw 7 g protein, spinach-and-brown-rice pilaf 6 g) and both CLEARED the 5 g floor
  rather than tripping it — the nudge-not-gate sizing is right.
- **The critic caught a real undeclared-time defect**: the chia pudding said "make-ahead" in its
  intro but left the mandatory 2-hour chill out of `passive_time`. It is the single
  `validation_passed=False` in the book, and it failing is the system working.

**11 envelope misses across 28 recipes** (~5% of ~224 axis checks), all soft:
`carb>ceiling 4, satfat>max 2, fiber<floor 2, kcal>max 2, sodium>max 1`.

### THE DECISION THAT NOW HAS THREE SIGNALS BEHIND IT — mains run hot

**8 of 19 mains are at 500+ kcal** against a 380-540 band (545, 540, 539, 535, 517, 513, 511, 507),
and protein routinely lands at **40-49 g against a 31 g target**. That single pattern drives most of
the 11 misses.

Root cause: **every floor is `>=` with no ceiling**, so the drafting model reads "at least 26 g
protein" as "aim high", and portions inflate. With mains clustering near 540 rather than the 460
midpoint, the modelled ~1,730 kcal day drifts toward ~1,900 — still hypocaloric, but eating into the
deficit the liver is relying on, and pushing a day's protein to ~1.8 g/kg against the dossier's own
1.2-1.6 frame.

**Fix it PROMPT-SIDE before the remaining 72, not envelope-side.** The tiers are derived from the
guidelines and should not move. Tell the drafting model to AIM AT THE TARGETS rather than clear the
floors, and say plainly that overshooting protein displaces the carbohydrate and fat the day is built
on. NOT YET APPLIED — this is the next change.

### ⛔ HARD STOP — GOOGLE API ACCESS DENIED (2026-08-09)

Two DIFFERENT API failures hit in sequence. Do not conflate them, or with the silent background
kills documented above (which leave no error at all):

1. **429 RESOURCE_EXHAUSTED** — *"Your project has exceeded its monthly spending cap."* Stopped the
   run at 53 recipes. The user raised the cap and generation resumed normally for another 26.
2. **403 PERMISSION_DENIED** — *"Your project has been denied access. Please contact support."*
   Stopped it again at 79. **This one is not a billing setting** — it is a project-level access
   denial and needs Google support, not a spend-cap change. Raising the budget will not clear it.

Neither is an engine fault and neither corrupts anything: both fired mid-pipeline, and every recipe
already written is complete and valid.

**FALLBACK AVAILABLE:** the engine is provider-agnostic (`src/llm/client.py`). Setting
`LLM_PROVIDER=anthropic` and a real `ANTHROPIC_API_KEY` in `.env` routes everything through Anthropic
instead and generation can continue. As of this checkpoint `ANTHROPIC_API_KEY` is still the
`.env.example` placeholder, so that path needs a key before it will work.

### STATE AT THE STOP — 79/100 recipes

| chapter | have | target | remaining | status |
|---|---|---|---|---|
| breakfasts | 16 | 16 | 0 | **COMPLETE** |
| soups_salads | 14 | 14 | 0 | **COMPLETE** |
| lunches | 13 | 14 | 1 | |
| poultry_meat_dinners | 6 | 13 | 7 | |
| fish_seafood_dinners | 4 | 11 | 7 | |
| vegetable_meatless_dinners | 4 | 10 | 6 | |
| snacks_sides | 12 | 12 | 0 | **COMPLETE** |
| desserts | 10 | 10 | 0 | **COMPLETE** |
| **total** | **79** | **100** | **21** | |

Four of eight chapters are finished. **All 21 remaining are the dinner block plus one lunch:**

```
1 lunches, 7 poultry_meat_dinners, 7 fish_seafood_dinners, 6 vegetable_meatless_dinners
```

Run in batches of 2-3 per the batching note above.

### PUBLICATION AUDIT — `scripts/audit_book.py` (exits non-zero on blockers)

**49/53 publishable as-is. 4 need work:**

| recipe | defect |
|---|---|
| 15-Minute Chickpea and Spinach Shakshuka | time claim in title AND filename (pre-fix) |
| Broiled Cinnamon Peaches with Vanilla Ricotta | fabricated preheat "for 3 minutes" (pre-fix) |
| Sheet-Pan Lemon-Dill Salmon | fabricated preheat "for 5 minutes" (pre-fix) |
| Smoky Salmon and Sweet Corn Chowder | declared total 32 min > the 30 min cover promise (POST-fix) |

The first three are pilot recipes generated before the prompt fixes. The fourth is post-fix and shows
the 30-minute cap still needs watching — `check_thirty_minutes` warns above 38 min (a deliberate
"clear overshoot" threshold), so a 32-minute recipe passes generation but fails the publication gate.
That gap is intentional but worth knowing.

**Building that audit found three bugs in the audit itself** — record them, they are the same traps
the engine documents: `"rum"` matching inside *"Crumbled feta"* (plain substring where `rules.py`
uses word boundaries), `"chilled yogurt"` misread as a chilling step, and a digits-only time regex
that walked past *"ready in under **ten** minutes"*. First run reported 5 blockers; the truth was 3.

### NOT YET DONE — do not assume otherwise

- [ ] **47 of 100 recipes remain** — blocked on the spend cap.
- [ ] **Fix the 4 audit blockers** (above). For the shakshuka, the time claim is in the FILENAME too,
      so regenerating produces a new file and the old one must be deleted; delete its `dedup.db`
      fingerprint first or the replacement will be blocked as a duplicate.
- [ ] **Re-check whether the aim-at-targets fix worked.** It was applied immediately before this
      batch, so the 25 post-fix recipes are the sample. Compare main-tier kcal/protein against the
      pre-fix batch (mains were 500-545 kcal, protein 40-49 g vs a 31 g target).
- [ ] **Meal-plan / PDF coaching prose is only partly retargeted.** The claims that were wrong for
      this book were fixed (`meal_plan_formatter.py`, `meal_plan.html.j2`), but the PDF palette in
      `pdf/assets/meal_plan.css` is still the parent book's and is flagged in a comment — re-sample
      it from this book's cover at bonus time.
- [ ] **`src/planning/pantry.py` thresholds** (`DEFAULT_MIN_RECIPES = 5`, `SPICE_MIN_RECIPES = 3`,
      `SPICE_MAX_TOTAL_G = 150`) were fitted to the parent book's ingredient-frequency
      distribution. Re-fit once this book's recipes exist. Matters for the meal-plan bonus, not for
      generation.
- [ ] **The three reader bonuses are explicitly deferred** to the `cookbook-bonuses` skill (companion
      app, meal plan, desserts PDF). Note the subtitle promises a **30-day** plan, not 60.

### PILOT — the next command to run

```bash
# 0. prerequisite — the ONLY thing standing between here and generation.
#    (data/usda.db is already built; see DONE above.)
cp .env.example .env          # then set GOOGLE_API_KEY

# 1. one recipe per chapter into a SCRATCH book, no review gate
PYTHONIOENCODING=utf-8 uv run python cli.py generate --book test-pilot --distribution \
  "1 breakfasts, 1 soups_salads, 1 lunches, 1 poultry_meat_dinners, \
   1 fish_seafood_dinners, 1 vegetable_meatless_dinners, 1 snacks_sides, 1 desserts"
```

**What to watch for in the per-recipe LOG** (tune from real failures before scaling to 3-5/chapter,
then the full 100):

1. **Under-carbohydrate warnings.** The most likely new failure mode: the model has years of
   "diabetes cookbook = low carb" prior and will drift below the floor. If it recurs, strengthen the
   drafting snippet rather than lowering the floor.
2. **False positives from the new hard blocks** — especially `no_alcohol_ingredient` on a vinegar
   the false-friend list doesn't cover, and `no_refined_grain_base` on couscous or a tortilla where
   the whole-grain qualifier was dropped.
3. **`light_main` quantity-check behavior** on a real brothy soup (the tier's bounds are new and
   untested against generated output).
4. **`snacks_sides` protein floor** on a genuine vegetable side — expected to warn, and that is fine;
   check the warning is not being escalated by the critic.
5. **30-minute overshoot.** The cap tightened from 45 to 30; watch how often `check_thirty_minutes`
   fires and whether the model declares passive time honestly.
6. **Food-DB mis-picks** (raw vs cooked, salted vs not, wrong cut) and USDA coverage on this book's
   ingredient vocabulary — olive oil, legumes, whole grains, fatty fish, Greek yogurt.
7. **Critic-loop saturation** — dimension 10 is deliberately demanding; if it flags nearly every
   recipe, soften the *minor* band, not the rule.

**Build prerequisites:** `data/*.db` and `data/generated_recipes/` are gitignored — the DB must be
rebuilt locally, and recipes are not carried between machines.
