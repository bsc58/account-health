import argparse
import hashlib
import json
import math
import os
import platform
import sys

import numpy as np

import flex_parse
import metrics
import rules
import simulate
import trades

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(os.path.dirname(HERE), "config", "thresholds.json")
STALE = ("model_judgment.json", "verdict.json", "diff.json", "adjudication.json", "analysis.md", "final.json", "report.md", "trimmed.json")
METHOD_ZH = {"sold": "卖出", "expired": "到期归零", "assigned": "被指派", "exercised": "行权"}
STATUS_ZH = {"OK": "数据完整", "PARTIAL": "数据有缺口（见文末）"}
LIMITS = (
    "重抽样只能重组已经发生的交易，造不出样本里没出现过的亏损，不能预测更坏的情况。",
    "波动率是账户自己的行为造成的。高波账户里用它归一化会替亏损开脱，所以高波账户另按逐笔口径判断，两条取较重的一条。",
    "逐笔口径以回撤前的交易作参照，只回答这次回撤有没有超出账户原来的打法；原来的打法本身是否过于激进，看实际伤害和期望值。",
    "去掉异常交易是对照，不是修正。被去掉的交易是真实发生的盈亏，正式结论以全部交易为准。",
    "模型判断的独立性只做到流程级：脚本强制先写判断、后出结论，但无法保证模型事先没看过规则和阈值。",
    "阈值是暂定值，都在 config/thresholds.json。",
    "这是复盘工具，不构成投资建议。",
)
FIELD_ZH = {
    "account_type": "账户类型",
    "c2_statistical": "C2 相对波动率",
    "c3_damage": "C3 实际伤害",
    "c5_expectancy": "C5 期望值",
    "overall": "总体健康度",
    "main_cause": "主要伤源",
}
FACT_ROWS = (
    ("区间与数据", None, None),
    ("period.from", "起始日", "s"),
    ("period.to", "结束日", "s"),
    ("period.nav_days", "净值天数", "n"),
    ("data_quality.status", "数据质量", "s"),
    ("data_quality.reconcile.relative", "对账差额占净值", "p"),
    ("账户", None, None),
    ("account.sigma_annual", "年化波动率", "p"),
    ("account.sigma_source", "波动率取自", "s"),
    ("account.option_share", "期权占已平仓盈亏绝对值的比例", "p"),
    ("资金口径", None, None),
    ("capital.start_value", "期初净值", "m"),
    ("capital.net_deposits_after_start", "期间净入金", "m"),
    ("capital.capital_in", "累计投入", "m"),
    ("capital.end_value", "期末净值", "m"),
    ("capital.fx_pnl", "汇率盈亏和换汇成本（不计入收益和盈亏）", "m"),
    ("capital.pnl", "绝对盈亏", "m"),
    ("capital.pnl_ratio", "绝对盈亏占累计投入", "p"),
    ("capital.gain_to_recover_capital", "回到累计投入需上涨", "p"),
    ("capital.twr_total", "时间加权总收益", "p"),
    ("回撤", None, None),
    ("drawdown.focus", "判定用的回撤", "s"),
    ("drawdown.depth", "回撤深度", "p"),
    ("drawdown.peak_date", "峰值日", "s"),
    ("drawdown.trough_date", "谷底日", "s"),
    ("drawdown.formation_days", "形成天数", "n"),
    ("drawdown.underwater_days", "水下天数", "n"),
    ("drawdown.recovered", "是否已收复", "s"),
    ("drawdown.amount", "回撤金额", "m"),
    ("drawdown.recovery_gain", "回本所需涨幅", "p"),
    ("drawdown.deposits_during", "回撤期间入金", "m"),
    ("drawdown_max.depth", "最大回撤", "p"),
    ("drawdown_current.depth", "当前回撤", "p"),
    ("低波指标", None, None),
    ("lowvol.reference_days", "参考窗口天数", "n"),
    ("lowvol.sigma_daily", "参考日波动率", "x"),
    ("lowvol.sigma_annual", "参考年化波动率", "p"),
    ("lowvol.sigma_annual_ci.0", "参考年化波动率置信区间下限", "p"),
    ("lowvol.sigma_annual_ci.1", "参考年化波动率置信区间上限", "p"),
    ("lowvol.multiple_of_annual_vol", "回撤是年化波动率的几倍 M", "x"),
    ("lowvol.z", "Z", "x"),
    ("lowvol.p_by_sharpe.0.0", "发生概率（夏普 0）", "p"),
    ("lowvol.p0_ci.0", "发生概率（夏普 0）按波动率区间的下限", "p"),
    ("lowvol.p0_ci.1", "发生概率（夏普 0）按波动率区间的上限", "p"),
    ("lowvol.p_by_sharpe.0.5", "发生概率（夏普 0.5）", "p"),
    ("lowvol.p_by_sharpe.1.0", "发生概率（夏普 1）", "p"),
    ("lowvol.max_compatible_sharpe", "与本次回撤相容的最高夏普", "x"),
    ("lowvol.p0_bootstrap", "发生概率（分块重抽样）", "p"),
    ("lowvol.methods_disagree", "两种算法相差过大", "s"),
    ("lowvol.expected_mdd_zero_drift", "零漂移最大回撤期望（解析）", "p"),
    ("lowvol.ulcer_index", "Ulcer Index", "p"),
    ("高波指标", None, None),
    ("highvol.closed_trades", "已平仓交易笔数", "n"),
    ("highvol.eligible_trades", "可计入比率的笔数", "n"),
    ("highvol.median_size", "标准仓位（开仓成本占当时净值的中位数）", "p"),
    ("highvol.median_cost", "开仓成本中位数（金额）", "m"),
    ("highvol.drawdown_in_standard_positions", "回撤是几个标准仓位", "x"),
    ("highvol.mean_loss_ratio", "单笔亏损与仓位之比的均值", "p"),
    ("highvol.oversized_trades", "超配单笔数", "n"),
    ("highvol.win_rate", "胜率", "p"),
    ("highvol.avg_win", "平均盈利", "p"),
    ("highvol.avg_loss", "平均亏损", "p"),
    ("highvol.longest_losing_streak", "最长连亏", "n"),
    ("highvol.streak_sim_median", "同胜率模拟连亏中位数", "n"),
    ("highvol.streak_sim_p95", "同胜率模拟连亏 95% 分位", "n"),
    ("highvol.reshuffle_actual_mdd", "逐笔盈亏占净值累加后的最大回撤", "p"),
    ("highvol.reshuffle_quantile", "顺序重排分位", "p"),
    ("逐笔回撤", None, None),
    ("trade_drawdown.trades", "计入的已平仓交易笔数", "n"),
    ("trade_drawdown.depth", "按逐笔平仓盈亏算的回撤", "p"),
    ("trade_drawdown.peak_date", "回撤起点（平仓日）", "s"),
    ("trade_drawdown.trough_date", "回撤谷底（平仓日）", "s"),
    ("trade_drawdown.reference_trades", "参照交易笔数", "n"),
    ("trade_drawdown.reference_source", "参照取自", "s"),
    ("trade_drawdown.impact_sd", "参照交易单笔盈亏占净值的标准差", "p"),
    ("trade_drawdown.impact_sd_ci.0", "标准差置信区间下限", "p"),
    ("trade_drawdown.impact_sd_ci.1", "标准差置信区间上限", "p"),
    ("trade_drawdown.p0", "发生概率（无优势，两种重抽样里较大的）", "p"),
    ("trade_drawdown.p0_ci.0", "发生概率按标准差区间的下限", "p"),
    ("trade_drawdown.p0_ci.1", "发生概率按标准差区间的上限", "p"),
    ("trade_drawdown.p0_independent", "发生概率（独立重抽样）", "p"),
    ("trade_drawdown.p0_block", "发生概率（分块重抽样）", "p"),
    ("trade_drawdown.methods_disagree", "两种重抽样相差过大", "s"),
    ("亏损归因", None, None),
    ("attribution.total_loss", "总亏损", "m"),
    ("attribution.top1_share", "最大 1 笔占比", "p"),
    ("attribution.top3_share", "前 3 笔占比", "p"),
    ("attribution.largest_loss_category", "亏损最多的类别", "s"),
    ("attribution.oversized_share", "超配单占比", "p"),
    ("期望值", None, None),
    ("expectancy.trades", "可计交易笔数", "n"),
    ("expectancy.mean", "单笔期望", "p"),
    ("expectancy.ci_low", "置信区间下限", "p"),
    ("expectancy.ci_high", "置信区间上限", "p"),
    ("expectancy.ci_method", "置信区间算法", "s"),
    ("expectancy.sqn", "SQN", "x"),
)


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump(path, obj):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def fail(message, code=2):
    print(message, file=sys.stderr)
    sys.exit(code)


