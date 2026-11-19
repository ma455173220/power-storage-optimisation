"""Download, load and validate AEMO NEM 5-minute price and demand data.

Source: AEMO "Aggregated price and demand data", one CSV per region per month:
    https://www.aemo.com.au/aemo/data/nem/priceanddemand/PRICE_AND_DEMAND_YYYYMM_REGION.csv
SETTLEMENTDATE is the END of each 5-minute interval, in NEM time (AEST, UTC+10,
no daylight saving). RRP is the regional reference price in $/MWh.

Run `python -m bess.data` to download (cached in data/raw/), validate and write
results/data_summary.csv.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

URL = "https://www.aemo.com.au/aemo/data/nem/priceanddemand/PRICE_AND_DEMAND_{yyyymm}_{region}.csv"
RAW_DIR = Path("data/raw")
RESULTS_DIR = Path("results")
REGIONS = ("SA1", "NSW1")
MONTHS = ("202605", "202606", "202607", "202608", "202609", "202610")
INTERVAL = pd.Timedelta(minutes=5)

# NEM market price limits in $/MWh by financial year (1 July to 30 June):
# (market floor price MPF, market price cap MPC).
# - MPF -1,000 $/MWh: National Electricity Rules clause 3.9.6 (unchanged in both years).
# - MPC 20,300 $/MWh (1 July 2025 - 30 June 2026) and 23,200 $/MWh (1 July 2026 -
#   30 June 2027): AEMC media release "AEMC updates market price cap for 2026-27"
#   (read 2026-11-19).
# These limits are only used as a sanity bound when validating the data.
PRICE_LIMITS = {
    "2025-26": (-1000.0, 20300.0),
    "2026-27": (-1000.0, 23200.0),
}


def financial_year(interval_end: pd.Series) -> pd.Series:
    """NEM financial year label ('2025-26') of each interval, from its START time.

    The interval ending 1 July 00:00 started on 30 June 23:55, so it belongs to the
    earlier financial year.
    """
    start = interval_end - INTERVAL
    first = start.dt.year.where(start.dt.month >= 7, start.dt.year - 1)
    return first.astype(str) + "-" + ((first + 1) % 100).astype(str).str.zfill(2)


def raw_path(region: str, yyyymm: str, raw_dir: Path = RAW_DIR) -> Path:
    return raw_dir / f"PRICE_AND_DEMAND_{yyyymm}_{region}.csv"


def download(region: str, yyyymm: str, raw_dir: Path = RAW_DIR) -> Path:
    """Download one month for one region unless it is already cached."""
    path = raw_path(region, yyyymm, raw_dir)
    if path.exists() and path.stat().st_size > 0:
        return path
    raw_dir.mkdir(parents=True, exist_ok=True)
    url = URL.format(yyyymm=yyyymm, region=region)
    # AEMO serves these files to curl; Python's urllib is refused (HTTP 403).
    subprocess.run(["curl", "-sSf", "-o", str(path), url], check=True)
    return path


def load_csv(path: Path) -> pd.DataFrame:
    """Read one AEMO file into tidy columns, sorted by interval end."""
    df = pd.read_csv(path)
    out = pd.DataFrame({
        "interval_end": pd.to_datetime(df["SETTLEMENTDATE"], format="%Y/%m/%d %H:%M:%S"),
        "region": df["REGION"].astype(str),
        "demand_mw": df["TOTALDEMAND"].astype(float),
        "rrp": df["RRP"].astype(float),
        "periodtype": df["PERIODTYPE"].astype(str),
    })
    return out.sort_values("interval_end").reset_index(drop=True)


def load(region: str, months=MONTHS, raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    frames = [load_csv(raw_path(region, m, raw_dir)) for m in months]
    return pd.concat(frames, ignore_index=True).sort_values("interval_end").reset_index(drop=True)


@dataclass
class ValidationReport:
    region: str
    n_rows: int
    first_end: pd.Timestamp
    last_end: pd.Timestamp
    n_expected: int
    missing: list = field(default_factory=list)      # interval ends absent from the data
    duplicates: list = field(default_factory=list)   # interval ends that appear more than once
    out_of_range: list = field(default_factory=list) # (interval end, rrp) outside [MPF, MPC]
    n_nan: int = 0
    n_not_trade: int = 0

    @property
    def ok(self) -> bool:
        return not (self.missing or self.duplicates or self.out_of_range or self.n_nan or self.n_not_trade)


def validate(df: pd.DataFrame, start_end: pd.Timestamp | None = None,
             last_end: pd.Timestamp | None = None) -> ValidationReport:
    """Check continuity, duplicates, missing values, period type and price limits.

    start_end / last_end: the first and last interval ends that SHOULD be present
    (default: first and last in the data). Pass them to detect gaps at the edges.
    """
    region = ",".join(sorted(df["region"].unique()))
    t = df["interval_end"]
    start_end = t.min() if start_end is None else start_end
    last_end = t.max() if last_end is None else last_end
    expected = pd.date_range(start_end, last_end, freq=INTERVAL)
    present = pd.Index(t.unique())
    missing = list(expected.difference(present))
    dup_mask = t.duplicated(keep=False)
    duplicates = sorted(t[dup_mask].unique())

    fy = financial_year(t)
    unknown = sorted(set(fy) - set(PRICE_LIMITS))
    if unknown:
        raise ValueError(f"No price limits defined for financial year(s) {unknown}")
    floor = fy.map(lambda y: PRICE_LIMITS[y][0])
    cap = fy.map(lambda y: PRICE_LIMITS[y][1])
    bad = (df["rrp"] < floor) | (df["rrp"] > cap)
    out_of_range = list(zip(t[bad], df.loc[bad, "rrp"]))

    return ValidationReport(
        region=region,
        n_rows=len(df),
        first_end=t.min(),
        last_end=t.max(),
        n_expected=len(expected),
        missing=missing,
        duplicates=duplicates,
        out_of_range=out_of_range,
        n_nan=int(df[["demand_mw", "rrp"]].isna().any(axis=1).sum()),
        n_not_trade=int((df["periodtype"] != "TRADE").sum()),
    )


def month_bounds(yyyymm: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last interval END of a calendar month (00:05 on day 1 to 00:00 next month)."""
    start = pd.Timestamp(f"{yyyymm[:4]}-{yyyymm[4:]}-01")
    return start + INTERVAL, start + pd.offsets.MonthBegin(1)


