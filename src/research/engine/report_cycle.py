"""Report for the cycle run (practice years only, exam years sealed).

Reads data/phase4_cycle/{pair}_{trades.csv,funnel.json,lookahead.json}.
Env: REPORT_LABEL (file name label), EXPECT_PAIRS (comma list).
Writes reports/phase4/report_cycle_<label>.md and the GitHub step summary.
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
TIME_COLS = ("placed_time", "end_time", "touch_time", "fill_time", "exit_time")
DONE = ["target", "stop", "stop_gap"]


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


def read_trades(pair):
    p = DATA / f"{pair}_trades.csv"
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame(columns=so.TRADE_COLS)
    for c in TIME_COLS:
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    for c in ("net_r", "r_gross", "dur_hours", "spread_cost_r", "risk_r"):
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
    allr = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=so.TRADE_COLS)
    if frames:
        for c in TIME_COLS:
            allr[c] = pd.to_datetime(allr[c], utc=True, errors="coerce")
    res = allr[allr["outcome"].isin(DONE)]

    miss = [p for p in expect if p not in looks]
    failed = [p for p, v in looks.items() if not v.get("pass")]
    look_ok = (not miss) and (not failed) and bool(looks)
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
          "- Variant: plain (no FVG). Pullback sells only; zone buys are not built yet.",
          "- Basis: stacking (every filled trade). Net R = gross R minus one spread cost.",
          "- Rule assumptions A1-A8 in cycle.py and 'one box serves one CHoCH' are not confirmed by you yet.",
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

    rows, pair_net = [], {}
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

    L += ["## Extras", "", "### All pairs"]
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

    L += ["### Pair funnel (why some pairs have few or no orders)"]
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

    L += ["### Open at cutoff (counted separately)"]
    L.append(f"- {n_open} filled trade(s) were still unresolved at the practice cutoff.")
    L.append("")

    L += ["### Pullback sells by entry model (zone buys are not built yet)"]
    mrow = []
    for kind in ("breaker", "ob"):
        st = stats(res[res["kind"] == kind])
        mrow.append([kind, st["n"], fmt(st["wr"], 1), fmt(st["net"]), fmt(st["exp"], 3)])
    mrow.append(["zone buys", "not built", "-", "-", "-"])
    L += table(["Model", "Trades", "Win %", "Net R", "Expectancy"], mrow)
    L.append("")

    L += ["### Orders that did not become trades"]
    sc = allr["status"].value_counts()
    srow = [[k, int(v)] for k, v in sc.items()]
    L += table(["Status", "Orders"], srow)
    canc = allr[allr["status"] == "unfilled_cancelled"]["end_reason"].value_counts()
    if len(canc):
        L.append("")
        L += table(["Cancelled by", "Orders"], [[k, int(v)] for k, v in canc.items()])
    L.append("")

    L += ["### Funnel (all pairs summed)"]
    tot = Counter()
    for fj in funnels.values():
        for k, v in fj.get("counts", {}).items():
            tot[k] += v
    L += table(["Counter", "Count"], [[k, tot[k]] for k in sorted(tot)])
    L.append("")

    L += ["### Trade sheet (first 10 resolved trades by fill time, to check against your charts)"]
    L.append("Times are UTC. Open the M15 chart of the pair at the placed time and look for "
             "the CHoCH, the box and the entry.")
    L.append("")
    sheet = res.sort_values("fill_time").head(10)
    if len(sheet):
        for i, (_, r) in enumerate(sheet.iterrows(), 1):
            L.append(f"{i}. **{r['pair']}** {r['kind']} {r['side']} - placed "
                     f"{ftime(r['placed_time'])}, filled {ftime(r['fill_time'])}, "
                     f"entry {fmt(r['entry'], 5)}, stop {fmt(r['stop'], 5)}, "
                     f"target {fmt(r['target_price'], 5)} -> {r['outcome']} at "
                     f"{ftime(r['exit_time'])}, net R {fmt(r['net_r'], 2)}")
    else:
        L.append("No resolved trades.")
    L.append("")

    md = "\n".join(L)
    out = ROOT / "reports" / "phase4"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"report_cycle_{label}.md").write_text(md)
    print(md)
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a") as f:
            f.write(md + "\n")


if __name__ == "__main__":
    main()
