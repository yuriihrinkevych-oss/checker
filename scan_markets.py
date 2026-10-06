"""Щотижневий скан: країни, ціни, локалізації + рейтинг пріоритету конкурентів.

Запуск: python scan_markets.py
Триває довго (кожна апка × ~60 країн × ~75 мов), тому окремо від щоденного трекера.
"""
import json
from datetime import date
from pathlib import Path

import yaml

from tracker import market, storage
from tracker.ranking import build_ranking, ranking_markdown
from tracker.report import save_report, send_slack

CONFIG = Path(__file__).resolve().parent / "config.yaml"


def _market_path(app_id):
    return storage.DATA / "market" / f"{app_id}.json"


def main(fetch=market.fetch_page, rates=None, today=None, delay=None):
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    mcfg = cfg.get("market_scan", {})
    countries = mcfg.get("countries") or list(market.CURRENCY)
    languages = mcfg.get("languages") or market.LANGUAGES
    delay = delay if delay is not None else tuple(mcfg.get("request_delay", [1, 2]))
    today = today or date.today().isoformat()
    rates = rates if rates is not None else market.load_fx()

    sections, summary_rows, price_rows, prices_by_app = [], [], [], {}
    for app in cfg["apps"]:
        scan = market.scan_app(app["id"], countries, languages, rates, delay=delay, fetch=fetch)
        scan["date"] = today
        p = _market_path(app["id"])
        old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        changes = market.diff_market(old, scan)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(scan, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

        s = market.price_summary(scan)
        prices_by_app[app["id"]] = s["median_min_usd"]
        summary_rows.append((app["name"], s, scan["languages"]))
        for cc, e in scan["countries"].items():
            price_rows.append({"date": today, "app_id": app["id"], "country": cc, **{
                k: e.get(k) for k in ("available", "currency", "min_local", "max_local", "min_usd", "max_usd")}})
        if changes or scan["errors"] or old is None:
            lines = [f"### {app['name']}"]
            if old is None:
                lines.append("Перший скан, збережено базу.")
            lines += [f"- **{t}**: {d}" for t, d in changes]
            if scan["errors"]:
                lines.append(f"- ⚠️ Не вдалося зібрати: {', '.join(scan['errors'][:10])}"
                             + (" …" if len(scan["errors"]) > 10 else ""))
            sections.append("\n".join(lines))

    _append_prices(price_rows)

    md = [f"# Тижневий скан ринків — {today}", ""]
    md.append("## Зміни")
    md.append("\n\n".join(sections) if sections else "Змін у ринках, локалізаціях і цінах не знайдено.")
    md += ["", "## Огляд", "",
           "| Апка | Країн | Локалізацій | Мін. ціна, $ (медіана) | Макс. ціна, $ (медіана) | США |",
           "|---|---|---|---|---|---|"]
    for name, s, _ in summary_rows:
        md.append(f"| {name} | {s['countries_available']} | {s['languages']} | "
                  f"{s['median_min_usd'] or '—'} | {s['median_max_usd'] or '—'} | {s['us'] or '—'} |")
    md.append("")
    md.append("Локалізації по апках:")
    md += [f"- **{name}**: {', '.join(langs) or 'лише базова мова'}" for name, _, langs in summary_rows]

    rows = storage.read_metrics()
    table, calibrated = build_ranking(rows, cfg["apps"], cfg["locales"][0], prices_by_app,
                                      mcfg.get("calibration"))
    md += ["", ranking_markdown(table, calibrated)]
    text = "\n".join(md)
    path = save_report(f"{today}-markets", text)
    send_slack(text)
    print(text)
    print(f"\nЗвіт: {path}")


def _append_prices(rows):
    import csv
    p = storage.DATA / "prices.csv"
    cols = ["date", "app_id", "country", "available", "currency",
            "min_local", "max_local", "min_usd", "max_usd"]
    new = not p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if new:
            w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
