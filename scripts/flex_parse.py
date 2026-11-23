import xml.etree.ElementTree as ET


def number(value, default=0.0):
    if value is None or value == "":
        return default
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return default


def stamp(value):
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) < 8:
        return "", ""
    return digits[:8], digits[8:14].ljust(6, "0")


def _codes(value):
    return sorted({part.strip() for part in (value or "").replace(",", ";").split(";") if part.strip()})


def _execution(el):
    fx = number(el.get("fxRateToBase"), 1.0) or 1.0
    day, clock = stamp(el.get("dateTime") or el.get("tradeDate"))
    if not day:
        day, clock = stamp(el.get("tradeDate"))
    if el.get("netCash") not in (None, ""):
        net = number(el.get("netCash"))
    else:
        net = number(el.get("proceeds")) + number(el.get("ibCommission")) + number(el.get("taxes"))
    key = el.get("tradeID") or el.get("transactionID") or "|".join(
        [el.get("conid", ""), el.get("dateTime", ""), el.get("quantity", ""), el.get("tradePrice", "")]
    )
    return {
        "id": key,
        "conid": el.get("conid", ""),
        "symbol": el.get("symbol", ""),
        "description": el.get("description", ""),
        "asset": el.get("assetCategory", ""),
        "underlying": el.get("underlyingSymbol") or el.get("symbol", ""),
        "multiplier": number(el.get("multiplier"), 1.0) or 1.0,
        "strike": number(el.get("strike")),
        "expiry": stamp(el.get("expiry"))[0],
        "put_call": el.get("putCall", ""),
        "date": day,
        "time": clock,
        "book_date": stamp(el.get("reportDate") or el.get("tradeDate"))[0] or day,
        "currency": el.get("currency", ""),
        "fx": fx,
        "quantity": number(el.get("quantity")),
        "price": number(el.get("tradePrice")),
        "net": net * fx,
        "open_close": el.get("openCloseIndicator", ""),
        "codes": _codes(el.get("notes")),
        "order": el.get("ibOrderID", ""),
    }


def _nearest_rate(rates, currency, day):
    known = rates.get(currency)
    if not known:
        return None
    return min(known, key=lambda item: (abs(int(item[0]) - int(day)), item[0]))[1]


def _trade_elements(statement):
    rows = [el for el in statement.iter("Trade") if el.get("levelOfDetail", "EXECUTION") in ("EXECUTION", "")]
    if rows:
        return rows
    return list(statement.iter("Order"))


def parse_files(paths, account=None):
    statements = []
    for path in paths:
        root = ET.parse(path).getroot()
        statements.extend(root.iter("FlexStatement"))
    accounts = sorted({st.get("accountId", "") for st in statements})
    if account is None and len(accounts) > 1:
        raise ValueError("文件里有多个账户，请用 --account 指定一个：" + "、".join(accounts))
    if account is not None:
        statements = [st for st in statements if st.get("accountId", "") == account]
    if not statements:
        raise ValueError("没有找到 FlexStatement")
    statements.sort(key=lambda st: (stamp(st.get("toDate"))[0], stamp(st.get("fromDate"))[0]))

    nav = {}
    executions = {}
    eae = {}
    cash = {}
    base_currency = ""
    nav_currency = ""
    transfers = 0
    corporate_actions = 0
    for st in statements:
        for el in st.iter("AccountInformation"):
            base_currency = el.get("currency", base_currency)
        for el in st.iter("EquitySummaryByReportDateInBase"):
            day = stamp(el.get("reportDate"))[0]
            nav_currency = el.get("currency", nav_currency)
            if day:
                nav[day] = {
                    "total": number(el.get("total")),
                    "cash": number(el.get("cash")) if el.get("cash") not in (None, "") else None,
                }
        for el in _trade_elements(st):
            row = _execution(el)
            if row["date"] and row["conid"]:
                executions[row["id"]] = row
        for el in st.iter("OptionEAE"):
            if el.get("transactionType") is None:
                continue
            day = stamp(el.get("date"))[0]
            key = (el.get("conid", ""), el.get("symbol", ""), day, el.get("transactionType", ""), el.get("quantity", ""))
            eae[key] = {
                "conid": el.get("conid", ""),
                "symbol": el.get("symbol", ""),
                "asset": el.get("assetCategory", "") or "OPT",
                "date": day,
                "type": el.get("transactionType", ""),
                "quantity": number(el.get("quantity")),
            }
        for el in st.iter("CashTransaction"):
            day = stamp(el.get("reportDate") or el.get("dateTime") or el.get("settleDate"))[0]
            kind = el.get("type", "")
            key = el.get("transactionID") or "|".join(
                [kind, el.get("dateTime", "") or day, el.get("amount", ""), el.get("description", "")]
            )
            cash[key] = {
                "type": kind,
                "date": day,
                "amount": number(el.get("amount")),
                "currency": el.get("currency", ""),
                "fx": number(el.get("fxRateToBase"), 0.0) or None,
                "flow": "Deposit" in kind or "Withdrawal" in kind,
            }
        transfers += sum(1 for _ in st.iter("Transfer"))
        corporate_actions += sum(1 for _ in st.iter("CorporateAction"))

    base_currency = base_currency or nav_currency
    by_symbol = {}
    rates = {}
    for row in executions.values():
        by_symbol[row["symbol"]] = row["conid"]
        rates.setdefault(row["currency"], []).append((row["book_date"], row["fx"]))
    for row in eae.values():
        row["conid"] = row["conid"] or by_symbol.get(row["symbol"], "")
    unconverted = 0
    for row in cash.values():
        fx = row["fx"]
        if fx is None:
            fx = 1.0 if row["currency"] in ("", base_currency) else _nearest_rate(rates, row["currency"], row["date"])
        if fx is None:
            unconverted += 1
            fx = 1.0
        row["amount"] *= fx

    has_positions = any(st.find("OpenPositions") is not None for st in statements)
    last = max(
        (st for st in statements if st.find("OpenPositions") is not None),
        key=lambda st: (stamp(st.get("toDate"))[0], stamp(st.get("fromDate"))[0]),
        default=statements[-1],
    )
    open_positions = []
    for el in last.iter("OpenPosition"):
        if el.get("levelOfDetail", "SUMMARY") not in ("SUMMARY", ""):
            continue
        fx = number(el.get("fxRateToBase"), 1.0) or 1.0
        open_positions.append({
            "conid": el.get("conid", "") or by_symbol.get(el.get("symbol", ""), ""),
            "symbol": el.get("symbol", ""),
            "asset": el.get("assetCategory", ""),
            "position": number(el.get("position")),
            "value": number(el.get("positionValue")) * fx,
            "cost": number(el.get("costBasisMoney")) * fx,
            "unrealized": number(el.get("fifoPnlUnrealized")) * fx,
        })

    return {
        "accounts": accounts if account is None else [account],
        "base_currency": base_currency,
        "from": min(stamp(st.get("fromDate"))[0] for st in statements),
        "to": max(stamp(st.get("toDate"))[0] for st in statements),
        "nav": nav,
        "executions": sorted(executions.values(), key=lambda r: (r["date"], r["time"], r["id"])),
        "eae": sorted(eae.values(), key=lambda r: (r["date"], r["conid"], r["type"])),
        "cash": sorted(cash.values(), key=lambda r: (r["date"], r["type"], r["amount"])),
        "open_positions": open_positions,
        "has_positions": has_positions,
        "unconverted_cash": unconverted,
        "transfers": transfers,
        "corporate_actions": corporate_actions,
    }
