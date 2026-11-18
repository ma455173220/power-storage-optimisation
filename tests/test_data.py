"""Unit tests for data loading and validation (synthetic data, no network)."""
import pandas as pd
import pytest

from bess import data


def make_frame(start_end="2026-05-01 00:05", n=12, rrp=50.0, region="SA1"):
    t = pd.date_range(start_end, periods=n, freq="5min")
    return pd.DataFrame({"interval_end": t, "region": region, "demand_mw": 1000.0,
                         "rrp": rrp, "periodtype": "TRADE"})


def test_clean_frame_passes():
    rep = data.validate(make_frame())
    assert rep.ok and rep.n_rows == rep.n_expected == 12


def test_gap_is_reported():
    df = make_frame().drop(index=5).reset_index(drop=True)
    rep = data.validate(df)
    assert not rep.ok
    assert rep.missing == [pd.Timestamp("2026-05-01 00:30")]


def test_gap_at_month_edge_needs_explicit_bounds():
    df = make_frame().iloc[1:]  # first interval (00:05) missing
    assert data.validate(df).ok  # cannot be seen from the data alone
    rep = data.validate(df, pd.Timestamp("2026-05-01 00:05"), df["interval_end"].max())
    assert rep.missing == [pd.Timestamp("2026-05-01 00:05")]


def test_duplicate_is_reported():
    df = make_frame()
    df = pd.concat([df, df.iloc[[3]]], ignore_index=True)
    rep = data.validate(df)
    assert rep.duplicates == [df["interval_end"].iloc[3]]


def test_price_limits_by_financial_year():
    df = make_frame("2026-06-30 23:55", n=3, rrp=21000.0)  # ends 23:55, 00:00 (FY25-26), 00:05 (FY26-27)
    rep = data.validate(df)
    # 21,000 is above the 2025-26 cap (20,300) but below the 2026-27 cap (23,200).
    assert [ts for ts, _ in rep.out_of_range] == [pd.Timestamp("2026-06-30 23:55"),
                                                  pd.Timestamp("2026-07-01 00:00")]
    df.loc[0, "rrp"] = -1000.0  # exactly the floor is allowed
    df.loc[1, "rrp"] = -1000.01
    rep = data.validate(df)
    assert [ts for ts, _ in rep.out_of_range] == [pd.Timestamp("2026-07-01 00:00")]


def test_financial_year_boundary_uses_interval_start():
    t = pd.Series(pd.to_datetime(["2026-07-01 00:00", "2026-07-01 00:05"]))
    assert list(data.financial_year(t)) == ["2025-26", "2026-27"]


def test_nan_and_period_type_are_reported():
    df = make_frame()
    df.loc[2, "rrp"] = float("nan")
    df.loc[4, "periodtype"] = "OTHER"
    rep = data.validate(df)
    assert rep.n_nan == 1 and rep.n_not_trade == 1 and not rep.ok


def test_month_bounds():
    assert data.month_bounds("202602") == (pd.Timestamp("2026-02-01 00:05"),
                                           pd.Timestamp("2026-03-01 00:00"))


def test_load_csv_parses_aemo_format(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("REGION,SETTLEMENTDATE,TOTALDEMAND,RRP,PERIODTYPE\n"
                 "SA1,2026/10/01 00:10:00,1320.82,101.02,TRADE\n"
                 "SA1,2026/10/01 00:05:00,1299.03,-119.62,TRADE\n")
    df = data.load_csv(p)
    assert list(df["interval_end"]) == [pd.Timestamp("2026-10-01 00:05"), pd.Timestamp("2026-10-01 00:10")]
    assert list(df["rrp"]) == [-119.62, 101.02]


def test_to_30min_averages_complete_periods_only():
    df = make_frame(n=12)  # ends 00:05 ... 01:00 -> two complete 30-min periods
    df["rrp"] = [1, 2, 3, 4, 5, 6, 10, 10, 10, 10, 10, 40]
    out = data.to_30min(df)
    assert list(out["interval_end"]) == [pd.Timestamp("2026-05-01 00:30"), pd.Timestamp("2026-05-01 01:00")]
    assert list(out["rrp"]) == pytest.approx([3.5, 15.0])
    assert len(data.to_30min(df.iloc[:-1])) == 1  # incomplete second period dropped
