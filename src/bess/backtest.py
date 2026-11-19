"""Run a battery strategy over many days and collect daily results."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import heuristic, model
from .model import Battery

METHODS = ("lp", "milp", "heuristic")


def split_days(df: pd.DataFrame, dt_h: float) -> list[tuple[pd.Timestamp, pd.DataFrame]]:
    """Group intervals into calendar days by interval START time (NEM time)."""
    start = df["interval_end"] - pd.Timedelta(hours=dt_h)
    per_day = round(24 / dt_h)
    out = []
    for day, g in df.groupby(start.dt.normalize()):
        if len(g) != per_day:
            raise ValueError(f"{day.date()}: {len(g)} intervals, expected {per_day}")
        out.append((day, g))
    return out


def day_row(day, g, sol: model.Solution, dt_h: float) -> dict:
    p = g["rrp"].to_numpy()
    neg = p < 0
    return {
        "date": day,
        "energy_revenue": sol.energy_revenue,
        "degradation": sol.degradation,
        "profit": sol.profit,
        "charge_mwh": float(sol.charge.sum() * dt_h),
        "discharge_mwh": float(sol.discharge.sum() * dt_h),
        "soc_end": float(sol.soc[-1]),
        "n_simultaneous": int(sol.simultaneous.sum()),
        "n_simultaneous_negative_price": int((sol.simultaneous & neg).sum()),
        # highest price at which the battery charged and discharged at once (NaN if never)
        "max_price_simultaneous": float(p[sol.simultaneous].max()) if sol.simultaneous.any() else float("nan"),
        "solve_seconds": sol.solve_seconds,
    }


def rolling(df: pd.DataFrame, dt_h: float, batt: Battery, method: str,
            keep_schedule: bool = False):
    """Solve day by day.

    lp / milp: each day starts and ends at the battery's initial SoC.
    heuristic: SoC carries over from the previous day.
    Returns a DataFrame with one row per day (and the interval schedule if requested).
    """
    if method not in METHODS:
        raise ValueError(method)
    rows, sched = [], []
    soc = batt.e_init
    for day, g in split_days(df, dt_h):
        p = g["rrp"].to_numpy()
        if method == "heuristic":
            sol = heuristic.day_schedule(p, dt_h, batt, e0=soc)
            soc = sol.soc[-1]
        else:
            sol = model.solve(p, dt_h, batt, binary=(method == "milp"))
        rows.append(day_row(day, g, sol, dt_h))
        if keep_schedule:
            sched.append(pd.DataFrame({"interval_end": g["interval_end"].to_numpy(), "rrp": p,
                                       "charge_mw": sol.charge, "discharge_mw": sol.discharge,
                                       "soc_mwh": sol.soc}))
    daily = pd.DataFrame(rows)
    if keep_schedule:
        return daily, pd.concat(sched, ignore_index=True)
    return daily


def full_horizon(df: pd.DataFrame, dt_h: float, batt: Battery, binary: bool) -> dict:
    """Solve the whole frame (e.g. one month) as a single optimisation."""
    p = df["rrp"].to_numpy()
    sol = model.solve(p, dt_h, batt, binary=binary)
    return {"profit": sol.profit, "energy_revenue": sol.energy_revenue,
            "degradation": sol.degradation, "discharge_mwh": float(sol.discharge.sum() * dt_h),
            "n_simultaneous": int(sol.simultaneous.sum()), "solve_seconds": sol.solve_seconds}


def summarise(daily: pd.DataFrame, batt: Battery) -> dict:
    """Totals and standard metrics over the days in `daily`."""
    n_days = len(daily)
    profit = daily["profit"].sum()
    usable = batt.e_max - batt.e_min
    return {
        "days": n_days,
        "profit": profit,
        "energy_revenue": daily["energy_revenue"].sum(),
        "degradation": daily["degradation"].sum(),
        # annualised profit per MW of power capacity
        "profit_per_mw_year": profit / batt.power_mw / (n_days / 365.0),
        # equivalent full cycles: energy delivered to the grid / usable energy capacity
        "cycles_per_day": daily["discharge_mwh"].sum() / usable / n_days,
        "n_simultaneous": int(daily["n_simultaneous"].sum()),
        "n_simultaneous_negative_price": int(daily["n_simultaneous_negative_price"].sum()),
        "max_price_simultaneous": daily["max_price_simultaneous"].max(),
        "solve_seconds": daily["solve_seconds"].sum(),
    }
