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
FIXED = "Fixed flat rate"

def recommend(curve, shape, tol_pct=3.0, risk_tol_pct=4.0):
    """COST x RISK recommendation. Cost picks the cheapest; load factor (peakiness)
    breaks thin ties on a defensible RISK basis. The justification always cites the
    shape metrics (load factor, red-band, night) — never the headline rate.

      - spiky (LF<0.35) AND Fixed is within risk_tol of the cost-winner -> Fixed
        (cap peak-price exposure for a margin we don't trust),
      - flat (LF>0.5) AND a time-varying product wins on cost -> keep it (low risk),
      - otherwise the cost-winner; 'too close to call' only when LF is moderate
        AND the cost margin is within tol (neither cost nor risk gives a signal)."""
    rank = pricing.compare_products(curve)
    best, second = rank.iloc[0], rank.iloc[1]
    cost_margin = 100 * (second["total_gbp"] - best["total_gbp"]) / best["total_gbp"]
    saving = rank.iloc[-1]["total_gbp"] - best["total_gbp"]
    m = synth.shape_metrics_of(shape)
    lf, night, red = m["load_factor"], m["night_pct"], m["redband_pct"]
    fixed = rank[rank["label"] == FIXED].iloc[0]
    fixed_premium = 100 * (fixed["total_gbp"] - best["total_gbp"]) / best["total_gbp"]

    cost_winner = best["label"]
    winner = cost_winner
    verdict = "clear" if cost_margin >= tol_pct else "too close to call"

    if lf < 0.35 and cost_winner != FIXED and fixed_premium <= risk_tol_pct:
        winner, verdict = FIXED, "risk-adjusted"
        why = (f"Spiky load (load factor {lf}, red-band {red}%): Fixed caps peak-price "
               f"exposure for only a {fixed_premium:.1f}% premium over the cost-cheapest "
               f"— too thin a margin to trust at this confidence.")
    elif lf > 0.5 and cost_winner != FIXED:
        verdict = "clear"
        why = (f"Flat, predictable load (load factor {lf}, night {night}%, red-band {red}%): "
               f"low volatility risk, so the time-varying product's saving is worth taking.")
    else:
        if 0.35 <= lf <= 0.5 and cost_margin < tol_pct:
            verdict = "too close to call"
        tail = ("margin within noise — confirm with metered data."
                if verdict == "too close to call" else f"clear {cost_margin:.1f}% ahead on cost.")
        why = f"Cheapest on cost (load factor {lf}, night {night}%, red-band {red}%); {tail}"

    return {"winner": winner, "cost_winner": cost_winner, "runner_up": second["label"],
            "margin_pct": cost_margin, "fixed_premium_pct": fixed_premium,
            "verdict": verdict, "rationale": why, "saving_gbp": saving,
            "load_factor": lf, "night_pct": night, "redband_pct": red}

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

    print("\n" + "=" * 70 + "\n  GUARDRAILS — cost x risk recommendation\n" + "=" * 70)
    for sec in ["qsr", "bakery", "restaurant", "pub", "convenience"]:
        r = synth.synthesize_year(sec)
        rec = recommend(r["curve"], r["shape_weekday"])
        flag = f" (cost-winner: {rec['cost_winner']})" if rec["winner"] != rec["cost_winner"] else ""
        print(f"    {synth.SECTORS[sec]['label']:<26} LF {rec['load_factor']:.2f} -> "
              f"{rec['winner']:<20} [{rec['verdict']}]{flag}")
    print("  plausibility: 150 m² QSR ->",
          plausibility(391, 58650, 0.49) or "clean ✅",
          "| bad ->", plausibility(391, 58650, 0.97))


if __name__ == "__main__":
    run_all()
