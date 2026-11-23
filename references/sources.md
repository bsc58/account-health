# 参考资料

## 理论

| 资料 | 用在哪 | 链接 |
|---|---|---|
| Van Hemert、Ganz、Harvey、Rattray、Sanchez Martin、Yawitch，《Drawdowns》(2020) | 回撤写成年化波动率的倍数（$M$）；给定观察期和夏普下的发生概率（$p_{SR}$） | https://ssrn.com/abstract=3583864 ，https://www.man.com/maninstitute/youre-fired |
| Rej、Seager、Bouchaud，《You are in a drawdown. When should you start worrying?》(2017) | “与本次回撤相容的最高夏普”这个表述；逐笔结论的检验形式：回撤落在假设过程的 5% 尾部以外即预警 | https://arxiv.org/abs/1707.01457 |
| MacKinlay，《Event Studies in Economics and Finance》，Journal of Economic Literature 35(1) (1997) | 逐笔结论的参照取在回撤之前：估计窗口在事件窗口之前，事件期间不进估计 | https://www.jstor.org/stable/2729691 |
| Magdon-Ismail、Atiya、Pratap、Abu-Mostafa，《On the Maximum Drawdown of a Brownian Motion》(2004) | 零漂移最大回撤期望的解析式（`lowvol.expected_mdd_zero_drift`） | https://papers.ssrn.com/abstract=874069 ，https://www.mathworks.com/help/finance/emaxdrawdown.html |
| Bailey、López de Prado，三倍忏悔法则 | C3 的回本时间参考值 | https://escholarship.org/uc/item/758637dr |
| Bailey、López de Prado，概率夏普和最短业绩记录长度 | 样本少时结论要带提醒的依据 | https://www.risk.net/journal-risk/2223785/sharpe-ratio-efficient-frontier |
| Goldberg、Mahmoud，条件期望回撤 | 最大回撤看分布而不是单个值 | https://arxiv.org/abs/1404.7493 |
| Peter Martin，Ulcer Index | `lowvol.ulcer_index` | https://www.tangotools.com/ui/ui.htm |
| Van Tharp，R 倍数、期望值、SQN | $\rho$、期望值、SQN | https://www.luxalgo.com/library/concept/sqn/ |

## 异常值和置信区间

| 资料 | 用在哪 | 链接 |
|---|---|---|
| Rosner，《Percentage Points for a Generalized ESD Many-Outlier Procedure》，Technometrics 25 (1983) | 第二步的异常交易检验 | https://itl.nist.gov/div898/handbook/eda/section3/eda35h3.htm |
| NIST/SEMATECH e-Handbook，Generalized ESD Test for Outliers | 检验统计量、临界值公式、遮蔽问题、样本量下限（25 笔很准，15 笔尚可） | https://itl.nist.gov/div898/handbook/eda/section3/eda35h3.htm |
| Leys、Ley、Klein、Bernard、Licata，《Detecting outliers: Do not use standard deviation around the mean, use absolute deviation around the median》(2013) | 不用“均值 ± 几倍标准差”一次划线 | https://orbilu.uni.lu/handle/10993/59204 |
| Adams、Hayunga、Mansi、Reeb、Verardi，《Identifying and treating outliers in finance》，Financial Management 48(2) (2019) | 删掉异常值会带来选择偏差；第二步只作对照，正式结论用全部交易 | https://ideas.repec.org/a/bla/finmgt/v48y2019i2p345-384.html |
| Bakker、Wicherts，《Outlier removal, sum scores, and the inflation of the Type I error rate》，Psychological Methods 19(3) (2014) | 看了结果再调门槛会抬高误判率；默认置信水平事先写在配置里，报告写明用的是哪个水平 | https://research.tilburguniversity.edu/en/publications/outlier-removal-sum-scores-and-the-inflation-of-the-type-i-error-/ |
| Hesterberg，《What Teachers Should Know About the Bootstrap》，The American Statistician 69(4) (2015) | C5 的置信区间用自助 t 法，不用百分位法；小样本用 t 区间 | https://arxiv.org/abs/1411.5279 |
| NIST/SEMATECH e-Handbook，标准差的置信区间 | 参考波动率的置信区间 | https://itl.nist.gov/div898/handbook/prc/section2/prc231.htm |
| Bonett，《Approximate confidence interval for standard deviation of nonnormal distributions》，Computational Statistics & Data Analysis 50(3) (2006)；公式见 NIST Dataplot 手册 | 逐笔结论里参照交易标准差的置信区间（不假设正态），由它得到发生概率的范围 | https://doi.org/10.1016/j.csda.2004.10.003 ，https://itl.nist.gov/div898/software/dataplot/refman1/auxillar/sdconfli.htm |
| NIST/SEMATECH e-Handbook 6.3.2，What are Variables Control Charts? | 参照最少 25 笔（Shewhart 的经验规则）；参照数据少时实际性质可能偏离假设，要加提醒 | https://itl.nist.gov/div898/handbook/pmc/section3/pmc32.htm |
| TradeStation，Select Net Profit | 同类做法的参照：盈利和亏损两头的异常交易一起去掉 | https://help.tradestation.com/10_00/eng/tradestationhelp/subsystems/spr_topics/report/total_outliers__strategy_performance_report_.htm |

