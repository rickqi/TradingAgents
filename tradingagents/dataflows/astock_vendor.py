"""a-stock-data vendor — pure Python wrappers for A-share financial data endpoints.

Provides 10 vendor functions sourced from the a-stock-data project
(https://github.com/simonlin1212/a-stock-data), covering research reports,
consensus EPS, hot stocks, concept blocks, fund flow, dragon-tiger boards,
lockup expiry, industry rankings, northbound capital, and full-market
dragon-tiger data.

All functions return formatted markdown strings. No exceptions are ever raised —
errors are returned as descriptive strings so callers can safely use the output
directly.

Dependencies: akshare, requests, pandas (all already installed).
"""

import logging
import math
import time
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Maximum rows to include in output before truncation
_MAX_ROWS = 500

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_ticker(code: str) -> str:
    """Strip market prefixes/suffixes to get a pure 6-digit stock code.

    Handles: sh600519, sz000858, bj832000, 600519.SH, 000858.SZ, SH600519, etc.
    """
    code = str(code).strip()
    # Remove known prefixes (case-insensitive)
    for prefix in ("sh", "sz", "bj", "SH", "SZ", "BJ"):
        if code.startswith(prefix):
            code = code[len(prefix):]
            break
    # Remove known suffixes
    for suffix in (".SH", ".SZ", ".BJ", ".sh", ".sz", ".bj"):
        if code.endswith(suffix):
            code = code[: -len(suffix)]
            break
    return code


def _get_prefix(code: str) -> str:
    """Return sh/sz/bj market prefix based on the 6-digit stock code."""
    code = _normalize_ticker(code)
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    else:
        return "sz"


def _format_table(data: list[dict], title: str) -> str:
    """Convert a list of row dicts into a markdown table string.

    Truncates at _MAX_ROWS with a summary line.
    """
    if not data:
        return f"# {title}\nNo data available.\n"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"# {title}", f"Retrieved: {now}", f"Total records: {len(data)}", ""]

    columns = list(data[0].keys())

    # Markdown table header
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("-" * max(len(str(c)), 3) for c in columns) + " |"
    lines.append(header)
    lines.append(sep)

    truncated = False
    display_data = data
    if len(data) > _MAX_ROWS:
        display_data = data[:_MAX_ROWS]
        truncated = True

    for row in display_data:
        vals = []
        for col in columns:
            val = str(row.get(col, ""))
            # Escape pipe characters in values
            val = val.replace("|", ";")
            vals.append(val)
        lines.append("| " + " | ".join(vals) + " |")

    if truncated:
        lines.append(
            f"\n... truncated {len(data) - _MAX_ROWS} rows "
            f"(showing first {_MAX_ROWS})"
        )

    return "\n".join(lines) + "\n"


def _format_kv_table(data: dict, title: str) -> str:
    """Format a flat dict as a key-value markdown table."""
    if not data:
        return f"# {title}\nNo data available.\n"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"# {title}", f"Retrieved: {now}", ""]
    lines.append("| Key | Value |")
    lines.append("|-----|-------|")
    for k, v in data.items():
        if isinstance(v, (list, dict)):
            v = str(v)[:200]
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines) + "\n"


# Shared HTTP headers
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
)

_BAIDU_PAE_HEADERS = {
    "Host": "finance.pae.baidu.com",
    "User-Agent": _UA,
    "Accept": "application/vnd.finance-web.v1+json",
    "Origin": "https://gushitong.baidu.com",
    "Referer": "https://gushitong.baidu.com/",
}

_HSGT_HEADERS = {
    "User-Agent": _UA,
    "Host": "data.hexin.cn",
    "Referer": "https://data.hexin.cn/",
}


# ---------------------------------------------------------------------------
# Public vendor functions — each returns str (formatted markdown)
# ---------------------------------------------------------------------------


