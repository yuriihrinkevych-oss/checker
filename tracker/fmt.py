"""Людськочитабельне форматування: країни, мови, числа, конвертація в Slack."""
import re

from babel import Locale

_UK = Locale("uk")


def flag(cc):
    cc = cc.upper()
    if len(cc) != 2 or not cc.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in cc)


def country(cc):
    name = _UK.territories.get(cc.upper(), cc.upper())
    return f"{flag(cc)} {name}".strip()


def language(code):
    c = code.replace("-", "_")
    c = {"iw": "he", "no": "nb"}.get(c, c)
    try:
        return Locale.parse(c).get_display_name("uk")
    except Exception:
        return code


def countries(codes, limit=10):
    codes = sorted(codes)
    shown = ", ".join(country(c) for c in codes[:limit])
    return shown + (f" і ще {len(codes) - limit}" if len(codes) > limit else "")


def languages(codes, limit=10):
    codes = sorted(codes)
    shown = ", ".join(language(c) for c in codes[:limit])
    return shown + (f" і ще {len(codes) - limit}" if len(codes) > limit else "")


def locales(locs, all_locs):
    """[('us','en'), ...] -> 'усі ринки' або '🇺🇸 🇧🇷'."""
    if set(locs) == set(all_locs):
        return "усі ринки"
    return " ".join(flag(c) or c for c, _ in locs)


def num(n):
    if n is None:
        return "—"
    a = abs(n)
    for size, unit in ((1e9, "млрд"), (1e6, "млн"), (1e3, "тис.")):
        if a >= size:
            v = f"{n / size:.1f}".replace(".0", "").replace(".", ",")
            return f"{v} {unit}"
    return f"{n:.0f}"


def signed(n, base=None):
    if n is None:
        return "—"
    s = ("+" if n >= 0 else "−") + num(abs(n))
    if base:
        s += " (" + f"{n / base:+.1%}".replace(".", ",") + ")"
    return s


def countries_in(n):
    """Місцевий відмінок: в 1 країні, в 2 країнах, в 5 країнах."""
    return f"{n} країні" if n % 10 == 1 and n % 100 != 11 else f"{n} країнах"


def pct(x):
    return f"{x:+.0%}".replace("-", "−")


def money(x):
    """2790.9 -> '2 790,90', 12000 -> '12 000'."""
    if x is None:
        return "—"
    s = f"{x:,.2f}" if x % 1 else f"{x:,.0f}"
    return s.replace(",", "\u00a0").replace(".", ",")


def clip(text, n=140):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


# ---------- Slack ----------

def _table_to_mono(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows
             if not re.fullmatch(r"\|?[\s\-:|]+\|?", r.strip())]
    widths = [max(len(r[i]) for r in cells if i < len(r)) for i in range(len(cells[0]))]
    out = ["  ".join(c.ljust(widths[i]) for i, c in enumerate(r)) for r in cells]
    return ["```"] + out + ["```"]


def to_slack(md):
    """Slack mrkdwn не вміє таблиць, заголовків і **жирного**. Конвертуємо."""
    out, table = [], []
    for line in md.splitlines() + [""]:
        if line.lstrip().startswith("|"):
            table.append(line)
            continue
        if table:
            out += _table_to_mono(table)
            table = []
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            line = f"*{m.group(2)}*"
        line = re.sub(r"\*\*(.+?)\*\*", r"*\1*", line)
        line = re.sub(r"^(\s*)- ", r"\1• ", line)
        out.append(line)
    return "\n".join(out).strip()
