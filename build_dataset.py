"""
build_dataset.py  —  bake data/dataset.json. Run once (build-time).

After unifying the engine + Option A, the dataset's job is narrow and honest:

  LIVE (read by the engine):
    metered_shapes     real metered rhythms — VALIDATION ground truth only
    end_use_library    equipment + real published kW — for the agent's menu path
    menu_to_equipment  menu category -> equipment   — for the agent's menu path

  REFERENCE (provenance for the writeup; NOT read by the engine — the sector
  presets + benchmarks live in synth.py, and the CSVs are validation only):
    elexon_profile_classes, epc_floor_bands

This file is the ONLY place the CSVs are read at build-time. The production
estimate path (synth -> pricing -> governance.recommend) never touches them.
"""

import json
import shapes


# ---- LIVE: metered shapes (validation ground truth) ------------------------
def metered_block(path):
    df = shapes.load_halfhourly(path)
    return {
        "weekday": [round(float(x), 5) for x in shapes.normalise(shapes.average_profile(df, "weekday"))],
        "weekend": [round(float(x), 5) for x in shapes.normalise(shapes.average_profile(df, "weekend"))],
        "metrics": shapes.shape_metrics(df),
        "provenance": "REAL metered half-hourly data — used for VALIDATION only",
    }


# ---- LIVE: equipment library (real published kW) ---------------------------
# Used by synth.shape_from_menu (the agent's menu path). kW are real; sources cited.
END_USE_LIBRARY = {
 "refrigeration": dict(kw=0.8, note="largest kitchen load ~41%, runs 24/7", src="Oxford IJLCT / Power Knot"),
 "fryer":        dict(kw=3.2, note="meal-prep spikes", src="ENERGY STAR / CooksDirect (3.2-4.5 kW)"),
 "grill":        dict(kw=6.4, note="meal-prep spikes", src="ENERGY STAR (6.4-8 kW griddle)"),
 "combi_oven":   dict(kw=2.2, note="meal prep", src="ENERGY STAR (2.2-3.5 kW)"),
 "deck_oven":    dict(kw=18.0, note="pre-dawn baking", src="Bakeit/UNOX (15-20 kW small bakery)"),
 "proofer":      dict(kw=2.0, note="proving before bake", src="British Baker"),
 "hvac":         dict(kw=5.0, note="tracks occupancy, 30-40% of restaurant energy", src="Oxford IJLCT"),
 "lighting":     dict(kw=1.5, note="open hours + darkness", src="general"),
 "it":           dict(kw=0.5, note="standby + daytime", src="general"),
}

# ---- LIVE: menu category -> equipment (the novel menu->equipment source) ----
MENU_TO_EQUIPMENT = {
 "fried_food":     ["fryer", "refrigeration"],
 "grilled_food":   ["grill", "refrigeration"],
 "baked_savoury":  ["combi_oven", "refrigeration"],
 "bread_pastry":   ["deck_oven", "proofer", "refrigeration"],
 "chilled_display":["refrigeration"],
}

# ---- REFERENCE: provenance only (not read by the engine) -------------------
REFERENCE = {
 "elexon_profile_classes": {
    "PC3": "Non-domestic single rate", "PC4": "Non-domestic Economy-7",
    "PC5-8": "Non-domestic Maximum Demand (by load factor)",
    "src": "Elexon BSC — Load Profiles & their use in Electricity Settlement",
    "insight": "generic PC3 is anti-correlated with a real bakery (~-0.06); our "
               "equipment method differentiates sectors PC3 cannot."},
 "epc_floor_bands": {
    "small_commercial_m2": "<=150", "medium_m2": "<=500 (public-display threshold)",
    "src": "EPC / gov.uk size bands; per-site lookup via EPC register in production",
    "note": "~90% of commercial premises are EPC Level 3"},
 "note": "Reference only. Sector presets + intensities live in synth.py (published "
         "benchmarks). The CSVs are validation, never engine inputs.",
}


def main():
    dataset = {
        "_about": "RYE meterless-procurement baked data. LIVE = metered_shapes "
                  "(validation), end_use_library + menu_to_equipment (agent menu "
                  "path). REFERENCE = provenance only.",
        "metered_shapes": {"qsr": metered_block("data/qsr_may.csv"),
                           "bakery": metered_block("data/bakery_may.csv")},
        "end_use_library": END_USE_LIBRARY,
        "menu_to_equipment": MENU_TO_EQUIPMENT,
        "reference": REFERENCE,
    }
    with open("data/dataset.json", "w") as f:
        json.dump(dataset, f, indent=1)

    print("=" * 64)
    print("  dataset.json rebuilt (lean).")
    print("=" * 64)
    print("  LIVE      : metered_shapes", list(dataset["metered_shapes"]),
          "| end_use_library", len(END_USE_LIBRARY), "| menu_to_equipment", len(MENU_TO_EQUIPMENT))
    print("  REFERENCE : elexon_profile_classes, epc_floor_bands (not engine inputs)")
    print("  Note: composition-vs-metered checks live in governance.py / "
          "validate_bottomup.py (which import synth).")


if __name__ == "__main__":
    main()