## 交易重抽样

| 资料 | 用在哪 | 链接 |
|---|---|---|
| 《Your backtest's max drawdown is a single sample, not a risk estimate》 | 重抽样只能重组已经发生的交易；交易扎堆时独立重抽样低估尾部，要有分块重抽样对照；交易少时尾部不可靠，要加提醒 | https://hackernoon.com/your-backtests-max-drawdown-is-a-single-sample-not-a-risk-estimate |
| MQL5 关于顺序风险的文章 | 顺序风险和抽样风险的区分；最长连亏的模拟 | https://www.mql5.com/en/articles/24469 ，https://www.mql5.com/en/blogs/post/779138 |

## 散户期权亏损的实证（类别标签的背景）

| 资料 | 要点 | 链接 |
|---|---|---|
| Bryzgalova、Pavlova、Sikorskaya (2023) | 散户期权成交约一半是一周内到期 | https://lbsresearch.london.edu/id/eprint/2827 |
| de Silva、Smith、So | 财报前后买期权的平均亏损 | https://mitsloan.mit.edu/ideas-made-to-matter/retail-investors-lose-big-options-markets-research-shows |
| Bogousslavsky、Muravyev | 反面证据：逐个交易者的数据显示亏损相对较小 | https://hkubs.hku.hk/event/an-anatomy-of-retail-option-trading |

## 工具和同类 skill

解析器用标准库 `xml.etree` 写，唯一的依赖是 `numpy`。下面是同类工具，供对照。

| 资料 | 链接 |
|---|---|
| ibflex | https://github.com/csingley/ibflex |
| py-ibkr | https://pypi.org/project/py-ibkr/ |
| QuantStats | https://pypi.org/project/quantstats |
| Esonhugh/ibkr-trade-analyzer | https://github.com/Esonhugh/ibkr-trade-analyzer |
| tradermonty/claude-trading-skills | https://github.com/tradermonty/claude-trading-skills |
| Trading Journal Performance Auditor | https://www.agensi.io/skills/trading-journal-performance-auditor |
| jgalea/ibkr-mcp、knishioka/ib-sec-mcp | https://glama.ai/mcp/servers/jgalea/ibkr-mcp ，https://glama.ai/mcp/servers/bmd7n40rdp |

## Skill 写法

| 资料 | 要点 | 链接 |
|---|---|---|
| Anthropic，Skill authoring best practices | 确定性操作用脚本 | https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices |
| Agent Skills 规范，Using scripts | 脚本接口的设计 | https://agentskills.io/skill-creation/using-scripts |
| Block，3 principles for designing agent skills | 脚本负责确定性部分，模型负责判断部分 | https://engineering.block.xyz/blog/3-principles-for-designing-agent-skills |
