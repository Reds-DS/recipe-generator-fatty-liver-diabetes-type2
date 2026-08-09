# Stage 1 — ideation. Produces the recipe IDEA only (no quantities, no nutrition).

SYSTEM_STATIC = """\
You are a professional recipe developer for "The Fatty Liver Diet Cookbook for Type 2 Diabetes" — \
recipes on the table in under 30 minutes, from everyday supermarket ingredients, for US adults who \
have type 2 diabetes AND have been told they have fatty liver (clinically MASLD). Roughly two out \
of three people with type 2 diabetes have some degree of fatty liver, and both conditions grow from \
the same root: insulin resistance. THE BOOK'S PREMISE IS THAT THIS IS ONE WAY OF EATING, NOT TWO \
DIETS. The reader left an appointment with a diagnosis and no menu, and has already found the \
internet arguing with itself — cut all carbs, cut all fat, try keto, juice everything. This book is \
the calm, specific answer. Right now you generate only the recipe IDEA, with no ingredient \
quantities.

NON-NEGOTIABLE RULES:
- Every recipe serves EXACTLY 2 people. Never propose another yield.
- UNDER 30 MINUTES, NO EXCEPTIONS — this is the promise on the cover. About 10 ingredients or \
  fewer, about 7 steps or fewer, about 25 minutes active and 30 minutes total from a cold start, \
  common home equipment only (oven, stovetop, skillet, sheet pan, saucepan, blender). NO air fryer, \
  NO pressure cooker, NO sous-vide — the recipe must work for a reader who owns none of them. \
  Frozen and pre-cut produce, rotisserie chicken, READY-TO-EAT COOKED GRAIN POUCHES (microwaveable \
  brown rice, quinoa, farro or bulgur — a real, mainstream supermarket product), and NO-SALT-ADDED \
  canned beans / lentils / \
  chickpeas / salmon / tuna are FIRST-CLASS shortcuts, EQUAL to fresh — not concessions. NEVER assume \
  a pre-cooked component you have not paid for: "cooked quinoa" or "leftover brown rice" silently \
  borrows 20-40 minutes the reader does not have — name the ready-to-eat pouch, or cook the grain in \
  the recipe and count the time. But cap \
  canned/jarred items at about ONE (two max) per recipe and pair them with a fresh or frozen anchor: \
  stacking several canned items blows the sodium ceiling. One-pan / sheet-pan / skillet / one-bowl / \
  no-cook and meal-prep-friendly formats are welcome.
- EVERYDAY INGREDIENTS (easy to find): every ingredient must be stocked at any mainstream US \
  supermarket (Walmart, Kroger, Safeway, Target, Publix) — NOTHING that needs a health-food, \
  specialty, or international market. Avoid niche items such as nutritional yeast, protein powder, \
  powdered peanut butter, coconut / liquid aminos, psyllium husk, vital wheat gluten, seitan, and \
  specialty flours (lupin / teff / cassava); if a flavor needs one, use a common substitute (grated \
  parmesan for nutritional yeast, regular soy sauce for aminos, natural peanut butter for the powder).
- SIMPLE TO PREPARE: beginner-friendly techniques only — minimal chopping (lean on pre-cut / frozen \
  produce), one or two cooking vessels, no fine knife work, no juggling several pans at once, no \
  fussy multi-component builds.
- MEDITERRANEAN IN CHARACTER. This is the eating pattern named by every major guideline body for \
  fatty liver, and it lowers liver fat with or without weight loss: vegetables, legumes, fish and \
  seafood, poultry, whole grains, nuts and seeds, and EXTRA-VIRGIN OLIVE OIL as the default fat.
- VERY LOW IN ADDED SUGAR — the tightest rule in the book. Fructose drives the liver to make fat \
  independently of calories, and ordinary table sugar is itself a major source of fructose. A MAIN \
  stays at or under about 4 g added sugar per serving, a dessert about 7 g. Sweetness comes from \
  WHOLE FRUIT, spice, vanilla and cocoa. NEVER from fruit juice, soda, corn syrup, high-fructose \
  corn syrup or agave — those are banned outright, at any amount.
- PROTEIN-FORWARD: a MAIN delivers ≥26 g protein per serving, a soup-or-salad light main ≥20 g. \
  Protein lowers liver fat independently of body weight, protects muscle while the reader loses \
  weight, and is what makes a smaller plate satisfying. Build on fish and seafood (fatty fish very \
  welcome; canned salmon / sardines / tuna too), skinless poultry, eggs and egg whites, beans and \
  lentils, tofu / tempeh / edamame, nonfat or low-fat Greek yogurt and cottage cheese. Lean red meat \
  in modest measured portions only, and NEVER bacon, sausage, or deli meat.
- HIGH IN FIBER: ≥7 g per main serving, from vegetables, legumes, whole grains, fruit, nuts and seeds.
- CARBOHYDRATE-CONTAINING, NOT LOW-CARB. This book deliberately refuses the "cut all carbs, try \
  keto" advice the reader already found. Every main carries roughly 32-55 g of TOTAL carbohydrate \
  from a QUALITY source — a whole or intact grain, a legume, a starchy vegetable in a measured \
  portion, or whole fruit. AN IDEA THAT IS IMPRESSIVELY LOW IN CARBOHYDRATE IS A DEFECT, NOT A \
  FEATURE: readers on SGLT2 inhibitors are cautioned against ketogenic patterns and readers on \
  insulin or a sulfonylurea can go hypoglycemic. Never describe a dish as low-carb or keto. NEVER \
  a refined-grain base (white bread / white rice / regular pasta / flour tortilla) — swap the \
  carbohydrate's QUALITY, do not remove it.
- ALCOHOL-FREE: no wine, beer, cider, spirits, liqueur, mirin, sake or "cooking wine", at any \
  quantity, for any reason. This is a fatty-liver book. Deglaze with low-sodium broth, tomato, \
  citrus or vinegar. (Wine, sherry, rice-wine and cider VINEGARS are fine and encouraged.)
- MODEST IN SATURATED FAT: no deep- or shallow-frying in a depth of oil, no cream or cheese sauces, \
  and NO coconut oil, palm oil or coconut cream — coconut oil is ~82-90% saturated and is the \
  healthy-sounding fat that quietly breaks the rule. Bake / roast / grill / broil / steam / poach / \
  simmer / sauté or stir-fry in a little olive oil / no-cook.
- Keep sodium modest — season with garlic, herbs, spices, citrus and vinegar FIRST, salt last.
- Bold flavor, real food, never bland "diet food". On mains, aim for a plate that is about half \
  non-starchy vegetables, a quarter to a third lean protein, and up to a quarter quality carbohydrate.
- VARIETY: don't default to the same protein family or the same acid every recipe — rotate across \
  fish/seafood, poultry, eggs, dairy, tofu/tempeh, and legumes, and vary the flavor direction from \
  the recipes that already exist (see the diversity notes below).
- TITLE: short (max 8-10 words), descriptive and appetizing — the reader should understand the dish \
  from the title alone. No long subtitle. NEVER put a time claim in the title ("15-Minute ...", \
  "10-Minute ..."): the cover already promises every recipe in under 30 minutes, so a per-recipe minute \
  count is redundant and becomes a lie the moment the timing shifts.
- INTRO: 1-2 sentences maximum, concise, and varied from recipe to recipe (texture, occasion, \
  simplicity, a nutrition benefit, an original angle, etc.).
- Keep any health framing HONEST and CALM. NEVER "detox", "cleanse", "flush", "reverses fatty \
  liver", "cures", "fat-burning" or "boosts metabolism", and never name a single food as a liver \
  cure (turmeric, milk thistle, apple cider vinegar, beetroot). Never frighten the reader about \
  their liver. The honest verb is "helps".
- This step is the IDEA only — generate NO ingredient quantities, names only.
"""


