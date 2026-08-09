# Fatty Liver + Type 2 Diabetes Cookbook — Recipe Guidelines (ground truth)

**Book:** *The Fatty Liver Diet Cookbook for Type 2 Diabetes* — *100+ Recipes in Under 30 Minutes from Everyday Ingredients, with a Personalized 30-Day Meal Plan to Help Lower Liver Fat and Keep Your Blood Sugar Steady.*

**What this file is.** A working brief telling the recipe generator (and human editors) what makes a recipe *suitable* and *ideal* for this book's readers. Every nutrition/clinical claim is attributed to a clinical guideline, public-health authority, or peer-reviewed source (see **§10 Sources**). The recipe-level per-serving numbers in §4 are *derived working values* — a daily authority target divided across the day's meals — flagged as derived and tuned during the build, never presented as authority-stated thresholds. The structured distillation is `data/fatty_liver_diabetes_guidelines.yaml`.

**Disclaimer.** This book is for general educational purposes only and is not individualized medical or nutritional advice. It does not diagnose, treat, or replace care from your physician, hepatologist, or registered dietitian. Nutrition information is estimated using USDA data and varies with ingredients, brands, and preparation. Talk to your clinician before making significant dietary changes — especially if you take **insulin or a sulfonylurea** (eating fewer carbohydrates without adjusting the dose can cause hypoglycemia), take an **SGLT2 inhibitor** (very-low-carbohydrate and ketogenic patterns are discouraged), have **chronic kidney disease** (protein is deliberately restricted under clinician guidance), have **advanced fibrosis or cirrhosis** (energy and protein needs are *higher*, not lower, and alcohol must stop completely), are **pregnant or breastfeeding**, or have a history of an eating disorder.

**Last reviewed:** 2026-08-09. **Re-check before print:** see §10 (Verification status) — several primary guideline pages returned HTTP 403 to the automated fetcher and their figures were taken from official abstracts, executive summaries, or society-derived summaries. The **Dietary Guidelines for Americans 2025-2030** were published 2026-01-07 and are assumed current here; its added-sugar framing changed materially from the 2020-2025 edition and is load-bearing for this book (§2 A5).

---

## 1. Audience

**Primary:** US adults with **type 2 diabetes** who have been told they have **fatty liver** — clinically, *metabolic dysfunction-associated steatotic liver disease* (**MASLD**), and in its inflammatory form *metabolic dysfunction-associated steatohepatitis* (**MASH**). Typically overweight or living with obesity, often on metformin and frequently on a GLP-1 receptor agonist, SGLT2 inhibitor, insulin, or a sulfonylurea. They cook ordinary US-supermarket food and have about half an hour.

**Secondary:** partners and family cooking the same meals; readers with prediabetes and fatty liver; readers who have been told to "lose some weight" without being told what to cook.

**They left the appointment with a diagnosis and no menu.** The book's job is to be the instruction sheet the appointment did not have time to write.

**Nomenclature.** In June 2023 a multi-society Delphi consensus retired *NAFLD* for **MASLD** and *NASH* for **MASH**. MASLD requires hepatic steatosis plus **at least one of five cardiometabolic criteria** — and **type 2 diabetes is itself one of them**, so essentially every reader of this book who has fatty liver meets the definition. The same consensus set the alcohol boundary for the MASLD label at **≤20 g/day for women and ≤30 g/day for men**; above that, up to 140-350 g/week (female) and 210-420 g/week (male), the condition is reclassified **MetALD**. [`masld-nomenclature-2023`]

**Reader-facing wording.** The book says **"fatty liver"** on the cover and in the recipes, and introduces MASLD/MASH once in the front matter as the terms the reader's clinician will use. Do not scatter acronyms through recipe copy.

### Why this population changes the picture

Five mechanisms drive every rule in §4. Each is the reason a constraint exists, not decoration.

- **Fatty liver and type 2 diabetes are the same metabolic problem seen from two sides.** Pooled global prevalence of MASLD among people with type 2 diabetes is **65.33%** (95% CI 62.35-68.18), rising to **72.65%** in Western countries and from 55.86% in 1990-2004 to **68.81%** in 2016-2021. [`younossi-t2d-prevalence-2024`] The ADA's own consensus report puts it at about **70% of US adults with type 2 diabetes**, roughly half of whom have the progressive MASH form. [`ada-masld-consensus-2025`] This is the book's central promise — *one way of eating, both conditions* — and it is an epidemiological fact, not a marketing line.
- **Weight loss is the therapy, and it is dose-responsive.** **≥5%** of body weight reduces liver fat; **7-10%** improves liver inflammation; **≥10%** improves fibrosis. [`easl-easd-easo-2024` (LoE 2, strong); `aga-2021-lifestyle`; `ada-masld-consensus-2025`] AASLD frames the same gradient as 3-5% improving steatosis with **>10%** generally required to improve MASH and fibrosis. [`aasld-2023`] Everything about recipe energy density follows from this.
- **Fructose is the liver-specific macronutrient.** Excessive fructose raises the risk of MASLD, MASH, and advanced fibrosis **independent of calorie intake**. [`aasld-2023`] In a 7-week randomized controlled trial, 80 g/day of **fructose- or sucrose-**sweetened beverage roughly doubled basal hepatic fatty-acid synthesis at *stable total calorie intake* — while the same dose of **glucose** did not. [`geidl-vidal-fructose-rct-2021`] NIDDK makes the practical point that table sugar (sucrose) is itself "a major source of fructose." [`niddk-nafld-diet`] This is why added sugar, not total carbohydrate, is this book's tightest axis.
- **Diet *quality* moves liver fat even when the scale does not.** A 6-week randomized cross-over trial in biopsy-proven NAFLD found a Mediterranean pattern reduced hepatic steatosis and improved insulin sensitivity versus a low-fat/high-carbohydrate control **without weight loss**. [`ryan-med-diet-2013`] The Mediterranean pattern is the diet named by EASL-EASD-EASO, AGA, and the ADA MASLD consensus alike. [`easl-easd-easo-2024`; `aga-2021-lifestyle`; `ada-masld-consensus-2025`]
- **Protein is protective here, not neutral.** Isocaloric diets at 30% protein — **animal or plant** — reduced liver fat and markers of hepatic necroinflammation and insulin resistance in adults with type 2 diabetes over 6 weeks, **independently of body weight**. [`markova-protein-2017`] The DGA 2025-2030 raised its own protein figure to **1.2-1.6 g/kg/day**. [`dga-2025-2030`] Protein also carries the satiety that makes a hypocaloric plan survivable, and protects lean mass while the reader loses the 7-10% that the liver needs.

