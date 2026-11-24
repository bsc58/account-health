import bisect
import copy
import itertools
import math

import numpy as np

import dist
import simulate

YEAR = 252


def rnd(value, digits=4):
    if value is None:
        return None
    return round(float(value), digits) + 0.0


def _fx_pnl(parsed, dates, values, cfg):
    base = parsed["base_currency"]
    n = len(dates)
    moves = {}
    booked = {}
    rates = {}

    def post(currency, day, units, rate=None, recorded=0.0):
        i = bisect.bisect_left(dates, day)
        if i >= n:
            return
        moves.setdefault(currency, [0.0] * n)[i] += units
        booked.setdefault(currency, [0.0] * n)[i] += recorded
        if rate:
            rates.setdefault(currency, {})[i] = rate

    for tx in parsed["cash"]:
        if tx["currency"] not in ("", base):
            post(tx["currency"], tx["date"], tx["units"], tx["fx"], tx["amount"])
    for row in parsed["executions"]:
        if row["asset"] == "CASH":
            post(row["symbol"].split(".")[0], row["book_date"], row["quantity"], row["price"] * row["fx"])
            post(row["currency"], row["book_date"], row["proceeds"], row["fx"])
            post(row["commission_currency"], row["book_date"], row["commission"])
        elif row["currency"] not in ("", base):
            post(row["currency"], row["book_date"], row["units"], row["fx"], row["net"])
    out = np.zeros(n)
    borrowed = []
    floor = -cfg["reconcile"]["fx_borrow_share"] * max(values)
    for currency in sorted(moves):
        if currency == base:
            rate = np.ones(n)
        elif currency in rates:
            known = sorted(rates[currency].items())
            rate = np.interp(np.arange(n), [i for i, _ in known], [value for _, value in known])
        else:
            continue
        balance = np.cumsum(moves[currency])
        step = np.diff(balance) * rate[1:] - np.asarray(booked[currency])[1:]
        if currency == base or float((balance * rate).min()) >= floor:
            step = step + balance[:-1] * np.diff(rate)
        else:
            borrowed.append(currency)
        out[1:] += step
    return out.tolist(), borrowed


def _place_flows(parsed, dates, cash, fx, cfg):
    n = len(dates)
    flows = [0.0] * n
    records = []
    other = [0.0] * n
    other_cash = 0.0
    for tx in parsed["cash"]:
        i = bisect.bisect_left(dates, tx["date"])
        if i <= 0 or i >= n:
            continue
        if tx["flow"]:
            records.append((i, tx["amount"]))
        else:
            other[i] += tx["amount"]
            other_cash += tx["amount"]
    records.sort()
    if not records or any(value is None for value in cash):
        for i, amount in records:
            flows[i] += amount
        return flows, other_cash, 0, 0
    executed = [0.0] * n
    for row in parsed["executions"]:
        i = bisect.bisect_left(dates, row["book_date"])
        if 0 < i < n and row["asset"] != "CASH":
            executed[i] += row["net"]
    tolerance = cfg["reconcile"]["flow_match_tolerance"]
    window = cfg["reconcile"]["flow_match_days"]
    pending = []
    cursor = 0
    moved = 0
    unmatched = 0
    for t in range(1, n):
        while cursor < len(records) and records[cursor][0] <= t:
            pending.append(records[cursor])
            cursor += 1
        for item in [item for item in pending if t - item[0] > window]:
            flows[item[0]] += item[1]
            unmatched += 1
            pending.remove(item)
        if not pending:
            continue
        gap_today = cash[t] - cash[t - 1] - executed[t] - other[t] - fx[t]
        sizes = range(1, len(pending) + 1) if len(pending) <= 10 else (1, len(pending))
        best = None
        for size in sizes:
            for picks in itertools.combinations(range(len(pending)), size):
                total = sum(pending[k][1] for k in picks)
                gap = abs(gap_today - total)
                if gap <= tolerance * abs(total) and (best is None or (gap, -size) < best[0]):
                    best = ((gap, -size), picks)
        if best is None:
            continue
        for k in best[1]:
            flows[t] += pending[k][1]
            if pending[k][0] != t:
                moved += 1
        pending = [item for k, item in enumerate(pending) if k not in best[1]]
    for i, amount in pending:
        flows[i] += amount
        unmatched += 1
    return flows, other_cash, moved, unmatched


