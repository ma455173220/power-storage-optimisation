"""M0 smoke test: HiGHS solves a tiny LP and returns the hand-computed duals.

max x + y  s.t.  x + 2y <= 4,  3x + y <= 6,  x, y >= 0
Both constraints bind: x = 1.6, y = 1.2, objective 2.8.
Duals solve  l1 + 3 l2 = 1  and  2 l1 + l2 = 1  ->  l1 = 0.4, l2 = 0.2.
"""
import pyomo.environ as pyo
import pytest


def test_highs_tiny_lp_and_duals():
    m = pyo.ConcreteModel()
    m.x = pyo.Var(bounds=(0, None))
    m.y = pyo.Var(bounds=(0, None))
    m.c1 = pyo.Constraint(expr=m.x + 2 * m.y <= 4)
    m.c2 = pyo.Constraint(expr=3 * m.x + m.y <= 6)
    m.obj = pyo.Objective(expr=m.x + m.y, sense=pyo.maximize)
    m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)
    pyo.SolverFactory("appsi_highs").solve(m)
    assert pyo.value(m.x) == pytest.approx(1.6)
    assert pyo.value(m.y) == pytest.approx(1.2)
    assert pyo.value(m.obj) == pytest.approx(2.8)
    assert m.dual[m.c1] == pytest.approx(0.4)
    assert m.dual[m.c2] == pytest.approx(0.2)
