"""
pricing.py  —  PART 3 of the meterless procurement estimator.

Take a synthesised full-year half-hourly curve (Part 2) and price it under
several real product structures, then rank them. The punchline this module
exists to prove:

    The SAME annual kWh costs a DIFFERENT amount under different products,
    purely because of WHEN it is used (the load shape) -- and the cheapest
    product FLIPS between a night-heavy business and a peak-heavy one.

How a bill is built (every product shares this skeleton; only the commodity
rate structure differs):

    total = ( commodity + standing + DUoS + CCL ) x (1 + VAT)

  commodity  the energy cost -- flat, or 2-tier day/night, or 48-point ToU
  standing   p/day x days        (fixed, shape-independent)
  DUoS       network charge, time-banded red/amber/green -- this is WHY a
             4-7pm peak is expensive to serve (applied to every product, so
             it explains site cost-to-serve rather than flipping the winner)
  CCL        Climate Change Levy 0.775 p/kWh
  VAT        20%

All p/kWh figures are REPRESENTATIVE UK non-domestic 2026 values: the
mechanism is real, the exact pennies are illustrative (production wires in the
client's contract + live DUoS by DNO + day-ahead wholesale).
"""

from __future__ import annotations
import numpy as np
import pandas as pd
import synth

# ---- fixed adders -----------------------------------------------------------
CCL_P_KWH = 0.775
VAT = 0.20
STANDING_P_DAY = 95.0

# ---- DUoS network bands (representative LV, p/kWh) ---------------------------
# red >> amber > green is the real structure; red is the 16:00-19:00 weekday
# crunch when the whole country is plugging in.
DUOS = {"red": 8.0, "amber": 0.8, "green": 0.2}


def _duos_band(hour: int, is_weekend: bool) -> str:
    if is_weekend:
        return "green"
    if 16 <= hour < 19:
        return "red"
    if 7 <= hour < 23:
        return "amber"
    return "green"


# ---- a representative ToU / Agile commodity curve (p/kWh by hour) ------------
# Cheap overnight, a midday solar dip, an expensive 16:00-19:00 evening peak.
_TOU_HOURLY = np.array([
    15, 15, 15, 15, 15, 16,   # 00-05 overnight
    18, 22, 24,               # 06-08 morning ramp
    23, 21, 20,               # 09-11
    19, 20,                   # 12-13 solar dip
    22, 26,                   # 14-15
    34, 38, 36,               # 16-18 EVENING PEAK
    28, 24, 20, 18,           # 19-22 taper
    16,                       # 23
], dtype=float)
TOU_CURVE_HH = np.repeat(_TOU_HOURLY, 2)          # 24 hours -> 48 half-hours


# ---- product definitions ----------------------------------------------------
PRODUCTS = {
    "fixed":      dict(label="Fixed flat rate",   kind="flat",  unit_p=24.5),
    "day_night":  dict(label="Day / Night (E7)",  kind="dn",
                       day_p=27.0, night_p=15.0),   # night = 00:00-07:00
    "tou":        dict(label="Time-of-Use / Agile", kind="tou", curve=TOU_CURVE_HH),
}


# ----------------------------------------------------------------------------
def _augment(curve: pd.DataFrame) -> pd.DataFrame:
    """Add the time-of-day helper columns pricing needs (done once)."""
    c = curve.copy()
    c["hour"] = c["ts"].dt.hour
    c["hh"] = c["ts"].dt.hour * 2 + (c["ts"].dt.minute >= 30).astype(int)
    c["is_weekend"] = c["ts"].dt.dayofweek >= 5
    c["is_night"] = c["hour"] < 7                       # E7 night window
    c["duos_p"] = [DUOS[_duos_band(h, w)]
                   for h, w in zip(c["hour"], c["is_weekend"])]
    return c