def account_series(parsed, cfg):
    rows = sorted(parsed["nav"].items())
    while rows and rows[0][1]["total"] <= 0:
        rows.pop(0)
    dates = [day for day, _ in rows]
    values = [row["total"] for _, row in rows]
    cash = [row["cash"] for _, row in rows]
    fx, fx_borrowed = _fx_pnl(parsed, dates, values, cfg) if dates else ([], [])
    flows, other_cash, moved, unmatched = _place_flows(parsed, dates, cash, fx, cfg)
    returns = [0.0] * len(dates)
    zero_base = 0
    for t in range(1, len(dates)):
        start = values[t - 1] + max(flows[t], 0.0)
        if start > 0:
            returns[t] = (values[t] - min(flows[t], 0.0) - fx[t]) / start - 1.0
        else:
            zero_base += 1
    index = np.cumprod(1.0 + np.asarray(returns)) if dates else np.asarray([])
    return {
        "dates": dates,
        "values": values,
        "cash": cash,
        "flows": flows,
        "fx": fx,
        "fx_borrowed": fx_borrowed,
        "returns": returns,
        "index": index,
        "other_cash": other_cash,
        "flows_moved": moved,
        "flows_unmatched": unmatched,
        "zero_base_days": zero_base,
    }


def _episode(s, peak, trough, end, recovered):
    index = s["index"]
    values = s["values"]
    flows = s["flows"]
    fx = s["fx"]
    depth = max(0.0, 1.0 - index[trough] / index[peak])
    amount = -sum(values[t] - values[t - 1] - flows[t] - fx[t] for t in range(peak + 1, trough + 1))
    deposits = sum(f for f in flows[peak + 1:end + 1] if f > 0)
    return {
        "peak": peak,
        "trough": trough,
        "end": end,
        "depth": depth,
        "amount": amount,
        "deposits": deposits,
        "recovered": recovered,
    }


def episodes(s):
    index = s["index"]
    last = len(index) - 1
    dd = 1.0 - index / np.maximum.accumulate(index)
    trough = int(np.argmax(dd))
    head = index[:trough + 1]
    peak = int(np.max(np.nonzero(head == head.max())[0]))
    later = np.nonzero(index[trough + 1:] >= index[peak])[0]
    recovered = len(later) > 0
    end = trough + 1 + int(later[0]) if recovered else last
    largest = _episode(s, peak, trough, end, recovered)
    peak_now = int(np.max(np.nonzero(index == index.max())[0]))
    current = _episode(s, peak_now, last, last, False)
    return largest, current, dd


def reference(s, peak, cfg):
    need = cfg["reference"]["min_days"]
    window = s["returns"][max(1, peak - cfg["reference"]["window_days"] + 1):peak + 1]
    source = "reference_window"
    if len(window) < need or float(np.std(window, ddof=1)) <= 0:
        window = s["returns"][1:]
        source = "full_record"
    sigma = float(np.std(window, ddof=1)) if len(window) >= 2 else 0.0
    return {
        "window": window,
        "days": len(window),
        "sigma": sigma,
        "source": source,
        "sufficient": len(window) >= need and sigma > 0,
    }