def to_30min(df: pd.DataFrame) -> pd.DataFrame:
    """Average six 5-minute prices into 30-minute periods (period labelled by its end).

    Intervals ending 00:05 ... 00:30 form the period ending 00:30. Only complete
    periods (exactly six intervals) are kept.
    """
    g = df.assign(period_end=df["interval_end"].dt.ceil("30min")).groupby("period_end")
    out = g.agg(rrp=("rrp", "mean"), demand_mw=("demand_mw", "mean"), n=("rrp", "size")).reset_index()
    out = out[out["n"] == 6].drop(columns="n").rename(columns={"period_end": "interval_end"})
    out["region"] = df["region"].iloc[0]
    return out.reset_index(drop=True)


def summarise(df: pd.DataFrame) -> dict:
    r = df["rrp"]
    return {
        "rows": len(df),
        "rrp_mean": r.mean(),
        "rrp_min": r.min(),
        "rrp_max": r.max(),
        "share_negative_pct": 100 * (r < 0).mean(),
    }


def main() -> int:
    for region in REGIONS:
        for m in MONTHS:
            download(region, m)
    rows, all_ok = [], True
    for region in REGIONS:
        for m in MONTHS:
            df = load_csv(raw_path(region, m))
            first, last = month_bounds(m)
            rep = validate(df, first, last)
            all_ok &= rep.ok
            rows.append({"region": region, "month": m, **summarise(df),
                         "expected_rows": rep.n_expected, "missing": len(rep.missing),
                         "duplicates": len(rep.duplicates), "out_of_range": len(rep.out_of_range),
                         "nan": rep.n_nan, "not_trade": rep.n_not_trade})
            for ts in rep.missing:
                print(f"GAP {region} {m}: interval ending {ts} missing")
    out = pd.DataFrame(rows)
    RESULTS_DIR.mkdir(exist_ok=True)
    out.to_csv(RESULTS_DIR / "data_summary.csv", index=False, float_format="%.2f")
    print(out.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    print("All checks passed." if all_ok else "Some checks FAILED: see table above.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
