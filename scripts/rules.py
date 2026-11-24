import re

RANK = {"green": 0, "yellow": 1, "red": 2}
ZH = {
    "green": "绿",
    "yellow": "黄",
    "red": "红",
    "undetermined": "无法判断",
    "high_vol": "高波账户",
    "low_vol": "低波账户",
    "positive": "正",
    "negative": "负",
    "unproven": "未证实",
    "insufficient": "样本不足",
}
CATEGORY_ZH = {"stock": "正股", "leveraged_etf": "杠杆 ETF", "option": "期权", "weekly_option": "周期权", "cash_like": "现金类 ETF"}
FIELDS = (
    ("account_type", "C1"),
    ("c2_statistical", "C2"),
    ("c3_damage", "C3"),
    ("c5_expectancy", "C5"),
    ("overall", "OVERALL"),
    ("main_cause", "C4"),
)
ENUMS = {
    "account_type": ("high_vol", "low_vol"),
    "c2_statistical": ("green", "yellow", "red", "undetermined"),
    "c3_damage": ("green", "yellow", "red"),
    "c5_expectancy": ("positive", "unproven", "negative", "insufficient"),
    "overall": ("green", "yellow", "red"),
}
CATEGORIES = ("DATA_ERROR", "RULE_NOT_APPLICABLE", "MODEL_ERROR", "UNRESOLVED")
C5_COLOR = {"positive": "green", "unproven": "yellow", "negative": "red"}
UNRELIABLE = {
    "data_quality.status": "PARTIAL",
    "data_quality.reconcile.ok": False,
    "account.sigma_source": "full_record",
    "lowvol.reference_source": "full_record",
    "lowvol.reference_sufficient": False,
    "lowvol.methods_disagree": True,
    "trade_drawdown.reference_source": "full_record",
    "trade_drawdown.methods_disagree": True,
}
RULE_INPUTS = {
    "C1": ("account.",),
    "C2": ("account.", "lowvol.", "trade_drawdown."),
    "C3": (),
    "C4": (),
    "C5": (),
    "OVERALL": ("account.", "lowvol.", "trade_drawdown."),
}


def pct(value):
    return "%.1f%%" % (value * 100)


def level_text(level):
    return "%g%%" % (level * 100)


def _volatility(facts, cfg, short=False):
    low = facts["lowvol"]
    ref = cfg["reference"]
    th = cfg["c2_lowvol"]
    if not low["reference_sufficient"]:
        return None
    reminders = []
    if low["reference_source"] == "full_record":
        reminders.append("回撤起点之前的参考窗口不足 %d 天，改用全程波动率，它包含回撤本身，会把回撤看轻" % ref["min_days"])
    if facts["period"]["nav_days"] < ref["min_nav_days"]:
        reminders.append("净值记录不足 %d 天" % ref["min_nav_days"])
    lead = "回撤 %s，是年化波动率 %s 的 %.2f 倍" % (
        pct(facts["drawdown"]["depth"]), pct(low["sigma_annual"]), low["multiple_of_annual_vol"])
    if cfg["lowvol_decision"] == "z":
        z = low["z"]
        value = "red" if z > th["z_red"] else "yellow" if z >= th["z_yellow"] else "green"
        return value, lead + "，相当于形成期内日波动率累计值的 %.2f 倍。" % z, reminders
    p0 = low["p_by_sharpe"]["0.0"]
    if p0 >= th["p_green"]:
        value, tail = "green", "在正常波动范围内"
    elif p0 >= th["p_red"]:
        value, tail = "yellow", "偏重"
    else:
        value, tail = "red", "波动率解释不了，属于事故"
    if short:
        body = lead + "，没有优势的账户出现这种回撤的概率是 %s（范围 %s 到 %s），%s。" % (
            pct(p0), pct(low["p0_ci"][0]), pct(low["p0_ci"][1]), tail)
        return value, body, reminders
    body = lead + "；没有优势的账户在同样长的记录里出现不小于这次回撤的概率是 %s，%s。参考波动率取自 %d 天，按它的 %s 置信区间，这个概率在 %s 到 %s 之间。" % (
        pct(p0), tail, low["reference_days"], level_text(cfg["simulation"]["ci_level"]), pct(low["p0_ci"][0]), pct(low["p0_ci"][1]))
    return value, body, reminders


def _remind(reminders):
    return "提醒：%s。" % "；".join(reminders) if reminders else ""


