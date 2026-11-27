"""Report for the cycle run (practice years only, exam years sealed).
Reads data/phase4_cycle/{pair}_{trades.csv,funnel.json,lookahead.json}.
Env:
  REPORT_LABEL (file name label)
  EXPECT_PAIRS (comma list)
  REPORT_MODE  ("main" = executive & quant summary without 5-month anatomy;
                "anatomy" = separate full 70+ months day-by-day & chart-by-chart anatomy;
                "anatomy_p1" = 2016-2019 anatomy summary;
                "anatomy_p2" = 2020-2022 anatomy summary)
Writes:
  reports/phase4/report_cycle_<label>.md (Main Executive & Quant Summary)
  reports/phase4/report_cycle_<label>_monthly_anatomy.md (All 70+ Months Day-by-Day & Chart Anatomy)
  and writes the selected mode to GITHUB_STEP_SUMMARY.
"""
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd
from src import config
from src.research.engine import simulate_orders as so
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "phase4_cycle"
DATA_START = "2016-01-03"
FIXED_MONTHS = 78.0
ALL_PAIRS = ("eurusd,gbpusd,usdjpy,audusd,usdcad,usdchf,nzdusd,eurjpy,gbpjpy,eurgbp,"
             "audjpy,eurchf,eurcad,euraud,eurnzd,gbpchf,gbpcad,gbpaud,gbpnzd,audcad,"
             "audchf,audnzd,nzdjpy,nzdcad,nzdchf,cadjpy,cadchf,chfjpy").split(",")
NEW_PAIRS = set(ALL_PAIRS[11:])
TIME_COLS = ("placed_time", "end_time", "touch_time", "fill_time", "exit_time",
             "bos_time", "zone_touch_time", "choch_time", "box_time", "idm_sweep_time")
MGMT_R_COLS = tuple(f"r_{k}" for k in so.MGMT_PRESETS)
MGMT_OUT_COLS = tuple(f"out_{k}" for k in so.MGMT_PRESETS)
NUM_COLS = (
    "net_r", "r_gross", "dur_hours", "mfe_r", "mae_r", "spread_cost_r",
    "risk_r", "target_r", "entry", "fill_price", "stop", "target_price",
    "exit_price", "zone_low", "zone_high", "choch_level", "ceiling",
    "box_low", "box_high", "idm_level",
    "fill1_net_r", "unpadded_net_r", "unpadded_spread_ratio",
    "raw_stop", "dest_room_r", "deal_pct", "local_ote_pct",
    "disp_body_atr", "disp_close_pct", "ny_hour",
) + MGMT_R_COLS
BOOL_COLS = ("kept_1at", "flip_while_open", "min_risk_padded", "opp_h1_in_path",
             "fvg_overlap", "sweep_reclaim", "h1_refined_ok")
TEXT_COLS = ("htf_bias", "killzone", "mgmt_exit") + MGMT_OUT_COLS
DONE = ["target", "stop", "stop_gap", "partial_be", "partial_target"]
V1_PULLBACK = (1455, -21.13)
def fmt(x, d=2):
    if x is None:
        return "n/a"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    if math.isnan(x):
        return "n/a"
    if math.isinf(x):
        return "inf"
    return f"{x:.{d}f}"
def ftime(x):
    if x is None or pd.isna(x):
        return "n/a"
    return x.strftime("%Y-%m-%d %H:%M")
def fclock(x):
    if x is None or pd.isna(x):
        return "n/a"
    ampm = x.strftime("%I:%M %p").lstrip("0")
    return f"{x.strftime('%H:%M')} UTC ({ampm})"
def outcome_label(r):
    outc = str(r.get("outcome", "") or "")
    mexit = str(r.get("mgmt_exit", "") or "")
    gross = float(r["r_gross"]) if r.get("r_gross") is not None and not pd.isna(r.get("r_gross")) else -1.0
    if outc == "partial_target" or mexit == "partial_target":
        return f"WIN (Partial+TP +{fmt(gross, 2)}R)"
    if outc == "partial_be" or mexit == "partial_be":
        return f"PARTIAL WIN (+{fmt(gross, 2)}R, Runner BE)"
    if outc == "target":
        return f"WIN (+{fmt(gross, 1)}R)"
    if abs(gross) < 1e-6 or mexit == "be":
        return "BREAK-EVEN (0R)"
    if gross > 0:
        return f"PARTIAL WIN (+{fmt(gross, 2)}R)"
    return "LOSS (-1R)"
def outcome_short(r):
    outc = str(r.get("outcome", "") or "")
    mexit = str(r.get("mgmt_exit", "") or "")
    gross = float(r["r_gross"]) if r.get("r_gross") is not None and not pd.isna(r.get("r_gross")) else -1.0
    if outc in ("target", "partial_target") or mexit == "partial_target":
        return "WIN"
    if outc == "partial_be" or mexit == "partial_be" or gross > 1e-6:
        return "P-WIN"
    if abs(gross) < 1e-6 or mexit == "be":
        return "BE"
    return "LOSS"
def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return out
def read_trades(pair):
    p = DATA / f"{pair}_trades.csv"
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p, low_memory=False)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame(columns=so.TRADE_COLS)
    for c in so.TRADE_COLS:
        if c not in df.columns:
            df[c] = np.nan
    for c in NUM_COLS + TEXT_COLS:
        if c not in df.columns:
            df[c] = np.nan
    for c in BOOL_COLS:
        if c not in df.columns:
            df[c] = "False"
    df["leg"] = df["leg"].fillna("pullback")
    df["target_mode"] = df["target_mode"].fillna("static")
    for c in TIME_COLS:
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    for c in NUM_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in BOOL_COLS:
        if c in df.columns:
            df[c] = df[c].astype(str).eq("True")
    return df
def stats(t, col="net_r", out_col="outcome"):
    n = len(t)
    if n == 0:
        return {"n": 0, "net": 0.0, "wr": np.nan, "pos_wr": np.nan, "pf": np.nan, "exp": np.nan, "rr": np.nan}
    r = t[col].astype(float).dropna()
    n_valid = len(r)
    if n_valid == 0:
        return {"n": 0, "net": 0.0, "wr": np.nan, "pos_wr": np.nan, "pf": np.nan, "exp": np.nan, "rr": np.nan}
    pos = r[r > 0].sum()
    neg = -r[r < 0].sum()
    pf = pos / neg if neg > 0 else (np.inf if pos > 0 else np.nan)
    aw = r[r > 0].mean() if (r > 0).any() else np.nan
    al = -r[r < 0].mean() if (r < 0).any() else np.nan
    rr = aw / al if (al == al and al > 0 and aw == aw) else np.nan
    if out_col in t.columns and t[out_col].notna().any():
        full_wr = float(t[out_col].isin(["target", "partial_target"]).mean() * 100)
    else:
        full_wr = float((t["outcome"].isin(["target", "partial_target"])).mean() * 100)
    pos_wr = float((r > 0).mean() * 100)
    return {"n": n_valid, "net": float(r.sum()),
            "wr": full_wr, "pos_wr": pos_wr,
            "pf": float(pf), "exp": float(r.mean()), "rr": float(rr)}
def dd_streak(t, col="net_r"):
    if len(t) == 0:
        return 0.0, 0
    s = t.sort_values(["exit_time", "fill_time"])[col].astype(float).dropna().to_numpy()
    if len(s) == 0:
        return 0.0, 0
    cum = np.cumsum(s)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    dd = float((peak - cum).max())
    streak = best = 0
    for x in s:
        if x < 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return dd, best
def verdict(look_ok, s):
    if not look_ok:
        return "IGNORE - lookahead check is not PASS"
    if s["n"] == 0:
        return "NO TRADES"
    if s["exp"] <= 0:
        return "NEGATIVE on practice years"
    if s["n"] < 200 or not (s["pf"] >= 1.2):
        return "WEAK / NOT PROVEN (positive, but under 200 trades or PF under 1.2)"
    return "POSITIVE on practice years (not an exam result)"
def card(allr, leg, mode):
    a = allr[(allr["leg"] == leg) & (allr["target_mode"] == mode)]
    return a, a[a["outcome"].isin(DONE)]
def split_rows(r):
    rows = []
    for kind in ("breaker", "ob"):
        for side in ("buy", "sell"):
            st = stats(r[(r["kind"] == kind) & (r["side"] == side)])
            rows.append([f"{kind} {side}", st["n"], fmt(st["wr"], 1), fmt(st["net"]),
                         fmt(st["exp"], 3)])
    for side in ("buy", "sell"):
        st = stats(r[r["side"] == side])
        rows.append([f"ALL {side}s", st["n"], fmt(st["wr"], 1), fmt(st["net"]),
                     fmt(st["exp"], 3)])
    return rows
