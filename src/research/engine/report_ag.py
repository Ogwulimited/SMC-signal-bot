"""Report for the aggressive entry run, variant ag (practice years only).

Reads data/phase4_cycle/{pair}_{trades.csv,funnel.json,lookahead.json}.
Env: REPORT_LABEL (file name label), EXPECT_PAIRS (comma list).
Writes reports/phase4/report_ag_<label>.md and the GitHub step summary.

One scorecard only: aggressive / static 1:3, never mixed with zone or
pullback trades. Includes Monthly and Rolling 8-Month performance.
"""
import json
import math
import os
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from src import config
from src.research.engine import simulate_orders as so

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "phase4_cycle"
DATA_START = "2016-01-03"
ALL_PAIRS = ("eurusd,gbpusd,usdjpy,audusd,usdcad,usdchf,nzdusd,eurjpy,gbpjpy,eurgbp,"
             "audjpy,eurchf,eurcad,euraud,eurnzd,gbpchf,gbpcad,gbpaud,gbpnzd,audcad,"
             "audchf,audnzd,nzdjpy,nzdcad,nzdchf,cadjpy,cadchf,chfjpy").split(",")
NEW_PAIRS = set(ALL_PAIRS[11:])
TIME_COLS = ("placed_time", "end_time", "touch_time", "fill_time", "exit_time",
             "bos_time", "zone_touch_time", "choch_time")
NUM_COLS = ("net_r", "r_gross", "dur_hours", "spread_cost_r", "risk_r", "target_r",
            "entry", "stop", "target_price", "zone_low", "zone_high", "choch_level")
DONE = ["target", "stop", "stop_gap"]
LEG = "aggressive"
MODE = "static"


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


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return out


def month_list(t0, t1_excl):
    last = t1_excl - pd.Timedelta(seconds=1)
    y, m = t0.year, t0.month
    ey, em = last.year, last.month
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y += 1
            m = 1
    return out


def read_trades(pair):
    p = DATA / f"{pair}_trades.csv"
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame(columns=so.TRADE_COLS)
    for c in so.TRADE_COLS:
        if c not in df.columns:
            df[c] = np.nan
    df["leg"] = df["leg"].fillna("pullback")
    df["target_mode"] = df["target_mode"].fillna("static")
    for c in TIME_COLS:
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    for c in NUM_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("kept_1at", "flip_while_open"):
        df[c] = df[c].astype(str).eq("True")
    return df


def stats(t):
    n = len(t)
    if n == 0:
        return {"n": 0, "net": 0.0, "wr": np.nan, "pf": np.nan, "exp": np.nan, "rr": np.nan}
    r = t["net_r"].astype(float)
    pos = r[r > 0].sum()
    neg = -r[r < 0].sum()
    pf = pos / neg if neg > 0 else (np.inf if pos > 0 else np.nan)
    aw = r[r > 0].mean() if (r > 0).any() else np.nan
    al = -r[r < 0].mean() if (r < 0).any() else np.nan
    rr = aw / al if (al == al and al > 0 and aw == aw) else np.nan
    return {"n": n, "net": float(r.sum()),
            "wr": float((t["outcome"] == "target").mean() * 100),
            "pf": float(pf), "exp": float(r.mean()), "rr": float(rr)}


def dd_streak(t):
    if len(t) == 0:
        return 0.0, 0
    s = t.sort_values(["exit_time", "fill_time"])["net_r"].astype(float).to_numpy()
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


def ag_counts(fj):
    """All counters whose name starts with 'ag' from one pair's funnel json."""
    out = {}
    for src in (fj.get("counts"), fj.get("agg")):
        if not isinstance(src, dict):
            continue
        if isinstance(src.get("counts"), dict):
            src = src["counts"]
        for k, v in src.items():
            if str(k).startswith("ag") and isinstance(v, (int, float)) \
                    and not isinstance(v, bool):
                out[k] = v
    return out


def sheet_line(i, r):
    return (f"{i}. **{r['pair']}** aggressive {r['side']} - HTF zone {r.get('setup')}; "
            f"HTF break closed {ftime(r['bos_time'])}; H1 box {fmt(r['zone_low'], 5)} to "
            f"{fmt(r['zone_high'], 5)}; placed {ftime(r['placed_time'])}, "
            f"filled {ftime(r['fill_time'])}, entry {fmt(r['entry'], 5)}, "
            f"stop {fmt(r['stop'], 5)}, target {fmt(r['target_price'], 5)} -> "
            f"{r['outcome']} at {ftime(r['exit_time'])}, net R {fmt(r['net_r'], 2)}")


