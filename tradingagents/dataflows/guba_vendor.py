"""East Money (东方财富) social sentiment data for Chinese A-share stocks.

Provides structured sentiment indicators from East Money's stock comment system,
including user attention index, participation desire, composite score, and
institutional participation — all via akshare.

Replaces Reddit/StockTwits for A-share tickers (which are GFW-blocked and
contain no relevant content for Chinese stock codes anyway).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import akshare as ak
import pandas as pd

from .akshare_vendor import _normalize_ticker_to_code

logger = logging.getLogger(__name__)


def fetch_guba_sentiment(ticker: str, days: int = 30) -> str:
    """Fetch comprehensive social sentiment for a Chinese A-share.

    Returns a formatted plaintext block (same pattern as fetch_reddit_posts /
    fetch_stocktwits_messages).

    Gathers:
    1. Current snapshot from stock_comment_em (综合得分, 关注指数, 机构参与度, 排名变化)
    2. Recent trend from stock_comment_detail_scrd_desire_em (参与意愿 + 5日均线 + 变化)
    3. Score trend from stock_comment_detail_zhpj_lspf_em (综合评分时间序列)
    4. Institutional trend from stock_comment_detail_zlkp_jgcyd_em (机构参与度时间序列)

    Returns formatted string ready for prompt injection. Degrades gracefully
    on any error — never raises exceptions.
    """
    ticker = str(ticker).strip()
    try:
        code = _normalize_ticker_to_code(ticker)
    except ValueError as exc:
        return f"<guba sentiment unavailable: cannot parse ticker '{ticker}': {exc}>"

    header = (
        f"# 东方财富社交情绪指标 — East Money Sentiment for {ticker.upper()}\n"
        f"# Fetched: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )

    sections: list[str] = []

    # ------------------------------------------------------------------
    # 1. Current snapshot from stock_comment_em (千股千评)
    # ------------------------------------------------------------------
    try:
        df_all = ak.stock_comment_em()
        time.sleep(0.5)
    except Exception as exc:
        logger.warning("guba_vendor: stock_comment_em failed for %s: %s", ticker, exc)
        df_all = pd.DataFrame()

    if df_all is not None and not df_all.empty:
        code_col = None
        for col_name in ("股票代码", "代码", "code"):
            if col_name in df_all.columns:
                code_col = col_name
                break

        if code_col is not None:
            df_all["_norm"] = df_all[code_col].astype(str).str.strip()
            matched = df_all[df_all["_norm"] == code]

            if not matched.empty:
                row = matched.iloc[0]

                def _gv(possible: list[str]) -> str:
                    for name in possible:
                        val = row.get(name)
                        if val is not None and not (isinstance(val, float) and pd.isna(val)):
                            return str(val)
                    return "N/A"

                name = _gv(["股票简称", "名称", "name"])
                composite = _gv(["综合评分", "综合得分", "score"])
                attention = _gv(["关注指数", "用户关注指数"])
                institutional = _gv(["机构参与度"])
                rank_change = _gv(["排名变化"])

                lines = [
                    f"股票: {name} ({ticker.upper()})",
                    f"综合评分 (Composite Score): {composite}",
                    f"关注指数 (Attention Index): {attention}",
                    f"机构参与度 (Institutional Participation): {institutional}",
                    f"排名变化 (Rank Change): {rank_change}",
                ]
                sections.append("## 千股千评快照 (Current Snapshot)\n" + "\n".join(lines))

    if not sections:
        sections.append(
            "## 千股千评快照 (Current Snapshot)\n<no snapshot data available>"
        )

    # ------------------------------------------------------------------
    # 2. 参与意愿 — stock_comment_detail_scrd_desire_em
    # ------------------------------------------------------------------
    desire_lines: list[str] = []
    try:
        df_desire = ak.stock_comment_detail_scrd_desire_em(symbol=code)
        time.sleep(0.5)
    except Exception as exc:
        logger.warning("guba_vendor: desire_em failed for %s: %s", ticker, exc)
        df_desire = pd.DataFrame()

    if df_desire is not None and not df_desire.empty:
        df_desire = df_desire.tail(days)
        desire_lines.append(
            f"日期, 参与意愿, 5日平均参与意愿, 参与意愿变化, 5日平均变化"
        )
        for _, r in df_desire.iterrows():
            date_val = str(r.get("交易日期", r.iloc[0] if len(r) > 0 else ""))[:10]
            desire_val = r.get("参与意愿", "N/A")
            avg5 = r.get("5日平均参与意愿", "N/A")
            change = r.get("参与意愿变化", "N/A")
            avg5_change = r.get("5日平均变化", "N/A")
            desire_lines.append(
                f"{date_val}, {desire_val}, {avg5}, {change}, {avg5_change}"
            )

    if desire_lines:
        sections.append(
            "## 参与意愿 (Participation Desire)\n" + "\n".join(desire_lines)
        )
    else:
        sections.append(
            "## 参与意愿 (Participation Desire)\n<no participation desire data available>"
        )

    # ------------------------------------------------------------------
    # 3. 综合评分时间序列 — stock_comment_detail_zhpj_lspf_em
    # ------------------------------------------------------------------
    score_lines: list[str] = []
    try:
        df_score = ak.stock_comment_detail_zhpj_lspf_em(symbol=code)
        time.sleep(0.5)
    except Exception as exc:
        logger.warning("guba_vendor: zhpj_lspf_em failed for %s: %s", ticker, exc)
        df_score = pd.DataFrame()

    if df_score is not None and not df_score.empty:
        df_score = df_score.tail(days)
        score_lines.append("日期, 综合评分")
        for _, r in df_score.iterrows():
            date_val = str(r.get("交易日", r.iloc[0] if len(r) > 0 else ""))[:10]
            score_val = r.get("评分", "N/A")
            score_lines.append(f"{date_val}, {score_val}")

    if score_lines:
        sections.append(
            "## 综合评分趋势 (Composite Score Trend)\n" + "\n".join(score_lines)
        )
    else:
        sections.append(
            "## 综合评分趋势 (Composite Score Trend)\n<no score trend data available>"
        )

    # ------------------------------------------------------------------
    # 4. 机构参与度时间序列 — stock_comment_detail_zlkp_jgcyd_em
    # ------------------------------------------------------------------
    inst_lines: list[str] = []
    try:
        df_inst = ak.stock_comment_detail_zlkp_jgcyd_em(symbol=code)
        time.sleep(0.5)
    except Exception as exc:
        logger.warning("guba_vendor: jgcyd_em failed for %s: %s", ticker, exc)
        df_inst = pd.DataFrame()

    if df_inst is not None and not df_inst.empty:
        df_inst = df_inst.tail(days)
        inst_lines.append("日期, 机构参与度")
        for _, r in df_inst.iterrows():
            date_val = str(r.get("交易日", r.iloc[0] if len(r) > 0 else ""))[:10]
            inst_val = r.get("机构参与度", "N/A")
            inst_lines.append(f"{date_val}, {inst_val}")

    if inst_lines:
        sections.append(
            "## 机构参与度趋势 (Institutional Participation Trend)\n"
            + "\n".join(inst_lines)
        )
    else:
        sections.append(
            "## 机构参与度趋势 (Institutional Participation Trend)\n"
            "<no institutional trend data available>"
        )

    return header + "\n\n".join(sections)
