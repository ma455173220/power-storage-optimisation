"""Shadow prices of the energy balance (LP): check them against the optimality conditions.

lambda_t = value of one more MWh stored at the end of interval t ($/MWh).
  charging, not at full power      ->  lambda_t = p_t / eta_c          (cost of storing one MWh)
  discharging, not at full power   ->  lambda_t = eta_d * (p_t - kappa) (net value of releasing one MWh)
  charging at full power           ->  p_t / eta_c <= lambda_t
  discharging at full power        ->  eta_d * (p_t - kappa) >= lambda_t
  idle                             ->  eta_d * (p_t - kappa) <= lambda_t <= p_t / eta_c
  SoC strictly between its limits  ->  lambda_t = lambda_{t+1}
"""
import numpy as np
import pytest

from bess import model
from bess.model import Battery


@pytest.fixture
def day():
    rng = np.random.default_rng(3)
    base = np.concatenate([np.full(96, 80.0), -20 - 100 * np.sin(np.linspace(0, np.pi, 96)), np.full(96, 160.0)])
    return base + rng.normal(0, 15, size=288)


def test_shadow_prices_match_optimality_conditions(day):
    b = Battery()
    s = model.solve(day, 1 / 12, b, duals=True)
    lam, p, P, tol = s.balance_dual, day, b.power_mw, 1e-4
    c, d = s.charge, s.discharge
    buy, sell = p / b.eta_c, b.eta_d * (p - b.deg_cost)
    part_c = (c > tol) & (c < P - tol) & (d < tol)
    part_d = (d > tol) & (d < P - tol) & (c < tol)
    full_c = (c > P - tol) & (d < tol)
    full_d = (d > P - tol) & (c < tol)
    idle = (c < tol) & (d < tol)
    assert np.allclose(lam[part_c], buy[part_c], atol=1e-6)
    assert np.allclose(lam[part_d], sell[part_d], atol=1e-6)
    assert np.all(buy[full_c] <= lam[full_c] + 1e-6)
    assert np.all(sell[full_d] >= lam[full_d] - 1e-6)
    assert np.all((sell[idle] <= lam[idle] + 1e-6) & (lam[idle] <= buy[idle] + 1e-6))
    inside = (s.soc > b.e_min + tol) & (s.soc < b.e_max - tol)
    assert np.allclose(lam[:-1][inside[:-1]], lam[1:][inside[:-1]], atol=1e-6)
    assert full_c.any() and full_d.any() and idle.any()  # the day exercises all cases


def test_duals_rejected_for_milp(day):
    with pytest.raises(ValueError):
        model.solve(day, 1 / 12, Battery(), binary=True, duals=True)
