import streamlit as st
import os
import json
import re
from typing import Any, Dict

# =========================
# Config
# =========================
st.set_page_config(page_title="Ice Cream App", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

RECIPES_PATH    = os.path.join(BASE_DIR, "recipes.json")
LINEUP_FILE     = os.path.join(BASE_DIR, "weekly_lineup.json")
INVENTORY_FILE  = os.path.join(BASE_DIR, "inventory.json")  # flavor inventory
INGREDIENT_FILE = os.path.join(BASE_DIR, "ingredient_inventory.json")
THRESHOLD_FILE  = os.path.join(BASE_DIR, "ingredient_thresholds.json")
EXCLUDE_FILE    = os.path.join(BASE_DIR, "excluded_ingredients.json")

UNIT_OPTIONS = ["cans", "50lbs bags", "grams", "liters", "gallons"]
UNIT_FACTORS = {"g": 1.0, "kg": 1000.0, "lb": 453.59237, "oz": 28.349523125}


# =========================
# Helpers (IO + keys)
# =========================
def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except FileNotFoundError:
        return 0.0

@st.cache_data(ttl=60)
def _load_json_cached(path: str, mtime: float) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_json(path: str, default: Any):
    if not os.path.exists(path):
        return default
    try:
        return _load_json_cached(path, _mtime(path))
    except json.JSONDecodeError as e:
        st.error(f"❌ Invalid JSON: {os.path.basename(path)}")
        st.caption(f"Error: {e.msg} at line {e.lineno}, column {e.colno}")
        st.stop()

def save_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "x").lower()).strip("_")

def ns_key(ns: str, name: str) -> str:
    return f"{ns}__{name}"

def to_grams(amount: float, unit: str) -> float:
    return float(amount) * UNIT_FACTORS.get((unit or "g").lower(), 1.0)


# =========================
# Recipe schema normalizer
# =========================
def normalize_recipes_schema(recipes: dict) -> dict:
    if not isinstance(recipes, dict):
        return {}
    for name, r in list(recipes.items()):
        if not isinstance(r, dict):
            continue
        r.setdefault("ingredients", {})
        instr = r.get("instruction", [])
        if instr is None:
            instr = []
        elif isinstance(instr, str):
            instr = [instr]
        r["instruction"] = instr
        r.setdefault("subrecipes", {})
        if not isinstance(r["subrecipes"], dict):
            r["subrecipes"] = {}

        for sname, s in r["subrecipes"].items():
            if not isinstance(s, dict):
                continue
            s.setdefault("ingredients", {})
            sinstr = s.get("instruction", [])
            if sinstr is None:
                sinstr = []
            elif isinstance(sinstr, str):
                sinstr = [sinstr]
            s["instruction"] = sinstr
    return recipes


# =========================
# Threshold/inventory schema normalizers
# =========================
def get_all_ingredients_from_recipes(recipes: Dict[str, Any]) -> list[str]:
    names = set()
    for r in (recipes or {}).values():
        if not isinstance(r, dict):
            continue
        for ing in (r.get("ingredients") or {}).keys():
            names.add(str(ing).strip())
        for s in (r.get("subrecipes") or {}).values():
            if not isinstance(s, dict):
                continue
            for ing in (s.get("ingredients") or {}).keys():
                names.add(str(ing).strip())
    return sorted(names)

def normalize_thresholds_schema(thresholds: Dict[str, Any]) -> Dict[str, Any]:
    upgraded: Dict[str, Any] = {}
    for ing, val in (thresholds or {}).items():
        if isinstance(val, dict):
            min_val = float(val.get("min", 0) or 0)
            unit = val.get("unit", "grams")
            if unit not in UNIT_OPTIONS:
                unit = "grams"
            upgraded[ing] = {"min": min_val, "unit": unit}
        else:
            upgraded[ing] = {"min": float(val) if val is not None else 0.0, "unit": "grams"}
    return upgraded

def normalize_inventory_schema(raw: dict) -> tuple[dict, bool]:
    inv, changed = {}, False
    for k, v in (raw or {}).items():
        if isinstance(v, dict):
            amt = float(v.get("amount", 0) or 0)
            unit = (v.get("unit") or "g").lower()
        else:
            amt = float(v or 0)
            unit = "g"
            changed = True
        inv[str(k)] = {"amount": amt, "unit": unit}
    return inv, changed


# =========================
# Render helpers
# =========================
def render_ingredients_block(ingredients: dict):
    if not ingredients:
        return
    st.markdown("### 📋 Ingredients")
    G_PER_GALLON_MILK = 3785
    for k, v in ingredients.items():
        try:
            grams_int = int(round(float(v)))
        except Exception:
            st.write(f"- {k}: {v}")
            continue

        line = f"- {k}: {grams_int} g"
        if str(k).lower() == "milk":
            whole_gal = grams_int // G_PER_GALLON_MILK
            rem_g = grams_int - whole_gal * G_PER_GALLON_MILK
            line += f" ({whole_gal} gal + {rem_g} g)"
        st.write(line)