def get_research_reports(
    code: str,
    max_pages: int = 3,
) -> str:
    """Fetch research reports from Eastmoney report API.

    Returns report list with ratings and 3-year EPS forecasts as markdown.
    """
    try:
        code = _normalize_ticker(code)
        session = requests.Session()
        session.headers.update(
            {"User-Agent": _UA, "Referer": "https://data.eastmoney.com/"}
        )

        api_url = "https://reportapi.eastmoney.com/report/list"
        all_records: list[dict] = []

        for page in range(1, max_pages + 1):
            params = {
                "industryCode": "*",
                "pageSize": "100",
                "industry": "*",
                "rating": "*",
                "ratingChange": "*",
                "beginTime": "2000-01-01",
                "endTime": "2030-01-01",
                "pageNo": str(page),
                "fields": "",
                "qType": "0",
                "orgCode": "",
                "code": code,
                "rcode": "",
                "p": str(page),
                "pageNum": str(page),
                "pageNumber": str(page),
            }
            r = session.get(api_url, params=params, timeout=30)
            d = r.json()
            rows = d.get("data") or []
            if not rows:
                break
            all_records.extend(rows)
            if page >= (d.get("TotalPage", 1) or 1):
                break
            time.sleep(0.3)

        if not all_records:
            return f"# Research Reports ({code})\nNo research reports found.\n"

        # Extract key fields
        display: list[dict] = []
        for rec in all_records:
            display.append({
                "date": (rec.get("publishDate") or "")[:10],
                "org": rec.get("orgSName") or "",
                "title": (rec.get("title") or "")[:80],
                "rating": rec.get("emRatingName") or "",
                "EPS_this": rec.get("predictThisYearEps", ""),
                "EPS_next": rec.get("predictNextYearEps", ""),
                "EPS_next2": rec.get("predictNextTwoYearEps", ""),
                "industry": rec.get("indvInduName") or "",
            })

        return _format_table(display, f"Research Reports ({code})")

    except Exception as exc:
        return f"Error fetching research reports for {code}: {exc}"


def get_consensus_eps(code: str) -> str:
    """Fetch institutional consensus EPS forecast via akshare stock_profit_forecast_ths.

    Returns yearly EPS consensus (min/mean/max) with analyst coverage count.
    """
    try:
        import akshare as ak

        code = _normalize_ticker(code)

        df = ak.stock_profit_forecast_ths(
            symbol=code, indicator="预测年报每股收益"
        )

        if df is None or df.empty:
            return f"# Consensus EPS ({code})\nNo institutional coverage found.\n"

        rows: list[dict] = []
        for _, row in df.iterrows():
            rows.append({
                "year": str(row.get("年度", "")),
                "analyst_count": row.get("预测机构数", ""),
                "eps_min": row.get("最小值", ""),
                "eps_mean": row.get("均值", ""),
                "eps_max": row.get("最大值", ""),
                "industry_avg": row.get("行业平均数", ""),
            })

        return _format_table(rows, f"Consensus EPS Forecast ({code})")

    except Exception as exc:
        return f"Error fetching consensus EPS for {code}: {exc}"


def get_hot_stocks_with_reasons(date: Optional[str] = None) -> str:
    """Fetch THS hot stocks with editorial reason tags (题材归因).

    Returns today's strong stocks with human-curated thematic attribution.
    """
    try:
        if date is None:
            date = _date.today().strftime("%Y-%m-%d")

        url = (
            f"http://zx.10jqka.com.cn/event/api/getharden/"
            f"date/{date}/orderby/date/orderway/desc/charset/GBK/"
        )
        headers = {"User-Agent": _UA}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()

        if data.get("errocode", 0) != 0:
            return (
                f"# Hot Stocks with Reasons ({date})\n"
                f"THS API error: {data.get('errormsg', 'unknown')}\n"
            )

        rows_raw = data.get("data") or []
        if not rows_raw:
            return f"# Hot Stocks with Reasons ({date})\nNo hot stocks data for this date.\n"

        # Build display rows with renamed fields
        display: list[dict] = []
        for item in rows_raw:
            display.append({
                "code": item.get("code", ""),
                "name": item.get("name", ""),
                "reason": item.get("reason", ""),  # 题材归因 — core field
                "change_pct": item.get("zhangfu", ""),
                "turnover_pct": item.get("huanshou", ""),
                "amount": item.get("chengjiaoe", ""),
                "dde_net": item.get("ddejingliang", ""),
                "close": item.get("close", ""),
                "market": item.get("market", ""),
            })

        return _format_table(display, f"Hot Stocks with Reasons ({date})")

    except Exception as exc:
        return f"Error fetching hot stocks: {exc}"


