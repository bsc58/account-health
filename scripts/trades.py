from datetime import date

EPS = 1e-9
EAE_METHODS = {"Expiration": "expired", "Assignment": "assigned", "Exercise": "exercised"}
CODE_METHODS = (("A", "assigned"), ("Ex", "exercised"), ("Ep", "expired"))
ELIGIBLE = ("stock", "leveraged_etf", "long_option", "debit_spread")


def _sign(value):
    return 1 if value > 0 else -1


def _day(text):
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def _method(codes):
    for code, method in CODE_METHODS:
        if code in codes:
            return method
    return "sold"


def _events(parsed):
    events = []
    for seq, row in enumerate(parsed["executions"]):
        if row["asset"] in ("STK", "OPT"):
            events.append(dict(row, kind="trade", seq=seq))
    for seq, row in enumerate(parsed["eae"]):
        if row["asset"] == "OPT" and row["type"] in EAE_METHODS:
            events.append({
                "kind": "eae",
                "conid": row["conid"],
                "date": row["date"],
                "time": "235959",
                "seq": seq,
                "quantity": row["quantity"],
                "method": EAE_METHODS[row["type"]],
            })
    return events


def _new_cycle(ev, direction):
    return {
        "conid": ev["conid"],
        "symbol": ev["symbol"],
        "description": ev["description"],
        "asset": ev["asset"],
        "underlying": ev["underlying"],
        "expiry": ev["expiry"],
        "put_call": ev["put_call"],
        "direction": direction,
        "open_date": ev["date"],
        "open_time": ev["time"],
        "order": ev["order"],
        "close_date": "",
        "close_time": "",
        "method": "",
        "open_net": 0.0,
        "close_net": 0.0,
        "quantity": 0.0,
        "adds": 0,
        "closed": False,
        "inferred": False,
    }


def _cycles(events, period_end, quality):
    by_conid = {}
    for ev in events:
        by_conid.setdefault(ev["conid"], []).append(ev)
    cycles = []
    for conid in sorted(by_conid):
        rows = sorted(by_conid[conid], key=lambda e: (e["date"], e["time"], e["kind"] == "eae", e["seq"]))
        pos = 0.0
        cur = None
        for ev in rows:
            if ev["kind"] == "eae":
                if abs(pos) < EPS:
                    continue
                size = min(abs(pos), abs(ev["quantity"])) if abs(ev["quantity"]) > EPS else abs(pos)
                qty = -size if pos > 0 else size
                net = 0.0
                method = ev["method"]
            else:
                qty = ev["quantity"]
                net = ev["net"]
                method = _method(ev["codes"])
                if abs(qty) < EPS:
                    continue
                if abs(pos) < EPS and method != "sold" and ev["asset"] == "OPT":
                    continue
                if abs(pos) < EPS and ev["open_close"].startswith("C"):
                    quality["orphan_closes"] += 1
                    quality["orphan_net"] += net
                    continue
            remaining = qty
            while abs(remaining) > EPS:
                if cur is None:
                    cur = _new_cycle(ev, _sign(remaining))
                if _sign(remaining) == cur["direction"]:
                    cur["open_net"] += net * remaining / qty
                    cur["quantity"] += abs(remaining)
                    cur["adds"] += 1
                    pos += remaining
                    remaining = 0.0
                else:
                    part = _sign(remaining) * min(abs(remaining), abs(pos))
                    cur["close_net"] += net * part / qty
                    pos += part
                    remaining -= part
                    if abs(pos) < EPS:
                        pos = 0.0
                        cur["closed"] = True
                        cur["close_date"] = ev["date"]
                        cur["close_time"] = ev["time"]
                        cur["method"] = method
                        cycles.append(cur)
                        cur = None
        if cur is not None:
            if cur["asset"] == "OPT" and cur["expiry"] and cur["expiry"] < period_end:
                cur["closed"] = True
                cur["close_date"] = cur["expiry"]
                cur["close_time"] = "235959"
                cur["method"] = "expired"
                cur["inferred"] = True
                quality["inferred_expiries"] += 1
            cycles.append(cur)
    return cycles


def _groups(cycles):
    keyed = {}
    singles = []
    for cycle in cycles:
        if cycle["asset"] == "OPT":
            key = (cycle["underlying"], cycle["open_date"], cycle["open_time"], cycle["put_call"])
            keyed.setdefault(key, []).append(cycle)
        else:
            singles.append([cycle])
    for key in sorted(keyed):
        legs = keyed[key]
        if len(legs) > 1 and len({leg["direction"] for leg in legs}) == 2:
            singles.append(legs)
        else:
            singles.extend([leg] for leg in legs)
    return singles