def lowvol(s, ep, ref, dd, cfg):
    sim = cfg["simulation"]
    steps = len(s["dates"]) - 1
    levels = [str(level) for level in sim["sharpe_levels"]]
    out = {
        "reference_days": ref["days"],
        "reference_sufficient": ref["sufficient"],
        "reference_source": ref["source"],
        "sigma_daily": None,
        "sigma_annual": None,
        "sigma_annual_ci": None,
        "multiple_of_annual_vol": None,
        "z": None,
        "p_by_sharpe": {level: None for level in levels},
        "p0_ci": None,
        "max_compatible_sharpe": None,
        "p0_bootstrap": None,
        "methods_disagree": None,
        "expected_mdd_zero_drift": None,
        "ulcer_index": rnd(math.sqrt(float(np.mean(dd ** 2)))),
        "underwater_days": ep["end"] - ep["peak"],
    }
    if not ref["sufficient"] or steps < 1:
        return out
    sd = ref["sigma"]
    annual = sd * math.sqrt(YEAR)
    depth = ep["depth"]
    cache = {}

    def prob(sharpe, scale=1.0):
        key = (sharpe, scale)
        if key not in cache:
            mdds = simulate.normal_mdd(
                sharpe * sd * scale / math.sqrt(YEAR), sd * scale, steps, sim["paths"], sim["chunk"], sim["seed"])
            cache[key] = simulate.exceed(mdds, depth)
        return cache[key]

    free = ref["days"] - 1
    tail = (1.0 - sim["ci_level"]) / 2.0
    narrow = math.sqrt(free / dist.chi2_quantile(1.0 - tail, free))
    wide = math.sqrt(free / dist.chi2_quantile(tail, free))

    count = int(round(sim["sharpe_grid_max"] / sim["sharpe_grid_step"]))
    grid = [round(i * sim["sharpe_grid_step"], 6) for i in range(count + 1)]
    boot = simulate.exceed(
        simulate.bootstrap_mdd(ref["window"], steps, sim["bootstrap_block"], sim["paths"], sim["chunk"], sim["seed"] + 1),
        depth,
    )
    p0 = prob(0.0)
    out.update({
        "sigma_daily": rnd(sd, 6),
        "sigma_annual": rnd(annual),
        "sigma_annual_ci": [rnd(annual * narrow), rnd(annual * wide)],
        "multiple_of_annual_vol": rnd(depth / annual),
        "z": rnd(depth / (sd * math.sqrt(max(1, ep["trough"] - ep["peak"])))),
        "p_by_sharpe": {str(level): rnd(prob(float(level))) for level in sim["sharpe_levels"]},
        "p0_ci": [rnd(prob(0.0, narrow)), rnd(prob(0.0, wide))],
        "max_compatible_sharpe": rnd(simulate.max_compatible(prob, grid, sim["compatible_p"]), 2),
        "p0_bootstrap": rnd(boot),
        "methods_disagree": abs(boot - p0) > sim["method_gap"],
        "expected_mdd_zero_drift": rnd(1.0 - math.exp(-math.sqrt(math.pi / 2.0) * sd * math.sqrt(steps))),
    })
    return out


def attach_nav(trades, s):
    dates = s["dates"]
    values = s["values"]
    for t in trades:
        nav = values[min(bisect.bisect_left(dates, t["open_date"]), len(dates) - 1)]
        t["nav_open"] = nav
        t["size"] = t["cost"] / nav if nav > 0 else None
        t["impact"] = t["pnl"] / nav if nav > 0 and t["pnl"] is not None else None


def annotate(closed, cfg):
    eligible = [t for t in closed if t["eligible"] and t["cost"] > 0 and t["size"]]
    keep = {id(t) for t in eligible}
    median_cost = float(np.median([t["cost"] for t in eligible])) if eligible else None
    median_size = float(np.median([t["size"] for t in eligible])) if eligible else None
    for t in closed:
        usable = id(t) in keep
        t["rho"] = t["pnl"] / t["cost"] if usable else None
        t["loss_ratio"] = max(0.0, -t["pnl"]) / t["cost"] if usable else None
        t["k"] = t["size"] / median_size if usable else None
        t["oversized"] = bool(t["k"] is not None and t["k"] > cfg["c4"]["k_max"])
    return eligible, median_cost, median_size


def gesd_bound(size, alpha):
    t = dist.t_upper_quantile(alpha / (2.0 * size), size - 2)
    return (size - 1) * t / math.sqrt((size - 2 + t * t) * size)


