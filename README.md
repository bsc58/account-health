# 账户健康度（account-health）

用 IBKR Flex 导出文件复盘账户回撤的 Claude skill。全部数字由脚本算出，给出五个结论：账户类型（高波或低波）、回撤相对账户常态的异常程度、实际伤害、亏损来源、打法期望值。模型先独立判断，再和计算结论比对，有偏差按固定程序裁决。

## 安装

```bash
git clone https://github.com/bsc58/account-health.git ~/.claude/skills/account-health
```

```bash
pip install -r ~/.claude/skills/account-health/requirements.txt
```

需要 Python 3.8 以上，依赖只有 `numpy`。

## 使用

1. 照 [references/flex-setup.md](references/flex-setup.md) 在 IBKR 建 Flex Query，导出 XML。
2. 在 Claude 里说“复盘账户”，把 XML 文件给它。Claude 按 [SKILL.md](SKILL.md) 的步骤运行脚本，最后给出 `report.md`。
3. 报告里出现“第二步（可选）”时，可以选择去掉异常交易再算一遍，置信水平自己定。

只想看数值时直接运行：

```bash
python3 scripts/health.py facts 文件1.xml 文件2.xml --out 输出目录
```

阈值和模拟参数都在 [config/thresholds.json](config/thresholds.json)，可以改。

## 依据

| 部分 | 依据 |
|---|---|
| 回撤写成年化波动率的倍数，给定夏普下的发生概率 | Van Hemert 等，《Drawdowns》(2020) |
| 回撤落在假设过程 5% 尾部以外即预警 | Rej、Seager、Bouchaud (2017) |
| 高波账户的逐笔回撤以回撤之前的交易为参照 | MacKinlay (1997) 事件研究的估计窗口；NIST 手册 6.3.2 |
| 参照交易标准差的置信区间 | Bonett (2006) |
| 逐笔交易重抽样，独立和分块两种，取较大的概率 | 《Your backtest's max drawdown is a single sample, not a risk estimate》 |
| 异常交易检验 | Rosner (1983) Generalized ESD；NIST 手册 |
| 期望值的置信区间 | Hesterberg (2015) 自助 t 法 |
| 期望值、R 倍数 | Van Tharp |

每个指标的定义和判定规则见 [references/metrics.md](references/metrics.md)，全部资料和链接见 [references/sources.md](references/sources.md)。
