"""Battery arbitrage as an LP or MILP (Pyomo + HiGHS).

Price-taker with perfect foresight over the window being solved. For each interval t:

    decision variables   c_t  charging power from the grid      [MW]   0 <= c_t <= P
                         d_t  discharging power to the grid     [MW]   0 <= d_t <= P
                         e_t  stored energy at the END of t     [MWh]  E_min <= e_t <= E_max
                         u_t  1 if charging is allowed (MILP only)      binary
    energy balance       e_t = e_{t-1} + eta_c * c_t * dt - d_t * dt / eta_d     (e_{-1} = e0)
    terminal condition   e_{T-1} = e_end
    MILP only            c_t <= P * u_t,   d_t <= P * (1 - u_t)
    objective            max  sum_t [ p_t * (d_t - c_t) * dt  -  kappa * d_t * dt ]

p_t is the price ($/MWh), dt the interval length (h) and kappa the degradation cost
per MWh discharged ($/MWh).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np
import pyomo.environ as pyo

SOLVER = "appsi_highs"
# LP algorithm: primal simplex. On the two month-long LPs whose prices reached the market
# price cap, HiGHS's default was much slower than primal simplex (same optimum); on the other
# months it was about as fast. `python -m bess.bench` measures all twelve months.
LP_HIGHS_OPTIONS = {"solver": "simplex", "simplex_strategy": 4}
MIP_GAP = 1e-6  # relative MILP optimality gap (HiGHS default is 1e-4; tighter is affordable here)
TOL = 1e-6  # MW; below this a power value counts as zero


@dataclass(frozen=True)
class Battery:
    power_mw: float = 100.0
    duration_h: float = 2.0
    rte: float = 0.85             # round-trip efficiency (AC-AC); split equally between charge and discharge
    deg_cost: float = 10.0        # kappa, $ per MWh discharged (ASSUMPTION, see README Parameters)
    soc_min_frac: float = 0.0
    soc_max_frac: float = 1.0
    soc_init_frac: float = 0.5
    # Optional cap on equivalent full cycles per day: energy delivered to the grid per day
    # <= max_cycles_per_day * usable energy. None = no cap.
    max_cycles_per_day: float | None = None

    @property
    def energy_mwh(self) -> float:
        return self.power_mw * self.duration_h

    @property
    def eta_c(self) -> float:
        return math.sqrt(self.rte)

    @property
    def eta_d(self) -> float:
        return math.sqrt(self.rte)

    @property
    def burn_threshold(self) -> float:
        """Price below which charging and discharging at once can pay ($/MWh).

        Raising c by x and d by rte*x leaves the SoC unchanged, buys (1 - rte)*x more
        energy and adds degradation kappa*rte*x. That pays only if
        -p*(1 - rte) > kappa*rte, i.e. p < -kappa*rte/(1 - rte).
        """
        return -self.deg_cost * self.rte / (1 - self.rte) + 0.0  # + 0.0 avoids -0.0

    @property
    def e_min(self) -> float:
        return self.soc_min_frac * self.energy_mwh

    @property
    def e_max(self) -> float:
        return self.soc_max_frac * self.energy_mwh

    @property
    def e_init(self) -> float:
        return self.soc_init_frac * self.energy_mwh


@dataclass
class Solution:
    charge: np.ndarray      # MW
    discharge: np.ndarray   # MW
    soc: np.ndarray         # MWh at the end of each interval
    energy_revenue: float   # $  sum p (d - c) dt
    degradation: float      # $  sum kappa d dt
    solve_seconds: float
    balance_dual: np.ndarray | None = None  # $/MWh: value of one more MWh stored at the end of t

    @property
    def profit(self) -> float:
        return self.energy_revenue - self.degradation

    @property
    def simultaneous(self) -> np.ndarray:
        """Boolean mask of intervals where the battery charges and discharges at once."""
        return (self.charge > TOL) & (self.discharge > TOL)


def solve(prices, dt_h: float, batt: Battery, binary: bool = False,
          e0: float | None = None, e_end: float | None = None, duals: bool = False) -> Solution:
    """Solve one window. e0 / e_end default to the battery's initial SoC.

    duals=True (LP only) also returns the shadow price of each energy-balance constraint.
    """
    p = np.asarray(prices, dtype=float)
    T = len(p)
    e0 = batt.e_init if e0 is None else e0
    e_end = e0 if e_end is None else e_end
    P = batt.power_mw

    m = pyo.ConcreteModel()
    m.T = pyo.RangeSet(0, T - 1)
    m.c = pyo.Var(m.T, bounds=(0, P))
    m.d = pyo.Var(m.T, bounds=(0, P))
    m.e = pyo.Var(m.T, bounds=(batt.e_min, batt.e_max))

    def balance(m, t):
        prev = e0 if t == 0 else m.e[t - 1]
        return m.e[t] == prev + batt.eta_c * m.c[t] * dt_h - m.d[t] * dt_h / batt.eta_d
    m.balance = pyo.Constraint(m.T, rule=balance)
    m.terminal = pyo.Constraint(expr=m.e[T - 1] == e_end)
    if batt.max_cycles_per_day is not None:
        days = T * dt_h / 24
        m.cycles = pyo.Constraint(expr=sum(m.d[t] * dt_h for t in m.T)
                                  <= batt.max_cycles_per_day * (batt.e_max - batt.e_min) * days)

    if binary:
        m.u = pyo.Var(m.T, within=pyo.Binary)
        m.c_on = pyo.Constraint(m.T, rule=lambda m, t: m.c[t] <= P * m.u[t])
        m.d_on = pyo.Constraint(m.T, rule=lambda m, t: m.d[t] <= P * (1 - m.u[t]))

    m.obj = pyo.Objective(
        expr=sum(p[t] * (m.d[t] - m.c[t]) * dt_h - batt.deg_cost * m.d[t] * dt_h for t in m.T),
        sense=pyo.maximize)

    t0 = time.perf_counter()
    if duals:
        if binary:
            raise ValueError("duals are only defined for the LP")
        m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)
    opt = pyo.SolverFactory(SOLVER)
    if binary:
        opt.config.mip_gap = MIP_GAP
    else:
        opt.highs_options = dict(LP_HIGHS_OPTIONS)
    res = opt.solve(m)
    secs = time.perf_counter() - t0
    if res.solver.termination_condition != pyo.TerminationCondition.optimal:
        raise RuntimeError(f"Solver status: {res.solver.termination_condition}")

    c = np.array([pyo.value(m.c[t]) for t in m.T])
    d = np.array([pyo.value(m.d[t]) for t in m.T])
    e = np.array([pyo.value(m.e[t]) for t in m.T])
    # Shadow price of the energy balance: change in the optimal objective per extra MWh in
    # storage at the end of t (sign checked against the stationarity conditions in tests).
    lam = np.array([m.dual[m.balance[t]] for t in m.T]) if duals else None
    return Solution(charge=c, discharge=d, soc=e,
                    energy_revenue=float(np.sum(p * (d - c) * dt_h)),
                    degradation=float(np.sum(batt.deg_cost * d * dt_h)),
                    solve_seconds=secs, balance_dual=lam)