EX_ROWS = (
    ("highvol.closed_trades", "已平仓交易笔数", "n"),
    ("highvol.median_size", "标准仓位（占净值）", "p"),
    ("highvol.oversized_trades", "超配单笔数", "n"),
    ("highvol.win_rate", "胜率", "p"),
    ("attribution.total_loss", "总亏损", "m"),
    ("attribution.top1_share", "最大 1 笔占比", "p"),
    ("attribution.top3_share", "前 3 笔占比", "p"),
    ("expectancy.trades", "可计交易笔数", "n"),
    ("expectancy.mean", "单笔期望", "p"),
    ("expectancy.ci_low", "置信区间下限", "p"),
    ("expectancy.ci_high", "置信区间上限", "p"),
)


def outlier_lines(trades):
    lines = ["| 编号 | 标的 | 盈亏 | 占当时净值 |", "|---|---|---|---|"]
    for t in trades:
        lines.append("| %s | %s | %s | %s |" % (t["id"], t["symbol"], fmt(t["pnl"], "m"), fmt(t["impact"], "p")))
    return lines


def fmt(value, kind):
    if value is None:
        return "无"
    if isinstance(value, bool):
        return "是" if value else "否"
    if kind == "p":
        return "%.2f%%" % (value * 100)
    if kind == "m":
        return "{:,.2f}".format(value)
    return str(value)


