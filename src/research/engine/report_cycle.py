"""Report for the cycle run (practice years only, exam years sealed).

Reads data/phase4_cycle/{pair}_{trades.csv,funnel.json,lookahead.json}.
Env: REPORT_LABEL (file name label), EXPECT_PAIRS (comma list).
Writes reports/phase4/report_cycle_<label>.md and the GitHub step summary.

Two static 1:3 scorecards plus their combined view:
  zone / static      = MAIN (the six sections), with-trend trades, 1:3 target
  pullback / static  = counter-trend trades, 1:3 target
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
    zall, zres = card(full, "zone", "static")
    pall, pres = card(full, "pullback", "static")
    allr, res = zall, zres          # the six sections show the MAIN card

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
          "- Variant: plain (no FVG).",
          "- MAIN scorecard (sections 1-6): ZONE trades = with the trend (buys in an uptrend, "
          "sells in a downtrend), static 1:3 target, breaker + OB together.",
          "- Pullback scorecard (counter-trend, static 1:3) and COMBINED (Zone + Pullback) "
          "are shown in Signal Frequency and Extras.",
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
    pb_per_month = len(pres) / win_months if win_months > 0 else np.nan
    comb_trades = len(res) + len(pres)
    comb_per_month = comb_trades / win_months if win_months > 0 else np.nan
    comb_net_static = float(res["net_r"].sum()) + float(pres["net_r"].sum())
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
        [f"ZONE trades per month, all pairs ({fmt(win_months, 0)} months)",
         fmt(per_month, 2)],
        [f"PULLBACK trades per month, all pairs ({fmt(win_months, 0)} months)",
         fmt(pb_per_month, 2)],
        [f"COMBINED trades per month (Zone + Pullback, {fmt(win_months, 0)} months)",
         fmt(comb_per_month, 2)],
        ["COMBINED total resolved trades (Zone + Pullback)", comb_trades],
        ["COMBINED Net R (Zone static 1:3 + Pullback static 1:3)", fmt(comb_net_static, 2)],
        [f"ZONE trades per month, since first Zone trade ({first_txt})",
         fmt(per_month_since, 2)],
        [f"ZONE trades per month per pair ({len(expect)} pair(s))", fmt(per_pair, 2)],
        ["% closed within 24h (Zone trades)", fmt(within, 1)]])
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

    # ------------------------------------------------------------ Extras
    L += ["## Extras", "", "### Scorecards side by side (Static 1:3)"]
    cards = (("ZONE static 1:3 (MAIN)", zall, zres),
             ("PULLBACK static 1:3", pall, pres))
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
    comb_st_df = pd.concat([zres, pres], ignore_index=True)
    cst = stats(comb_st_df)
    cd2, _ = dd_streak(comb_st_df)
    ctpm = cst["n"] / win_months if win_months > 0 else np.nan
    r1.append(["COMBINED (Zone + Pullback)", cst["n"], fmt(ctpm, 2), fmt(cst["net"]),
               fmt(cst["wr"], 1), fmt(cst["exp"], 3)])
    r2.append(["COMBINED (Zone + Pullback)", fmt(cst["pf"]), fmt(cd2), "3.00",
               int((zall["outcome"] == "open_at_cutoff").sum()) + int((pall["outcome"] == "open_at_cutoff").sum())])
    L += table(["Scorecard", "Trades", "Trades/mo", "Net R", "Win %", "Expectancy"], r1)
    L.append("")
    L += table(["Scorecard", "PF", "Max DD R", "Avg planned target (R)", "Open at cutoff"], r2)
    L.append("")
    L.append(f"- Pullback check against V1 (only meaningful in a zt or v1 run): V1 had "
             f"{V1_PULLBACK[0]} trades, {fmt(V1_PULLBACK[1])} R. This run: {len(pres)} trades, "
             f"{fmt(pres['net_r'].sum())} R. Equal: "
             f"{'YES' if (len(pres) == V1_PULLBACK[0] and abs(float(pres['net_r'].sum()) - V1_PULLBACK[1]) < 0.015) else 'NO'}.")
    L.append("")

    L += ["### Buy / sell split by entry model"]
    for name, a, r in cards:
        L.append(f"**{name}**")
        L += table(["Group", "Trades", "Win %", "Net R", "Expectancy"], split_rows(r))
        L.append("")

    L += ["### All pairs (MAIN card: zone, static)"]
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
            zrows.append([p, "n/a", "n/a", "n/a", "n/a"])
            continue
        c = fj.get("counts", {})
        zrows.append([p, c.get("z_scan", 0), c.get("z_setups", 0),
                      fj.get("zone_orders", 0),
                      int((zall[zall["pair"] == p]["status"] == "filled").sum())])
    L += table(["Pair", "Zone touches (scans)", "Zone setups", "Zone orders",
                "Filled (static)"], zrows)
    L.append("")

    L += ["### Stacking vs one-at-a-time (MAIN card, kept per pair)"]
    kept = res[res["kept_1at"]]
    crow = []
    for name, t in (("Stacking (all)", res), ("One-at-a-time", kept)):
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

    L += ["### Open at cutoff (counted separately)"]
    L.append(f"- Zone static: {n_open}; pullback: "
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

    L += ["### Funnel (all pairs summed; z_ = zone counters)"]
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
    sheet = res.sort_values("fill_time").head(10)
    if len(sheet):
        for i, (_, r) in enumerate(sheet.iterrows(), 1):
            L.append(sheet_line(i, r))
    else:
        L.append("No resolved zone trades.")
    L.append("")

    L += ["### Zone trade sheet: first 5 resolved zone SELLS by fill time"]
    L.append("")
    sells = res[res["side"] == "sell"].sort_values("fill_time").head(5)
    if len(sells):
        for i, (_, r) in enumerate(sells.iterrows(), 1):
            L.append(sheet_line(i, r))
    else:
        L.append("No resolved zone sells.")
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