def render_instructions(title: str, steps: list[str]):
    if not steps:
        return
    with st.expander(title, expanded=True):
        for line in steps:
            st.markdown(f"- {line}")

def render_subrecipes(subrecipes: dict):
    if not subrecipes:
        return
    st.markdown("### 🧩 Sub-recipes")
    for sname, srec in subrecipes.items():
        with st.expander(f"Subrecipe: {sname}", expanded=False):
            ings = (srec or {}).get("ingredients", {}) or {}
            if ings:
                st.markdown("**Ingredients**")
                for k, v in ings.items():
                    try:
                        st.write(f"- {k}: {int(round(float(v)))}")
                    except Exception:
                        st.write(f"- {k}: {v}")
            render_instructions("Instructions", (srec or {}).get("instruction", []) or [])

def show_scaled_result(selected_name: str, scaled_ingredients: dict, recipes_dict: dict):
    base = recipes_dict.get(selected_name, {}) or {}
    rec = {
        "ingredients": scaled_ingredients or {},
        "instruction": base.get("instruction", []) or [],
        "subrecipes": base.get("subrecipes", {}) or {},
    }
    render_ingredients_block(rec.get("ingredients", {}))
    render_instructions("🛠️ Instructions", rec.get("instruction", []))
    render_subrecipes(rec.get("subrecipes", {}))


# =========================
# Load recipes (single source of truth)
# =========================
if not os.path.exists(RECIPES_PATH):
    st.error(f"Missing recipes file: {RECIPES_PATH}")
    st.info("Fix: add recipes.json to the repo (same folder as app.py).")
    st.stop()

recipes: Dict[str, Any] = load_json(RECIPES_PATH, default={})
recipes = normalize_recipes_schema(recipes)

recipe_names = sorted(recipes.keys())
if not recipe_names:
    st.error("No recipes found in recipes.json.")
    st.stop()


