"""Збирає viewer.html: один файл з усіма даними всередині.
Відкривається подвійним кліком, без сервера. Картинки тягнуться напряму з Google Play.

Запуск: python build_viewer.py
"""
import csv
import json
from datetime import date
from pathlib import Path

import yaml

from tracker import fmt, storage
from tracker.market import COUNTRY_LANG, CURRENCY, LANGUAGES
from tracker.report import _describe

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "viewer" / "template.html"
OUT = ROOT / "viewer.html"


def _read_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _jsonl(p):
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def build():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    locales = cfg["locales"]
    calib = (cfg.get("market_scan") or {}).get("calibration") or {}
    own_id = calib.get("app_id") or cfg["apps"][0]["id"]

    labels, pages, own_screens, prices, first_seen, metrics = {}, {}, {}, {}, {}, {}
    daily_lang = {}
    for loc in locales:
        daily_lang.setdefault(loc["country"], loc["lang"])
    all_cc = list(dict.fromkeys(list(daily_lang) + list(CURRENCY)))
    for cc in all_cc:
        labels[f"cc:{cc}"] = f"{fmt.country(cc)}, {fmt.language(daily_lang.get(cc) or COUNTRY_LANG.get(cc, 'en'))}"
    for hl in ["en"] + LANGUAGES:
        labels[f"lang:{hl}"] = fmt.language(hl)

    country_names = {}
    for app in cfg["apps"]:
        aid = app["id"]
        pages[aid] = {}
        base = storage.DATA / "snapshots" / aid
        # Щотижневі сторінки країн, поверх них щоденні (свіжіші) для основних ринків
        for f in sorted((base / "country").glob("*.json")) if (base / "country").exists() else []:
            snap = _read_json(f)
            if snap:
                pages[aid][f"cc:{f.stem}"] = snap
        for cc, lang in daily_lang.items():
            snap = _read_json(base / f"{cc}-{lang}.json")
            if snap:
                pages[aid][f"cc:{cc}"] = snap
        for f in sorted((base / "lang").glob("*.json")) if (base / "lang").exists() else []:
            snap = _read_json(f)
            if snap:
                pages[aid][f"lang:{f.stem}"] = snap

        m = _read_json(storage.DATA / "market" / f"{aid}.json") or {}
        own_screens[aid] = sorted(hl for hl, l in (m.get("listings") or {}).items()
                                  if l and l.get("own_screens"))
        prices[aid] = {cc: {k: e.get(k) for k in ("available", "iap", "currency", "min_local",
                                                    "max_local", "min_usd", "max_usd", "containsAds")}
                       for cc, e in (m.get("countries") or {}).items()}
        for cc in prices[aid]:
            country_names.setdefault(cc, fmt.country(cc))
        first_seen[aid] = m.get("first_seen") or {}

    primary = locales[0]
    for r in storage.read_metrics():
        if r["country"] == primary["country"] and r["lang"] == primary["lang"]:
            metrics.setdefault(r["app_id"], []).append(
                [r["date"], _f(r.get("realInstalls")), _f(r.get("ratings")), _f(r.get("score"))])
    for v in metrics.values():
        v.sort()

    changes = _changes(cfg, locales)

    data = {
        "generated": date.today().isoformat(),
        "ownId": own_id,
        "apps": [{"id": a["id"], "name": a["name"]} for a in cfg["apps"]],
        "countries": sorted((f"cc:{cc}" for cc in all_cc),
                            key=lambda k: labels[k].split(" ", 1)[-1]),
        "daily": [f"cc:{cc}" for cc in daily_lang],
        "labels": labels,
        "pages": pages,
        "ownScreens": own_screens,
        "prices": prices,
        "countryNames": country_names,
        "firstSeen": first_seen,
        "metrics": metrics,
        "changes": changes,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    OUT.write_text(html, encoding="utf-8")
    return OUT


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _changes(cfg, locales):
    """Події з обох журналів, перекладені людською мовою, одна подія = один рядок."""
    import scan_markets
    all_locs = [(l["country"], l["lang"]) for l in locales]
    out, seen = [], set()
    groups = {}
    for e in _jsonl(storage.DATA / "changes.jsonl"):
        if e.get("type") == "change":
            c = e["change"]
            if c["field"] in ("lastUpdatedOn",):
                continue
            text = _describe(c["field"], c)
        elif e.get("type") == "velocity":
            v = e["velocity"]
            text = f"Сплеск рейтингів: +{fmt.num(v['today_delta'])} за добу при звичних ~{fmt.num(v['baseline'])}"
        elif e.get("type") == "removed":
            text = "Сторінку прибрали з Google Play"
        else:
            continue
        key = (e["date"], e["app_id"], text)
        groups.setdefault(key, []).append((e["country"], e["lang"]))
    for (d, aid, text), locs in groups.items():
        out.append({"date": d, "app": aid, "kind": "page", "text": text,
                    "where": fmt.locales(locs, all_locs)})
    for e in _jsonl(storage.DATA / "market_changes.jsonl"):
        for line in scan_markets._change_lines(e):
            key = (e["date"], e["app_id"], line)
            if key not in seen:
                seen.add(key)
                out.append({"date": e["date"], "app": e["app_id"], "kind": "market", "text": line, "where": ""})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


if __name__ == "__main__":
    print(f"Готово: {build()}")
