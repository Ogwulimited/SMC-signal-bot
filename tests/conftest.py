import pandas as pd


def _mk_df(opens, highs, lows, closes, freq="1h", start="2023-01-01"):
    n = len(opens)
    ts = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": opens, "high": highs, "low": lows, "close": closes})
