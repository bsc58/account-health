---
name: account-health
description: 用 IBKR Flex 导出文件复盘账户健康度。脚本算出账户类型（高波或低波）、回撤相对波动率的异常程度、实际伤害、亏损来源和打法期望值，输出五个结论；模型先独立判断，再与计算结论比对，有偏差按固定程序裁决。用户说“复盘账户”“账户健康度”“回撤重不重”“分析 IB 账户”或给出 Flex XML 文件时使用。
---

# 账户健康度

所有数字由脚本算出。你不自己算任何数字，只做三件事：读数值后写判断、对偏差做裁决、写不超过三句的分析。

下面的 `SKILL` 指本文件所在目录，`RUN` 指本次运行的输出目录（每次复盘新建一个）。

## 环境

Python 3.8 以上，`numpy`（见 `requirements.txt`）。没有其他依赖。

## 输入

IBKR Flex Query 导出的 XML 文件，一个或多个（跨年时多个文件会自动合并去重）。用户还没有文件时，让他照 `references/flex-setup.md` 建查询并导出。

## 步骤

按顺序执行，不跳步，不改命令。

### 1. 算指标

```bash
python3 SKILL/scripts/health.py facts 文件1.xml [文件2.xml ...] --out RUN
```

得到 `RUN/facts.json`、`RUN/facts.md`、`RUN/trades.json`，里面只有数值，没有结论。另有 `RUN/run_meta.json` 记录版本和输入文件哈希，不用读。

### 2. 写你的判断

写完这一步之前，不要打开 `scripts/rules.py`、`config/thresholds.json` 和 `references/metrics.md`。

读 `RUN/facts.json`，把判断写进 `RUN/model_judgment.json`：

```json
{
  "account_type": "high_vol | low_vol",
  "c2_statistical": "green | yellow | red | undetermined",
  "c3_damage": "green | yellow | red",
  "c5_expectancy": "positive | unproven | negative | insufficient",
  "overall": "green | yellow | red",
  "main_cause": "交易编号或类别名",
  "reasons": {
    "account_type": "一句话",
    "c2_statistical": "一句话",
    "c3_damage": "一句话",
    "c5_expectancy": "一句话",
    "overall": "一句话",
    "main_cause": "一句话"
  }
}
```

各字段的含义：

| 字段 | 问的是什么 | 看哪些数 | 取值含义 |
|---|---|---|---|
| `account_type` | 账户属于哪一类 | `account.sigma_annual`（不看 `sigma_annual_full_record`）、`account.option_share` | `high_vol`：年化波动率很高，或盈亏主要来自期权，满足一条即可。`low_vol`：其余 |
| `c2_statistical` | 这次回撤相对账户自己的常态是否异常 | 每个账户都看 `lowvol.multiple_of_annual_vol`（回撤是年化波动率的几倍）和 `lowvol.p_by_sharpe["0.0"]`（没有优势时出现这么深回撤的概率，越小越异常），`lowvol.p0_ci` 是它的范围。高波账户再看 `trade_drawdown.p0`（以回撤之前的交易为参照，没有优势时出现这么深的逐笔回撤的概率，越小越异常），`trade_drawdown.p0_ci` 是它的范围；两条取较重的 | `green`：正常范围内。`yellow`：偏重。`red`：账户原来的波动或打法解释不了，属于事故。`undetermined`：只在两个概率都为空时用。样本少但有数时照常给颜色 |
| `c3_damage` | 从谷底回到前高有多难 | `drawdown.recovery_gain`。`capital.pnl_ratio` 只作旁证，两者不一致时以前者为准 | `green`：容易回本。`yellow`：要较大涨幅。`red`：很难回本 |
| `c5_expectancy` | 这套打法赚不赚钱 | `expectancy.trades`、`expectancy.ci_low`、`expectancy.ci_high` | `positive`：置信区间整体大于 0。`negative`：整体小于 0。`unproven`：跨 0。`insufficient`：只在区间为空（算不出来）时用 |
| `overall` | 总体 | 上面三项 | 三项里最差的一个。`c5_expectancy` 换算：`negative` 当红，`unproven` 当黄，`positive` 当绿。`undetermined` 和 `insufficient` 的项不参与比较 |
| `main_cause` | 伤主要从哪来 | `attribution` | 亏损最大那笔的交易编号（如 `T0012`），或亏损最多的类别：`stock`、`leveraged_etf`、`option`、`weekly_option`。两种填法都算对 |

### 3. 出规则结论和比对

```bash
python3 SKILL/scripts/health.py verdict --out RUN
```

`model_judgment.json` 不存在或格式不对时脚本拒绝运行。成功后得到 `RUN/verdict.json` 和 `RUN/diff.json`。每次 facts 之后 verdict 只能跑一次；跑过之后不能再改 `model_judgment.json`，要重来就从第 1 步重跑。