def gesd(values, alpha, limit):
    data = np.asarray(values, dtype=float)
    left = list(range(len(data)))
    steps = []
    for _ in range(limit):
        cur = data[left]
        spread = float(cur.std(ddof=1))
        if spread <= 0:
            break
        gaps = np.abs(cur - cur.mean())
        pick = int(np.argmax(gaps))
        bound = gesd_bound(len(left), alpha)
        steps.append((left.pop(pick), float(gaps[pick]) / spread, bound))
    count = max((i + 1 for i, (_, stat, bound) in enumerate(steps) if stat > bound), default=0)
    return [index for index, _, _ in steps[:count]]


def outliers(rows, level, cfg):
    rated = [t for t in rows if t["impact"] is not None]
    rule = cfg["outliers"]
    limit = min(len(rated) - 2, max(rule["min_candidates"], math.ceil(rule["max_share"] * len(rated))))
    if limit < 1:
        return []
    return [rated[i] for i in gesd([t["impact"] for t in rated], 1.0 - level, limit)]


def outlier_scan(closed, cfg):
    level = cfg["outliers"]["default_level"]
    flagged = outliers(closed, level, cfg)
    return {
        "level": level,
        "tested": sum(1 for t in closed if t["impact"] is not None),
        "trades": [
            {"id": t["id"], "symbol": t["symbol"], "pnl": rnd(t["pnl"], 2), "impact": rnd(t["impact"], 6)}
            for t in flagged
        ],
        "pnl": rnd(sum(rnd(t["pnl"], 2) for t in flagged), 2),
    }


def trimmed(rows, flagged, drawdown, cfg):
    gone = {t["id"] for t in flagged}
    inside = [t for t in flagged if drawdown["peak_date"] < t["close_date"] <= drawdown["trough_date"]]
    out = {
        "trades": [_brief(t) for t in flagged],
        "removed_pnl": rnd(sum(t["pnl"] for t in flagged), 2),
        "window": {
            "closed_inside": len(inside),
            "pnl": rnd(sum(t["pnl"] for t in inside), 2),
            "opened_before_peak": sum(1 for t in inside if t["open_date"] <= drawdown["peak_date"]),
        },
        "highvol": None,
        "attribution": None,
        "expectancy": None,
    }
    if not flagged:
        return out
    kept = [copy.deepcopy(t) for t in rows if t["id"] not in gone]
    eligible, median_cost, median_size = annotate(kept, cfg)
    out["highvol"] = highvol(kept, eligible, median_cost, median_size, drawdown["depth"], cfg)
    out["attribution"] = attribution(kept)
    out["expectancy"] = expectancy(eligible, cfg)
    return out


def _longest_run(flags):
    best = 0
    cur = 0
    for flag in flags:
        cur = cur + 1 if flag else 0
        best = max(best, cur)
    return best


