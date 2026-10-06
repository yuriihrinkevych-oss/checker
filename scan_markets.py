"""Щотижневий скан: країни, ціни, мовні версії сторінок + хто росте.

Запуск: python scan_markets.py
Триває 1-2 години (кожна апка × ~60 країн × ~75 мов), тому окремо від щоденного трекера.
"""
import csv
import json
from datetime import date, timedelta
from pathlib import Path

import yaml

from tracker import fmt, market, storage
from tracker.ranking import build_ranking, ranking_markdown
from tracker.report import save_report, send_slack

CONFIG = Path(__file__).resolve().parent / "config.yaml"
WEIGHT = {"country_added": 5, "country_removed": 4, "price": 4, "ads": 4,
          "listing_edited": 4, "lang_added": 3, "lang_removed": 2, "base_changed": 2}


def _market_path(app_id):
    return storage.DATA / "market" / f"{app_id}.json"


def _price_text(changes, limit=6):
    """Зсув меж діапазону більш ніж на 60% — це швидше новий/прибраний тариф, ніж зміна ціни."""
    reprices = [c for c in changes if abs(c["pct"]) <= 0.6]
    sku = [c for c in changes if abs(c["pct"]) > 0.6]
    out = []
    for group, verb in (([c for c in reprices if c["pct"] > 0], "Підняли"),
                        ([c for c in reprices if c["pct"] < 0], "Знизили")):
        if not group:
            continue
        group = sorted(group, key=lambda c: -abs(c["pct"]))
        kinds = {c["kind"] for c in group}
        what = "вхідну ціну" if kinds == {"entry"} else "верхню ціну" if kinds == {"top"} else "ціни"
        n = len({c["country"] for c in group})
        parts = [f"{fmt.country(c['country'])} {fmt.pct(c['pct'])}"
                 + ("" if len(kinds) == 1 else f" ({'вхід' if c['kind'] == 'entry' else 'верх'})")
                 for c in group[:limit]]
        more = f" і ще {len(group) - limit}" if len(group) > limit else ""
        out.append(f"{verb} {what} в {fmt.countries_in(n)}: {', '.join(parts)}{more}")
    if sku:
        by_cc = {}
        for c in sku:
            by_cc.setdefault(c["country"], []).append(c)
        parts = []
        for cc in sorted(by_cc)[:limit]:
            ends = [f"{'найдешевший' if c['kind'] == 'entry' else 'найдорожчий'} "
                    f"{fmt.money(c['old'])} → {fmt.money(c['new'])}"
                    for c in sorted(by_cc[cc], key=lambda c: c["kind"])]
            parts.append(f"{fmt.country(cc)}: {', '.join(ends)} {by_cc[cc][0]['currency'] or ''}".strip())
        out.append(f"Змінили лінійку тарифів в {fmt.countries_in(len(by_cc))} (межі діапазону зсунулись "
                   f"різко, імовірно новий або прибраний план): {'; '.join(parts)}")
    return out


def _change_lines(ch):
    t = ch["type"]
    if t == "country_added":
        return [f"Вийшли на нові ринки: {fmt.countries(ch['countries'])}"]
    if t == "country_removed":
        return [f"Пішли з ринків: {fmt.countries(ch['countries'])}"]
    if t == "lang_added":
        return [f"Нові мовні версії сторінки: {fmt.languages(ch['langs'])}"]
    if t == "lang_removed":
        return [f"Прибрали мовні версії: {fmt.languages(ch['langs'])}"]
    if t == "listing_edited":
        sample = next(((a, b) for _, a, b in ch["samples"] if a != b), None)
        title = f": «{fmt.clip(sample[0], 50)}» → «{fmt.clip(sample[1], 50)}»" if sample else ""
        return [f"Вручну оновили сторінку — {fmt.languages(ch['langs'])}{title}. "
                "Англійська версія не змінювалась, тож це ручна робота над ринком, а не автопереклад"]
    if t == "base_changed":
        return [f"Змінили англійську сторінку: «{fmt.clip(ch['old'], 60)}» → «{fmt.clip(ch['new'], 60)}»"]
    if t == "price":
        return _price_text(ch["changes"])
    if t == "ads":
        verb = "Увімкнули" if ch["now"] else "Вимкнули"
        return [f"{verb} рекламу в апці: {fmt.countries(ch['countries'])}"]
    return []


def _recent(first_seen, today, days=90):
    cutoff = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    return [k for k, v in first_seen.items() if v != "baseline" and v >= cutoff]


