"""Порівняння двох snapshot-ів і пошук аномалій у рості."""
import difflib
from statistics import median

from .collect import TRACKED_FIELDS



def _lines(text):
    return [l.strip() for l in (text or "").splitlines() if l.strip()]


def _text_diff(old, new):
    """Які рядки опису додали і які прибрали (без шуму unified diff)."""
    a, b = _lines(old), _lines(new)
    added = [l for l in b if l not in a]
    removed = [l for l in a if l not in b]
    return added, removed


def _list_diff(old, new):
    old, new = old or [], new or []
    added = [x for x in new if x not in old]
    removed = [x for x in old if x not in new]
    if not added and not removed:
        return "змінили порядок", added
    if len(old) == len(new) and len(added) == len(removed):
        return f"замінили {len(added)} з {len(new)}", added
    parts = [f"було {len(old)}, стало {len(new)}"]
    if added:
        parts.append(f"нових {len(added)}")
    if removed:
        parts.append(f"прибрали {len(removed)}")
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
            change["added"], change["removed"] = _text_diff(a, b)
            change["detail"] = f"+{len(change['added'])} / −{len(change['removed'])} рядків"
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
        r = today_delta / base if base > 0 else None
        ratio = ("з нуля" if r is None else f"×{r:.0f}" if r >= 10
                 else f"×{r:.1f}".replace(".", ","))
        return {"today_delta": int(today_delta), "baseline": round(base, 1), "ratio": ratio}
    return None