def highvol(closed, eligible, median_cost, median_size, depth, cfg):
    sim = cfg["simulation"]
    out = {
        "closed_trades": len(closed),
        "eligible_trades": len(eligible),
        "median_cost": rnd(median_cost, 2),
        "median_size": rnd(median_size),
        "drawdown_in_standard_positions": None,
        "mean_loss_ratio": None,
        "oversized_trades": sum(1 for t in closed if t["oversized"]),
        "win_rate": None,
        "avg_win": None,
        "avg_loss": None,
        "longest_losing_streak": None,
        "streak_sim_median": None,
        "streak_sim_p95": None,
        "reshuffle_actual_mdd": None,
        "reshuffle_quantile": None,
        "reshuffle_median_mdd": None,
        "reshuffle_p95_mdd": None,
    }
    if eligible:
        rho = np.asarray([t["rho"] for t in eligible])
        wins = rho > 0
        win_rate = float(np.mean(wins))
        streaks = simulate.loss_streaks(win_rate, len(eligible), sim["streak_paths"], sim["seed"] + 2)
        out.update({
            "drawdown_in_standard_positions": rnd(depth / median_size, 2),
            "mean_loss_ratio": rnd(np.mean([t["loss_ratio"] for t in eligible])),
            "win_rate": rnd(win_rate),
            "avg_win": rnd(rho[wins].mean()) if wins.any() else 0.0,
            "avg_loss": rnd(-rho[~wins].mean()) if (~wins).any() else 0.0,
            "longest_losing_streak": _longest_run([not w for w in wins]),
            "streak_sim_median": rnd(np.median(streaks), 1),
            "streak_sim_p95": rnd(np.percentile(streaks, 95), 1),
        })
    impacts = [t["impact"] for t in closed if t["impact"] is not None]
    if len(impacts) >= 2:
        actual = float(simulate.money_mdd(np.asarray(impacts)))
        sims = simulate.reshuffle_mdd(impacts, sim["permutations"], sim["chunk"], sim["seed"] + 3)
        ties = np.isclose(sims, actual, rtol=1e-9, atol=1e-9)
        out.update({
            "reshuffle_actual_mdd": rnd(actual),
            "reshuffle_quantile": rnd(float(np.mean((sims < actual) & ~ties)) + 0.5 * float(np.mean(ties))),
            "reshuffle_median_mdd": rnd(np.median(sims)),
            "reshuffle_p95_mdd": rnd(np.percentile(sims, 95)),
        })
    return out


def trade_drawdown(closed, cfg):
    rule = cfg["c2_highvol"]
    sim = cfg["simulation"]
    rows = [t for t in closed if t["impact"] is not None]
    out = {
        "trades": len(rows),
        "depth": None,
        "peak_date": None,
        "trough_date": None,
        "reference_trades": None,
        "reference_source": None,
        "impact_sd": None,
        "impact_sd_ci": None,
        "p0": None,
        "p0_ci": None,
        "p0_independent": None,
        "p0_block": None,
        "methods_disagree": None,
    }
    if len(rows) < 2:
        return out
    impacts = np.asarray([t["impact"] for t in rows], dtype=float)
    logp = np.cumsum(np.log1p(np.maximum(impacts, -0.999999)))
    gap = logp - np.maximum(np.maximum.accumulate(logp), 0.0)
    trough = int(np.argmin(gap))
    depth = 1.0 - math.exp(float(gap[trough]))
    head = np.concatenate([[0.0], logp[:trough + 1]])
    before = int(np.max(np.nonzero(head == head.max())[0]))
    ref = impacts[:before]
    source = "before_peak"
    if len(ref) < rule["min_reference"]:
        ref = impacts
        source = "full_record"
    sd = float(np.std(ref, ddof=1))
    out.update({
        "depth": rnd(depth),
        "peak_date": rows[before - 1]["close_date"] if before else None,
        "trough_date": rows[trough]["close_date"],
        "reference_trades": len(ref),
        "reference_source": source,
        "impact_sd": rnd(sd, 6),
    })
    if sd <= 0:
        return out

    def prob(scale, block, seed):
        mdds = simulate.bootstrap_mdd(ref * scale, len(impacts), block, sim["paths"], sim["chunk"], seed)
        return simulate.exceed(mdds, depth)

    alone = prob(1.0, 1, sim["seed"] + 5)
    blocked = prob(1.0, rule["block"], sim["seed"] + 6)
    block, seed = (rule["block"], sim["seed"] + 6) if blocked > alone else (1, sim["seed"] + 5)
    out.update({
        "p0": rnd(max(alone, blocked)),
        "p0_independent": rnd(alone),
        "p0_block": rnd(blocked),
        "methods_disagree": abs(blocked - alone) > sim["method_gap"],
    })
    if len(ref) >= 5:
        low, high = dist.sd_interval(ref, sim["ci_level"])
        out.update({
            "impact_sd_ci": [rnd(low, 6), rnd(high, 6)],
            "p0_ci": [rnd(prob(low / sd, block, seed)), rnd(prob(high / sd, block, seed))],
        })
    return out