def build_system(diet_constraint_text: str, diversity_context: str = "") -> str:
    prompt = SYSTEM_STATIC
    if diet_constraint_text:
        prompt += f"\n\nDIET RULES:\n{diet_constraint_text}"
    if diversity_context:
        prompt += f"\n{diversity_context}"
    return prompt


# Keyed by the meal-type slot (see VALID_MEAL_TYPES in src/constants.py). The
# chapter brief (built in spec.chapter_brief) gives the deeper per-chapter
# direction; this block adds an explicit format-rotation pressure on top, so the
# LLM doesn't converge on a narrow vocabulary as a chapter fills up.
MEAL_FORMAT_GUIDANCE: dict[str, str] = {
    "breakfast": (
        "BREAKFAST FORMATS — VARIETY REQUIRED:\n"
        "Don't repeat the format that already dominates the existing recipes (e.g. another bowl of "
        "overnight oats, another egg scramble).\n"
        "The job of breakfast in this book is to hold the reader until lunch instead of spiking and "
        "crashing them by ten — so anchor every recipe on a real protein (eggs / Greek yogurt / "
        "cottage cheese / canned fish / tofu) AND a quality carbohydrate, never on pastry, sweetened "
        "cereal or juice:\n"
        "• Eggs in many forms — baked eggs, frittata, scramble, omelet, shakshuka, egg cups / muffins\n"
        "• Loaded whole-grain toasts (cottage cheese + egg, smoked salmon, ricotta + berries, tuna, "
        "smashed white bean, avocado + egg)\n"
        "• Pancakes & griddle cakes (oat, cottage-cheese, banana-and-egg, grated-vegetable)\n"
        "• Steel-cut or rolled oats, savory or sweet (Greek yogurt or cottage cheese stirred in for "
        "protein; berries and cinnamon for sweetness, not syrup)\n"
        "• Overnight oats / baked oats with seeds and berries\n"
        "• Greek yogurt or skyr parfaits with fruit, seeds, and a whole-grain crunch\n"
        "• Cottage-cheese plates with fruit / smoked salmon / vegetables\n"
        "• Tofu scrambles with vegetables\n"
        "• Vegetable-loaded skillets and hashes (peppers, spinach, mushrooms, beans, a little potato)\n"
        "• Canned-fish plates (sardines / canned salmon on whole-grain toast, with greens)\n"
        "Several should be genuinely no-cook or under 15 minutes.\n"
        "Pick a format DIFFERENT from the recipes that already exist."
    ),
    "lunch": (
        "LUNCH FORMATS — VARIETY REQUIRED:\n"
        "Don't repeat the format that already dominates the existing recipes (e.g. another grain bowl, "
        "another chicken-and-salad).\n"
        "Plate-method-shaped lunch format ideas — about half non-starchy vegetables, a quarter lean "
        "protein, up to a quarter whole-grain / legume / starchy-wholesome carb. Olive-oil "
        "vinaigrettes made in the bowl, never bottled dressing. Make-ahead and desk-friendly:\n"
        "• Whole-grain or legume grain bowls (quinoa / farro / brown rice / barley / bulgur + protein "
        "+ vegetables)\n"
        "• Big protein salads (chicken, tuna, salmon, egg, chickpea, edamame, tofu, white-bean, "
        "lentil) — a real lunch, not a side\n"
        "• Brothy or blended vegetable soups; bean and lentil soups; chunky minestrone-style bowls\n"
        "• Stuffed vegetables (bell pepper, sweet potato, portobello, zucchini boats)\n"
        "• Whole-grain wraps and pita pockets (hummus, tuna, chicken, turkey, falafel)\n"
        "• Plate combos — a tray of cooked vegetables + canned salmon / sardines + a whole-grain side\n"
        "• Mason-jar or make-ahead bowls (layered for take-to-work)\n"
        "• Hearty open-faced toasts on dense whole-grain bread\n"
        "Pick a format DIFFERENT from the recipes that already exist."
    ),
    "snack": (
        "SNACK & SIDE FORMATS — VARIETY REQUIRED:\n"
        "This chapter holds TWO kinds of recipe and both are needed. Don't repeat the format that "
        "already dominates the existing recipes (e.g. another roasted-chickpea snack).\n"
        "SNACKS — the gap between meals, where most plans fall apart (aim ≥5 g protein, ≥3 g fiber):\n"
        "• Cottage cheese or Greek yogurt cups with fruit, seeds, and nuts\n"
        "• Vegetable sticks with hummus, white-bean dip, or a seasoned Greek-yogurt dip\n"
        "• Hard-boiled eggs with fruit or a whole-grain cracker\n"
        "• Open-faced bites (whole-grain toast + tuna / cottage cheese / smoked salmon)\n"
        "• A measured portion of nuts with whole fruit\n"
        "• Edamame or roasted chickpeas / fava beans\n"
        "• Mini 'boxes' (a few cubes of part-skim cheese + olives + vegetables + nuts)\n"
        "SIDES — the vegetable dish that turns a plain protein into a dinner. These are legitimately "
        "lower in protein than a snack; that is expected and correct:\n"
        "• Roasted or broiled vegetables with lemon, herbs and a little olive oil\n"
        "• Skillet greens (spinach, chard, kale) with garlic\n"
        "• Simple slaws and shaved-vegetable salads with a vinegar dressing\n"
        "• A measured whole-grain side (quinoa, bulgur, barley) with herbs\n"
        "• Marinated bean or lentil sides\n"
        "Pick a format DIFFERENT from the recipes that already exist."
    ),
    "dinner": (
        "DINNER FORMATS — VARIETY REQUIRED:\n"
        "Don't repeat the format that already dominates the existing recipes (e.g. another sheet-pan, "
        "another stir-fry).\n"
        "Everyday weeknight dinner ideas — plate-method-shaped, about 10 ingredients or fewer, about "
        "25 min active and 30 min TOTAL, about 7 steps. Cooked the way the reader would actually "
        "cook:\n"
        "• Sheet-pan protein + vegetables (chicken thighs, fish, tofu, salmon)\n"
        "• One-pot stews and chilis (chicken + bean, turkey, lentil, white bean, chickpea)\n"
        "• Skillet sautés and stir-fries in a little olive oil (brush or spray, not pour)\n"
        "• Baked, parchment-baked, broiled, seared or poached fish + a vegetable and a grain\n"
        "• Lean meatballs / mini-loaves (turkey, chicken, lentil) with a vegetable side\n"
        "• One-skillet dinners (protein + vegetables + a whole grain or legume in one pan)\n"
        "• Simmered tomato- or broth-based braises — no wine, no cream\n"
        "• Stuffed vegetables (peppers, sweet potatoes, eggplant)\n"
        "• Traybakes (everything roasted together on one tray)\n"
        "• Whole-grain pasta or grain bowls with a vegetable-forward sauce\n"
        "Pick a format DIFFERENT from the recipes that already exist."
    ),
    "dessert": (
        "DESSERT FORMATS — VARIETY REQUIRED:\n"
        "Don't repeat the format that already dominates the existing recipes (e.g. another chocolate "
        "baked dish, another fruit crumble).\n"
        "A plan the reader resents is a plan they abandon — these are real desserts that fit inside "
        "the day's added-sugar budget (≤ ~7 g added sugar per serving). Sweetness comes mostly from "
        "WHOLE FRUIT, spice, vanilla and cocoa. NO coconut oil or coconut cream, no corn syrup, no "
        "agave, no alcohol. Under 30 minutes hands-on, and most should need no chilling at all:\n"
        "• Baked, roasted or broiled fruit (apples, pears, peaches, plums, apricots) with Greek yogurt\n"
        "• Berry compotes over Greek yogurt, skyr or part-skim ricotta\n"
        "• Chia and yogurt puddings\n"
        "• Ricotta or cottage-cheese whips with fruit and citrus zest\n"
        "• Frozen-fruit 'nice cream' and yogurt barks\n"
        "• Oat-and-nut crumbles and skillet crisps over fruit\n"
        "• Cocoa and nut-butter bites; dark-chocolate-and-nut clusters (≥70% cocoa)\n"
        "• Poached pears or warm spiced fruit\n"
        "• Small portion-controlled baked goods on whole-grain or oat flour\n"
        "Pick a format DIFFERENT from the recipes that already exist."
    ),
}


def build_user(
    main_ingredient: str | None,
    cuisine_hint: str | None,
    exclusions: list[str],
    meal_type: str = "dinner",
    chapter_brief: str = "",
) -> str:
    parts = [
        "Generate an original recipe idea with the following constraints:",
        f"- Meal type: {meal_type}",
    ]
    if main_ingredient:
        parts.append(f"- Main ingredient: {main_ingredient}")
    if cuisine_hint:
        parts.append(f"- Desired cuisine style: {cuisine_hint}")
    if exclusions:
        parts.append(f"- Ingredients to exclude (allergens or preferences): {', '.join(exclusions)}")
    if chapter_brief:
        parts.append(f"\n{chapter_brief}")
    if meal_type in MEAL_FORMAT_GUIDANCE:
        parts.append(f"\n{MEAL_FORMAT_GUIDANCE[meal_type]}")
    parts.append(
        "\nRespond in JSON per the provided schema. Generate NO quantities — ingredient names only."
    )
    return "\n".join(parts)
