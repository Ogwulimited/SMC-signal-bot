"""
zones.py -- Phase 2 SMC zone/pool detection.

CORRECTIONS THIS ROUND (self-caught, not DeepSeek's):
- find_swings() real output column is "timestamp", not "time". Fixed in
  find_swing_pools, detect_equal_lows, find_equal_highs, find_inducement.
- Standardized pool schema across producers: all pool-producing functions
  now output pool_price, confirm_time, expires_at, swept_time, side,
  pool_type, so find_liquidity_taken works against either swing pools or
  equal-lows/highs pools uniformly. swept_time defaults to NaT (populated
  later by a Phase-3 orchestration step calling detect_sweep per pool, not
  by these functions themselves).

ASSUMPTIONS (confirmed against real primitives.py source this round):
1. primitives.find_swings(df, n, tf) columns: index, timestamp, price, kind
   ("high"/"low"), confirm_time. CONFIRMED from real source.
2. primitives.detect_bos_choch(...) columns: label, direction, time (close
   time = open+tf), close, broken_swing_time, broken_swing_price,
   last_opposite_time, last_opposite_price. CONFIRMED from real source.
3. GROUND TRUTH: choch.direction=="down" => BEARISH setup;
   choch.direction=="up" => BULLISH setup. Verified by real CI run.
4. bad_days CSV schema still unconfirmed -- _load_bad_days tries common
   column names.
5. ob_unmitigated_before_touch is a caller-side helper (Phase 3 knows real
   touch time); detect_order_blocks's valid_pretouch covers only
   ob_sweep+ob_fvg, not mitigation -- caller must AND it in.
6. PDH/PDL/PWH/PWL/PMH/PML expiry: fixed offset from bucket close time;
   month uses pd.DateOffset for real calendar arithmetic.
7. EQL/EQH pools: no time-based expiry per appendix -- expires_at is NaT.
8. Breaker stop = far edge +/- 0.1*ATR(H1,14), per overall strategy spec.
9. find_inducement tries Model A first, Model B as fallback -- appendix
   doesn't state an order explicitly.
"""

import numpy as np
import pandas as pd

from src import config
from src.research import primitives


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_bad_days(bad_days_path, pair=None):
    if not bad_days_path:
        return set()
    raw = pd.read_csv(bad_days_path)
    if pair and "pair" in raw.columns:
        raw = raw[raw["pair"] == pair]
    col = "date" if "date" in raw.columns else ("bad_day" if "bad_day" in raw.columns else raw.columns[0])
    return set(pd.to_datetime(raw[col]).dt.date)


def _is_continuous(timestamps, tf, bad_days=None):
    ts = list(timestamps)
    if len(ts) < 1:
        return False
    if bad_days:
        for t in ts:
            if pd.Timestamp(t).date() in bad_days:
                return False
    if len(ts) < 2:
        return True
    for a, b in zip(ts, ts[1:]):
        if (b - a) > tf:
            return False
    return True


def _atr_shifted(df, period=14):
    return primitives.compute_atr(df, period=period).shift(1)


def ob_unmitigated_before_touch(mitigated_at, touch_time):
    if pd.isna(mitigated_at):
        return True
    if pd.isna(touch_time):
        return True
    return mitigated_at >= touch_time


# ---------------------------------------------------------------------------
# FVG
# ---------------------------------------------------------------------------

def detect_fvgs(df, tf, bad_days=None):
    atr = _atr_shifted(df, period=14)
    n = len(df)
    times = df["timestamp"]
    highs, lows = df["high"].values, df["low"].values
    rows = []
    for a in range(n - 2):
        b, c = a + 1, a + 2
        ts_slice = times.iloc[a:c + 1].tolist()
        if not _is_continuous(ts_slice, tf, bad_days):
            continue
        atr_c = atr.iloc[c]
        if pd.isna(atr_c) or atr_c <= 0:
            continue
        if lows[c] > highs[a]:
            size = lows[c] - highs[a]
            size_atr = size / atr_c
            if size_atr >= config.FVG_MIN_SIZE_ATR:
                rows.append({"a_index": a, "b_index": b, "c_index": c, "direction": "bullish",
                             "zone_low": highs[a], "zone_high": lows[c], "size": size,
                             "size_atr": size_atr, "confirm_time": times.iloc[c] + tf})
        if highs[c] < lows[a]:
            size = lows[a] - highs[c]
            size_atr = size / atr_c
            if size_atr >= config.FVG_MIN_SIZE_ATR:
                rows.append({"a_index": a, "b_index": b, "c_index": c, "direction": "bearish",
                             "zone_low": highs[c], "zone_high": lows[a], "size": size,
                             "size_atr": size_atr, "confirm_time": times.iloc[c] + tf})
    cols = ["a_index", "b_index", "c_index", "direction", "zone_low", "zone_high",
            "size", "size_atr", "confirm_time"]
    out = pd.DataFrame(rows, columns=cols)
    if not out.empty:
        out["confirm_time"] = pd.to_datetime(out["confirm_time"], utc=True)
    return out