### 4. 裁决偏差

`diff.json` 的 `count` 为 0 时跳过这一步。否则对 `deviations` 里的每一项，按下面的顺序检查，停在第一个成立的类别：

1. **`DATA_ERROR`**：你能指出 `trades.json` 里某笔交易或某个日期的净值有解析或数据错误。证据写交易编号或 8 位日期、字段名、你认为正确的值。
2. **`RULE_NOT_APPLICABLE`**：`facts.json` 里有脚本立起的“输入不可靠”标志已经亮起，且和这条规则有关。只认下面这些字段，字段的当前值必须等于括号里的值才算：
   - 任何规则都可用：`data_quality.status`（`"PARTIAL"`）、`data_quality.reconcile.ok`（`false`）。
   - `C1`、`C2`、`OVERALL` 可用：`account.sigma_source`（`"full_record"`）。
   - `C2`、`OVERALL` 可用：`lowvol.reference_source`（`"full_record"`）、`lowvol.reference_sufficient`（`false`）、`lowvol.methods_disagree`（`true`）、`trade_drawdown.reference_source`（`"full_record"`）、`trade_drawdown.methods_disagree`（`true`）。
   - `C3`、`C4`、`C5` 只能用前两个。

   这些标志都没亮时不能选这一类。证据写规则编号和字段路径。
3. **`MODEL_ERROR`**：你读错了数字、推理有误，或者只是分界线和规则不同。
4. **`UNRESOLVED`**：以上都不是，你仍然不同意，但给不出可验证的原因。

写进 `RUN/adjudication.json`：

```json
{
  "items": [
    {
      "field": "c2_statistical",
      "category": "RULE_NOT_APPLICABLE",
      "evidence": {"rule": "C2", "facts_path": "lowvol.methods_disagree"},
      "note": "一句话"
    },
    {
      "field": "c3_damage",
      "category": "DATA_ERROR",
      "evidence": {"record": "T0012", "field": "pnl", "value": -1234.5},
      "note": "一句话"
    },
    {"field": "overall", "category": "MODEL_ERROR", "note": "一句话"}
  ]
}
```

规则编号：`account_type` 是 `C1`，`c2_statistical` 是 `C2`，`c3_damage` 是 `C3`，`c5_expectancy` 是 `C5`，`overall` 是 `OVERALL`，`main_cause` 是 `C4`。

各类别的结果：

| 类别 | 最终结论 |
|---|---|
| `DATA_ERROR` | 以计算结论为准，报告标题和对照表写明模型指出的那条记录。把这条记录告诉用户，请他对照账户核实，拿到更正后的导出文件再从第 1 步重跑 |
| `RULE_NOT_APPLICABLE` | 该项记为“无法判断”，两个结论并列 |
| `MODEL_ERROR` | 以计算结论为准 |
| `UNRESOLVED` | 以计算结论为准，标注存在偏差，两个结论并列 |

### 5. 写分析

把分析写进 `RUN/analysis.md`：

- 不超过三句。
- 只串联 `verdict.json` 里已有的结论和 `facts.json` 里已有的数字，不引入新数字，不给操作建议。
- 百分比按 `verdict.json` 句子里的写法抄。

### 6. 出报告

```bash
python3 SKILL/scripts/health.py report --out RUN
```

脚本会校验裁决、检查分析文字（数字能否在 `facts.json` 或 `verdict.json` 里找到、措辞是否和最终结论矛盾），通过后写出 `RUN/report.md`。被退回时按提示改对应的文件，再运行同一条命令。只想检查分析文字时用：

```bash
python3 SKILL/scripts/health.py lint --out RUN
```

### 7. 交给用户

把 `RUN/report.md` 原样给用户。不要改写其中的结论，不要补充报告里没有的数字。

### 8. 第二步（报告里有“第二步（可选）”一节时）

这一节只在亏损集中时出现，里面列出按默认置信水平检出的异常交易。把这张表给用户看，问一句：要不要去掉异常交易再算一遍；按表里的置信水平去掉、换一个水平，还是直接点名哪几笔。不替用户选，用户不要就结束。

按置信水平：

```bash
python3 SKILL/scripts/health.py trim --out RUN --level 0.95
```

点名：

```bash
python3 SKILL/scripts/health.py trim --out RUN --trades T0012,T0034
```

脚本把结果写进 `RUN/trimmed.json`，并在 `RUN/report.md` 里把这一节换成“第二步：去掉异常交易后”。把更新后的报告原样给用户。用户想换就再运行一次。

## 文件

- `scripts/health.py`：命令入口（`facts`、`verdict`、`lint`、`report`、`trim`）
- `config/thresholds.json`：全部阈值和模拟参数，带版本号
- `references/metrics.md`：指标定义、判定规则
- `references/flex-setup.md`：怎么建 Flex Query
- `references/sources.md`：参考资料
