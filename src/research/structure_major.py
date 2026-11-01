"""SMC Research Engine - major-structure BOS/CHoCH.

Python version of the Pine v5 check script ("major structure").

Rule (bullish version; bearish is the mirror image):
  * Swings come from primitives.find_swings (unchanged). A swing only counts
    from the open of the bar AFTER the bar that confirms it (no lookahead).
  * Up-break: a candle BODY CLOSES above the HIGHEST standing swing high.
    The line starts at that highest swing, not at the nearest one.
    (Highs 95k then 93k, close at 100k -> line starts at 95k.
     A close at 94k prints nothing, because 95k is still standing.)
  * Down-break: a close below the LOWEST standing swing low.
  * Label: INIT if there was no trend yet, BOS if the break is in the
    direction of the current trend, CHoCH if it is against it.
  * After a BOS, older opposite swings are dropped. The protected level
    becomes the pullback swing formed AFTER the broken level (the HL / LH).
  * After a CHoCH or INIT, opposite swings are kept, so the leg's extreme
    stays in memory (for a CHoCH down, the leg's top stays protected).
  * After any break, all swings on the broken side are cleared.

Output columns are identical to primitives.detect_bos_choch, so it is a
drop-in replacement:
  last_opposite_price/time = the protected opposite swing at the moment of
  the break (the lowest standing low for an up-break, the highest standing
  high for a down-break).
"""
import numpy as np
import pandas as pd

COLUMNS = ["label", "direction", "time", "close", "broken_swing_time",
           "broken_swing_price", "last_opposite_time", "last_opposite_price"]


def _empty_events():
    return pd.DataFrame({
        "label": pd.array([], dtype=object),
        "direction": pd.array([], dtype=object),
        "time": pd.array([], dtype="datetime64[ns, UTC]"),
        "close": pd.array([], dtype="float64"),
        "broken_swing_time": pd.array([], dtype="datetime64[ns, UTC]"),
        "broken_swing_price": pd.array([], dtype="float64"),
        "last_opposite_time": pd.array([], dtype="datetime64[ns, UTC]"),
        "last_opposite_price": pd.array([], dtype="float64"),
    })


def detect_bos_choch_major(df, swings, tf):
    """Major-structure BOS/CHoCH detection.

    Event 'time' is the CLOSE time (bar open + tf) of the breaking bar,
    exactly like primitives.detect_bos_choch.
    """
    times = df["timestamp"].tolist()
    closes = df["close"].values

    h_prices, h_times = [], []   # standing swing highs
    l_prices, l_times = [], []   # standing swing lows
    hi_max = None                # highest standing swing high
    lo_min = None                # lowest standing swing low
    events = []
    trend = "none"

    s_records = swings.to_dict("records")
    s_idx = 0

    for i in range(len(df)):
        t = times[i]
        c = float(closes[i])

        # Gate: a swing counts only if confirmed at or before the OPEN of this bar
        while s_idx < len(s_records) and s_records[s_idx]["confirm_time"].value <= t.value:
            sw = s_records[s_idx]
            p = float(sw["price"])
            if sw["kind"] == "high":
                h_prices.append(p)
                h_times.append(sw["timestamp"])
                if hi_max is None or p > hi_max:
                    hi_max = p
            else:
                l_prices.append(p)
                l_times.append(sw["timestamp"])
                if lo_min is None or p < lo_min:
                    lo_min = p
            s_idx += 1

        if hi_max is not None and c > hi_max:
            # ---- UP break: close above the HIGHEST standing swing high ----
            ih = h_prices.index(hi_max)
            bt = h_times[ih]
            bp = hi_max
            label = "INIT" if trend == "none" else ("BOS" if trend == "up" else "CHoCH")

            if label == "BOS":
                # keep only lows formed at or after the broken high
                keep = [k for k in range(len(l_times)) if l_times[k] >= bt]
                l_prices = [l_prices[k] for k in keep]
                l_times = [l_times[k] for k in keep]
                lo_min = min(l_prices) if l_prices else None

            if l_prices:
                il = l_prices.index(lo_min)
                opp_t, opp_p = l_times[il], l_prices[il]
            else:
                opp_t, opp_p = pd.NaT, np.nan

            h_prices, h_times, hi_max = [], [], None
            trend = "up"
            events.append({
                "label": label, "direction": "up", "time": t + tf,
                "close": c, "broken_swing_time": bt, "broken_swing_price": bp,
                "last_opposite_time": opp_t, "last_opposite_price": opp_p,
            })

        elif lo_min is not None and c < lo_min:
            # ---- DOWN break: close below the LOWEST standing swing low ----
            il = l_prices.index(lo_min)
            bt = l_times[il]
            bp = lo_min
            label = "INIT" if trend == "none" else ("BOS" if trend == "down" else "CHoCH")

            if label == "BOS":
                # keep only highs formed at or after the broken low
                keep = [k for k in range(len(h_times)) if h_times[k] >= bt]
                h_prices = [h_prices[k] for k in keep]
                h_times = [h_times[k] for k in keep]
                hi_max = max(h_prices) if h_prices else None

            if h_prices:
                ih = h_prices.index(hi_max)
                opp_t, opp_p = h_times[ih], h_prices[ih]
            else:
                opp_t, opp_p = pd.NaT, np.nan

            l_prices, l_times, lo_min = [], [], None
            trend = "down"
            events.append({
                "label": label, "direction": "down", "time": t + tf,
                "close": c, "broken_swing_time": bt, "broken_swing_price": bp,
                "last_opposite_time": opp_t, "last_opposite_price": opp_p,
            })

    if not events:
        return _empty_events()

    out = pd.DataFrame(events)[COLUMNS]
    out["label"] = out["label"].astype(object)
    out["direction"] = out["direction"].astype(object)
    for col in ["time", "broken_swing_time", "last_opposite_time"]:
        out[col] = pd.to_datetime(out[col], utc=True).astype("datetime64[ns, UTC]")
    return out
