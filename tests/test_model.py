"""Correctness tests for the LP model, the heuristic and the day splitter."""
import numpy as np
import pandas as pd
import pytest

from bess import backtest, heuristic, model
from bess.model import Battery

# A 1 MW / 1 MWh battery with hourly intervals keeps the hand calculations simple.
SMALL = dict(power_mw=1.0, duration_h=1.0, soc_init_frac=0.0)


@pytest.mark.parametrize("rte, kappa, expected", [
    (1.00, 0.0, 90.0),   # buy 1 MWh at 10, sell 1 MWh at 100
    (0.81, 0.0, 71.0),   # eta = 0.9: buy 1 MWh (store 0.9), sell 0.9 * 0.9 = 0.81 MWh at 100
    (0.81, 5.0, 66.95),  # as above minus 5 $/MWh on 0.81 MWh discharged
])
def test_two_period_hand_example(rte, kappa, expected):
    b = Battery(**SMALL, rte=rte, deg_cost=kappa)
    s = model.solve([10.0, 100.0], 1.0, b, e0=0.0, e_end=0.0)
    assert s.profit == pytest.approx(expected)
    assert s.charge == pytest.approx([1.0, 0.0])
    assert s.discharge == pytest.approx([0.0, 0.81 if rte < 1 else 1.0])


def test_two_cycles_beat_heuristic_hand_example():
    # Optimal: charge at 10, sell at 100, charge at 20, sell at 90 -> 90 + 70 = 160.
    # Heuristic (one cheapest + one dearest interval per day) only does the first cycle -> 90.
    b = Battery(**SMALL, rte=1.0, deg_cost=0.0)
    prices = [10.0, 100.0, 20.0, 90.0]
    assert model.solve(prices, 1.0, b, e0=0.0, e_end=0.0).profit == pytest.approx(160.0)
    assert heuristic.day_schedule(prices, 1.0, b, e0=0.0).profit == pytest.approx(90.0)


@pytest.fixture
def random_day():
    rng = np.random.default_rng(0)
    return rng.normal(60, 80, size=288)  # includes negative prices


@pytest.mark.parametrize("binary", [False, True])
def test_energy_balance_and_bounds(random_day, binary):
    b = Battery()
    dt = 1 / 12
    s = model.solve(random_day, dt, b, binary=binary)
    prev = np.concatenate([[b.e_init], s.soc[:-1]])
    assert s.soc == pytest.approx(prev + b.eta_c * s.charge * dt - s.discharge * dt / b.eta_d, abs=1e-6)
    assert s.soc[-1] == pytest.approx(b.e_init, abs=1e-6)
    tol = 1e-6
    assert s.charge.min() >= -tol and s.charge.max() <= b.power_mw + tol
    assert s.discharge.min() >= -tol and s.discharge.max() <= b.power_mw + tol
    assert s.soc.min() >= b.e_min - tol and s.soc.max() <= b.e_max + tol
    # reported profit equals the objective recomputed from the schedule
    assert s.profit == pytest.approx(np.sum(random_day * (s.discharge - s.charge) * dt)
                                     - b.deg_cost * np.sum(s.discharge) * dt)


@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize("price", [0.0, 50.0, 300.0])
def test_constant_non_negative_price_cannot_make_money(price, binary):
    # Any cycle loses energy (rte < 1) and pays degradation, so the best is to do nothing.
    s = model.solve(np.full(48, price), 0.5, Battery(), binary=binary)
    assert s.profit <= 1e-6


def test_constant_negative_price_can_make_money():
    # Being paid to consume makes losses valuable: the battery absorbs energy and wastes it.
    s = model.solve(np.full(48, -100.0), 0.5, Battery(deg_cost=0.0))
    assert s.profit > 0


def test_heuristic_respects_bounds_and_skips_flat_days(random_day):
    b = Battery()
    s = heuristic.day_schedule(random_day, 1 / 12, b, e0=b.e_init)
    assert s.soc.min() >= b.e_min - 1e-9 and s.soc.max() <= b.e_max + 1e-9
    assert not s.simultaneous.any()
    flat = heuristic.day_schedule(np.full(288, 50.0), 1 / 12, b, e0=b.e_init)
    assert flat.profit == 0 and flat.charge.sum() == 0


def test_split_days_uses_interval_start():
    t = pd.date_range("2026-05-01 00:05", periods=2 * 288, freq="5min")
    df = pd.DataFrame({"interval_end": t, "rrp": 1.0})
    days = backtest.split_days(df, 1 / 12)
    assert [d for d, _ in days] == [pd.Timestamp("2026-05-01"), pd.Timestamp("2026-05-02")]
    assert days[0][1]["interval_end"].iloc[-1] == pd.Timestamp("2026-05-02 00:00")
    with pytest.raises(ValueError):
        backtest.split_days(df.iloc[:-1], 1 / 12)


@pytest.mark.parametrize("binary", [False, True])
def test_daily_cycle_cap_is_respected_and_costs_profit(random_day, binary):
    free = model.solve(random_day, 1 / 12, Battery(), binary=binary)
    capped_batt = Battery(max_cycles_per_day=1.0)
    capped = model.solve(random_day, 1 / 12, capped_batt, binary=binary)
    usable = capped_batt.e_max - capped_batt.e_min
    assert free.discharge.sum() / 12 > usable  # the cap binds on this day
    assert capped.discharge.sum() / 12 <= usable + 1e-6
    assert capped.profit <= free.profit + 1e-6
