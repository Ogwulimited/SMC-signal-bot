"""CT engine smoke tests on synthetic data (no real data, no exam years)."""
import pandas as pd

from src import config
from src.research.engine import ct_engine as ct
from src.research.engine import simulate_orders as so
from src.research.engine.run_ct import run_engine, set_pair_settings
from src.research.poison import make_synthetic_m15


def _run(weeks=52, seed=42):
    set_pair_settings("eurusd")
    m15 = make_synthetic_m15(weeks=weeks, seed=seed, start="2016-01-04")
    rec, log = run_engine(m15)
    return m15, rec, log


def test_ct_runs_and_orders_are_well_formed():
    m15, rec, log = _run()
    assert len(log.items) > 0
    for o in rec.ctorders:
        assert o["side"] in ("buy", "sell")
        assert o["entry"] != o["stop"]
        risk = abs(o["entry"] - o["stop"])
        assert risk > 0
        if o["side"] == "buy":
            assert o["stop"] < o["entry"]
        else:
            assert o["stop"] > o["entry"]
        assert o["leg"] == "zone"
        assert o["fill"] == "limit"


def test_ct_simulation_produces_scorecard():
    m15, rec, log = _run()
    recs = so.simulate_all(list(rec.ctorders), m15, "eurusd")
    df = pd.DataFrame(recs)
    if len(df):
        assert set(df["target_mode"].unique()) <= {"static", "liquidity"}
        filled = df[df["status"] == "filled"]
        for _, r in filled.iterrows():
            assert r["risk_r"] > 0


def test_ct_does_not_import_simulator():
    import pathlib
    src = pathlib.Path("src/research/engine/ct_engine.py").read_text()
    assert "simulate_orders" not in src
    assert "tradesim" not in src


def test_liquidity_is_beyond_three_r_and_order_exists():
    from types import SimpleNamespace
    from src.research.lookahead_guard import DecisionLog
    engine = ct.CTEngine(DecisionLog())
    engine._sw_hi = [1.02, 1.04, 1.05]
    engine._sw_lo = [0.95, 0.96, 0.98]
    assert engine._liq(1.0, 1.03, False) == [1.04, 1.05]
    assert engine._liq(1.0, 0.97, True) == [0.96, 0.95]
    now = pd.Timestamp('2016-02-01', tz='UTC')
    box = SimpleNamespace(low=0.99, high=1.0, candle_time=now)
    o = engine._place('buy', False, box, 1.0, 0.99, .01, now,
                      None, None, 'H1-1', ['FVG'], 'ob')
    assert o['id'] == 'CT1'
    assert o['stop'] < o['entry'] < o['ceiling']
    assert o['liq'] == [1.04, 1.05]


def test_final_bar_touch_is_observed_before_h1_cancellation():
    from types import SimpleNamespace
    from src.research.lookahead_guard import DecisionLog, Bar
    from src.research.engine.bias import htf_bias
    engine = ct.CTEngine(DecisionLog())
    engine.bias['D1'].bias = engine.bias['H4'].bias = 'bull'
    now = pd.Timestamp('2016-02-01', tz='UTC')
    box = SimpleNamespace(low=0.99, high=1.0, candle_time=now)
    o = engine._place('buy', False, box, 1.0, 0.99, .01, now,
                      None, None, 'H1-1', ['FVG'], 'ob')
    bar = Bar('M15', now, now + pd.Timedelta(minutes=15), 1.01, 1.03, .999, 1.02)
    engine._observe_fills(bar)
    engine._cancel_pending(bar, bar.close_time)
    assert o['_touched'] and o['end_time'] is None
    assert 'H1-1' not in engine._pending_zones


def test_practice_boundary_and_global_config_restored():
    import pytest
    from src.research.engine.run_ct import PRACTICE_END
    before = {k: getattr(config, k, None) for k in ('LTF_TF', 'MAJOR_HTF', 'BIAS_TIMEFRAMES')}
    m15, _, _ = _run(weeks=12)
    assert before == {k: getattr(config, k, None) for k in before}
    m15.loc[m15.index[-1], 'timestamp'] = PRACTICE_END
    with pytest.raises(ValueError, match='practice window'):
        run_engine(m15)


def test_synthetic_prefix_and_poison_checks():
    import numpy as np
    from src.research.engine.run_ct import lookahead_check
    from src.research.poison import make_poisoned
    m15, rec, log = _run(weeks=52)
    assert len(rec.ctorders) > 0  # exercise order decisions, not just mapping
    assert lookahead_check(m15, log, 3)['pass']
    p = len(m15) // 2
    cut = m15.timestamp.iloc[p] + pd.Timedelta(minutes=15)
    poisoned = make_poisoned(m15, p, np.random.default_rng(20))
    _, got = run_engine(poisoned)
    assert [d.key() for d in log.items if d.time <= cut] == [
        d.key() for d in got.items if d.time <= cut]


def test_end_to_end_practice_runner_and_report(tmp_path, monkeypatch):
    from src.research.engine import run_ct, report_ct
    data = tmp_path / 'processed'
    out = tmp_path / 'outputs'
    data.mkdir()
    sample = make_synthetic_m15(weeks=52, seed=42, start='2016-01-04')
    sample.to_parquet(data / 'eurusd_m15.parquet')
    monkeypatch.setattr(run_ct, 'PROCESSED_DIR', data)
    monkeypatch.setattr(run_ct, 'OUT_DIR', out)
    monkeypatch.setenv('LOOKAHEAD_CUTS', '2')
    trades = run_ct.run_pair('eurusd')
    assert len(trades) > 0
    monkeypatch.setattr(report_ct, 'ROOT', tmp_path)
    monkeypatch.setattr(report_ct, 'DATA', out)
    monkeypatch.setenv('EXPECT_PAIRS', 'eurusd,gbpusd')
    monkeypatch.setenv('REPORT_LABEL', 'test')
    report_ct.main()
    report = (tmp_path / 'reports/phase4/report_ct_test.md').read_text()
    assert 'gbpusd' in report
    assert 'Lookahead: FAIL' in report
    assert 'Verdict: inconclusive' in report


def test_loader_filters_practice_boundary(tmp_path, monkeypatch):
    import pytest
    from src.research.engine import run_ct
    ts = pd.to_datetime(['2016-01-02 23:45Z', '2016-01-03 22:00Z',
                         '2022-06-30 23:45Z', '2022-07-01 00:00Z'], utc=True)
    df = pd.DataFrame({'timestamp': ts, 'open': 1., 'high': 1.1, 'low': .9, 'close': 1.})
    df.to_parquet(tmp_path / 'eurusd_m15.parquet')
    monkeypatch.setattr(run_ct, 'PROCESSED_DIR', tmp_path)
    got = run_ct.load_m15('eurusd')
    assert list(got.timestamp) == [ts[1], ts[2]]
    with pytest.raises(ValueError, match='practice window'):
        run_ct.load_m15('eurusd', pd.Timestamp('2022-07-02', tz='UTC'))