def facts_markdown(facts):
    lines = ["# 账户指标（只有数值，没有结论）", ""]
    for path, label, kind in FACT_ROWS:
        if label is None:
            lines += ["", "## " + path, "", "| 指标 | 数值 |", "|---|---|"]
        else:
            lines.append("| %s | %s |" % (label, fmt(rules.lookup(facts, path), kind)))
    lines += ["", "## 亏损最大的交易", "", "| 编号 | 标的 | 类别 | 平仓方式 | 仓位 | 盈亏 | 超配倍数 |", "|---|---|---|---|---|---|---|"]
    for t in facts["attribution"]["top_losses"]:
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            t["id"], t["symbol"], t["category"], t["method"], fmt(t["cost"], "m"), fmt(t["pnl"], "m"), fmt(t["k"], "x")))
    lines += ["", "## 未平仓", "", "| 编号 | 标的 | 开仓日 | 仓位 | 浮动盈亏 |", "|---|---|---|---|---|"]
    for t in facts["open_positions"]:
        lines.append("| %s | %s | %s | %s | %s |" % (t["id"], t["symbol"], t["open_date"], fmt(t["cost"], "m"), fmt(t["unrealized"], "m")))
    scan = facts["outliers"]
    lines += ["", "## 异常交易检验", "", "对 %d 笔已平仓交易的单笔盈亏占当时净值的比例做多异常值检验，置信水平 %s，检出 %d 笔，盈亏合计 %s。" % (
        scan["tested"], rules.level_text(scan["level"]), len(scan["trades"]), fmt(scan["pnl"], "m")), ""]
    lines += outlier_lines(scan["trades"])
    lines += ["", "## 数据质量说明", ""]
    lines += ["- " + note for note in facts["data_quality"]["notes"]] or ["- 无"]
    return "\n".join(lines) + "\n"


def run_pipeline(files, cfg, account=None):
    parsed = flex_parse.parse_files(files, account)
    book = trades.build_trades(parsed, cfg)
    facts = metrics.compute_facts(parsed, book, cfg)
    return facts, metrics.trade_rows(book)


def cmd_facts(args):
    cfg = load(args.config)
    try:
        facts, rows = run_pipeline(args.files, cfg, args.account)
    except (ValueError, OSError) as error:
        fail(str(error))
    os.makedirs(args.out, exist_ok=True)
    for name in STALE:
        path = os.path.join(args.out, name)
        if os.path.exists(path):
            os.remove(path)
    dump(os.path.join(args.out, "facts.json"), facts)
    dump(os.path.join(args.out, "trades.json"), rows)
    with open(os.path.join(args.out, "facts.md"), "w", encoding="utf-8") as handle:
        handle.write(facts_markdown(facts))
    dump(os.path.join(args.out, "run_meta.json"), {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "config_sha256": sha256(args.config),
        "inputs": [{"name": os.path.basename(path), "sha256": sha256(path)} for path in args.files],
    })
    print("已写出 facts.json、facts.md、trades.json。")
    print("下一步：读 facts.json，把你的判断写进 %s，再运行 verdict。" % os.path.join(args.out, "model_judgment.json"))


