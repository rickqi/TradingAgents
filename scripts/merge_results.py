"""Merge batch_results_A.json + batch_results_B.json + batch_20_results.json into final."""
import json, math, os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TICKER_ORDER = [
    "688041.SH", "688256.SH", "688012.SH", "603986.SH", "688008.SH",
    "300442.SZ", "603019.SH", "688111.SH", "002230.SZ", "002837.SZ",
    "002049.SZ", "688027.SH", "300223.SZ", "301269.SZ", "002747.SZ",
    "688332.SH", "002896.SZ", "688568.SH", "300672.SZ", "300458.SZ",
]


def load_json(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    sources = [
        os.path.join(SCRIPT_DIR, "batch_20_results.json"),
        os.path.join(SCRIPT_DIR, "batch_results_A.json"),
        os.path.join(SCRIPT_DIR, "batch_results_B.json"),
    ]

    # ticker -> best result (prefer non-error)
    merged = {}
    for src in sources:
        for r in load_json(src):
            t = r["ticker"]
            if t not in merged:
                merged[t] = r
            elif merged[t].get("error") and not r.get("error"):
                merged[t] = r  # prefer success over error
            elif not merged[t].get("error") and not r.get("error"):
                # both success — keep the one with more signal fields
                if len(r) > len(merged[t]):
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