def get_concept_blocks(code: str) -> str:
    """Fetch Baidu PAE industry/concept/region classification for a stock.

    Returns all three dimensions with change percentages.
    """
    try:
        code = _normalize_ticker(code)

        url = (
            f"https://finance.pae.baidu.com/api/getrelatedblock"
            f"?code={code}&market=ab"
            f"&typeCode=all&finClientType=pc"
        )
        r = requests.get(url, headers=_BAIDU_PAE_HEADERS, timeout=10)
        d = r.json()

        if str(d.get("ResultCode", -1)) != "0":
            return f"# Concept Blocks ({code})\nBaidu PAE error: {d}\n"

        sections: list[dict] = []
        for block in d.get("Result", []):
            block_type = block.get("type", "")
            for item in block.get("list", []):
                sections.append({
                    "category": block_type,
                    "name": item.get("name", ""),
                    "change_pct": item.get("increase", ""),
                    "desc": item.get("desc", ""),
                })

        if not sections:
            return f"# Concept Blocks ({code})\nNo classification data found.\n"

        return _format_table(sections, f"Concept Blocks ({code})")

    except Exception as exc:
        return f"Error fetching concept blocks for {code}: {exc}"


def get_fund_flow(
    code: str,
    date: Optional[str] = None,
) -> str:
    """Fetch Baidu PAE individual stock fund flow (main force / retail / super-large).

    Combines minute-level realtime + 20-day history into a single report.
    """
    try:
        code = _normalize_ticker(code)
        today_compact = (
            date.replace("-", "") if date else _date.today().strftime("%Y%m%d")
        )

        # --- Part 1: Minute-level realtime ---
        realtime_rows: list[dict] = []
        rt_url = (
            f"https://finance.pae.baidu.com/vapi/v1/fundflow"
            f"?code={code}&market=ab&date={today_compact}"
            f"&finClientType=pc"
        )
        try:
            r = requests.get(rt_url, headers=_BAIDU_PAE_HEADERS, timeout=10)
            d = r.json()
            if str(d.get("ResultCode", -1)) == "0":
                raw = d.get("Result", {}).get("update_data", "")
                if raw:
                    for segment in raw.split(";"):
                        parts = segment.split(",")
                        if len(parts) >= 9:
                            realtime_rows.append({
                                "time": parts[0],
                                "mainForce_wan": parts[2],
                                "retail_wan": parts[3],
                                "super_wan": parts[4],
                                "large_wan": parts[5],
                                "price": parts[8],
                            })
        except Exception as exc_rt:
            logger.warning("Failed to fetch realtime fund flow: %s", exc_rt)

        # --- Part 2: Daily history (20 trading days) ---
        history_rows: list[dict] = []
        hist_url = (
            f"https://finance.pae.baidu.com/vapi/v1/fundsortlist"
            f"?code={code}&market=ab&pn=0&rn=20"
            f"&finClientType=pc"
        )
        try:
            r = requests.get(hist_url, headers=_BAIDU_PAE_HEADERS, timeout=10)
            d = r.json()
            if str(d.get("ResultCode", -1)) == "0":
                for item in d.get("Result", {}).get("list", []):
                    history_rows.append({
                        "date": item.get("showtime", ""),
                        "close": item.get("closepx", ""),
                        "change_pct": item.get("ratio", ""),
                        "superNetIn_wan": item.get("superNetIn", ""),
                        "largeNetIn_wan": item.get("largeNetIn", ""),
                        "mediumNetIn_wan": item.get("mediumNetIn", ""),
                        "littleNetIn_wan": item.get("littleNetIn", ""),
                        "mainIn_wan": item.get("extMainIn", ""),
                    })
        except Exception as exc_hist:
            logger.warning("Failed to fetch fund flow history: %s", exc_hist)

        # Combine both parts
        parts: list[str] = []
        if history_rows:
            parts.append(
                _format_table(
                    history_rows,
                    f"Fund Flow History - {code} (Recent 20 Trading Days)",
                )
            )
        if realtime_rows:
            parts.append(
                _format_table(
                    realtime_rows,
                    f"Fund Flow Realtime - {code} (Minute-Level)",
                )
            )

        if not parts:
            return f"# Fund Flow ({code})\nNo fund flow data available.\n"

        return "\n".join(parts)

    except Exception as exc:
        return f"Error fetching fund flow for {code}: {exc}"


