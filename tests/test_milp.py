"""LP vs MILP: simultaneous charging and discharging."""
import numpy as np
import pytest

from bess import model
from bess.model import Battery


def test_full_battery_at_negative_price_hand_example():
    # 1 MW / 1 MWh, full at the start and required to end full, one hour at -100 $/MWh.
    # LP: charge 1 MWh (stores 0.9) and discharge 0.81 MWh (removes 0.9): SoC unchanged,
    #     net purchase 0.19 MWh at -100 -> profit 19. MILP cannot do both -> profit 0.
    b = Battery(power_mw=1.0, duration_h=1.0, rte=0.81, deg_cost=0.0, soc_init_frac=1.0)
    lp = model.solve([-100.0], 1.0, b)
    milp = model.solve([-100.0], 1.0, b, binary=True)
    assert lp.profit == pytest.approx(19.0)
    assert lp.charge == pytest.approx([1.0]) and lp.discharge == pytest.approx([0.81])
    assert milp.profit == pytest.approx(0.0, abs=1e-9)


@pytest.fixture
def volatile_day():
    rng = np.random.default_rng(1)
    return rng.normal(0, 150, size=288)  # many deeply negative prices, rapidly alternating


@pytest.fixture
def solar_day():
    """Night 50 $/MWh, a 8-hour midday trough from -10 down to -200 and back, evening 150.

    The battery fills early in the trough, then stays full while prices are still
    negative: the situation in which an LP can profit from wasting energy.
    """
    midday = -10 - 190 * np.sin(np.linspace(0, np.pi, 96))
    return np.concatenate([np.full(96, 50.0), midday, np.full(96, 150.0)])


def test_milp_never_charges_and_discharges_at_once(volatile_day):
    s = model.solve(volatile_day, 1 / 12, Battery(), binary=True)
    assert not s.simultaneous.any()


@pytest.mark.parametrize("kappa", [0.0, 5.0, 10.0, 20.0])
def test_lp_simultaneous_only_below_burn_threshold(solar_day, kappa):
    b = Battery(deg_cost=kappa)
    lp = model.solve(solar_day, 1 / 12, b)
    assert lp.simultaneous.any()  # the effect is present on this day
    assert solar_day[lp.simultaneous].max() <= b.burn_threshold + 1e-6
    milp = model.solve(solar_day, 1 / 12, b, binary=True)
    assert not milp.simultaneous.any()
    assert lp.profit > milp.profit  # the LP gains from wasting energy


def test_lp_is_a_relaxation_of_milp(volatile_day):
    b = Battery()
    assert model.solve(volatile_day, 1 / 12, b).profit >= \
        model.solve(volatile_day, 1 / 12, b, binary=True).profit - 1e-6


def test_burn_threshold_value():
    assert Battery(rte=0.85, deg_cost=10.0).burn_threshold == pytest.approx(-56.6667, abs=1e-3)
