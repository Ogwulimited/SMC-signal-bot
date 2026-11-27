"""Major-Swing Zone Layer (D1 / H4 zones -> M15 confirmation -> static 3R or liquidity target).
Wraps CycleRecorder without changing a single line of cycle.py, MapRecorder,
or aggressive.py. Enabled only for the `mz` variant via SETTINGS["enabled"].
"""
from bisect import bisect_left, bisect_right, insort
from collections import defaultdict, deque
import pandas as pd
from src import config
from src.research.engine import aggressive as ag
from src.research.engine import cycle as cy
from src.research.engine.bias import htf_bias

SETTINGS = {"enabled": False, "rules": False, "pip": 0.0001, "spread": 0.0}
LIQ_CAP = 100
H1_OPPOSING_HTF_MIN_R = 3.0
H1_ZONE_MAX_AGE = pd.Timedelta(hours=48)
H1_SCAN_MAX_DURATION = pd.Timedelta(hours=24)
H1_ORDER_EXPIRY = pd.Timedelta(hours=24)


def _ny_killzone_info(ts):
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    ny = t.tz_convert("America/New_York")
    h = ny.hour
    if 2 <= h < 5:
        kz = "London_KZ"
    elif 7 <= h < 10:
        kz = "NY_AM_KZ"
    elif 10 <= h < 12:
        kz = "London_Close_KZ"
    elif 20 <= h < 24:
        kz = "Asian_KZ"
    else:
        kz = "Outside_KZ"
    return h, kz


def _fvg_overlaps_ob(fvgs, ob_top, ob_bot):
    for f in fvgs or []:
        if max(float(f["bottom"]), float(ob_bot)) <= min(float(f["top"]), float(ob_top)):
            return True
    return False


