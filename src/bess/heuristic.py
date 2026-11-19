"""Rule-of-thumb benchmark (at most about one cycle a day): charge in the cheapest
intervals, discharge in the dearest.

For each day:
  1. n_c = intervals at full power needed to fill the battery from empty,
     n_d = intervals at full power needed to empty it.
  2. Mark the n_c cheapest intervals for charging and the n_d dearest for discharging.
  3. Skip the day if the spread does not cover losses and degradation:
         mean(dear) * rte - mean(cheap) - kappa * rte <= 0     ($ per MWh bought)
  4. Walk through the day in time order. Charge or discharge at full power when the
     interval is marked, clipped so the SoC stays within limits.
The SoC carries over from one day to the next (no end-of-day target).
"""
from __future__ import annotations

import math

import numpy as np

from .model import Battery, Solution


def day_schedule(prices, dt_h: float, batt: Battery, e0: float) -> Solution:
    p = np.asarray(prices, dtype=float)
    T = len(p)
    P, usable = batt.power_mw, batt.e_max - batt.e_min
    n_c = math.ceil(usable / (batt.eta_c * P * dt_h) - 1e-9)
    n_d = math.ceil(usable * batt.eta_d / (P * dt_h) - 1e-9)
    order = np.argsort(p, kind="stable")
    cheap, dear = set(order[:n_c]), set(order[::-1][:n_d])

    c, d, e = np.zeros(T), np.zeros(T), np.zeros(T)
    trade = p[list(dear)].mean() * batt.rte - p[list(cheap)].mean() - batt.deg_cost * batt.rte > 0
    soc = e0
    for t in range(T):
        if trade and t in cheap and t not in dear:
            c[t] = min(P, (batt.e_max - soc) / (batt.eta_c * dt_h))
        elif trade and t in dear and t not in cheap:
            d[t] = min(P, (soc - batt.e_min) * batt.eta_d / dt_h)
        soc = soc + batt.eta_c * c[t] * dt_h - d[t] * dt_h / batt.eta_d
        e[t] = soc
    return Solution(charge=c, discharge=d, soc=e,
                    energy_revenue=float(np.sum(p * (d - c) * dt_h)),
                    degradation=float(np.sum(batt.deg_cost * d * dt_h)),
                    solve_seconds=0.0)
