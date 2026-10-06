"""Щоденний запуск: зібрати → порівняти → зберегти → звіт.

Локально:  python run.py
Без Slack: просто не задавай SLACK_WEBHOOK_URL, звіт ляже в reports/<дата>.md
"""
import random
import sys
import time
from datetime import date
from pathlib import Path

import yaml

from tracker import storage
from tracker.collect import fetch
from tracker.diff import diff_snapshots, velocity_alert
from tracker.report import build_markdown, save_report, send_slack

CONFIG = Path(__file__).resolve().parent / "config.yaml"


def main(fetch_fn=fetch, today=None, sleep=True):
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    today = today or date.today().isoformat()
    alerts_cfg = cfg.get("alerts", {})
    delay = cfg.get("request_delay", [2, 4])

    history = storage.read_metrics()
    events, metric_rows, errors = [], [], []
    baseline_count = 0

    for app in cfg["apps"]:
        for loc in cfg["locales"]:
            country, lang = loc["country"], loc["lang"]
            base = {"date": today, "app_id": app["id"], "app_name": app["name"],
                    "group": app.get("group"), "country": country, "lang": lang}
            try:
                new = fetch_fn(app["id"], country, lang)
            except Exception as e:  # одна апка не має валити весь запуск
                errors.append(f"{app['name']} [{country}-{lang}]: {e}")
                continue
            finally:
                if sleep:
                    time.sleep(random.uniform(*delay))

            old = storage.load_snapshot(app["id"], country, lang)
            if new is None:
                if old is not None and not old.get("_removed"):
                    events.append({**base, "type": "removed"})
                    storage.save_snapshot(app["id"], country, lang, {**old, "_removed": True})
                continue
            if old is None:
                baseline_count += 1

            for c in diff_snapshots(old, new):
                events.append({**base, "type": "change", "change": c})

            m = new["metrics"]
            past = sorted((r for r in history
                           if r["app_id"] == app["id"] and r["country"] == country
                           and r["lang"] == lang and r["date"] < today),
                          key=lambda r: r["date"])
            v = velocity_alert(past, m.get("ratings"),
                               alerts_cfg.get("velocity_multiplier", 2.0),
                               alerts_cfg.get("velocity_min_delta", 20),
                               alerts_cfg.get("lookback_days", 7))
            if v:
                events.append({**base, "type": "velocity", "velocity": v})

            metric_rows.append({"date": today, "app_id": app["id"], "country": country,
                                "lang": lang, **{k: m.get(k) for k in storage.METRIC_COLUMNS[4:]}})
            storage.save_snapshot(app["id"], country, lang, new)

    storage.upsert_metrics(metric_rows)
    storage.log_changes(events)
    md = build_markdown(today, events, baseline_count, errors)
    path = save_report(today, md)
    sent = send_slack(md) if events or errors else False
    print(md)
    print(f"\nЗвіт: {path}" + (" | надіслано в Slack" if sent else ""))
    return events, errors


if __name__ == "__main__":
    _, errs = main()
    # якщо впало все, а не окремі апки, позначаємо запуск як невдалий
    sys.exit(1 if errs and not storage.read_metrics() else 0)