def cmd_verdict(args):
    if os.path.exists(os.path.join(args.out, "verdict.json")):
        fail("拒绝运行：verdict.json 已存在，模型判断不能在比对之后改。要重来就从 facts 重跑。")
    cfg = load(args.config)
    facts = load(os.path.join(args.out, "facts.json"))
    path = os.path.join(args.out, "model_judgment.json")
    if not os.path.exists(path):
        fail("拒绝运行：%s 不存在。先写出模型判断。" % path)
    try:
        judgment = load(path)
    except ValueError:
        fail("拒绝运行：model_judgment.json 不是合法的 JSON。")
    errors = rules.validate_judgment(judgment)
    if errors:
        fail("拒绝运行：model_judgment.json 格式不对。\n- " + "\n- ".join(errors))
    digest = sha256(path)
    verdict = rules.decide(facts, cfg)
    verdict["judgment_sha256"] = digest
    deviations = rules.compare(verdict, judgment)
    dump(os.path.join(args.out, "verdict.json"), verdict)
    dump(os.path.join(args.out, "diff.json"), {"judgment_sha256": digest, "count": len(deviations), "deviations": deviations})
    print("已写出 verdict.json 和 diff.json。偏差 %d 项。" % len(deviations))
    if deviations:
        print("下一步：对每项偏差写裁决到 adjudication.json，再写 analysis.md，然后运行 report。")
    else:
        print("下一步：写 analysis.md，然后运行 report。")


def gather(args):
    cfg = load(args.config)
    out = args.out
    facts = load(os.path.join(out, "facts.json"))
    verdict_path = os.path.join(out, "verdict.json")
    if not os.path.exists(verdict_path):
        fail("verdict.json 不存在。先运行 verdict。")
    verdict = load(verdict_path)
    judgment_path = os.path.join(out, "model_judgment.json")
    if sha256(judgment_path) != verdict["judgment_sha256"]:
        fail("model_judgment.json 在 verdict 之后被改过。改回原样，或从 facts 重跑。")
    judgment = load(judgment_path)
    deviations = load(os.path.join(out, "diff.json"))["deviations"]
    adj = None
    if deviations:
        adj_path = os.path.join(out, "adjudication.json")
        if not os.path.exists(adj_path):
            fail("有 %d 项偏差，但 adjudication.json 不存在。" % len(deviations))
        try:
            adj = load(adj_path)
        except ValueError:
            fail("adjudication.json 不是合法的 JSON。")
        ids = {row["id"] for row in load(os.path.join(out, "trades.json"))}
        errors = rules.validate_adjudication(adj, deviations, facts, ids)
        if errors:
            fail("adjudication.json 被退回。\n- " + "\n- ".join(errors))
    final = rules.finalize(verdict, judgment, deviations, adj)
    return cfg, facts, verdict, judgment, deviations, adj, final


def lint_errors(args, cfg, facts, verdict, final):
    path = os.path.join(args.out, "analysis.md")
    if not os.path.exists(path):
        return None, ["analysis.md 不存在。写不超过 %d 句的分析。" % cfg["lint"]["max_sentences"]]
    with open(path, encoding="utf-8") as handle:
        text = handle.read().strip()
    return text, rules.lint(text, [facts, verdict, final], final["overall"], cfg)


def cmd_lint(args):
    cfg, facts, verdict, _, _, _, final = gather(args)
    _, errors = lint_errors(args, cfg, facts, verdict, final)
    if errors:
        fail("lint 未通过。\n- " + "\n- ".join(errors))
    print("lint 通过。")


def show(field, value):
    if field == "main_cause":
        return value
    return rules.ZH.get(value, value)


