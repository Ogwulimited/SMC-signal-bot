"""Higher-timeframe bias computation from structural swings.

For each LTF bar timestamp, we ask: what is the HTF bias at that moment?
Bias is derived from the last HTF CHoCH: up if the last CHoCH was bullish,
down if the last CHoCH was bearish, None otherwise.
"""

from typing import Optional, Dict

from .smc import find_swings, detect_bos_choch


def compute_htf_bias_series(htf_candles, htf_swing_lookback=3):
    """Return list of (epoch, bias) at each HTF bar, using only data up to that bar.

    bias in {"bullish", "bearish", None}
    """
    if not htf_candles:
        return []

    out = []
    for i in range(len(htf_candles)):
        window = htf_candles[: i + 1]
        if len(window) < htf_swing_lookback * 2 + 5:
            out.append((htf_candles[i]["epoch"], None))
            continue
        try:
            swings = find_swings(window, htf_swing_lookback)
            _, chochs, trend = detect_bos_choch(window, swings)
            out.append((htf_candles[i]["epoch"], trend))
        except Exception:
            out.append((htf_candles[i]["epoch"], None))

    return out


def build_bias_lookup(bias_series):
    """Return dict {epoch: bias}. Caller looks up LTF epoch by nearest lower HTF epoch."""
    return {epoch: bias for epoch, bias in bias_series}


def lookup_bias(lookup: Dict[int, str], ltf_epoch: int, htf_epochs_sorted):
    """Find the most recent HTF epoch <= ltf_epoch and return its bias."""
    if not htf_epochs_sorted:
        return None
    # binary search for speed
    import bisect
    idx = bisect.bisect_right(htf_epochs_sorted, ltf_epoch) - 1
    if idx < 0:
        return None
    return lookup.get(htf_epochs_sorted[idx], None)