def sheet_line(i, r):
    return (f"{i}. **{r['pair']}** zone {r['kind']} {r['side']} - BOS {ftime(r['bos_time'])}; "
            f"zone {r['zone_tf']} {fmt(r['zone_low'], 5)} to {fmt(r['zone_high'], 5)} touched "
            f"{ftime(r['zone_touch_time'])}; CHoCH {ftime(r['choch_time'])} "
            f"(level {fmt(r['choch_level'], 5)}); placed {ftime(r['placed_time'])}, "
            f"filled {ftime(r['fill_time'])}, trigger {fmt(r['entry'], 5)}, "
            f"fill {fmt(r['fill_price'], 5)}, stop {fmt(r['stop'], 5)}, "
            f"target {fmt(r['target_price'], 5)} (planned {fmt(r['target_r'], 2)}R) -> "
            f"{r['outcome']} at {ftime(r['exit_time'])} ({fmt(r['exit_price'], 5)}), "
            f"gross R {fmt(r['r_gross'], 2)}, spread {fmt(r['spread_cost_r'], 2)}R, "
            f"net R {fmt(r['net_r'], 2)}")
def win_loss_be_counts(sub):
    if len(sub) == 0:
        return 0, 0, 0
    gross = sub["r_gross"].astype(float)
    wins = int(((sub["outcome"].isin(["target", "partial_target"])) | (gross > 1e-6)).sum())
    be = int((gross.abs() <= 1e-6).sum())
    losses = len(sub) - wins - be
    return wins, losses, be
def _trend_description(tr):
    hb = str(tr.get("htf_bias", "") or "").lower()
    leg = str(tr.get("leg", "pullback")).lower()
    side = str(tr.get("side", "")).lower()
    ztf = str(tr.get("zone_tf", "") or "").upper()
    if hb not in ("bull", "bear"):
        if leg == "zone":
            hb = "bull" if side == "buy" else "bear"
        else:
            hb = "bull" if side == "sell" else "bear"
    trend_word = "BULLISH (D1 + H4 Bull)" if hb == "bull" else "BEARISH (D1 + H4 Bear)"
    if leg == "zone":
        z_label = "H1 Continuation Zone" if ztf == "H1" else f"{ztf} Deep HTF Zone"
        mode_desc = f"With-Trend {z_label} {side.upper()}"
    else:
        mode_desc = f"Counter-Trend Pullback {side.upper()} (retracement against {hb.upper()} HTF)"
    return f"{trend_word} — {mode_desc}"
def _format_trade_chart_audit(t_num, tr):
    leg = str(tr.get("leg", "pullback")).lower()
    kind = str(tr.get("kind", "ob")).upper()
    side = str(tr.get("side", "")).upper()
    pair = str(tr.get("pair", "")).upper()
    ztf_raw = str(tr.get("zone_tf", "") or "").upper()
    leg_tag = f"ZONE ({ztf_raw})" if leg == "zone" and ztf_raw else leg.upper()
    res_lbl = outcome_label(tr)
    net_v = float(tr["net_r"])
    sign = "+" if net_v >= 0 else ""
    lines = [
        f"- **Trade #{t_num} ({ftime(tr['fill_time'])} UTC) | {pair} | {leg_tag} {kind} {side} -> {res_lbl} (Net {sign}{fmt(net_v, 2)} R)**",
        f"  - **1. HTF Trend / Bias:** {_trend_description(tr)}",
    ]
    ztf = tr.get("zone_tf")
    zlow = tr.get("zone_low")
    zhigh = tr.get("zone_high")
    ztouch = tr.get("zone_touch_time")
    has_zone = ztf is not None and not pd.isna(ztf) and zlow is not None and not pd.isna(zlow)
    if leg == "zone":
        lines.append(
            f"  - **2. HTF Zone & Tap/Sweep Into Zone:** {ztf} Zone `{fmt(zlow, 5)}` to `{fmt(zhigh, 5)}` | "
            f"Price tapped/swept into {ztf} Zone at `{ftime(ztouch)} UTC` "
            f"(preceding counter-trend M15 BOS at `{ftime(tr.get('bos_time'))} UTC`; "
            f"Impulse Ceiling at `{fmt(tr.get('ceiling'), 5)}`)"
        )
    else:
        z_txt = (f"Nearest opposing {ztf} Zone `{fmt(zlow, 5)}` to `{fmt(zhigh, 5)}`"
                 if has_zone else "No unmitigated opposing HTF zone")
        lines.append(
            f"  - **2. HTF Impulse Ceiling & Opposing HTF Zone:** Pullback started from Impulse Ceiling "
            f"`{fmt(tr.get('ceiling'), 5)}` | Trading toward {z_txt}"
        )
    lines.append(
        f"  - **3. M15 CHoCH (Change of Character):** Candle closed at `{ftime(tr.get('choch_time'))} UTC` "
        f"breaking structure level `{fmt(tr.get('choch_level'), 5)}`"
        + (f" | Confirming M15 BOS at `{ftime(tr.get('bos_time'))} UTC`"
           if leg == "pullback" and tr.get("bos_time") is not None and not pd.isna(tr.get("bos_time"))
           else "")
    )
    if kind == "OB":
        lines.append(
            f"  - **4. M15 Inducement (IDM) & Liquidity Sweep:** Inducement level `{fmt(tr.get('idm_level'), 5)}` "
            f"swept at `{ftime(tr.get('idm_sweep_time'))} UTC`"
        )
    else:
        lines.append(
            "  - **4. Unicorn Breaker Displacement:** M15 Breaker Block broken with overlapping Fair Value Gap"
        )
    lines.append(
        f"  - **5. M15 {kind} Box (POI):** Candle `{ftime(tr.get('box_time'))} UTC` | "
        f"Box Low `{fmt(tr.get('box_low'), 5)}` to Box High `{fmt(tr.get('box_high'), 5)}`"
    )
    lines.append(
        f"  - **6. Entry, Stop Loss & Take Profit:** Order placed `{ftime(tr.get('placed_time'))} UTC` "
        f"(Trigger `{fmt(tr.get('entry'), 5)}`) -> **Filled at `{ftime(tr.get('fill_time'))} UTC` @ `{fmt(tr.get('fill_price'), 5)}`** | "
        f"**Stop Loss:** `{fmt(tr.get('stop'), 5)}` | **Take Profit (+{fmt(tr.get('target_r'), 2)}R):** `{fmt(tr.get('target_price'), 5)}`"
    )
    lines.append(
        f"  - **7. Resolution:** `{tr.get('outcome')}` at `{ftime(tr.get('exit_time'))} UTC` @ `{fmt(tr.get('exit_price'), 5)}` | "
        f"Gross `{fmt(tr.get('r_gross'), 2)} R`, Spread `{fmt(tr.get('spread_cost_r'), 2)} R`, "
        f"**Net `{sign}{fmt(net_v, 2)} R`** (Max Favorable `{fmt(tr.get('mfe_r'), 2)} R`, Max Adverse `{fmt(tr.get('mae_r'), 2)} R`)"
    )
    return lines
def render_all_months_deep_dive(m_records, label, year_filter=None):
    """Render the separate full 70+ months Day-by-Day Calendar & Chart-by-Chart Trade Anatomy report."""
    chosen = [r for r in m_records if (year_filter is None or int(r["ym"][:4]) in year_filter)]
    active_months = sum(1 for r in chosen if r["n"] > 0)
    total_trades = sum(r["n"] for r in chosen)
    scope_txt = "All 78 Calendar Months (2016-01 to 2022-06)" if year_filter is None else f"Years {min(year_filter)}-{max(year_filter)}"
    out = [
        f"# Phase 4 Full Monthly Day-by-Day & Chart-by-Chart Trade Anatomy: {label}",
        "",
        f"- **Scope:** {scope_txt} — **{len(chosen)} calendar months** ({active_months} active trading months, **{total_trades} resolved trades**).",
        f"- **Management Mode:** `{getattr(config, 'MANAGEMENT_MODE', 'legacy')}`",
        "- Each month below includes: (1) the chronological win/loss sequence, "
        "(2) the complete day-by-day calendar from the 1st to the end of the month (including `No trade` days), and "
        "(3) the 7-point TradingView chart coordinates for every single trade in that month.",
        "",
    ]
    for idx_m, mr in enumerate(chosen, 1):
        ym_str = mr["ym"]
        p_m = pd.Period(ym_str, freq="M")
        month_title = p_m.start_time.strftime("%B %Y")
        sub = mr["sub"].sort_values(["fill_time", "exit_time"]).reset_index(drop=True)
        out.append(f"## Month {idx_m}: {month_title} ({ym_str}) — {mr['n']} Trades "
                   f"({mr['wins']} Wins, {mr['losses']} Losses, {mr['be']} Break-Even | "
                   f"Full TP Win Rate: {fmt(mr['wr'], 1)}% | Net R: {fmt(mr['net'], 2)} R | PF: {fmt(mr['pf'], 2)})")
        if mr["n"] == 0:
            out.append("_No resolved trades in this calendar month._")
            out.append("")
            continue
        seq_parts = []
        for t_idx, (_, tr) in enumerate(sub.iterrows(), 1):
            short_res = outcome_short(tr)
            net_val = float(tr["net_r"])
            sign = "+" if net_val >= 0 else ""
            seq_parts.append(f"Trade {t_idx}: **{short_res}** ({sign}{fmt(net_val, 2)}R)")
        out.append("**Chronological Trade Sequence:** " + " -> ".join(seq_parts))
        out.append("")
        days = pd.date_range(p_m.start_time.date(), p_m.end_time.date(), freq="D")
        sub_dates = sub["fill_time"].dt.date.tolist()
        day_rows = []
        running_r = 0.0
        for d in days:
            d_date = d.date()
            d_str = d.strftime("%d %b %Y (%a)")
            matching_indices = [i for i, dt in enumerate(sub_dates) if dt == d_date]
            if not matching_indices:
                day_rows.append([d_str, "-", "-", "No trade", "-", "-", "-", fmt(running_r, 2)])
            else:
                for i in matching_indices:
                    tr = sub.iloc[i]
                    t_num = i + 1
                    net_v = float(tr["net_r"])
                    running_r += net_v
                    hb = str(tr.get("htf_bias", "") or "").lower()
                    if hb not in ("bull", "bear"):
                        hb = ("bull" if tr["side"] == "buy" else "bear") if tr["leg"] == "zone" else ("bull" if tr["side"] == "sell" else "bear")
                    ztf = str(tr.get("zone_tf", "") or "").upper()
                    leg_txt = f"zone {ztf}" if tr["leg"] == "zone" and ztf else str(tr["leg"])
                    model_str = f"{tr['pair']} ({leg_txt} {tr['kind']} {tr['side']} | HTF {hb.upper()})"
                    day_rows.append([
                        d_str,
                        f"Trade #{t_num}",
                        fclock(tr["fill_time"]),
                        model_str,
                        outcome_label(tr),
                        fmt(net_v, 2),
                        ftime(tr["exit_time"]),
                        fmt(running_r, 2),
                    ])
        out += table(["Calendar Date", "Order #", "Bot Entry Time", "Pair, Setup & HTF Trend",
                      "Resolution", "Trade Net R", "Resolved At (UTC)", "Running Month R"], day_rows)
        out.append("")
        out.append(f"**Chart-by-Chart Trade Anatomy for {month_title} ({mr['n']} Trades in Chronological Order):**")
        out.append("")
        for t_idx, (_, tr) in enumerate(sub.iterrows(), 1):
            out += _format_trade_chart_audit(t_idx, tr)
        out.append("")
    return out
