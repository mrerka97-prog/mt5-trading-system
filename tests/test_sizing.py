"""Баримтын 7-р хэсгийн тооцооны хүснэгтийг шалгана."""
import pytest

from bot.risk.sizing import SymbolSpec, calculate_lot

EURUSD = SymbolSpec("EURUSD", tick_size=0.00001, tick_value=1.0,
                    volume_min=0.01, volume_step=0.01, volume_max=50.0, digits=5)
PIP = EURUSD.pip_size


def test_pip_definitions():
    assert PIP == pytest.approx(0.0001)
    assert EURUSD.pip_value_per_lot == pytest.approx(10.0)


@pytest.mark.parametrize("balance, lot, sl_money, tp_money, risk_pct", [
    (10_000, 0.33, 99.0, 198.0, 0.99),
    (5_000, 0.16, 48.0, 96.0, 0.96),
    (1_000, 0.03, 9.0, 18.0, 0.9),
    (500, 0.01, 3.0, 6.0, 0.6),
])
def test_table(balance, lot, sl_money, tp_money, risk_pct):
    r = calculate_lot(balance, 1.0, 30 * PIP, EURUSD, tp_distance=60 * PIP)
    assert r.lot == pytest.approx(lot)
    assert r.risk_money == pytest.approx(sl_money)
    assert r.reward_money == pytest.approx(tp_money)
    assert r.risk_pct == pytest.approx(risk_pct)


def test_too_small_account_skips():
    r = calculate_lot(100, 1.0, 30 * PIP, EURUSD)
    assert r.lot is None


def test_never_rounds_up_risk():
    for bal in range(200, 20_000, 137):
        r = calculate_lot(bal, 0.5, 30 * PIP, EURUSD)
        if r.lot:
            assert r.risk_money <= bal * 0.005 + 1e-9


def test_dollar_risk_constant_when_sl_changes():
    a = calculate_lot(1_000, 1.0, 30 * PIP, EURUSD)
    b = calculate_lot(1_000, 1.0, 15 * PIP, EURUSD)
    assert b.lot == pytest.approx(0.06)
    assert a.risk_money == b.risk_money == pytest.approx(9.0)


def test_demo_5000_half_percent():
    r = calculate_lot(5_000, 0.5, 30 * PIP, EURUSD)
    assert r.lot == pytest.approx(0.08)
    assert r.risk_money == pytest.approx(24.0)


def test_no_sl_rejected():
    assert calculate_lot(5_000, 0.5, 0, EURUSD).lot is None


def test_jpy_pair_pip():
    usdjpy = SymbolSpec("USDJPY", tick_size=0.001, tick_value=0.67,
                        volume_min=0.01, volume_step=0.01, volume_max=50, digits=3)
    assert usdjpy.pip_size == pytest.approx(0.01)
