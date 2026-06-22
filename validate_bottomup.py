"""
validate_bottomup.py  —  the HONEST held-out test.

Build QSR and Bakery PURELY bottom-up — published intensities, EPC floor bands,
GENERIC equipment priors — WITHOUT ever looking at the CSVs. Then compare the
blind prediction to the real metered data on three axes:

  1. magnitude  (May kWh)      — how close is the size estimate?
  2. shape      (corr + peak)  — does the rhythm match?
  3. tariff     (the decision) — does it pick the SAME product the meter would?

This removes the circularity in the "calibrated" sectors (whose intensity was
back-derived from the CSV and whose shape was tuned to it). Caveat: with only 2
sites and an analyst who has seen them, this is "quasi-blind" — but it uses
published intensities + generic priors, so it's the strongest validation
available, far better than fitting then checking on the same data.
"""

import numpy as np
import synth, pricing, governance, shapes

# ---------------------------------------------------------------------------
# BOTTOM-UP, BLIND presets — built from PUBLIC priors only (no CSV peeking):
#   intensity : published benchmark range (NOT back-derived from the meter)
#   floor     : EPC typical band
#   mix       : generic end-use priors
#   meal_bias : GENERIC (1,1) — we do NOT tell it the QSR is lunch-led
# ---------------------------------------------------------------------------
BOTTOM_UP = {
 "qsr": dict(label="QSR", intensity=375, floor=150, open=11, close=23,
    weekend_ratio=1.0, footfall=[[12.5, 3, 1.0], [19, 4, 1.0]],   # GENERIC: lunch == dinner
    mix={"refrigeration":0.30, "cooking":0.30, "hvac":0.25, "lighting":0.15},
    src="intensity = CIBSE/DEC restaurant ~350-400 (mid 375); floor = EPC band"),
 "bakery": dict(label="Bakery", intensity=400, floor=120, open=7, close=17,
    weekend_ratio=1.2, footfall=[[8, 3, 1.0]],                    # generic breakfast
    mix={"baking":0.45, "refrigeration":0.25, "hvac":0.15, "lighting":0.15},
    src="intensity = oven-heavy bakery estimate ~400; floor = EPC band"),
}


def inject():
    """Register the blind bottom-up archetypes in the engine."""
    for key, b in BOTTOM_UP.items():
        synth.SECTORS[f"{key}_bu"] = dict(
            family="Hospitality", label=b["label"] + " (bottom-up, blind)",
            intensity=b["intensity"], confidence="prior", floor=b["floor"],
            open=b["open"], close=b["close"], weekend_ratio=b["weekend_ratio"],
            footfall=b["footfall"], mix=b["mix"])
    synth.ARCHETYPES = synth._build_archetypes()


def may(curve):
    return curve[curve["ts"].dt.month == 5]


def test(key, path):
    b = BOTTOM_UP[key]
    bu = synth.synthesize_year(f"{key}_bu")
    bu_may = may(bu["curve"])
    real_may = may(governance.real_curve(path))

    # 1. magnitude (May kWh)
    bu_kwh, real_kwh = bu_may["kwh"].sum(), real_may["kwh"].sum()
    mag_err = 100 * (bu_kwh - real_kwh) / real_kwh

    # 2. shape
    bu_shape = bu["shape_weekday"]
    real_shape = governance.weekday_shape(real_may)
    corr = float(np.corrcoef(bu_shape, real_shape)[0, 1])

    # 3. tariff (the decision)
    bu_rank = pricing.compare_products(bu_may)
    real_rank = pricing.compare_products(real_may)
    bu_win, real_win = bu_rank.iloc[0]["label"], real_rank.iloc[0]["label"]
    margin = 100 * (real_rank.iloc[1]["total_gbp"] - real_rank.iloc[0]["total_gbp"]) \
        / real_rank.iloc[0]["total_gbp"]
    if bu_win == real_win:
        tariff = "✅ MATCH"
    elif margin < 3:
        tariff = f"≈ immaterial (true margin {margin:.1f}%)"
    else:
        tariff = f"❌ miss (margin {margin:.1f}%)"

    print(f"\n  {b['label']}   [built blind — {b['src']}]")
    print(f"    1. magnitude : blind {bu_kwh:>7,.0f} kWh  vs meter {real_kwh:>7,.0f} kWh  ({mag_err:+.1f}%)")
    print(f"    2. shape     : corr {corr:.2f}   peak blind {shapes.hh_label(int(bu_shape.argmax()))}"
          f" vs meter {shapes.hh_label(int(real_shape.argmax()))}")
    print(f"    3. tariff    : blind picks {bu_win} | meter {real_win}  ->  {tariff}")
    print(f"       blind {shapes.sparkline(bu_shape)}")
    print(f"       meter {shapes.sparkline(real_shape)}")


if __name__ == "__main__":
    inject()
    print("=" * 72)
    print("  BLIND BOTTOM-UP VALIDATION — CSVs never used to build the estimate")
    print("=" * 72)
    test("qsr", "data/qsr_may.csv")
    test("bakery", "data/bakery_may.csv")
    print("\n  Read: magnitude = size accuracy, shape = rhythm fidelity,")
    print("  tariff = the decision RYE actually acts on (the one that matters).")
