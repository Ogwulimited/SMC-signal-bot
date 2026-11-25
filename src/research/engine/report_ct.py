"""Report for the CT run (practice years only, exam sealed).

Reads data/phase4_ct/{pair}_{trades.csv,funnel.json,lookahead.json}.
Env: REPORT_LABEL, EXPECT_PAIRS.
Writes reports/phase4/report_ct_<label>.md and prints it.
Headline card: leg=zone, target_mode=static (1:3) — comparable to the
V1/ZT cards in versions.md. Liquidity card shown alongside.
"""
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.engine import simulate_orders as so

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "phase4_ct"
FIXED_MONTHS = (pd.Timestamp("2022-07-01", tz="UTC") - pd.Timestamp("2016-01-03", tz="UTC")).total_seconds() / (86400 * 365.2425 / 12)
ALL_PAIRS = ("eurusd,gbpusd,usdjpy,audusd,usdcad,usdchf,nzdusd,eurjpy,gbpjpy,eurgbp,"
             "audjpy,eurchf,eurcad,euraud,eurnzd,gbpchf,gbpcad,gbpaud,gbpnzd,audcad,"
             "audchf,audnzd,nzdjpy,nzdcad,nzdchf,cadjpy,cadchf,chfjpy").split(",")
DONE = ["target", "stop", "stop_gap"]
# Existing-system baselines from reports/phase4/versions.md (practice years)
BASELINES = {
    "V1 pullback": (1455, -21.13, 27.1, 0.98),
    "V4 OB only": (436, 8.22, 27.8, 1.02),
    "ZT zone MAIN": (284, 10.00, 28.2, 1.04),
}


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


def stats(t):
    n = len(t)
    if n == 0:
        return {"n": 0, "net": 0.0, "wr": np.nan, "pf": np.nan, "exp": np.nan}
    r = t["net_r"].astype(float)
    pos, neg = r[r > 0].sum(), -r[r < 0].sum()
    pf = pos / neg if neg > 0 else (np.inf if pos > 0 else np.nan)
    return {"n": n, "net": float(r.sum()),
            "wr": float((t["outcome"] == "target").mean() * 100),
            "pf": float(pf), "exp": float(r.mean())}


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
    df["leg"] = df["leg"].fillna("zone")
    df["target_mode"] = df["target_mode"].fillna("static")
    for c in ("placed_time", "fill_time", "exit_time"):
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    df["net_r"] = pd.to_numeric(df["net_r"], errors="coerce")
    return df


