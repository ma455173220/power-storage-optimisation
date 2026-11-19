# Battery arbitrage in the NEM: LP vs MILP

<!-- README.md is generated from README.template.md by `make report`; edit the template. -->

How much could a grid-scale battery earn from energy arbitrage in South Australia (SA1) and New South Wales (NSW1)? This repository answers that with a small, reproducible optimisation study on AEMO 5-minute prices for May–October 2026 (@@n_days@@ days). It compares:

- a **linear program (LP)** with a **mixed-integer linear program (MILP)** that forbids charging and discharging at the same time;
- **daily rolling** solves with a **full-month** solve (an upper bound);
- **5-minute** with **30-minute** price resolution;
- the optimiser with a **one-cycle-per-day heuristic**.

Built with Pyomo + HiGHS. Developed with AI coding agents (Claude Code); the formulation, tests and results were checked by the author. All money is in Australian dollars (A$).

## Key results

Base case: 100 MW / 2 h battery, round-trip efficiency 85%, degradation cost 10 $/MWh discharged, perfect foresight, energy arbitrage only.

@@table_headline@@

Cycles are equivalent full cycles: energy delivered to the grid divided by usable energy capacity. "$/MW/year" scales the @@n_days@@-day total to a year and therefore inherits the price spikes of this particular period (see below).