def _brief(t):
    return {
        "id": t["id"],
        "symbol": t["symbol"],
        "kind": t["kind"],
        "category": t["category"],
        "open_date": t["open_date"],
        "close_date": t["close_date"],
        "method": t["method"],
        "cost": rnd(t["cost"], 2),
        "pnl": rnd(t["pnl"], 2),
        "loss_ratio": rnd(t["loss_ratio"]),
        "size": rnd(t["size"], 6),
        "impact": rnd(t["impact"], 6),
        "k": rnd(t["k"], 2),
    }


def attribution(closed):
    losers = sorted((t for t in closed if t["pnl"] < 0), key=lambda t: (t["pnl"], t["id"]))
    total = -sum(t["pnl"] for t in losers)
    out = {
        "total_loss": rnd(total, 2),
        "losing_trades": len(losers),
        "top1_share": None,
        "top3_share": None,
        "by_category": {},
        "by_method": {},
        "largest_loss_category": None,
        "oversized_share": None,
        "top_losses": [_brief(t) for t in losers[:5]],
    }
    if total <= 0:
        return out
    by_category = {}
    by_method = {}
    for t in losers:
        by_category[t["category"]] = by_category.get(t["category"], 0.0) - t["pnl"]
        by_method[t["method"]] = by_method.get(t["method"], 0.0) - t["pnl"]
    out.update({
        "top1_share": rnd(-losers[0]["pnl"] / total),
        "top3_share": rnd(-sum(t["pnl"] for t in losers[:3]) / total),
        "by_category": {key: rnd(by_category[key] / total) for key in sorted(by_category)},
        "by_method": {key: rnd(by_method[key] / total) for key in sorted(by_method)},
        "largest_loss_category": sorted(by_category, key=lambda key: (-by_category[key], key))[0],
        "oversized_share": rnd(-sum(t["pnl"] for t in losers if t["oversized"]) / total),
    })
    return out


def expectancy(eligible, cfg):
    sim = cfg["simulation"]
    out = {"trades": len(eligible), "mean": None, "ci_low": None, "ci_high": None, "ci_method": None, "sqn": None}
    n = len(eligible)
    if n < 2:
        return out
    rho = np.asarray([t["rho"] for t in eligible])
    spread = float(np.std(rho, ddof=1))
    if n >= cfg["c5"]["n_min"]:
        method = "bootstrap_t"
        low, high = simulate.mean_ci(rho, sim["ci_resamples"], sim["ci_level"], 1000, sim["seed"] + 4)
    else:
        method = "student_t"
        half = dist.t_upper_quantile((1.0 - sim["ci_level"]) / 2.0, n - 1) * spread / math.sqrt(n)
        low, high = float(rho.mean()) - half, float(rho.mean()) + half
    out.update({
        "mean": rnd(rho.mean()),
        "ci_low": rnd(low),
        "ci_high": rnd(high),
        "ci_method": method,
        "sqn": rnd(math.sqrt(n) * rho.mean() / spread, 2) if spread > 0 else None,
    })
    return out


def reconcile(parsed, s, cfg):
    dates = s["dates"]
    values = s["values"]
    executed = sum(
        row["net"] for row in parsed["executions"]
        if dates[0] < row["book_date"] <= dates[-1] and row["asset"] != "CASH")
    explained = sum(s["flows"]) + s["other_cash"] + executed + sum(s["fx"])
    if s["cash"][0] is not None and s["cash"][-1] is not None:
        basis = "cash"
        residual = s["cash"][-1] - s["cash"][0] - explained
    else:
        basis = "nav"
        held = sum(pos["value"] for pos in parsed["open_positions"])
        residual = values[-1] - values[0] - explained - held
    relative = abs(residual) / max(abs(values[0]), abs(values[-1]), 1.0)
    return {
        "basis": basis,
        "residual": rnd(residual, 2),
        "relative": rnd(relative),
        "ok": relative <= cfg["reconcile"]["tolerance"],
    }


