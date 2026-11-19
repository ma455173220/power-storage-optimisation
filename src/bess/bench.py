"""Benchmark HiGHS LP algorithms on every month-long LP (5-minute, base battery).

    python -m bess.bench        -> results/benchmark.csv
Timings depend on the machine; the optimum must be identical across algorithms.
"""
import time

import numpy as np
import pandas as pd

from . import data, model
from .model import Battery

CASES = {
    "HiGHS default (no options)": {},
    "primal simplex": {"solver": "simplex", "simplex_strategy": 4},
    "interior point (IPM)": {"solver": "ipm"},
}


def main():
    rows, saved = [], dict(model.LP_HIGHS_OPTIONS)
    try:
        for region in data.REGIONS:
            for month in data.MONTHS:
                p = data.load_csv(data.raw_path(region, month))["rrp"].to_numpy()
                for name, opts in CASES.items():
                    model.LP_HIGHS_OPTIONS.clear()
                    model.LP_HIGHS_OPTIONS.update(opts)
                    t = time.perf_counter()
                    sol = model.solve(p, 1 / 12, Battery())
                    rows.append({"region": region, "month": month, "algorithm": name,
                                 "seconds": time.perf_counter() - t, "profit": sol.profit,
                                 "max_price": p.max()})
    finally:
        model.LP_HIGHS_OPTIONS.clear()
        model.LP_HIGHS_OPTIONS.update(saved)
    out = pd.DataFrame(rows)
    spread = out.groupby(["region", "month"])["profit"].agg(lambda s: s.max() - s.min())
    assert np.all(spread < 1e-3 * out["profit"].abs().max()), "algorithms disagree on the optimum"
    data.RESULTS_DIR.mkdir(exist_ok=True)
    out.to_csv(data.RESULTS_DIR / "benchmark.csv", index=False, float_format="%.3f")
    print(out.pivot_table(index=["region", "month"], columns="algorithm", values="seconds").round(2))


if __name__ == "__main__":
    main()