# ---------------------------------------------------------------------------
# Generic sweep detector
# ---------------------------------------------------------------------------

def detect_sweep(df, tf, pool_price, confirm_time, side, bad_days=None,
                  reclaim_window=config.SWEEP_RECLAIM_WINDOW):
    atr = _atr_shifted(df, period=14)
    cand = df[df["timestamp"] >= confirm_time].reset_index(drop=False)
    for _, row in cand.iterrows():
        orig_idx = row["index"]
        if bad_days and row["timestamp"].date() in bad_days:
            continue
        atr_i = atr.iloc[orig_idx]
        if side == "low":
            if row["low"] < pool_price:
                depth = (pool_price - row["low"]) / atr_i if pd.notna(atr_i) and atr_i > 0 else np.nan
                future_closes = df["close"].iloc[orig_idx + 1: orig_idx + 1 + reclaim_window]
                return {"swept_index": orig_idx, "swept_time": row["timestamp"] + tf,
                        "depth_atr": depth, "reclaim_same_bar": bool(row["close"] > pool_price),
                        "reclaim_3": bool((future_closes > pool_price).any())}
        else:
            if row["high"] > pool_price:
                depth = (row["high"] - pool_price) / atr_i if pd.notna(atr_i) and atr_i > 0 else np.nan
                future_closes = df["close"].iloc[orig_idx + 1: orig_idx + 1 + reclaim_window]
                return {"swept_index": orig_idx, "swept_time": row["timestamp"] + tf,
                        "depth_atr": depth, "reclaim_same_bar": bool(row["close"] < pool_price),
                        "reclaim_3": bool((future_closes < pool_price).any())}
    return None


# ---------------------------------------------------------------------------
# Swing pools (H1/H4)  -- FIXED: "time"->"timestamp", price->pool_price,
# added swept_time column for schema consistency with liquidity_taken.
# ---------------------------------------------------------------------------

