"""Щоденний звіт: спочатку головне, потім деталі по апках, без технічного шуму."""
import os
from pathlib import Path

import requests

from . import fmt

REPORTS = Path(__file__).resolve().parent.parent / "reports"
SLACK_LIMIT = 35000

# Наскільки зміна важлива для рішень (5 = точно подивитись сьогодні).
WEIGHT = {
    "velocity": 5, "removed": 5, "inAppProductPrice": 4, "price": 4, "containsAds": 4,
    "installs": 4, "title": 3, "summary": 3, "developer": 3, "genre": 2, "screenshots": 2,
    "icon": 2, "video": 2, "description": 2, "headerImage": 1, "contentRating": 1, "release": 1,
}
HIGHLIGHT_MIN = 3
RELEASE_FIELDS = {"version", "lastUpdatedOn"}


def _q(v):
    return f"«{fmt.clip(v, 90)}»" if v else "порожньо"


def _describe(field, c):
    """Людське формулювання однієї зміни."""
    old, new = c.get("old"), c.get("new")
    if field == "title":
        return f"Нова назва: {_q(old)} → {_q(new)}"
    if field == "summary":
        return f"Новий short description: {_q(old)} → {_q(new)}"
    if field == "description":
        return f"Оновили повний опис ({c['detail']})"
    if field == "screenshots":
        return f"Скріншоти: {c['detail']}"
    if field == "icon":
        return "Нова іконка"
    if field == "headerImage":
        return "Нова feature graphic"
    if field == "video":
        return "Додали промо-відео" if new and not old else "Прибрали промо-відео" if old and not new else "Нове промо-відео"
    if field == "inAppProductPrice":
        return f"Діапазон цін IAP: {old or '—'} → {new or '—'}"
    if field == "price":
        return f"Ціна апки: {old} → {new}"
    if field == "containsAds":
        return "Увімкнули рекламу в апці" if new else "Прибрали рекламу з апки"
    if field == "installs":
        return f"Новий бакет інсталлів: {new} (було {old})"
    if field == "genre":
        return f"Змінили категорію: {old} → {new}"
    if field == "developer":
        return f"Змінилась назва розробника: {old} → {new}"
    return f"{c.get('label', field)}: {old} → {new}"


def _app_items(events, all_locs, primary):
    """Згортає події однієї апки в пункти звіту з вагою."""
    items, groups, releases, descriptions = [], {}, [], []
    for e in events:
        loc = (e["country"], e["lang"])
        if e["type"] == "velocity":
            groups.setdefault(("velocity", e["velocity"]["today_delta"]), {"e": e, "locs": []})["locs"].append(loc)
        elif e["type"] == "removed":
            groups.setdefault(("removed",), {"e": e, "locs": []})["locs"].append(loc)
        else:
            c = e["change"]
            if c["field"] in RELEASE_FIELDS:
                releases.append((loc, c))
            elif c["field"] == "description":
                descriptions.append((loc, c))
            else:
                key = ("change", c["field"], str(c.get("old")), str(c.get("new")), c.get("detail"))
                groups.setdefault(key, {"e": e, "locs": []})["locs"].append(loc)

    for key, g in groups.items():
        e, where = g["e"], fmt.locales(g["locs"], all_locs)
        if key[0] == "velocity":
            v = e["velocity"]
            text = (f"Сплеск рейтингів: +{fmt.num(v['today_delta'])} за добу при звичних "
                    f"~{fmt.num(v['baseline'])} ({v['ratio']}). Схоже на сплеск інсталлів: "
                    f"перевір, що вони змінили за останні 2 тижні")
            items.append({"w": WEIGHT["velocity"], "text": text, "where": where})
        elif key[0] == "removed":
            items.append({"w": WEIGHT["removed"], "where": where,
                          "text": "Сторінку не знайдено: апку зняли з Google Play або змінили package"})
        else:
            f = e["change"]["field"]
            items.append({"w": WEIGHT.get(f, 1), "text": _describe(f, e["change"]), "where": where})

    if descriptions:
        locs = [l for l, _ in descriptions]
        main = next((c for l, c in descriptions if l == primary), descriptions[0][1])
        details = [f"+ {fmt.clip(x)}" for x in main.get("added", [])[:3]]
        details += [f"− {fmt.clip(x)}" for x in main.get("removed", [])[:3]]
        items.append({"w": WEIGHT["description"], "where": fmt.locales(locs, all_locs),
                      "text": _describe("description", main), "details": details})

    if releases:
        # дата оновлення локалізована в кожному ринку, тому один реліз = один рядок
        version = next((c["new"] for _, c in releases if c["field"] == "version"
                        and c["new"] and "varies" not in str(c["new"]).lower()), None)
        date_ = next((c["new"] for l, c in releases if c["field"] == "lastUpdatedOn" and l == primary),
                     next((c["new"] for _, c in releases if c["field"] == "lastUpdatedOn"), None))
        text = "Випустили оновлення" + (f" {version}" if version else "") + (f" ({date_})" if date_ else "")
        items.append({"w": WEIGHT["release"], "text": text, "where": None})

    return sorted(items, key=lambda i: -i["w"])