def compute_facts(parsed, book, cfg):
    s = account_series(parsed, cfg)
    if len(s["dates"]) < 2:
        raise ValueError("每日净值记录不足两天，无法计算。请确认 Flex Query 勾选了每日净值。")
    largest, current, dd = episodes(s)
    ep = current if cfg["drawdown_focus"] == "current" else largest
    ref = reference(s, ep["peak"], cfg)
    closed = book["closed"]
    attach_nav(closed, s)
    eligible, median_cost, median_size = annotate(closed, cfg)
    dates = s["dates"]
    values = s["values"]
    full_sigma = float(np.std(s["returns"][1:], ddof=1)) * math.sqrt(YEAR) if len(dates) > 2 else 0.0
    gross = sum(abs(t["pnl"]) for t in closed)
    option_gross = sum(abs(t["pnl"]) for t in closed if t["category"] in ("option", "weekly_option"))
    capital_in = values[0] + sum(s["flows"])
    fx_pnl = sum(s["fx"])
    pnl = values[-1] - capital_in - fx_pnl
    rec = reconcile(parsed, s, cfg)
    quality = book["quality"]
    ineligible = len(closed) - len(eligible)

    notes = []
    partial = False
    if not rec["ok"]:
        partial = True
        notes.append("对账不平：差额 %.2f，占净值 %.2f%%。" % (rec["residual"], rec["relative"] * 100))
    if s["flows_unmatched"]:
        partial = True
        notes.append("有 %d 笔出入金在现金余额里找不到对应变动，按记录日期计入。" % s["flows_unmatched"])
    if s["flows_moved"]:
        notes.append("有 %d 笔出入金的到账日和记录日不同，按现金余额实际变动的那天计入。" % s["flows_moved"])
    if parsed["unconverted_cash"]:
        partial = True
        notes.append("有 %d 笔外币现金记录找不到汇率，按原币金额计入。" % parsed["unconverted_cash"])
    if quality["vanished"]:
        partial = True
        notes.append("有 %d 个持仓没有平仓记录、期末持仓里也没有（可能是换代码或公司行动），未计入交易统计：%s。" % (
            len(quality["vanished"]), "、".join(quality["vanished"])))
    if quality["orphan_closes"]:
        partial = True
        notes.append("有 %d 笔平仓找不到开仓记录（导出起点之前已持仓，或换过代码），未计入交易统计。" % quality["orphan_closes"])
    if quality["inferred_expiries"]:
        partial = True
        notes.append("有 %d 个期权过了到期日却没有平仓或到期记录，按到期归零处理。" % quality["inferred_expiries"])
    if parsed["transfers"]:
        partial = True
        notes.append("文件里有 %d 条仓位转移记录，未计入交易统计。" % parsed["transfers"])
    if parsed["corporate_actions"]:
        partial = True
        notes.append("文件里有 %d 条公司行动记录，未计入交易统计。" % parsed["corporate_actions"])
    if s["zero_base_days"]:
        partial = True
        notes.append("有 %d 天的前一日净值加当日入金不大于零，当日收益记为 0。" % s["zero_base_days"])
    base = parsed["base_currency"]
    conversions = book["other_assets"].get("CASH", 0)
    if conversions or fx_pnl:
        notes.append("换汇成交 %d 笔，不算交易；换汇成本和外币现金的汇率盈亏合计 %.2f，不计入收益和盈亏。" % (conversions, fx_pnl))
    if s["fx_borrowed"]:
        notes.append("%s 的现金余额推算出负数（导出起点之前已有这个币种的现金，或借了这个币种），它的汇率盈亏没有剔除。" % "、".join(s["fx_borrowed"]))
    priced = sorted({row["currency"] for row in parsed["executions"]
                     if row["asset"] in ("STK", "OPT") and row["currency"] not in ("", base)})
    if priced:
        notes.append("有以 %s 计价的持仓，持仓市值里的汇率变动没有剔除。" % "、".join(priced))
    others = {key: count for key, count in book["other_assets"].items() if key != "CASH"}
    if others:
        listing = "、".join("%s %d 笔" % (key, others[key]) for key in sorted(others))
        notes.append("其他资产只计入净值，不做逐笔统计：" + listing + "。")
    if quality["cash_like_trades"]:
        notes.append("现金类 ETF（%s）的 %d 笔买卖不计入交易统计，盈亏合计 %.2f。" % (
            "、".join(quality["cash_like_symbols"]), quality["cash_like_trades"], quality["cash_like_pnl"]))
    if ineligible:
        notes.append("有 %d 笔卖出期权或贷方价差只计入金额归因，不计入比率类指标。" % ineligible)
    if any(t["kind"] in ("stock", "leveraged_etf") for t in eligible):
        notes.append("正股和杠杆 ETF 以开仓成本作分母，仓位不等于最大亏损。")

    def block(e):
        return {
            "depth": rnd(e["depth"]),
            "peak_date": dates[e["peak"]],
            "trough_date": dates[e["trough"]],
            "formation_days": e["trough"] - e["peak"],
            "underwater_days": e["end"] - e["peak"],
            "recovered": e["recovered"],
            "amount": rnd(e["amount"], 2),
            "recovery_gain": rnd(e["depth"] / (1.0 - e["depth"])) if e["depth"] < 1 else None,
            "deposits_during": rnd(e["deposits"], 2),
        }

    return {
        "schema": "account-health/facts/1",
        "config_version": cfg["version"],
        "base_currency": parsed["base_currency"],
        "period": {
            "from": dates[0],
            "to": dates[-1],
            "nav_days": len(dates),
            "return_days": len(dates) - 1,
        },
        "data_quality": {
            "status": "PARTIAL" if partial else "OK",
            "notes": notes,
            "reconcile": rec,
        },
        "account": {
            "sigma_annual": rnd(ref["sigma"] * math.sqrt(YEAR) if ref["sufficient"] else full_sigma),
            "sigma_source": ref["source"],
            "sigma_annual_full_record": rnd(full_sigma),
            "option_share": rnd(option_gross / gross) if gross > 0 else 0.0,
        },
        "capital": {
            "start_value": rnd(values[0], 2),
            "end_value": rnd(values[-1], 2),
            "net_deposits_after_start": rnd(sum(s["flows"]), 2),
            "capital_in": rnd(capital_in, 2),
            "fx_pnl": rnd(fx_pnl, 2),
            "pnl": rnd(pnl, 2),
            "pnl_ratio": rnd(pnl / capital_in) if capital_in > 0 else None,
            "gain_to_recover_capital": rnd(capital_in / values[-1] - 1.0) if 0 < values[-1] < capital_in else 0.0,
            "twr_total": rnd(float(s["index"][-1]) - 1.0),
        },
        "drawdown": dict(block(ep), focus=cfg["drawdown_focus"]),
        "drawdown_max": block(largest),
        "drawdown_current": block(current),
        "lowvol": lowvol(s, ep, ref, dd, cfg),
        "highvol": highvol(closed, eligible, median_cost, median_size, ep["depth"], cfg),
        "trade_drawdown": trade_drawdown(closed, cfg),
        "attribution": attribution(closed),
        "expectancy": expectancy(eligible, cfg),
        "outliers": outlier_scan(closed, cfg),
        "open_positions": [
            {
                "id": t["id"],
                "symbol": t["symbol"],
                "kind": t["kind"],
                "open_date": t["open_date"],
                "cost": rnd(t["cost"], 2),
                "unrealized": rnd(t["unrealized"], 2),
            }
            for t in book["open"]
        ],
    }


def trade_rows(book):
    rows = []
    for t in book["closed"]:
        row = _brief(t)
        row.update({
            "direction": t["direction"],
            "eligible": t["eligible"],
            "rho": rnd(t["rho"]),
            "oversized": t["oversized"],
            "dte_at_open": t["dte_at_open"],
            "adds": t["adds"],
            "inferred_expiry": t["inferred_expiry"],
        })
        rows.append(row)
    return rows