def report_markdown(facts, verdict, final, analysis, trimmed=None):
    period = facts["period"]
    title = rules.ZH[final["overall"]] + ("（证据不足）" if final["evidence_insufficient"] else "")
    if final["data_disputed"]:
        title += "（模型指出数据有误，结论待核实，见对照表）"
    elif final["has_deviation"]:
        title += "（模型判断与计算结论有偏差，见对照表）"
    lines = [
        "# 账户健康度：" + title,
        "",
        "区间 %s 至 %s，净值记录 %d 天，%s。" % (period["from"], period["to"], period["nav_days"], STATUS_ZH[facts["data_quality"]["status"]]),
        "",
        "## 五个结论（计算层）",
        "",
        "1. " + verdict["account_type"]["sentence"],
        "2. " + verdict["c2_statistical"]["sentence"],
        "3. " + verdict["c3_damage"]["sentence"],
        "4. " + verdict["c4_source"]["sentence"],
        "5. " + verdict["c5_expectancy"]["sentence"],
        "",
        verdict["overall"]["sentence"],
        "",
        "## 对照",
        "",
        "| 项目 | 计算结论 | 模型判断 | 最终结论 | 来源与裁决 |",
        "|---|---|---|---|---|",
    ]
    for field, _ in rules.FIELDS:
        row = final["fields"][field]
        note = row["mark"] + ("（%s）" % row["category"] if row["category"] else "")
        lines.append("| %s | %s | %s | %s | %s |" % (
            FIELD_ZH[field], show(field, row["computed"]), show(field, row["model"]), show(field, row["final"]), note))
    scan = facts["outliers"]
    if trimmed:
        tv = trimmed["verdict"]
        block = trimmed["facts"]
        lines += ["", "## 第二步：去掉异常交易后", "", tv["sentence"]]
        if block["trades"]:
            lines += [""] + outlier_lines(block["trades"]) + [""]
            for key in ("c4_source", "c5_expectancy"):
                lines.append("- " + tv[key]["sentence"])
            lines.append("- " + tv["window"])
            lines.append("- 相对波动率和实际伤害按每日净值算，成交记录里没有这些仓位每天的市值，去掉交易后不能重算。")
            lines += ["", "| 指标 | 全部交易 | 去掉后 |", "|---|---|---|"]
            for path, label, kind in EX_ROWS:
                lines.append("| %s | %s | %s |" % (label, fmt(rules.lookup(facts, path), kind), fmt(rules.lookup(block, path), kind)))
    elif verdict["c4_source"].get("second_step"):
        level = rules.level_text(scan["level"])
        lines += ["", "## 第二步（可选）：去掉异常交易重算", "",
                  "亏损集中在少数几笔。可以把异常交易去掉再算一遍，看剩下的交易本身怎么样。", ""]
        if scan["trades"]:
            lines += ["按 %s 置信水平检出 %d 笔，盈亏合计 %s：" % (level, len(scan["trades"]), fmt(scan["pnl"], "m")), ""]
            lines += outlier_lines(scan["trades"])
        else:
            lines += ["按 %s 置信水平没有检出异常交易。" % level]
        if verdict["c4_source"].get("second_step_note"):
            lines += ["", verdict["c4_source"]["second_step_note"]]
        lines += ["", "置信水平的意思：如果账户里其实没有异常交易，误判出任何一笔的概率不超过 1 减去这个水平。",
                  "", "运行 `health.py trim --out RUN --level %g` 按这个水平去掉；水平可以换。也可以用 `--trades 编号,编号` 点名去掉。" % scan["level"]]
    lines += ["", "## 亏损最大的 3 笔", "", "| 编号 | 标的 | 类别 | 开仓 | 平仓 | 平仓方式 | 仓位 | 盈亏 | 亏损与仓位之比 | 超配倍数 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for t in facts["attribution"]["top_losses"][:3]:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            t["id"], t["symbol"], rules.CATEGORY_ZH.get(t["category"], t["category"]), t["open_date"], t["close_date"],
            METHOD_ZH.get(t["method"], t["method"]), fmt(t["cost"], "m"), fmt(t["pnl"], "m"), fmt(t["loss_ratio"], "p"), fmt(t["k"], "x")))
    if facts["open_positions"]:
        lines += ["", "## 未平仓", "", "| 编号 | 标的 | 开仓日 | 仓位 | 浮动盈亏 |", "|---|---|---|---|---|"]
        for t in facts["open_positions"]:
            lines.append("| %s | %s | %s | %s | %s |" % (t["id"], t["symbol"], t["open_date"], fmt(t["cost"], "m"), fmt(t["unrealized"], "m")))
    lines += ["", "## 分析", "", analysis, "", "## 数据质量", ""]
    lines += ["- " + note for note in facts["data_quality"]["notes"]] or ["- 没有发现问题。"]
    lines += ["", "## 方法局限", ""]
    lines += ["- " + item for item in LIMITS]
    return "\n".join(lines) + "\n"