def _paired_bootstrap_ci(diff_arr, n_boot=2000, seed=42):
    """Bootstrap 95% confidence interval for total Net R difference on paired trades."""
    diff = np.asarray(diff_arr, dtype=float)
    diff = diff[~np.isnan(diff)]
    n = len(diff)
    if n == 0:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    sums = diff[idx].sum(axis=1)
    lo, hi = np.percentile(sums, [2.5, 97.5])
    p_pos = float((sums > 0).mean() * 100.0)
    return float(lo), float(hi), p_pos
def render_phase1_to_3_diagnostics(res, zres, pres, win_months):
    """Render Phase 1 Management Ladder, Stress Tests, and Phase 2/3 ICT Confluence Tables."""
    out = []
    if len(res) == 0:
        return out
    # 1. Phase 1 Management Ladder Paired Comparison
    out += [
        "### Phase 1: Management Ladder Paired Comparison & Bootstrap 95% CI (Combined Static Card)",
        "Every preset below is evaluated on the exact same filled trades (zero frequency loss). "
        "Delta R and 95% Bootstrap CI are paired trade-by-trade against `legacy` (+235.75R baseline).",
        "",
    ]
    base_col = "r_legacy" if "r_legacy" in res.columns and res["r_legacy"].notna().any() else "net_r"
    base_r = res[base_col].astype(float)
    mgmt_rows = []
    ladder_specs = [
        ("legacy",   "Legacy (Asymmetric BE@2.0R on PB Sell & H1 Zone)"),
        ("be_10",    "Symmetric BE @ +1.0R (All Zone + PB, Full 3R TP)"),
        ("be_15",    "Symmetric BE @ +1.5R (All Zone + PB, Full 3R TP)"),
        ("be_20",    "Symmetric BE @ +2.0R (All Zone + PB, Full 3R TP)"),
        ("be_25",    "Symmetric BE @ +2.5R (All Zone + PB, Full 3R TP)"),
        ("be10_p20", "Symmetric BE @ +1.0R + 50% Partial @ +2.0R (Runner 3R)"),
        ("p15_be",   "50% Partial @ +1.5R + BE @ +1.5R (Runner 3R)"),
        ("be15_p20", "Symmetric BE @ +1.5R + 50% Partial @ +2.0R (Runner 3R)"),
        ("p20_be",   "50% Partial @ +2.0R + BE @ +2.0R (Runner 3R)"),
        ("be20_p25", "Symmetric BE @ +2.0R + 50% Partial @ +2.5R (Runner 3R)"),
        ("p25_be",   "50% Partial @ +2.5R + BE @ +2.5R (Runner 3R)"),
    ]
    for code, desc in ladder_specs:
        col = f"r_{code}"
        out_col = f"out_{code}"
        if col not in res.columns or res[col].isna().all():
            continue
        st = stats(res, col=col, out_col=out_col)
        dd_v, strk = dd_streak(res, col=col)
        diff = res[col].astype(float) - base_r
        delta_sum = float(diff.sum())
        lo, hi, p_win = _paired_bootstrap_ci(diff.to_numpy())
        min_yr = np.inf
        for y in range(2016, 2023):
            ysub = res[res["fill_time"].dt.year == y][col].astype(float)
            if len(ysub):
                min_yr = min(min_yr, float(ysub.sum()))
        net_2x = float((res[col].astype(float) - res["spread_cost_r"].astype(float)).sum())
        adopt_ok = (
            st["net"] > 235.75
            and st["pf"] >= 1.50
            and dd_v <= 19.47
            and min_yr >= 0.0
        )
        ci_txt = "[0.00, 0.00]" if code == "legacy" else f"[{fmt(lo, 1)}, {fmt(hi, 1)}] ({fmt(p_win, 1)}%)"
        mgmt_rows.append([
            f"`{code}`", desc, st["n"], fmt(st["net"], 2),
            ("+" if delta_sum >= 0 else "") + fmt(delta_sum, 2),
            ci_txt, fmt(st["pos_wr"], 1), fmt(st["exp"], 3), fmt(st["pf"], 2),
            fmt(dd_v, 2), strk, fmt(min_yr, 2), fmt(net_2x, 2),
            "PASS" if adopt_ok else "CHECK"
        ])
    out += table([
        "Code", "Management Rule", "Trades", "Net R", "Delta vs Legacy",
        "Paired 95% CI (P>0)", "Pos R %", "Exp (R)", "PF", "Max DD",
        "Streak", "Worst Year R", "2x Spread R", "Adoption Bar"
    ], mgmt_rows)
    out.append("")
    out += ["#### Management Ladder Impact by Stream (`legacy` vs BE & Partial Presets)"]
    m_stream_rows = []
    stream_cols = ["r_legacy", "r_be_15", "r_be_20", "r_be_25", "r_p15_be", "r_p20_be", "r_be20_p25", "r_p25_be"]
    for s_name, s_df in (
        ("D1/H4 Zone OB Buy", zres[(zres["zone_tf"].isin(["D1", "H4"])) & (zres["side"] == "buy")]),
        ("D1/H4 Zone OB Sell", zres[(zres["zone_tf"].isin(["D1", "H4"])) & (zres["side"] == "sell")]),
        ("H1 Zone Continuation", zres[zres["zone_tf"] == "H1"]),
        ("Pullback OB Buy", pres[(pres["kind"] == "ob") & (pres["side"] == "buy")]),
        ("Pullback OB Sell", pres[(pres["kind"] == "ob") & (pres["side"] == "sell")]),
        ("Pullback Breaker Buy", pres[(pres["kind"] == "breaker") & (pres["side"] == "buy")]),
        ("ALL COMBINED", res),
    ):
        if len(s_df) == 0:
            continue
        row_vals = [s_name, len(s_df)]
        for sc in stream_cols:
            row_vals.append(fmt(s_df[sc].sum(), 2) if sc in s_df.columns and s_df[sc].notna().any() else "n/a")
        m_stream_rows.append(row_vals)
    out += table([
        "Stream / Model", "Trades", "Legacy R", "BE@1.5 R", "BE@2.0 R", "BE@2.5 R",
        "50%@1.5+BE R", "50%@2.0+BE R", "BE@2.0+50%@2.5 R", "50%@2.5+BE R"
    ], m_stream_rows)
    out.append("")
    # 2. Trigger Perturbation & Zone Fill-1 vs Fill-2
    out += ["### Phase 1 Stress Tests: +-25% Trigger Perturbation & Zone Fill-1 vs Fill-2"]
    pert_rows = []
    for p_code, p_label in (
        ("be_075",  "BE @ +0.75R (-25% of 1.0R)"),
        ("be_10",   "BE @ +1.00R (Center 1.0R)"),
        ("be_125",  "BE @ +1.25R (+25% of 1.0R)"),
        ("be_1125", "BE @ +1.125R (-25% of 1.5R)"),
        ("be_15",   "BE @ +1.50R (Center 1.5R)"),
        ("be_1875", "BE @ +1.875R (+25% of 1.5R)"),
        ("be_20",   "BE @ +2.00R (Center 2.0R)"),
        ("be_25",   "BE @ +2.50R (+25% of 2.0R)"),
        ("p15_lo",  "50% Partial + BE @ +1.125R (-25% of 1.5R)"),
        ("p15_be",  "50% Partial + BE @ +1.50R (Center 1.5R)"),
        ("p15_hi",  "50% Partial + BE @ +1.875R (+25% of 1.5R)"),
        ("p20_lo",  "50% Partial + BE @ +1.50R (-25% of 2.0R)"),
        ("p20_be",  "50% Partial + BE @ +2.00R (Center 2.0R)"),
        ("p20_hi",  "50% Partial + BE @ +2.50R (+25% of 2.0R)"),
        ("p25_lo",  "50% Partial + BE @ +1.875R (-25% of 2.5R)"),
        ("p25_be",  "50% Partial + BE @ +2.50R (Center 2.5R)"),
        ("p25_hi",  "50% Partial + BE @ +2.80R (Capped +25% of 2.5R)"),
    ):
        col = f"r_{p_code}"
        out_col = f"out_{p_code}"
        if col not in res.columns or res[col].isna().all():
            continue
        st_p = stats(res, col=col, out_col=out_col)
        dd_p, _ = dd_streak(res, col=col)
        pert_rows.append([p_label, st_p["n"], fmt(st_p["net"], 2), fmt(st_p["exp"], 3),
                          fmt(st_p["pf"], 2), fmt(dd_p, 2)])
    out += table(["Perturbation Setting", "Trades", "Net R", "Expectancy", "PF", "Max DD R"], pert_rows)
    out.append("")
    if len(zres) and "fill1_net_r" in zres.columns:
        z_f2_net = float(zres["net_r"].sum())
        z_f1_valid = zres["fill1_net_r"].dropna()
        z_f1_net = float(z_f1_valid.sum()) if len(z_f1_valid) else np.nan
        out.append(f"- **Zone Fill Convention Stress Test:** Default Fill-2 (next M15 open) = "
                   f"**{fmt(z_f2_net, 2)} R** ({len(zres)} trades) vs. In-Bar Limit Fill-1 = "
                   f"**{fmt(z_f1_net, 2)} R** ({len(z_f1_valid)} trades).")
    if "unpadded_net_r" in res.columns and res["min_risk_padded"].any():
        pad_sub = res[res["min_risk_padded"]]
        pad_actual = float(pad_sub["net_r"].sum())
        pad_unp = pad_sub["unpadded_net_r"].dropna()
        out.append(f"- **Min-Risk Stop Padding Counterfactual ({len(pad_sub)} padded trades):** "
                   f"Padded Net R = **{fmt(pad_actual, 2)} R** | "
                   f"If left at raw structural stop (unpadded) = **{fmt(float(pad_unp.sum()), 2)} R** "
                   f"(median unpadded spread/risk ratio = `{fmt(float(pad_sub['unpadded_spread_ratio'].median()), 2)}`).")
    out.append("")
    # 3. Phase 2 & 3 ICT Confluence Telemetry
    out += [
        "### Phase 2 & 3: ICT Confluence Diagnostic Telemetry (2016-2019 vs 2020-2022 & Buy vs Sell)",
        "Logged non-invasively across all resolved trades to verify cross-period stability before enabling any gate.",
        "",
    ]
    def _conf_row(label_c, sub_df):
        if len(sub_df) == 0:
            return [label_c, 0, "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a"]
        st_all = stats(sub_df)
        p1 = sub_df[sub_df["fill_time"].dt.year <= 2019]
        p2 = sub_df[sub_df["fill_time"].dt.year >= 2020]
        b_df = sub_df[sub_df["side"] == "buy"]
        s_df = sub_df[sub_df["side"] == "sell"]
        st1, st2 = stats(p1), stats(p2)
        stb, sts = stats(b_df), stats(s_df)
        return [
            label_c, st_all["n"], fmt(st_all["net"], 2), fmt(st_all["exp"], 3), fmt(st_all["pf"], 2),
            f"{st1['n']} ({fmt(st1['exp'], 3)}R)",
            f"{st2['n']} ({fmt(st2['exp'], 3)}R)",
            f"{stb['n']} ({fmt(stb['exp'], 3)}R)",
            f"{sts['n']} ({fmt(sts['exp'], 3)}R)",
        ]
    conf_rows = []
    conf_rows.append(_conf_row("Stop Hygiene: Natural Stop (Not Padded)", res[~res["min_risk_padded"]]))
    conf_rows.append(_conf_row("Stop Hygiene: Min-Risk Padded Stop", res[res["min_risk_padded"]]))
    pb_dr = pres["dest_room_r"]
    conf_rows.append(_conf_row("PB Dest Room: < 3.0R (Blocked by HTF Zone)", pres[pb_dr.notna() & (pb_dr < 3.0)]))
    conf_rows.append(_conf_row("PB Dest Room: 3.0R - 3.5R", pres[pb_dr.notna() & (pb_dr >= 3.0) & (pb_dr < 3.5)]))
    conf_rows.append(_conf_row("PB Dest Room: >= 3.5R (Clear Path)", pres[pb_dr.notna() & (pb_dr >= 3.5)]))
    conf_rows.append(_conf_row("PB Path: Fresh Opposing H1 Zone in Path", pres[pres["opp_h1_in_path"]]))
    conf_rows.append(_conf_row("PB Path: No Opposing H1 Zone in Path", pres[~pres["opp_h1_in_path"]]))
    z_deep = zres[zres["zone_tf"].isin(["D1", "H4"])]
    conf_rows.append(_conf_row("D1/H4 Zone: Inside Clean H1 Refined Base", z_deep[z_deep["h1_refined_ok"]]))
    conf_rows.append(_conf_row("D1/H4 Zone: Outside/No Clean H1 Base", z_deep[~z_deep["h1_refined_ok"]]))
    z_dp = z_deep["deal_pct"]
    conf_rows.append(_conf_row("D1/H4 Zone Deal Range: < 50% (Shallow)", z_deep[z_dp.notna() & (z_dp < 50.0)]))
    conf_rows.append(_conf_row("D1/H4 Zone Deal Range: >= 50% (Discount/Premium)", z_deep[z_dp.notna() & (z_dp >= 50.0)]))
    p_dp = pres["deal_pct"]
    conf_rows.append(_conf_row("PB Macro Range: < 50% (Past Equilibrium)", pres[p_dp.notna() & (p_dp < 50.0)]))
    conf_rows.append(_conf_row("PB Macro Range: 50% - 62%", pres[p_dp.notna() & (p_dp >= 50.0) & (p_dp < 62.0)]))
    conf_rows.append(_conf_row("PB Macro Range: 62% - 79% (Macro OTE)", pres[p_dp.notna() & (p_dp >= 62.0) & (p_dp <= 79.0)]))
    conf_rows.append(_conf_row("PB Macro Range: > 79% (Deep Origin)", pres[p_dp.notna() & (p_dp > 79.0)]))
    p_ote = pres["local_ote_pct"]
    conf_rows.append(_conf_row("PB Local M15 Leg: < 50%", pres[p_ote.notna() & (p_ote < 50.0)]))
    conf_rows.append(_conf_row("PB Local M15 Leg: 50% - 62%", pres[p_ote.notna() & (p_ote >= 50.0) & (p_ote < 62.0)]))
    conf_rows.append(_conf_row("PB Local M15 Leg: 62% - 79% (Local OTE)", pres[p_ote.notna() & (p_ote >= 62.0) & (p_ote <= 79.0)]))
    conf_rows.append(_conf_row("PB Local M15 Leg: > 79%", pres[p_ote.notna() & (p_ote > 79.0)]))
    conf_rows.append(_conf_row("OB + FVG Overlap: True (Unicorn / Imbalance)", res[res["fvg_overlap"]]))
    conf_rows.append(_conf_row("OB + FVG Overlap: False (Plain OB)", res[~res["fvg_overlap"]]))
    conf_rows.append(_conf_row("PB Ceiling Liquidity Sweep + Reclaim: True", pres[pres["sweep_reclaim"]]))
    conf_rows.append(_conf_row("PB Ceiling Liquidity Sweep + Reclaim: False", pres[~pres["sweep_reclaim"]]))
    disp = res["disp_body_atr"]
    conf_rows.append(_conf_row("CHoCH Displacement Body: < 0.5 ATR", res[disp.notna() & (disp < 0.5)]))
    conf_rows.append(_conf_row("CHoCH Displacement Body: 0.5 - 1.0 ATR", res[disp.notna() & (disp >= 0.5) & (disp < 1.0)]))
    conf_rows.append(_conf_row("CHoCH Displacement Body: >= 1.0 ATR", res[disp.notna() & (disp >= 1.0)]))
    for kz_name in ("London_KZ", "NY_AM_KZ", "London_Close_KZ", "Asian_KZ", "Outside_KZ"):
        conf_rows.append(_conf_row(f"NY Local Time Killzone: {kz_name}", res[res["killzone"] == kz_name]))
    out += table([
        "Confluence / Bucket", "Trades", "Net R", "Exp (R)", "PF",
        "2016-19 N (Exp)", "2020-22 N (Exp)", "Buy N (Exp)", "Sell N (Exp)"
    ], conf_rows)
    out.append("")
    return out