# =========================
# Pages
# =========================
def page_batching():
    ns = "batch"

    # Stable recipe selector (ONE selectbox only)
    current = st.session_state.get("selected_recipe")
    if current not in recipe_names:
        current = recipe_names[0]
        st.session_state["selected_recipe"] = current

    selected_name = st.selectbox(
        "Choose a recipe",
        recipe_names,
        index=recipe_names.index(current),
        key="selected_recipe",
    )

    rec = recipes.get(selected_name, {}) or {}
    base_ings = rec.get("ingredients", {}) or {}
    original_weight = float(sum([float(x) for x in base_ings.values()]) or 0.0)

    st.divider()
    st.subheader("Scale")

    # Namespace scaling keys by recipe so you never collide
    scale_ns = f"scale__{slugify(selected_name)}"
    def k(name: str) -> str:
        return ns_key(scale_ns, name)

    scale_mode = st.radio(
        "Method",
        [
            "Target batch weight (g)",
            "Container: 5 L",
            "Container: 1.5 gal",
            "Containers: combo (5 L + 1.5 gal)",
            "Scale by ingredient weight",
            "Multiplier x",
        ],
        horizontal=True,
        key=k("mode"),
    )

    density_g_per_ml = None
    if scale_mode in {"Container: 5 L", "Container: 1.5 gal", "Containers: combo (5 L + 1.5 gal)"}:
        density_g_per_ml = st.number_input(
            "Mix density (g/mL)",
            min_value=0.5, max_value=1.5, value=1.03, step=0.01,
            key=k("density"),
        )

    GAL_TO_L     = 3.785411784
    VOL_5L_L     = 5.0
    VOL_1_5GAL_L = 1.5 * GAL_TO_L

    info_lines: list[str] = []
    scale_factor = 1.0
    target_weight = None

    if not base_ings:
        st.warning("This recipe has no ingredients.")
        scale_factor = 1.0

    elif scale_mode == "Target batch weight (g)":
        target_weight = st.number_input(
            "Target weight (g)",
            min_value=1.0,
            value=float(original_weight or 1000.0),
            step=100.0,
            key=k("target_weight"),
        )
        scale_factor = (target_weight / original_weight) if original_weight else 1.0
        info_lines.append(f"Target weight: {target_weight:,.0f} g")

    elif scale_mode == "Container: 5 L":
        n_5l = st.number_input("How many 5 L pans?", min_value=1, value=1, step=1, key=k("n5l"))
        total_l = n_5l * VOL_5L_L
        density_g_per_ml = density_g_per_ml or 1.03
        target_weight = total_l * 1000.0 * density_g_per_ml
        scale_factor = (target_weight / original_weight) if original_weight else 1.0
        info_lines += [f"Total volume: {total_l:,.2f} L", f"Target weight: {target_weight:,.0f} g"]

    elif scale_mode == "Container: 1.5 gal":
        n_15 = st.number_input("How many 1.5 gal tubs?", min_value=1, value=1, step=1, key=k("n15"))
        total_l = n_15 * VOL_1_5GAL_L
        density_g_per_ml = density_g_per_ml or 1.03
        target_weight = total_l * 1000.0 * density_g_per_ml
        scale_factor = (target_weight / original_weight) if original_weight else 1.0
        info_lines += [f"Total volume: {total_l:,.2f} L", f"Target weight: {target_weight:,.0f} g"]

    elif scale_mode == "Containers: combo (5 L + 1.5 gal)":
        c1, c2 = st.columns(2)
        with c1:
            n_5l = st.number_input("5 L pans", min_value=0, value=1, step=1, key=k("n5l_combo"))
        with c2:
            n_15 = st.number_input("1.5 gal tubs", min_value=0, value=0, step=1, key=k("n15_combo"))
        total_l = n_5l * VOL_5L_L + n_15 * VOL_1_5GAL_L
        if total_l <= 0:
            st.warning("Set at least one container.")
            total_l = 0.0
        density_g_per_ml = density_g_per_ml or 1.03
        target_weight = total_l * 1000.0 * density_g_per_ml
        scale_factor = (target_weight / original_weight) if original_weight else 1.0
        info_lines += [
            f"5 L pans: {n_5l}  |  1.5 gal tubs: {n_15}",
            f"Total volume: {total_l:,.2f} L",
            f"Target weight: {target_weight:,.0f} g",
        ]

    elif scale_mode == "Scale by ingredient weight":
        ing_names = list(base_ings.keys())
        anchor_ing = st.selectbox("Anchor ingredient", ing_names, key=k("anchor_ing"))
        available_g = st.number_input(
            f"Available {anchor_ing} (g)",
            min_value=0.0,
            value=float(base_ings.get(anchor_ing, 0.0)),
            step=10.0,
            key=k("available_anchor"),
        )
        base_req = float(base_ings.get(anchor_ing, 0.0))
        scale_factor = (available_g / base_req) if base_req > 0 else 1.0
        info_lines.append(f"Scale factor from {anchor_ing}: ×{scale_factor:.3f}")

    else:  # Multiplier x
        scale_factor = st.number_input(
            "Multiplier",
            min_value=0.01,
            value=1.0,
            step=0.1,
            key=k("multiplier"),
        )
        info_lines.append(f"Scale factor: ×{scale_factor:.3f}")

    scaled = {ing: round(float(qty) * scale_factor, 2) for ing, qty in base_ings.items()}
    total_scaled = round(sum(scaled.values()), 2)

    st.metric("Total batch weight (g)", f"{total_scaled:,.2f}")
    if density_g_per_ml and total_scaled > 0:
        est_l = total_scaled / (density_g_per_ml * 1000.0)
        st.caption(f"Estimated volume: {est_l:,.2f} L @ {density_g_per_ml:.2f} g/mL")
    for line in info_lines:
        st.caption(line)

    st.divider()
    show_scaled_result(selected_name, scaled, recipes)

    st.divider()
    st.subheader("Execute batch (step-by-step)")

    step_ns = f"steps__{slugify(selected_name)}"
    step_key  = ns_key(step_ns, "step")
    order_key = ns_key(step_ns, "order")

    if step_key not in st.session_state:
        st.session_state[step_key] = None
    if order_key not in st.session_state or not isinstance(st.session_state[order_key], list):
        st.session_state[order_key] = list(scaled.keys())

    start_clicked = st.button("▶️ Start batch", key=ns_key(step_ns, "start"))
    if start_clicked:
        st.session_state[step_key] = 0
        st.session_state[order_key] = list(scaled.keys())

    step = st.session_state[step_key]
    order = st.session_state[order_key]

    if step is not None:
        if step < len(order):
            ing = order[step]
            grams = float(scaled.get(ing, 0))
            st.info(f"**{ing} {grams:.0f} grams**")

            c1, c2, c3 = st.columns(3)
            with c1:
                st.button(
                    "⬅️ Back",
                    key=ns_key(step_ns, "back"),
                    disabled=(step == 0),
                    on_click=lambda: st.session_state.update({step_key: max(0, step - 1)}),
                )
            with c2:
                st.button(
                    "⏹ Reset",
                    key=ns_key(step_ns, "reset"),
                    on_click=lambda: st.session_state.update({step_key: None}),
                )
            with c3:
                st.button(
                    "Next ➡️",
                    key=ns_key(step_ns, "next"),
                    on_click=lambda: st.session_state.update({step_key: step + 1}),
                )
        else:
            st.success("✅ Batch complete")
            st.button(
                "Start over",
                key=ns_key(step_ns, "restart"),
                on_click=lambda: st.session_state.update({step_key: 0}),
            )


