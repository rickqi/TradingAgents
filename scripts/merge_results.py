"""Merge batch_results_*.json group files + batch_20_results.json into final.

Auto-discovers all batch_results_?.json files (A, B, C, D, ...) to support
any --parallel value. For each ticker, keeps the result with the newest date.
"""
import json, math, os, sys, glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "..", "docs", "scripts"))
from stocks_config import STOCKS_ORDER as TICKER_ORDER


def load_json(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    # Auto-discover all batch_results_*.json group files (A, B, C, D, ...)
    # Previously hardcoded A/B only, missing C/D when --parallel 4 was used.
    group_files = sorted(
        glob.glob(os.path.join(SCRIPT_DIR, "batch_results_?.json"))
    )
    sources = [os.path.join(SCRIPT_DIR, "batch_20_results.json")] + group_files

    # ticker -> best result (prefer newer date, then non-error)
    merged = {}
    for src in sources:
        for r in load_json(src):
            t = r["ticker"]
            if t not in merged:
                merged[t] = r
            elif merged[t].get("error") and not r.get("error"):
                merged[t] = r  # prefer success over error
            elif not merged[t].get("error") and not r.get("error"):
                # both success — prefer newer date
                old_date = merged[t].get("date", "")
                new_date = r.get("date", "")
                if new_date > old_date:
                    merged[t] = r
                elif new_date == old_date and len(r) > len(merged[t]):
                    merged[t] = r

    final = []
    for t in TICKER_ORDER:
        if t in merged:
            entry = merged[t]
            # Clean NaN
            pt = entry.get("price_target")
            if isinstance(pt, float) and math.isnan(pt):
                entry["price_target"] = None
            final.append(entry)

    out_path = os.path.join(SCRIPT_DIR, "batch_20_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    ok = sum(1 for r in final if not r.get("error"))
    err = sum(1 for r in final if r.get("error"))
    print(f"Merged: {len(final)} total, {ok} success, {err} errors -> {out_path}")
    print()
    print(f"{'Ticker':<12} {'Name':<8} {'Decision':<14} {'Signals':<30} {'St'}")
    print("-" * 80)
    for r in final:
        status = "OK" if not r.get("error") else "ERR"
        if r.get("error"):
            sig = r["error"][:30]
        else:
            sig = f"ai={r.get('ai_score','?'):>+2d} ta={r.get('trader_action','?'):>+2d} rm={r.get('research_rating','?'):>+2d} tgt={r.get('price_target','-')}"
        print(f"{r['ticker']:<12} {r.get('name',''):<8} {r.get('decision',''):<14} {sig:<30} {status}")


if __name__ == "__main__":
    main()
