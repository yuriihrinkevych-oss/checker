"""Порівняння двох snapshot-ів і пошук аномалій у рості."""
import difflib
from statistics import median

from .collect import TRACKED_FIELDS

MAX_DIFF_LINES = 30


def _text_diff(old, new):
    lines = list(difflib.unified_diff(
        (old or "").splitlines(), (new or "").splitlines(), lineterm="", n=0))
    body = [l for l in lines[2:] if not l.startswith("@@")]  # без заголовків
    if len(body) > MAX_DIFF_LINES:
        body = body[:MAX_DIFF_LINES] + [f"... ще {len(body) - MAX_DIFF_LINES} рядків"]
    return "\n".join(body)


def _list_diff(old, new):
    old, new = old or [], new or []
    added = [x for x in new if x not in old]
    removed = [x for x in old if x not in new]
    parts = []
    if added:
        parts.append(f"нових: {len(added)}")
    if removed:
        parts.append(f"прибрано: {len(removed)}")
    if not added and not removed and old != new:
        parts.append("змінено порядок")
    parts.append(f"було {len(old)} → стало {len(new)}")
    return ", ".join(parts), added


def diff_snapshots(old, new):
    """Повертає список змін. old=None означає перший запуск (baseline, змін нема)."""
    if old is None or new is None:
        return []
    changes = []
    for field, label in TRACKED_FIELDS.items():
        a, b = old.get(field), new.get(field)
        if a == b:
            continue
        change = {"field": field, "label": label, "old": a, "new": b}
        if field == "description":
            change["detail"] = _text_diff(a, b)
            change["old"] = change["new"] = None  # повний текст не тягнемо в лог
        elif field == "screenshots":
            change["detail"], change["added_urls"] = _list_diff(a, b)
            change["old"] = change["new"] = None
        elif field in ("icon", "headerImage", "video"):
            change["detail"] = "оновлено"
        else:
            change["detail"] = f"{a!r} → {b!r}"
        changes.append(change)
    return changes


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def velocity_alert(history, today_ratings, multiplier, min_delta, lookback):
    """history: список рядків metrics.csv для однієї апки/локалі, відсортований за датою,
    БЕЗ сьогоднішнього дня. Повертає опис алерту або None.

    Логіка: приріст рейтингів сьогодні vs медіана щоденного приросту за lookback днів.
    Медіана, а не середнє, щоб один викид не ламав базу."""
    values = [_num(r.get("ratings")) for r in history]
    values = [v for v in values if v is not None]
    today = _num(today_ratings)
    if today is None or len(values) < 3:
        return None  # замало історії
    deltas = [b - a for a, b in zip(values, values[1:])][-lookback:]
    today_delta = today - values[-1]
    base = median(deltas) if deltas else 0
    if today_delta < min_delta:
        return None
    if base <= 0 or today_delta >= base * multiplier:
        ratio = f"x{today_delta / base:.1f}" if base > 0 else "з нуля"
        return {"today_delta": int(today_delta), "baseline": round(base, 1), "ratio": ratio}
    return None