def append_log(path, out, verdict, deviations, final):
    digest = verdict["judgment_sha256"]
    seen = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    seen.add((row["judgment_sha256"], row["field"]))
    with open(path, "a", encoding="utf-8") as handle:
        for dev in deviations:
            if (digest, dev["field"]) in seen:
                continue
            row = dict(dev, judgment_sha256=digest, run=os.path.abspath(out),
                       category=final["fields"][dev["field"]]["category"], config_version=verdict["config_version"])
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def cmd_report(args):
    cfg, facts, verdict, _, deviations, _, final = gather(args)
    analysis, errors = lint_errors(args, cfg, facts, verdict, final)
    if errors:
        fail("analysis.md 未通过 lint。\n- " + "\n- ".join(errors))
    dump(os.path.join(args.out, "final.json"), final)
    trimmed_path = os.path.join(args.out, "trimmed.json")
    trimmed = load(trimmed_path) if os.path.exists(trimmed_path) else None
    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as handle:
        handle.write(report_markdown(facts, verdict, final, analysis, trimmed))
    log = args.log or os.path.join(os.path.dirname(os.path.abspath(args.out)), "deviation_log.jsonl")
    if deviations and not getattr(args, "skip_log", False):
        append_log(log, args.out, verdict, deviations, final)
    print("已写出 report.md 和 final.json。")


def cmd_trim(args):
    cfg = load(args.config)
    for name in ("facts.json", "trades.json", "verdict.json", "final.json"):
        if not os.path.exists(os.path.join(args.out, name)):
            fail("先跑完第一步的报告（缺 %s）。" % name)
    facts = load(os.path.join(args.out, "facts.json"))
    rows = load(os.path.join(args.out, "trades.json"))
    if args.trades and args.level is not None:
        fail("--level 和 --trades 只能用一个。")
    if args.trades:
        wanted = [part.strip() for part in args.trades.split(",") if part.strip()]
        known = {row["id"] for row in rows}
        missing = [name for name in wanted if name not in known]
        if missing:
            fail("trades.json 里没有这些交易编号：" + "、".join(missing))
        selection = {"by": "named"}
        flagged = [row for row in rows if row["id"] in set(wanted)]
    else:
        level = args.level if args.level is not None else cfg["outliers"]["default_level"]
        if not 0.5 <= level < 1.0:
            fail("--level 要在 0.5 到 1 之间，例如 0.95。")
        selection = {"by": "level", "level": level}
        flagged = metrics.outliers(rows, level, cfg)
    block = metrics.trimmed(rows, flagged, facts["drawdown"], cfg)
    dump(os.path.join(args.out, "trimmed.json"), {
        "schema": "account-health/trimmed/2",
        "selection": selection,
        "facts": block,
        "verdict": rules.decide_trimmed(facts, block, selection, cfg),
    })
    args.log = None
    args.skip_log = True
    cmd_report(args)
    print("已写出 trimmed.json，report.md 已加上第二步。")


def main():
    parser = argparse.ArgumentParser(prog="health.py")
    sub = parser.add_subparsers(dest="command", required=True)
    facts = sub.add_parser("facts")
    facts.add_argument("files", nargs="+")
    facts.add_argument("--out", required=True)
    facts.add_argument("--account")
    facts.add_argument("--config", default=DEFAULT_CONFIG)
    facts.set_defaults(func=cmd_facts)
    for name, func in (("verdict", cmd_verdict), ("lint", cmd_lint), ("report", cmd_report)):
        cmd = sub.add_parser(name)
        cmd.add_argument("--out", required=True)
        cmd.add_argument("--config", default=DEFAULT_CONFIG)
        if name == "report":
            cmd.add_argument("--log")
        cmd.set_defaults(func=func)
    trim = sub.add_parser("trim")
    trim.add_argument("--out", required=True)
    trim.add_argument("--level", type=float)
    trim.add_argument("--trades")
    trim.add_argument("--config", default=DEFAULT_CONFIG)
    trim.set_defaults(func=cmd_trim)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
