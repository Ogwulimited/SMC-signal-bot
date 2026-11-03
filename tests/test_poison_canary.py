import numpy as np

from src.research.engine.structure import run_structure_pipeline
from src.research.lookahead_guard import DataFeed, DecisionLog
from src.research.poison import format_result, make_synthetic_m15, poison_test


def run_cheating_pipeline(m15):
    """CANARY: a deliberately cheating strategy. It confirms a swing high with
    the NEXT bar's close, from a precomputed vector, and stamps the decision
    with the earlier time as if it knew it then."""
    df = m15.reset_index(drop=True)
    high = df["high"].to_numpy()
    close = df["close"].to_numpy()
    cand = np.zeros(len(df), dtype=bool)
    cand[1:] = high[1:] > high[:-1]
    next_lower = np.zeros(len(df), dtype=bool)
    next_lower[:-1] = close[1:] < close[:-1]          # CHEAT: uses the next bar's close
    flag = cand & next_lower
    log = DecisionLog()
    state = {"i": 0}

    class Cheat:
        def on_bar_close(self, bar, feed):
            if bar.tf != "M15":
                return
            j = state["i"]
            state["i"] += 1
            if flag[j]:
                log.add("cheat_swing_high", bar.close_time, bar.close_time, price=float(high[j]))

    DataFeed(df, htf=()).run(Cheat())
    return log.items


def test_honest_pipeline_passes_the_poison_test():
    m15 = make_synthetic_m15(weeks=10, seed=21)
    res = poison_test(run_structure_pipeline, m15, n_cuts=100, seed=7)
    print(format_result("POISON (honest structure pipeline, synthetic data)", res))
    if res.first_mismatch:
        print("  first mismatch: " + res.first_mismatch)
    assert res.decisions_compared > 0
    assert res.mismatches == 0


def test_canary_cheating_strategy_is_caught():
    m15 = make_synthetic_m15(weeks=10, seed=21)
    res = poison_test(run_cheating_pipeline, m15, n_cuts=100, seed=7)
    if res.mismatches > 0:
        print(f"CANARY: poison test FAILED on cheating strategy (expected) - "
              f"{res.mismatches} of {res.n_cuts} cut times differ")
    else:
        print("CANARY: poison test did NOT catch the cheat (BAD)")
    assert res.mismatches > 0