def find_swing_pools(df, tf, timeframe_label, side, bad_days=None):
    n = config.LIQUIDITY_SWING_N
    swings = primitives.find_swings(df, n, tf)
    kind = "low" if side == "low" else "high"
    sub = swings[swings["kind"] == kind].copy()
    max_age = config.SWING_POOL_MAX_AGE_H1 if timeframe_label == "H1" else config.SWING_POOL_MAX_AGE_H4
    sub["expires_at"] = sub["confirm_time"] + max_age * tf
    sub["timeframe"] = timeframe_label
    sub["side"] = side
    sub["pool_type"] = "swing"
        sub["swept_time"] = pd.DatetimeIndex([pd.NaT] * len(sub), tz="UTC")
    sub = sub.rename(columns={"price": "pool_price"})
    if bad_days:
        sub = sub[~sub["timestamp"].apply(lambda t: t.date() in bad_days)]
    return sub[["index", "timestamp", "pool_price", "confirm_time", "expires_at",
                "swept_time", "side", "timeframe", "pool_type"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Equal lows / equal highs -- FIXED: "time"->"timestamp", added
# expires_at (NaT, no stated expiry) + swept_time (NaT) for schema parity.
# ---------------------------------------------------------------------------

def _cluster_equal_swings(swings, atr_series, side):
    n = len(swings)
    swings = swings.reset_index(drop=True)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for i in range(n):
        for j in range(i + 1, n):
            bar_dist = swings["index"].iloc[j] - swings["index"].iloc[i]
            if bar_dist < config.EQ_LOWS_MIN_BARS or bar_dist > config.EQ_LOWS_MAX_BARS:
                continue
            atr_val = atr_series.iloc[swings["index"].iloc[j]]
            if pd.isna(atr_val) or atr_val <= 0:
                continue
            tol = config.EQ_LOWS_TOLERANCE_ATR * atr_val
            if abs(swings["price"].iloc[j] - swings["price"].iloc[i]) <= tol:
                union(i, j)

    clusters = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    results = []
    for members in clusters.values():
        if len(members) < config.EQ_LOWS_MIN_CLUSTER:
            continue
        sub = swings.iloc[members]
        pool_price = sub["price"].min() if side == "low" else sub["price"].max()
        results.append({"pool_price": pool_price, "confirm_time": sub["confirm_time"].max(),
                         "expires_at": pd.NaT, "swept_time": pd.NaT,
                         "cluster_size": len(members), "member_indexes": sorted(sub["index"].tolist()),
                         "side": side, "pool_type": "equal_lows" if side == "low" else "equal_highs"})
    return results


def detect_equal_lows(df, tf, bad_days=None):
    atr = _atr_shifted(df, period=14)
    swings = primitives.find_swings(df, config.LIQUIDITY_SWING_N, tf)
    lows = swings[swings["kind"] == "low"].reset_index(drop=True)
    if bad_days:
        lows = lows[~lows["timestamp"].apply(lambda t: t.date() in bad_days)].reset_index(drop=True)
    clusters = _cluster_equal_swings(lows, atr, "low")
        cols = ["pool_price", "confirm_time", "expires_at", "swept_time",
            "cluster_size", "member_indexes", "side", "pool_type"]
    out = pd.DataFrame(clusters, columns=cols)
    if not out.empty:
        out["confirm_time"] = pd.to_datetime(out["confirm_time"], utc=True)
        out["expires_at"] = pd.to_datetime(out["expires_at"], utc=True)
        out["swept_time"] = pd.to_datetime(out["swept_time"], utc=True)
    return out

def find_equal_highs(df, tf, bad_days=None):
    atr = _atr_shifted(df, period=14)
    swings = primitives.find_swings(df, config.LIQUIDITY_SWING_N, tf)
    highs = swings[swings["kind"] == "high"].reset_index(drop=True)
    if bad_days:
        highs = highs[~highs["timestamp"].apply(lambda t: t.date() in bad_days)].reset_index(drop=True)
    clusters = _cluster_equal_swings(highs, atr, "high")
        cols = ["pool_price", "confirm_time", "expires_at", "swept_time",
            "cluster_size", "member_indexes", "side", "pool_type"]
    out = pd.DataFrame(clusters, columns=cols)
    if not out.empty:
        out["confirm_time"] = pd.to_datetime(out["confirm_time"], utc=True)
        out["expires_at"] = pd.to_datetime(out["expires_at"], utc=True)
        out["swept_time"] = pd.to_datetime(out["swept_time"], utc=True)
    return out


# ---------------------------------------------------------------------------
# PDH/PDL, PWH/PWL, PMH/PML
# ---------------------------------------------------------------------------

def _ny_session_bucket(ts_utc, freq):
    ny = ts_utc.tz_convert("America/New_York")
    if freq == "D":
        return (ny - pd.Timedelta(hours=17)).strftime("%Y-%m-%d")
    if freq == "W":
        s = (ny - pd.Timedelta(hours=17)).isocalendar()
        return f"{s.year}-W{s.week}"
    if freq == "M":
        return ny.strftime("%Y-%m")
    raise ValueError(freq)


def _periodic_hilo_pools(df, tf, freq, max_age_periods, prefix, bad_days=None):
    work = df.copy()
    work["bucket"] = work["timestamp"].apply(lambda t: _ny_session_bucket(t, freq))
    if bad_days:
        work = work[~work["timestamp"].apply(lambda t: t.date() in bad_days)]
    rows = []
    for b, g in work.groupby("bucket"):
        confirm_time = g["timestamp"].max() + tf
        if freq == "D":
            age = pd.Timedelta(days=max_age_periods)
        elif freq == "W":
            age = pd.Timedelta(weeks=max_age_periods)
        else:
            age = pd.DateOffset(months=max_age_periods)
        rows.append({"bucket": b, "side": "high", "pool_price": g["high"].max(),
                     "confirm_time": confirm_time, "expires_at": confirm_time + age,
                     "swept_time": pd.NaT, "pool_type": f"{prefix}H"})
        rows.append({"bucket": b, "side": "low", "pool_price": g["low"].min(),
                     "confirm_time": confirm_time, "expires_at": confirm_time + age,
                     "swept_time": pd.NaT, "pool_type": f"{prefix}L"})
    cols = ["bucket", "side", "pool_price", "confirm_time", "expires_at", "swept_time", "pool_type"]
    return pd.DataFrame(rows, columns=cols)


def find_pdh_pdl(df, tf, bad_days=None):
    return _periodic_hilo_pools(df, tf, "D", config.PDH_PDL_LOOKBACK_DAYS, "PD", bad_days)


def find_pwh_pwl(df, tf, bad_days=None):
    return _periodic_hilo_pools(df, tf, "W", config.PWH_PWL_LOOKBACK_WEEKS, "PW", bad_days)


def find_pmh_pml(df, tf, bad_days=None):
    return _periodic_hilo_pools(df, tf, "M", config.PMH_PML_LOOKBACK_MONTHS, "PM", bad_days)


# ---------------------------------------------------------------------------
# Liquidity Taken (Layer 4)
# ---------------------------------------------------------------------------

def find_liquidity_taken(pools, bos_open_time, l_base_price, direction,
                          atr_at_bos=None, ob_upper_edge=None):
    side = "low" if direction == "bullish" else "high"
    cand = pools[pools["side"] == side].copy()
    cand = cand[cand["confirm_time"] < bos_open_time]
    cand = cand[(cand["swept_time"].isna()) | (cand["swept_time"] >= bos_open_time)]
    if "expires_at" in cand.columns:
        cand = cand[(cand["expires_at"].isna()) | (cand["expires_at"] >= bos_open_time)]
    cand = cand[l_base_price < cand["pool_price"]] if side == "low" else cand[l_base_price > cand["pool_price"]]
    cand["depth"] = (cand["pool_price"] - l_base_price).abs()
    have_atr = atr_at_bos not in (None, 0) and pd.notna(atr_at_bos)
    cand["depth_atr"] = cand["depth"] / atr_at_bos if have_atr else np.nan
    if ob_upper_edge is not None and have_atr:
        cand["distance_atr"] = (ob_upper_edge - cand["pool_price"]).abs() / atr_at_bos
    else:
        cand["distance_atr"] = np.nan
    return cand[["pool_type", "pool_price", "depth", "depth_atr", "distance_atr"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Entry Order Block (unchanged -- already tested & passing)
# ---------------------------------------------------------------------------

def detect_order_blocks(df, tf, bos_choch_events, bad_days=None):
    atr = _atr_shifted(df, period=14)
    times = df["timestamp"]
    n = len(df)
    time_to_idx = {t: i for i, t in enumerate(times)}

    bos_choch_events = bos_choch_events[bos_choch_events["label"].isin(["BOS", "CHoCH"])]
    bos_rows = bos_choch_events[bos_choch_events["label"] == "BOS"].reset_index(drop=True)
    choch_rows = bos_choch_events[bos_choch_events["label"] == "CHoCH"].reset_index(drop=True)

    def bar_idx_for_close_time(close_time):
        return time_to_idx.get(close_time - tf)

    rows = []
    for _, choch in choch_rows.iterrows():
        prior_bos = bos_rows[bos_rows["time"] < choch["time"]]
        if prior_bos.empty:
            continue
        bos = prior_bos.iloc[-1]
        bos_idx = bar_idx_for_close_time(bos["time"])
        choch_idx = bar_idx_for_close_time(choch["time"])
        if bos_idx is None or choch_idx is None or bos_idx >= choch_idx:
            continue

        leg_ts = times.iloc[bos_idx:choch_idx + 1].tolist()
        if not _is_continuous(leg_ts, tf, bad_days):
            continue

        if choch["direction"] == "down":
            setup_direction = "bearish"
            leg = df["high"].iloc[bos_idx:choch_idx + 1]
            l_base_idx = bos_idx + int(leg.values.argmax())
            l_base_price = leg.iloc[int(leg.values.argmax())]
        else:
            setup_direction = "bullish"
            leg = df["low"].iloc[bos_idx:choch_idx + 1]
            l_base_idx = bos_idx + int(leg.values.argmin())
            l_base_price = leg.iloc[int(leg.values.argmin())]

        search_start = max(0, l_base_idx - config.OB_SEARCH_BACK_MAX)
        ob_idx = None
        for k in range(l_base_idx, search_start - 1, -1):
            o, c = df["open"].iloc[k], df["close"].iloc[k]
            if o == c:
                continue
            if setup_direction == "bearish" and c > o:
                ob_idx = k
                break
            if setup_direction == "bullish" and c < o:
                ob_idx = k
                break
        if ob_idx is None or ob_idx == 0:
            continue

        search_ts = times.iloc[ob_idx:l_base_idx + 1].tolist()
        if not _is_continuous(search_ts, tf, bad_days):
            continue

        ob_low, ob_high = df["low"].iloc[ob_idx], df["high"].iloc[ob_idx]

        if setup_direction == "bullish":
            ob_sweep = bool(df["low"].iloc[ob_idx] < df["low"].iloc[ob_idx - 1])
        else:
            ob_sweep = bool(df["high"].iloc[ob_idx] > df["high"].iloc[ob_idx - 1])

        ob_fvg, fvg_size_atr = False, np.nan
        a, c = ob_idx, ob_idx + 2
        if c < n:
            fvg_ts = times.iloc[a:c + 1].tolist()
            if _is_continuous(fvg_ts, tf, bad_days):
                atr_c = atr.iloc[c]
                if pd.notna(atr_c) and atr_c > 0:
                    if setup_direction == "bullish" and df["low"].iloc[c] > df["high"].iloc[a]:
                        size = df["low"].iloc[c] - df["high"].iloc[a]
                        fvg_size_atr = size / atr_c
                        ob_fvg = fvg_size_atr >= config.FVG_MIN_SIZE_ATR
                    elif setup_direction == "bearish" and df["high"].iloc[c] < df["low"].iloc[a]:
                        size = df["low"].iloc[a] - df["high"].iloc[c]
                        fvg_size_atr = size / atr_c
                        ob_fvg = fvg_size_atr >= config.FVG_MIN_SIZE_ATR

        mitigated_at, penetration_depth_frac = pd.NaT, np.nan
        zone_size = ob_high - ob_low
        for k in range(ob_idx + config.OB_MITIGATION_START_OFFSET, n):
            if setup_direction == "bullish" and df["low"].iloc[k] <= ob_high:
                mitigated_at = times.iloc[k] + tf
                if zone_size > 0:
                    penetration_depth_frac = max(0.0, (ob_high - df["low"].iloc[k]) / zone_size)
                break
            if setup_direction == "bearish" and df["high"].iloc[k] >= ob_low:
                mitigated_at = times.iloc[k] + tf
                if zone_size > 0:
                    penetration_depth_frac = max(0.0, (df["high"].iloc[k] - ob_low) / zone_size)
                break

        rows.append({"bos_time": bos["time"], "choch_time": choch["time"], "direction": setup_direction,
                     "l_base_index": l_base_idx, "l_base_time": times.iloc[l_base_idx], "l_base_price": l_base_price,
                     "ob_index": ob_idx, "ob_time": times.iloc[ob_idx], "ob_low": ob_low, "ob_high": ob_high,
                     "ob_sweep": ob_sweep, "ob_fvg": ob_fvg, "ob_fvg_size_atr": fvg_size_atr,
                     "ob_structure": True, "mitigated_at": mitigated_at,
                     "penetration_depth_frac": penetration_depth_frac,
                     "valid_pretouch": bool(ob_sweep and ob_fvg)})

    cols = ["bos_time", "choch_time", "direction", "l_base_index", "l_base_time", "l_base_price",
            "ob_index", "ob_time", "ob_low", "ob_high", "ob_sweep", "ob_fvg", "ob_fvg_size_atr",
            "ob_structure", "mitigated_at", "penetration_depth_frac", "valid_pretouch"]
    out = pd.DataFrame(rows, columns=cols)
    if not out.empty:
        for col in ["bos_time", "choch_time", "mitigated_at"]:
            out[col] = pd.to_datetime(out[col], utc=True)
    return out


# ---------------------------------------------------------------------------
# Inducement (IDM) -- FIXED: "time"->"timestamp" throughout (Model A & B)
# ---------------------------------------------------------------------------

def find_inducement(h1_df, m15_df, tf_h1, tf_m15, choch_time, l_base_time,
                     ob_low, ob_high, direction, bad_days=None):
    bull = direction == "bullish"

    def _model_b():
        swings = primitives.find_swings(h1_df, config.STRUCTURE_SWING_N, tf_h1)
        kind = "high" if bull else "low"
        cand = swings[(swings["kind"] == kind) & (swings["timestamp"] >= choch_time)].sort_values("timestamp")
        if cand.empty:
            return None
        s1 = cand.iloc[0]
        after = h1_df[h1_df["timestamp"] >= s1["confirm_time"]].reset_index(drop=False)
        bos_row = None
        for _, r in after.iterrows():
            if bull and r["close"] > s1["price"]:
                bos_row = r; break
            if (not bull) and r["close"] < s1["price"]:
                bos_row = r; break
        if bos_row is None:
            return None
        bos_idx = bos_row["index"]
        s1_match = h1_df.index[h1_df["timestamp"] == s1["timestamp"]]
        if len(s1_match) == 0 or s1_match[0] >= bos_idx:
            return None
        s1_idx = s1_match[0]
        opp = "low" if bull else "high"
        between = swings[(swings["kind"] == opp) & (swings["index"] > s1_idx) & (swings["index"] < bos_idx)]
        if between.empty:
            return None
        idm_row = between.loc[between["price"].idxmin() if bull else between["price"].idxmax()]
        return {"model": "B", "idm_price": idm_row["price"], "idm_time": idm_row["confirm_time"],
                "armed_time": h1_df["timestamp"].iloc[bos_idx] + tf_h1}

    def _model_a():
        swings = primitives.find_swings(m15_df, config.STRUCTURE_SWING_N, tf_m15)
        kind = "high" if bull else "low"
        cand = swings[(swings["kind"] == kind) & (swings["timestamp"] > l_base_time) & (swings["confirm_time"] <= choch_time)]
        if cand.empty:
            return None
        window = m15_df[(m15_df["timestamp"] > l_base_time) &
                         (m15_df["timestamp"] + tf_m15 <= choch_time)].reset_index(drop=False)
        bos_row = None
        for _, r in window.iterrows():
            active = cand[cand["confirm_time"] <= r["timestamp"]]
            if active.empty:
                continue
            recent = active.sort_values("timestamp").iloc[-1]
            if bull and r["close"] > recent["price"]:
                bos_row = r; break
            if (not bull) and r["close"] < recent["price"]:
                bos_row = r; break
        if bos_row is None:
            return None
        bos_idx = bos_row["index"]
        bos_close_time = m15_df["timestamp"].iloc[bos_idx] + tf_m15
        opp = "low" if bull else "high"
        opp_cand = swings[(swings["kind"] == opp) & (swings["timestamp"] > l_base_time) &
                           (swings["timestamp"] < m15_df["timestamp"].iloc[bos_idx]) &
                           (swings["confirm_time"] <= bos_close_time)]
        if opp_cand.empty:
            return None
        idm_row = opp_cand.sort_values("timestamp").iloc[-1]
        return {"model": "A", "idm_price": idm_row["price"], "idm_time": idm_row["confirm_time"],
                "armed_time": bos_close_time}

    result = _model_a() or _model_b()
    if result is None:
        return None

    idm_price, armed_time = result["idm_price"], result["armed_time"]
    m15_after = m15_df[m15_df["timestamp"] + tf_m15 > armed_time].reset_index(drop=False)
    swept_time, swept_idx = pd.NaT, None
    for _, r in m15_after.iterrows():
        if bad_days and r["timestamp"].date() in bad_days:
            continue
        if bull and r["low"] < idm_price:
            swept_time, swept_idx = r["timestamp"] + tf_m15, r["index"]; break
        if (not bull) and r["high"] > idm_price:
            swept_time, swept_idx = r["timestamp"] + tf_m15, r["index"]; break
    result["swept_time"] = swept_time

    touch_time, same_bar_ambiguous, invalid_h1_close_through = pd.NaT, False, False
    if swept_idx is not None:
        after_sweep = m15_df[m15_df["timestamp"] >= m15_df["timestamp"].iloc[swept_idx]].reset_index(drop=False)
        for _, r in after_sweep.iterrows():
            touched = (r["low"] <= ob_high) if bull else (r["high"] >= ob_low)
            if touched:
                if r["index"] == swept_idx:
                    same_bar_ambiguous = True
                else:
                    touch_time = r["timestamp"] + tf_m15
                break
        end_bound = touch_time if pd.notna(touch_time) else m15_df["timestamp"].iloc[-1] + tf_m15
        h1_through = h1_df[(h1_df["timestamp"] + tf_h1 > armed_time) & (h1_df["timestamp"] + tf_h1 <= end_bound)]
        invalid_h1_close_through = bool((h1_through["close"] < ob_low).any()) if bull else \
                                    bool((h1_through["close"] > ob_high).any())

    result.update({"touch_time": touch_time, "same_bar_ambiguous": same_bar_ambiguous,
                   "invalid_h1_close_through": invalid_h1_close_through})
    return result


# ---------------------------------------------------------------------------
# Touch and Fill (unchanged -- already tested & passing)
# ---------------------------------------------------------------------------

def find_touch_and_fill(m15_df, tf_m15, idm_swept_time, ob_low, ob_high, direction):
    bull = direction == "bullish"
    after = m15_df[m15_df["timestamp"] + tf_m15 > idm_swept_time].reset_index(drop=False)
    touch_row = None
    for _, r in after.iterrows():
        if bull and r["low"] <= ob_high:
            touch_row = r; break
        if (not bull) and r["high"] >= ob_low:
            touch_row = r; break
    if touch_row is None:
        return None
    touch_idx = touch_row["index"]
    fill1 = ob_high if bull else ob_low
    fill2, fill2_skipped = np.nan, True
    if touch_idx + 1 < len(m15_df):
        next_open = m15_df["open"].iloc[touch_idx + 1]
        if bull and next_open >= ob_low:
            fill2, fill2_skipped = next_open, False
        elif (not bull) and next_open <= ob_high:
            fill2, fill2_skipped = next_open, False
    return {"touch_time": m15_df["timestamp"].iloc[touch_idx] + tf_m15, "touch_index": touch_idx,
            "fill1": fill1, "fill2": fill2, "fill2_skipped": fill2_skipped}


# ---------------------------------------------------------------------------
# Breakers (unchanged -- not yet tested)
# ---------------------------------------------------------------------------

def detect_breakers(df, tf, m15_df, tf_m15, bos_choch_events, bad_days=None):
    atr = _atr_shifted(df, period=14)
    times = df["timestamp"]
    n = len(df)
    time_to_idx = {t: i for i, t in enumerate(times)}
    bos_rows = bos_choch_events[bos_choch_events["label"] == "BOS"].reset_index(drop=True)

    rows = []
    for _, bos in bos_rows.iterrows():
        if pd.isna(bos["last_opposite_time"]):
            continue
        bos_idx = time_to_idx.get(bos["time"] - tf)
        swing_idx = time_to_idx.get(bos["last_opposite_time"])
        if bos_idx is None or swing_idx is None or swing_idx > bos_idx:
            continue

        breaker_dir = "bullish" if bos["direction"] == "down" else "bearish"
        search_start = max(0, swing_idx - config.OB_BREAKER_SEARCH_BACK)
        zone_idx = None
        for k in range(swing_idx, search_start - 1, -1):
            o, c = df["open"].iloc[k], df["close"].iloc[k]
            if o == c:
                continue
            if breaker_dir == "bullish" and c > o:
                zone_idx = k; break
            if breaker_dir == "bearish" and c < o:
                zone_idx = k; break
        if zone_idx is None:
            continue

        zone_ts = times.iloc[zone_idx:bos_idx + 1].tolist()
        if not _is_continuous(zone_ts, tf, bad_days):
            continue

        zone_low, zone_high = df["low"].iloc[zone_idx], df["high"].iloc[zone_idx]

        failed_at, failed_idx = pd.NaT, None
        for k in range(zone_idx + 1, n):
            if breaker_dir == "bullish" and df["close"].iloc[k] > zone_high:
                failed_at, failed_idx = times.iloc[k] + tf, k; break
            if breaker_dir == "bearish" and df["close"].iloc[k] < zone_low:
                failed_at, failed_idx = times.iloc[k] + tf, k; break
        if failed_idx is None:
            continue

        fvg_overlap, f_low_m, f_high_m = False, np.nan, np.nan
        for a in range(failed_idx, min(failed_idx + 3, n - 2) + 1):
            b, c = a + 1, a + 2
            if c >= n:
                continue
            seg = times.iloc[a:c + 1].tolist()
            if not _is_continuous(seg, tf, bad_days):
                continue
            atr_c = atr.iloc[c]
            if pd.isna(atr_c) or atr_c <= 0:
                continue
            if breaker_dir == "bullish" and df["low"].iloc[c] > df["high"].iloc[a]:
                f_low, f_high = df["high"].iloc[a], df["low"].iloc[c]
            elif breaker_dir == "bearish" and df["high"].iloc[c] < df["low"].iloc[a]:
                f_low, f_high = df["high"].iloc[c], df["low"].iloc[a]
            else:
                continue
            if (f_high - f_low) / atr_c >= config.FVG_MIN_SIZE_ATR and max(zone_low, f_low) < min(zone_high, f_high):
                fvg_overlap, f_low_m, f_high_m = True, f_low, f_high
                break

        limit_price = (zone_low + zone_high) / 2.0
        filled, fill_time, cancelled, cancel_time = False, pd.NaT, False, pd.NaT
        h1_after = df[df["timestamp"] + tf > failed_at].reset_index(drop=False)
        cancel_ts = None
        for _, r in h1_after.iterrows():
            if breaker_dir == "bullish" and r["close"] < zone_low:
                cancelled, cancel_time, cancel_ts = True, r["timestamp"] + tf, r["timestamp"]; break
            if breaker_dir == "bearish" and r["close"] > zone_high:
                cancelled, cancel_time, cancel_ts = True, r["timestamp"] + tf, r["timestamp"]; break
        m15_after = m15_df[m15_df["timestamp"] + tf_m15 > failed_at].reset_index(drop=False)
        for _, r in m15_after.iterrows():
            if cancel_ts is not None and r["timestamp"] >= cancel_ts:
                break
            if breaker_dir == "bullish" and r["low"] <= limit_price:
                filled, fill_time = True, r["timestamp"] + tf_m15; break
            if breaker_dir == "bearish" and r["high"] >= limit_price:
                filled, fill_time = True, r["timestamp"] + tf_m15; break

        atr_zone = atr.iloc[zone_idx]
        stop = (zone_low - 0.1 * atr_zone) if breaker_dir == "bullish" else (zone_high + 0.1 * atr_zone)

        rows.append({"direction": breaker_dir, "swing_time": bos["last_opposite_time"],
                     "swing_price": bos["last_opposite_price"], "bos_time": bos["time"],
                     "zone_index": zone_idx, "zone_time": times.iloc[zone_idx],
                     "zone_low": zone_low, "zone_high": zone_high, "failed_at": failed_at,
                     "fvg_overlap": fvg_overlap, "fvg_low": f_low_m, "fvg_high": f_high_m,
                     "limit_price": limit_price, "stop": stop, "filled": filled, "fill_time": fill_time,
                     "cancelled": cancelled, "cancel_time": cancel_time})

    cols = ["direction", "swing_time", "swing_price", "bos_time", "zone_index", "zone_time",
            "zone_low", "zone_high", "failed_at", "fvg_overlap", "fvg_low", "fvg_high",
            "limit_price", "stop", "filled", "fill_time", "cancelled", "cancel_time"]
    out = pd.DataFrame(rows, columns=cols)
    if not out.empty:
        for col in ["swing_time", "bos_time", "zone_time", "failed_at", "fill_time", "cancel_time"]:
            out[col] = pd.to_datetime(out[col], utc=True)
    return out


# ---------------------------------------------------------------------------
# HTF zones (D1/H4) (unchanged -- not yet tested)
# ---------------------------------------------------------------------------

def find_htf_zones(df, tf, bos_choch_events, bad_days=None):
    times = df["timestamp"]
    n = len(df)
    time_to_idx = {t: i for i, t in enumerate(times)}
    bos_rows = bos_choch_events[bos_choch_events["label"] == "BOS"].reset_index(drop=True)
    choch_rows = bos_choch_events[bos_choch_events["label"] == "CHoCH"].reset_index(drop=True)

    rows = []
    for _, choch in choch_rows.iterrows():
        prior_bos = bos_rows[bos_rows["time"] < choch["time"]]
        if prior_bos.empty:
            continue
        bos = prior_bos.iloc[-1]
        bos_idx = time_to_idx.get(bos["time"] - tf)
        choch_idx = time_to_idx.get(choch["time"] - tf)
        if bos_idx is None or choch_idx is None or bos_idx >= choch_idx:
            continue
        leg_ts = times.iloc[bos_idx:choch_idx + 1].tolist()
        if not _is_continuous(leg_ts, tf, bad_days):
            continue

        if choch["direction"] == "down":
            direction = "bearish"
            leg = df["high"].iloc[bos_idx:choch_idx + 1]
            l_base_idx = bos_idx + int(leg.values.argmax())
        else:
            direction = "bullish"
            leg = df["low"].iloc[bos_idx:choch_idx + 1]
            l_base_idx = bos_idx + int(leg.values.argmin())

        search_start = max(0, l_base_idx - config.OB_SEARCH_BACK_MAX)
        ob_idx = None
        for k in range(l_base_idx, search_start - 1, -1):
            o, c = df["open"].iloc[k], df["close"].iloc[k]
            if o == c:
                continue
            if direction == "bearish" and c > o:
                ob_idx = k; break
            if direction == "bullish" and c < o:
                ob_idx = k; break
        if ob_idx is None:
            continue

        zone_low, zone_high = df["low"].iloc[ob_idx], df["high"].iloc[ob_idx]
        invalidated_at, touch_count = pd.NaT, 0
        for k in range(ob_idx + 1, n):
            if direction == "bullish":
                if df["low"].iloc[k] <= zone_high and pd.isna(invalidated_at):
                    touch_count += 1
                if df["close"].iloc[k] < zone_low:
                    invalidated_at = times.iloc[k] + tf; break
            else:
                if df["high"].iloc[k] >= zone_low and pd.isna(invalidated_at):
                    touch_count += 1
                if df["close"].iloc[k] > zone_high:
                    invalidated_at = times.iloc[k] + tf; break

        rows.append({"direction": direction, "ob_index": ob_idx, "confirm_time": times.iloc[ob_idx] + tf,
                     "zone_low": zone_low, "zone_high": zone_high,
                     "invalidated_at": invalidated_at, "touch_count": touch_count})

    cols = ["direction", "ob_index", "confirm_time", "zone_low", "zone_high", "invalidated_at", "touch_count"]
    out = pd.DataFrame(rows, columns=cols)
    if not out.empty:
        out["confirm_time"] = pd.to_datetime(out["confirm_time"], utc=True)
        out["invalidated_at"] = pd.to_datetime(out["invalidated_at"], utc=True)
    return out
