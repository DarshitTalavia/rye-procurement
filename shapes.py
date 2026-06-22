"""
shapes.py  —  PART 1 of the meterless procurement estimator.

Goal of this module: turn raw half-hourly meter data into a clean, reusable
LOAD SHAPE plus the handful of metrics that actually decide which tariff wins.

Key idea: a "shape" is SIZE-independent. We normalise the daily profile so it
sums to 1.0 — i.e. "what fraction of a day's energy is drawn in each half-hour".
That normalised shape is what we'll later reuse for sectors we have no meter for.
SIZE (annual kWh) is handled separately in Part 2.

Units note (a load-bearing assumption — stated explicitly):
  The CSV column is "load". We treat it as AVERAGE POWER in kW over each
  half-hour, so energy in that half-hour = load_kW * 0.5 h = kWh.
  If RYE's export is actually kWh-per-period, multiply our kWh figures by 2.
  Either way the SHAPE (the thing that picks the tariff) is unaffected.
"""

from __future__ import annotations
import pandas as pd
import numpy as np

HALF_HOURS = 48                       # 48 half-hours in a day
HH_PER_HOUR = 2
HOURS_PER_HH = 0.5                    # kW -> kWh conversion per period


# ----------------------------------------------------------------------------
# 1. Load + clean
# ----------------------------------------------------------------------------
def load_halfhourly(path: str) -> pd.DataFrame:
    """Read a (timestamp, load) CSV into a tidy frame with helper columns.

    Columns added:
      ts        parsed timestamp
      kw        the load value (avg kW over the half-hour)
      date      calendar date
      hh        half-hour index 0..47  (00:00->0, 00:30->1, ... 23:30->47)
      dow       day of week 0=Mon..6=Sun
      is_weekend
    """
    df = pd.read_csv(path)
    # timestamps look like "2026-05-25 10:30:00.000000 UTC" — drop the " UTC"
    df["ts"] = pd.to_datetime(df["timestamp"].str.replace(" UTC", "", regex=False))
    df = df.rename(columns={"load": "kw"})

    # half-hour index of the day: hour*2 + (1 if minute==30 else 0)
    df["hh"] = df["ts"].dt.hour * HH_PER_HOUR + (df["ts"].dt.minute >= 30).astype(int)
    df["date"] = df["ts"].dt.date
    df["dow"] = df["ts"].dt.dayofweek
    df["is_weekend"] = df["dow"] >= 5

    # Keep only full May days. The files carry one stray 00:00 slot on Jun 1
    # (the period-ending reading); dropping it gives clean 31-day months.
    df = df[df["ts"].dt.month == 5].copy()
    return df.sort_values("ts").reset_index(drop=True)


# ----------------------------------------------------------------------------
# 2. Daily profiles + averaging
# ----------------------------------------------------------------------------
def daily_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot to a (days x 48) matrix of kW. Each row is one day's profile."""
    m = df.pivot_table(index="date", columns="hh", values="kw", aggfunc="mean")
    return m.reindex(columns=range(HALF_HOURS))   # ensure all 48 cols present


def average_profile(df: pd.DataFrame, which: str = "all") -> np.ndarray:
    """Mean kW in each half-hour. which = 'all' | 'weekday' | 'weekend'."""
    if which == "weekday":
        df = df[~df["is_weekend"]]
    elif which == "weekend":
        df = df[df["is_weekend"]]
    prof = df.groupby("hh")["kw"].mean().reindex(range(HALF_HOURS))
    return prof.to_numpy()


def normalise(profile: np.ndarray) -> np.ndarray:
    """Turn a kW profile into a unit SHAPE that sums to 1.0 over the day."""
    total = np.nansum(profile)
    return profile / total if total else profile


# ----------------------------------------------------------------------------
# 3. The metrics that decide the tariff
# ----------------------------------------------------------------------------
def hh_label(hh: int) -> str:
    """Half-hour index -> 'HH:MM' label."""
    return f"{hh // 2:02d}:{'30' if hh % 2 else '00'}"


