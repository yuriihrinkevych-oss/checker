"""Зберігання. Принцип: git = база даних.
- data/snapshots/<app>/<country>-<lang>.json  — останній стан (історія живе в git)
- data/metrics.csv                             — часовий ряд показників
- data/changes.jsonl                           — журнал усіх знайдених змін
"""
import csv
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
METRIC_COLUMNS = ["date", "app_id", "country", "lang",
                  "realInstalls", "minInstalls", "score", "ratings", "reviews"]


def _metrics_csv():
    return DATA / "metrics.csv"


def _changes_log():
    return DATA / "changes.jsonl"


def snapshot_path(app_id, country, lang):
    return DATA / "snapshots" / app_id / f"{country}-{lang}.json"


def load_snapshot(app_id, country, lang):
    p = snapshot_path(app_id, country, lang)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_snapshot(app_id, country, lang, snap):
    p = snapshot_path(app_id, country, lang)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def read_metrics():
    if not _metrics_csv().exists():
        return []
    with _metrics_csv().open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def upsert_metrics(rows):
    """Додає рядки за сьогодні; якщо скрипт запускали двічі за день, перезаписує."""
    keys = {(r["date"], r["app_id"], r["country"], r["lang"]) for r in rows}
    existing = [r for r in read_metrics()
                if (r["date"], r["app_id"], r["country"], r["lang"]) not in keys]
    DATA.mkdir(parents=True, exist_ok=True)
    with _metrics_csv().open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=METRIC_COLUMNS)
        w.writeheader()
        for r in sorted(existing + rows, key=lambda r: (r["app_id"], r["country"], r["lang"], r["date"])):
            w.writerow({k: r.get(k, "") for k in METRIC_COLUMNS})


def log_changes(changes):
    if not changes:
        return
    DATA.mkdir(parents=True, exist_ok=True)
    with _changes_log().open("a", encoding="utf-8") as f:
        for c in changes:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