def _trades(facts, cfg):
    td = facts["trade_drawdown"]
    th = cfg["c2_highvol"]
    p0 = td["p0"]
    if p0 is None:
        return None
    reminders = []
    if td["reference_source"] == "full_record":
        basis = "以全部 %d 笔交易为参照" % td["reference_trades"]
        reminders.append("回撤起点之前的交易不足 %d 笔，改用全部交易作参照，它包含回撤本身，会把回撤看轻" % th["min_reference"])
    else:
        basis = "以回撤前 %d 笔交易为参照" % td["reference_trades"]
    if td["trades"] < th["n_thin"]:
        reminders.append("已平仓交易 %d 笔，不足 %d 笔，笔数偏少，结论不稳" % (td["trades"], th["n_thin"]))
    if td["methods_disagree"] and td["p0_block"] > td["p0_independent"]:
        reminders.append("盈亏在时间上扎堆，概率取自分块重抽样；假设各笔互相独立时是 %s" % pct(td["p0_independent"]))
    if p0 >= th["p_green"]:
        value, tail = "green", "在原来打法的正常范围内"
    elif p0 >= th["p_red"]:
        value, tail = "yellow", "偏重"
    else:
        value, tail = "red", "原来的打法解释不了"
    span = "（范围 %s 到 %s）" % (pct(td["p0_ci"][0]), pct(td["p0_ci"][1])) if td["p0_ci"] else ""
    body = "按逐笔平仓盈亏算回撤 %s，%s，没有优势的账户做同样多笔出现这种回撤的概率是 %s%s，%s。" % (
        pct(td["depth"]), basis, pct(p0), span, tail)
    return value, body, reminders


def _c2(facts, cfg):
    high = _is_high(facts, cfg)
    vol = _volatility(facts, cfg, high)
    trade = _trades(facts, cfg) if high else None
    days = cfg["reference"]["min_days"]
    lenient = "高波账户的波动率由自己的仓位造成，按波动率的结论偏宽松"
    if vol is None and trade is None:
        return {
            "value": "undetermined",
            "mode": "insufficient_history",
            "thin": True,
            "by_volatility": None,
            "by_trades": None,
            "sentence": "相对波动率：无法判断。净值记录不足 %d 天，算不出波动率。" % days,
        }
    if vol is None:
        value, body, reminders = trade
        return {
            "value": value,
            "mode": "highvol_trades",
            "thin": False,
            "by_volatility": None,
            "by_trades": value,
            "sentence": "相对波动率：%s。%s" % (ZH[value], body)
            + _remind(["净值记录不足 %d 天，算不出波动率，只按逐笔口径判断" % days] + reminders),
        }
    if trade is None:
        value, body, reminders = vol
        mode = "lowvol_z" if cfg["lowvol_decision"] == "z" else "lowvol_p0"
        if high:
            mode = "highvol_volatility"
            reminders = ["已平仓交易太少，逐笔口径算不了，只按波动率判断", lenient] + reminders
        return {
            "value": value,
            "mode": mode,
            "thin": False,
            "by_volatility": value,
            "by_trades": None,
            "sentence": "相对波动率：%s。%s" % (ZH[value], body) + _remind(reminders),
        }
    value = max(vol[0], trade[0], key=lambda color: RANK[color])
    return {
        "value": value,
        "mode": "highvol_both",
        "thin": False,
        "by_volatility": vol[0],
        "by_trades": trade[0],
        "sentence": "相对波动率：%s。按逐笔口径是%s：%s按波动率是%s：%s两条取较重的一条。" % (
            ZH[value], ZH[trade[0]], trade[1], ZH[vol[0]], vol[1])
        + _remind(trade[2] + [lenient] + vol[2]),
    }


def _c3(facts, cfg):
    dd = facts["drawdown"]
    cap = facts["capital"]
    th = cfg["c3"]
    g = dd["recovery_gain"]
    value = "red" if g is None or g >= th["g_red"] else "yellow" if g >= th["g_yellow"] else "green"
    ratio = cap["pnl_ratio"] or 0.0
    return {
        "value": value,
        "sentence": "实际伤害：%s。回撤 %s，回本需要上涨 %s；资金口径%s %s。回本时间参考值约 %d 个交易日（回撤形成时间的三倍，仅作参考）。"
        % (
            ZH[value],
            pct(dd["depth"]),
            pct(g) if g is not None else "无穷",
            "亏损" if ratio < 0 else "盈利",
            pct(abs(ratio)),
            3 * dd["formation_days"],
        ),
    }


