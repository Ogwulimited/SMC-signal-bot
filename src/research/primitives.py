"""SMC Research Engine - Phase 1 Primitives."""
import pandas as pd
import numpy as np

def find_swings(df, n, tf):
    """Vectorized swing detection using numpy sliding windows.
    
    confirm_time is the CLOSE time of the bar that confirms the swing.
    """
    highs = df["high"].values
    lows = df["low"].values
    times = df["timestamp"].values

    # Sliding windows for highs
    h_windows = np.lib.stride_tricks.sliding_window_view(highs, 2*n+1)
    h_centers = highs[n:-n]
    is_h = (h_centers == h_windows.max(axis=1)) & (h_centers > h_windows[:, :n].max(axis=1)) & (h_centers > h_windows[:, n+1:].max(axis=1))

    # Sliding windows for lows
    l_windows = np.lib.stride_tricks.sliding_window_view(lows, 2*n+1)
    l_centers = lows[n:-n]
    is_l = (l_centers == l_windows.min(axis=1)) & (l_centers < l_windows[:, :n].min(axis=1)) & (l_centers < l_windows[:, n+1:].min(axis=1))

    swing_indices_h = np.where(is_h)[0] + n
    swing_indices_l = np.where(is_l)[0] + n

    swings = []
    for i in swing_indices_h:
        swings.append({
            "index": i, "timestamp": pd.Timestamp(times[i]), "price": highs[i],
            "kind": "high", "confirm_time": pd.Timestamp(times[i+n]) + tf
        })
    for i in swing_indices_l:
        swings.append({
            "index": i, "timestamp": pd.Timestamp(times[i]), "price": lows[i],
            "kind": "low", "confirm_time": pd.Timestamp(times[i+n]) + tf
        })
    
    if not swings:
        return pd.DataFrame(columns=["index", "timestamp", "price", "kind", "confirm_time"])
        
    return pd.DataFrame(swings).sort_values("confirm_time").reset_index(drop=True)

def detect_bos_choch(df, swings):
    """Fully vectorized BOS/CHoCH detection using parallel lists."""
    times = df["timestamp"].values
    closes = df["close"].values
    
    h_prices, h_times = [], []
    l_prices, l_times = [], []
    events = []
    trend = "none"
    
    s_idx = 0
    s_records = swings.to_dict("records")
    
    for i in range(len(df)):
        t = times[i]
        c = closes[i]
        
        # Add newly confirmed swings to active lists
        while s_idx < len(s_records) and s_records[s_idx]["confirm_time"].value <= pd.Timestamp(t).value:
            sw = s_records[s_idx]
            if sw["kind"] == "high":
                h_prices.append(sw["price"])
                h_times.append(sw["timestamp"])
            else:
                l_prices.append(sw["price"])
                l_times.append(sw["timestamp"])
            s_idx += 1
            
        # Up break
        if h_prices and c > h_prices[-1]:
            opp_t = l_times[-1] if l_times else pd.NaT
            opp_p = l_prices[-1] if l_prices else np.nan
            
            bp = h_prices.pop()
            bt = h_times.pop()
            
            while h_prices and h_prices[-1] <= c:
                h_prices.pop()
                h_times.pop()
                
            label = "INIT" if trend == "none" else ("BOS" if trend == "up" else "CHoCH")
            trend = "up"
            
            events.append({
                "label": label, "direction": "up", "time": pd.Timestamp(t),
                "close": c, "broken_swing_time": bt, "broken_swing_price": bp,
                "last_opposite_time": opp_t, "last_opposite_price": opp_p
            })
            
        # Down break
        if l_prices and c < l_prices[-1]:
            opp_t = h_times[-1] if h_times else pd.NaT
            opp_p = h_prices[-1] if h_prices else np.nan
            
            bp = l_prices.pop()
            bt = l_times.pop()
            
            while l_prices and l_prices[-1] >= c:
                l_prices.pop()
                l_times.pop()
                
            label = "INIT" if trend == "none" else ("BOS" if trend == "down" else "CHoCH")
            trend = "down"
            
            events.append({
                "label": label, "direction": "down", "time": pd.Timestamp(t),
                "close": c, "broken_swing_time": bt, "broken_swing_price": bp,
                "last_opposite_time": opp_t, "last_opposite_price": opp_p
            })
            
    return pd.DataFrame(events)

def compute_atr(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def resample_to_tf(m15_df, rule, offset_hours=0):
    ny = m15_df.set_index("timestamp").tz_convert("America/New_York")
    if offset_hours: ny.index = ny.index + pd.Timedelta(hours=offset_hours)
    agg = {"open": ("open", "first"), "high": ("high", "max"), "low": ("low", "min"), "close": ("close", "last")}
    res = ny.resample(rule, label="left", closed="left").agg(**agg).dropna(subset=["open"])
    if offset_hours: res.index = res.index - pd.Timedelta(hours=offset_hours)
    return res.tz_convert("UTC").reset_index()

def bars_available_at(df, t, tf_minutes):
    close_time = df["timestamp"] + pd.Timedelta(minutes=tf_minutes)
    return df[close_time <= t].copy()
