"""Phase 4 cycle engine, rebuild 2: pullbacks / reversals.
Sell side in a bull context; the buy side is the exact mirror. Bar by bar, no
lookahead. Sits on top of MapRecorder (structure, POI books, bias, ATR).
The trading timeframe is self.ltf (M15 by default, H1 when config.LTF_TF is
"H1"). Method names such as _on_m15 keep their old names; they run on bars of
the trading timeframe.
"""
from bisect import bisect_left
from collections import defaultdict
import math
import pandas as pd
from src import config
from src.research.engine import fvg as fvg_mod
from src.research.engine import poi as poi_mod
from src.research.engine.bias import htf_bias
from src.research.engine.mapper import MapRecorder
from src.research.lookahead_guard import DataFeed, DecisionLog

IDLE = "idle"
ARMED = "armed"
PULL = "pullback"
SCAN = "buy_scan"

_CTX = {
    "sell": {"side": "sell", "bias": "bull", "htf_dir": "up", "choch_dir": "down",
             "other_dir": "up", "zone_side": "buy", "up": True},
    "buy": {"side": "buy", "bias": "bear", "htf_dir": "down", "choch_dir": "up",
            "other_dir": "down", "zone_side": "sell", "up": False},
}


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _beyond(price, level, up):
    return price > level if up else price < level


def _ny_killzone(ts):
    """Convert UTC timestamp to America/New_York local hour and ICT Killzone."""
    try:
        ny = ts.tz_convert("America/New_York")
        h = int(ny.hour)
    except Exception:
        h = int((ts.hour - 5) % 24)
    if 2 <= h < 5:
        kz = "London_KZ"
    elif 7 <= h < 10:
        kz = "NY_AM_KZ"
    elif 10 <= h < 12:
        kz = "London_Close_KZ"
    elif h >= 20:
        kz = "Asian_KZ"
    else:
        kz = "Outside_KZ"
    return h, kz