def _c4(facts, cfg):
    att = facts["attribution"]
    th = cfg["c4"]
    if att["top1_share"] is None:
        return {"concentrated": False, "oversized_driven": False, "sentence": "伤从哪来：没有亏损的已平仓交易。"}
    concentrated = att["top3_share"] >= th["top3_concentrated"]
    oversized = att["oversized_share"] >= th["oversized_share"]
    sentence = "伤从哪来：亏损最大的 1 笔占总亏损 %s，前 3 笔占 %s；亏损最多的类别是%s。" % (
        pct(att["top1_share"]),
        pct(att["top3_share"]),
        CATEGORY_ZH.get(att["largest_loss_category"], att["largest_loss_category"]),
    )
    if concentrated:
        sentence += "属于集中型亏损。"
    if oversized:
        sentence += "伤主要来自超配单。"
    return {"concentrated": concentrated, "oversized_driven": oversized, "sentence": sentence}


def _c5(exp, cfg):
    n = exp["trades"]
    if exp["mean"] is None:
        return {"value": "insufficient", "thin": True, "sentence": "打法期望值：样本不足。可计交易只有 %d 笔，算不出区间。" % n}
    value = "positive" if exp["ci_low"] > 0 else "negative" if exp["ci_high"] < 0 else "unproven"
    thin = n < cfg["c5"]["n_min"]
    sentence = "打法期望值：%s。%d 笔可计交易，单笔期望 %s，%s 置信区间 %s 到 %s。" % (
        ZH[value], n, pct(exp["mean"]), level_text(cfg["simulation"]["ci_level"]), pct(exp["ci_low"]), pct(exp["ci_high"]))
    if thin:
        sentence += "提醒：可计交易不足 %d 笔，区间很宽，这一项仅供参考。" % cfg["c5"]["n_min"]
    return {"value": value, "thin": thin, "sentence": sentence}


def _overall(c2, c3, c5, thin=False):
    colors = [value for value in (c2, c3, C5_COLOR.get(c5)) if value in RANK]
    value = max(colors, key=lambda color: RANK[color]) if colors else "undetermined"
    insufficient = thin or c2 not in RANK or c3 not in RANK or c5 not in C5_COLOR
    return value, insufficient


def _is_high(facts, cfg):
    acct = facts["account"]
    cls = cfg["classification"]
    return acct["sigma_annual"] >= cls["sigma_annual_high"] or acct["option_share"] >= cls["option_share_high"]


def money(value):
    return "{:,.2f}".format(value)


def outlier_note(tested, cfg):
    rule = cfg["outliers"]
    if tested < rule["n_rough"]:
        return "提醒：已平仓交易只有 %d 笔，少于这个检验要求的 %d 笔，检出结果仅供参考，可以直接点名。" % (tested, rule["n_rough"])
    if tested < rule["n_accurate"]:
        return "提醒：已平仓交易 %d 笔，不足 %d 笔，检验的临界值是近似的。" % (tested, rule["n_accurate"])
    return ""


def decide_trimmed(facts, block, selection, cfg):
    count = len(block["trades"])
    if selection["by"] == "level":
        if not count:
            return {"sentence": "按 %s 置信水平没有检出异常交易，没有重算。" % level_text(selection["level"])}
        head = "按 %s 置信水平检出并去掉 %d 笔交易，盈亏合计 %s。" % (level_text(selection["level"]), count, money(block["removed_pnl"]))
    else:
        head = "按点名去掉 %d 笔交易，盈亏合计 %s。" % (count, money(block["removed_pnl"]))
    dd = facts["drawdown"]
    win = block["window"]
    span = "这次回撤（%s 至 %s）" % (dd["peak_date"], dd["trough_date"])
    if not win["closed_inside"]:
        window = "去掉的交易都不在%s期间平仓。" % span
    else:
        window = "%s的金额是 %s；去掉的交易里有 %d 笔在这期间平仓，盈亏合计 %s" % (
            span, money(dd["amount"]), win["closed_inside"], money(win["pnl"]))
        if win["opened_before_peak"]:
            window += "；其中 %d 笔开仓早于峰值日，亏损有一部分发生在回撤开始之前，这个合计不能直接和回撤金额相减。" % win["opened_before_peak"]
        elif win["pnl"] < 0 and -win["pnl"] >= dd["amount"]:
            window += "，超过回撤金额：去掉它们，账户在这期间合计没有亏。"
        elif win["pnl"] < 0 and dd["amount"] > 0:
            window += "，占回撤金额的 %s。" % pct(-win["pnl"] / dd["amount"])
        else:
            window += "。"
    return {
        "sentence": head,
        "window": window,
        "c4_source": _c4({"attribution": block["attribution"]}, cfg),
        "c5_expectancy": _c5(block["expectancy"], cfg),
    }


