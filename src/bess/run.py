"""Run every experiment and write the result tables to results/.

    python -m bess.run

Experiments (each region: SA1 and NSW1, May-Oct 2026):
  base        100 MW / 2 h, 5-minute prices        LP, MILP, heuristic
  base_30min  same battery, 30-minute mean prices  LP, MILP, heuristic
  dur_4h      100 MW / 4 h, 5-minute prices        LP, MILP, heuristic
  rte_0.80, rte_0.90      round-trip efficiency     MILP
  kappa_0, kappa_5, kappa_20  degradation cost      LP, MILP
  full_horizon  base battery, one solve per month   LP, MILP   (upper bound for daily rolling)
Jobs run in parallel processes; each job is independent.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace

import pandas as pd

from . import backtest, data, model
from .model import Battery

RESULTS = data.RESULTS_DIR
BASE = Battery()
SCENARIOS = {
    "base": (BASE, "5min", ("lp", "milp", "heuristic")),
    "base_30min": (BASE, "30min", ("lp", "milp", "heuristic")),
    "dur_4h": (replace(BASE, duration_h=4.0), "5min", ("lp", "milp", "heuristic")),
    "rte_0.80": (replace(BASE, rte=0.80), "5min", ("milp",)),
    "rte_0.90": (replace(BASE, rte=0.90), "5min", ("milp",)),
    "kappa_0": (replace(BASE, deg_cost=0.0), "5min", ("lp", "milp")),
    "kappa_5": (replace(BASE, deg_cost=5.0), "5min", ("lp", "milp")),
    "kappa_20": (replace(BASE, deg_cost=20.0), "5min", ("lp", "milp")),
}
DT = {"5min": 1 / 12, "30min": 0.5}


def prices(region: str, resolution: str) -> pd.DataFrame:
    df = data.load(region)
    return df if resolution == "5min" else data.to_30min(df)


def daily_job(region, scenario, method):
    batt, res, _ = SCENARIOS[scenario]
    daily = backtest.rolling(prices(region, res), DT[res], batt, method)
    return region, scenario, method, daily


def month_job(region, month, method):
    df = data.load_csv(data.raw_path(region, month))
    out = backtest.full_horizon(df, DT["5min"], BASE, binary=(method == "milp"))
    return {"region": region, "month": month, "method": method, **out}


def showcase(region: str, daily_lp: pd.DataFrame) -> pd.DataFrame:
    """Schedules (LP and MILP) for the day with the most LP simultaneous charge/discharge."""
    day = daily_lp.loc[daily_lp["n_simultaneous_negative_price"].idxmax(), "date"]
    g = dict(backtest.split_days(prices(region, "5min"), DT["5min"]))[day]
    frames = []
    for method in ("lp", "milp"):
        sol = model.solve(g["rrp"].to_numpy(), DT["5min"], BASE, binary=(method == "milp"))
        frames.append(pd.DataFrame({"region": region, "date": day, "method": method,
                                    "interval_end": g["interval_end"].to_numpy(), "rrp": g["rrp"].to_numpy(),
                                    "charge_mw": sol.charge, "discharge_mw": sol.discharge,
                                    "soc_mwh": sol.soc}))
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    t0 = time.perf_counter()
    RESULTS.mkdir(exist_ok=True)
    jobs = [(r, s, m) for r in data.REGIONS for s, (_, _, ms) in SCENARIOS.items() for m in ms]
    mjobs = [(r, mo, m) for r in data.REGIONS for mo in data.MONTHS for m in ("lp", "milp")]
    workers = os.cpu_count() or 1
    with ProcessPoolExecutor(max_workers=workers) as pool:
        fut_daily = [pool.submit(daily_job, *j) for j in jobs]
        fut_month = [pool.submit(month_job, *j) for j in mjobs]
        daily_results = [f.result() for f in fut_daily]
        month_rows = [f.result() for f in fut_month]

    summary, monthly, dailies = [], [], {}
    for region, scenario, method, daily in daily_results:
        batt, res, _ = SCENARIOS[scenario]
        dailies[(region, scenario, method)] = daily
        summary.append({"region": region, "scenario": scenario, "method": method, "resolution": res,
                        **{k: v for k, v in asdict(batt).items()}, **backtest.summarise(daily, batt)})
        m = daily.assign(month=daily["date"].dt.strftime("%Y%m")).groupby("month")["profit"].sum()
        monthly += [{"region": region, "scenario": scenario, "method": method, "month": mo, "profit": v}
                    for mo, v in m.items()]
    summary = pd.DataFrame(summary)
    monthly = pd.DataFrame(monthly)
    full = pd.DataFrame(month_rows)
    daily_sum = monthly[monthly["scenario"] == "base"].rename(columns={"profit": "daily_rolling_profit"})
    full = full.merge(daily_sum[["region", "month", "method", "daily_rolling_profit"]],
                      on=["region", "month", "method"], how="left")

    summary.to_csv(RESULTS / "summary.csv", index=False, float_format="%.4f")
    monthly.to_csv(RESULTS / "monthly.csv", index=False, float_format="%.2f")
    full.to_csv(RESULTS / "full_horizon.csv", index=False, float_format="%.2f")
    pd.concat([showcase(r, dailies[(r, "base", "lp")]) for r in data.REGIONS]).to_csv(
        RESULTS / "showcase_days.csv", index=False, float_format="%.4f")
    for (region, scenario, method), daily in dailies.items():
        if scenario == "base":
            daily.to_csv(RESULTS / f"daily_{region}_{method}.csv", index=False, float_format="%.4f")

    meta = {"wall_seconds": round(time.perf_counter() - t0, 1), "workers": workers,
            "n_daily_jobs": len(jobs), "n_month_jobs": len(mjobs),
            "sum_solver_seconds": round(float(summary["solve_seconds"].sum() + full["solve_seconds"].sum()), 1),
            "mip_gap": model.MIP_GAP, "months": list(data.MONTHS), "regions": list(data.REGIONS)}
    (RESULTS / "run_meta.json").write_text(json.dumps(meta, indent=2))
    print(summary[["region", "scenario", "method", "profit", "profit_per_mw_year", "cycles_per_day",
                   "n_simultaneous", "solve_seconds"]].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
