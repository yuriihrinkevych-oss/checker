"""Формування звіту: markdown-файл у reports/ і повідомлення в Slack."""
import os
from pathlib import Path

import requests

REPORTS = Path(__file__).resolve().parent.parent / "reports"
SLACK_LIMIT = 35000


def build_markdown(date, events, baseline_count, errors):
    lines = [f"# Competitor tracker — {date}", ""]
    if baseline_count:
        lines.append(f"Перший запуск для {baseline_count} апок/локалей: збережено baseline, зміни з'являться з наступного дня.\n")
    if not events:
        lines.append("Змін не знайдено.")
    # Групуємо: та сама зміна в кількох ринках = один рядок зі списком ринків
    grouped = {}
    for e in events:
        if e["type"] == "velocity":
            v = e["velocity"]
            key = (e["app_name"], "velocity", v["today_delta"], v["baseline"])
        elif e["type"] == "removed":
            key = (e["app_name"], "removed")
        else:
            c = e["change"]
            key = (e["app_name"], "change", c["field"], c["detail"])
        g = grouped.setdefault(key, {"event": e, "locales": []})
        g["locales"].append(f"{e['country']}-{e['lang']}")

    by_app = {}
    for key, g in grouped.items():
        by_app.setdefault(key[0], []).append(g)
    for app_name, items in by_app.items():
        lines.append(f"## {app_name}")
        for g in items:
            e, loc = g["event"], ", ".join(g["locales"])
            if e["type"] == "velocity":
                v = e["velocity"]
                lines.append(f"- 📈 **Сплеск рейтингів** [{loc}]: +{v['today_delta']} за добу "
                             f"(звично ~{v['baseline']}/день, {v['ratio']}). Перевір, що вони змінили за останні 2 тижні.")
            elif e["type"] == "removed":
                lines.append(f"- ❗ **Сторінку не знайдено** [{loc}]: знято з Google Play або змінили package.")
            else:
                c = e["change"]
                multiline = "\n" in c["detail"]
                inline = "" if multiline else c["detail"]
                lines.append(f"- **{c['label']}** [{loc}]: {inline}")
                if multiline:
                    lines.append("```diff")
                    lines.append(c["detail"])
                    lines.append("```")
        lines.append("")
    if errors:
        lines.append("## Помилки збору")
        lines += [f"- {e}" for e in errors]
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
    text = markdown.replace("**", "*")  # Slack mrkdwn використовує одинарні зірочки
    if len(text) > SLACK_LIMIT:
        text = text[:SLACK_LIMIT] + "\n…звіт обрізано, повна версія в reports/"
    r = requests.post(url, json={"text": text}, timeout=30)
    r.raise_for_status()
    return True
