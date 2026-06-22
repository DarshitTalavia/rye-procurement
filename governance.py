"""
governance.py  —  the trust layer, on the UNIFIED engine.

Two evals + guardrails:

  1. FIDELITY  — the engine COMPOSES each food sector's shape from its equipment
     mix + hours. Does that composed shape match the REAL metered shape?
     (correlation + peak timing).

  2. DECISION VALIDATION — the test that matters: does pricing the engine's
     (composed) curve pick the SAME cheapest tariff as pricing the REAL metered
     curve? With a materiality check, since a "miss" inside the error band is a
     coin-flip the guardrail already flags.

  Guardrails: too-close-to-call recommendation + plausibility bounds.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
import shapes, synth, pricing

HH = 48


def real_curve(path: str) -> pd.DataFrame:
    df = shapes.load_halfhourly(path)
    return pd.DataFrame({"ts": df["ts"].to_numpy(),
                         "kwh": df["kw"].to_numpy() * shapes.HOURS_PER_HH})

def may(curve):  # keep both horizons comparable (real data is May)
    return curve[curve["ts"].dt.month == 5].copy()

def weekday_shape(curve):
    c = curve[curve["ts"].dt.dayofweek < 5].copy()
    c["hh"] = c["ts"].dt.hour * 2 + (c["ts"].dt.minute >= 30).astype(int)
    p = c.groupby("hh")["kwh"].mean().reindex(range(HH)).to_numpy()
    return p / np.nansum(p)


# ---- EVAL 1: fidelity (composed vs metered) --------------------------------
def fidelity(sector, path):
    comp = synth.ARCHETYPES[sector]["shape_weekday"]
    real = np.array(synth.DATASET["metered_shapes"][sector]["weekday"])
    corr = float(np.corrcoef(comp, real)[0, 1])
    print(f"    {sector:<7} corr {corr:.2f}   peak composed "
          f"{shapes.hh_label(int(comp.argmax()))} vs real {shapes.hh_label(int(real.argmax()))}")
    return corr


# ---- EVAL 2: decision validation (right tariff, blind) ---------------------
def decision_validation(sector, path, tol_pct=3.0):
    real = may(real_curve(path))                                    # ground truth
    eng = may(synth.synthesize_year(sector)["curve"])              # engine composed

    real_rank = pricing.compare_products(real)
    eng_rank = pricing.compare_products(eng)
    real_win, eng_win = real_rank.iloc[0]["label"], eng_rank.iloc[0]["label"]
    margin = 100 * (real_rank.iloc[1]["total_gbp"] - real_rank.iloc[0]["total_gbp"]) \
        / real_rank.iloc[0]["total_gbp"]

    if real_win == eng_win:
        outcome, verdict = "correct", "✅ right tariff, blind"
    elif margin < tol_pct:
        outcome, verdict = "immaterial", f"≈ immaterial (true margin {margin:.1f}%, too-close)"
    else:
        outcome, verdict = "material", f"❌ material miss (margin {margin:.1f}%)"
    print(f"    {sector:<7} truth={real_win} | engine={eng_win} | {verdict}")
    return outcome


# ---- GUARDRAILS ------------------------------------------------------------
def recommend(curve, tol_pct=3.0):
    rank = pricing.compare_products(curve)
    best, second = rank.iloc[0], rank.iloc[1]
    margin = 100 * (second["total_gbp"] - best["total_gbp"]) / best["total_gbp"]
    return {"winner": best["label"], "runner_up": second["label"], "margin_pct": margin,
            "verdict": "clear" if margin >= tol_pct else "too close to call",
            "saving_gbp": rank.iloc[-1]["total_gbp"] - best["total_gbp"]}

def plausibility(intensity, annual_kwh, load_factor):
    w = []
    if not 50 <= intensity <= 1500: w.append(f"intensity {intensity:.0f} out of 50-1500")
    if not 1_000 <= annual_kwh <= 5_000_000: w.append(f"annual {annual_kwh:,.0f} implausible")
    if not 0.10 <= load_factor <= 0.90: w.append(f"load factor {load_factor:.2f} out of 0.10-0.90")
    return w


def run_all():
    print("=" * 70)
    print("  EVAL 1 — FIDELITY (engine-composed shape vs real metered shape)")
    print("=" * 70)
    fidelity("qsr", "data/qsr_may.csv")
    fidelity("bakery", "data/bakery_may.csv")

    print("\n" + "=" * 70)
    print("  EVAL 2 — DECISION VALIDATION (engine picks the right tariff vs meter)")
    print("=" * 70)
    outs = [decision_validation("qsr", "data/qsr_may.csv"),
            decision_validation("bakery", "data/bakery_may.csv")]
    material = outs.count("material")
    print(f"\n  Material decision accuracy: {2 - material}/2 "
          f"({outs.count('correct')} exact, {outs.count('immaterial')} immaterial, {material} material miss)")

    print("\n" + "=" * 70 + "\n  GUARDRAILS\n" + "=" * 70)
    for sec in ["qsr", "bakery", "restaurant", "convenience"]:
        rec = recommend(synth.synthesize_year(sec)["curve"])
        print(f"    {synth.SECTORS[sec]['label']:<26} {rec['winner']:<20} "
              f"{rec['margin_pct']:>4.1f}%  {rec['verdict']}  (saves £{rec['saving_gbp']:,.0f})")
    print("  plausibility: 150 m² QSR ->",
          plausibility(391, 58650, 0.49) or "clean ✅",
          "| bad ->", plausibility(391, 58650, 0.97))


if __name__ == "__main__":
    run_all()
