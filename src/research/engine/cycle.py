from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional

from ..data.oanda import to_utc
from ..structure.swings import SwingDetector
from ..zones.pois import POIDetector, _overlap
from ... import config


class CycleRecorder:
    def __init__(self, pair: str, ltf: str = "M15", htf1: str = "H4", htf2: str = "D1"):
        self.pair = pair
        self.ltf = str(ltf).upper()
        self.htf1 = str(htf1).upper()
        self.htf2 = str(htf2).upper()

        self.swing = {
            self.ltf: SwingDetector(n=int(getattr(config, "LTF_SWING_N", 2))),
            self.htf1: SwingDetector(n=int(getattr(config, "MAJOR_H4_SWING_N", 8))),
            self.htf2: SwingDetector(n=int(getattr(config, "MAJOR_D1_SWING_N", 8))),
        }
        self.pois = POIDetector()

        self.last_bar: Dict[str, Any] = {self.ltf: None, self.htf1: None, self.htf2: None}
        self.bias: Dict[str, Optional[str]] = {self.htf1: None, self.htf2: None}
        self.bias_flip_bar: Dict[str, int] = {self.htf1: -10**9, self.htf2: -10**9}
        self.bias_bars: Dict[str, int] = {self.htf1: 0, self.htf2: 0}

        self.state = "IDLE"  # IDLE -> ARMED -> SCAN -> WAIT_BOS -> DONE
        self.arm_bar = -10**9
        self.idm: Optional[Dict[str, Any]] = None
        self.bos: Optional[Dict[str, Any]] = None
        self.sweep: Optional[Dict[str, Any]] = None

        self.setups: List[Dict[str, Any]] = []
        self.trades: List[Dict[str, Any]] = []
        self.pending: List[Dict[str, Any]] = []
        self._zone_orders: List[Dict[str, Any]] = []

        self._bar_idx = -1
        self._equity = 0.0
        self.ctx: Dict[str, Any] = {}
        self._spread = 0.0

        self._ob_recent: Deque[Dict[str, Any]] = deque(maxlen=10)
        self._idm_recent: Deque[Dict[str, Any]] = deque(maxlen=10)

        self._stats: Dict[str, int] = {
            "bars_total": 0,
            "ltf_bars": 0,
            "htf_bars": 0,
            "attempted": 0,
            "placed": 0,
            "filled": 0,
            "win": 0,
            "loss": 0,
            "be": 0,
            "open": 0,
            "rearm": 0,
            "sweep_found": 0,
            "idm_found": 0,
            "bos_found": 0,
            "ob_found": 0,
            "breaker_found": 0,
            "scan_locked": 0,
            "scan_no_idm": 0,
            "scan_far_break": 0,
            "scan_ceiling": 0,
            "wait_locked": 0,
            "wait_no_bos": 0,
            "wait_no_ob": 0,
            "wait_same_bar": 0,
            "ob_same_bar": 0,
            "ob_used": 0,
            "ob_miti_past": 0,
            "orders_ob": 0,
            "orders_br": 0,
            "cancel_spread": 0,
            "cancel_expired": 0,
            "fill_limit": 0,
            "fill_next_open": 0,
            "orders_left_open": 0,
            "setups_closed": 0,
            "setups_open_left": 0,
        }

    # ---------------- public API ----------------
    def on_bar(self, tf: str, bar: Dict[str, Any], spread: float = 0.0):
        tf = str(tf).upper()
        self._spread = float(spread or 0.0)
        self._bar_idx += 1
        self.last_bar[tf] = bar
        self._stats["bars_total"] += 1

        if tf in (self.htf1, self.htf2):
            self._stats["htf_bars"] += 1
            self._on_htf(tf, bar)
            return

        if tf != self.ltf:
            return

        self._stats["ltf_bars"] += 1

        sc = self.swing[self.ltf].update(bar)
        self._expire_pending(bar)
        self._resolve_fills(bar)

        ev = sc.get("event")
        if ev:
            self._on_ltf_event(bar, ev)

        self._maybe_arm_from_sweep(bar)
        self._maybe_scan(bar)
        self._maybe_wait_bos(bar)

    def close_all_open(self, reason: str = "end"):
        last = self.last_bar.get(self.ltf) or {}
        t = last.get("time")
        o = _f(last.get("open"))
        h = _f(last.get("high"))
        l = _f(last.get("low"))
        c = _f(last.get("close"))
        if o is None or h is None or l is None or c is None:
            return

        still = []
        for tr in self.trades:
            if str(tr.get("status", "")).lower() != "open":
                continue
            px = c
            rr = self._rr(tr, px)
            tr["status"] = "be"
            tr["exit"] = float(px)
            tr["exit_time"] = t
            tr["pnl_r"] = float(rr)
            tr["exit_reason"] = str(reason)
            self._stats["be"] += 1
            self._stats["open"] = max(0, self._stats["open"] - 1)
            self._equity += float(rr)
            still.append(tr)

        self.trades.extend(still)
        self.pending.clear()
        self._zone_orders.clear()
        self.state = "DONE"
        self.ctx = {}
        self.idm = None
        self.bos = None
        self.sweep = None

    def snapshot(self) -> Dict[str, Any]:
        closed = [t for t in self.trades if str(t.get("status")) in ("win", "loss", "be")]
        wins = [t for t in closed if t["status"] == "win"]
        losses = [t for t in closed if t["status"] == "loss"]
        gross_win = sum(float(t["pnl_r"]) for t in wins)
        gross_loss = abs(sum(float(t["pnl_r"]) for t in losses))
        pf = (gross_win / gross_loss) if gross_loss > 1e-12 else (999.0 if gross_win > 0 else 0.0)

        eq = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in closed:
            eq += float(t.get("pnl_r", 0.0))
            peak = max(peak, eq)
            max_dd = max(max_dd, peak - eq)

        ob_buy = [t for t in closed if t.get("kind") == "ob" and t.get("side") == "buy"]
        ob_sell = [t for t in closed if t.get("kind") == "ob" and t.get("side") == "sell"]
        br_buy = [t for t in closed if t.get("kind") == "breaker" and t.get("side") == "buy"]
        br_sell = [t for t in closed if t.get("kind") == "breaker" and t.get("side") == "sell"]

        return {
            "pair": self.pair,
            "ltf": self.ltf,
            "htf1": self.htf1,
            "htf2": self.htf2,
            "bias": dict(self.bias),
            "state": self.state,
            "trades_total": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "be": len([t for t in closed if t["status"] == "be"]),
            "open_left": len([t for t in self.trades if t.get("status") == "open"]),
            "pending_left": len(self.pending),
            "winrate": (len(wins) / len(closed) * 100.0) if closed else 0.0,
            "net_r": round(sum(float(t.get("pnl_r", 0.0)) for t in closed), 4),
            "profit_factor": round(pf, 4),
            "max_drawdown_r": round(max_dd, 4),
            "ob_buy": {"n": len(ob_buy), "r": round(sum(float(t["pnl_r"]) for t in ob_buy), 4)},
            "ob_sell": {"n": len(ob_sell), "r": round(sum(float(t["pnl_r"]) for t in ob_sell), 4)},
            "breaker_buy": {"n": len(br_buy), "r": round(sum(float(t["pnl_r"]) for t in br_buy), 4)},
            "breaker_sell": {"n": len(br_sell), "r": round(sum(float(t["pnl_r"]) for t in br_sell), 4)},
            "stats": dict(self._stats),
        }

    # ---------------- HTF bias ----------------
    def _on_htf(self, tf: str, bar: Dict[str, Any]):
        sc = self.swing[tf].update(bar)
        ev = sc.get("event")
        if not ev:
            return
        self._check_bias(tf, ev)

    def _check_bias(self, tf: str, ev: Dict[str, Any]):
        if str(ev.get("type", "")).upper() != "BOS":
            return
        direction = str(ev.get("direction", "")).lower()
        if direction not in ("up", "down"):
            return
        nb = "buy" if direction == "up" else "sell"

        prev = self.bias.get(tf)
        if prev == nb:
            return

        self.bias[tf] = nb
        self.bias_flip_bar[tf] = self._bar_idx
        self.bias_bars[tf] = 0

        if self.state in ("ARMED", "SCAN", "WAIT_BOS"):
            self._reset_cycle("htf_bias_flip")

    # ---------------- LTF flow ----------------
    def _on_ltf_event(self, bar: Dict[str, Any], ev: Dict[str, Any]):
        et = str(ev.get("type", "")).upper()
        direction = str(ev.get("direction", "")).lower()
        side = self._htf_side()
        if side is None:
            return

        up = (side == "buy")

        if self.state == "IDLE":
            if up and et == "BOS" and direction == "down":
                self._arm_from_sweep_event(bar, ev, side)
            elif (not up) and et == "BOS" and direction == "up":
                self._arm_from_sweep_event(bar, ev, side)
            return

        if self.state == "ARMED":
            if up and et == "CHoCH" and direction == "down":
                self.sweep = _mk_level("sweep", ev, bar)
                self._stats["sweep_found"] += 1
            elif (not up) and et == "CHoCH" and direction == "up":
                self.sweep = _mk_level("sweep", ev, bar)
                self._stats["sweep_found"] += 1

            if self.sweep is not None:
                self.state = "SCAN"
                self.ctx = {"side": side, "up": up}
            return

        if self.state == "SCAN":
            if up and et == "CHoCH" and direction == "down":
                self.sweep = _mk_level("sweep", ev, bar)
                self._stats["sweep_found"] += 1
            elif (not up) and et == "CHoCH" and direction == "up":
                self.sweep = _mk_level("sweep", ev, bar)
                self._stats["sweep_found"] += 1
            return

        if self.state == "WAIT_BOS":
            if up and et == "BOS" and direction == "up":
                self.bos = _mk_level("bos", ev, bar)
                self._stats["bos_found"] += 1
            elif (not up) and et == "BOS" and direction == "down":
                self.bos = _mk_level("bos", ev, bar)
                self._stats["bos_found"] += 1

    def _arm_from_sweep_event(self, bar: Dict[str, Any], ev: Dict[str, Any], side: str):
        self._reset_cycle("arm")
        self.state = "ARMED"
        self.arm_bar = self._bar_idx
        self.sweep = _mk_level("sweep", ev, bar)
        self.ctx = {"side": side, "up": side == "buy"}
        self._stats["sweep_found"] += 1

    def _maybe_arm_from_sweep(self, bar: Dict[str, Any]):
        return

    def _maybe_scan(self, bar: Dict[str, Any]):
        if self.state != "SCAN":
            return
        if self.sweep is None:
            return

        side = self.ctx.get("side")
        up = bool(self.ctx.get("up"))
        if side is None:
            self._reset_cycle("scan_no_side")
            return

        high = _f(bar.get("high"))
        low = _f(bar.get("low"))
        if high is None or low is None:
            return

        sweep_px = _f(self.sweep.get("price"))
        if sweep_px is None:
            self._reset_cycle("scan_bad_sweep")
            return

        swept = (low <= sweep_px <= high) if up else (low <= sweep_px <= high)
        if not swept:
            age = self._bar_idx - int(self.sweep.get("bar_idx", self._bar_idx))
            if age > 24:
                self._stats["scan_ceiling"] += 1
                self._reset_cycle("scan_ceiling")
            return

        idm = self._find_idm_against(side)
        if idm is None:
            self._stats["scan_no_idm"] += 1
            age = self._bar_idx - int(self.sweep.get("bar_idx", self._bar_idx))
            if age > 30:
                self._reset_cycle("scan_no_idm_timeout")
            return

        self.idm = idm
        self._stats["idm_found"] += 1
        self.state = "WAIT_BOS"

    def _maybe_wait_bos(self, bar: Dict[str, Any]):
        if self.state != "WAIT_BOS":
            return
        if self.bos is None:
            age = self._bar_idx - int((self.idm or {}).get("bar_idx", self.arm_bar))
            if age > 40:
                self._stats["wait_no_bos"] += 1
                self._reset_cycle("wait_bos_timeout")
            return

        side = self.ctx.get("side")
        up = bool(self.ctx.get("up"))
        if side is None:
            self._reset_cycle("wait_no_side")
            return

        self._place_ob(bar, side, up)
        self._place_breaker(bar, side, up)

        if not self.pending and not self._zone_orders:
            self._stats["wait_no_ob"] += 1
            self._reset_cycle("wait_no_setup")
            return

        self.state = "DONE"
        self.ctx["done_bar"] = self._bar_idx

    # ---------------- setup builders ----------------
    def _place_ob(self, bar: Dict[str, Any], side: str, up: bool):
        allow_used = bool(config.TRADE_USED_POIS) or bool(getattr(config, "MAJOR_HTF", False))
        box = self.pois.last_ob(
            self.swing[self.ltf].swings,
            side=side,
            allow_used=allow_used,
            require_fresh=not allow_used,
        )
        if not box:
            return

        entry = _f(box.get("top")) if up else _f(box.get("bottom"))
        stop = _f(box.get("bottom")) if up else _f(box.get("top"))
        if entry is None or stop is None:
            return

        if (not up and entry <= stop) or (up and entry >= stop):
            return

        if self._overlap_idm(box):
            return

        if self._overlap_recent_ob(box):
            return

        if self._ob_touched_now(bar, box):
            self._stats["ob_same_bar"] += 1
            return

        # Stage 1A: min_risk stop padding only on Pullback OB SELL
        if self._spread > 0.0 and not up:
            min_risk = (self._spread / float(config.MAX_SPREAD_RISK_RATIO)) * 1.0001
            if abs(entry - stop) < min_risk:
                stop = entry - min_risk

        self._place(
            kind="ob",
            side=side,
            up=up,
            entry=float(entry),
            stop=float(stop),
            box=box,
            bar=bar,
            fill="limit",
        )
        self._stats["ob_found"] += 1
        self._ob_recent.append(
            {
                "top": _f(box.get("top")),
                "bottom": _f(box.get("bottom")),
                "bar_idx": int(box.get("bar_idx", self._bar_idx)),
            }
        )

    def _place_breaker(self, bar: Dict[str, Any], side: str, up: bool):
        skip_br_sell = bool(getattr(config, "MAJOR_HTF", False)) and side == "sell"
        if skip_br_sell:
            return

        box = self.pois.last_breaker(
            self.swing[self.ltf].swings,
            side=side,
            allow_used=False,
        )
        if not box:
            return

        entry = _f(box.get("top")) if up else _f(box.get("bottom"))
        stop = _f(box.get("bottom")) if up else _f(box.get("top"))
        if entry is None or stop is None:
            return

        if (not up and entry <= stop) or (up and entry >= stop):
            return

        if self._overlap_idm(box):
            return

        self._place(
            kind="breaker",
            side=side,
            up=up,
            entry=float(entry),
            stop=float(stop),
            box=box,
            bar=bar,
            fill="next_open",
        )
        self._stats["breaker_found"] += 1

    def _place(self, kind: str, side: str, up: bool, entry: float, stop: float, box: Dict[str, Any], bar: Dict[str, Any], fill: str):
        risk = abs(entry - stop)
        if risk <= 1e-12:
            return

        max_risk = risk
        spr = float(self._spread or 0.0)
        if spr > 0.0:
            max_risk = spr / max(1e-9, float(getattr(config, "MAX_SPREAD_RISK_RATIO", 0.15)))

        if risk > (max_risk + 1e-12):
            self._stats["cancel_spread"] += 1
            return

        rr = float(getattr(config, "RR_STATIC", 3.0))
        tp = entry + (risk * rr) if up else entry - (risk * rr)

        setup = {
            "id": len(self.setups) + 1,
            "pair": self.pair,
            "ltf": self.ltf,
            "htf1": self.htf1,
            "htf2": self.htf2,
            "kind": kind,
            "side": side,
            "up": bool(up),
            "entry": float(entry),
            "stop": float(stop),
            "tp": float(tp),
            "risk": float(risk),
            "rr": float(rr),
            "state": "pending",
            "created_time": bar.get("time"),
            "created_bar_idx": self._bar_idx,
            "expire_bar_idx": self._bar_idx + 24,
            "fill_mode": str(fill),
            "zone_id": None,
            "box": {
                "top": _f(box.get("top")),
                "bottom": _f(box.get("bottom")),
                "time": box.get("time"),
                "bar_idx": box.get("bar_idx"),
            },
            "idm_price": _f((self.idm or {}).get("price")),
            "bos_price": _f((self.bos or {}).get("price")),
            "sweep_price": _f((self.sweep or {}).get("price")),
        }
        self.setups.append(setup)

        order = {
            "setup_id": setup["id"],
            "kind": kind,
            "side": side,
            "up": bool(up),
            "entry": float(entry),
            "stop": float(stop),
            "tp": float(tp),
            "risk": float(risk),
            "rr": float(rr),
            "created_bar_idx": self._bar_idx,
            "expire_bar_idx": self._bar_idx + 24,
            "fill_mode": str(fill),
            "zone_id": None,
            "status": "pending",
        }
        self.pending.append(order)
        self._stats["attempted"] += 1
        self._stats["placed"] += 1
        if kind == "ob":
            self._stats["orders_ob"] += 1
        else:
            self._stats["orders_br"] += 1

    # ---------------- fills / exits ----------------
    def _expire_pending(self, bar: Dict[str, Any]):
        if not self.pending:
            return
        keep = []
        for od in self.pending:
            if self._bar_idx > int(od.get("expire_bar_idx", self._bar_idx)):
                self._cancel_setup(od.get("setup_id"), "expired")
                self._stats["cancel_expired"] += 1
                continue
            keep.append(od)
        self.pending = keep

    def _resolve_fills(self, bar: Dict[str, Any]):
        if not self.pending:
            return

        high = _f(bar.get("high"))
        low = _f(bar.get("low"))
        open_ = _f(bar.get("open"))
        close = _f(bar.get("close"))
        t = bar.get("time")
        if high is None or low is None or open_ is None or close is None:
            return

        still = []
        for od in self.pending:
            up = bool(od.get("up"))
            entry = _f(od.get("entry"))
            stop = _f(od.get("stop"))
            tp = _f(od.get("tp"))
            if entry is None or stop is None or tp is None:
                continue

            fill_mode = str(od.get("fill_mode", "limit"))

            if fill_mode == "limit":
                touched = (low <= entry <= high) if up else (low <= entry <= high)
                if not touched:
                    still.append(od)
                    continue

                bad = close <= stop if up else close >= stop
                if bad:
                    self._cancel_setup(od.get("setup_id"), "filled_through_stop")
                    continue

                self._open_trade(od, fill_price=float(entry), fill_time=t, fill_reason="limit_touch")
                self._stats["fill_limit"] += 1
                continue

            # next_open
            if int(od.get("created_bar_idx", self._bar_idx)) >= self._bar_idx:
                still.append(od)
                continue

            fill_px = float(open_)
            if up and fill_px <= stop:
                self._cancel_setup(od.get("setup_id"), "next_open_through_stop")
                continue
            if (not up) and fill_px >= stop:
                self._cancel_setup(od.get("setup_id"), "next_open_through_stop")
                continue

            self._open_trade(od, fill_price=float(fill_px), fill_time=t, fill_reason="next_open")
            self._stats["fill_next_open"] += 1

        self.pending = still

        for tr in self.trades:
            if str(tr.get("status", "")).lower() != "open":
                continue

            up = bool(tr.get("up"))
            stop = _f(tr.get("stop"))
            tp = _f(tr.get("tp"))
            if stop is None or tp is None:
                continue

            if up:
                if low <= stop:
                    tr["status"] = "loss"
                    tr["exit"] = float(stop)
                    tr["exit_time"] = t
                    tr["exit_reason"] = "sl"
                    tr["pnl_r"] = -1.0
                    self._stats["loss"] += 1
                    self._stats["open"] = max(0, self._stats["open"] - 1)
                    self._equity += -1.0
                    continue
                if high >= tp:
                    tr["status"] = "win"
                    tr["exit"] = float(tp)
                    tr["exit_time"] = t
                    tr["exit_reason"] = "tp"
                    tr["pnl_r"] = float(tr.get("rr", 3.0))
                    self._stats["win"] += 1
                    self._stats["open"] = max(0, self._stats["open"] - 1)
                    self._equity += float(tr.get("rr", 3.0))
                    continue
            else:
                if high >= stop:
                    tr["status"] = "loss"
                    tr["exit"] = float(stop)
                    tr["exit_time"] = t
                    tr["exit_reason"] = "sl"
                    tr["pnl_r"] = -1.0
                    self._stats["loss"] += 1
                    self._stats["open"] = max(0, self._stats["open"] - 1)
                    self._equity += -1.0
                    continue
                if low <= tp:
                    tr["status"] = "win"
                    tr["exit"] = float(tp)
                    tr["exit_time"] = t
                    tr["exit_reason"] = "tp"
                    tr["pnl_r"] = float(tr.get("rr", 3.0))
                    self._stats["win"] += 1
                    self._stats["open"] = max(0, self._stats["open"] - 1)
                    self._equity += float(tr.get("rr", 3.0))
                    continue

    def _open_trade(self, od: Dict[str, Any], fill_price: float, fill_time: Any, fill_reason: str):
        tr = {
            "id": len(self.trades) + 1,
            "setup_id": od.get("setup_id"),
            "pair": self.pair,
            "ltf": self.ltf,
            "htf1": self.htf1,
            "htf2": self.htf2,
            "kind": od.get("kind"),
            "side": od.get("side"),
            "up": bool(od.get("up")),
            "entry": float(fill_price),
            "stop": float(od.get("stop")),
            "tp": float(od.get("tp")),
            "risk": float(od.get("risk")),
            "rr": float(od.get("rr", 3.0)),
            "status": "open",
            "entry_time": fill_time,
            "created_time": od.get("created_time", fill_time),
            "fill_reason": fill_reason,
            "zone_id": od.get("zone_id"),
        }
        self.trades.append(tr)
        self._stats["filled"] += 1
        self._stats["open"] += 1
        self._mark_setup(od.get("setup_id"), "filled")

    def _cancel_setup(self, setup_id: Any, reason: str):
        for st in self.setups:
            if int(st.get("id", -1)) == int(setup_id or -1) and st.get("state") == "pending":
                st["state"] = "cancelled"
                st["cancel_reason"] = reason
                self._stats["setups_closed"] += 1
                break

    def _mark_setup(self, setup_id: Any, state: str):
        for st in self.setups:
            if int(st.get("id", -1)) == int(setup_id or -1):
                st["state"] = state
                break

    # ---------------- helpers ----------------
    def _htf_side(self) -> Optional[str]:
        b1 = self.bias.get(self.htf1)
        b2 = self.bias.get(self.htf2)
        if b1 in ("buy", "sell") and b1 == b2:
            return b1
        return None

    def _reset_cycle(self, reason: str = ""):
        self.state = "IDLE"
        self.arm_bar = -10**9
        self.idm = None
        self.bos = None
        self.sweep = None
        self.ctx = {}
        self.pending.clear()
        self._zone_orders.clear()
        if reason:
            self._stats["rearm"] += 1

    def _find_idm_against(self, side: str) -> Optional[Dict[str, Any]]:
        swings = list(self.swing[self.ltf].swings or [])
        if len(swings) < 2:
            return None

        if side == "buy":
            pivots = [s for s in swings if str(s.get("type")) == "low"]
            if not pivots:
                return None
            pivots = sorted(pivots, key=lambda x: int(x.get("bar_idx", -1)))
            return dict(pivots[-1])

        pivots = [s for s in swings if str(s.get("type")) == "high"]
        if not pivots:
            return None
        pivots = sorted(pivots, key=lambda x: int(x.get("bar_idx", -1)))
        return dict(pivots[-1])

    def _overlap_idm(self, box: Dict[str, Any]) -> bool:
        idm = self.idm or {}
        ip = _f(idm.get("price"))
        if ip is None:
            return False
        top = _f(box.get("top"))
        bot = _f(box.get("bottom"))
        if top is None or bot is None:
            return False
        return bot <= ip <= top

    def _overlap_recent_ob(self, box: Dict[str, Any]) -> bool:
        top = _f(box.get("top"))
        bot = _f(box.get("bottom"))
        if top is None or bot is None:
            return False
        for old in self._ob_recent:
            ot = _f(old.get("top"))
            ob = _f(old.get("bottom"))
            if ot is None or ob is None:
                continue
            if _overlap(top, bot, ot, ob):
                return True
        return False

    def _ob_touched_now(self, bar: Dict[str, Any], box: Dict[str, Any]) -> bool:
        high = _f(bar.get("high"))
        low = _f(bar.get("low"))
        top = _f(box.get("top"))
        bot = _f(box.get("bottom"))
        if None in (high, low, top, bot):
            return False
        return not (high < bot or low > top)

    def _rr(self, tr: Dict[str, Any], px: float) -> float:
        entry = _f(tr.get("entry"))
        stop = _f(tr.get("stop"))
        up = bool(tr.get("up"))
        if entry is None or stop is None:
            return 0.0
        risk = abs(entry - stop)
        if risk <= 1e-12:
            return 0.0
        if up:
            return (float(px) - float(entry)) / risk
        return (float(entry) - float(px)) / risk


def _f(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _mk_level(kind: str, ev: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    px = _f(ev.get("level"))
    if px is None:
        px = _f(ev.get("price"))
    if px is None:
        px = _f(bar.get("close"))
    return {
        "kind": kind,
        "price": float(px) if px is not None else None,
        "time": ev.get("time", bar.get("time")),
        "bar_idx": int(ev.get("bar_idx", -1)),
        "direction": str(ev.get("direction", "")).lower(),
        "source": str(ev.get("type", "")).upper(),
    }