def main(fetch=market.fetch_page, rates=None, today=None, delay=None):
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    mcfg = cfg.get("market_scan", {})
    countries = mcfg.get("countries") or list(market.CURRENCY)
    languages = mcfg.get("languages") or market.LANGUAGES
    delay = delay if delay is not None else tuple(mcfg.get("request_delay", [1, 2]))
    today = today or date.today().isoformat()
    rates = rates if rates is not None else market.load_fx()

    results, price_rows, prices_by_app, first_scan, errors = [], [], {}, [], []
    for app in cfg["apps"]:
        scan = market.scan_app(app["id"], countries, languages, rates, delay=delay, fetch=fetch)
        scan["date"] = today
        p = _market_path(app["id"])
        old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        changes = market.diff_market(old, scan)
        scan["first_seen"] = market.merge_first_seen(old, scan, today)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(scan, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

        prices_by_app[app["id"]] = market.price_summary(scan)["median_min_usd"]
        for cc, e in scan["countries"].items():
            price_rows.append({"date": today, "app_id": app["id"], "country": cc, **{
                k: e.get(k) for k in ("available", "currency", "min_local", "max_local", "min_usd", "max_usd")}})
        if old is None:
            first_scan.append(app["name"])
        if scan["errors"]:
            errors.append(f"{app['name']}: не зібрано {len(scan['errors'])} запитів "
                          f"({', '.join(scan['errors'][:5])}{' …' if len(scan['errors']) > 5 else ''})")
        results.append((app, scan, changes))

    _append_prices(price_rows)
    _log_market_changes(today, results)

    md = [f"# Ринки та ціни конкурентів — {today}", ""]
    highlights = [(app["name"], WEIGHT.get(ch["type"], 1), line)
                  for app, _, changes in results for ch in changes for line in _change_lines(ch)]
    highlights.sort(key=lambda h: -h[1])
    top = [h for h in highlights if h[1] >= 3][:5]
    if top:
        md.append("## Головне")
        md += [f"- **{n}**: {line}" for n, _, line in top]
    elif highlights:
        md.append("Лише дрібні зміни, деталі нижче.")
    elif first_scan and len(first_scan) == len(results):
        md.append("Перший скан: збережено базу. Зміни ринків, мов і цін з'являться з наступного тижня.")
    else:
        md.append("Тихий тиждень: нових ринків, ручних правок локалізацій і змін цін немає.")

    shown = {(n, line) for n, _, line in top}
    rest = [(app["name"], [line for ch in sorted(changes, key=lambda c: -WEIGHT.get(c["type"], 1))
                           for line in _change_lines(ch) if (app["name"], line) not in shown])
            for app, _, changes in results]
    rest = [(n, lines) for n, lines in rest if lines]
    if rest:
        md += ["", "## Інші зміни"]
        for name, lines in rest:
            md += ["", f"### {name}"] + [f"- {line}" for line in lines]

    md += ["", "## Присутність", "",
           "| Апка | Країн | Нові країни, 90 днів | Мовних версій* | Ручні правки мов, 90 днів | Реклама |",
           "|---|---|---|---|---|---|"]
    for app, scan, _ in results:
        fs = scan["first_seen"]
        new_c = _recent(fs["countries"], today)
        ads = {e.get("containsAds") for e in scan["countries"].values()} - {None}
        ads_txt = "так" if ads == {True} else "ні" if ads == {False} else "частково"
        edited = _manual_edits(app["id"], today)
        md.append(f"| {app['name']} | {sum(e.get('available', False) for e in scan['countries'].values())} | "
                  f"{' '.join(fmt.flag(c) for c in new_c) or '—'} | {len(scan['languages'])} | "
                  f"{len(edited) or '—'} | {ads_txt} |")
    md += ["", "*Включно з автоперекладом Google, тому саме число мало що каже. "
               "Сигнал — нові мови та ручні правки, коли текст мови змінюється без зміни англійського."]

    rows = storage.read_metrics()
    history_days = len({r["date"] for r in rows})
    table, calibrated = build_ranking(rows, cfg["apps"], cfg["locales"][0], prices_by_app,
                                      mcfg.get("calibration"))
    md += ["", ranking_markdown(table, calibrated, history_days)]
    if errors:
        md += ["", "## Не вдалося зібрати"] + [f"- {e}" for e in errors]
    md += ["", "Ціни по всіх країнах: `data/prices.csv`."]

    text = "\n".join(md)
    path = save_report(f"{today}-markets", text)
    send_slack(text)
    print(text)
    print(f"\nЗвіт: {path}")


def _log_market_changes(today, results):
    p = storage.DATA / "market_changes.jsonl"
    with p.open("a", encoding="utf-8") as f:
        for app, _, changes in results:
            for ch in changes:
                f.write(json.dumps({"date": today, "app_id": app["id"], **ch}, ensure_ascii=False) + "\n")


def _manual_edits(app_id, today, days=90):
    p = storage.DATA / "market_changes.jsonl"
    if not p.exists():
        return set()
    cutoff = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    langs = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["app_id"] == app_id and r["type"] == "listing_edited" and r["date"] >= cutoff:
            langs.update(r["langs"])
    return langs


def _append_prices(rows):
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
