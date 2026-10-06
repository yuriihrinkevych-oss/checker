"""Одноразово: перерахувати ціни в уже зібраних даних новим парсером (без повторного скану)."""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tracker import market, storage  # noqa: E402

rates = json.loads((storage.DATA / "fx.json").read_text())
fixed = {}
for f in (storage.DATA / "market").glob("*.json"):
    d = json.loads(f.read_text(encoding="utf-8"))
    for cc, e in d["countries"].items():
        lo, hi, cur = market.parse_price_range(e.get("iap"), cc)
        e.update({"min_local": lo, "max_local": hi, "currency": cur,
                  "min_usd": market.to_usd(lo, cur, rates), "max_usd": market.to_usd(hi, cur, rates)})
        fixed[(f.stem, cc)] = e
    d.setdefault("first_seen", market.merge_first_seen(None, d, d["date"]))
    f.write_text(json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

p = storage.DATA / "prices.csv"
rows = list(csv.DictReader(p.open(encoding="utf-8")))
for r in rows:
    e = fixed.get((r["app_id"], r["country"]))
    if e:
        for k in ("currency", "min_local", "max_local", "min_usd", "max_usd"):
            r[k] = e[k]
with p.open("w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"Перераховано {len(fixed)} записів")