- **Profit is concentrated in a few extreme days.** With perfect foresight, the five best days give @@sa1_top5_share@@ of SA1 profit and @@nsw1_top5_share@@ of NSW1 profit; the single best day (@@sa1_top1_date@@ in SA1, @@nsw1_top1_date@@ in NSW1) gives @@sa1_top1_share@@ and @@nsw1_top1_share@@. @@sa1_best_month@@ alone gives @@sa1_best_month_share@@ of SA1 profit and @@nsw1_best_month@@ @@nsw1_best_month_share@@ of NSW1 profit; in both months prices reached the market price cap.
- **The optimiser earns @@sa1_milp_vs_heur@@ the heuristic's profit in SA1 and @@nsw1_milp_vs_heur@@ in NSW1.** Part of this is extra cycling: the heuristic makes at most about one cycle a day. Limited to one cycle a day, the MILP still earns @@sa1_cap1_vs_heur@@ (SA1) and @@nsw1_cap1_vs_heur@@ (NSW1) the heuristic's profit, because it chooses *when* to cycle with the whole day in view. (The heuristic carries its state of charge across days and ends the period at @@sa1_heur_end_soc@@ MWh in SA1 and @@nsw1_heur_end_soc@@ MWh in NSW1, against 100 MWh at the start; buying back the difference at the period's mean price would @@sa1_heur_adj_dir@@ its profit by @@sa1_heur_adj@@ (@@sa1_heur_adj_pct@@) in SA1 and @@nsw1_heur_adj_dir@@ it by @@nsw1_heur_adj@@ (@@nsw1_heur_adj_pct@@) in NSW1.)
- **The LP overstates profit by @@sa1_lp_minus_milp@@ (@@sa1_lp_minus_milp_pct@@) in SA1.** In @@sa1_lp_sim@@ five-minute intervals it charges and discharges at the same time, so that efficiency losses dispose of energy: either to absorb more energy at a deeply negative price, or to make room in the battery for even more negative prices later. Either way this can only pay when the price is below the *burn threshold* −κ·rte/(1−rte) = @@burn_threshold@@ $/MWh; the highest price at which the LP did it was @@sa1_lp_sim_maxprice@@. NSW1 prices never fell that low (minimum @@nsw1_min_price@@ $/MWh), so there the LP and MILP give the same profit (difference @@nsw1_lp_minus_milp@@).
- **Solving one day at a time captures @@sa1_daily_capture@@ (SA1) and @@nsw1_daily_capture@@ (NSW1) of the full-month optimum.** The two differ only in the end-of-day condition: the daily solve forces the battery back to 50% at every midnight.
- **Resolution matters:** with 30-minute average prices the MILP earns @@sa1_30min_loss@@ (SA1) and @@nsw1_30min_loss@@ (NSW1) less than with 5-minute prices.
- **Duration:** a 4 h battery earns @@sa1_4h_gain@@ (SA1) and @@nsw1_4h_gain@@ (NSW1) more per MW than a 2 h battery.

These are perfect-foresight, price-taker numbers: an upper bound on energy-arbitrage revenue in this period, not a forecast of what a real battery would earn (see [Limitations](#limitations)).

## Model

For each interval $t$ of length $\Delta t$ hours with price $p_t$ ($/MWh):

| Symbol | Meaning |
|---|---|
| $c_t, d_t \in [0, P]$ | charging and discharging power (MW) |
| $e_t \in [E_{min}, E_{max}]$ | stored energy at the end of interval $t$ (MWh) |
| $E_{init}$ | stored energy at the start and required at the end of each window (MWh) |
| $u_t \in \{0, 1\}$ | MILP only: 1 if the battery may charge in interval $t$ |
| $\eta_c = \eta_d = \sqrt{rte}$ | charging and discharging efficiency |
| $\kappa$ | degradation cost per MWh discharged ($/MWh) |

$$\max \sum_t \Big[\, p_t\,(d_t - c_t)\,\Delta t \;-\; \kappa\, d_t\, \Delta t \,\Big]$$

subject to

$$e_t = e_{t-1} + \eta_c\, c_t\, \Delta t - \frac{d_t\, \Delta t}{\eta_d}, \qquad e_{-1} = E_{init}, \qquad e_{T-1} = E_{init}$$

and, in the MILP only,

$$c_t \le P\, u_t, \qquad d_t \le P\,(1 - u_t).$$

An optional cycle cap adds $\sum_t d_t \Delta t \le N \cdot (E_{max} - E_{min})$ per day (used with $N = 1$ in one scenario).

- **Objective:** the first term is the energy bought and sold at the spot price; the second is a linear stand-in for battery wear, charged per MWh discharged.
- **Why the LP can charge and discharge at once:** in any interval where both $c_t > 0$ and $d_t > 0$, lowering $c_t$ by $x$ and $d_t$ by $rte \cdot x$ leaves the stored energy unchanged, cuts grid purchases by $(1-rte)\,x$ and saves $\kappa \cdot rte \cdot x$ of degradation. At an optimum this cannot be an improvement, so simultaneous operation requires $p_t \le -\kappa\, rte / (1 - rte)$. This is a necessary condition, not a sufficient one. The binary $u_t$ rules simultaneous operation out. The tests check that every simultaneous interval in an LP solution lies below this threshold.
- **Shadow prices:** `model.solve(..., duals=True)` returns the dual of each energy-balance constraint, i.e. the value of one more MWh in storage at the end of that interval. The tests check it against the optimality conditions: it equals $p_t/\eta_c$ while charging below full power and $\eta_d (p_t - \kappa)$ while discharging below full power, and it stays constant while the state of charge is strictly between its limits.
- **Daily rolling:** each calendar day (NEM time, AEST) is solved separately, starting and ending at 50% state of charge. The **full-month** variant solves each month as a single problem with the same start and end condition.
- **Heuristic benchmark:** each day, mark the cheapest intervals needed to fill the battery and the dearest needed to empty it; skip the day if the average spread does not cover losses and degradation; then charge or discharge at full power in marked intervals, in time order, within the energy limits. It does not look at the order of prices within the day, and it makes at most about one cycle a day.

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
| Cycle limit | none (≤ 1 equivalent full cycle per day in sensitivity) | Assumption |
| Energy limits | 0–100% of rated energy | Assumption (rated energy treated as usable; not varied) |
| Start and end-of-day state of charge | 50% | Assumption (not varied; the full-month solve relaxes it within each month) |
| Market price floor | −1,000 $/MWh | National Electricity Rules, clause 3.9.6 |
| Market price cap | 20,300 $/MWh (1 July 2025 – 30 June 2026), 23,200 $/MWh (1 July 2026 – 30 June 2027) | AEMC media release *AEMC updates market price cap for 2026-27*. Both caps appear as the maximum price in the data table above. |
| MILP optimality gap | @@mip_gap@@ (relative) | Solver setting |

## Results

### LP vs MILP: simultaneous charging and discharging

@@table_kappa@@

The lower the degradation cost, the higher the burn threshold and the more often the LP exploits it. With κ = 0 any non-positive price is enough. The interval counts need not be unique, because the LP can have several optimal schedules with the same profit; the profit gap is the robust measure.

What the base-case LP does in the intervals priced below the threshold:

@@table_threshold@@

Discharging at a negative price costs money, so the discharge-only intervals buy something else: room in the battery for even more negative prices later in the day, or the return to 50% by midnight.

![SA1 day with the most LP simultaneous charging and discharging](results/figures/showcase_SA1.png)

On @@show_day@@ the LP charged and discharged at once in @@show_n_sim@@ intervals, all at prices of @@show_max_price@@ $/MWh or lower. The MILP schedule never does both.

### Monthly profit

![Monthly profit by strategy](results/figures/monthly_profit.png)

Daily rolling vs full-month solve (MILP):

@@table_full@@

### Sensitivity

![Sensitivity of annualised profit](results/figures/sensitivity.png)

@@table_sensitivity@@

## Performance

Each daily problem has 288 five-minute intervals. The whole study (@@n_jobs@@ independent jobs) runs in parallel on @@workers@@ processes: @@wall_seconds@@ s wall-clock for @@sum_solver_seconds@@ s of solver time. Timings depend on the machine and on what else it is running.

- **LP vs MILP:** the @@n_days@@ daily SA1 base-case solves took @@t_lp_daily@@ s in total as LPs and @@t_milp_daily@@ s as MILPs (@@t_milp_daily_k0@@ s for the MILP with κ = 0). A whole month as one problem took @@t_full_lp@@ s as an LP and @@t_full_milp@@ s as a MILP.
- **LP algorithm:** solve time in seconds for each month-long LP (8,640–8,928 intervals), same optimum for every algorithm:

@@table_bench@@

HiGHS with default options was slow on @@bench_slow_cases@@, the two months whose prices reached the market price cap; on the other months it took at most @@bench_default_rest_max@@ s. Primal simplex and the interior-point method took @@bench_other_range@@ s on every month, so the LPs here use primal simplex. Why the default struggles on those two months was not investigated; extreme price coefficients are one possible cause. `make bench` reproduces the table.

Other ways to speed up, not tried here: warm starts from the previous day's solution, solving the LP first and switching to the MILP only on days where the LP charges and discharges at once, and coarser time steps where accuracy allows.

## Limitations

- **Perfect foresight:** the battery knows every price of the day in advance. Real operation relies on forecasts, so these results are an upper bound. Because profit is concentrated in a few spike days, the gap to a forecast-based schedule could be large.
- **One six-month window:** May–October 2026 includes cap-level price events in both regions; annualised figures from this window should not be read as typical annual revenue.
- **Price-taker:** a 100 MW battery is assumed not to move prices, which is optimistic in a small region such as SA1.
- **Energy only:** frequency control ancillary services (FCAS), network charges and marginal loss factors are not modelled.
- **Cycling and degradation:** a fixed cost per MWh discharged, with no dependence on depth of discharge or state of charge and no capacity fade. Without a cycle limit the optimiser averages about two equivalent full cycles a day, which is high for a lithium-ion battery whose warranty limits throughput; the one-cycle-per-day scenario shows the cost of such a limit.
- **Fixed daily state-of-charge target:** the full-month comparison shows what this costs. The 50% level and the 0–100% usable range were not varied.
- **30-minute case:** prices are averaged to 30 minutes to measure the value of resolution; settlement in the NEM has been five-minute since October 2021.

## Next steps

Forecast-based scheduling (measure the share of perfect-foresight profit captured), FCAS co-optimisation, price impact, and a mini economic-dispatch model whose energy-balance shadow prices give marginal prices.

## How to run

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
make env    # create .venv and install the pinned packages (requirements.lock)
make all    # download data, run tests, run all experiments, benchmark, figures, README
```

Individual steps, in order: `make data`, `make test`, `make run` (the slowest step), `make bench`, `make report`. `make report` needs the outputs of `make data` and `make run`.

| Path | Contents |
|---|---|
| `src/bess/data.py` | download, validation, 30-minute aggregation |
| `src/bess/model.py` | LP/MILP battery model (Pyomo) |
| `src/bess/heuristic.py` | one-cycle-per-day benchmark |
| `src/bess/backtest.py` | daily rolling and full-horizon runs, metrics |
| `src/bess/run.py` | all experiments, in parallel |
| `src/bess/bench.py` | HiGHS LP algorithm benchmark |
| `src/bess/report.py` | figures and this README |
| `tests/` | pytest: hand-calculated examples, energy balance, bounds, cycle cap, LP vs MILP, shadow prices, data checks |
| `results/` | generated tables and figures |

## Licence

Code: MIT (see `LICENSE`). Price data: © AEMO, not redistributed here; downloaded from AEMO and used under its copyright permissions with attribution.