class CycleRecorder(MapRecorder):
    def __init__(self, log, first_read=None):
        super().__init__(log)
        if first_read is not None:
            for tr in self.bias.values():
                tr.first_read = int(first_read)
        self.counts = defaultdict(int)
        self.orders = []
        self.pullbacks = []
        self.state = IDLE
        self.ctx = None
        self._pb = None
        self._scan = None
        self._rearm_after_scan = False
        self._after_far_break = False
        self._htf_q = []
        self._h4 = {}
        self._h4_times = []
        self._n_pb = 0
        self._n_setup = 0
        self._n_order = 0
        self._spread = 0.0

    def on_bar_close(self, bar, feed):
        n0 = len(self.events)
        super().on_bar_close(bar, feed)
        if bar.tf == "H4":
            self._h4[bar.open_time] = bar
            self._h4_times.append(bar.open_time)
        new = self.events[n0:]
        if bar.tf in ("H4", "D1"):
            self._htf_q.extend(new)
        elif bar.tf == self.ltf:
            self._on_m15(bar, new[0] if new else None)

    def _log(self, kind, now, **data):
        self.log.add(kind, now, now, **data)

    def _on_m15(self, bar, ev):
        now = bar.close_time
        queue, self._htf_q = self._htf_q, []
        for hev in queue:
            self._on_htf_event(hev, now)
        self._check_bias(now)
        if ev is not None and ev["label"] == "CHoCH" and self.state == IDLE:
            self.counts["choch_idle"] += 1
        if self.state == ARMED:
            self._armed_step(bar, ev, now)
        elif self.state == PULL:
            self._pull_step(bar, ev, now)
        elif self.state == SCAN:
            self._scan_step(bar, now)
            if self._rearm_after_scan:
                self._rearm_after_scan = False
                self.state = ARMED
                self.counts["rearm"] += 1
                self.counts["rearm_far_break"] += 1
                self._log("pb_rearm", now, reason="far_edge_break")

    def _on_htf_event(self, ev, now):
        if ev["label"] != "BOS":
            return
        hb = htf_bias(self.bias["D1"], self.bias["H4"])
        if (self.ctx is not None and hb == self.ctx["bias"]
                and ev["direction"] == self.ctx["htf_dir"]):
            self._after_far_break = False
        if self.state in (PULL, SCAN):
            self.counts["htf_bos_ignored_in_pullback"] += 1
            return
        if self.state == ARMED:
            return
        for c in _CTX.values():
            if hb == c["bias"] and ev["direction"] == c["htf_dir"]:
                self.ctx = c
                self.state = ARMED
                self._after_far_break = False
                self.counts["htf_arm"] += 1
                self._log("pb_armed", now, tf=ev["tf"], side=c["side"])
                return
        self.counts["htf_bos_no_arm"] += 1

    def _check_bias(self, now):
        if self.state == IDLE:
            return
        if htf_bias(self.bias["D1"], self.bias["H4"]) == self.ctx["bias"]:
            return
        if self.state == PULL:
            self._end_pullback(now, "bias_lost")
        self._scan = None
        self._rearm_after_scan = False
        self._after_far_break = False
        self.state = IDLE
        self.counts["disarmed_bias"] += 1
        self._log("pb_disarm", now, reason="bias_lost")

    def _armed_step(self, bar, ev, now):
        if ev is None or ev["label"] != "CHoCH" or ev["direction"] != self.ctx["choch_dir"]:
            return
        self.counts["choch_armed"] += 1
        self._start_pullback(bar, ev, now)

    def _start_pullback(self, bar, ev, now):
        self._n_pb += 1
        zones = self._freeze_zones()
        pb = {"id": f"PB{self._n_pb}", "side": self.ctx["side"], "start": now,
              "zones": zones, "ceiling": None, "locked": False, "attempt": None,
              "setups": [], "orders": [], "end_time": None, "end_reason": None}
        self._pb = pb
        self.pullbacks.append(pb)
        self.state = PULL
        self.counts["pullbacks"] += 1
        if not zones:
            self.counts["no_zone"] += 1
        self._log("pb_start", now, id=pb["id"], side=pb["side"], zones=len(zones))
        self._new_choch(bar, ev, now)

    def _freeze_zones(self):
        buy_zone = self.ctx["zone_side"] == "buy"
        inc = bool(config.TRADE_USED_POIS)
        out = []
        for tf in ("D1", "H4"):
            for p in self.books[tf].usable(self.ctx["zone_side"], include_used=inc):
                out.append(self._refine(p, buy_zone))
        return out

    def _refine(self, p, buy_zone):
        zone = {"id": p.id, "tf": p.tf, "poi": p, "low": p.low, "high": p.high,
                "refined": False}
        if p.tf != "D1":
            return zone
        t0 = p.candle_time
        t1 = t0 + pd.Timedelta(days=1)
        i = bisect_left(self._h4_times, t0)
        bars = []
        while i < len(self._h4_times) and self._h4_times[i] < t1:
            bars.append(self._h4[self._h4_times[i]])
            i += 1
        if not bars:
            self.counts["refine_none"] += 1
            return zone
        if buy_zone:
            k = min(range(len(bars)), key=lambda j: bars[j].low)
        else:
            k = max(range(len(bars)), key=lambda j: bars[j].high)

        def right(b):
            return b.close < b.open if buy_zone else b.close > b.open

        pick = k
        if poi_mod.REQUIRE_COLOUR and not right(bars[k]):
            step = -1 if config.WRONG_COLOUR_SEARCH_DIRECTION == "back" else 1
            pick = None
            for d in range(1, int(config.OB_SEARCH_BACK_MAX) + 1):
                j = k + step * d
                if j < 0 or j >= len(bars):
                    break
                if right(bars[j]):
                    pick = j
                    break
            if pick is None:
                pick = k
                self.counts["refine_cap"] += 1
        b = bars[pick]
        zone["low"] = b.low
        zone["high"] = b.high
        zone["refined"] = True
        return zone

    def _choch_poi(self, ev):
        pois = self.books[self.ltf].pois
        if pois and pois[-1].origin == "CHoCH" and pois[-1].born_time == ev["time"]:
            return pois[-1]
        return None

    def _compute_choch_disp(self, bar, ev, up):
        """Measure CHoCH displacement candle body / ATR and close location."""
        atr = self.atr.value_at(bar.open_time)
        body = abs(float(bar.close) - float(bar.open))
        rng = max(float(bar.high) - float(bar.low), 1e-12)
        disp_atr = (body / float(atr)) if (atr is not None and float(atr) > 0) else None
        # For down CHoCH (up=True, sell), close near low = 100%; for up CHoCH (buy), close near high = 100%
        if up:
            close_pct = (float(bar.high) - float(bar.close)) / rng * 100.0
        else:
            close_pct = (float(bar.close) - float(bar.low)) / rng * 100.0
        return disp_atr, close_pct

    def _new_choch(self, bar, ev, now):
        pb = self._pb
        if pb["ceiling"] is None:
            c = _num(ev["last_opposite_price"])
            if c is None:
                self.counts["no_ceiling"] += 1
                return
            pb["ceiling"] = c
            pb["locked"] = False
            pb["attempt"] = {"choch_time": ev["time"], "after": 0}
            self._log("pb_ceiling", now, id=pb["id"], ceiling=c, locked=False)
        else:
            self.counts["choch_in_pullback"] += 1
        self._n_setup += 1
        box = self._choch_poi(ev)
        breaker = self.books[self.ltf].choch_breaker.get(ev["time"])
        disp_atr, close_pct = self._compute_choch_disp(bar, ev, self.ctx["up"])
        setup = {"id": f"{pb['id']}-S{self._n_setup}", "choch_time": ev["time"],
                 "choch_level": _num(ev.get("broken_swing_price")),
                 "box": box, "breaker": breaker,
                 "attempt": None if pb["locked"] else pb["attempt"],
                 "br": "none", "ob": "none", "idm": None,
                 "idm_sweep_time": None, "bos_time": None,
                 "disp_body_atr": disp_atr, "disp_close_pct": close_pct}
        pb["setups"].append(setup)
        self.counts["setups"] += 1
        skip_br = self.ctx["up"]
        if breaker is None:
            self.counts["no_breaker"] += 1
        elif skip_br:
            self.counts["breaker_" + self.ctx["side"] + "_skipped"] += 1
        else:
            setup["br"] = "wait"
            self._try_breaker(setup, bar, now, first=True)
            if setup["br"] == "wait":
                self.counts["breaker_wait"] += 1
        if box is None:
            self.counts["no_choch_box"] += 1
        else:
            setup["ob"] = "wait_bos"

    def _unicorn_fvg(self, s, p, now):
        t_start = p.dead_time - pd.Timedelta(minutes=45)
        candles = self.books[self.ltf].window(t_start, now)
        fvgs = [f for f in fvg_mod.find_fvgs(candles, self.atr.value_at)
                if f.time >= p.dead_time]
        d = "down" if self.ctx["up"] else "up"
        return fvg_mod.pick_for_breaker(fvgs, d, p.low, p.high)

    def _try_breaker(self, s, bar, now, first):
        p = s["breaker"]
        if p.state != "dead":
            return
        if (p.dead_time - p.candle_time > pd.Timedelta(hours=2)
                or p.dead_time > s["choch_time"] + pd.Timedelta(hours=1)):
            s["br"] = "none"
            self.counts["breaker_slow_skipped"] += 1
            return
        if not (6 <= now.hour < 20):
            s["br"] = "none"
            self.counts["breaker_asian_skipped"] += 1
            return
        up = self.ctx["up"]
        near = p.low if up else p.high
        if now > p.dead_time:
            touched = bar.high >= near if up else bar.low <= near
            if touched:
                s["br"] = "none"
                self.counts["breaker_retrace_before_fvg"] += 1
                return
        fvg = self._unicorn_fvg(s, p, now)
        if fvg is None:
            if now >= p.dead_time + pd.Timedelta(minutes=15):
                s["br"] = "none"
                self.counts["breaker_no_unicorn_fvg"] += 1
            return
        s["br"] = "none"
        if self._place(s, "breaker", p, bar, now) is not None and not first:
            self.counts["breaker_late"] += 1

    def _try_ob(self, s, bar, now):
        up = self.ctx["up"]
        box = s["box"]
        if box.state == "dead":
            s["ob"] = "none"
            self.counts["ob_box_dead"] += 1
            return
        idm = s["idm"]
        swept = bar.high > idm if up else bar.low < idm
        if not swept:
            return
        s["ob"] = "none"
        s["idm_sweep_time"] = now
        allow_used = bool(config.TRADE_USED_POIS) or bool(getattr(config, "MAJOR_HTF", False))
        if box.state != "fresh" and not allow_used:
            self.counts["ob_box_used"] += 1
            return
        near = box.low if up else box.high
        touched = bar.high >= near if up else bar.low <= near
        if touched:
            self.counts["ob_same_bar"] += 1
            if up or bool(getattr(config, "SYM_SAME_BAR_SKIP_BOTH", False)):
                return
        self._place(s, "ob", box, bar, now)

    def _nearest_pb_zone(self, pb, up):
        best = None
        for z in pb.get("zones", []):
            near = float(z["high"]) if up else float(z["low"])
            if best is None or (near > best[0] if up else near < best[0]):
                best = (near, z)
        return best[1] if best is not None else None

    def _check_ob_fvg_overlap(self, p, now, up):
        """True if an M15 FVG in the CHoCH displacement leg overlaps or touches the OB box."""
        t_start = p.candle_time - pd.Timedelta(minutes=30)
        candles = self.books[self.ltf].window(t_start, now)
        fvgs = [f for f in fvg_mod.find_fvgs(candles, self.atr.value_at)
                if f.time >= p.candle_time]
        d = "down" if up else "up"
        return fvg_mod.pick_for_breaker(fvgs, d, p.low, p.high) is not None

    def _check_ceiling_sweep_reclaim(self, pb, setup, up):
        """True if the impulse ceiling swept a prior 24h M15 high/low and closed back inside."""
        c_val = pb.get("ceiling")
        ct = setup.get("choch_time")
        if c_val is None or ct is None:
            return False
        t_start = ct - pd.Timedelta(hours=30)
        candles = self.books[self.ltf].window(t_start, ct)
        if len(candles) < 12:
            return False
        # Split into prior session pool [:-8] and ceiling formation window [-8:]
        prior = candles[:-8]
        recent = candles[-8:]
        if not prior or not recent:
            return False
        if up:
            pool_lvl = max(float(x.high) for x in prior)
            swept = float(c_val) > pool_lvl
            reclaimed = any(float(x.high) >= pool_lvl and float(x.close) < pool_lvl for x in recent)
        else:
            pool_lvl = min(float(x.low) for x in prior)
            swept = float(c_val) < pool_lvl
            reclaimed = any(float(x.low) <= pool_lvl and float(x.close) > pool_lvl for x in recent)
        return bool(swept and reclaimed)

    def _check_opp_h1_in_path(self, entry, target, up):
        """True if a fresh opposing H1 POI sits between entry and the 3R target."""
        opp_side = "buy" if up else "sell"
        for p in self.books["H1"].usable(opp_side, include_used=False):
            if up:
                # Selling from entry down to target: check if bull H1 zone top is between target and entry
                if target <= float(p.high) < entry:
                    return True
            else:
                if entry < float(p.low) <= target:
                    return True
        return False

    def _place(self, setup, kind, p, bar, now):
        if self._after_far_break:
            self.counts["pb_deep_skipped"] += 1
            return None
        up = self.ctx["up"]
        atr = self.atr.value_at(p.candle_time)
        if atr is None:
            self.counts[kind + "_no_atr"] += 1
            return None
        entry = p.low if up else p.high
        edge = p.high if up else p.low
        ahead = bar.close < entry if up else bar.close > entry
        if not ahead:
            self.counts[kind + "_entry_not_ahead"] += 1
            return None
        if kind == "ob" and up and setup.get("idm") is not None:
            min_idm_atr = 0.75 if (6 <= now.hour < 12) else 0.5
            if float(entry) - float(setup["idm"]) < min_idm_atr * float(atr):
                self.counts["ob_idm_too_close"] += 1
                return None
            if float(p.high) - float(p.low) > 1.75 * float(atr):
                self.counts["ob_box_too_wide"] += 1
                return None
            if 12 <= now.hour < 16:
                self.counts["ob_sell_overlap_skipped"] += 1
                return None
        if kind == "ob" and not up:
            if float(p.high) - float(p.low) < 0.25 * float(atr):
                self.counts["ob_buy_box_too_narrow"] += 1
                return None
            if 16 <= now.hour < 20:
                self.counts["ob_buy_ny_afternoon_skipped"] += 1
                return None
        buf = float(config.STOP_BUFFER_ATR) * float(atr)
        raw_stop = edge + buf if up else edge - buf
        stop = raw_stop
        min_risk_padded = False
        # Stage 1A: min_risk stop padding / skip hygiene
        if self._spread > 0.0 and kind == "ob" and up:
            min_risk = (self._spread / float(config.MAX_SPREAD_RISK_RATIO)) * 1.0001
            if abs(entry - stop) < min_risk:
                if bool(getattr(config, "SKIP_MIN_RISK_PADDED", False)):
                    self.counts[kind + "_min_risk_skipped"] += 1
                    return None
                stop = entry + min_risk if up else entry - min_risk
                min_risk_padded = True
                self.counts[kind + "_min_risk_padded"] += 1

        pb = self._pb
        nz = self._nearest_pb_zone(pb, up)
        risk = abs(float(entry) - float(stop))
        target_3r = (float(entry) - float(config.RR_STATIC) * risk) if up else (float(entry) + float(config.RR_STATIC) * risk)

        # Confluence A: Destination Room to opposing D1/H4 zone (in R)
        dest_room_r = None
        if nz is not None and risk > 0:
            z_near = float(nz["high"]) if up else float(nz["low"])
            dest_room_r = ((float(entry) - z_near) / risk) if up else ((z_near - float(entry)) / risk)

        opp_h1_in_path = self._check_opp_h1_in_path(float(entry), target_3r, up) if risk > 0 else False

        # Confluence B: Macro Dealing-Range % and Local M15 OTE %
        deal_pct = None
        c_val = _num(pb.get("ceiling"))
        if c_val is not None and nz is not None:
            z_near = float(nz["high"]) if up else float(nz["low"])
            span = abs(c_val - z_near)
            if span > 0:
                # 100% = at Impulse Ceiling, 0% = at opposing HTF zone edge
                deal_pct = ((float(entry) - z_near) / span * 100.0) if up else ((z_near - float(entry)) / span * 100.0)

        local_ote_pct = None
        idm_val = _num(setup.get("idm")) or _num(setup.get("choch_level"))
        if c_val is not None and idm_val is not None:
            l_span = abs(c_val - idm_val)
            if l_span > 0:
                # Retracement % from IDM/CHoCH back toward Impulse Ceiling (OTE = 62% - 79%)
                local_ote_pct = ((float(entry) - idm_val) / l_span * 100.0) if up else ((idm_val - float(entry)) / l_span * 100.0)

        fvg_overlap = self._check_ob_fvg_overlap(p, now, up)
        sweep_reclaim = self._check_ceiling_sweep_reclaim(pb, setup, up)
        disp_body_atr = setup.get("disp_body_atr")
        disp_close_pct = setup.get("disp_close_pct")
        ny_hour, killzone = _ny_killzone(now)

        # Optional Phase 2 & 3 Gate Enforcement (all False by default)
        if bool(getattr(config, "PB_REQUIRE_DEST_ROOM", False)) and dest_room_r is not None:
            need_r = float(config.RR_STATIC) + float(getattr(config, "PB_DEST_ROOM_BUFFER_R", 0.0))
            if dest_room_r < need_r:
                self.counts["pb_dest_room_skipped"] += 1
                return None
        if bool(getattr(config, "PB_BLOCK_OPPOSING_H1_PATH", False)) and opp_h1_in_path:
            self.counts["pb_opp_h1_path_skipped"] += 1
            return None
        if bool(getattr(config, "PB_REQUIRE_DISCOUNT_PREMIUM", False)) and deal_pct is not None:
            if deal_pct < 50.0:
                self.counts["pb_deal_half_skipped"] += 1
                return None
        if bool(getattr(config, "PB_REQUIRE_OTE", False)) and local_ote_pct is not None:
            if local_ote_pct < 62.0:
                self.counts["pb_ote_skipped"] += 1
                return None
        if bool(getattr(config, "PB_REQUIRE_FVG_OVERLAP", False)) and not fvg_overlap:
            self.counts["pb_no_fvg_skipped"] += 1
            return None
        if bool(getattr(config, "PB_REQUIRE_SWEEP_RECLAIM", False)) and not sweep_reclaim:
            self.counts["pb_no_sweep_reclaim_skipped"] += 1
            return None
        min_disp = float(getattr(config, "PB_MIN_DISP_BODY_ATR", 0.0) or 0.0)
        if min_disp > 0.0 and disp_body_atr is not None and disp_body_atr < min_disp:
            self.counts["pb_weak_disp_skipped"] += 1
            return None
        if bool(getattr(config, "KILLZONE_ONLY", False)) and killzone == "Outside_KZ":
            self.counts["pb_outside_kz_skipped"] += 1
            return None

        self._n_order += 1
        breaker = setup["breaker"]
        order = {"id": f"O{self._n_order}", "pullback": pb["id"], "setup": setup["id"],
                 "variant": "plain", "kind": kind, "side": self.ctx["side"],
                 "htf_bias": self.ctx["bias"],
                 "placed_time": now, "entry": float(entry), "stop": float(stop),
                 "raw_stop": float(raw_stop), "min_risk_padded": bool(min_risk_padded),
                 "stop_edge": float(edge), "box_low": float(p.low),
                 "box_high": float(p.high), "box_time": p.candle_time,
                 "atr": float(atr),
                 "ceiling": pb["ceiling"], "ceiling_locked": pb["locked"],
                 "breaker_id": breaker.id if breaker is not None else None,
                 "anchor_id": None, "end_time": None, "end_reason": None,
                 "fill": "limit",
                 "choch_time": setup.get("choch_time"),
                 "choch_level": setup.get("choch_level"),
                 "bos_time": setup.get("bos_time"),
                 "idm_level": _num(setup.get("idm")),
                 "idm_sweep_time": setup.get("idm_sweep_time"),
                 "zone_tf": nz["tf"] if nz is not None else None,
                 "zone_low": float(nz["low"]) if nz is not None else None,
                 "zone_high": float(nz["high"]) if nz is not None else None,
                 "zone_touch_time": None,
                 "dest_room_r": dest_room_r,
                 "opp_h1_in_path": bool(opp_h1_in_path),
                 "deal_pct": deal_pct,
                 "local_ote_pct": local_ote_pct,
                 "fvg_overlap": bool(fvg_overlap),
                 "sweep_reclaim": bool(sweep_reclaim),
                 "disp_body_atr": disp_body_atr,
                 "disp_close_pct": disp_close_pct,
                 "ny_hour": ny_hour,
                 "killzone": killzone,
                 "h1_refined_ok": None}
        self.orders.append(order)
        pb["orders"].append(order)
        self.counts["orders_" + kind] += 1
        self._log("pb_order", now, id=order["id"], order_kind=kind,
                  side=order["side"], entry=order["entry"], stop=order["stop"],
                  setup=setup["id"])
        return order

    def _pull_step(self, bar, ev, now):
        pb = self._pb
        up = self.ctx["up"]
        if up or bool(getattr(config, "SYM_EXPIRY_48H_BOTH", False)):
            for o in pb["orders"]:
                if o["end_time"] is None and now - o["placed_time"] >= pd.Timedelta(hours=48):
                    o["end_time"] = now
                    o["end_reason"] = "expired_48h"
                    self.counts["orders_expired_48h"] += 1
        if pb["ceiling"] is not None and _beyond(bar.close, pb["ceiling"], up):
            if pb["locked"]:
                self._end_pullback(now, "ceiling_break")
                self.counts["end_ceiling_break"] += 1
                self.state = ARMED
                self.counts["rearm"] += 1
                self.log.add("pb_rearm", now, now, id=pb["id"])
                return
            self._fail_attempt(now, "ceiling_break")
            return
        z = self._zone_touched(bar)
        if z is not None:
            ceiling = pb["ceiling"]
            self._end_pullback(now, "zone")
            self.counts["end_zone"] += 1
            if ceiling is None:
                self.state = IDLE
                self.counts["zone_no_ceiling"] += 1
            else:
                self.state = SCAN
                self._scan = {"zone": z, "ceiling": ceiling}
                self._log("pb_zone", now, id=pb["id"], zone=z["id"], tf=z["tf"])
                self._scan_step(bar, now)
            return
        for s in pb["setups"]:
            if s["br"] == "wait":
                self._try_breaker(s, bar, now, first=False)
            if s["ob"] == "wait_sweep":
                self._try_ob(s, bar, now)
        if ev is None:
            return
        lab = ev["label"]
        d = ev["direction"]
        if lab == "CHoCH" and d == self.ctx["choch_dir"]:
            self._new_choch(bar, ev, now)
        elif lab == "BOS" and d == self.ctx["choch_dir"]:
            self._on_bos(ev, now)
        elif lab == "CHoCH" and d == self.ctx["other_dir"]:
            self._on_choch_other(now)

    def _on_bos(self, ev, now):
        pb = self._pb
        for s in pb["setups"]:
            if s["ob"] == "wait_bos" and s["choch_time"] < ev["time"]:
                p = _num(ev["last_opposite_price"])
                if p is None:
                    s["ob"] = "none"
                    self.counts["ob_no_idm"] += 1
                else:
                    s["idm"] = p
                    s["bos_time"] = ev["time"]
                    s["ob"] = "wait_sweep"
                    self.counts["idm_set"] += 1
        a = pb["attempt"]
        if not pb["locked"] and a is not None:
            a["after"] += 1
            if a["after"] >= 2:
                self._lock(now)

    def _on_choch_other(self, now):
        pb = self._pb
        for s in pb["setups"]:
            if s["ob"] == "wait_bos":
                s["ob"] = "none"
                self.counts["ob_no_bos"] += 1
        a = pb["attempt"]
        if not pb["locked"] and a is not None:
            if a["after"] == 0:
                self._fail_attempt(now, "choch_against")
            else:
                self._lock(now)

    def _lock(self, now):
        pb = self._pb
        pb["locked"] = True
        self.counts["ceiling_locked"] += 1
        self._log("pb_lock", now, id=pb["id"], ceiling=pb["ceiling"])

    def _fail_attempt(self, now, why):
        pb = self._pb
        a = pb["attempt"]
        ids = set()
        for s in pb["setups"]:
            if a is not None and s["attempt"] is a:
                s["br"] = "none"
                s["ob"] = "none"
                ids.add(s["id"])
        reason = "ceiling_break" if why == "ceiling_break" else "attempt_failed"
        for o in pb["orders"]:
            if o["setup"] in ids and o["end_time"] is None:
                o["end_time"] = now
                o["end_reason"] = reason
        pb["ceiling"] = None
        pb["attempt"] = None
        pb["locked"] = False
        self.counts["attempt_failed_" + why] += 1
        self._log("pb_fail", now, id=pb["id"], why=why)

    def _end_pullback(self, now, reason):
        pb = self._pb
        for o in pb["orders"]:
            if o["end_time"] is None:
                o["end_time"] = now
                o["end_reason"] = reason
        pb["end_time"] = now
        pb["end_reason"] = reason
        self._log("pb_end", now, id=pb["id"], reason=reason)
        self._pb = None

    def _zone_touched(self, bar):
        up = self.ctx["up"]
        ok = ("fresh", "used") if config.TRADE_USED_POIS else ("fresh",)
        best = None
        for z in self._pb["zones"]:
            if z["poi"].state not in ok:
                continue
            if up:
                hit = bar.low <= z["high"]
                near = z["high"]
            else:
                hit = bar.high >= z["low"]
                near = z["low"]
            if hit and (best is None or (near > best[0] if up else near < best[0])):
                best = (near, z)
        return best[1] if best is not None else None

    def _scan_step(self, bar, now):
        sc = self._scan
        up = self.ctx["up"]
        if _beyond(bar.close, sc["ceiling"], up):
            self.counts["scan_ceiling_break"] += 1
            self.counts["rearm"] += 1
            self.state = ARMED
            self._scan = None
            self._log("pb_scan_end", now, reason="ceiling_break")
            return
        far = sc["zone"]["low"] if up else sc["zone"]["high"]
        if _beyond(bar.close, far, not up):
            sc["zone"]["poi"].state = "dead"
            self.counts["scan_far_break"] += 1
            self.state = IDLE
            self._scan = None
            self._after_far_break = True
            self._rearm_after_scan = True
            self._log("pb_scan_end", now, reason="far_edge_break")

    def funnel(self):
        return dict(self.counts)

    def pullback_rows(self):
        return [{"id": pb["id"], "side": pb["side"], "start": pb["start"],
                 "end_time": pb["end_time"], "end_reason": pb["end_reason"],
                 "ceiling": pb["ceiling"], "locked": pb["locked"],
                 "zones": len(pb["zones"]), "setups": len(pb["setups"]),
                 "orders": len(pb["orders"])} for pb in self.pullbacks]


def run_cycle(m15, first_read=None):
    log = DecisionLog()
    rec = CycleRecorder(log, first_read)
    DataFeed(m15, htf=("H1", "H4", "D1")).run(rec)
    return rec, log


def run_cycle_pipeline(m15):
    return run_cycle(m15)[1].items