def decide(facts, cfg):
    acct = facts["account"]
    high = _is_high(facts, cfg)
    account_type = "high_vol" if high else "low_vol"
    c2 = _c2(facts, cfg)
    c3 = _c3(facts, cfg)
    c4 = _c4(facts, cfg)
    c4["second_step"] = c4["concentrated"]
    c4["second_step_note"] = outlier_note(facts["outliers"]["tested"], cfg)
    c5 = _c5(facts["expectancy"], cfg)
    overall, insufficient = _overall(c2["value"], c3["value"], c5["value"], c2.get("thin", False) or c5["thin"])
    att = facts["attribution"]
    accepted = []
    if att["top_losses"]:
        accepted.append(att["top_losses"][0]["id"])
    if att["largest_loss_category"]:
        accepted.append(att["largest_loss_category"])
    return {
        "schema": "account-health/verdict/1",
        "config_version": cfg["version"],
        "account_type": {
            "value": account_type,
            "sentence": "账户类型：%s（年化波动率 %s，期权占比 %s）。"
            % (ZH[account_type], pct(acct["sigma_annual"]), pct(acct["option_share"])),
        },
        "c2_statistical": c2,
        "c3_damage": c3,
        "c4_source": c4,
        "c5_expectancy": c5,
        "overall": {
            "value": overall,
            "evidence_insufficient": insufficient,
            "sentence": "总体健康度：%s%s。" % (ZH[overall], "（证据不足）" if insufficient else ""),
        },
        "main_cause": {"accepted": accepted},
    }


def validate_judgment(obj):
    errors = []
    if not isinstance(obj, dict):
        return ["model_judgment.json 必须是一个 JSON 对象"]
    for field, allowed in ENUMS.items():
        if obj.get(field) not in allowed:
            errors.append("%s 必须是 %s 之一" % (field, " | ".join(allowed)))
    if not isinstance(obj.get("main_cause"), str) or not obj.get("main_cause", "").strip():
        errors.append("main_cause 必须是交易编号或类别名（stock | leveraged_etf | option | weekly_option）")
    reasons = obj.get("reasons")
    if not isinstance(reasons, dict):
        errors.append("reasons 必须是对象")
    else:
        for field, _ in FIELDS:
            if not isinstance(reasons.get(field), str) or not reasons.get(field, "").strip():
                errors.append("reasons.%s 缺一句话理由" % field)
    return errors


def _cause_matches(model, accepted):
    text = model.strip().lower()
    names = {item.lower() for item in accepted}
    names |= {CATEGORY_ZH[item].lower() for item in accepted if item in CATEGORY_ZH}
    return text in names


def compare(verdict, judgment):
    deviations = []
    for field, rule in FIELDS:
        if field == "main_cause":
            accepted = verdict["main_cause"]["accepted"]
            if accepted and not _cause_matches(judgment["main_cause"], accepted):
                deviations.append({
                    "field": field,
                    "rule": rule,
                    "computed": " 或 ".join(accepted),
                    "model": judgment["main_cause"],
                })
            continue
        computed = verdict[field]["value"]
        if judgment[field] != computed:
            deviations.append({"field": field, "rule": rule, "computed": computed, "model": judgment[field]})
    return deviations


def lookup(obj, path):
    cur = obj
    parts = path.split(".")
    i = 0
    while i < len(parts):
        if isinstance(cur, dict):
            for j in range(len(parts), i, -1):
                key = ".".join(parts[i:j])
                if key in cur:
                    cur = cur[key]
                    i = j
                    break
            else:
                return None
        elif isinstance(cur, list) and parts[i].isdigit() and int(parts[i]) < len(cur):
            cur = cur[int(parts[i])]
            i += 1
        else:
            return None
    return cur


def _flag_on(facts, path):
    value = lookup(facts, path)
    expected = UNRELIABLE[path]
    if isinstance(expected, bool):
        return value is expected
    return value == expected


def _flag_paths(rule):
    return [path for path in UNRELIABLE if path.startswith("data_quality.") or path.startswith(RULE_INPUTS[rule])]