def page_ingredient_inventory():
    ns = "inv"

    all_ingredients = get_all_ingredients_from_recipes(recipes)
    excluded = load_json(EXCLUDE_FILE, [])
    excluded = [e for e in excluded if e in all_ingredients]

    st.subheader("Ingredient Inventory")

    exclude_list = st.multiselect(
        "Exclude ingredients",
        all_ingredients,
        default=excluded,
        key=ns_key(ns, "exclude"),
    )
    if st.button("Save exclusion list", key=ns_key(ns, "save_exclude")):
        save_json(EXCLUDE_FILE, exclude_list)
        st.success("Saved.")

    raw_inv = load_json(INGREDIENT_FILE, {})
    inv, changed = normalize_inventory_schema(raw_inv)

    # Ensure all ingredients exist
    for ing in all_ingredients:
        inv.setdefault(ing, {"amount": 0.0, "unit": "g"})

    if changed:
        save_json(INGREDIENT_FILE, inv)

    q = st.text_input("Filter ingredients", "", key=ns_key(ns, "filter")).strip().lower()

    unit_options = ["g", "kg", "lb", "oz"]
    items = [i for i in all_ingredients if i not in exclude_list and q in i.lower()]

    cols = st.columns(3)
    updated: Dict[str, Any] = {}

    for i, ing in enumerate(items):
        with cols[i % 3]:
            amt = st.number_input(
                ing,
                min_value=0.0,
                value=float(inv.get(ing, {}).get("amount", 0.0)),
                step=1.0,
                key=ns_key(ns, f"amt__{slugify(ing)}"),
            )
            unit0 = (inv.get(ing, {}).get("unit") or "g").lower()
            idx = unit_options.index(unit0) if unit0 in unit_options else 0
            unit = st.selectbox(
                "Unit",
                unit_options,
                index=idx,
                key=ns_key(ns, f"unit__{slugify(ing)}"),
            )
            updated[ing] = {"amount": amt, "unit": unit}

    if st.button("💾 Save ingredient inventory", key=ns_key(ns, "save")):
        inv.update(updated)
        save_json(INGREDIENT_FILE, inv)
        st.success("Ingredient inventory saved.")

    # Summary table
    summary = {
        ing: f"{inv[ing]['amount']:.2f} {inv[ing]['unit']}  ({to_grams(inv[ing]['amount'], inv[ing]['unit']):,.0f} g)"
        for ing in items
    }
    st.dataframe(summary, use_container_width=True)


def page_set_min_inventory():
    ns = "min"

    st.subheader("Set Minimum Inventory Levels")
    all_ings = get_all_ingredients_from_recipes(recipes)
    if not all_ings:
        st.info("No ingredients found in recipes.")
        return

    thresholds_raw = load_json(THRESHOLD_FILE, {})
    thresholds = normalize_thresholds_schema(thresholds_raw)

    edited: Dict[str, Any] = {}

    header = st.columns([3, 2, 2])
    header[0].markdown("**Ingredient**")
    header[1].markdown("**Min Level**")
    header[2].markdown("**Unit**")

    for ing in all_ings:
        cur = thresholds.get(ing, {"min": 0.0, "unit": "grams"})
        c1, c2, c3 = st.columns([3, 2, 2])
        c1.write(ing)
        new_min = c2.number_input(
            "min",
            value=float(cur.get("min", 0.0)),
            min_value=0.0,
            step=1.0,
            format="%.2f",
            label_visibility="collapsed",
            key=ns_key(ns, f"min__{slugify(ing)}"),
        )
        cur_unit = cur.get("unit", "grams")
        unit_idx = UNIT_OPTIONS.index(cur_unit) if cur_unit in UNIT_OPTIONS else UNIT_OPTIONS.index("grams")
        new_unit = c3.selectbox(
            "unit",
            options=UNIT_OPTIONS,
            index=unit_idx,
            label_visibility="collapsed",
            key=ns_key(ns, f"unit__{slugify(ing)}"),
        )
        edited[ing] = {"min": new_min, "unit": new_unit}

    if st.button("💾 Save Minimums & Units", type="primary", key=ns_key(ns, "save")):
        save_json(THRESHOLD_FILE, edited)
        st.success("Minimum inventory levels and units saved.")


# =========================
# Sidebar navigation (ONE radio only)
# =========================
page = st.sidebar.radio(
    "Go to",
    ["Batching System", "Ingredient Inventory", "Set Min Inventory"],
    key="sidebar_nav",
)

if page == "Batching System":
    page_batching()
elif page == "Ingredient Inventory":
    page_ingredient_inventory()
elif page == "Set Min Inventory":
    page_set_min_inventory()