def shape_metrics(df: pd.DataFrame) -> dict:
    """Compute the load-shape fingerprint of a site.

    Every metric here is decision-relevant for procurement:
      daily_kwh        magnitude sanity check
      annual_kwh       naive annualisation of May (Part 2 adds seasonality)
      baseload_kw      overnight floor = always-on (fridges/standby)
      peak_kw          biggest half-hour
      peak_hh          WHEN the peak lands  <- this is what flips the tariff
      load_factor      mean/peak; flat load -> high, peaky -> low
      night_share      energy 23:00-07:00  -> value of an Economy-7 night rate
      redband_share    energy 16:00-19:00 weekdays -> DUoS red-band exposure
      weekend_ratio    weekend daily kWh / weekday daily kWh
    """
    prof = average_profile(df, "all")                 # mean kW per half-hour
    daily_kwh = np.nansum(prof) * HOURS_PER_HH        # avg day's energy
    baseload = float(np.nanmin(prof))
    peak = float(np.nanmax(prof))
    peak_hh = int(np.nanargmax(prof))

    # night window 23:00–07:00  => hh in [46,47] U [0,13]
    night_hh = list(range(46, 48)) + list(range(0, 14))
    night_share = float(np.nansum(prof[night_hh]) / np.nansum(prof))

    # DUoS red band ~16:00–19:00 on weekdays => hh 32..37 (weekday profile)
    wk = average_profile(df, "weekday")
    red_hh = list(range(32, 38))
    redband_share = float(np.nansum(wk[red_hh]) / np.nansum(wk))

    # weekend vs weekday daily energy
    wk_daily = np.nansum(average_profile(df, "weekday")) * HOURS_PER_HH
    we_daily = np.nansum(average_profile(df, "weekend")) * HOURS_PER_HH

    return {
        "daily_kwh": round(daily_kwh, 1),
        "annual_kwh_naive": round(daily_kwh * 365, 0),
        "baseload_kw": round(baseload, 2),
        "peak_kw": round(peak, 2),
        "peak_time": hh_label(peak_hh),
        "load_factor": round(float(np.nanmean(prof) / peak), 2),
        "night_share_pct": round(night_share * 100, 1),
        "redband_share_pct": round(redband_share * 100, 1),
        "weekend_ratio": round(float(we_daily / wk_daily), 2) if wk_daily else None,
    }


# ----------------------------------------------------------------------------
# 4. Terminal visual so we can SEE the shape (no matplotlib needed)
# ----------------------------------------------------------------------------
def sparkline(profile: np.ndarray) -> str:
    """8-level unicode sparkline of a 48-point profile."""
    bars = "▁▂▃▄▅▆▇█"
    p = np.nan_to_num(profile)
    lo, hi = p.min(), p.max()
    rng = hi - lo or 1
    idx = ((p - lo) / rng * (len(bars) - 1)).round().astype(int)
    return "".join(bars[i] for i in idx)


def summarise(name: str, path: str) -> dict:
    """Load a sector file and print its shape fingerprint + visual."""
    df = load_halfhourly(path)
    m = shape_metrics(df)
    n_days = df["date"].nunique()

    print(f"\n{'='*72}\n  {name}   ({n_days} days, {len(df)} half-hour readings)\n{'='*72}")
    print(f"  Annual (naive)   : {m['annual_kwh_naive']:>10,.0f} kWh   "
          f"(daily {m['daily_kwh']} kWh)")
    print(f"  Baseload / Peak  : {m['baseload_kw']:>6} kW  /  {m['peak_kw']} kW   "
          f"(load factor {m['load_factor']})")
    print(f"  Peak lands at    : {m['peak_time']}")
    print(f"  Night share      : {m['night_share_pct']:>5}%   (23:00-07:00  -> Economy-7 value)")
    print(f"  Red-band share   : {m['redband_share_pct']:>5}%   (16:00-19:00 wkdy -> DUoS cost)")
    print(f"  Weekend vs wkday : {m['weekend_ratio']}x")
    print(f"\n  Daily shape  (00:00 ............................................ 23:30)")
    print(f"    all     {sparkline(average_profile(df, 'all'))}")
    print(f"    weekday {sparkline(average_profile(df, 'weekday'))}")
    print(f"    weekend {sparkline(average_profile(df, 'weekend'))}")
    return m


if __name__ == "__main__":
    summarise("QSR (Quick-Service Restaurant)", "data/qsr_may.csv")
    summarise("Bakery", "data/bakery_may.csv")
