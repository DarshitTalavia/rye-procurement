"""
synth.py  —  THE UNIFIED DETERMINISTIC ENGINE.

One source of truth for SIZE x SEASON x SHAPE, shared by the website
(build_site.py), the agent (agent.py), the pricer (pricing.py) and the evals
(governance.py). Nothing else defines sectors or composes shapes.

  SHAPE  : composed from a sector's equipment mix, placed against opening hours
           (hours genuinely reshape the curve). Validated vs the metered data.
  SIZE   : floor area (default per sector) x intensity (kWh/m2/yr); or override.
  SEASON : representative monthly weights.

Scope = RYE's market: hospitality + retail. No offices.
"""

from __future__ import annotations
import json, os
from collections import Counter
import numpy as np
import pandas as pd
import shapes

HH = 48
_HERE = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------------
# SEASON — representative monthly weights (mean = 1.0).
# ----------------------------------------------------------------------------
_SEASON_RAW = np.array([1.10, 1.06, 1.03, 0.98, 0.95, 0.96,
                        0.99, 0.99, 0.97, 1.00, 1.06, 1.11])
SEASON = _SEASON_RAW / _SEASON_RAW.mean()
MAY = 5
def season_weight(month: int) -> float:
    return float(SEASON[month - 1])

# ----------------------------------------------------------------------------
# dataset.json — provides the metered shapes (validation) + equipment library
# and menu map (for the agent's menu path). Sector PRESETS live here in synth.
# ----------------------------------------------------------------------------
def load_dataset(path: str | None = None) -> dict:
    with open(path or os.path.join(_HERE, "data", "dataset.json")) as f:
        return json.load(f)
DATASET = load_dataset()

# ----------------------------------------------------------------------------
# SHAPE COMPOSITION — end-use placement vs opening hours (o,c are HH indices).
# ----------------------------------------------------------------------------
def _norm(a):
    a = np.asarray(a, float); s = a.sum(); return a / s if s else a
def _gauss(centre, width):
    i = np.arange(HH); return np.exp(-0.5 * ((i - centre) / width) ** 2)

def place_baseload(o, c):                       # fridges/cellar: 24/7
    return _norm(np.ones(HH))
def place_pre_open(o, c):                        # baking: ready BEFORE open
    return _norm(_gauss(o - 3, 2))

def footfall_curve(peaks, o, c):
    """The FOOTFALL (occupancy) curve from per-type busy periods —
    each peak is (hour, width_halfhours, height) — gated to opening hours.
    Fixed per business type for now; in production = Google Places Popular Times."""
    i = np.arange(HH); a = np.zeros(HH)
    for hr, w, h in peaks:
        a += h * _gauss(hr * 2, w)
    a = np.where((i >= o - 1) & (i < c), a, 0.0)
    return _norm(a) if a.sum() else _norm(np.where((i >= o) & (i < c), 1.0, 0.0))

def compose(mix: dict, footfall, o: int, c: int) -> np.ndarray:
    """A normalised daily shape. refrigeration = 24/7 baseload; baking = pre-open;
    every occupancy-driven load (cooking, hvac, lighting) FOLLOWS the footfall curve."""
    ff = footfall_curve(footfall, o, c)
    a = np.zeros(HH)
    for eu, w in mix.items():
        if eu == "refrigeration":
            p = place_baseload(o, c)
        elif eu == "baking":
            p = place_pre_open(o, c)
        else:                                    # cooking / hvac / lighting
            p = ff
        a += w * p
    return _norm(a)

# legacy primitive kept for any direct callers
def make_shape(base, bumps):
    i = np.arange(HH); arr = np.full(HH, float(base))
    for centre, width, height in bumps:
        arr += height * np.exp(-0.5 * ((i - centre) / width) ** 2)
    return arr / arr.sum()