def get_dragon_tiger_detail(
    code: str,
    trade_date: Optional[str] = None,
    look_back: int = 30,
) -> str:
    """Fetch dragon tiger board detail for a stock via akshare.

    Returns board records + buy/sell seats TOP5 + institution stats.
    """
    try:
        import akshare as ak

        code = _normalize_ticker(code)

        if trade_date is None:
            trade_date = _date.today().strftime("%Y-%m-%d")

        start = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(
            days=look_back
        )
        start_str = start.strftime("%Y%m%d")
        end_str = trade_date.replace("-", "")

        # 1. Board records
        records: list[dict] = []
        try:
            df = ak.stock_lhb_detail_em(
                start_date=start_str, end_date=end_str
            )
            if df is not None and not df.empty:
                df_stock = df[df["代码"] == code]
                for _, row in df_stock.iterrows():
                    records.append({
                        "date": str(row.get("日期", "")),
                        "reason": row.get("解读", ""),
                        "net_buy": row.get("龙虎榜净买额", 0),
                        "turnover": row.get("换手率", 0),
                    })
        except Exception:
            pass

        # 2. Buy/sell seats TOP5
        buy_seats: list[dict] = []
        sell_seats: list[dict] = []
        if records:
            latest_date = records[0]["date"].replace("-", "")[:8]
            try:
                df_detail = ak.stock_lhb_stock_detail_em(
                    symbol=code, date=latest_date, flag="买入"
                )
                if df_detail is not None and not df_detail.empty:
                    for _, row in df_detail.head(5).iterrows():
                        buy_seats.append({
                            "name": row.get("营业部名称", ""),
                            "buy_amt": row.get("买入额", 0),
                            "sell_amt": row.get("卖出额", 0),
                            "net": row.get("净额", 0),
                        })
            except Exception:
                pass
            try:
                df_detail = ak.stock_lhb_stock_detail_em(
                    symbol=code, date=latest_date, flag="卖出"
                )
                if df_detail is not None and not df_detail.empty:
                    for _, row in df_detail.head(5).iterrows():
                        sell_seats.append({
                            "name": row.get("营业部名称", ""),
                            "buy_amt": row.get("买入额", 0),
                            "sell_amt": row.get("卖出额", 0),
                            "net": row.get("净额", 0),
                        })
            except Exception:
                pass

        # 3. Institution stats
        institution: dict = {}
        try:
            df_inst = ak.stock_lhb_jgmmtj_em(symbol=code)
            if df_inst is not None and not df_inst.empty:
                row = df_inst.iloc[0]
                institution = {
                    "buy_count": row.get("买入机构数", 0),
                    "sell_count": row.get("卖出机构数", 0),
                    "net_amount": row.get("机构净买入额", 0),
                }
        except Exception:
            pass

        # Build combined output
        parts: list[str] = []

        if records:
            parts.append(
                _format_table(
                    records,
                    f"Dragon Tiger Board Records - {code} (Last {look_back} Days)",
                )
            )
        else:
            parts.append(
                f"# Dragon Tiger Board Records - {code}\n"
                f"No board records in last {look_back} days.\n"
            )

        if buy_seats:
            parts.append(
                _format_table(
                    buy_seats, f"Buy Seats TOP5 - {code}"
                )
            )
        if sell_seats:
            parts.append(
                _format_table(
                    sell_seats, f"Sell Seats TOP5 - {code}"
                )
            )
        if institution:
            parts.append(
                _format_kv_table(
                    institution,
                    f"Institution Stats - {code}",
                )
            )

        return "\n".join(parts)

    except Exception as exc:
        return f"Error fetching dragon tiger detail for {code}: {exc}"


