"""Variant E — CycleStrategy + with-trend entries at D1/H4 zones and H1 continuation zones."""
from collections import defaultdict
import pandas as pd

from src import config
from src.detectors import bos_choch, fvg, order_block
from src.research.engine import aggressive, cycle
from src.research.engine.cycle import (
    BAR_SEC, CycleStrategy, _as_ts, _body_atr, _extreme_idx,
    _lvl_broken, _merged_swings, _ny_killzone, _touch,
)

ZONE_OB_LOOKBACK_M15 = 80
H1_ZONE_MAX_AGE = pd.Timedelta(hours=96)
CANCEL_DIST_PIPS = 150.0


def _pip_size(pair):
    return 0.01 if "jpy" in pair.lower() else 0.0001


class ZoneCycleStrategy(CycleStrategy):
    def __init__(self, log, pip=0.0001, major_htf=False, rules=False, agg=False):
        super().__init__(log, pip=pip, major_htf=major_htf)
        self.rules = rules
        self.agg = agg
        self.z_state = "IDLE"
        self.z_ctx = None
        self.h1_state = "IDLE"
        self.h1_ctx = None
        self.used_zones = set()
        self.pending_orders = []
        for k in ("zones_built", "z_touches", "z_choch", "z_orders_placed",
                  "z_no_zone_d1", "z_no_zone_h4", "z_expired_touch", "z_expired_48h",
                  "z_ob_none", "z_ob_body", "z_ob_fvg", "z_ob_exhaust", "z_ob_rr",
                  "z_ob_same_bar", "z_ob_min_risk_padded", "z_ob_min_risk_skipped",
                  "z_ob_spread_skipped", "z_brk_orders", "z_liq_orders", "z_liq_skipped_r",
                  "z_deal_pct_skipped", "z_h1_ref_skipped",
                  "h1_zones_found", "h1_touches", "h1_choch", "h1_orders_placed",
                  "h1_expired_touch", "h1_expired_48h", "h1_ob_none", "h1_ob_body",
                  "h1_ob_fvg", "h1_ob_exhaust", "h1_ob_rr", "h1_ob_same_bar",
                  "h1_ob_min_risk_padded", "h1_ob_min_risk_skipped", "h1_ob_spread_skipped",
                  "h1_brk_orders", "h1_liq_orders", "h1_liq_skipped_r",
                  "zones_spent_skip", "orders_cancelled_150p", "zones_broken_past",
                  "ag_pb_orders", "ag_pb_no_fvg", "ag_pb_exhaust", "ag_pb_rr",
                  "ag_pb_min_risk_padded", "ag_pb_spread_skipped",
                  "ag_zone_orders", "ag_zone_no_h1", "ag_zone_h1_dirty", "ag_zone_no_ob",
                  "ag_zone_body", "ag_zone_fvg", "ag_zone_exhaust", "ag_zone_rr",
                  "ag_zone_same_bar", "ag_zone_min_risk_padded", "ag_zone_spread_skipped",
                  "ag_zone_liq_orders", "ag_zone_liq_skipped_r"):
            self.counts[k] = 0

    def _reset_z(self):
        self.z_state = "IDLE"
        self.z_ctx = None

    def _reset_h1(self):
        self.h1_state = "IDLE"
        self.h1_ctx = None

    def _reset(self):
        super()._reset()
        self._reset_z()
        self._reset_h1()

    def on_bar_close(self, bar, feed):
        if self.rules and self.m15:
            self._resolve_fills(bar)
        super().on_bar_close(bar, feed)

    def _resolve_fills(self, bar):
        hi, lo = float(bar.high), float(bar.low)
        close = float(bar.close)
        keep = []
        spent_now = set()
        for p in self.pending_orders:
            ep = p["entry"]
            if lo <= ep <= hi:
                if p.get("z_key") is not None:
                    self.used_zones.add(p["z_key"])
                    spent_now.add(p["z_key"])
                continue
            if p.get("leg") == "zone":
                dist = (close - ep) if not p["sell"] else (ep - close)
                if dist >= CANCEL_DIST_PIPS * self.pip:
                    self.counts["orders_cancelled_150p"] += 1
                    continue
            keep.append(p)
        self.pending_orders = keep
        sym_spent = getattr(config, "SYM_SPENT_ZONE_BOTH", False)
        if spent_now and self.ctx and (not self.ctx["up"] or sym_spent):
            if self.z_ctx and any(z["key"] in spent_now for z in self.z_ctx.get("zones", [])):
                self.z_ctx["zones"] = [z for z in self.z_ctx["zones"] if z["key"] not in spent_now]
            if self.h1_ctx and self.h1_ctx["zone"]["key"] in spent_now:
                self._reset_h1()

    def _find_zone(self, tf, up, counts, max_age=None, now=None, count=True):
        bars = self.htf[tf]
        if len(bars) < 5:
            return None
        sw = _merged_swings(bars, self.htf_sw_n[tf])
        kind = "high" if up else "low"
        cands = [s for s in sw if s["kind"] == kind]
        for s in reversed(cands):
            brk_idx = None
            for i in range(s["idx"] + 1, len(bars)):
                b = bars[i]
                if (up and b["close"] > s["price"]) or (not up and b["close"] < s["price"]):
                    brk_idx = i
                    break
            if brk_idx is None:
                continue
            anchor = self._anchor_before_break(bars, sw, s["idx"], brk_idx, up)
            if anchor is None:
                continue
            ext_idx = _extreme_idx(bars, anchor["idx"], brk_idx, up)
            ob = order_block.find_order_block(bars, ext_idx, brk_idx, "bullish" if up else "bearish")
            if ob is None:
                continue
            if _body_atr(bars, brk_idx) < config.MIN_BREAK_BODY_ATR:
                continue
            z_low, z_high = float(ob["low"]), float(ob["high"])
            broken = False
            for j in range(brk_idx + 1, len(bars)):
                if (up and bars[j]["close"] < z_low) or (not up and bars[j]["close"] > z_high):
                    broken = True
                    break
            if broken:
                continue
            if max_age is not None and now is not None and (now - _as_ts(ob["ts"])) > max_age:
                continue
            key = (tf, _as_ts(ob["ts"]), "bull" if up else "bear")
            if self.rules and key in self.used_zones:
                if count:
                    counts["zones_spent_skip"] += 1
                continue
            return {
                "tf": tf, "ts": _as_ts(ob["ts"]), "low": z_low, "high": z_high,
                "broken_level": float(s["price"]), "broken_ts": _as_ts(bars[brk_idx]["ts"]),
                "key": key, "up": up,
            }
        return None

    def _anchor_before_break(self, bars, sw, s_idx, brk_idx, up):
        opp = "low" if up else "high"
        cands = [x for x in sw if x["kind"] == opp and s_idx < x["idx"] < brk_idx]
        if cands:
            return min(cands, key=lambda x: x["price"]) if up else max(cands, key=lambda x: x["price"])
        cands = [x for x in sw if x["kind"] == opp and x["idx"] < s_idx]
        return cands[-1] if cands else None

    def _build_zones(self, up):
        zones = []
        for tf in ("D1", "H4"):
            z = self._find_zone(tf, up, self.counts)
            if z is None:
                self.counts[f"z_no_zone_{tf.lower()}"] += 1
            else:
                zones.append(z)
        return zones

    def _find_opposing_zones(self, up_trade):
        """Find fresh opposing D1/H4/H1 zones for Confluence A (destination room)."""
        opp_up = not up_trade
        dummy_c = defaultdict(int)
        zones = []
        for tf in ("D1", "H4", "H1"):
            z = self._find_zone(tf, opp_up, dummy_c, count=False)
            if z is not None:
                zones.append(z)
        return zones

    def _compute_dest_room(self, entry, risk, target, tsell):
        """Compute distance in R to nearest opposing D1/H4 zone and check opposing H1 in path."""
        up_trade = not tsell
        opp_zones = self._find_opposing_zones(up_trade)
        dest_room_r = None
        opp_h1_in_path = False
        if risk <= 0:
            return None, False
        for oz in opp_zones:
            if up_trade:
                edge = oz["low"]
                if edge > entry:
                    r_dist = (edge - entry) / risk
                    if oz["tf"] in ("D1", "H4"):
                        if dest_room_r is None or r_dist < dest_room_r:
                            dest_room_r = round(float(r_dist), 3)
                    elif oz["tf"] == "H1" and edge < target:
                        opp_h1_in_path = True
            else:
                edge = oz["high"]
                if edge < entry:
                    r_dist = (entry - edge) / risk
                    if oz["tf"] in ("D1", "H4"):
                        if dest_room_r is None or r_dist < dest_room_r:
                            dest_room_r = round(float(r_dist), 3)
                    elif oz["tf"] == "H1" and edge > target:
                        opp_h1_in_path = True
        return dest_room_r, opp_h1_in_path

    def _freeze_zones(self):
        """Include opposing zones so cycle.py pullback leg can compute Confluence A & B."""
        base_zones = list(self.z_ctx["zones"]) if self.z_ctx and self.z_ctx.get("zones") else []
        if self.ctx:
            up_opp = self.ctx["up"]
            dummy_c = defaultdict(int)
            for tf in ("D1", "H4", "H1"):
                oz = self._find_zone(tf, up_opp, dummy_c, count=False)
                if oz is not None and not any(x.get("key") == oz["key"] for x in base_zones):
                    base_zones.append(oz)
        return base_zones

    def _liq_target(self, up, entry, risk):
        pool = []
        for tf in ("D1", "H4"):
            sw = _merged_swings(self.htf[tf], self.htf_sw_n[tf])
            if up:
                pool += [s["price"] for s in sw if s["kind"] == "high" and s["price"] > entry]
            else:
                pool += [s["price"] for s in sw if s["kind"] == "low" and s["price"] < entry]
        if self.ctx and "ceiling" in self.ctx:
            c = self.ctx["ceiling"]
            if (up and c > entry) or (not up and c < entry):
                pool.append(c)
        if not pool:
            return None
        t = min(pool) if up else max(pool)
        if abs(t - entry) / risk < config.LIQ_MIN_R:
            return None
        return float(t)

    def _on_m15(self, bar, ev):
        now = _as_ts(bar.timestamp)
        super()._on_m15(bar, ev)
        if self.z_state in ("Z_WAIT", "Z_TOUCHED"):
            self._z_step(bar, now)
        if getattr(config, "H1_STREAM_ENABLED", True):
            self._h1_step(bar, now)

    def _start_pullback(self, bar, ev, now):
        up = self.ctx["up"]
        zones = self._build_zones(up)
        if zones:
            self.counts["zones_built"] += len(zones)
            self.z_ctx = {"up": up, "zones": zones, "arm_ts": now}
            self.z_state = "Z_WAIT"
        super()._start_pullback(bar, ev, now)

    def _z_step(self, bar, now):
        zc = self.z_ctx
        up = zc["up"]
        if self.rules:
            kept = []
            for z in zc["zones"]:
                if (up and float(bar.close) < z["low"]) or (not up and float(bar.close) > z["high"]):
                    self.counts["zones_broken_past"] += 1
                    continue
                if z["key"] in self.used_zones and (not up or getattr(config, "SYM_SPENT_ZONE_BOTH", False)):
                    self.counts["zones_spent_skip"] += 1
                    continue
                kept.append(z)
            zc["zones"] = kept
            if not zc["zones"]:
                return self._reset_z()
        if self.z_state == "Z_WAIT":
            for z in zc["zones"]:
                if float(bar.low) <= z["high"] and float(bar.high) >= z["low"]:
                    zc["active"] = z
                    zc["touch_ts"] = now
                    zc["touch_idx"] = len(self.m15) - 1
                    zc["touch_ext"] = float(bar.low) if up else float(bar.high)
                    self.counts["z_touches"] += 1
                    if self.agg and z["tf"] in ("D1", "H4"):
                        self._ag_zone_enter(bar, now, z, up)
                        return self._reset_z()
                    self.z_state = "Z_TOUCHED"
                    break
            else:
                if (now - zc["arm_ts"]) > config.TOUCH_TIMEOUT:
                    self.counts["z_expired_touch"] += 1
                    return self._reset_z()
                return
        z = zc["active"]
        if up and float(bar.low) < zc["touch_ext"]:
            zc["touch_ext"] = float(bar.low)
        elif not up and float(bar.high) > zc["touch_ext"]:
            zc["touch_ext"] = float(bar.high)
        if (now - zc["touch_ts"]) > config.ORDER_EXPIRY:
            self.counts["z_expired_48h"] += 1
            return self._reset_z()
        b = self._z_new_choch("M15", zc["touch_ts"], up)
        if b is None:
            return
        self.counts["z_choch"] += 1
        self._z_place(bar, now, b, z, up, prefix="z", zone_tf=z["tf"])
        self._reset_z()

    def _h1_step(self, bar, now):
        if self.state not in ("ARMED", "PULLBACK", "ASSAULT") or not self.ctx:
            return self._reset_h1()
        up = self.ctx["up"]
        if self.h1_state == "IDLE":
            z = self._find_zone("H1", up, self.counts, max_age=H1_ZONE_MAX_AGE, now=now)
            if z is None:
                return
            self.counts["h1_zones_found"] += 1
            self.h1_ctx = {"up": up, "zone": z, "arm_ts": now}
            self.h1_state = "H1_WAIT"
        hc = self.h1_ctx
        if hc["up"] != up:
            return self._reset_h1()
        z = hc["zone"]
        if self.rules:
            if (up and float(bar.close) < z["low"]) or (not up and float(bar.close) > z["high"]):
                self.counts["zones_broken_past"] += 1
                return self._reset_h1()
            if z["key"] in self.used_zones and (not up or getattr(config, "SYM_SPENT_ZONE_BOTH", False)):
                self.counts["zones_spent_skip"] += 1
                return self._reset_h1()
        if self.h1_state == "H1_WAIT":
            if float(bar.low) <= z["high"] and float(bar.high) >= z["low"]:
                hc["touch_ts"] = now
                hc["touch_idx"] = len(self.m15) - 1
                hc["touch_ext"] = float(bar.low) if up else float(bar.high)
                self.counts["h1_touches"] += 1
                self.h1_state = "H1_TOUCHED"
            elif (now - hc["arm_ts"]) > config.TOUCH_TIMEOUT:
                self.counts["h1_expired_touch"] += 1
                return self._reset_h1()
            else:
                return
        if up and float(bar.low) < hc["touch_ext"]:
            hc["touch_ext"] = float(bar.low)
        elif not up and float(bar.high) > hc["touch_ext"]:
            hc["touch_ext"] = float(bar.high)
        if (now - hc["touch_ts"]) > config.ORDER_EXPIRY:
            self.counts["h1_expired_48h"] += 1
            return self._reset_h1()
        b = self._z_new_choch("M15", hc["touch_ts"], up)
        if b is None:
            return
        self.counts["h1_choch"] += 1
        self._z_place(bar, now, b, z, up, prefix="h1", zone_tf="H1")
        self._reset_h1()

    def _z_new_choch(self, tf, since_ts, up):
        bars = self.m15 if tf == "M15" else self.htf[tf]
        sw = _merged_swings(bars, config.SWING_LOOKBACK_LTF)
        ev = bos_choch.detect_bos_choch(bars, sw)
        if not ev:
            return None
        b = ev[-1]
        if _as_ts(b["ts"]) < since_ts or _as_ts(b["ts"]) != _as_ts(bars[-1]["ts"]):
            return None
        want = "bullish" if up else "bearish"
        if b["direction"] != want:
            return None
        if self.rules and b["kind"] != "CHOCH":
            return None
        return b

    def _z_place(self, bar, now, b, z, up, prefix="z", zone_tf="H4"):
        ltf_bars = self.m15
        n = len(ltf_bars)
        start = max(0, n - ZONE_OB_LOOKBACK_M15)
        ext_idx = _extreme_idx(ltf_bars, start, b["break_idx"], up)
        tsell = not up
        direction = "bearish" if tsell else "bullish"
        ob = order_block.find_order_block(ltf_bars, ext_idx, b["break_idx"], direction)
        if ob is None:
            self.counts[f"{prefix}_ob_none"] += 1
            return
        sym_same = getattr(config, "SYM_SAME_BAR_SKIP_BOTH", False)
        if self.rules and (not tsell or sym_same) and _as_ts(ob["ts"]) == now:
            self.counts[f"{prefix}_ob_same_bar"] += 1
            return
        if _body_atr(ltf_bars, b["break_idx"]) < config.MIN_BREAK_BODY_ATR:
            self.counts[f"{prefix}_ob_body"] += 1
            return
        fvgs = fvg.find_fvgs(ltf_bars, self.pip)
        if not fvg.has_overlapping_fvg(fvgs, ob["low"], ob["high"], direction, after_ts=ob["ts"]):
            self.counts[f"{prefix}_ob_fvg"] += 1
            return
        if _body_atr(ltf_bars, b["break_idx"]) > config.EXHAUSTION_MULT:
            self.counts[f"{prefix}_ob_exhaust"] += 1
            return

        # Optional H1 Refinement of D1/H4 zone entries (Change 2B)
        h1_refined_ok = False
        if zone_tf in ("D1", "H4"):
            dummy_ag = defaultdict(int)
            h1_base = aggressive.pick_h1_base(
                self.htf["H1"], z["broken_ts"], tsell, z["low"], z["high"],
                float(bar.close), dummy_ag
            )
            h1_refined_ok = h1_base is not None
            if getattr(config, "ZONE_H1_REFINEMENT", False):
                if not h1_refined_ok:
                    self.counts["z_h1_ref_skipped"] += 1
                    return

        entry = float(ob["low"]) if tsell else float(ob["high"])
        raw_stop = (float(ob["high"]) + config.SL_BUFFER_PIPS * self.pip) if tsell else (
                    float(ob["low"]) - config.SL_BUFFER_PIPS * self.pip)
        stop = raw_stop
        min_risk_padded = False
        if self.rules:
            min_risk = (self.spread / config.MAX_SPREAD_RISK_RATIO) * 1.0001
            if abs(entry - stop) < min_risk:
                if getattr(config, "SKIP_MIN_RISK_PADDED", False):
                    self.counts[f"{prefix}_ob_min_risk_skipped"] += 1
                    return
                stop = (entry + min_risk) if tsell else (entry - min_risk)
                self.counts[f"{prefix}_ob_min_risk_padded"] += 1
                min_risk_padded = True
        risk = abs(entry - stop)
        if risk <= 0:
            return
        if self.spread / risk > config.MAX_SPREAD_RISK_RATIO:
            self.counts[f"{prefix}_ob_spread_skipped"] += 1
            return
        target = (entry - config.RR_TARGET * risk) if tsell else (entry + config.RR_TARGET * risk)
        if abs(target - entry) / risk < config.MIN_RR_AFTER_COSTS:
            self.counts[f"{prefix}_ob_rr"] += 1
            return

        # Compute Zone Dealing Range % (Ceiling -> Zone extreme) for Change 3B
        deal_pct = None
        if self.ctx and "ceiling" in self.ctx:
            ceil_p = float(self.ctx["ceiling"])
            if not tsell:  # Buy zone trade: ceiling is high, zone low is range low
                rng = ceil_p - float(z["low"])
                if rng > 0:
                    deal_pct = round((ceil_p - entry) / rng * 100.0, 2)
            else:  # Sell zone trade: ceiling is low, zone high is range high
                rng = float(z["high"]) - ceil_p
                if rng > 0:
                    deal_pct = round((entry - ceil_p) / rng * 100.0, 2)

        if getattr(config, "ZONE_REQUIRE_DISCOUNT_PREMIUM", False) and prefix == "z":
            if deal_pct is not None and deal_pct < 50.0:
                self.counts["z_deal_pct_skipped"] += 1
                return

        dest_room_r, opp_h1_in_path = self._compute_dest_room(entry, risk, target, tsell)
        disp_body, disp_close = self._disp_metrics(b, ltf_bars)
        ny_hr, kz = _ny_killzone(now)
        if getattr(config, "KILLZONE_ONLY", False) and kz == "Outside_KZ":
            return

        extra = {
            "raw_stop": raw_stop,
            "min_risk_padded": min_risk_padded,
            "dest_room_r": dest_room_r,
            "opp_h1_in_path": opp_h1_in_path,
            "deal_pct": deal_pct,
            "local_ote_pct": None,
            "fvg_overlap": True,
            "sweep_reclaim": True,
            "disp_body_atr": disp_body,
            "disp_close_pct": disp_close,
            "ny_hour": ny_hr,
            "killzone": kz,
            "h1_refined_ok": h1_refined_ok,
        }

        self._emit_order(now, tsell, entry, stop, target, "ob", z, zone_tf, "static", prefix, extra=extra)
        if not self.rules and b["kind"] == "BOS":
            brk = order_block.find_breaker_block(ltf_bars, ext_idx, b["break_idx"], direction)
            if brk is not None and fvg.pick_for_breaker(fvgs, brk["low"], brk["high"], after_ts=brk["ts"]) is not None:
                be = float(brk["low"]) if tsell else float(brk["high"])
                bs = (float(brk["high"]) + config.SL_BUFFER_PIPS * self.pip) if tsell else (
                      float(brk["low"]) - config.SL_BUFFER_PIPS * self.pip)
                br = abs(be - bs)
                if br > 0 and self.spread / br <= config.MAX_SPREAD_RISK_RATIO:
                    bt = (be - config.RR_TARGET * br) if tsell else (be + config.RR_TARGET * br)
                    self._emit_order(now, tsell, be, bs, bt, "breaker", z, zone_tf, "static", prefix,
                                     count_key=f"{prefix}_brk_orders", extra=extra)
        if self.rules:
            self.pending_orders.append({"entry": entry, "sell": tsell, "z_key": z["key"], "leg": "zone"})
        liq_t = self._liq_target(up, entry, risk)
        if liq_t is not None:
            self._emit_order(now, tsell, entry, stop, liq_t, "ob", z, zone_tf, "liq", prefix,
                             count_key=f"{prefix}_liq_orders", extra=extra)
        else:
            self.counts[f"{prefix}_liq_skipped_r"] += 1

    def _ag_zone_enter(self, bar, now, z, up):
        tsell = not up
        base = aggressive.pick_h1_base(
            self.htf["H1"], z["broken_ts"], tsell, z["low"], z["high"],
            float(bar.close), self.counts,
        )
        if base is None:
            return
        spec = aggressive.refine_h1_to_m15(
            self.m15, base, tsell, self.pip, self.spread, now, self.counts, self.rules,
        )
        if spec is None:
            return
        entry, stop, target, risk = spec["entry"], spec["stop"], spec["target"], spec["risk"]
        self._emit_order(now, tsell, entry, stop, target, "ag_h1_m15", z, z["tf"],
                         "static", "z", count_key="ag_zone_orders")
        if self.rules:
            self.pending_orders.append({"entry": entry, "sell": tsell, "z_key": z["key"], "leg": "zone"})
        liq_t = self._liq_target(up, entry, risk)
        if liq_t is not None:
            self._emit_order(now, tsell, entry, stop, liq_t, "ag_h1_m15", z, z["tf"],
                             "liq", "z", count_key="ag_zone_liq_orders")
        else:
            self.counts["ag_zone_liq_skipped_r"] += 1

    def _emit_order(self, now, tsell, entry, stop, target, kind, z, zone_tf,
                    target_mode, prefix, count_key=None, extra=None):
        oid = len(self.orders) + 1
        rec = {
            "id": oid, "placed_ts": now, "placed_ts_dt": now,
            "direction": "sell" if tsell else "buy",
            "kind": kind, "entry": entry, "stop": stop, "target": target,
            "leg": "zone", "zone_tf": zone_tf, "zone_low": z["low"], "zone_high": z["high"],
            "zone_ts": z["ts"], "target_mode": target_mode,
            "choch_ts": now, "choch_level": z["broken_level"], "idm_ts": z["ts"],
        }
        if extra:
            rec.update(extra)
        self.orders.append(rec)
        if count_key:
            self.counts[count_key] += 1
        else:
            self.counts[f"{prefix}_orders_placed"] += 1
            self.log.record("M15", now, f"order_{kind}_zone_{zone_tf.lower()}",
                            direction=rec["direction"], entry=round(entry, 6),
                            stop=round(stop, 6), target=round(target, 6))
