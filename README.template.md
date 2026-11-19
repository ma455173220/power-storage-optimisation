# Battery arbitrage in the NEM: LP vs MILP

<!-- README.md is generated from README.template.md by `make report`; edit the template. -->

How much could a grid-scale battery earn from energy arbitrage in South Australia (SA1) and New South Wales (NSW1)? This repository answers that with a small, reproducible optimisation study on AEMO 5-minute prices for May–October 2026 (@@n_days@@ days). It compares:

- a **linear programme (LP)** with a **mixed-integer programme (MILP)** that forbids charging and discharging at the same time;
- **daily rolling** solves with a **full-month** solve (an upper bound);
- **5-minute** with **30-minute** price resolution;
- the optimiser with a **rule-of-thumb heuristic**.

Built with Pyomo + HiGHS. Developed with AI coding agents (Claude Code); the formulation, tests and results were checked by the author.

## Key results

Base case: 100 MW / 2 h battery, round-trip efficiency 85%, degradation cost 10 $/MWh discharged, perfect foresight, energy arbitrage only.

@@table_headline@@

- **The optimiser earns @@sa1_milp_vs_heur@@ the heuristic's profit in SA1 and @@nsw1_milp_vs_heur@@ in NSW1.** The heuristic makes at most about one full cycle a day; the optimiser cycles whenever the spread covers losses and degradation.
- **The LP overstates profit by @@sa1_lp_minus_milp@@ (@@sa1_lp_minus_milp_pct@@) in SA1** because in @@sa1_lp_sim@@ five-minute intervals it charges and discharges at the same time, wasting energy while being paid to consume it. This only pays when the price is below the *burn threshold* −κ·rte/(1−rte) = @@burn_threshold@@ $/MWh; the highest price at which the LP did it was @@sa1_lp_sim_maxprice@@. NSW1 prices never fell that low (minimum @@nsw1_min_price@@ $/MWh), so there the LP and MILP give the same profit (difference @@nsw1_lp_minus_milp@@).
- **Solving one day at a time captures @@sa1_daily_capture@@ (SA1) and @@nsw1_daily_capture@@ (NSW1) of the full-month optimum.** The loss comes from forcing the battery back to 50% at midnight.
- **Resolution matters:** with 30-minute average prices the MILP earns @@sa1_30min_loss@@ (SA1) and @@nsw1_30min_loss@@ (NSW1) less than with 5-minute prices.
- **Duration:** a 4 h battery earns @@sa1_4h_gain@@ (SA1) and @@nsw1_4h_gain@@ (NSW1) more per MW than a 2 h battery.