def _leveraged(leg, ident):
    if leg["symbol"].upper() in ident["leveraged_symbols"]:
        return True
    text = leg["description"].upper()
    return any(pattern in text for pattern in ident["leveraged_patterns"])


def _trade(legs, ident):
    first = min(legs, key=lambda leg: (leg["open_date"], leg["open_time"], leg["conid"]))
    open_net = sum(leg["open_net"] for leg in legs)
    pnl = sum(leg["open_net"] + leg["close_net"] for leg in legs)
    closed = all(leg["closed"] for leg in legs)
    if len(legs) > 1:
        kind = "debit_spread" if open_net < 0 else "credit_spread"
        label = first["underlying"] + " spread " + first["expiry"]
    elif first["asset"] == "OPT":
        kind = "long_option" if first["direction"] > 0 else "short_option"
        label = first["description"] or first["symbol"]
    else:
        if first["symbol"].upper() in ident["cash_like_symbols"]:
            kind = "cash_like"
        else:
            kind = "leveraged_etf" if _leveraged(first, ident) else "stock"
        label = first["symbol"]
    if first["asset"] == "OPT":
        dte = min((_day(leg["expiry"]) - _day(leg["open_date"])).days for leg in legs if leg["expiry"]) if any(
            leg["expiry"] for leg in legs) else None
        category = "weekly_option" if dte is not None and dte <= ident["weekly_dte"] else "option"
    else:
        dte = None
        category = kind
    methods = [leg["method"] for leg in legs]
    if "assigned" in methods:
        method = "assigned"
    elif "exercised" in methods:
        method = "exercised"
    elif closed and all(m == "expired" for m in methods):
        method = "expired"
    else:
        method = "sold" if closed else ""
    last = max(legs, key=lambda leg: (leg["close_date"], leg["close_time"]))
    return {
        "symbol": label,
        "underlying": first["underlying"],
        "conids": sorted(leg["conid"] for leg in legs),
        "kind": kind,
        "category": category,
        "direction": "long" if first["direction"] > 0 else "short",
        "eligible": kind in ELIGIBLE,
        "cost": abs(open_net),
        "pnl": pnl if closed else None,
        "open_date": first["open_date"],
        "open_time": first["open_time"],
        "close_date": last["close_date"] if closed else "",
        "close_time": last["close_time"] if closed else "",
        "method": method,
        "dte_at_open": dte,
        "adds": sum(leg["adds"] for leg in legs),
        "inferred_expiry": any(leg["inferred"] for leg in legs),
        "closed": closed,
    }


def build_trades(parsed, cfg):
    quality = {
        "orphan_closes": 0, "orphan_net": 0.0, "inferred_expiries": 0, "vanished": [],
        "cash_like_trades": 0, "cash_like_pnl": 0.0, "cash_like_symbols": [],
    }
    cycles = _cycles(_events(parsed), parsed["to"], quality)
    trades = [_trade(legs, cfg["identification"]) for legs in _groups(cycles)]
    parked = [t for t in trades if t["closed"] and t["kind"] == "cash_like"]
    quality["cash_like_trades"] = len(parked)
    quality["cash_like_pnl"] = sum(t["pnl"] for t in parked)
    quality["cash_like_symbols"] = sorted({t["symbol"] for t in parked})
    closed = sorted(
        (t for t in trades if t["closed"] and t["kind"] != "cash_like"),
        key=lambda t: (t["close_date"], t["close_time"], t["open_date"], t["open_time"], t["symbol"]),
    )
    for i, trade in enumerate(closed, 1):
        trade["id"] = "T%04d" % i
    unrealized = {}
    held = {}
    for pos in parsed["open_positions"]:
        unrealized[pos["conid"]] = unrealized.get(pos["conid"], 0.0) + pos["unrealized"]
        held[pos["conid"]] = held.get(pos["conid"], 0.0) + pos["cost"]
    still_open = sorted((t for t in trades if not t["closed"]), key=lambda t: (t["open_date"], t["open_time"], t["symbol"]))
    if parsed["has_positions"]:
        quality["vanished"] = [t["symbol"] for t in still_open if not any(c in unrealized for c in t["conids"])]
        still_open = [t for t in still_open if any(c in unrealized for c in t["conids"])]
    for i, trade in enumerate(still_open, 1):
        trade["id"] = "O%03d" % i
        known = [unrealized[c] for c in trade["conids"] if c in unrealized]
        trade["unrealized"] = sum(known) if known else None
        if known:
            trade["cost"] = abs(sum(held[c] for c in trade["conids"] if c in held))
    other = {}
    for row in parsed["executions"]:
        if row["asset"] not in ("STK", "OPT"):
            other[row["asset"]] = other.get(row["asset"], 0) + 1
    return {"closed": closed, "open": still_open, "quality": quality, "other_assets": other}