---

## 2. Nutrition foundations *(§A)*

### §A. General dietary frame

| # | Principle | Authority |
|---|---|---|
| A1 | **Weight loss, dose-responsive:** **≥5%** reduces liver fat; **7-10%** improves inflammation; **≥10%** improves fibrosis. AASLD: 3-5% improves steatosis, **>10%** generally needed for MASH and fibrosis. Lean patients benefit at **3-5%**. | EASL-EASD-EASO 2024 (LoE 2, strong); AGA 2021; ADA 2025; AASLD 2023 |
| A2 | **Energy:** a hypocaloric diet targeting **1,200-1,500 kcal/day**, *or* a reduction of **500-1,000 kcal/day** from baseline. | AGA 2021 |
| A3 | **Dietary pattern:** improve diet quality toward a **Mediterranean pattern**; it is the pattern named by all three guideline bodies and it lowers liver fat with or without weight loss. | EASL-EASD-EASO 2024 (LoE 2, strong); AGA 2021; ADA 2025; Ryan 2013 |
| A4 | **Ultra-processed food:** limit it — "rich in sugars and saturated fat." Meta-analysis of 9 studies / 60,961 adults finds a **dose-response** rise in NAFLD risk with UPF intake. | EASL-EASD-EASO 2024; Henney 2023 |
| A5 | **Added sugars:** DGA 2025-2030 sets **no more than 10 g of added sugars per meal** and states that no amount of added sugars is recommended as part of a healthy diet. AHA: **<25 g/day (women), <36 g/day (men)**, and <6% of calories. FDA Daily Value: 50 g/day. | DGA 2025-2030; AHA; FDA DV |
| A6 | **Sugar-sweetened beverages and commercial fructose:** **avoid** SSBs; **limit or eliminate commercially produced fructose**. NIDDK names sweetened soft drinks, sports drinks, sweetened tea and **juices**. | EASL-EASD-EASO 2024; AGA 2021; NIDDK; DGA 2025-2030 |
| A7 | **Saturated fat:** **<10% of calories** (FDA DV <20 g/day). Minimize saturated fat "specifically red and processed meat"; replace saturated and trans fats with unsaturated fats, **especially omega-3**. | DGA 2025-2030; AGA 2021; NIDDK; FDA DV |
| A8 | **Carbohydrate — quality first, no ideal percentage.** ADA: there is no ideal percentage of calories from carbohydrate; emphasize **minimally processed, nutrient-dense, high-fiber** sources at **≥14 g fiber per 1,000 kcal**. NIDDK: eat more **low-glycemic-index** foods — most fruits, vegetables, whole grains. DGA: significantly reduce highly processed, **refined carbohydrates**; 2-4 servings whole grains/day. | ADA SoC 2026 §5; NIDDK; DGA 2025-2030; IOM DRI |
| A9 | **Protein:** **1.2-1.6 g/kg/day**. Isocaloric high-protein (30% of energy), animal *or* plant, lowers liver fat in type 2 diabetes independently of weight. ~25-30 g per main meal is the satiety and muscle-protein-synthesis threshold. | DGA 2025-2030; Markova 2017; ISSN 2017; Leidy AJCN |
| A10 | **Sodium:** **<2,300 mg/day** (adults 14+); ADA counsels the same for people with diabetes, best achieved by limiting processed foods. | DGA 2025-2030; ADA SoC 2026 §5; FDA DV |
| A11 | **Alcohol:** **restrict or eliminate.** Moderate use *increases* the probability of advanced fibrosis; heavy use accelerates injury and must be avoided; all alcohol stops **completely and permanently** with advanced fibrosis or cirrhosis. NIDDK: minimize alcohol. | AGA 2021; AASLD 2023; EASL-EASD-EASO 2024 (strong); NIDDK |
| A12 | **Physical activity:** **150-300 min/week moderate** or **75-150 min/week vigorous**, plus resistance training. (Front-matter content — not a recipe rule.) | AGA 2021; EASL-EASD-EASO 2024 (LoE 1, strong) |
| A13 | **Coffee:** associated with less liver damage and ~**35% lower odds** of significant fibrosis; AASLD says 3+ cups/day "could be recommended in the absence of contraindications." **Observational only.** | AASLD 2023; EASL-EASD-EASO 2024 (LoE 4); Hayat 2021 |

### §A2. What distinguishes *this* book

The deltas that make this a **fatty liver + type 2 diabetes** book rather than a generic diabetes cookbook or a generic weight-loss cookbook:

