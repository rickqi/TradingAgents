#!/usr/bin/env python3
"""Test data source connectivity for Chinese A-share / HK stocks.

Validates that Tencent, Sina, and EastMoney APIs are reachable and
returning valid data. Useful for debugging vendor issues.

Usage:
    python scripts/test_datasource.py           # test all sources
    python scripts/test_datasource.py --kline    # test K-line only
    python scripts/test_datasource.py --quote    # test real-time quotes only
"""
import argparse
import json
import time

import requests


# ---------------------------------------------------------------------------
# Test: Sina real-time quotes
# ---------------------------------------------------------------------------

def test_sina_quotes():
    """Test Sina real-time quote API."""
    print("=" * 60)
    print("Sina Real-time Quotes")
    print("=" * 60)

    stocks = [
        ("sz300308", "中际旭创"),
        ("sh600183", "生益科技"),
        ("sz002371", "北方华创"),
        ("hk02149", "贝克微"),
    ]
    for sym, name in stocks:
        url = f"https://hq.sinajs.cn/list={sym}"
        headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        try:
            r = requests.get(url, headers=headers, timeout=10)
            text = r.text.strip()
            if '=""' in text or len(text) < 10:
                print(f"  {sym:12s} {name}: NO DATA")
            else:
                parts = text.split('="')
                if len(parts) >= 2:
                    fields = parts[1].rstrip('";').split(",")
                    if len(fields) > 3:
                        print(f"  {sym:12s} {name}: open={fields[1]} last={fields[3]} vol={fields[8]}")
                    else:
                        print(f"  {sym:12s} {name}: {len(fields)} fields")
                else:
                    print(f"  {sym:12s} {name}: unexpected: {text[:60]}")
        except Exception as e:
            print(f"  {sym:12s} {name}: ERROR - {e}")
        time.sleep(0.3)


# ---------------------------------------------------------------------------
# Test: Tencent K-line
# ---------------------------------------------------------------------------

def test_tencent_kline():
    """Test Tencent (QQ Finance) daily K-line API."""
    print("\n" + "=" * 60)
    print("Tencent K-line (A-share)")
    print("=" * 60)

    for sym, name in [("sz300308", "中际旭创"), ("sh600183", "生益科技"), ("sz002371", "北方华创")]:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,30,qfq"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            r = requests.get(url, headers=headers, timeout=10)
            data = r.json()
            d = data.get("data", {})
            if isinstance(d, dict):
                stock_data = d.get(sym, {})
                klines = stock_data.get("qfqday", stock_data.get("day", []))
            else:
                klines = []
            if klines:
                print(f"  {name}: {len(klines)} bars, last={klines[-1]}")
            else:
                print(f"  {name}: no data")
        except Exception as e:
            print(f"  {name}: ERROR - {e}")
        time.sleep(0.3)

    # HK stock
    print(f"\n  --- HK ---")
    sym = "r02149"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={sym},day,,,30,qfq"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()
        klines = data.get("data", {}).get(sym, {}).get("qfqday", data.get("data", {}).get(sym, {}).get("day", []))
        if klines:
            print(f"  贝克微: {len(klines)} bars, last={klines[-1]}")
        else:
            print(f"  贝克微: no data")
    except Exception as e:
        print(f"  贝克微: ERROR - {e}")


# ---------------------------------------------------------------------------
# Test: EastMoney K-line
# ---------------------------------------------------------------------------

def test_eastmoney_kline():
    """Test EastMoney historical K-line API."""
    print("\n" + "=" * 60)
    print("EastMoney K-line")
    print("=" * 60)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }

    # A-share
    for secid, name in [("0.300308", "中际旭创"), ("1.600183", "生益科技"), ("0.002371", "北方华创")]:
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101", "fqt": "1",
            "beg": "20260401", "end": "20260503",
        }
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            d = r.json()
            klines = d.get("data", {}).get("klines", [])
            if klines:
                print(f"  {name}: {len(klines)} klines, last={klines[-1]}")
            else:
                print(f"  {name}: no klines (rc={d.get('rc')})")
        except Exception as e:
            print(f"  {name}: ERROR - {e}")
        time.sleep(1)

    # HK stock
    print(f"\n  --- HK ---")
    params = {
        "secid": "116.02149",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101", "fqt": "1",
        "beg": "20260401", "end": "20260503",
    }
    try:
        r = requests.get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                         params=params, headers=headers, timeout=15)
        d = r.json()
        klines = d.get("data", {}).get("klines", [])
        print(f"  贝克微: {len(klines)} klines")
        for k in klines[-2:]:
            print(f"    {k}")
    except Exception as e:
        print(f"  贝克微: ERROR - {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Test A-share data source connectivity")
    parser.add_argument("--quote", action="store_true", help="Test real-time quotes only")
    parser.add_argument("--kline", action="store_true", help="Test K-line only")
    args = parser.parse_args()

    if args.quote:
        test_sina_quotes()
    elif args.kline:
        test_tencent_kline()
        test_eastmoney_kline()
    else:
        test_sina_quotes()
        test_tencent_kline()
        test_eastmoney_kline()
        print("\nAll data source tests completed.")


if __name__ == "__main__":
    main()