# ----------------------------------------------------------------------------
# SECTOR PRESETS — RYE's two families. mix is over placement primitives
# (refrigeration / cooking / baking / hvac / lighting). open/close in hours.
# intensity = kWh/m2/yr — ALL from published benchmarks (no back-derivation
# from the CSVs). qsr/bakery are "validated": their blind benchmark estimate
# was checked against the metered data (see validate_bottomup.py) — size within
# ~5%, right tariff. Others are "prior": benchmark, not yet validated.
# ----------------------------------------------------------------------------
# footfall = per-type busy periods (hour, width_halfhours, height) — the fixed
# occupancy curve that drives the activity loads. (Production: Places API.)
SECTORS = {
 "qsr": dict(family="Hospitality", label="Quick-Service Restaurant",
    intensity=375, confidence="validated", floor=150, open=11, close=23, weekend_ratio=1.0,
    footfall=[[12.5, 3, 1.0], [19, 4, 0.6]],          # lunch-led
    mix={"refrigeration":0.25,"cooking":0.30,"hvac":0.30,"lighting":0.15}),
 "restaurant": dict(family="Hospitality", label="Restaurant (full service)",
    intensity=400, confidence="prior", floor=250, open=12, close=23, weekend_ratio=1.1,
    footfall=[[13, 3, 0.5], [19.5, 4, 1.0]],          # dinner-led
    mix={"refrigeration":0.20,"cooking":0.35,"hvac":0.30,"lighting":0.15}),
 "cafe": dict(family="Hospitality", label="Cafe",
    intensity=250, confidence="prior", floor=90, open=7, close=17, weekend_ratio=1.0,
    footfall=[[8.5, 3, 1.0], [12.5, 3, 0.7]],         # morning + lunch
    mix={"refrigeration":0.25,"cooking":0.15,"hvac":0.30,"lighting":0.30}),
 "bakery": dict(family="Hospitality", label="Bakery",
    intensity=400, confidence="validated", floor=120, open=7, close=17, weekend_ratio=1.2,
    footfall=[[8, 3, 1.0]],                           # breakfast (baking pre-dawn)
    mix={"baking":0.45,"refrigeration":0.25,"hvac":0.15,"lighting":0.15}),
 "pub": dict(family="Hospitality", label="Pub / bar",
    intensity=250, confidence="prior", floor=200, open=12, close=23, weekend_ratio=1.3,
    footfall=[[13, 3, 0.3], [20, 4, 1.0]],            # evening-led
    mix={"refrigeration":0.40,"cooking":0.15,"hvac":0.25,"lighting":0.20}),
 "convenience": dict(family="Retail", label="Convenience / food shop",
    intensity=300, confidence="prior", floor=120, open=7, close=23, weekend_ratio=0.95,
    footfall=[[13, 4, 0.7], [17.5, 3, 1.0]],          # lunch + after-work
    mix={"refrigeration":0.50,"hvac":0.20,"lighting":0.30}),
 "general_retail": dict(family="Retail", label="General retail (non-food)",
    intensity=165, confidence="prior", floor=200, open=9, close=18, weekend_ratio=0.9,
    footfall=[[14, 5, 1.0]],                          # broad daytime
    mix={"refrigeration":0.15,"hvac":0.40,"lighting":0.45}),
}

def _build_archetypes():
    lib = {}
    for k, s in SECTORS.items():
        wd = compose(s["mix"], s["footfall"], s["open"] * 2, s["close"] * 2)
        lib[k] = {**s, "shape_weekday": wd, "shape_weekend": wd}
    return lib
ARCHETYPES = _build_archetypes()

# ----------------------------------------------------------------------------
# SIZE
# ----------------------------------------------------------------------------
def estimate_annual_kwh(sector, floor_m2=None, annual_kwh=None) -> dict:
    a = ARCHETYPES[sector]
    if annual_kwh is not None:
        return {"annual_kwh": float(annual_kwh), "source": "override", "confidence": "high"}
    floor_m2 = floor_m2 or a["floor"]
    annual = floor_m2 * a["intensity"]
    validated = a["confidence"] == "validated"
    return {"annual_kwh": annual,
            "source": f"{floor_m2:g} m2 x {a['intensity']:.0f} kWh/m2/yr benchmark"
                      + (" (validated vs meter)" if validated else ""),
            "confidence": "medium" if validated else "low"}

# ----------------------------------------------------------------------------
# curve builder (shared) + shape metrics
# ----------------------------------------------------------------------------
def _build_curve(shape, annual, weekend_ratio, year=2026) -> pd.DataFrame:
    """Spread annual kWh across the year (season + weekday/weekend) then across
    each day by the daily shape -> a full-year half-hourly (ts, kwh) curve."""
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    is_we = days.dayofweek >= 5
    day_w = np.array([season_weight(m) for m in days.month]) * np.where(is_we, weekend_ratio, 1.0)
    daily = annual * day_w / day_w.sum()
    rows = [pd.DataFrame({"ts": pd.date_range(d, periods=HH, freq="30min"), "kwh": dk * shape})
            for d, dk in zip(days, daily)]
    return pd.concat(rows, ignore_index=True)