def main():
    label = os.environ.get("REPORT_LABEL", "run")
    report_mode = os.environ.get("REPORT_MODE", "main").strip().lower()
    if "--anatomy" in sys.argv:
        report_mode = "anatomy"
    elif "--anatomy-p1" in sys.argv:
        report_mode = "anatomy_p1"
    elif "--anatomy-p2" in sys.argv:
        report_mode = "anatomy_p2"
    expect = [p for p in os.environ.get("EXPECT_PAIRS", "").split(",") if p] or ALL_PAIRS
    frames, funnels, looks = [], {}, {}
    for p in expect:
        df = read_trades(p)
        if df is not None:
            frames.append(df)
        fp = DATA / f"{p}_funnel.json"
        if fp.exists():
            funnels[p] = json.loads(fp.read_text())
        lp = DATA / f"{p}_lookahead.json"
        if lp.exists():
            looks[p] = json.loads(lp.read_text())
    full = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=so.TRADE_COLS)
    if frames:
        for c in TIME_COLS:
            full[c] = pd.to_datetime(full[c], utc=True, errors="coerce")
    else:
        full["leg"] = full["leg"].astype(object)
    zall, zres = card(full, "zone", "static")
    zlall, zlres = card(full, "zone", "liquidity")
    pall, pres = card(full, "pullback", "static")
    z_deep_all = zall[zall["zone_tf"].isin(["D1", "H4"])]
    z_deep_res = zres[zres["zone_tf"].isin(["D1", "H4"])]
    z_h1_all = zall[zall["zone_tf"] == "H1"]
    z_h1_res = zres[zres["zone_tf"] == "H1"]
    call = pd.concat([zall, pall], ignore_index=True)
    cres = pd.concat([zres, pres], ignore_index=True)
    if bool(getattr(config, "ENFORCE_ONE_AT_A_TIME", False)):
        cres = cres[cres["kept_1at"]]
        zres = zres[zres["kept_1at"]]
        pres = pres[pres["kept_1at"]]
        z_deep_res = z_deep_res[z_deep_res["kept_1at"]]
        z_h1_res = z_h1_res[z_h1_res["kept_1at"]]
    allr, res = call, cres
    miss = [p for p in expect if p not in looks]
    failed = [p for p, v in looks.items() if not v.get("pass")]
    look_ok = (not miss) and (not failed) and bool(looks)
    active_mgmt = str(getattr(config, "MANAGEMENT_MODE", "legacy") or "legacy")
    L = [f"# Phase 4 cycle report: {label}", ""]
    if look_ok:
        dec = sum(v.get("decisions", 0) for v in looks.values())
        cuts = min(v.get("cuts", 0) for v in looks.values())
        L.append(f"**LOOKAHEAD: PASS** - {len(expect)} pair(s), {cuts} cut(s) each, "
                 f"{dec} decisions compared, no decision changed when the future was cut.")
    else:
        L.append(f"**LOOKAHEAD: FAIL** - missing: {miss or 'none'}; failed: {failed or 'none'}. "
                 "IGNORE ALL NUMBERS BELOW.")
    L += ["",
          f"- Practice years only: start of data to {config.PRACTICE_END}. Exam years are sealed.",
          "- Bad days are NOT excluded in this run.",
          "- Variant: plain (no FVG).",
          f"- Active Management Mode: `{active_mgmt}`.",
          "- MAIN scorecard (sections 1-7): COMBINED (Zone + Pullback) at static 1:3 target.",
          "- Separate ZONE (D1/H4 Deep vs. H1 Continuation vs. All With-Trend), ZONE liquidity, and PULLBACK static 1:3 scorecards are "
          "shown in Signal Frequency and Extras.",
          "- Full 78-Month Day-by-Day & Chart-by-Chart Trade Anatomy is written to `report_cycle_" + label + "_monthly_anatomy.md`.",
          ""]
    s = stats(res)
    L += ["## 1. Executive Summary"]
    L += table(["Metric", "Value"], [
        ["Total Net R", fmt(s["net"])],
        ["Full Target (+3R) Win Rate %", fmt(s["wr"], 1)],
        ["Positive Net R Trade Rate % (incl. Partial Wins)", fmt(s["pos_wr"], 1)],
        ["Profit Factor", fmt(s["pf"])],
        ["Verdict", verdict(look_ok, s)]])
    L.append("")
    L += ["## 2. Core Performance Metrics"]
    n_open = int((allr["outcome"] == "open_at_cutoff").sum())
    L += table(["Metric", "Value"], [
        ["Expectancy (net R per trade)", fmt(s["exp"], 3)],
        ["Total Trades (resolved)", s["n"]],
        ["Avg R:R (avg winning net R / avg losing net R)", fmt(s["rr"])],
        ["open_at_cutoff (not in the numbers)", n_open]])
    L.append("")
    dd, streak = dd_streak(res)
    L += ["## 3. Drawdown & Risk"]
    L += table(["Metric", "Value"], [["Max Drawdown R", fmt(dd)],
                                      ["Longest Losing Streak (trades)", streak]])
    L.append("")
    L += ["## 4. Signal Frequency"]
    t_start = pd.Timestamp(DATA_START, tz="UTC")
    t_end = pd.Timestamp(config.PRACTICE_END, tz="UTC")
    win_months = (t_end - t_start).days / 30.44
    z_per_month = len(zres) / win_months if win_months > 0 else np.nan
    z_deep_pm = len(z_deep_res) / win_months if win_months > 0 else np.nan
    z_h1_pm = len(z_h1_res) / win_months if win_months > 0 else np.nan
    pb_per_month = len(pres) / win_months if win_months > 0 else np.nan
    comb_trades = len(res)
    comb_per_month = comb_trades / win_months if win_months > 0 else np.nan
    comb_per_78 = comb_trades / FIXED_MONTHS
    comb_net_static = float(res["net_r"].sum())
    if len(res):
        per_pair = comb_per_month / max(len(expect), 1)
        first_fill = res["fill_time"].min()
        since_months = max((t_end - first_fill).days / 30.44, 1.0)
        per_month_since = len(res) / since_months
        first_txt = first_fill.strftime("%Y-%m-%d")
        within = float((res["dur_hours"] <= 24).mean() * 100)
    else:
        per_pair = per_month_since = within = np.nan
        first_txt = "n/a"
    L += table(["Metric", "Value"], [
        [f"COMBINED trades per month (Zone + Pullback, {fmt(win_months, 2)} months)",
         fmt(comb_per_month, 2)],
        ["COMBINED trades per month (strict 78-calendar-month denominator)",
         fmt(comb_per_78, 2)],
        [f"ALL WITH-TREND ZONE trades per month (D1 + H4 + H1, {fmt(win_months, 2)} months)",
         fmt(z_per_month, 2)],
        [f"  -> D1/H4 Deep Zone trades per month ({len(z_deep_res)} trades total)",
         fmt(z_deep_pm, 2)],
        [f"  -> H1 Continuation Zone trades per month ({len(z_h1_res)} trades total)",
         fmt(z_h1_pm, 2)],
        [f"PULLBACK trades per month, all pairs ({fmt(win_months, 2)} months)",
         fmt(pb_per_month, 2)],
        ["COMBINED total resolved trades (Zone + Pullback)", comb_trades],
        ["COMBINED Net R (Zone static 1:3 + Pullback static 1:3)", fmt(comb_net_static, 2)],
        [f"COMBINED trades per month, since first trade ({first_txt})",
         fmt(per_month_since, 2)],
        [f"COMBINED trades per month per pair ({len(expect)} pair(s))", fmt(per_pair, 2)],
        ["% closed within 24h (Combined trades)", fmt(within, 1)]])
    L.append("")
    pair_net = {}
    for p in expect:
        t = res[res["pair"] == p]
        pair_net[p] = (float(t["net_r"].sum()) if len(t) else 0.0, len(t))
    ranked = sorted([p for p in expect if pair_net[p][1] > 0], key=lambda p: -pair_net[p][0])
    L += ["## 5. Performance by Pair"]
    if len(ranked) < 6:
        L.append("(fewer than 6 pairs with trades: the Top and Bottom lists overlap)")
    top, bot = ranked[:3], list(reversed(ranked[-3:]))
    L.append("**Top 3**")
    L += table(["Pair", "Trades", "Net R"],
               [[p + (" (assumed spread)" if p in NEW_PAIRS else ""), pair_net[p][1],
                 fmt(pair_net[p][0])] for p in top])
    L.append("")
    L.append("**Bottom 3**")
    L += table(["Pair", "Trades", "Net R"],
               [[p + (" (assumed spread)" if p in NEW_PAIRS else ""), pair_net[p][1],
                 fmt(pair_net[p][0])] for p in bot])
    L.append("")
    L += ["## 6. Performance by Year (by entry year; exam years sealed)"]
    yrows = []
    for y in range(2016, 2027):
        if y >= 2023:
            yrows.append([str(y), "sealed", "-", "-", "-"])
            continue
        sub = res[res["fill_time"].dt.year == y] if len(res) else res
        st = stats(sub)
        name = "2022 (Jan-Jun only)" if y == 2022 else str(y)
        yrows.append([name, st["n"], fmt(st["net"]), fmt(st["wr"], 1), fmt(st["pf"])])
    L += table(["Year", "Trades", "Net R", "Win %", "PF"], yrows)
    L.append("")
    # Section 7: Monthly Performance
    L += ["## 7. Monthly Consistency & Individual Month Spotlight (15+ Trades)"]
    all_months = pd.period_range("2016-01", "2022-06", freq="M")
    if len(res):
        res_m = res.copy()
        res_m["ym"] = res_m["fill_time"].dt.tz_localize(None).dt.to_period("M")
    else:
        res_m = res.copy()
        res_m["ym"] = pd.Series(dtype="period[M]")
    m_counts = []
    m_records = []
    for ym in all_months:
        sub = res_m[res_m["ym"] == ym] if len(res_m) else res_m
        st = stats(sub)
        wins, losses, be = win_loss_be_counts(sub)
        m_counts.append(st["n"])
        m_records.append({
            "ym": str(ym), "sub": sub, "n": st["n"], "wins": wins,
            "losses": losses, "be": be, "wr": st["wr"], "net": st["net"],
            "pf": st["pf"], "exp": st["exp"]
        })
    m_arr = np.array(m_counts, dtype=float)
    active_arr = m_arr[m_arr > 0] if (m_arr > 0).any() else m_arr
    L += table(["Monthly Consistency Metric (78 Calendar Months: 2016-01 to 2022-06)", "Value"], [
        ["Average resolved trades / month (all 78 months)", fmt(float(m_arr.mean()), 2)],
        ["Median resolved trades / month (all 78 months)", fmt(float(np.median(m_arr)), 1)],
        ["Median resolved trades / month (active trading months only)",
         fmt(float(np.median(active_arr)), 1)],
        ["Months with >= 15 trades (count and % of 78 months)",
         f"{int((m_arr >= 15).sum())} / {len(m_arr)} ({fmt(float((m_arr >= 15).mean() * 100), 1)}%)"],
        ["Months with >= 16 trades (count and % of 78 months)",
         f"{int((m_arr >= 16).sum())} / {len(m_arr)} ({fmt(float((m_arr >= 16).mean() * 100), 1)}%)"],
        ["Lowest monthly trade count (all 78 months / post-2016 warmup)",
         f"{int(m_arr.min())} / {int(m_arr[12:].min()) if len(m_arr) > 12 else int(m_arr.min())}"],
        ["Highest monthly trade count", f"{int(m_arr.max())}"],
        ["Positive Net R months (out of active trading months)",
         f"{sum(1 for r in m_records if r['n'] > 0 and r['net'] > 0)} / "
         f"{sum(1 for r in m_records if r['n'] > 0)}"]
    ])
    L.append("")
    qual_15 = [r for r in m_records if r["n"] >= 15]
    if qual_15:
        qual_sorted = sorted(qual_15, key=lambda x: x["n"])
        rep_m = qual_sorted[len(qual_sorted) // 2]
        peak_m = qual_sorted[-1]
        first_15 = qual_15[0]
        spotlights = [("Typical (Median) 15+ Trade Month", rep_m),
                      ("First 15+ Trade Month", first_15),
                      ("Highest-Volume 15+ Trade Month", peak_m)]
        L.append("### Single-Month Deep Spotlight (Wins vs. Losses on 15+ Trade Months)")
        s_rows = []
        for label_m, mr in spotlights:
            sub = mr["sub"]
            gross_sum = float(sub["r_gross"].sum()) if len(sub) else 0.0
            sp_sum = float(sub["spread_cost_r"].sum()) if len(sub) else 0.0
            s_rows.append([
                label_m, mr["ym"], mr["n"], mr["wins"], mr["losses"], mr["be"],
                fmt(mr["wr"], 1), fmt(gross_sum, 2), fmt(sp_sum, 2),
                fmt(mr["net"], 2), fmt(mr["pf"], 2)
            ])
        L += table(["Spotlight Type", "Month", "Trades", "Wins", "Losses (-1R)",
                    "Break-Even (0R gross)", "Win %", "Gross R", "Spread Cost R",
                    "Net R", "PF"], s_rows)
        L.append("")
        L.append(f"**Entry Model Breakdown Inside Spotlight Month ({rep_m['ym']}: "
                 f"{rep_m['n']} Trades, {rep_m['wins']} Wins, {rep_m['losses']} Losses, "
                 f"{rep_m['be']} Break-Even, Net {fmt(rep_m['net'], 2)} R)**")
        ms_rows = []
        sub_rep = rep_m["sub"]
        for leg_name, kind_name, side_name, label_g in (
            ("zone", "ob", "buy", "Zone OB Buy (D1+H4+H1)"),
            ("zone", "ob", "sell", "Zone OB Sell (D1+H4+H1)"),
            ("pullback", "ob", "buy", "Pullback OB Buy"),
            ("pullback", "ob", "sell", "Pullback OB Sell"),
            ("pullback", "breaker", "buy", "Pullback Breaker Buy"),
        ):
            g_sub = sub_rep[(sub_rep["leg"] == leg_name)
                            & (sub_rep["kind"] == kind_name)
                            & (sub_rep["side"] == side_name)]
            if len(g_sub) == 0:
                continue
            gw, gl, gbe = win_loss_be_counts(g_sub)
            gst = stats(g_sub)
            ms_rows.append([label_g, gst["n"], gw, gl, gbe, fmt(gst["wr"], 1), fmt(gst["net"], 2)])
        L += table(["Model", "Trades", "Wins", "Losses", "Break-Even", "Win %", "Net R"], ms_rows)
        L.append("")
        L.append(f"### All {len(qual_15)} Individual Months with 15+ Trades (Chronological)")
        q_rows = []
        for mr in qual_15:
            q_rows.append([
                mr["ym"], mr["n"], mr["wins"], mr["losses"], mr["be"],
                fmt(mr["wr"], 1), fmt(mr["net"], 2), fmt(mr["exp"], 3), fmt(mr["pf"], 2)
            ])
        L += table(["Month", "Trades", "Wins", "Losses", "Break-Even", "Win %",
                    "Net R", "Expectancy", "PF"], q_rows)
        L.append("")
    # Extras
    L += ["## Extras", "", "### Scorecards side by side (With-Trend Zones vs. Pullbacks)"]
    cards = (
        ("COMBINED (All Zones + Pullbacks) (MAIN)", call, cres),
        ("ZONE ALL WITH-TREND (D1 + H4 + H1) static 1:3", zall, zres),
        ("  -> ZONE D1/H4 Deep Only static 1:3", z_deep_all, z_deep_res),
        ("  -> ZONE H1 Continuation Only static 1:3", z_h1_all, z_h1_res),
        ("ZONE liquidity target (D1 + H4 + H1)", zlall, zlres),
        ("PULLBACK Counter-Trend static 1:3", pall, pres),
    )
    r1, r2 = [], []
    for name, a, r in cards:
        st = stats(r)
        d2, _ = dd_streak(r)
        fl = a[a["status"] == "filled"]
        tr = float(fl["target_r"].mean()) if len(fl) else np.nan
        tpm = st["n"] / win_months if win_months > 0 else np.nan
        r1.append([name, st["n"], fmt(tpm, 2), fmt(st["net"]), fmt(st["wr"], 1), fmt(st["exp"], 3)])
        r2.append([name, fmt(st["pf"]), fmt(d2), fmt(tr, 2),
                   int((a["outcome"] == "open_at_cutoff").sum())])
    L += table(["Scorecard", "Trades", "Trades/mo", "Net R", "Win %", "Expectancy"], r1)
    L.append("")
    L += table(["Scorecard", "PF", "Max DD R", "Avg planned target (R)", "Open at cutoff"], r2)
    L.append("")
    L.append(f"- Pullback check against V1 (only meaningful in a zt or v1 run): V1 had "
             f"{V1_PULLBACK[0]} trades, {fmt(V1_PULLBACK[1])} R. This run: {len(pres)} trades, "
             f"{fmt(pres['net_r'].sum())} R. Equal: "
             f"{'YES' if (len(pres) == V1_PULLBACK[0] and abs(float(pres['net_r'].sum()) - V1_PULLBACK[1]) < 0.015) else 'NO'}.")
    L.append("")
    # Phase 1-3 Management Ladder, Stress Tests, and ICT Confluence Telemetry
    L += render_phase1_to_3_diagnostics(res, zres, pres, win_months)
    L += ["### Buy / sell split by entry model"]
    for name, a, r in (
        ("COMBINED (All Zones + Pullbacks) (MAIN)", call, cres),
        ("ZONE ALL WITH-TREND (D1 + H4 + H1) static 1:3", zall, zres),
        ("ZONE D1/H4 Deep Only static 1:3", z_deep_all, z_deep_res),
        ("ZONE H1 Continuation Only static 1:3", z_h1_all, z_h1_res),
        ("PULLBACK Counter-Trend static 1:3", pall, pres),
    ):
        L.append(f"**{name}**")
        L += table(["Group", "Trades", "Win %", "Net R", "Expectancy"], split_rows(r))
        L.append("")
    # MFE / MAE Telemetry
    L += ["### Trade-Path MFE / MAE & Milestone Reversal Diagnostics (Static 1:3)"]
    mfe_groups = [
        ("D1/H4 Zone OB Buy", z_deep_res[(z_deep_res["kind"] == "ob") & (z_deep_res["side"] == "buy")]),
        ("D1/H4 Zone OB Sell", z_deep_res[(z_deep_res["kind"] == "ob") & (z_deep_res["side"] == "sell")]),
        ("H1 Cont. Zone OB Buy", z_h1_res[(z_h1_res["kind"] == "ob") & (z_h1_res["side"] == "buy")]),
        ("H1 Cont. Zone OB Sell", z_h1_res[(z_h1_res["kind"] == "ob") & (z_h1_res["side"] == "sell")]),
        ("Pullback OB Buy", pres[(pres["kind"] == "ob") & (pres["side"] == "buy")]),
        ("Pullback OB Sell", pres[(pres["kind"] == "ob") & (pres["side"] == "sell")]),
        ("Pullback Breaker Buy", pres[(pres["kind"] == "breaker") & (pres["side"] == "buy")]),
    ]
    mfe_rows = []
    for label_g, sub in mfe_groups:
        if len(sub) == 0:
            continue
        wins, losses, be = win_loss_be_counts(sub)
        non_tgt = sub[~sub["outcome"].isin(["target", "partial_target"])]
        n_nt = len(non_tgt)
        mfe_all = float(sub["mfe_r"].median()) if sub["mfe_r"].notna().any() else np.nan
        mae_all = float(sub["mae_r"].median()) if sub["mae_r"].notna().any() else np.nan
        w_sub = sub[sub["outcome"].isin(["target", "partial_target"])]
        mae_win = float(w_sub["mae_r"].median()) if len(w_sub) and w_sub["mae_r"].notna().any() else np.nan
        r10 = int((non_tgt["mfe_r"] >= 1.0).sum()) if n_nt else 0
        r15 = int((non_tgt["mfe_r"] >= 1.5).sum()) if n_nt else 0
        r20 = int((non_tgt["mfe_r"] >= 2.0).sum()) if n_nt else 0
        r25 = int((non_tgt["mfe_r"] >= 2.5).sum()) if n_nt else 0
        mfe_rows.append([
            label_g, len(sub), wins, losses, be,
            fmt(mfe_all, 2), fmt(mae_all, 2), fmt(mae_win, 2),
            f"{r10} ({fmt(r10 / n_nt * 100, 1)}%)" if n_nt else "0",
            f"{r15} ({fmt(r15 / n_nt * 100, 1)}%)" if n_nt else "0",
            f"{r20} ({fmt(r20 / n_nt * 100, 1)}%)" if n_nt else "0",
            f"{r25} ({fmt(r25 / n_nt * 100, 1)}%)" if n_nt else "0",
        ])
    L += table(["Model", "Trades", "Wins", "Losses", "BE (0R)", "Med MFE (R)",
                "Med MAE (R)", "Win Med MAE (R)", "Non-Win >=1.0R", "Non-Win >=1.5R",
                "Non-Win >=2.0R", "Non-Win >=2.5R"], mfe_rows)
    L.append("")
    # Sub-period
    L += ["### Sub-Period Comparison by Entry Model (2016-2019 vs. 2020-June 2022)"]
    sp_rows = []
    for label_g, sub in mfe_groups:
        if len(sub) == 0:
            continue
        p1 = sub[sub["fill_time"].dt.year <= 2019]
        p2 = sub[sub["fill_time"].dt.year >= 2020]
        s1_st, s2_st = stats(p1), stats(p2)
        sp_rows.append([
            label_g,
            s1_st["n"], fmt(s1_st["wr"], 1), fmt(s1_st["net"], 2), fmt(s1_st["exp"], 3),
            s2_st["n"], fmt(s2_st["wr"], 1), fmt(s2_st["net"], 2), fmt(s2_st["exp"], 3),
        ])
    L += table(["Model", "2016-19 Trades", "2016-19 Win %", "2016-19 Net R", "2016-19 Exp",
                "2020-22 Trades", "2020-22 Win %", "2020-22 Net R", "2020-22 Exp"], sp_rows)
    L.append("")
    # Pending Order Age & Session Diagnostics
    if len(res):
        L += ["### Setup Freshness: Pending Order Wait Time (Placed -> Fill Hours)"]
        age_h = (res["fill_time"] - res["placed_time"]).dt.total_seconds() / 3600.0
        age_rows = []
        for b_label, mask in (
            ("<= 4h (16 M15 bars)", age_h <= 4.0),
            ("4h - 12h", (age_h > 4.0) & (age_h <= 12.0)),
            ("12h - 24h", (age_h > 12.0) & (age_h <= 24.0)),
            ("24h - 72h (1-3 days)", (age_h > 24.0) & (age_h <= 72.0)),
            ("> 72h (> 3 days)", age_h > 72.0),
        ):
            sub_a = res[mask]
            st_a = stats(sub_a)
            pb_s = sub_a[(sub_a["leg"] == "pullback") & (sub_a["side"] == "sell")]
            st_pbs = stats(pb_s)
            age_rows.append([
                b_label, st_a["n"], fmt(st_a["wr"], 1), fmt(st_a["net"], 2),
                fmt(st_a["exp"], 3), st_pbs["n"], fmt(st_pbs["net"], 2), fmt(st_pbs["exp"], 3)
            ])
        L += table(["Order Wait Bucket", "All Trades", "All Win %", "All Net R", "All Exp",
                    "PB Sell Trades", "PB Sell Net R", "PB Sell Exp"], age_rows)
        L.append("")
        L += ["### Session Timing Breakdown (by UTC Order Placement & Fill Hour)"]
        sess_rows = []
        p_hr = res["placed_time"].dt.hour
        for s_label, smask in (
            ("Asian (00:00 - 05:59 UTC)", p_hr < 6),
            ("London (06:00 - 11:59 UTC)", (p_hr >= 6) & (p_hr < 12)),
            ("London/NY Overlap (12:00 - 15:59 UTC)", (p_hr >= 12) & (p_hr < 16)),
            ("NY Afternoon (16:00 - 19:59 UTC)", (p_hr >= 16) & (p_hr < 20)),
            ("Late NY (20:00 - 23:59 UTC)", p_hr >= 20),
        ):
            sub_s = res[smask]
            st_s = stats(sub_s)
            pb_s = sub_s[(sub_s["leg"] == "pullback") & (sub_s["side"] == "sell")]
            st_pbs = stats(pb_s)
            pb_b = sub_s[(sub_s["leg"] == "pullback") & (sub_s["side"] == "buy")]
            st_pbb = stats(pb_b)
            z_sub = sub_s[sub_s["leg"] == "zone"]
            st_z = stats(z_sub)
            sess_rows.append([
                s_label, st_s["n"], fmt(st_s["net"], 2), fmt(st_s["exp"], 3),
                st_pbs["n"], fmt(st_pbs["net"], 2), fmt(st_pbs["exp"], 3),
                st_pbb["n"], fmt(st_pbb["net"], 2),
                st_z["n"], fmt(st_z["net"], 2)
            ])
        L += table(["Placed Session (UTC)", "All Trades", "All Net R", "All Exp",
                    "PB Sell N", "PB Sell Net R", "PB Sell Exp",
                    "PB Buy N", "PB Buy Net R", "Zone N", "Zone Net R"], sess_rows)
        L.append("")
    L += ["### All pairs (MAIN card: Combined Zone + Pullback, static 1:3)"]
    prow, warns = [], []
    for p in expect:
        t = res[res["pair"] == p]
        a = allr[allr["pair"] == p]
        filled_p = a[a["status"] == "filled"]
        n_skip_sp = int((a["status"] == "skipped_spread").sum())
        st = stats(t)
        sp = filled_p["spread_cost_r"].dropna()
        avg_sp = float(sp.mean()) if len(sp) else np.nan
        lab = "assumed" if p in NEW_PAIRS else "measured"
        prow.append([p, lab, len(a), int((a["status"] == "filled").sum()), n_skip_sp, st["n"],
                     fmt(st["wr"], 1), fmt(st["net"]), fmt(st["pf"]), fmt(avg_sp, 3)])
        if p in NEW_PAIRS and st["n"] and st["net"] > 0:
            doubled = st["net"] - float(t["spread_cost_r"].sum())
            if doubled <= 0:
                warns.append(f"WARNING {p}: assumed-spread pair. Net {fmt(st['net'])} R with the "
                             f"assumed spread, but {fmt(doubled)} R if the spread were twice as "
                             f"wide. Do not trust this pair's result.")
            elif p in top:
                warns.append(f"Note {p}: assumed-spread pair in the Top 3 "
                             f"(doubled-spread net {fmt(doubled)} R).")
    L += table(["Pair", "Spread", "Orders", "Filled", "Skipped (spread)", "Resolved", "Win %",
                "Net R", "PF", "Avg spread cost, filled trades (R)"], prow)
    L.append("")
    for w in warns:
        L.append(f"- {w}")
    if warns:
        L.append("")
    filled_all = full[full["status"] == "filled"]
    limit = float(config.MAX_SPREAD_RISK_RATIO)
    if len(filled_all):
        mx = float(filled_all["spread_cost_r"].max())
        if mx > limit + 1e-9:
            L.append(f"- CHECK FAILED: a filled trade has spread cost {fmt(mx, 3)} R, above the "
                     f"{fmt(limit, 2)} limit. This is a bug. Do not trust the numbers.")
        else:
            L.append(f"- Check passed: highest spread cost among filled trades is "
                     f"{fmt(mx, 3)} R (limit {fmt(limit, 2)}).")
        L.append("")
    L += ["### Pair funnel: pullbacks (why some pairs have few or no orders)"]
    frows = []
    for p in expect:
        fj = funnels.get(p)
        if fj is None:
            frows.append([p, "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a"])
            continue
        c = fj.get("counts", {})
        frows.append([p, fj.get("bars", "n/a"), fj.get("decisions", "n/a"),
                      fj.get("flips", "n/a"), c.get("htf_arm", 0), c.get("pullbacks", 0),
                      c.get("setups", 0), fj.get("orders", 0)])
    L += table(["Pair", "Bars", "Decisions", "Bias flips", "HTF arms", "Pullbacks", "Setups",
                "Orders"], frows)
    L.append("")
    L += ["### Pair funnel: zone trades"]
    zrows = []
    for p in expect:
        fj = funnels.get(p)
        if fj is None:
            zrows.append([p, "n/a", "n/a", "n/a", "n/a", "n/a"])
            continue
        c = fj.get("counts", {})
        zrows.append([p, c.get("z_scan", 0), c.get("h1_scan", 0),
                      c.get("z_setups", 0) + c.get("h1_setups", 0),
                      fj.get("zone_orders", 0),
                      int((zall[zall["pair"] == p]["status"] == "filled").sum())])
    L += table(["Pair", "D1/H4 touches (scans)", "H1 touches (scans)", "Zone setups (all)",
                "Zone orders (all)", "Filled (static)"], zrows)
    L.append("")
    L += ["### Stacking vs one-at-a-time (kept per pair)"]
    kept = res[res["kept_1at"]]
    zkept = zres[zres["kept_1at"]]
    crow = []
    for name, t in (("Combined Stacking (all)", res),
                    ("Combined One-at-a-time", kept),
                    ("Zone All With-Trend Stacking (D1+H4+H1)", zres),
                    ("Zone All With-Trend One-at-a-time", zkept),
                    ("  -> Zone D1/H4 Deep Stacking", z_deep_res),
                    ("  -> Zone H1 Continuation Stacking", z_h1_res)):
        st = stats(t)
        d2, s2 = dd_streak(t)
        crow.append([name, st["n"], fmt(st["net"]), fmt(st["exp"], 3), fmt(st["pf"]),
                     fmt(d2), s2])
    L += table(["Set", "Trades", "Net R", "Expectancy", "PF", "Max DD R", "Losing streak"], crow)
    L.append("")
    L += ["### Bias flip while open (MAIN card; trade ran, not managed)"]
    frow = []
    for name, t in (("flip_while_open", res[res["flip_while_open"]]),
                    ("no flip", res[~res["flip_while_open"]])):
        st = stats(t)
        frow.append([name, st["n"], fmt(st["net"]), fmt(st["exp"], 3)])
    L += table(["Group", "Trades", "Net R", "Expectancy"], frow)
    L.append("")
    L += ["### Duration (MAIN card; hours, fill to exit, resolved trades)"]
    d = res["dur_hours"].astype(float)
    L += table(["Median", "Mean", "Max"],
               [[fmt(d.median(), 1), fmt(d.mean(), 1), fmt(d.max(), 1)]])
    L.append("")
    if len(res):
        L += ["### Top 10 Longest Duration Trades (Phase 1B Outlier Audit)"]
        top_dur = res.sort_values("dur_hours", ascending=False).head(10)
        d_rows = []
        for _, r in top_dur.iterrows():
            d_rows.append([
                r["pair"], f"{r['leg']} {r['kind']} {r['side']}",
                ftime(r["fill_time"]), ftime(r["exit_time"]),
                fmt(r["dur_hours"], 1), fmt(r["fill_price"], 5),
                fmt(r["stop"], 5), fmt(r["target_price"], 5),
                r["outcome"], fmt(r["net_r"], 2)
            ])
        L += table(["Pair", "Model", "Fill Time", "Exit Time", "Duration (h)",
                    "Fill Price", "Stop", "Target", "Outcome", "Net R"], d_rows)
        L.append("")
    L += ["### Open at cutoff (counted separately)"]
    L.append(f"- Zone static: {int((zall['outcome'] == 'open_at_cutoff').sum())}; pullback: "
             f"{int((pall['outcome'] == 'open_at_cutoff').sum())} filled trade(s) were still "
             f"unresolved at the practice cutoff.")
    L.append("")
    L += ["### Orders that did not become trades"]
    s1 = zall["status"].value_counts()
    s3 = pall["status"].value_counts()
    keys = sorted(set(s1.index) | set(s3.index))
    L += table(["Status", "Zone static", "Pullback"],
               [[k, int(s1.get(k, 0)), int(s3.get(k, 0))] for k in keys])
    canc = zall[zall["status"] == "unfilled_cancelled"]["end_reason"].value_counts()
    if len(canc):
        L.append("")
        L.append("Zone orders cancelled by:")
        L += table(["Cancelled by", "Orders"], [[k, int(v)] for k, v in canc.items()])
    L.append("")
    L += ["### Funnel (all pairs summed; z_ = D1/H4 zone counters, h1_ = H1 continuation counters)"]
    tot = Counter()
    for fj in funnels.values():
        for k, v in fj.get("counts", {}).items():
            tot[k] += v
    L += table(["Counter", "Count"], [[k, tot[k]] for k in sorted(tot)])
    L.append("")
    L += ["### Zone trade sheet: first 10 resolved zone trades by fill time"]
    L.append("Times are UTC and are candle CLOSE times (the candle opened 15 minutes "
             "earlier). On the M15 chart check: the BOS against the trend, the leg touching "
             "the HTF zone, the CHoCH (level = high/low of that leg), the box and the entry.")
    L.append("")
    sheet = zres.sort_values("fill_time").head(10)
    if len(sheet):
        for i, (_, r) in enumerate(sheet.iterrows(), 1):
            L.append(sheet_line(i, r))
    else:
        L.append("No resolved zone trades.")
    L.append("")
    L += ["### Zone trade sheet: first 5 resolved zone SELLS by fill time"]
    L.append("")
    sells = zres[zres["side"] == "sell"].sort_values("fill_time").head(5)
    if len(sells):
        for i, (_, r) in enumerate(sells.iterrows(), 1):
            L.append(sheet_line(i, r))
    else:
        L.append("No resolved zone sells.")
    L.append("")
    md_main = "\n".join(L)
    anat_all_lines = render_all_months_deep_dive(m_records, label, year_filter=None)
    md_anatomy_all = "\n".join(anat_all_lines)
    out = ROOT / "reports" / "phase4"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"report_cycle_{label}.md").write_text(md_main)
    (out / f"report_cycle_{label}_monthly_anatomy.md").write_text(md_anatomy_all)
    if report_mode == "anatomy":
        md_out = md_anatomy_all
    elif report_mode == "anatomy_p1":
        md_out = "\n".join(render_all_months_deep_dive(m_records, label, year_filter={2016, 2017, 2018, 2019}))
    elif report_mode == "anatomy_p2":
        md_out = "\n".join(render_all_months_deep_dive(m_records, label, year_filter={2020, 2021, 2022}))
    else:
        md_out = md_main
    print(md_out)
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        encoded = md_out.encode("utf-8")
        if len(encoded) > 990_000:
            trunc_note = (
                "\n\n---\n**Note:** Step summary truncated at 990 KB due to GitHub Actions 1 MB UI limit. "
                f"Full 78-month report is saved in `reports/phase4/report_cycle_{label}_monthly_anatomy.md`.\n"
            )
            md_gh = encoded[:990_000].decode("utf-8", errors="ignore") + trunc_note
        else:
            md_gh = md_out + "\n"
        with open(gh, "a") as f:
            f.write(md_gh)
if __name__ == "__main__":
    main()