def get_lockup_expiry(
    code: str,
    trade_date: Optional[str] = None,
    forward_days: int = 90,
) -> str:
    """Fetch lockup expiry calendar for a stock via akshare.

    Returns historical lockup releases + upcoming expiries within forward_days.
    """
    try:
        import akshare as ak

        code = _normalize_ticker(code)

        if trade_date is None:
            trade_date = _date.today().strftime("%Y-%m-%d")

        # 1. Historical lockup releases
        history: list[dict] = []
        try:
            df = ak.stock_restricted_release_queue_em(symbol=code)
            if df is not None and not df.empty:
                for _, row in df.head(15).iterrows():
                    history.append({
                        "date": str(row.get("解禁时间", "")),
                        "type": row.get("限售股类型", ""),
                        "shares": row.get("解禁数量", 0),
                        "ratio": row.get("实际解禁市值占总市值比例", 0),
                    })
        except Exception:
            pass

        # 2. Upcoming expiries
        upcoming: list[dict] = []
        today_str = trade_date.replace("-", "")
        try:
            df = ak.stock_restricted_release_detail_em(date=today_str)
            if df is not None and not df.empty:
                df_stock = df[df["股票代码"] == code]
                for _, row in df_stock.iterrows():
                    upcoming.append({
                        "date": str(row.get("解禁日期", "")),
                        "type": row.get("限售股类型", ""),
                        "shares": row.get("解禁数量", 0),
                        "float_ratio": row.get("占流通股比例", 0),
                    })
        except Exception:
            pass

        # Build combined output
        parts: list[str] = []

        if history:
            parts.append(
                _format_table(
                    history,
                    f"Lockup Expiry History - {code}",
                )
            )
        else:
            parts.append(
                f"# Lockup Expiry History - {code}\nNo historical lockup data found.\n"
            )

        if upcoming:
            parts.append(
                _format_table(
                    upcoming,
                    f"Upcoming Lockup Expiry - {code} (Next {forward_days} Days)",
                )
            )
        else:
            parts.append(
                f"# Upcoming Lockup Expiry - {code}\n"
                f"No upcoming lockup expiries within {forward_days} days.\n"
            )

        return "\n".join(parts)

    except Exception as exc:
        return f"Error fetching lockup expiry for {code}: {exc}"


def get_industry_ranking(top_n: int = 20) -> str:
    """Fetch THS ~90 industry rankings via akshare stock_board_industry_summary_ths.

    Returns top and bottom industries by change percentage.
    """
    try:
        import akshare as ak

        df = ak.stock_board_industry_summary_ths()

        if df is None or df.empty:
            return "# Industry Ranking\nNo industry data available.\n"

        rows: list[dict] = []
        for i, row in df.iterrows():
            rows.append({
                "rank": i + 1,
                "name": row.get("板块", ""),
                "change_pct": row.get("涨跌幅", 0),
                "turnover_yi": row.get("总成交额", 0),
                "net_inflow": (
                    row.get("净流入", 0) if "净流入" in df.columns else ""
                ),
                "up_count": row.get("上涨家数", 0),
                "down_count": row.get("下跌家数", 0),
                "leader": row.get("领涨股", ""),
            })

        total = len(rows)
        display = rows[:top_n]
        # Also include bottom N
        if total > top_n:
            display.extend(
                [
                    {"rank": "...", "name": "...", "change_pct": "...",
                     "turnover_yi": "...", "net_inflow": "...",
                     "up_count": "...", "down_count": "...", "leader": "..."},
                ]
            )
            display.extend(rows[-top_n:])

        title = f"Industry Ranking (Total: {total}, Top/Bottom {top_n})"
        return _format_table(display, title)

    except Exception as exc:
        return f"Error fetching industry ranking: {exc}"