def price_curve(curve: pd.DataFrame, product_key: str) -> dict:
    """Price one full-year curve under one product. Returns a £ breakdown."""
    c = curve if "duos_p" in curve.columns else _augment(curve)
    p = PRODUCTS[product_key]
    kwh = c["kwh"].to_numpy()
    total_kwh = kwh.sum()
    n_days = c["ts"].dt.normalize().nunique()

    # --- commodity (the only part that differs by product) ---
    if p["kind"] == "flat":
        commodity_p = total_kwh * p["unit_p"]
    elif p["kind"] == "dn":
        night = c["is_night"].to_numpy()
        commodity_p = (kwh[night].sum() * p["night_p"]
                       + kwh[~night].sum() * p["day_p"])
    else:  # tou: each half-hour priced by the curve
        commodity_p = float((kwh * p["curve"][c["hh"].to_numpy()]).sum())

    standing_p = n_days * STANDING_P_DAY
    duos_p = float((kwh * c["duos_p"].to_numpy()).sum())
    ccl_p = total_kwh * CCL_P_KWH

    subtotal_p = commodity_p + standing_p + duos_p + ccl_p
    vat_p = subtotal_p * VAT
    total_p = subtotal_p + vat_p

    return {
        "product": product_key, "label": p["label"],
        "total_gbp": total_p / 100,
        "commodity_gbp": commodity_p / 100,
        "standing_gbp": standing_p / 100,
        "duos_gbp": duos_p / 100,
        "ccl_gbp": ccl_p / 100,
        "vat_gbp": vat_p / 100,
        "blended_p_kwh": total_p / total_kwh,      # the size-neutral number
        "total_kwh": total_kwh,
    }


def compare_products(curve: pd.DataFrame) -> pd.DataFrame:
    """Price under every product, cheapest first."""
    c = _augment(curve)
    rows = [price_curve(c, k) for k in PRODUCTS]
    df = pd.DataFrame(rows).sort_values("total_gbp").reset_index(drop=True)
    return df


def _print_compare(name: str, curve: pd.DataFrame, redband_note: str = ""):
    df = compare_products(curve)
    win = df.iloc[0]
    print(f"\n  {name}")
    print(f"  {'product':<22}{'£/yr':>10}{'p/kWh':>9}{'  DUoS £':>10}")
    print(f"  {'-'*51}")
    for _, r in df.iterrows():
        mark = "  <-- cheapest" if r["product"] == win["product"] else ""
        print(f"  {r['label']:<22}{r['total_gbp']:>10,.0f}"
              f"{r['blended_p_kwh']:>9.2f}{r['duos_gbp']:>10,.0f}{mark}")
    if redband_note:
        print(f"  {redband_note}")
    return df


def tariff_flip_demo():
    """The headline: same engine, two shapes, the winner flips."""
    print("=" * 72)
    print("  TARIFF-FLIP DEMO  —  the load shape, not the unit rate, picks the winner")
    print("=" * 72)

    # (a) realistic: each site at its own estimated size
    qsr = synth.synthesize_year("qsr", floor_m2=150)["curve"]
    bak = synth.synthesize_year("bakery", floor_m2=120)["curve"]
    q = _print_compare("QSR  (150 m2, peak 12:30, 6% night, 21% red-band)", qsr)
    b = _print_compare("Bakery (120 m2, peak 05:00, 40% night, 6% red-band)", bak)

    print(f"\n  ---> QSR's cheapest    : {q.iloc[0]['label']}")
    print(f"  ---> Bakery's cheapest : {b.iloc[0]['label']}")

    # (b) controlled: SAME annual kWh for both, so ONLY the shape differs
    print("\n" + "-" * 72)
    print("  CONTROLLED: both forced to 50,000 kWh/yr — only the SHAPE differs")
    print("-" * 72)
    qsr2 = synth.synthesize_year("qsr", annual_kwh=50000)["curve"]
    bak2 = synth.synthesize_year("bakery", annual_kwh=50000)["curve"]
    qc = compare_products(qsr2).set_index("label")["blended_p_kwh"]
    bc = compare_products(bak2).set_index("label")["blended_p_kwh"]
    print(f"  {'product':<22}{'QSR p/kWh':>12}{'Bakery p/kWh':>15}")
    print(f"  {'-'*49}")
    for label in PRODUCTS_ORDER:
        print(f"  {label:<22}{qc[label]:>12.2f}{bc[label]:>15.2f}")
    print(f"\n  Same 50,000 kWh. QSR is cheapest on '{qc.idxmin()}'; "
          f"Bakery is cheapest on '{bc.idxmin()}'.")
    print(f"  Day/Night costs the QSR {qc['Day / Night (E7)']:.1f}p but the "
          f"Bakery only {bc['Day / Night (E7)']:.1f}p — that gap is pure load shape.")


PRODUCTS_ORDER = [PRODUCTS[k]["label"] for k in PRODUCTS]


if __name__ == "__main__":
    tariff_flip_demo()