def validate_adjudication(adj, deviations, facts, trade_ids):
    errors = []
    items = adj.get("items") if isinstance(adj, dict) else None
    if not isinstance(items, list):
        return ["adjudication.json 必须是 {\"items\": [...]}"]
    by_field = {}
    for item in items:
        if isinstance(item, dict):
            by_field[item.get("field")] = item
    for dev in deviations:
        item = by_field.get(dev["field"])
        if item is None:
            errors.append("%s 有偏差但没有裁决" % dev["field"])
            continue
        category = item.get("category")
        if category not in CATEGORIES:
            errors.append("%s 的 category 必须是 %s 之一" % (dev["field"], " | ".join(CATEGORIES)))
            continue
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        if category == "DATA_ERROR":
            record = str(evidence.get("record", ""))
            if record not in trade_ids and not re.fullmatch(r"\d{8}", record):
                errors.append("%s：DATA_ERROR 的 evidence.record 必须是 trades.json 里的交易编号或 8 位日期" % dev["field"])
            if not evidence.get("field") or "value" not in evidence:
                errors.append("%s：DATA_ERROR 的 evidence 需要 field 和 value" % dev["field"])
        if category == "RULE_NOT_APPLICABLE":
            if evidence.get("rule") != dev["rule"]:
                errors.append("%s：RULE_NOT_APPLICABLE 的 evidence.rule 必须是 %s" % (dev["field"], dev["rule"]))
            path = evidence.get("facts_path")
            allowed = _flag_paths(dev["rule"])
            if path not in allowed or not _flag_on(facts, path):
                errors.append("%s：RULE_NOT_APPLICABLE 的 evidence.facts_path 必须是下面某个已经亮起的标志（当前都没亮就不能用这一类）：%s" % (
                    dev["field"], "、".join("%s=%s" % (p, lookup(facts, p)) for p in allowed)))
    return errors


def finalize(verdict, judgment, deviations, adj):
    items = {}
    if adj:
        items = {item.get("field"): item for item in adj.get("items", []) if isinstance(item, dict)}
    deviated = {dev["field"]: dev for dev in deviations}
    fields = {}
    for field, rule in FIELDS:
        if field == "main_cause":
            computed = " 或 ".join(verdict["main_cause"]["accepted"]) or "无"
        else:
            computed = verdict[field]["value"]
        row = {
            "rule": rule,
            "computed": computed,
            "model": judgment[field],
            "final": computed,
            "category": None,
            "mark": "一致",
        }
        if field in deviated:
            category = items[field]["category"]
            row["category"] = category
            if category == "RULE_NOT_APPLICABLE":
                row["final"] = "undetermined"
                row["mark"] = "规则不适用，两个结论并列"
            elif category == "MODEL_ERROR":
                row["mark"] = "以计算结论为准"
            elif category == "UNRESOLVED":
                row["mark"] = "存在偏差，以计算结论为准，两个结论并列"
            else:
                evidence = items[field]["evidence"]
                row["mark"] = "模型指出数据有误：%s 的 %s 应为 %s；以计算结论为准，待核实" % (
                    evidence["record"], evidence["field"], evidence["value"])
        fields[field] = row
    if fields["overall"]["category"] == "RULE_NOT_APPLICABLE":
        overall, insufficient = "undetermined", True
    else:
        overall, insufficient = _overall(
            fields["c2_statistical"]["final"], fields["c3_damage"]["final"], fields["c5_expectancy"]["final"],
            verdict["c2_statistical"].get("thin", False) or verdict["c5_expectancy"].get("thin", False),
        )
        fields["overall"]["final"] = overall
    return {
        "schema": "account-health/final/1",
        "fields": fields,
        "overall": overall,
        "evidence_insufficient": insufficient,
        "has_deviation": bool(deviations),
        "data_disputed": any(row["category"] == "DATA_ERROR" for row in fields.values()),
    }


def _numbers(obj, out):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.append(abs(float(obj)))
    elif isinstance(obj, str):
        for token in re.findall(r"\d+(?:\.\d+)?", obj):
            out.append(float(token))
    elif isinstance(obj, dict):
        for value in obj.values():
            _numbers(value, out)
    elif isinstance(obj, list):
        for value in obj:
            _numbers(value, out)


def lint(text, sources, final_overall, cfg):
    rules = cfg["lint"]
    errors = []
    sentences = [part for part in re.split(r"[。！？!?]|\.(?!\d)", text) if part.strip()]
    if not sentences:
        errors.append("分析文字是空的")
    if len(sentences) > rules["max_sentences"]:
        errors.append("分析有 %d 句，上限是 %d 句" % (len(sentences), rules["max_sentences"]))
    known = [float(value) for value in rules["allowed_numbers"]]
    for source in sources:
        _numbers(source, known)
    for token in re.findall(r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?(?![A-Za-z_\d])", text):
        digits = len(token.split(".")[1]) if "." in token else 0
        target = float(token)
        hit = any(
            abs(round(value, digits) - target) < 1e-9 or abs(round(value * 100, digits) - target) < 1e-9
            for value in known
        )
        if not hit:
            errors.append("数字 %s 在 facts.json 和 verdict.json 里找不到" % token)
    for phrase in rules["contradictions"].get(final_overall, []):
        if phrase in text:
            errors.append("措辞“%s”和最终结论（%s）矛盾" % (phrase, ZH[final_overall]))
    return errors
