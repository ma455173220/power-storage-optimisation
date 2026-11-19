"""Benchmark HiGHS LP algorithms on the largest LP in the project (one month, 5-minute).

    python -m bess.bench        -> results/benchmark.csv
Timings depend on the machine; the optimum must be identical across algorithms.
"""
import time

import pandas as pd
import pyomo.environ as pyo

from . import data, model
from .model import Battery

CASES = {
    "dual simplex (HiGHS default)": {"solver": "simplex", "simplex_strategy": 1},
    "primal simplex (used here)": {"solver": "simplex", "simplex_strategy": 4},
    "interior point (IPM)": {"solver": "ipm"},
    "PDLP (first-order)": {"solver": "pdlp"},
}


def main(region="NSW1", month="202610"):
    df = data.load_csv(data.raw_path(region, month))
    rows, saved = [], dict(model.LP_HIGHS_OPTIONS)
    try:
        for name, opts in CASES.items():
            model.LP_HIGHS_OPTIONS.clear()
            model.LP_HIGHS_OPTIONS.update(opts)
            t = time.perf_counter()
            sol = model.solve(df["rrp"].to_numpy(), 1 / 12, Battery())
            rows.append({"algorithm": name, "seconds": time.perf_counter() - t, "profit": sol.profit})
    finally:
        model.LP_HIGHS_OPTIONS.clear()
        model.LP_HIGHS_OPTIONS.update(saved)
    out = pd.DataFrame(rows).assign(case=f"{region} {month}, {len(df)} intervals, LP")
    data.RESULTS_DIR.mkdir(exist_ok=True)
    out.to_csv(data.RESULTS_DIR / "benchmark.csv", index=False, float_format="%.2f")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
