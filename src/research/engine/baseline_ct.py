"""Run the unchanged MZ engine on exactly the CT practice-only data.

Separate process and outputs; no changes to the existing engine or runner.
"""
import json
import os
from pathlib import Path

import pandas as pd

from src.research.engine import run_ct, run_cycle, simulate_orders as so

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / 'data' / 'phase4_ct_baseline'


def run_pair(pair):
    m15 = run_ct.load_m15(pair)
    if m15.empty:
        raise ValueError('No practice bars for ' + pair)
    run_cycle.set_variant('mz')
    run_cycle.set_pair_settings(pair)
    rec, log = run_cycle.run_engine(m15)
    orders = [o for o in rec.orders if o['kind'] in run_cycle.ACTIVE['kinds']]
    orders += list(rec.zorders)
    records = so.simulate_all(orders, m15, pair)
    groups = {}
    for r in records:
        groups.setdefault((r['leg'], r['target_mode']), []).append(r)
    for group in groups.values():
        so.tag_trades(group, rec.flips)
    look = run_cycle.lookahead_check(m15, log, int(os.environ.get('LOOKAHEAD_CUTS', '10')))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records, columns=so.TRADE_COLS).to_csv(OUT_DIR / f'{pair}_trades.csv', index=False)
    (OUT_DIR / f'{pair}_lookahead.json').write_text(json.dumps(look, indent=1, default=str))
    meta = {'pair': pair, 'variant': 'mz', 'bars': len(m15),
            'data_hash': run_ct.data_hash(m15), 'orders': len(orders),
            'first_bar': str(m15['timestamp'].iloc[0]),
            'last_close': str(m15['timestamp'].iloc[-1] + run_ct.TF_M15)}
    (OUT_DIR / f'{pair}_meta.json').write_text(json.dumps(meta, indent=1))
    print(f'[{pair}] matched MZ: {len(orders)} orders, lookahead {look["pass"]}', flush=True)


if __name__ == '__main__':
    run_pair(os.environ.get('PAIR', 'eurusd'))