- **Added sugar is the tightest axis in the book, tighter than carbohydrate.** Fructose drives hepatic de novo lipogenesis independently of calories; total carbohydrate does not carry the same liver-specific signal. A main meal is capped at **4 g** added sugar — every recipe therefore sits far inside the DGA's 10 g-per-meal limit, and a full day lands at **22 g**, under the AHA's 25 g women's limit.
- **Every recipe is alcohol-free as an ingredient.** Not "use sparingly" — zero. A cookbook whose subject is liver fat cannot put wine in the pan sauce. This is the book's signature hard block and it is an editorial decision built on A11.
- **Fruit juice is treated as a sugar-sweetened beverage, not as fruit.** NIDDK names juices alongside soda. Whole fruit is encouraged; juice as a recipe component is blocked. (Lemon and lime juice as an acid/flavor agent are exempt — they are the book's main salt replacement.)
- **The book is deliberately NOT low-carbohydrate.** It refuses the "cut all carbs / try keto" advice the reader found online. ADA states there is no ideal carbohydrate percentage; carbohydrate is a **window with a floor**, sized so that a day built entirely of floor-hugging recipes still lands at **~27-28% of energy from carbohydrate** — clear of the <26% very-low-carbohydrate line — because readers on SGLT2 inhibitors are cautioned against ketogenic patterns and readers on insulin or sulfonylureas risk hypoglycemia when carbohydrate drops unannounced.
- **Net carbs are not printed.** ADA and FDA both count **total** carbohydrate; "net carbs" has no regulatory definition and would mislead a reader dosing insulin. This book prints Total Carbohydrate and Dietary Fiber, and nothing derived from subtracting them. *(This is a deliberate divergence from the engine's parent cookbook.)*
- **Protein is a therapeutic axis, not just satiety.** Sourced from fish, poultry, eggs, legumes, tofu, and low-fat dairy — explicitly **not** from red and processed meat, which A7 singles out.
- **Every recipe is on the table in under 30 minutes.** The cover says so and the description answers the objection with "no exceptions." This is an editorial hard promise (§7), not a nutrition rule.

---

## 3. How the diet works — mechanism, medications, and safety *(§B)*

**One root, two symptoms.** Insulin resistance is the shared upstream cause: the liver stores fat it cannot export, and the same resistance leaves glucose in the blood. That is why the levers overlap almost completely and why the book can honestly say the reader is managing *one* problem. Ease insulin resistance — through weight loss, diet quality, fiber, protein, and less fructose — and both numbers move. [`aasld-2023`; `ada-masld-consensus-2025`; `geidl-vidal-fructose-rct-2021`]

**The reader's medications change what a recipe must not do.**

| Medication class | Why it matters for a recipe |
|---|---|
| **GLP-1 RA** (semaglutide, tirzepatide) — now first-line for T2D with MASH | Nausea, early satiety, reduced appetite. Recipes must be **nutrient-dense per bite** — the reader eats less volume, so a low-protein, low-fiber plate fails them. Semaglutide 2.4 mg resolved MASH without worsening fibrosis in **62.9% vs 34.3%** on placebo at 72 weeks. [`essence-semaglutide-2025`; `ada-soc-2026-s4`] |
| **SGLT2 inhibitor** | Ketogenic and very-low-carbohydrate patterns are discouraged (euglycemic ketoacidosis risk). **This is why carbohydrate has a floor.** |
| **Insulin / sulfonylurea** | Hypoglycemia risk. Carbohydrate must be **present and consistent** meal to meal, and printed as **total** carbohydrate so a dose can be matched to it. Skipped meals are a named risk. |
| **Metformin** | GI tolerance; large fat loads and very large single portions are less well tolerated. |
| **Pioglitazone** | Weight gain and fluid retention — reinforces the sodium ceiling and the energy ceiling. |

**Safety boundaries the book must respect.**
- **Chronic kidney disease** is common in long-standing type 2 diabetes and restricts protein (≈0.55-0.60 g/kg/day, or 0.6-0.8 with diabetes) under clinician guidance. The book's protein targets are for readers **without** that restriction; the disclaimer says so. [`kdoqi-ckd-2020`]
- **Advanced fibrosis or cirrhosis inverts several rules** — energy and protein requirements rise (EASL cites ≥35 kcal/kg/day and 1.2-1.5 g/kg/day protein in cirrhosis) and alcohol must stop completely and permanently. This book is written for the **pre-cirrhotic** reader and must direct anyone told they have advanced fibrosis to their hepatologist. [`easl-easd-easo-2024`]
- **Increase fiber gradually** with adequate fluids.

---

## 4. What this means for a *recipe* *(§C — the rules ground truth)*

Recipes are **fixed at 2 servings**; per-serving = one person's per-meal portion. Each constraint is tagged **`[hard]`** (reject and regenerate) or **`[soft]`** (a target; the diet-check warns and keeps the recipe). Per-serving numbers are **derived** — a daily authority target split across the day's eating occasions — not authority-stated.

### The day the envelope is built from

Two day shapes, both supported by the chapter set:

- **Day A** — breakfast `main` + lunch `main` + snack + dinner `main` + dessert
- **Day B** — breakfast `main` + lunch `light_main` (a soup or salad) + snack + dinner `main` + dessert

### Per-serving envelope

| Axis | `main` | `light_main` | `snack` | `dessert` | Tag | Derived from |
|---|---|---|---|---|---|---|
| **Energy** | **380-540 kcal** | **300-440** | **120-230** | **120-220** | `[soft]` | A2 — a ~1,635-1,725 kcal day is a 500-1,000 kcal deficit for this reader |
| **Protein** | floor **26 g**, target 31 | floor **20**, target 24 | floor **5**, target 8 | floor **4**, target 6 | `[soft]` | A9 — ~25-30 g/main meal; day targets = 1.4-1.5 g/kg at 70 kg |
| **Total carbohydrate** | floor **32 g**, target 45, max **55** | floor **25**, target 35, max **45** | floor **10**, target 16, max **24** | floor **14**, target 20, max **28** | `[soft]`, **both ends warn** | A8 — a window, never a ceiling alone; see the floor arithmetic below |
| **Dietary fiber** | floor **≥7 g**, target 9 | **≥6**, target 8 | **≥3**, target 4 | **≥2**, target 3 | `[soft]` | A8 — ≥14 g/1,000 kcal; ≥5.6 g also clears FDA "high fiber" on mains |
| **Added sugars** | **≤4 g** | **≤4** | **≤3** | **≤7** | `[soft]`; **`[hard]`**: no SSB/juice component, no HFCS/agave, not a sugar-delivery vehicle | A5/A6 — the liver-specific axis |
| **Saturated fat** | **≤5 g** | **≤4** | **≤2** | **≤2** | `[soft]`; **`[hard]`**: not built on processed/cured meat or tropical fat | A7 — <10% of energy |
| **Sodium** | **≤550 mg** | **≤500** | **≤250** | **≤150** | `[soft]` | A10 — <2,300 mg/day with margin |
| **Added culinary oil** | **≤1 tbsp** | **≤1 tbsp** | **≤0.5** | **≤0.5** | `[soft]` | A3/A7 — extra-virgin olive oil first |

### The arithmetic these numbers have to survive

Both day shapes were checked against every authority figure they claim to respect:

```
DAY A (3 mains + snack + dessert)          DAY B (2 mains + light_main + snack + dessert)
energy    1,725 kcal at midpoints          energy    1,635 kcal at midpoints
protein   107 g targets = 1.53 g/kg @70kg  protein   100 g targets = 1.43 g/kg @70kg
          87 g floors   = 1.24 g/kg                  81 g floors   = 1.16 g/kg
carbs     120 g at ALL FLOORS = 27.8%      carbs     113 g at ALL FLOORS = 27.6%   <- clears <26%
          171 g targets       = 39.7%                161 g targets       = 39.4%
          217 g maxima        = 50.3%                207 g maxima        = 50.6%   <- inside 45-65% AMDR
fiber      26 g floors = 15.1 g/1,000 kcal fiber      25 g floors = 15.3 g/1,000 kcal  <- clears ADA's 14
added sug  22 g  (AHA: <25 women, <36 men) added sug  22 g   <- and every recipe is under DGA's 10 g/meal
sat fat    19 g = 9.9% of energy           sat fat    18 g = 9.9%   <- clears <10% even at every ceiling
sodium  2,050 mg                           sodium  2,000 mg   <- 11-13% under 2,300
```

**Why the carbohydrate floor exists and must not be quietly removed.** A recipe that is impressively low in carbohydrate is a **defect** in this book. The floors are sized so that a reader who cooks nothing but floor-hugging recipes for a whole day still eats ~27-28% of energy as carbohydrate, above the **<26%-of-energy** line that marks a very-low-carbohydrate pattern. That protects the reader on an SGLT2 inhibitor (ketogenic patterns discouraged) and the reader on insulin or a sulfonylurea (hypoglycemia). It is also the book's editorial position: the reader came here *because* the internet told them to cut all carbs.

**Note on the protein floors.** The floors are the warning line, not the design point. A floor-hugging Day B lands at 1.16 g/kg for a 70 kg reader, just under the DGA's 1.2; the plan's **targets** land at 1.43-1.53 g/kg, inside the 1.2-1.6 band. The personalized plan (`src/planning/personalization.py`) computes an individual figure from body weight.

### Composition & character

- **Plate shape** `[soft]` — each `main` ≈ **½ non-starchy vegetables, ¼-⅓ lean protein, ≤¼ quality carbohydrate** (whole grain, legume, or whole fruit, in a measured portion).
- **Carbohydrate source** `[soft]` — whole/intact grains, legumes, vegetables, whole fruit; **`[hard]`: not a refined-grain base** (white bread, white rice, regular pasta).
- **Fat character** `[soft]` — extra-virgin olive oil first; nuts, seeds, avocado, fatty fish. **`[hard]`: not built on coconut oil, palm oil, or coconut cream** — the "healthy-sounding" saturated fats that would quietly break A7.
- **Cooking** — **`[hard]`: not deep-fried, batter-fried, or breaded-and-fried.** `[soft]`: bake / roast / sheet-pan / grill / broil / steam / poach / simmer / sauté or stir-fry in minimal olive oil / no-cook.
- **Alcohol** — **`[hard]`: no alcoholic ingredient at any quantity** (wine, beer, cider, spirits, liqueur, mirin, sake, cooking wine). Alcohol retention after cooking is unreliable and the subject of the book is the liver.
- **Under 30 minutes** `[soft, editorially near-hard]` — see §7.

### Per-recipe nutrition panel *(what the pipeline computes for every recipe)*

Every recipe carries a **per-serving nutrition panel**, computed via **USDA FoodData Central**: the LLM picks the best-matching food per ingredient, then Python does the per-serving arithmetic — never free-form LLM estimation. `src/nutrition/qualifiers.py` deterministically enforces the salted/unsalted and raw/cooked basis of each pick. The one exception is **added sugars**, which USDA does not carry for generic foods, so it is LLM-estimated from the added sweeteners and flagged as estimated.

**Hero six (printed up front, in this order):** **Calories · Total Carbohydrate · Dietary Fiber · Added Sugars · Protein · Saturated Fat.** Three of them are the liver levers (calories, added sugars, saturated fat) and three are the blood-sugar levers (total carbohydrate, fiber, protein). That is the book's whole thesis in six numbers.

**Tier A — core** (computed, printed, drive the rules): calories `1008`, total carbohydrate `1005`, dietary fiber `1079`, added sugars *(LLM-estimated)*, protein `1003`, saturated fat `1258`, total fat `1004`, sodium `1093`, total sugars `2000`.

**Tier B — extended** (full FDA panel): cholesterol `1253`, trans fat `1257`, potassium `1092`, calcium `1087`, iron `1089`, vitamin D `1114`.

**Tier C — internal/derived** (not printed): saturated-fat % of energy, protein density (g/100 kcal), added-sugar % of energy.

> **On "net carbs":** it has **no legal FDA definition** and is not endorsed by the ADA — both count *total* carbohydrate. The engine's parent cookbook featured it; **this book does not print it**, because the reader may be dosing insulin against the number on the page.

---

## 5. Concern → recipe-characteristic map *(§D)*

| Concern | What the recipe must do |
|---|---|
| **Liver fat (steatosis)** | energy inside the tier band; added sugar at the tightest ceiling in the book; saturated fat ≤10% of energy; unsaturated fat forward; no alcohol; no fructose syrups |
| **Blood-sugar swings** | carbohydrate present, bounded at **both** ends, and quality-forward; fiber floor on every recipe; protein at every eating occasion; no refined-grain base; total carbohydrate printed so a dose can be matched |
| **"Cut all carbs / try keto" advice the reader already found** | a carbohydrate **floor**, stated openly in the front matter, and no "net carbs" number to encourage the habit |
| **Weight loss without hunger** | ≥26 g protein and ≥7 g fiber per main; volume from non-starchy vegetables; energy density kept low so the portion still looks like dinner |
| **GLP-1 RA: small appetite, early satiety, nausea** | nutrient-dense per bite; moderate fat; nothing that only "works" at a large volume; gentle textures available in every chapter |
| **Insulin / sulfonylurea: hypoglycemia** | no meal engineered to be very low carbohydrate; consistent carbohydrate across the day's slots; snack slot is part of the plan, not optional |
| **Sodium and blood pressure (common comorbidity)** | ≤550 mg per main; "no-salt-added"/"low-sodium" specified on every canned or jarred item; acid, herbs and aromatics as the flavor lever rather than salt |
| **"I have no time to cook"** | ≤10 ingredients, ≤25 min active, **≤30 min total**, ≤7 steps, one-pan / sheet-pan / skillet / no-cook |
| **"Special ingredients are expensive"** | every ingredient stocked by a mainstream US supermarket; no health-food-shop items |
| **Fatty liver has no symptoms, so why act now** | front-matter framing only — never a scare claim inside a recipe |

---

## 6. Foods — emphasize / limit / avoid

**Emphasize.** Extra-virgin olive oil; non-starchy vegetables (leafy greens, broccoli, cauliflower, peppers, zucchini, green beans, tomatoes, mushrooms, onions); fish and seafood, especially fatty fish (salmon, sardines, mackerel, trout, tuna); skinless poultry; eggs and egg whites; legumes (beans, lentils, chickpeas) in measured portions; tofu, tempeh, edamame; nonfat/low-fat Greek yogurt and cottage cheese; nuts and seeds including walnuts, chia and ground flax; intact whole grains (oats, quinoa, barley, farro, bulgur, brown rice, whole-grain bread and pasta) in measured portions; whole fruit, especially berries and lower-sugar fruit; garlic, herbs, spices, vinegar, lemon and lime.

**Limit (small measured portions).** Red meat — lean cuts only, modest portions (A7 names red meat specifically); full-fat dairy, butter, cream, full-fat cheese; added sweeteners of any kind, which count against the added-sugar ceiling; dried fruit and higher-sugar tropical fruit; starchy vegetables in large portions; salt.

**Avoid (never build a recipe on these).** Alcohol in any form, including cooking wine and mirin; sugar-sweetened beverages and **fruit juice** as a component; high-fructose corn syrup, corn syrup, and agave nectar; refined-grain bases (white bread, white rice, regular pasta); processed and cured meats (bacon, sausage, hot dogs, deli meats, salami); deep-fried food and batter-fried food; coconut oil, palm oil, palm kernel oil, and coconut cream; ultra-processed snack foods and pastries; heavy cream, cheese and butter sauces.

---

## 7. "Under 30 minutes, everyday ingredients" — editorial constraints *(not medical claims)*

Taken straight from the cover and the description, and kept separate from the nutrition rules:

- **≤ 30 minutes total** (prep + cook), **≤ 25 minutes active.** The description answers the "no time" objection with *"Under thirty minutes, every recipe, no exceptions."* Treat 30 as the promise, not a guideline. Optional chilling or marinating time lives in the separate `passive_time` field, must be genuinely optional or clearly labeled make-ahead, and never counts toward the 30.
- **≤ 10 ingredients** (excluding salt, pepper, water, and a small measured oil).
- **≤ 7 steps.**
- **Common home kitchen** — stovetop, oven, sheet pan, skillet, blender. **No air fryer, pressure cooker, sous-vide, or specialty gear**: the recipe must work for a reader who owns none of them.
- **Everyday ingredients** — everything stocked by a mainstream US supermarket (Walmart, Kroger, Target). No health-food-shop items (protein powder, nutritional yeast, psyllium, specialty flours, vital wheat gluten, aminos), no international-market-only items.
- Favor **one-pan / sheet-pan / skillet / one-bowl / no-cook** and meal-prep-friendly formats. Still written for **2 servings**.
- Oven temperatures in **°F and °C**; stovetop heat as a level word plus a sensory cue, never a numeric setpoint.

---

## 8. Claims this book must NOT make

Recorded so the position is auditable and cannot be quietly re-litigated:

1. **No "detox," "cleanse," or "flush" language.** No food, drink, or recipe detoxifies a liver. Nothing in the retrieved guidance supports it.
2. **No cure or reversal promise.** The weight-loss thresholds in A1 are dose-response *probabilities* from trials. "Helps lower liver fat" is the honest verb; "reverses fatty liver" is not.
3. **No per-recipe glycemic index or glycemic load number.** GI is not reliably computable for a mixed cooked dish from a food database, and no guideline body endorses a GI/GL target. NIDDK's "eat more low-glycemic-index foods" is citable as a *food-choice* direction; a number on a recipe card is not. Build on **fiber and carbohydrate quality** instead.
4. **No vitamin E recommendation.** AASLD's vitamin E evidence (800 IU/day) is for **non-diabetic**, non-cirrhotic biopsy-proven MASH — the precise opposite of this reader. It must not appear as advice.
5. **No named "liver superfoods."** No turmeric, milk thistle, apple cider vinegar, lemon water, beetroot, or dandelion claims.
6. **No "a little alcohol is fine."** AASLD: moderate alcohol use increases the probability of advanced fibrosis. The book's position is zero in recipes and "ask your clinician" in the front matter.
7. **Coffee is an association, not a prescription.** A13 is observational (EASL grades it LoE 4). It may be mentioned once in the front matter with that caveat; it is not a treatment claim and not a recipe ingredient rule.
8. **No "net carbs."** See §4.
9. **No metabolism-boosting or fat-burning language.**

---

## 9. The chapters

**8 chapters, 100 recipes** — mapped 1:1 onto the six content blocks the book's description promises, with "everyday dinners, chicken and fish and vegetables" split three ways so the biggest slot browses well and the meal planner has variety to draw on. 100 satisfies the cover's "100+ Recipes".

| slug | printed chapter title | meal slot | tier | target |
|---|---|---|---|---|
| `breakfasts` | Breakfasts | breakfast | `main` | 16 |
| `soups_salads` | Soups & Salads | lunch | `light_main` | 14 |
| `lunches` | Lunches | lunch | `main` | 14 |
| `poultry_meat_dinners` | Chicken, Turkey & Lean Meat Dinners | dinner | `main` | 13 |
| `fish_seafood_dinners` | Fish & Seafood Dinners | dinner | `main` | 11 |
| `vegetable_meatless_dinners` | Vegetable & Meatless Dinners | dinner | `main` | 10 |
| `snacks_sides` | Snacks & Sides | snack | `snack` | 12 |
| `desserts` | Desserts | dessert | `dessert` | 10 |

**Where the count sits, and why.** The book is sized against its own **30-day meal plan**, so the
question for each chapter is how often a reader repeats a recipe across 30 days:

| slot | recipes | slots in 30 days | repeats |
|---|---|---|---|
| breakfast | 16 | 30 | ~1.9× |
| lunch (`soups_salads` + `lunches`) | 28 | 30 | ~1.1× |
| **dinner** (three chapters) | **34** | **30** | **~0.9×** |
| snack | 12 | 30 | 2.5× |
| dessert | 10 | 30 (optional slot) | 3× |

Dinner is the only block that covers its slots without repeating, which is why the trim from an
earlier 106-recipe plan came entirely out of the three dinner chapters (two each) rather than being
spread evenly: at 40 they were over-supplied against a 30-day plan. Dessert repeats most often, but
it is the one **optional** slot (see `OPTIONAL_MEAL_TYPES`), so a reader who skips it never notices.

Default chapter: **`poultry_meat_dinners`**. Three chapters share the `dinner` slot and two share `lunch`, so the chapter→meal-slot map is not a bijection — `MEAL_TYPE_DEFAULT_CHAPTER` in `src/constants.py` nominates one chapter per slot.

`soups_salads` is the only `light_main` chapter, and that is the point of the tier: a soup or salad eaten as a lunch is a real meal but a smaller one, and judging it against full-main bounds would false-flag every recipe in the chapter. It is also the only tier whose *raw-weight* ceiling is the highest in the book — a brothy soup for two is mostly water by weight.

`snacks_sides` deliberately holds two kinds of recipe: portable snacks that bridge meals, and vegetable sides that turn a plain protein into a dinner. Sides are legitimately lower in protein than snacks, which is why that tier's protein floor is a nudge (5 g) rather than a gate.

---

## 10. Verification status — read before print

| Item | Status |
|---|---|
| EASL-EASD-EASO 2024 weight-loss thresholds, diet-quality, physical-activity, alcohol and cirrhosis figures | **Retrieved** from the PMC executive summary (PMC11519095). The full *Journal of Hepatology* article returned HTTP 403. |
| AASLD 2023 weight-loss, fructose, alcohol-category, coffee, exercise, vitamin E and pioglitazone statements | **Retrieved** from the PMC full text (PMC10735173). |
| AGA 2021 Best Practice Advice (weight-loss %, 1,200-1,500 kcal/day or -500 to -1,000 kcal/day, Mediterranean, saturated fat/red meat, commercial fructose, alcohol, exercise minutes) | **Retrieved** from gastro.org. |
| ADA MASLD consensus report 2025 (Diabetes Care 48(7):1057-1082) | **Not directly retrieved** — the PDF and article page returned HTTP 403. Figures (≈70% MASLD in US T2D, ~half MASH; Mediterranean pattern; weight-loss thresholds) taken from the official abstract and society summaries, and each is corroborated by a second source already retrieved. **Re-verify the exact wording before print.** |
| ADA Standards of Care 2026 §4 and §5 | **Not directly retrieved** — diabetesjournals.org returned HTTP 403. FIB-4 screening, GLP-1 RA preference, "no ideal percentage", ≥14 g fiber/1,000 kcal, added-sugar minimization, sodium <2,300 mg and the 5-7% weight target are from ADA-derived summaries. **Re-verify recommendation numbers and grades before print.** |
| DGA 2025-2030 (published 2026-01-07): added sugars ≤10 g per meal, saturated fat <10% kcal, sodium <2,300 mg (14+), protein 1.2-1.6 g/kg, whole grains 2-4 servings/day, "avoid sugar-sweetened beverages", "significantly reduce highly processed refined carbohydrates" | **Retrieved** from a guideline-summary service and the Harvard Nutrition Source commentary; dietaryguidelines.gov itself failed to fetch and realfood.gov served an image-only PDF. The **10 g added sugars per meal** figure is load-bearing for §4 — **re-verify it against the primary document before print.** |
| MASLD nomenclature, cardiometabolic criteria, alcohol thresholds, MetALD bands | **Retrieved** (multi-society Delphi, 2023). |
| Younossi 2024 T2D prevalence 65.33% (95% CI 62.35-68.18) | **Retrieved** from the published meta-analysis summary. Supports the description's "two out of three." |
| Fructose/sucrose vs glucose DNL RCT (94 men, 80 g/day, 7 weeks) | **Retrieved.** |
| Markova 2017 isocaloric high-protein liver-fat trial | **Retrieved** (design and direction confirmed; the *percentage* reductions in liver fat could **not** be retrieved — the Gastroenterology full text returned 403. **Do not print a percentage** for this study.) |
| Ryan 2013 Mediterranean cross-over trial | **Retrieved** (design and direction). One secondary source quotes "39% reduction in hepatic steatosis" for a different 12-week trial (n=259); that figure is **not** attributed here and must not be printed. |
| FDA Daily Values, 21 CFR 101.9 and 101.54, USDA FoodData Central, AHA figures | Carried over verified from the parent engine's spec, where they were cross-checked; USDA nutrient IDs 1235/1092/1114 were verified against the live `nutrient.csv` on 2026-07-19. |

---

## 11. Sources

1. **EASL-EASD-EASO.** *Clinical Practice Guidelines on the management of metabolic dysfunction-associated steatotic liver disease (MASLD)*, 2024 — Executive Summary. — https://pmc.ncbi.nlm.nih.gov/articles/PMC11519095/ (weight loss ≥5% liver fat / 7-10% inflammation / ≥10% fibrosis, LoE 2 strong; Mediterranean-like diet quality; limit ultra-processed food; avoid sugar-sweetened beverages; >150 min/wk moderate or 75 min/wk vigorous, LoE 1 strong; stop alcohol completely in advanced fibrosis/cirrhosis; cirrhosis ≥35 kcal/kg/day and 1.2-1.5 g/kg protein)
2. **Rinella ME, Neuschwander-Tetri BA, Siddiqui MS, et al.** *AASLD Practice Guidance on the clinical assessment and management of nonalcoholic fatty liver disease.* Hepatology 2023;77:1797-1835. — https://pmc.ncbi.nlm.nih.gov/articles/PMC10735173/ (3-5% weight loss improves steatosis, >10% generally needed for MASH/fibrosis; excess fructose raises risk independent of calories; alcohol mild ≤20 g/d women, ≤30 g/d men, moderate use increases probability of advanced fibrosis; coffee 3+ cups/day; ≥150 min/wk moderate exercise; vitamin E 800 IU in **non-diabetic** non-cirrhotic; pioglitazone 30-45 mg)
3. **Younossi ZM, et al.** *AGA Clinical Practice Update on Lifestyle Modification Using Diet and Exercise to Achieve Weight Loss in the Management of NAFLD: Expert Review.* Gastroenterology 2021. — https://gastro.org/clinical-guidance/lifestyle-modification-using-diet-and-exercise-to-achieve-weight-loss-in-the-management-of-nonalcoholic-fatty-liver-disease-nafld/ (≥5% steatosis, ≥7% NASH resolution, ≥10% fibrosis regression; hypocaloric 1,200-1,500 kcal/d **or** -500 to -1,000 kcal/d; Mediterranean diet; minimize saturated fat, specifically red and processed meat; limit or eliminate commercially produced fructose; alcohol restricted or eliminated; 150-300 min moderate / 75-150 min vigorous per week; lean NAFLD 3-5%)
4. **Cusi K, Abdelmalek MF, Apovian CM, et al.** *MASLD in People With Diabetes: The Need for Screening and Early Intervention. A Consensus Report of the American Diabetes Association.* Diabetes Care 2025;48(7):1057-1082. — https://diabetesjournals.org/care/article/48/7/1057/160536/ (≈70% of US adults with T2D have MASLD, about half with MASH; Mediterranean pattern; ≥5% / 7-10% / ≥10% weight-loss targets; GLP-1 RA and pioglitazone) *(403 to the fetcher — see §9)*
5. **American Diabetes Association.** *4. Comprehensive Medical Evaluation and Assessment of Comorbidities: Standards of Care in Diabetes-2026.* Diabetes Care 2026;49(Suppl 1). — https://pubmed.ncbi.nlm.nih.gov/41358897/ (screen all adults with type 2 diabetes or prediabetes for liver fibrosis with FIB-4 regardless of liver enzymes; FIB-4 ≥1.3 → VCTE or ELF; GLP-1 RA with demonstrated MASH benefit preferred) *(403 to the fetcher — see §9)*
6. **American Diabetes Association.** *5. Facilitating Positive Health Behaviors and Well-being to Improve Health Outcomes: Standards of Care in Diabetes-2026.* Diabetes Care 2026;49(Suppl 1):S89. — https://diabetesjournals.org/care/article/49/Supplement_1/S89/163932/ (no ideal percentage of calories from carbohydrate, protein or fat; minimally processed nutrient-dense high-fiber carbohydrate at ≥14 g fiber/1,000 kcal; minimize added sugar; sodium <2,300 mg/day; weight-loss target 5-7% of baseline) *(403 to the fetcher — see §9)*
7. **USDA & HHS.** *Dietary Guidelines for Americans, 2025-2030* (published 2026-01-07). — https://www.dietaryguidelines.gov/ (added sugars: no more than 10 g per meal, and no amount recommended; saturated fat <10% of calories; sodium <2,300 mg/day ages 14+; protein 1.2-1.6 g/kg/day; whole grains 2-4 servings/day; avoid sugar-sweetened beverages; significantly reduce highly processed refined carbohydrates; limit non-nutritive sweeteners) *(see §9)*
8. **FDA.** *Daily Value on the Nutrition and Supplement Facts Labels.* — https://www.fda.gov/food/nutrition-facts-label/daily-value-nutrition-and-supplement-facts-labels (fiber 28 g, protein 50 g, total carb 275 g, total fat 78 g, sat fat 20 g, added sugars 50 g, sodium 2,300 mg, cholesterol 300 mg, vitamin D 20 mcg, calcium 1,300 mg, iron 18 mg, potassium 4,700 mg)
9. **FDA / eCFR 21 CFR 101.9.** *Nutrition labeling of food* — mandatory panel; Total Carbohydrate with Dietary Fiber and Sugars beneath; "net carbs" has no regulatory definition. — https://www.ecfr.gov/current/title-21/chapter-I/subchapter-B/part-101/subpart-A/section-101.9
10. **FDA / eCFR 21 CFR 101.54.** *Nutrient content claims* — "good source" 10-19% DV, "high"/"excellent source" ≥20% DV per RACC (⇒ "high fiber" ≥5.6 g, "high protein" ≥10 g per serving). — https://www.ecfr.gov/current/title-21/chapter-I/subchapter-B/part-101/subpart-D/section-101.54
11. **American Heart Association.** *Added Sugars.* — https://www.heart.org/en/healthy-living/healthy-eating/eat-smart/sugar/added-sugars (no more than 25 g / 6 tsp / 100 kcal per day for women and 36 g / 9 tsp / 150 kcal for men; <6% of calories)
12. **Rinella ME, Lazarus JV, Ratziu V, et al.** *A multisociety Delphi consensus statement on new fatty liver disease nomenclature.* J Hepatol / Hepatology 2023. — https://www.journal-of-hepatology.eu/article/S0168-8278(23)00418-X/fulltext (NAFLD → MASLD, NASH → MASH; ≥1 of 5 cardiometabolic criteria, of which **type 2 diabetes is one**; alcohol ≤20 g/d women and ≤30 g/d men; MetALD 140-350 g/wk female, 210-420 g/wk male)
13. **Younossi ZM, et al.** *The Global Epidemiology of Nonalcoholic Fatty Liver Disease and Nonalcoholic Steatohepatitis Among Patients With Type 2 Diabetes.* Clin Gastroenterol Hepatol 2024. — https://pubmed.ncbi.nlm.nih.gov/38521116/ (pooled MASLD prevalence in T2D 65.33%, 95% CI 62.35-68.18; Western countries 72.65%; 55.86% in 1990-2004 → 68.81% in 2016-2021)
14. **Geidl-Flueck B, et al.** *Fructose- and sucrose- but not glucose-sweetened beverages promote hepatic de novo lipogenesis: a randomized controlled trial.* J Hepatol 2021. — https://pubmed.ncbi.nlm.nih.gov/33684506/ (94 healthy men, 80 g/day for 7 weeks at stable calorie intake; fructose and sucrose raised basal hepatic fatty-acid synthesis, glucose did not)
15. **NIDDK (NIH).** *Eating, Diet, & Nutrition for NAFLD & NASH.* — https://www.niddk.nih.gov/health-information/liver-disease/nafld-nash/eating-diet-nutrition (replace saturated and trans fats with unsaturated, especially omega-3; eat more low-glycemic-index foods — most fruits, vegetables, whole grains; avoid foods and drinks with large amounts of simple sugars, especially fructose, found in sweetened soft drinks, sports drinks, sweetened tea and juices; table sugar is a major source of fructose; minimize alcohol)
16. **Ryan MC, et al.** *The Mediterranean diet improves hepatic steatosis and insulin sensitivity in individuals with non-alcoholic fatty liver disease.* J Hepatol 2013;59:138-43. — https://pubmed.ncbi.nlm.nih.gov/23485520/ (6-week randomized cross-over in biopsy-proven NAFLD; reduced steatosis and improved insulin sensitivity vs a low-fat/high-carbohydrate control **without weight loss**)
17. **Markova M, Pivovarova O, Hornemann S, et al.** *Isocaloric Diets High in Animal or Plant Protein Reduce Liver Fat and Inflammation in Individuals With Type 2 Diabetes.* Gastroenterology 2017;152:571-585. — https://pubmed.ncbi.nlm.nih.gov/27765690/ (37 adults with T2D; 6 weeks isocaloric 30% protein / 40% carbohydrate / 30% fat; liver fat and markers of hepatic necroinflammation and insulin resistance fell with **both** animal- and plant-protein diets, independently of body weight)
18. **Henney AE, et al.** *Ultra-Processed Food Intake Is Associated with Non-Alcoholic Fatty Liver Disease in Adults: A Systematic Review and Meta-Analysis.* Nutrients 2023. — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10224355/ (9 studies, 60,961 participants; moderate and high UPF intake both raise NAFLD risk, dose-responsive)
19. **Hayat U, et al.** *Effect of Coffee Consumption on Non-Alcoholic Fatty Liver Disease Incidence, Prevalence and Risk of Significant Liver Fibrosis: Systematic Review with Meta-Analysis of Observational Studies.* 2021. — https://pubmed.ncbi.nlm.nih.gov/34578919/ (~35% lower odds of significant fibrosis; benefit above ~2-3 cups/day; observational)
20. **Newsome PN, Sanyal AJ, et al.** *Phase 3 Trial of Semaglutide in Metabolic Dysfunction-Associated Steatohepatitis (ESSENCE).* N Engl J Med 2025;392:2089-2099. — https://pubmed.ncbi.nlm.nih.gov/40305708/ (week 72: MASH resolution without worsening fibrosis 62.9% vs 34.3%; fibrosis improvement without worsening MASH 36.8% vs 22.4%; mean body-weight change -10.5% vs -2.0%)
21. **Jäger R, et al.** *ISSN Position Stand: Protein and Exercise.* J Int Soc Sports Nutr 2017. — https://pmc.ncbi.nlm.nih.gov/articles/PMC5477153/ (per-meal 0.25 g/kg or 20-40 g high-quality protein; 1.4-2.0 g/kg/day safe for kidney and bone in healthy adults)
22. **Leidy HJ, et al.** *The role of protein in weight loss and maintenance.* Am J Clin Nutr. — https://ajcn.nutrition.org/article/S0002-9165(23)27427-4/fulltext (1.2-1.6 g/kg/day preserves lean mass during weight loss; ~25-30 g protein/meal satiety threshold)
23. **IOM/NASEM DRI — Fiber** (Adequate Intake 14 g/1,000 kcal), via Linus Pauling Institute. — https://lpi.oregonstate.edu/mic/other-nutrients/fiber
24. **NKF KDOQI.** *Clinical Practice Guideline for Nutrition in CKD*, 2020 (AJKD) — protein 0.55-0.60 g/kg/day, or 0.6-0.8 g/kg/day with diabetes, under clinician guidance. — https://www.ajkd.org/article/S0272-6386(20)30726-5/fulltext
25. **American Heart Association.** *Fish and Omega-3 Fatty Acids* — two ~3.5 oz servings/week of non-fried fish, preferring fatty fish. — https://www.heart.org/en/healthy-living/healthy-eating/eat-smart/fats/fish-and-omega-3-fatty-acids
26. **Mayo Clinic.** *Healthy cooking basics.* — https://www.mayoclinic.org/healthy-lifestyle/nutrition-and-healthy-eating/basics/healthy-cooking/hlv-20049477 (prefer bake/roast/grill/broil/steam/poach/sauté in minimal oil; increase fiber gradually with adequate fluids)
27. **USDA FoodData Central** — Foundation Foods + SR Legacy + FNDDS for generic ingredients; per-100 g values; **no added-sugars value for generic foods**, so it is estimated. — https://fdc.nal.usda.gov/

---

## 12. Machine-readable storage

The structured spec is `data/fatty_liver_diabetes_guidelines.yaml`, registered in `src/config.py` and loaded by `src/diet_rules/spec.py`. It carries the four per-tier envelopes (`per_recipe_constraints.meal_categories`), the eight hard blocks, the eight chapters (`recipe_categories`), the nutrition panel, and the pre-rendered `prompt_snippets.{ideation, drafting, critic}` injected into generation. Validate with:

```bash
python "C:/Users/terja/Documents/AI_Projects/.claude/skills/cookbook-recipe-system/scripts/validate_spec.py" data/fatty_liver_diabetes_guidelines.yaml
```

The per-serving numbers in §4 above are duplicated by design in three places — this table, the YAML `meal_categories`, and the YAML `prompt_snippets.drafting` prose. `tests/test_spec_coherence.py` asserts that all three agree, and additionally pins the day arithmetic in §4 (the carbohydrate floors clearing 26% of energy, fiber clearing ADA's 14 g/1,000 kcal, sodium and added sugar under their daily limits, saturated fat under 10% of energy). When a number changes, change it in all three places and re-run that file.