def shape_metrics_of(shape) -> dict:
    return {"peak_time": shapes.hh_label(int(np.argmax(shape))),
            "night_pct": round(float(np.sum(shape[0:14])) * 100, 1),
            "redband_pct": round(float(np.sum(shape[32:38])) * 100, 1)}

# ----------------------------------------------------------------------------
# THE SYNTHESISER — facts (+ optional hours) -> full-year half-hourly curve
# ----------------------------------------------------------------------------
def synthesize_year(sector, floor_m2=None, annual_kwh=None,
                    open=None, close=None, year=2026) -> dict:
    a = ARCHETYPES[sector]
    o = (a["open"] if open is None else open) * 2
    c = (a["close"] if close is None else close) * 2
    shape = compose(a["mix"], a["footfall"], o, c)

    size = estimate_annual_kwh(sector, floor_m2, annual_kwh)
    annual = size["annual_kwh"]
    curve = _build_curve(shape, annual, a["weekend_ratio"], year)

    return {"sector": sector, "label": a["label"], "family": a["family"],
            "confidence": a["confidence"], "year": year,
            "annual_kwh": float(curve["kwh"].sum()), "size_provenance": size,
            "open": o // 2, "close": c // 2, "shape_weekday": shape,
            "monthly_kwh": curve.groupby(curve["ts"].dt.month)["kwh"].sum(),
            "curve": curve}

# ----------------------------------------------------------------------------
# MENU PATH (used by the agent): menu categories -> equipment -> shape
# ----------------------------------------------------------------------------
EQUIP_TO_PRIMITIVE = {"fryer": "cooking", "grill": "cooking", "combi_oven": "cooking",
                      "deck_oven": "baking", "proofer": "baking",
                      "refrigeration": "refrigeration", "hvac": "hvac",
                      "lighting": "lighting", "it": "lighting"}

DEFAULT_FOOTFALL = ((12.5, 3, 1.0), (19, 4, 0.6))

def synthesize_from_menu(menu_categories, floor_m2, open=11, close=23,
                         intensity=375, weekend_ratio=1.0, footfall=DEFAULT_FOOTFALL,
                         year=2026) -> dict:
    """Menu path: build a full-year curve from a menu (+ size + hours), so the
    agent can price a business with no preset. Food-service intensity default."""
    shape, mix = shape_from_menu(menu_categories, footfall, open, close)
    annual = floor_m2 * intensity
    curve = _build_curve(shape, annual, weekend_ratio, year)
    return {"label": "Custom (from menu)", "annual_kwh": float(curve["kwh"].sum()),
            "shape_weekday": shape, "curve": curve, "mix": mix,
            "size_source": f"{floor_m2:g} m2 x {intensity} kWh/m2/yr (food-service benchmark)"}


def shape_from_menu(menu_categories, footfall=DEFAULT_FOOTFALL,
                    open=11, close=23):
    """Infer equipment from menu categories, weight by kW, map to placement
    primitives, compose against a footfall curve. The agent's generalisation path.
    (Menu gives equipment; footfall is a separate input — defaulted here.)"""
    m2e, lib = DATASET["menu_to_equipment"], DATASET["end_use_library"]
    prim = Counter()
    for cat in menu_categories:
        for e in m2e.get(cat, []):
            prim[EQUIP_TO_PRIMITIVE.get(e, "lighting")] += lib[e]["kw"]
    total = sum(prim.values()) or 1.0
    mix = {k: v / total for k, v in prim.items()}
    return compose(mix, footfall, open * 2, close * 2), mix


if __name__ == "__main__":
    print("UNIFIED ENGINE — sectors:",
          ", ".join(f"{k}[{v['family'][:4]}/{v['confidence'][:4]}]" for k, v in ARCHETYPES.items()))
    for k in ARCHETYPES:
        r = synthesize_year(k)
        print(f"  {r['label']:<26} {r['annual_kwh']:>8,.0f} kWh  "
              f"{shapes.sparkline(r['shape_weekday'])}")
    print("\n  hours reshape: QSR 11-23 vs 06-14 (breakfast spot)")
    for hrs in [(11, 23), (6, 14)]:
        r = synthesize_year("qsr", open=hrs[0], close=hrs[1])
        print(f"    {hrs}  {shapes.sparkline(r['shape_weekday'])}  peak "
              f"{shapes.hh_label(int(r['shape_weekday'].argmax()))}")