def main():
    label = os.environ.get("REPORT_LABEL", "run")
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
    allr, res = card(full, LEG, MODE)

    miss = [p for p in expect if p not in looks]
    failed = [p for p, v in looks.items() if not v.get("pass")]
    look_ok = (not miss) and (not failed) and bool(looks)
    L = [f"# Phase 4 aggressive entry report (ag): {label}", ""]
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
          "- Variant ag: aggressive entry (Option A: no 150-pip cap, clean/untapped H1, "
          "latest D1/H4 dealing range only, cancel on Major CHoCH warning).",
          "- Break-even win rate at 1:3 is 25% before spread cost.",
          "- Basis: stacking (every filled trade). Net R = gross R minus one spread cost.",
          ""]

    s = stats(res)
    L += ["## 1. Executive Summary"]
    L += table(["Metric", "Value"], [
        ["Total Net R", fmt(s["net"])], ["Win Rate %", fmt(s["wr"], 1)],
        ["Profit Factor", fmt(s["pf"])], ["Verdict", verdict(look_ok, s)]])
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
    if len(res):
        per_month = len(res) / win_months
        per_pair = per_month / max(len(expect), 1)
        first_fill = res["fill_time"].min()
        since_months = max((t_end - first_fill).days / 30.44, 1.0)
        per_month_since = len(res) / since_months
        first_txt = first_fill.strftime("%Y-%m-%d")
        within = float((res["dur_hours"] <= 24).mean() * 100)
    else:
        per_month = per_pair = per_month_since = within = np.nan
        first_txt = "n/a"
    L += table(["Metric", "Value"], [
        [f"Trades per month, all pairs, whole practice window ({fmt(win_months, 0)} months)",
         fmt(per_month, 2)],
        [f"Trades per month, all pairs, since the first trade ({first_txt})",
         fmt(per_month_since, 2)],
        [f"Trades per month per pair ({len(expect)} pair(s))", fmt(per_pair, 2)],
        ["% closed within 24h", fmt(within, 1)]])
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

    L += ["## 7. Monthly & 8-Month Consistency (active window, by entry month)"]
    months = month_list(res["fill_time"].min(), t_end) if len(res) else []
    m_n, m_net, m_win = {}, {}, {}
    if months:
        ym = res["fill_time"].dt.strftime("%Y-%m")
        for m in months:
            sub = res[ym == m]
            m_n[m] = len(sub)
            m_net[m] = float(sub["net_r"].sum()) if len(sub) else 0.0
            m_win[m] = int((sub["outcome"] == "target").sum()) if len(sub) else 0
        nets = [m_net[m] for m in months]
        n_m = len(months)
        n_green = sum(1 for x in nets if x > 0)
        n_red = sum(1 for x in nets if x < 0)
        n_flat = n_m - n_green - n_red
        best_m = max(months, key=lambda m: m_net[m])
        worst_m = min(months, key=lambda m: m_net[m])
        L += table(["Monthly Metric", "Value"], [
            ["Active months", f"{n_m} ({months[0]} to {months[-1]})"],
            ["Green months (Net R > 0)", f"{n_green}/{n_m} ({fmt(n_green * 100.0 / n_m, 1)}%)"],
            ["Red / Flat months", f"{n_red} red / {n_flat} flat (0 tr)"],
            ["Avg trades per active month", fmt(len(res) / n_m, 2)],
            ["Avg / Median monthly Net R", f"{fmt(np.mean(nets))} / {fmt(np.median(nets))}"],
            ["Best month", f"{best_m} ({fmt(m_net[best_m])} R, {m_n[best_m]} tr)"],
            ["Worst month", f"{worst_m} ({fmt(m_net[worst_m])} R, {m_n[worst_m]} tr)"],
        ])
        L.append("")
        if n_m >= 8:
            r8 = [(f"{months[i]}..{months[i + 7]}",
                   sum(m_n[x] for x in months[i:i + 8]),
                   sum(m_net[x] for x in months[i:i + 8]))
                  for i in range(n_m - 7)]
            r8_nets = [x[2] for x in r8]
            r8_tr = [x[1] for x in r8]
            g8 = sum(1 for x in r8_nets if x > 0)
            best8 = max(r8, key=lambda x: x[2])
            worst8 = min(r8, key=lambda x: x[2])
            L.append("**Rolling 8-month windows**")
            L += table(["8-Month Metric", "Value"], [
                ["Rolling 8-month windows", len(r8)],
                ["Green 8-month windows", f"{g8}/{len(r8)} ({fmt(g8 * 100.0 / len(r8), 1)}%)"],
                ["Avg 8-month trades", fmt(np.mean(r8_tr), 1)],
                ["Avg / Median 8-month Net R",
                 f"{fmt(np.mean(r8_nets))} / {fmt(np.median(r8_nets))}"],
                ["Best 8m stretch", f"{best8[0]} ({fmt(best8[2])} R, {best8[1]} tr)"],
                ["Worst 8m stretch", f"{worst8[0]} ({fmt(worst8[2])} R, {worst8[1]} tr)"],
            ])
            L.append("")
        L.append("**Chronological 8-month blocks**")
        brows = []
        for i in range(0, n_m, 8):
            w = months[i:i + 8]
            bn = sum(m_n[x] for x in w)
            bnet = sum(m_net[x] for x in w)
            bw = sum(m_win[x] for x in w)
            bwr = (bw * 100.0 / bn) if bn else np.nan
            bg = sum(1 for x in w if m_net[x] > 0)
            tag = f"{w[0]}..{w[-1]}" if len(w) == 8 else f"{w[0]}..{w[-1]} ({len(w)}m)"
            brows.append([tag, bn, fmt(bwr, 1), fmt(bnet), f"{bg}/{len(w)}"])
        L += table(["8m Block", "Tr", "Win %", "Net R", "Green m"], brows)
    else:
        L.append("No resolved trades for monthly or 8-month stats.")
    L.append("")

    # ------------------------------------------------------------ Extras
    L += ["## Extras", ""]

    L += ["### Buy / sell split"]
    srows = []
    for side in ("buy", "sell"):
        st = stats(res[res["side"] == side])
        srows.append([f"{side}s", st["n"], fmt(st["wr"], 1), fmt(st["net"]), fmt(st["exp"], 3)])
    st = stats(res)
    srows.append(["ALL", st["n"], fmt(st["wr"], 1), fmt(st["net"]), fmt(st["exp"], 3)])
    L += table(["Group", "Trades", "Win %", "Net R", "Expectancy"], srows)
    L.append("")

    L += ["### HTF zone origin split (D1 vs H4)"]
    setup_s = res["setup"].astype(str) if "setup" in res.columns else pd.Series(dtype=str)
    zrows = []
    for ztf in ("D1", "H4"):
        sub = res[setup_s.str.startswith(ztf)] if len(res) else res
        st = stats(sub)
        zrows.append([ztf, st["n"], fmt(st["wr"], 1), fmt(st["net"]), fmt(st["exp"], 3)])
    L += table(["Origin TF", "Trades", "Win %", "Net R", "Expectancy"], zrows)
    L.append("")

    L += ["### Market group split (measured majors vs assumed crosses)"]
    grows = []
    for gname, mask in (("Majors / liquid (11 measured)", ~res["pair"].isin(NEW_PAIRS)),
                        ("Minor crosses (17 assumed)", res["pair"].isin(NEW_PAIRS))):
        st = stats(res[mask] if len(res) else res)
        grows.append([gname, st["n"], fmt(st["wr"], 1), fmt(st["net"]), fmt(st["exp"], 3)])
    L += table(["Group", "Trades", "Win %", "Net R", "Expectancy"], grows)
    L.append("")

    L += ["### All pairs (aggressive, static 1:3)"]
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

    filled_all = allr[allr["status"] == "filled"]
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

    L += ["### Pair funnel: aggressive entry"]
    arows = []
    for p in expect:
        fj = funnels.get(p)
        if fj is None:
            arows.append(["n/a"] * 8)
            continue
        c = ag_counts(fj)
        mit = c.get("ag_h1_all_mitigated", 0) + c.get("ag_drop_h1_mitigated", 0)
        arows.append([p, c.get("ag_zones_D1", 0), c.get("ag_zones_H4", 0),
                      mit, c.get("ag_slots", 0), c.get("ag_orders", 0),
                      c.get("ag_zone_spent", 0),
                      int((allr[allr["pair"] == p]["status"] == "filled").sum())])
    L += table(["Pair", "D1 zones", "H4 zones", "H1 mitigated", "H1 slots", "Orders",
                "Zones spent", "Filled"], arows)
    L.append("")

    L += ["### Stacking vs one-at-a-time (kept per pair)"]
    kept = res[res["kept_1at"]]
    crow = []
    for name, t in (("Stacking (all)", res), ("One-at-a-time", kept)):
        st = stats(t)
        d2, s2 = dd_streak(t)
        crow.append([name, st["n"], fmt(st["net"]), fmt(st["exp"], 3), fmt(st["pf"]),
                     fmt(d2), s2])
    L += table(["Set", "Trades", "Net R", "Expectancy", "PF", "Max DD R", "Losing streak"], crow)
    L.append("")

    L += ["### Bias flip while open (trade ran, not managed)"]
    frow = []
    for name, t in (("flip_while_open", res[res["flip_while_open"]]),
                    ("no flip", res[~res["flip_while_open"]])):
        st = stats(t)
        frow.append([name, st["n"], fmt(st["net"]), fmt(st["exp"], 3)])
    L += table(["Group", "Trades", "Net R", "Expectancy"], frow)
    L.append("")

    L += ["### Duration (hours, fill to exit, resolved trades)"]
    d = res["dur_hours"].astype(float)
    L += table(["Median", "Mean", "Max"],
               [[fmt(d.median(), 1), fmt(d.mean(), 1), fmt(d.max(), 1)]])
    L.append("")

    L += ["### Outcomes of resolved trades"]
    oc = res["outcome"].value_counts()
    L += table(["Outcome", "Trades"], [[k, int(v)] for k, v in oc.items()])
    L.append("")

    L += ["### Open at cutoff (counted separately)"]
    L.append(f"- {n_open} filled trade(s) were still unresolved at the practice cutoff.")
    L.append("")

    L += ["### Orders that did not become trades"]
    s1 = allr["status"].value_counts()
    L += table(["Status", "Orders"], [[k, int(v)] for k, v in s1.items()])
    canc = allr[allr["status"] == "unfilled_cancelled"]["end_reason"].value_counts()
    if len(canc):
        L.append("")
        L.append("Orders cancelled by:")
        L += table(["Cancelled by", "Orders"], [[k, int(v)] for k, v in canc.items()])
    L.append("")

    L += ["### Funnel (all pairs summed; ag_ = aggressive counters)"]
    tot = Counter()
    for fj in funnels.values():
        for k, v in ag_counts(fj).items():
            tot[k] += v
    if tot:
        L += table(["Counter", "Count"], [[k, tot[k]] for k in sorted(tot)])
    else:
        L.append("No ag_ counters found in the funnel files.")
    L.append("")

    if months:
        L += ["### Month-by-month breakdown (active window)"]
        mrows = []
        for m in months:
            mn = m_n[m]
            mwr = (m_win[m] * 100.0 / mn) if mn else np.nan
            mrows.append([m, mn, fmt(mwr, 1), fmt(m_net[m])])
        L += table(["Month", "Tr", "Win %", "Net R"], mrows)
        L.append("")

    L += ["### Trade sheet: first 10 resolved aggressive trades by fill time"]
    L.append("Times are UTC and are candle CLOSE times. On the chart check: the D1/H4 "
             "zone, the refined H1 box, that the limit sat at the near edge, the stop "
             "behind the far edge, and what price did after the fill.")
    L.append("")
    sheet = res.sort_values("fill_time").head(10)
    if len(sheet):
        for i, (_, r) in enumerate(sheet.iterrows(), 1):
            L.append(sheet_line(i, r))
    else:
        L.append("No resolved aggressive trades.")
    L.append("")

    L += ["### Trade sheet: first 5 resolved aggressive SELLS by fill time"]
    L.append("")
    sells = res[res["side"] == "sell"].sort_values("fill_time").head(5)
    if len(sells):
        for i, (_, r) in enumerate(sells.iterrows(), 1):
            L.append(sheet_line(i, r))
    else:
        L.append("No resolved aggressive sells.")
    L.append("")

    md = "\n".join(L)
    out = ROOT / "reports" / "phase4"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"report_ag_{label}.md").write_text(md)
    print(md)
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a") as f:
            f.write(md + "\n")


if __name__ == "__main__":
    main()