def get_northbound_realtime() -> str:
    """Fetch THS hsgtApi real-time HGT/SGT minute-level flow with local cache.

    Returns minute-by-minute cumulative net buy for Shanghai/Shenzhen Connect.
    Automatically caches closing data to local CSV for history.
    """
    try:
        url = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
        r = requests.get(url, headers=_HSGT_HEADERS, timeout=10)
        d = r.json()

        times = d.get("time", [])
        hgt = d.get("hgt", [])
        sgt = d.get("sgt", [])

        if not times:
            return "# Northbound Realtime Flow\nNo data available (market closed or API error).\n"

        n = len(times)
        rows: list[dict] = []
        for i in range(n):
            hgt_val = hgt[i] if i < len(hgt) else None
            sgt_val = sgt[i] if i < len(sgt) else None
            rows.append({
                "time": times[i],
                "hgt_yi": hgt_val if hgt_val is not None else "",
                "sgt_yi": sgt_val if sgt_val is not None else "",
            })

        # Auto-cache the latest closing snapshot
        try:
            non_null = [r for r in rows if r["hgt_yi"] != "" and r["sgt_yi"] != ""]
            if non_null:
                last = non_null[-1]
                hgt_close = float(last["hgt_yi"])
                sgt_close = float(last["sgt_yi"])
                today_str = _date.today().strftime("%Y-%m-%d")
                _save_northbound_snapshot(today_str, hgt_close, sgt_close)
        except Exception as exc_cache:
            logger.warning("Failed to cache northbound snapshot: %s", exc_cache)

        return _format_table(rows, "Northbound Realtime Flow (HGT/SGT)")

    except Exception as exc:
        return f"Error fetching northbound realtime data: {exc}"


def get_full_market_dragon_tiger(
    trade_date: Optional[str] = None,
) -> str:
    """Fetch Eastmoney datacenter: all stocks on daily dragon tiger board.

    Returns all board triggers for the given date, sorted by net buy amount.
    """
    try:
        if trade_date is None:
            trade_date = _date.today().strftime("%Y-%m-%d")

        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
            "columns": "ALL",
            "filter": (
                f"(TRADE_DATE>='{trade_date}')(TRADE_DATE<='{trade_date}')"
            ),
            "pageNumber": "1",
            "pageSize": "500",
            "sortTypes": "-1",
            "sortColumns": "BILLBOARD_NET_AMT",
            "source": "WEB",
            "client": "WEB",
        }
        headers = {
            "User-Agent": _UA,
            "Referer": "https://data.eastmoney.com/",
        }
        r = requests.get(url, params=params, headers=headers, timeout=15)
        d = r.json()

        if (
            not d.get("success")
            or not d.get("result")
            or not d["result"].get("data")
        ):
            return (
                f"# Full Market Dragon Tiger ({trade_date})\n"
                f"No data (non-trading day or post-market not updated).\n"
            )

        raw_data = d["result"]["data"]
        rows: list[dict] = []
        for row in raw_data:
            net_buy = (row.get("BILLBOARD_NET_AMT") or 0) / 10000
            rows.append({
                "code": row.get("SECURITY_CODE", ""),
                "name": row.get("SECURITY_NAME_ABBR", ""),
                "reason": row.get("EXPLANATION", ""),
                "close": row.get("CLOSE_PRICE") or 0,
                "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
                "net_buy_wan": round(net_buy, 1),
                "buy_wan": round(
                    (row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1
                ),
                "sell_wan": round(
                    (row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1
                ),
                "turnover_pct": round(
                    float(row.get("TURNOVERRATE") or 0), 2
                ),
            })

        return _format_table(
            rows,
            f"Full Market Dragon Tiger ({trade_date}, {len(rows)} records)",
        )

    except Exception as exc:
        return f"Error fetching full market dragon tiger: {exc}"


# ---------------------------------------------------------------------------
# Northbound cache helpers (internal)
# ---------------------------------------------------------------------------


def _northbound_cache_path() -> Path:
    """Return path to local northbound daily CSV cache."""
    p = Path.home() / ".tradingagents" / "cache" / "northbound_daily.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _save_northbound_snapshot(date: str, hgt: float, sgt: float) -> None:
    """Write/update one day's northbound closing data to local CSV."""
    path = _northbound_cache_path()
    rows: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").strip().split("\n")[1:]:
            parts = line.split(",")
            if len(parts) == 3:
                rows[parts[0]] = line
    rows[date] = f"{date},{hgt},{sgt}"
    with open(path, "w", encoding="utf-8") as f:
        f.write("date,hgt,sgt\n")
        for d in sorted(rows.keys()):
            f.write(rows[d] + "\n")