These are perfect-foresight, price-taker numbers: an upper bound on energy-arbitrage revenue, not a forecast of what a real battery would earn (see [Limitations](#limitations)).

## Model

For each interval $t$ of length $\Delta t$ hours with price $p_t$ ($/MWh):

| Symbol | Meaning |
|---|---|
| $c_t, d_t \in [0, P]$ | charging and discharging power (MW) |
| $e_t \in [E_{min}, E_{max}]$ | stored energy at the end of interval $t$ (MWh) |
| $u_t \in \{0, 1\}$ | MILP only: 1 if the battery may charge in interval $t$ |
| $\eta_c = \eta_d = \sqrt{rte}$ | charging and discharging efficiency |
| $\kappa$ | degradation cost per MWh discharged ($/MWh) |

$$\max \sum_t \Big[\, p_t\,(d_t - c_t)\,\Delta t \;-\; \kappa\, d_t\, \Delta t \,\Big]$$

subject to

$$e_t = e_{t-1} + \eta_c\, c_t\, \Delta t - \frac{d_t\, \Delta t}{\eta_d}, \qquad e_{-1} = e_0, \qquad e_{T-1} = e_0$$

and, in the MILP only,

$$c_t \le P\, u_t, \qquad d_t \le P\,(1 - u_t).$$

- **Objective:** the first term is the energy bought and sold at the spot price; the second is a linear stand-in for battery wear, charged per MWh discharged.
- **Why the LP can charge and discharge at once:** raising $c_t$ by $x$ and $d_t$ by $rte \cdot x$ leaves the stored energy unchanged, buys $(1-rte)\,x$ more energy and adds $\kappa \cdot rte \cdot x$ of degradation. That is profitable exactly when $p_t < -\kappa\, rte / (1 - rte)$. The binary $u_t$ rules it out. The tests check that every simultaneous interval in an LP solution lies below this threshold.
- **Shadow prices:** `model.solve(..., duals=True)` returns the dual of each energy-balance constraint, i.e. the value of one more MWh in storage at the end of that interval. The tests check it against the optimality conditions: it equals $p_t/\eta_c$ while charging below full power and $\eta_d (p_t - \kappa)$ while discharging below full power, and it stays constant while the state of charge is strictly between its limits.
- **Daily rolling:** each calendar day (NEM time, AEST) is solved separately, starting and ending at 50% state of charge. The **full-month** variant solves each month as a single problem with the same start and end condition.
- **Heuristic benchmark:** each day, mark the cheapest intervals needed to fill the battery and the dearest needed to empty it; skip the day if the average spread does not cover losses and degradation; then charge or discharge at full power in marked intervals, in time order, within the energy limits.

## Data

AEMO aggregated price and demand data, one CSV per region and month, downloaded by `bess/data.py` from
`https://www.aemo.com.au/aemo/data/nem/priceanddemand/PRICE_AND_DEMAND_YYYYMM_REGION.csv`.
`SETTLEMENTDATE` is the end of each 5-minute interval in NEM time (AEST, UTC+10). The raw files are cached in `data/raw/` and are not committed.

Every file is validated: continuous 5-minute timestamps for the whole month, no duplicates, no missing values, period type `TRADE`, and prices within the market price floor and cap for the relevant financial year. All @@n_intervals_total@@ intervals passed.

@@table_data@@

Source: Australian Energy Market Operator (AEMO), *Aggregated price and demand data*, used under AEMO's copyright permissions, which allow use for any purpose with accurate attribution to AEMO.

## Parameters

| Parameter | Value | Source or status |
|---|---|---|
| Power | 100 MW | Assumption |
| Duration | 2 h (4 h in sensitivity) | Assumption |
| Round-trip efficiency | 85% (80% and 90% in sensitivity) | Assumption. For reference, the US utility-scale battery fleet averaged a monthly round-trip efficiency of 82% in 2019 (US EIA, *Today in Energy*, 12 February 2021). |
| Degradation cost κ | 10 $/MWh discharged (0, 5 and 20 in sensitivity) | Assumption |
| Energy limits | 0–100% of rated energy | Assumption (rated energy treated as usable) |
| Start and end-of-day state of charge | 50% | Assumption |
| Market price floor | −1,000 $/MWh | National Electricity Rules, clause 3.9.6 |
| Market price cap | 20,300 $/MWh (2025-26), 23,200 $/MWh (2026-27) | 2025-26: WattClarity, 1 July 2025. 2026-27: AEMC media release *AEMC updates market price cap 2026-27*, as quoted in search results (the page itself refused automated access). Both caps appear as the maximum price in the data table above. |
| MILP optimality gap | @@mip_gap@@ (relative) | Solver setting |

## Results

### LP vs MILP: simultaneous charging and discharging

@@table_kappa@@

The lower the degradation cost, the higher the burn threshold and the more often the LP exploits it. With κ = 0 any negative price is enough. The interval counts are not unique: the LP can have several optimal schedules with the same profit, and switching the simplex variant changed some counts by a few intervals while the profits stayed identical. The profit gap is the robust measure.

![SA1 day with the most LP simultaneous charging and discharging](results/figures/showcase_SA1.png)

On @@show_day@@ the LP charged and discharged at once in @@show_n_sim@@ intervals, all at prices of @@show_max_price@@ $/MWh or lower. The MILP schedule never does both.

### Monthly profit

![Monthly profit by strategy](results/figures/monthly_profit.png)

June 2026 dominates SA1; that month's prices reached the market price cap (see the data table).

Daily rolling vs full-month solve (MILP):

@@table_full@@

### Sensitivity

![Sensitivity of annualised profit](results/figures/sensitivity.png)

@@table_sensitivity@@

## Performance

Each daily problem has 288 five-minute intervals. The whole study (@@n_jobs@@ independent jobs) runs in parallel on @@workers@@ processes: @@wall_seconds@@ s wall-clock for @@sum_solver_seconds@@ s of solver time. Timings depend on the machine.

The choice of LP algorithm mattered a lot. On the largest LP (@@bench_case@@):

@@table_bench@@

HiGHS's default dual simplex was @@bench_speedup@@ slower than primal simplex on this problem, with the same optimum, so the LPs here use primal simplex (`bess/bench.py` reproduces the comparison). This study also uses rolling daily horizons and runs independent cases in parallel. Other options, not tried here: coarser time steps where accuracy allows, warm starts from the previous day's solution, and solver tuning for the MILP.

## Limitations

- **Perfect foresight:** the battery knows every price of the day in advance. Real operation relies on forecasts, so these results are an upper bound.
- **Price-taker:** a 100 MW battery is assumed not to move prices, which is optimistic in a small region such as SA1.
- **Energy only:** frequency control ancillary services (FCAS), network charges and marginal loss factors are not modelled.
- **Simple degradation:** a fixed cost per MWh discharged, with no dependence on depth of discharge or state of charge and no capacity fade.
- **Fixed daily state-of-charge target:** the full-month comparison shows what this costs.
- **30-minute case:** prices are averaged to 30 minutes to measure the value of resolution; settlement in the NEM has been five-minute since October 2021.

## Next steps

Forecast-based scheduling (measure the share of perfect-foresight profit captured), FCAS co-optimisation, price impact, and a mini economic-dispatch model whose energy-balance shadow prices give marginal prices.

## How to run

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
make env    # create .venv and install the pinned packages (requirements.lock)
make all    # download data, run tests, run all experiments, benchmark, figures, README
```

Individual steps: `make data`, `make test`, `make run` (the slowest step; see Performance), `make bench`, `make report`.

| Path | Contents |
|---|---|
| `src/bess/data.py` | download, validation, 30-minute aggregation |
| `src/bess/model.py` | LP/MILP battery model (Pyomo) |
| `src/bess/heuristic.py` | rule-of-thumb benchmark |
| `src/bess/backtest.py` | daily rolling and full-horizon runs, metrics |
| `src/bess/run.py` | all experiments, in parallel |
| `src/bess/bench.py` | HiGHS LP algorithm benchmark |
| `src/bess/report.py` | figures and this README |
| `tests/` | pytest: hand-calculated examples, energy balance, bounds, LP vs MILP, data checks |
| `results/` | generated tables and figures |

## License

Code: MIT (see `LICENSE`). Price data: © AEMO, not redistributed here; downloaded from AEMO and used under its copyright permissions with attribution.