def build_markdown(date, events, baseline_count, errors, all_locs=None, app_names=None):
    all_locs = all_locs or sorted({(e["country"], e["lang"]) for e in events})
    primary = all_locs[0] if all_locs else None
    by_app = {}
    for e in events:
        by_app.setdefault(e["app_name"], []).append(e)
    per_app = {name: _app_items(evs, all_locs, primary) for name, evs in by_app.items()}

    lines = [f"# Конкуренти в Google Play — {date}", ""]
    if baseline_count and not events:
        lines.append(f"Перший запуск: збережено стан {baseline_count} сторінок. "
                     "Зміни з'являться з наступного дня, сплески росту — приблизно з п'ятого.")
    elif not events:
        lines.append("Тихий день: змін на сторінках і сплесків росту немає.")
    else:
        spikes = sorted({e["app_name"] for e in events if e["type"] == "velocity"})
        lines.append(f"Зміни в {len(per_app)} з {len(app_names or per_app)} апок"
                     + (f"; сплеск росту: {', '.join(spikes)}." if spikes else "."))

    highlights = [(name, i) for name, items in per_app.items() for i in items if i["w"] >= HIGHLIGHT_MIN]
    highlights.sort(key=lambda x: -x[1]["w"])
    top = highlights[:5]
    if top:
        lines += ["", "## Головне"]
        for name, i in top:
            where = f" ({i['where']})" if i["where"] else ""
            lines.append(f"- **{name}**: {i['text']}{where}")
            lines += [f"  - {d}" for d in i.get("details", [])]

    shown = {id(i) for _, i in top}
    rest = {n: [i for i in items if id(i) not in shown] for n, items in per_app.items()}
    rest = {n: items for n, items in rest.items() if items}
    if rest:
        lines += ["", "## Інші зміни"]
        for name in sorted(rest, key=lambda n: -max(i["w"] for i in rest[n])):
            lines += ["", f"### {name}"]
            for i in rest[name]:
                where = f" — {i['where']}" if i["where"] else ""
                lines.append(f"- {i['text']}{where}")
                lines += [f"  - {d}" for d in i.get("details", [])]

    if app_names and per_app:
        quiet = [n for n in app_names if n not in per_app]
        if quiet:
            lines += ["", f"Без змін: {', '.join(quiet)}."]
    if errors:
        lines += ["", "## Не вдалося зібрати"] + [f"- {e}" for e in errors]
    return "\n".join(lines)


def save_report(date, markdown):
    REPORTS.mkdir(parents=True, exist_ok=True)
    p = REPORTS / f"{date}.md"
    p.write_text(markdown, encoding="utf-8")
    return p


def send_slack(markdown):
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return False
    text = fmt.to_slack(markdown)
    if len(text) > SLACK_LIMIT:
        text = text[:SLACK_LIMIT] + "\n…звіт обрізано, повна версія в reports/"
    r = requests.post(url, json={"text": text}, timeout=30)
    r.raise_for_status()
    return True
