# 怎么建 Flex Query

## 建查询

登录 IBKR 客户端门户：Performance & Reports → Flex Queries → Activity Flex Query → 新建。

勾选这些部分：

| 部分 | 用途 | 必选字段 |
|---|---|---|
| Account Information | 基础货币 | Account ID、Currency |
| Net Asset Value (NAV) in Base，或 Equity Summary by Report Date in Base | 每日净值 | Report Date、Total、Cash |
| Trades，明细级别选 Execution | 成交 | 全选最省事。至少要有：Asset Class、Symbol、Description、Conid、Underlying Symbol、Multiplier、Strike、Expiry、Put/Call、Trade ID、Order ID、Date/Time、Quantity、Trade Price、Proceeds、IB Commission、Net Cash、FX Rate To Base、Open/Close Indicator、Notes/Codes |
| Option Exercises, Assignments and Expirations | 到期、行权、指派 | 全选 |
| Cash Transactions | 出入金、股息、利息、费用 | 全选，类型全勾。有外币时要有 FX Rate To Base |
| Corporate Actions | 换代码、合并 | 全选。有记录时脚本在数据质量里提示 |
| Open Positions，级别选 Summary | 期末持仓和浮动盈亏 | 全选 |

导出设置：

- Format：XML
- Date Format：`yyyyMMdd`
- Time Format：`HHmmss`
- Date/Time Separator：`;`
- 各部分可以放在同一个查询里，也可以分成几个查询导出几个文件，一起传给 `facts`。
- Period：尽量长。单次查询有时间跨度上限，超过就分段导出，把多个文件一起传给 `facts`，脚本按成交编号去重。

## 脚本读哪些元素

| XML 元素 | 读取的属性 |
|---|---|
| `FlexStatement` | `accountId`、`fromDate`、`toDate` |
| `AccountInformation` | `currency`（没有这部分时取净值行的 `currency`） |
| `EquitySummaryByReportDateInBase` | `reportDate`、`total`、`cash` |
| `Trade` | `assetCategory`、`symbol`、`description`、`conid`、`underlyingSymbol`、`multiplier`、`strike`、`expiry`、`putCall`、`tradeID`、`dateTime`、`reportDate`、`tradeDate`、`currency`、`quantity`、`tradePrice`、`proceeds`、`ibCommission`、`netCash`、`fxRateToBase`、`openCloseIndicator`、`notes` |
| `OptionEAE` | `conid`（没有则用 `symbol` 对应到成交里的合约）、`date`、`transactionType`、`quantity` |
| `CashTransaction` | `type`、`amount`、`currency`、`dateTime`、`fxRateToBase`、`reportDate`、`transactionID`（后三个可以没有） |
| `OpenPosition` | `conid`（没有则用 `symbol`）、`symbol`、`assetCategory`、`position`、`positionValue`、`costBasisMoney`、`fifoPnlUnrealized`、`fxRateToBase` |

到期、指派、行权有两个来源，脚本都认：`Trade` 行的 `notes` 里带 `Ep`、`A`、`Ex`；或 `OptionEAE` 行的 `transactionType` 是 `Expiration`、`Assignment`、`Exercise`。两处都没有记录、但期权已过到期日的，按到期归零处理并在数据质量里标出。

## 文件里有多个账户

用 `--account U1234567` 指定一个。

## 凭证

只读手动导出的文件，不联网，不需要 Flex token。