def main():
    label = os.environ.get("REPORT_LABEL", "full")
    expect = os.environ.get("EXPECT_PAIRS", ",".join(ALL_PAIRS)).split(",")
    frames, funnels, looks = [], {}, {}
    for pair in expect:
        df = read_trades(pair)
        if df is not None:
            frames.append(df)
        fj = DATA / f"{pair}_funnel.json"
        if fj.exists():
            funnels[pair] = json.loads(fj.read_text())
        lj = DATA / f"{pair}_lookahead.json"
        if lj.exists():
            looks[pair] = json.loads(lj.read_text())
    allr = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    missing = [p for p in expect if not (p in funnels and p in looks and (DATA / f"{p}_trades.csv").exists())]
    look_ok = not missing and all(looks[p].get("pass") and looks[p].get("cuts", 0) > 0 for p in expect)
    out = [f"# CT continuation report — {label} (practice years, exam sealed)",
           f"Pairs: {len(funnels)}/{len(expect)}  Lookahead: "
           f"{'PASS' if look_ok else 'FAIL'}",
           f"Window: 2016-01-03 to 2022-07-01 ({FIXED_MONTHS:.2f} elapsed months); partial coverage is not annualized.",
           f"Missing pair outputs: {missing or 'none'}\n"]
    for mode in ("static", "liquidity"):
        sub = allr[(allr["target_mode"] == mode)] if len(allr) else allr
        res = sub[sub["outcome"].isin(DONE)] if len(sub) else sub
        s = stats(res)
        dd, streak = dd_streak(res)
        fills = int((sub["status"] == "filled").sum()) if len(sub) else 0
        per_month = fills / FIXED_MONTHS
        out += [f"## Card: {mode}",
                f"- Filled: {fills}; resolved: {s['n']} ({per_month:.2f} fills/month portfolio-wide; "
                f"target >= 10/month: {'YES (observed)' if per_month >= 10 and look_ok and len(expect) == len(ALL_PAIRS) else 'NOT ESTABLISHED'})",
                f"- Net R: {fmt(s['net'])}  Win: {fmt(s['wr'], 1)}%  "
                f"PF: {fmt(s['pf'])}  Expectancy: {fmt(s['exp'], 3)}R",
                f"- Max drawdown: {fmt(dd)}R  Longest losing streak: {streak}",
                f"- Statuses: {sub['status'].value_counts().to_dict() if len(sub) else {}}",
                f"- open_at_cutoff: {int((sub['outcome'] == 'open_at_cutoff').sum()) if len(sub) else 0}\n"]
    out += ["## Historical references from versions.md (28 pairs; not a matched rerun)",
            "| System | Resolved | Net R | Win% | PF | Exp | resolved/month |",
            "|---|---|---|---|---|---|---|"]
    for name, (n, net, wr, pf) in BASELINES.items():
        out.append(f"| {name} | {n} | {net:.2f} | {wr:.1f} | {pf:.2f} | "
                   f"{net/n:.3f} | {n/FIXED_MONTHS:.2f} |")
    sub = allr[allr["target_mode"] == "static"] if len(allr) else allr
    res = sub[sub["outcome"].isin(DONE)] if len(sub) else sub
    s = stats(res)
    out.append(f"| **CT (this run)** | {s['n']} | {fmt(s['net'])} | "
               f"{fmt(s['wr'],1)} | {fmt(s['pf'])} | {fmt(s['exp'],3)} | "
               f"{s['n']/FIXED_MONTHS:.2f} |")
    out += ["",
            "**Verdict: inconclusive.** Ledger figures are historical references, "
            "not a verified matched rerun; compare the current baseline on the "
            "same pairs, data, dates, cost and execution assumptions before "
            "deciding. A positive practice result alone does not prove an edge.",
            f"Completeness and lookahead checks: {'PASS' if look_ok else 'FAIL'}. "
            "Static and liquidity are alternative simulations, not additive trades.\n"]
    if len(res):
        out += ["## By side / kind (static)",
                "| Split | n | Win% | Net R | Exp |",
                "|---|---|---|---|---|"]
        for (side, kind), g in res.groupby(["side", "kind"]):
            gs = stats(g)
            out.append(f"| {side} {kind} | {gs['n']} | {fmt(gs['wr'],1)} | "
                       f"{fmt(gs['net'])} | {fmt(gs['exp'],3)} |")
        out += ["", "## By exit year (static, resolved)",
                "| Year | n | Net R | Exp |",
                "|---|---|---|---|"]
        res2 = res.copy()
        res2["yr"] = res2["exit_time"].dt.year
        for yr, g in res2.groupby("yr"):
            gs = stats(g)
            out.append(f"| {yr} | {gs['n']} | {fmt(gs['net'])} | "
                       f"{fmt(gs['exp'],3)} |")
        out += ["", "## Filled trade frequency by calendar year (static)",
                "| Year | Filled | Months in practice window | Average fills/month |",
                "|---|---|---|---|"]
        filled = sub[sub["status"] == "filled"]
        for year in range(2016, 2023):
            year_rows = filled[filled["fill_time"].dt.year == year]
            start = max(pd.Timestamp(f"{year}-01-01", tz="UTC"), pd.Timestamp("2016-01-03", tz="UTC"))
            end = min(pd.Timestamp(f"{year+1}-01-01", tz="UTC"), pd.Timestamp("2022-07-01", tz="UTC"))
            months = (end - start).total_seconds() / (86400 * 365.2425 / 12)
            out.append(f"| {year} | {len(year_rows)} | {months:.2f} | {len(year_rows)/months:.2f} |")
        out += ["", "## Per pair (static)",
                "| Pair | n | Win% | Net R | Exp |",
                "|---|---|---|---|---|"]
        for pair, g in res.groupby("pair"):
            gs = stats(g)
            out.append(f"| {pair} | {gs['n']} | {fmt(gs['wr'],1)} | "
                       f"{fmt(gs['net'])} | {fmt(gs['exp'],3)} |")
    out += ["", "## Data coverage (first bar to last close)"]
    for pair, funnel in sorted(funnels.items()):
        out.append(f"- {pair}: {funnel.get('first_bar', 'unknown')} to {funnel.get('last_close', 'unknown')}")
    out += ["", "## Funnel (top counters, summed)",
            "| Counter | Total |",
            "|---|---|"]
    tot = {}
    for f in funnels.values():
        for k, v in f.get("counts", {}).items():
            tot[k] = tot.get(k, 0) + int(v)
    for k, v in sorted(tot.items(), key=lambda x: -x[1])[:25]:
        out.append(f"| {k} | {v} |")
    text = "\n".join(out) + "\n"
    print(text, flush=True)
    outdir = ROOT / "reports" / "phase4"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"report_ct_{label}.md").write_text(text)
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
