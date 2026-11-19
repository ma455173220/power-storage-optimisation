"""Make the figures and render README.md from README.template.md.

    python -m bess.report

Every number in the README is filled in here from the files in results/, so the
README cannot drift away from the latest run. Placeholders look like @@name@@.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from . import data  # noqa: E402
from .run import BASE, SCENARIOS  # noqa: E402

R = data.RESULTS_DIR
FIG = R / "figures"
# Categorical colours (fixed entity -> colour mapping, validated for colour-vision deficiency).
COL = {"milp": "#2a78d6", "lp": "#eb6834", "heuristic": "#1baf7a", "full": "#eda100"}
LABEL = {"heuristic": "Heuristic", "lp": "LP, daily", "milp": "MILP, daily", "full": "MILP, full month"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "font.size": 10, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
    "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "#fcfcfb",
    "axes.facecolor": "#fcfcfb", "savefig.facecolor": "#fcfcfb", "legend.frameon": False,
})


def money_m(x: float) -> str:
    return f"${x / 1e6:,.2f} M"


def money_k(x: float) -> str:
    return f"${x / 1e3:,.0f}k"


def pct(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}%"


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def load():
    s = pd.read_csv(R / "summary.csv")
    full = pd.read_csv(R / "full_horizon.csv")
    monthly = pd.read_csv(R / "monthly.csv", dtype={"month": str})
    full["month"] = full["month"].astype(str)
    return s, full, monthly


def get(s, region, scenario, method, col="profit"):
    row = s[(s.region == region) & (s.scenario == scenario) & (s.method == method)]
    assert len(row) == 1, (region, scenario, method)
    return row.iloc[0][col]


# ---------------------------------------------------------------- figures
def fig_showcase():
    sc = pd.read_csv(R / "showcase_days.csv", parse_dates=["interval_end"])
    g = sc[sc.region == "SA1"]
    day = g["date"].iloc[0][:10]
    lp, milp = g[g.method == "lp"], g[g.method == "milp"]
    fig, ax = plt.subplots(3, 1, figsize=(9, 7.5), sharex=True, height_ratios=[1, 1.2, 1])
    ax[0].plot(lp.interval_end, lp.rrp, color=INK2, lw=1.2)
    ax[0].axhline(0, color=INK2, lw=0.8)
    ax[0].axhline(BASE.burn_threshold, color=INK2, lw=0.8, ls="--")
    ax[0].annotate(f"burn threshold {BASE.burn_threshold:.1f} $/MWh", (lp.interval_end.iloc[2], BASE.burn_threshold),
                   textcoords="offset points", xytext=(0, 4), color=INK2, fontsize=8)
    ax[0].set_ylabel("Price ($/MWh)")
    ax[0].set_title(f"SA1, {day}: day with the most LP simultaneous charge/discharge", loc="left", color=INK)
    for name, d in (("lp", lp), ("milp", milp)):
        ax[1].step(d.interval_end, d.discharge_mw - d.charge_mw, where="post", color=COL[name], lw=1.6,
                   label=LABEL[name] + " (net export)")
    sim = (lp.charge_mw > 1e-6) & (lp.discharge_mw > 1e-6)
    ax[1].scatter(lp.interval_end[sim], (lp.discharge_mw - lp.charge_mw)[sim], s=14, color=COL["lp"],
                  edgecolor="#fcfcfb", linewidth=1, zorder=3, label="LP charges and discharges at once")
    ax[1].set_ylabel("Net export (MW)\n+ discharge / − charge")
    ax[1].legend(loc="lower right", fontsize=8)
    for name, d in (("lp", lp), ("milp", milp)):
        ax[2].plot(d.interval_end, d.soc_mwh, color=COL[name], lw=1.6, label=LABEL[name])
    ax[2].set_ylabel("Stored energy (MWh)")
    ax[2].legend(loc="lower right", fontsize=8)
    ax[2].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax[2].set_xlabel("Interval end (AEST)")
    fig.tight_layout()
    fig.savefig(FIG / "showcase_SA1.png", dpi=150)
    plt.close(fig)
    return day, int(sim.sum()), float(lp.rrp[sim].max()) if sim.any() else float("nan")


def fig_monthly(monthly, full):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=False)
    months = list(data.MONTHS)
    w = 0.2
    for ax, region in zip(axes, data.REGIONS):
        series = {m: monthly[(monthly.region == region) & (monthly.scenario == "base") & (monthly.method == m)]
                  .set_index("month")["profit"] for m in ("heuristic", "lp", "milp")}
        series["full"] = full[(full.region == region) & (full.method == "milp")].set_index("month")["profit"]
        for i, (name, ser) in enumerate(series.items()):
            x = [k + (i - 1.5) * w for k in range(len(months))]
            ax.bar(x, [ser[m] / 1e6 for m in months], width=w * 0.9, color=COL[name], label=LABEL[name])
        ax.set_xticks(range(len(months)), [pd.Timestamp(m + "01").strftime("%b") for m in months])
        ax.set_title(region, loc="left", color=INK)
        ax.set_ylabel("Profit ($ million)")
    axes[0].legend(fontsize=8, loc="upper right")
    fig.suptitle("Monthly profit, 100 MW / 2 h battery, 2026", x=0.01, ha="left", color=INK)
    fig.tight_layout()
    fig.savefig(FIG / "monthly_profit.png", dpi=150)
    plt.close(fig)


SENS_ORDER = [("base", "Base: 2 h, 5-min, rte 85%, κ 10"), ("base_30min", "30-min prices"),
              ("dur_4h", "4 h duration"), ("rte_0.80", "rte 80%"), ("rte_0.90", "rte 90%"),
              ("kappa_0", "κ = 0 $/MWh"), ("kappa_5", "κ = 5 $/MWh"), ("kappa_20", "κ = 20 $/MWh")]


def fig_sensitivity(s):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharex=True)
    for ax, region in zip(axes, data.REGIONS):
        vals = [get(s, region, sc, "milp", "profit_per_mw_year") / 1e3 for sc, _ in SENS_ORDER]
        y = range(len(vals))[::-1]
        ax.barh(list(y), vals, color=COL["milp"], height=0.6)
        for yi, v in zip(y, vals):
            ax.annotate(f"{v:,.0f}", (v, yi), textcoords="offset points", xytext=(3, -3), fontsize=8, color=INK)
        ax.set_yticks(list(y), [lab for _, lab in SENS_ORDER] if region == data.REGIONS[0] else [""] * len(vals))
        ax.set_title(region, loc="left", color=INK)
        ax.set_xlabel("MILP profit ($k per MW per year)")
    fig.suptitle("Sensitivity of annualised profit (MILP, daily rolling)", x=0.01, ha="left", color=INK)
    fig.tight_layout()
    fig.savefig(FIG / "sensitivity.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- README values
def values(s, full, monthly, show) -> dict:
    v = {}
    meta = json.loads((R / "run_meta.json").read_text())
    bench = pd.read_csv(R / "benchmark.csv")
    dsum = pd.read_csv(R / "data_summary.csv", dtype={"month": str})
    v["n_days"] = str(int(get(s, "SA1", "base", "milp", "days")))
    v["burn_threshold"] = f"{BASE.burn_threshold:.2f}"

    # headline table
    rows = []
    for region in data.REGIONS:
        fh = full[(full.region == region) & (full.method == "milp")]["profit"].sum()
        for m in ("heuristic", "lp", "milp"):
            rows.append({"Region": region, "Strategy": LABEL[m],
                         "Profit (6 months)": money_m(get(s, region, "base", m)),
                         "$/MW/year": money_k(get(s, region, "base", m, "profit_per_mw_year")),
                         "Cycles/day": f"{get(s, region, 'base', m, 'cycles_per_day'):.2f}",
                         "Simultaneous charge+discharge (intervals)": int(get(s, region, "base", m, "n_simultaneous"))})
        n_days = get(s, region, "base", "milp", "days")
        rows.append({"Region": region, "Strategy": LABEL["full"], "Profit (6 months)": money_m(fh),
                     "$/MW/year": money_k(fh / BASE.power_mw / (n_days / 365)), "Cycles/day": "–",
                     "Simultaneous charge+discharge (intervals)": int(full[(full.region == region) & (full.method == "milp")]["n_simultaneous"].sum())})
    v["table_headline"] = md_table(pd.DataFrame(rows))

    for region in data.REGIONS:
        r = region.lower()
        milp, lp, heur = (get(s, region, "base", m) for m in ("milp", "lp", "heuristic"))
        fh = full[(full.region == region) & (full.method == "milp")]["profit"].sum()
        v[f"{r}_milp_vs_heur"] = f"{milp / heur:.2f}×"
        v[f"{r}_lp_minus_milp"] = f"${lp - milp:,.0f}"
        v[f"{r}_lp_minus_milp_pct"] = pct(100 * (lp - milp) / milp, 2)
        v[f"{r}_lp_sim"] = f"{int(get(s, region, 'base', 'lp', 'n_simultaneous')):,}"
        mx = get(s, region, "base", "lp", "max_price_simultaneous")
        v[f"{r}_lp_sim_maxprice"] = "none" if pd.isna(mx) else f"{mx:.2f} $/MWh"
        v[f"{r}_daily_capture"] = pct(100 * milp / fh)
        v[f"{r}_30min_loss"] = pct(100 * (1 - get(s, region, "base_30min", "milp") / milp))
        v[f"{r}_4h_gain"] = pct(100 * (get(s, region, "dur_4h", "milp") / milp - 1))
        v[f"{r}_min_price"] = f"{data.load(region)['rrp'].min():,.2f}"
        v[f"{r}_n_below_thr"] = f"{int((data.load(region)['rrp'] < BASE.burn_threshold).sum()):,}"

    # LP vs MILP by kappa
    rows = []
    for region in data.REGIONS:
        for sc, k in (("kappa_0", 0), ("kappa_5", 5), ("base", 10), ("kappa_20", 20)):
            b = SCENARIOS[sc][0]
            lp, milp = get(s, region, sc, "lp"), get(s, region, sc, "milp")
            mx = get(s, region, sc, "lp", "max_price_simultaneous")
            rows.append({"Region": region, "κ ($/MWh)": k, "Burn threshold ($/MWh)": f"{b.burn_threshold + 0.0:.2f}",
                         "LP simultaneous intervals": f"{int(get(s, region, sc, 'lp', 'n_simultaneous')):,}",
                         "Highest price among them": "–" if pd.isna(mx) else f"{mx:.2f}",
                         "LP − MILP profit": f"${lp - milp:,.0f} ({100 * (lp - milp) / milp:.2f}%)"})
    v["table_kappa"] = md_table(pd.DataFrame(rows))

    # sensitivity table
    rows = []
    for sc, lab in SENS_ORDER:
        rows.append({"Scenario": lab, **{f"{r} $/MW/year": money_k(get(s, r, sc, "milp", "profit_per_mw_year"))
                                         for r in data.REGIONS},
                     **{f"{r} cycles/day": f"{get(s, r, sc, 'milp', 'cycles_per_day'):.2f}" for r in data.REGIONS}})
    v["table_sensitivity"] = md_table(pd.DataFrame(rows))

    # data table
    dt = dsum.assign(Month=dsum["month"].map(lambda m: pd.Timestamp(m + "01").strftime("%b %Y")))
    dt = dt[["region", "Month", "rows", "missing", "duplicates", "out_of_range", "rrp_mean", "rrp_min", "rrp_max",
             "share_negative_pct"]]
    dt.columns = ["Region", "Month", "Intervals", "Missing", "Duplicates", "Outside MPF–MPC",
                  "Mean ($/MWh)", "Min", "Max", "Negative (%)"]
    for c in ["Mean ($/MWh)", "Min", "Max"]:
        dt[c] = dt[c].map(lambda x: f"{x:,.2f}")
    dt["Negative (%)"] = dt["Negative (%)"].map(lambda x: f"{x:.1f}")
    v["table_data"] = md_table(dt)
    v["n_intervals_total"] = f"{int(dsum['rows'].sum()):,}"

    # full horizon table
    fh = full[full.method == "milp"].copy()
    fh["Month"] = fh["month"].map(lambda m: pd.Timestamp(m + "01").strftime("%b"))
    fh["Daily rolling"] = fh["daily_rolling_profit"].map(money_m)
    fh["Full month"] = fh["profit"].map(money_m)
    fh["Daily / full"] = (100 * fh["daily_rolling_profit"] / fh["profit"]).map(lambda x: f"{x:.1f}%")
    v["table_full"] = md_table(fh[["region", "Month", "Daily rolling", "Full month", "Daily / full"]]
                               .rename(columns={"region": "Region"}))

    # performance
    b = bench.copy()
    b["Time (s)"] = b["seconds"].map(lambda x: f"{x:.1f}")
    b["Profit"] = b["profit"].map(lambda x: f"${x:,.2f}")
    v["bench_case"] = b["case"].iloc[0]
    v["table_bench"] = md_table(b[["algorithm", "Time (s)", "Profit"]].rename(columns={"algorithm": "HiGHS algorithm"}))
    v["bench_speedup"] = f"{b['seconds'].iloc[0] / b['seconds'].iloc[1]:.0f}×"
    v["wall_seconds"] = f"{meta['wall_seconds']:.0f}"
    v["sum_solver_seconds"] = f"{meta['sum_solver_seconds']:.0f}"
    v["workers"] = str(meta["workers"])
    v["n_jobs"] = str(meta["n_daily_jobs"] + meta["n_month_jobs"])
    v["mip_gap"] = f"{meta['mip_gap']:g}"

    v["show_day"], v["show_n_sim"] = show[0], str(show[1])
    v["show_max_price"] = f"{show[2]:.2f}"
    return v


def render(v: dict, template=Path("README.template.md"), out=Path("README.md")):
    text = template.read_text()
    missing = sorted(set(re.findall(r"@@(\w+)@@", text)) - set(v))
    if missing:
        raise KeyError(f"No value for placeholders: {missing}")
    out.write_text(re.sub(r"@@(\w+)@@", lambda m: str(v[m.group(1)]), text))


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    s, full, monthly = load()
    show = fig_showcase()
    fig_monthly(monthly, full)
    fig_sensitivity(s)
    render(values(s, full, monthly, show))
    print("Wrote README.md and", ", ".join(p.name for p in sorted(FIG.glob("*.png"))))


if __name__ == "__main__":
    main()
