"""Wrapper: run H1 flexible-confluence detector with MIN_RR=1.5 baseline.

Exposes the raw signals so the backtest can filter by RR threshold
post-hoc without re-running detection.

This tests the question: "of the signals detected with MIN_RR=1.5,
which ones would have survived a higher MIN_RR filter?"
"""

from ..config import MIN_RR as DEFAULT_MIN_RR
from .h1_cascade import detect_h1_cascade_signals


def detect_h1_signals_with_rr(h1_window, d1_candles):
    """Same as detect_h1_cascade_signals but returns (signal, rr) tuples
    so the caller can filter by RR threshold without re-running detection."""
    sigs = detect_h1_cascade_signals(h1_window, d1_candles)
    return [(s, s.rr) for s in sigs]


# Re-export the baseline MIN_RR for the report
BASELINE_MIN_RR = DEFAULT_MIN_RR