class ZoneRecorder(cy.CycleRecorder):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._z_bias = {"D1": None, "H4": None}
        self._z_zones = []
        self._z_zid = 0
        self._z_scans = []
        self._z_ltf_sw = deque(maxlen=40)
        self._z_seen = {"D1": 0, "H4": 0}
        self._z_liq = {"H1": deque(maxlen=LIQ_CAP), "H4": deque(maxlen=LIQ_CAP), "D1": deque(maxlen=LIQ_CAP)}
        self._z_fvg = {"D1": deque(maxlen=60), "H4": deque(maxlen=120), "H1": deque(maxlen=240)}
        self._z_bars = {"D1": deque(maxlen=40), "H4": deque(maxlen=60), "H1": deque(maxlen=240)}
        self._z_watch = []
        self._z_pend = []
        self._z_filled = []
        self.zone_orders = []
        self.zone_skipped = defaultdict(int)
        self._z_oid = 0
        # --- H1 continuation stream (additive, strictly isolated from D1/H4) ---
        self._h1_seen = 0
        self._h1_zones = []
        self._h1_zid = 0
        self._h1_scans = []
        self._h1_pend = []

    def on_bar(self, tf, bar):
        super().on_bar(tf, bar)
        if not SETTINGS["enabled"]:
            return
        if tf in ("D1", "H4", "H1"):
            self._z_on_htf_bar(tf, bar)
        if tf in ("D1", "H4"):
            self._z_on_htf(tf, bar)
        elif tf == "H1":
            self._h1_on_bar(bar)
        elif tf == config.LTF_TF:
            self._z_on_ltf(bar)
            self._h1_on_ltf(bar)

    # --- HTF bar / FVG / liquidity tracking ---
    def _z_on_htf_bar(self, tf, bar):
        b = {
            "time": bar.time,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
        }
        buf = self._z_bars[tf]
        buf.append(b)
        for g in self._z_fvg[tf]:
            if g["mitigated"]:
                continue
            if g["dir"] == "bullish" and b["low"] <= g["top"]:
                g["mitigated"] = True
            elif g["dir"] == "bearish" and b["high"] >= g["bottom"]:
                g["mitigated"] = True
        if len(buf) >= 3:
            b0, b1, b2 = buf[-3], buf[-2], buf[-1]
            atr = self._atr.get(tf) or 0.0
            min_sz = config.FVG_MIN_SIZE_ATR * atr
            if b2["low"] - b0["high"] > min_sz:
                self._z_fvg[tf].append({
                    "tf": tf, "dir": "bullish", "top": b2["low"], "bottom": b0["high"],
                    "created_time": b2["time"], "mitigated": False, "ob_candle": b0, "imp_candle": b1,
                })
            elif b0["low"] - b2["high"] > min_sz:
                self._z_fvg[tf].append({
                    "tf": tf, "dir": "bearish", "top": b0["low"], "bottom": b2["high"],
                    "created_time": b2["time"], "mitigated": False, "ob_candle": b0, "imp_candle": b1,
                })
        for p in self._z_liq[tf]:
            if p["swept"]:
                continue
            if p["side"] == "BSL" and b["high"] > p["price"]:
                p["swept"] = True
            elif p["side"] == "SSL" and b["low"] < p["price"]:
                p["swept"] = True
        sw_list = self._sw[tf]
        if sw_list:
            last = sw_list[-1]
            pool = self._z_liq[tf]
            if not pool or pool[-1]["time"] != last["time"] or pool[-1]["type"] != last["type"]:
                pool.append({
                    "tf": tf,
                    "side": "BSL" if last["type"] == "high" else "SSL",
                    "type": last["type"],
                    "price": float(last["price"]),
                    "time": last["time"],
                    "swept": False,
                })

    # --- D1 / H4 zone building (impulse leg between consecutive major swings) ---
    def _z_on_htf(self, tf, bar):
        sw = self._sw[tf]
        if len(sw) > self._z_seen[tf]:
            self._z_seen[tf] = len(sw)
            if len(sw) >= 2:
                self._z_build_from_leg(tf, sw[-2], sw[-1], bar.time)
        n = config.MAJOR_BIAS_FIRST_READ if config.MAJOR_HTF else config.BIAS_FIRST_READ_SWINGS
        self._z_bias[tf] = htf_bias(sw, float(bar.close), n)
        b_close = float(bar.close)
        b_high, b_low = float(bar.high), float(bar.low)
        for z in self._z_zones:
            if z["tf"] != tf or z["status"] == "invalidated":
                continue
            if z["status"] in ("fresh", "touched") and z["created_time"] < bar.time:
                if b_low <= z["top"] and b_high >= z["bottom"]:
                    z["status"] = "touched"
                    if z["first_touch_time"] is None:
                        z["first_touch_time"] = bar.time
            if z["dir"] == "bullish" and b_close < z["bottom"]:
                z["status"] = "invalidated"
                if z["kind"] == "ob" and not z.get("flipped") and not SETTINGS["rules"]:
                    self._z_flip_breaker(z, bar.time)
            elif z["dir"] == "bearish" and b_close > z["top"]:
                z["status"] = "invalidated"
                if z["kind"] == "ob" and not z.get("flipped") and not SETTINGS["rules"]:
                    self._z_flip_breaker(z, bar.time)

    def _z_build_from_leg(self, tf, s_prev, s_last, confirmed_time):
        if s_prev["type"] == "low" and s_last["type"] == "high" and s_last["price"] > s_prev["price"]:
            direction = "bullish"
        elif s_prev["type"] == "high" and s_last["type"] == "low" and s_last["price"] < s_prev["price"]:
            direction = "bearish"
        else:
            return
        bars = [b for b in self._z_bars[tf] if s_prev["time"] <= b["time"] <= s_last["time"]]
        if not bars:
            return
        want_opp = "bearish" if direction == "bullish" else "bullish"
        chosen = None
        for b in bars:
            col = "bullish" if b["close"] > b["open"] else ("bearish" if b["close"] < b["open"] else "doji")
            if col == want_opp:
                chosen = b
                break
        if chosen is None:
            chosen = bars[0]
        top, bot = float(chosen["high"]), float(chosen["low"])
        if top <= bot:
            return
        fvg_hit = None
        for g in self._z_fvg[tf]:
            if g["dir"] == direction and s_prev["time"] <= g["created_time"] <= s_last["time"]:
                fvg_hit = g
                break
        if SETTINGS["rules"]:
            if fvg_hit is None:
                self.zone_skipped["z_no_htf_fvg"] += 1
                return
            self._z_add_zone(
                tf, "ob_fvg", direction, top, bot, confirmed_time,
                s_prev["price"], s_last["price"], has_fvg=True,
            )
            return
        self._z_add_zone(
            tf, "ob", direction, top, bot, confirmed_time,
            s_prev["price"], s_last["price"], has_fvg=(fvg_hit is not None),
        )
        if fvg_hit is not None:
            self._z_add_zone(
                tf, "fvg", direction, float(fvg_hit["top"]), float(fvg_hit["bottom"]),
                confirmed_time, s_prev["price"], s_last["price"], has_fvg=True,
            )

    def _z_add_zone(self, tf, kind, direction, top, bottom, ctime, sp_start, sp_end, has_fvg=False):
        if top <= bottom:
            return
        self._z_zid += 1
        self._z_zones.append({
            "id": self._z_zid, "tf": tf, "kind": kind, "dir": direction,
            "top": top, "bottom": bottom, "created_time": ctime,
            "status": "fresh", "first_touch_time": None, "used": False, "flipped": False,
            "has_fvg": has_fvg, "leg_start": float(sp_start), "leg_end": float(sp_end),
        })

    def _z_flip_breaker(self, z, ctime):
        z["flipped"] = True
        new_dir = "bearish" if z["dir"] == "bullish" else "bullish"
        self._z_add_zone(
            z["tf"], "breaker", new_dir, z["top"], z["bottom"], ctime,
            z["leg_start"], z["leg_end"], has_fvg=z["has_fvg"],
        )

    # --- M15 confirmation inside active D1/H4 zones ---
    def _z_on_ltf(self, bar):
        b = {
            "time": bar.time,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
        }
        sw = self._sw[config.LTF_TF]
        if len(sw) > len(self._z_ltf_sw) or (sw and (not self._z_ltf_sw or sw[-1]["time"] != self._z_ltf_sw[-1]["time"])):
            self._z_ltf_sw.append(dict(sw[-1]))
        if SETTINGS["rules"]:
            self._z_update_orders(b)
        active_ids = {s["zone"]["id"] for s in self._z_scans}
        for z in self._z_zones:
            if z["status"] == "invalidated" or z["used"] or z["id"] in active_ids:
                continue
            if z["created_time"] >= b["time"]:
                continue
            if not self._z_bias_allows(z):
                continue
            if b["low"] <= z["top"] and b["high"] >= z["bottom"]:
                if z["first_touch_time"] is None:
                    z["first_touch_time"] = b["time"]
                    z["status"] = "touched"
                self._z_scans.append({
                    "zone": z, "touch_time": b["time"], "choch": None,
                    "swept": self._z_check_sweep(z, b),
                })
                active_ids.add(z["id"])
        keep = []
        for s in self._z_scans:
            z = s["zone"]
            if z["status"] == "invalidated" or z["used"]:
                continue
            if not self._z_bias_allows(z):
                continue
            if not s["swept"] and self._z_check_sweep(z, b):
                s["swept"] = True
            if s["choch"] is None:
                ch = self._z_detect_choch(z["dir"], s["touch_time"], b)
                if ch is not None:
                    s["choch"] = ch
                    self._z_try_emit(s, b)
                    if z["used"]:
                        continue
            keep.append(s)
        self._z_scans = keep
        self._z_step_watches(b)

    def _z_update_orders(self, b):
        still_p = []
        for p in self._z_pend:
            if p["side"] == "buy" and b["low"] <= p["entry"]:
                p["fill_time"] = b["time"]
                self._z_filled.append(p)
            elif p["side"] == "sell" and b["high"] >= p["entry"]:
                p["fill_time"] = b["time"]
                self._z_filled.append(p)
            else:
                if abs(b["close"] - p["entry"]) <= config.ZONE_CANCEL_PIPS * SETTINGS["pip"]:
                    still_p.append(p)
        self._z_pend = still_p
        still_f = []
        for f in self._z_filled:
            if f["side"] == "buy":
                if b["low"] <= f["stop"] or b["high"] >= f["target"]:
                    continue
            else:
                if b["high"] >= f["stop"] or b["low"] <= f["target"]:
                    continue
            still_f.append(f)
        self._z_filled = still_f

    def _z_bias_allows(self, z):
        want = z["dir"]
        d1, h4 = self._z_bias["D1"], self._z_bias["H4"]
        if z["tf"] == "D1":
            return d1 == want
        return h4 == want and (d1 == want or d1 in (None, "neutral"))

    def _z_check_sweep(self, z, b):
        want_side = "SSL" if z["dir"] == "bullish" else "BSL"
        for tf in ("H1", "H4", "D1"):
            for p in self._z_liq[tf]:
                if p["side"] != want_side or p["time"] >= b["time"]:
                    continue
                if z["bottom"] <= p["price"] <= z["top"]:
                    if (want_side == "SSL" and b["low"] < p["price"]) or (want_side == "BSL" and b["high"] > p["price"]):
                        return True
        return False

    def _z_detect_choch(self, direction, touch_time, b):
        want_type = "high" if direction == "bullish" else "low"
        ref = None
        for s in reversed(self._z_ltf_sw):
            if s["type"] == want_type and s["time"] <= b["time"]:
                ref = s
                break
        if ref is None:
            return None
        if direction == "bullish" and b["close"] > ref["price"]:
            return {"dir": "bullish", "level": ref["price"], "time": b["time"], "ref_time": ref["time"]}
        if direction == "bearish" and b["close"] < ref["price"]:
            return {"dir": "bearish", "level": ref["price"], "time": b["time"], "ref_time": ref["time"]}
        return None

    def _z_try_emit(self, s, b):
        z = s["zone"]
        ch = s["choch"]
        direction = z["dir"]
        sell = direction == "bearish"
        ltf_bars = list(self._ltf)
        if not ltf_bars:
            return
        idx_ch = len(ltf_bars) - 1
        idx_start = max(0, idx_ch - 20)
        for i in range(idx_ch, -1, -1):
            if ltf_bars[i]["time"] <= ch["ref_time"]:
                idx_start = i
                break
        leg_bars = ltf_bars[idx_start:idx_ch + 1]
        atr_ltf = self._atr.get(config.LTF_TF) or 0.0
        fvgs = cy.leg_fvgs(leg_bars, direction, atr_ltf)
        idm_swept = self._z_has_idm(direction, s["touch_time"], b["time"], ltf_bars, idx_start, idx_ch)
        if not idm_swept and not fvgs:
            self.zone_skipped["z_no_idm_no_fvg"] += 1
            return
        ob = cy.find_ob(ltf_bars, idx_start, idx_ch, direction)
        if ob is None:
            self.zone_skipped["z_no_ltf_ob"] += 1
            return
        if SETTINGS["rules"] and not sell and b["low"] <= float(ob["high"]):
            self.zone_skipped["z_ob_touched_same_bar"] += 1
            return
        if getattr(config, "SYM_SAME_BAR_SKIP_BOTH", False) and sell and b["high"] >= float(ob["low"]):
            self.zone_skipped["z_ob_touched_same_bar"] += 1
            return

        # --- Phase 2: Check if entry sits inside a clean H1 base inside the D1/H4 zone ---
        h1_bars_list = list(self._z_bars["H1"])
        h1_sw_list = list(self._sw["H1"])
        h1_atr = self._atr.get("H1") or 0.0
        h1_base = ag.pick_h1_base(
            h1_bars_list, h1_sw_list, z["created_time"], b["time"],
            "sell" if sell else "buy", h1_atr,
        )
        in_h1_base = False
        if h1_base is not None:
            hb_lo, hb_hi = float(h1_base[0]), float(h1_base[1])
            ob_mid = 0.5 * (float(ob["high"]) + float(ob["low"]))
            if hb_lo <= ob_mid <= hb_hi:
                in_h1_base = True
        if getattr(config, "ZONE_H1_REFINEMENT", False) and not in_h1_base:
            self.zone_skipped["z_not_in_h1_base"] += 1
            return

        # --- Phase 3: Compute D1/H4 Zone Dealing Range Location ---
        leg_lo = min(float(z["leg_start"]), float(z["leg_end"]))
        leg_hi = max(float(z["leg_start"]), float(z["leg_end"]))
        leg_rng = leg_hi - leg_lo
        ob_entry_est = float(ob["low"]) if sell else float(ob["high"])
        if leg_rng > 1e-9:
            deal_pct = ((leg_hi - ob_entry_est) / leg_rng * 100.0) if not sell else ((ob_entry_est - leg_lo) / leg_rng * 100.0)
        else:
            deal_pct = 50.0
        if getattr(config, "ZONE_REQUIRE_DISCOUNT_PREMIUM", False) and deal_pct < 50.0:
            self.zone_skipped["z_not_discount_premium"] += 1
            return

        fvg_ov = _fvg_overlaps_ob(fvgs, ob["high"], ob["low"])
        ch_body = abs(float(b["close"]) - float(b["open"]))
        disp_atr = (ch_body / atr_ltf) if atr_ltf > 1e-9 else 0.0
        ch_rng = float(b["high"]) - float(b["low"])
        disp_close_pct = ((float(b["close"]) - float(b["low"])) / ch_rng) if (not sell and ch_rng > 1e-9) else (
            ((float(b["high"]) - float(b["close"])) / ch_rng) if (sell and ch_rng > 1e-9) else 0.5
        )

        meta = {
            "in_h1_base": in_h1_base,
            "deal_pct": round(deal_pct, 2),
            "local_ote_pct": round(deal_pct, 2),
            "fvg_overlap": bool(fvg_ov),
            "sweep_reclaim": bool(s["swept"]),
            "disp_body_atr": round(disp_atr, 3),
            "disp_close_pct": round(disp_close_pct, 3),
        }

        z["used"] = True
        self._z_emit_pair(
            z, "ob", direction, float(ob["high"]), float(ob["low"]),
            b["time"], s["swept"], idm_swept, bool(fvgs), meta=meta,
        )
        self._z_watch.append({
            "zone": z, "dir": direction, "top": float(ob["high"]), "bottom": float(ob["low"]),
            "born": b["time"], "swept": s["swept"], "idm": idm_swept, "fvg": bool(fvgs),
            "meta": meta,
        })

    def _z_has_idm(self, direction, touch_time, now_time, ltf_bars, idx_start, idx_ch):
        want_type = "low" if direction == "bullish" else "high"
        for s in self._z_ltf_sw:
            if s["type"] != want_type or s["time"] < touch_time or s["time"] >= now_time:
                continue
            for b in ltf_bars[idx_start:idx_ch + 1]:
                if b["time"] <= s["time"]:
                    continue
                if direction == "bullish" and b["low"] < s["price"]:
                    return True
                if direction == "bearish" and b["high"] > s["price"]:
                    return True
        return False

    def _z_step_watches(self, b):
        if SETTINGS["rules"]:
            self._z_watch = []
            return
        keep = []
        for w in self._z_watch:
            if w["dir"] == "bullish" and b["close"] < w["bottom"]:
                self._z_emit_pair(
                    w["zone"], "breaker", "bearish", w["top"], w["bottom"],
                    b["time"], w["swept"], w["idm"], w["fvg"], meta=w.get("meta"),
                )
            elif w["dir"] == "bearish" and b["close"] > w["top"]:
                self._z_emit_pair(
                    w["zone"], "breaker", "bullish", w["top"], w["bottom"],
                    b["time"], w["swept"], w["idm"], w["fvg"], meta=w.get("meta"),
                )
            else:
                keep.append(w)
        self._z_watch = keep

    # --- Emit both static 3R and liquidity-targeted orders for a confirmed setup ---
    def _z_emit_pair(self, z, kind, direction, ob_top, ob_bot, placed_time, swept, idm, has_fvg, meta=None):
        meta = meta or {}
        ny_h, kz = _ny_killzone_info(placed_time)
        if getattr(config, "KILLZONE_ONLY", False) and kz == "Outside_KZ":
            self.zone_skipped["z_outside_killzone"] += 1
            return
        if SETTINGS["rules"]:
            side_now = "sell" if direction == "bearish" else "buy"
            if any(p["side"] == side_now for p in self._z_pend):
                self.zone_skipped["z_dup_pending_side"] += 1
                return
            if any(f["side"] == side_now for f in self._z_filled):
                self.zone_skipped["z_open_trade_side"] += 1
                return
        sell = direction == "bearish"
        spread = float(SETTINGS["spread"])
        atr_h1 = self._atr.get("H1") or 0.0
        buf = config.STOP_BUFFER_ATR * atr_h1
        if sell:
            entry = ob_bot
            stop = ob_top + buf + spread
            risk = stop - entry
        else:
            entry = ob_top + spread
            stop = ob_bot - buf
            risk = entry - stop
        if risk <= 0:
            self.zone_skipped["z_bad_risk"] += 1
            return
        min_risk = (spread / config.MAX_SPREAD_RISK_RATIO) * 1.0001 if spread > 0 else 0.0
        min_risk_padded = False
        if risk < min_risk:
            if getattr(config, "SKIP_MIN_RISK_PADDED", False):
                self.zone_skipped["z_ob_min_risk_skipped"] += 1
                return
            if sell:
                stop = entry + min_risk
            else:
                stop = entry - min_risk
            risk = min_risk
            min_risk_padded = True
            self.zone_skipped["z_ob_min_risk_padded"] += 1
        t_static = entry - config.RR_STATIC * risk if sell else entry + config.RR_STATIC * risk
        if SETTINGS["rules"] and not self._z_room_ok(direction, entry, risk, z["id"]):
            self.zone_skipped["z_opposing_zone_blocks_3r"] += 1
            return
        self._z_oid += 1
        base = {
            "order_id": f"Z_{self._z_oid}", "leg": "zone", "kind": kind,
            "side": "sell" if sell else "buy", "placed_time": placed_time,
            "entry": entry, "stop": stop, "zone_id": z["id"], "zone_tf": z["tf"],
            "zone_kind": z["kind"], "zone_top": z["top"], "zone_bottom": z["bottom"],
            "zone_created": z["created_time"], "liq_swept": swept, "idm_swept": idm,
            "has_fvg": has_fvg,
            "min_risk_padded": min_risk_padded,
            "in_h1_base": meta.get("in_h1_base", False),
            "deal_pct": meta.get("deal_pct", 50.0),
            "local_ote_pct": meta.get("local_ote_pct", 50.0),
            "fvg_overlap": meta.get("fvg_overlap", has_fvg),
            "sweep_reclaim": meta.get("sweep_reclaim", swept),
            "disp_body_atr": meta.get("disp_body_atr", 0.0),
            "disp_close_pct": meta.get("disp_close_pct", 0.5),
            "ny_hour": ny_h,
            "killzone": kz,
        }
        o_static = dict(base, target=t_static, target_mode="static", target_r=config.RR_STATIC, liq_tf=None)
        self.zone_orders.append(o_static)
        if SETTINGS["rules"]:
            self._z_pend.append({
                "side": o_static["side"], "entry": entry, "stop": stop,
                "target": t_static, "placed_time": placed_time,
            })
        liq = self._z_pick_liquidity_target(direction, entry, risk)
        if liq is not None:
            t_liq, r_liq, ltf = liq
            self.zone_orders.append(dict(base, order_id=f"Z_{self._z_oid}L", target=t_liq, target_mode="liquidity", target_r=r_liq, liq_tf=ltf))
        else:
            self.zone_skipped["z_no_liq_target_3r"] += 1

    def _z_room_ok(self, direction, entry, risk, own_id):
        req = H1_OPPOSING_HTF_MIN_R * risk
        opp_dir = "bearish" if direction == "bullish" else "bullish"
        for z in self._z_zones:
            if z["id"] == own_id or z["status"] == "invalidated" or z["dir"] != opp_dir:
                continue
            if direction == "bullish" and z["bottom"] > entry and (z["bottom"] - entry) < req:
                return False
            if direction == "bearish" and z["top"] < entry and (entry - z["top"]) < req:
                return False
        return True

    def _z_pick_liquidity_target(self, direction, entry, risk):
        want_side = "BSL" if direction == "bullish" else "SSL"
        best = None
        for tf in ("H1", "H4", "D1"):
            for p in self._z_liq[tf]:
                if p["swept"] or p["side"] != want_side:
                    continue
                dist = (p["price"] - entry) if direction == "bullish" else (entry - p["price"])
                r = dist / risk
                if r < config.MIN_TARGET_R:
                    continue
                if best is None or dist < best[0]:
                    best = (dist, p["price"], r, tf)
        if best is None:
            return None
        return best[1], best[2], best[3]

    # ==================================================================
    # H1 CONTINUATION STREAM (additive; only runs when SETTINGS["rules"])
    # ==================================================================
    def _h1_on_bar(self, bar):
        if not SETTINGS["rules"] or not getattr(config, "H1_STREAM_ENABLED", True):
            return
        sw = self._sw["H1"]
        if len(sw) > self._h1_seen:
            self._h1_seen = len(sw)
            if len(sw) >= 2:
                self._h1_build_from_leg(sw[-2], sw[-1], bar.time)
        b_close = float(bar.close)
        b_high, b_low = float(bar.high), float(bar.low)
        for z in self._h1_zones:
            if z["status"] == "invalidated":
                continue
            if (bar.time - z["created_time"]) > H1_ZONE_MAX_AGE:
                z["status"] = "invalidated"
                continue
            if z["status"] == "fresh" and z["created_time"] < bar.time:
                if b_low <= z["top"] and b_high >= z["bottom"]:
                    z["status"] = "touched"
                    if z["first_touch_time"] is None:
                        z["first_touch_time"] = bar.time
            if z["dir"] == "bullish" and b_close < z["bottom"]:
                z["status"] = "invalidated"
            elif z["dir"] == "bearish" and b_close > z["top"]:
                z["status"] = "invalidated"

    def _h1_build_from_leg(self, s_prev, s_last, confirmed_time):
        if s_prev["type"] == "low" and s_last["type"] == "high" and s_last["price"] > s_prev["price"]:
            direction = "bullish"
        elif s_prev["type"] == "high" and s_last["type"] == "low" and s_last["price"] < s_prev["price"]:
            direction = "bearish"
        else:
            return
        bars = [b for b in self._z_bars["H1"] if s_prev["time"] <= b["time"] <= s_last["time"]]
        if not bars:
            return
        want_opp = "bearish" if direction == "bullish" else "bullish"
        chosen = None
        for b in bars:
            col = "bullish" if b["close"] > b["open"] else ("bearish" if b["close"] < b["open"] else "doji")
            if col == want_opp:
                chosen = b
                break
        if chosen is None:
            chosen = bars[0]
        top, bot = float(chosen["high"]), float(chosen["low"])
        if top <= bot:
            return
        fvg_hit = None
        for g in self._z_fvg["H1"]:
            if g["dir"] == direction and s_prev["time"] <= g["created_time"] <= s_last["time"]:
                fvg_hit = g
                break
        if fvg_hit is None:
            self.zone_skipped["h1_no_fvg"] += 1
            return
        self._h1_zid += 1
        self._h1_zones.append({
            "id": self._h1_zid, "tf": "H1", "kind": "ob_fvg", "dir": direction,
            "top": top, "bottom": bot, "created_time": confirmed_time,
            "status": "fresh", "first_touch_time": None, "used": False,
            "has_fvg": True, "leg_start": float(s_prev["price"]), "leg_end": float(s_last["price"]),
        })

    def _h1_bias_allows(self, z):
        want = z["dir"]
        return self._z_bias["D1"] == want and self._z_bias["H4"] == want

    def _h1_inside_parent_zone(self, z):
        for pz in self._z_zones:
            if pz["status"] == "invalidated" or pz["dir"] != z["dir"]:
                continue
            if pz["bottom"] <= z["top"] and pz["top"] >= z["bottom"]:
                return True
        return False

    def _h1_on_ltf(self, bar):
        if not SETTINGS["rules"] or not getattr(config, "H1_STREAM_ENABLED", True):
            return
        b = {
            "time": bar.time,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
        }
        self._h1_update_pend(b)
        active_ids = {s["zone"]["id"] for s in self._h1_scans}
        for z in self._h1_zones:
            if z["status"] == "invalidated" or z["used"] or z["id"] in active_ids:
                continue
            if z["created_time"] >= b["time"]:
                continue
            if (b["time"] - z["created_time"]) > H1_ZONE_MAX_AGE:
                z["status"] = "invalidated"
                continue
            if not self._h1_bias_allows(z):
                continue
            if self._h1_inside_parent_zone(z):
                continue
            if b["low"] <= z["top"] and b["high"] >= z["bottom"]:
                if z["first_touch_time"] is None:
                    z["first_touch_time"] = b["time"]
                    z["status"] = "touched"
                self._h1_scans.append({
                    "zone": z, "touch_time": b["time"], "choch": None,
                    "swept": self._z_check_sweep(z, b),
                })
                active_ids.add(z["id"])
        keep = []
        for s in self._h1_scans:
            z = s["zone"]
            if z["status"] == "invalidated" or z["used"]:
                continue
            if (b["time"] - s["touch_time"]) > H1_SCAN_MAX_DURATION:
                z["used"] = True
                self.zone_skipped["h1_scan_expired"] += 1
                continue
            if not self._h1_bias_allows(z):
                continue
            if not s["swept"] and self._z_check_sweep(z, b):
                s["swept"] = True
            if s["choch"] is None:
                ch = self._z_detect_choch(z["dir"], s["touch_time"], b)
                if ch is not None:
                    s["choch"] = ch
                    self._h1_try_emit(s, b)
                    if z["used"]:
                        continue
            keep.append(s)
        self._h1_scans = keep

    def _h1_update_pend(self, b):
        still = []
        for p in self._h1_pend:
            if (b["time"] - p["placed_time"]) > H1_ORDER_EXPIRY:
                continue
            if p["side"] == "buy" and b["low"] <= p["entry"]:
                self._z_filled.append(dict(p, fill_time=b["time"]))
            elif p["side"] == "sell" and b["high"] >= p["entry"]:
                self._z_filled.append(dict(p, fill_time=b["time"]))
            else:
                if abs(b["close"] - p["entry"]) <= config.ZONE_CANCEL_PIPS * SETTINGS["pip"]:
                    still.append(p)
        self._h1_pend = still

    def _h1_try_emit(self, s, b):
        z = s["zone"]
        ch = s["choch"]
        direction = z["dir"]
        sell = direction == "bearish"
        ltf_bars = list(self._ltf)
        if not ltf_bars:
            return
        idx_ch = len(ltf_bars) - 1
        idx_start = max(0, idx_ch - 20)
        for i in range(idx_ch, -1, -1):
            if ltf_bars[i]["time"] <= ch["ref_time"]:
                idx_start = i
                break
        leg_bars = ltf_bars[idx_start:idx_ch + 1]
        atr_ltf = self._atr.get(config.LTF_TF) or 0.0
        fvgs = cy.leg_fvgs(leg_bars, direction, atr_ltf)
        idm_swept = self._z_has_idm(direction, s["touch_time"], b["time"], ltf_bars, idx_start, idx_ch)
        if not idm_swept or not fvgs:
            self.zone_skipped["h1_need_idm_and_fvg"] += 1
            return
        ob = cy.find_ob(ltf_bars, idx_start, idx_ch, direction)
        if ob is None:
            self.zone_skipped["h1_no_ltf_ob"] += 1
            return
        if b["low"] <= float(ob["high"]) and b["high"] >= float(ob["low"]):
            self.zone_skipped["h1_ob_touched_same_bar"] += 1
            return
        side_now = "sell" if sell else "buy"
        if any(p["side"] == side_now for p in self._z_pend) or any(p["side"] == side_now for p in self._h1_pend):
            self.zone_skipped["h1_dup_pending_side"] += 1
            return
        if any(f["side"] == side_now for f in self._z_filled):
            self.zone_skipped["h1_open_trade_side"] += 1
            return

        ny_h, kz = _ny_killzone_info(b["time"])
        if getattr(config, "KILLZONE_ONLY", False) and kz == "Outside_KZ":
            self.zone_skipped["h1_outside_killzone"] += 1
            return

        spread = float(SETTINGS["spread"])
        atr_h1 = self._atr.get("H1") or 0.0
        buf = config.STOP_BUFFER_ATR * atr_h1
        ob_top, ob_bot = float(ob["high"]), float(ob["low"])
        if sell:
            entry = ob_bot
            stop = ob_top + buf + spread
            risk = stop - entry
        else:
            entry = ob_top + spread
            stop = ob_bot - buf
            risk = entry - stop
        if risk <= 0:
            self.zone_skipped["h1_bad_risk"] += 1
            return
        min_risk = (spread / config.MAX_SPREAD_RISK_RATIO) * 1.0001 if spread > 0 else 0.0
        min_risk_padded = False
        if risk < min_risk:
            if getattr(config, "SKIP_MIN_RISK_PADDED", False):
                self.zone_skipped["h1_ob_min_risk_skipped"] += 1
                return
            stop = (entry + min_risk) if sell else (entry - min_risk)
            risk = min_risk
            min_risk_padded = True
            self.zone_skipped["h1_ob_min_risk_padded"] += 1
        t_static = entry - config.RR_STATIC * risk if sell else entry + config.RR_STATIC * risk
        if not self._z_room_ok(direction, entry, risk, -1):
            self.zone_skipped["h1_opposing_zone_blocks_3r"] += 1
            return

        leg_lo = min(float(z["leg_start"]), float(z["leg_end"]))
        leg_hi = max(float(z["leg_start"]), float(z["leg_end"]))
        leg_rng = leg_hi - leg_lo
        if leg_rng > 1e-9:
            deal_pct = ((leg_hi - entry) / leg_rng * 100.0) if not sell else ((entry - leg_lo) / leg_rng * 100.0)
        else:
            deal_pct = 50.0
        fvg_ov = _fvg_overlaps_ob(fvgs, ob_top, ob_bot)
        ch_body = abs(float(b["close"]) - float(b["open"]))
        disp_atr = (ch_body / atr_ltf) if atr_ltf > 1e-9 else 0.0
        ch_rng = float(b["high"]) - float(b["low"])
        disp_close_pct = ((float(b["close"]) - float(b["low"])) / ch_rng) if (not sell and ch_rng > 1e-9) else (
            ((float(b["high"]) - float(b["close"])) / ch_rng) if (sell and ch_rng > 1e-9) else 0.5
        )

        z["used"] = True
        self._z_oid += 1
        exp_time = b["time"] + H1_ORDER_EXPIRY
        base = {
            "order_id": f"Z_{self._z_oid}", "leg": "zone", "kind": "ob",
            "side": side_now, "placed_time": b["time"], "expiry_time": exp_time,
            "entry": entry, "stop": stop, "zone_id": z["id"], "zone_tf": "H1",
            "zone_kind": z["kind"], "zone_top": z["top"], "zone_bottom": z["bottom"],
            "zone_created": z["created_time"], "liq_swept": s["swept"], "idm_swept": True,
            "has_fvg": True,
            "min_risk_padded": min_risk_padded,
            "in_h1_base": True,
            "deal_pct": round(deal_pct, 2),
            "local_ote_pct": round(deal_pct, 2),
            "fvg_overlap": bool(fvg_ov),
            "sweep_reclaim": bool(s["swept"]),
            "disp_body_atr": round(disp_atr, 3),
            "disp_close_pct": round(disp_close_pct, 3),
            "ny_hour": ny_h,
            "killzone": kz,
        }
        self.zone_orders.append(dict(base, target=t_static, target_mode="static", target_r=config.RR_STATIC, liq_tf=None))
        self._h1_pend.append({
            "side": side_now, "entry": entry, "stop": stop,
            "target": t_static, "placed_time": b["time"],
        })
        liq = self._z_pick_liquidity_target(direction, entry, risk)
        if liq is not None:
            t_liq, r_liq, ltf = liq
            self.zone_orders.append(dict(base, order_id=f"Z_{self._z_oid}L", target=t_liq, target_mode="liquidity", target_r=r_liq, liq_tf=ltf))
