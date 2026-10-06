"""Пріоритизація конкурентів: ріст інсталлів і грубий індекс ревенью,
відкалібрований на власній апці."""
from datetime import date, timedelta


def _series(rows, app_id, country, lang):
    pts = {}
    for r in rows:
        if r["app_id"] == app_id and r["country"] == country and r["lang"] == lang:
            try:
                pts[r["date"]] = float(r["realInstalls"])
            except (TypeError, ValueError):
                pass
    return sorted(pts.items())


def _delta(series, days):
    """Приріст за `days` днів: остання точка мінус найближча точка не пізніше дати відліку."""
    if len(series) < 2:
        return None
    last_d, last_v = series[-1]
    cutoff = (date.fromisoformat(last_d) - timedelta(days=days)).isoformat()
    past = [v for d, v in series if d <= cutoff]
    return last_v - past[-1] if past else None


def build_ranking(rows, apps, primary, price_by_app, calibration=None):
    """calibration = {"app_id": ..., "revenue_usd_30d": ...} — реальна виручка власної апки
    за 30 днів. Без неї рейтинг лише за ростом інсталлів."""
    country, lang = primary["country"], primary["lang"]
    table = []
    for a in apps:
        s = _series(rows, a["id"], country, lang)
        table.append({"app": a["name"], "id": a["id"],
                      "installs": s[-1][1] if s else None,
                      "d7": _delta(s, 7), "d30": _delta(s, 30),
                      "price": price_by_app.get(a["id"])})

    factor = None
    if calibration:
        own = next((t for t in table if t["id"] == calibration["app_id"]), None)
        if own and own["d30"] and own["price"]:
            factor = calibration["revenue_usd_30d"] / (own["d30"] * own["price"])
    for t in table:
        t["rev_index"] = (round(t["d30"] * t["price"] * factor)
                          if factor and t["d30"] and t["price"] else None)
    key = "rev_index" if factor else "d30"
    table.sort(key=lambda t: (t[key] is None, -(t[key] or 0), -(t["d7"] or 0)))
    return table, bool(factor)


def ranking_markdown(table, calibrated, history_days=0):
    from . import fmt
    lines = ["## Хто росте", ""]
    has_d7 = any(t["d7"] is not None for t in table)
    if not has_d7:
        lines.append(f"Динаміка з'явиться після 7 днів щоденних даних (зараз: {history_days}). "
                     "Поки що лише масштаб:")
        lines.append("")
    head = "| Апка | Інсталли (оцінка) |"
    sep = "|---|---|"
    if has_d7:
        head += " За 7 днів | За 30 днів |"
        sep += "---|---|"
    if calibrated:
        head += " Ревенью 30д, $ (індекс) |"
        sep += "---|"
    lines += [head, sep]
    for t in table:
        row = f"| {t['app']} | {fmt.num(t['installs'])} |"
        if has_d7:
            row += f" {fmt.signed(t['d7'], t['installs'])} | {fmt.signed(t['d30'], t['installs'])} |"
        if calibrated:
            row += f" {fmt.num(t['rev_index'])} |"
        lines.append(row)
    if has_d7 and not calibrated:
        lines += ["", "Щоб бачити оцінку ревенью, заповни `calibration` у config.yaml "
                      "(реальна виручка власної апки за 30 днів)."]
    elif calibrated:
        lines += ["", "Ревенью: ваша виручка × (їхній приріст інсталлів / ваш) × (їхня ціна / ваша). "
                      "Індекс для порівняння, точність у межах порядку величини."]
    return "\n".join(lines)
