"""Щотижневий скан ринків: доступність по країнах, ціни IAP у локальній валюті і USD,
список локалізацій сторінки."""
import hashlib
import json
import re
import time
import random
from statistics import median

import requests
from google_play_scraper.features.app import parse_dom

from . import storage

PLAY_URL = "https://play.google.com/store/apps/details?id={id}&hl={hl}&gl={gl}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
FX_URL = "https://open.er-api.com/v6/latest/USD"

# Країна -> валюта Google Play. Якщо Play показує ціну в US$, це визначиться з рядка.
CURRENCY = {
    "us": "USD", "ca": "CAD", "mx": "MXN", "br": "BRL", "ar": "ARS", "cl": "CLP",
    "co": "COP", "pe": "PEN", "gb": "GBP", "ie": "EUR", "de": "EUR", "fr": "EUR",
    "es": "EUR", "it": "EUR", "nl": "EUR", "be": "EUR", "at": "EUR", "pt": "EUR",
    "fi": "EUR", "gr": "EUR", "sk": "EUR", "si": "EUR", "ee": "EUR", "lv": "EUR",
    "lt": "EUR", "hr": "EUR", "bg": "EUR", "pl": "PLN", "cz": "CZK", "hu": "HUF",
    "ro": "RON", "se": "SEK", "no": "NOK", "dk": "DKK", "ch": "CHF", "ua": "UAH",
    "tr": "TRY", "il": "ILS", "ae": "AED", "sa": "SAR", "qa": "QAR", "eg": "EGP",
    "ma": "MAD", "za": "ZAR", "ng": "NGN", "ke": "KES", "in": "INR", "pk": "PKR",
    "bd": "BDT", "id": "IDR", "my": "MYR", "th": "THB", "vn": "VND", "ph": "PHP",
    "sg": "SGD", "jp": "JPY", "kr": "KRW", "tw": "TWD", "hk": "HKD", "au": "AUD",
    "nz": "NZD", "kz": "KZT", "rs": "RSD",
}

# Мови сторінок Google Play (параметр hl).
LANGUAGES = [
    "af", "am", "ar", "az", "be", "bg", "bn", "ca", "cs", "da", "de", "el",
    "en-GB", "en-AU", "en-IN", "es", "es-419", "et", "eu", "fa", "fi", "fil",
    "fr", "fr-CA", "gl", "gu", "hi", "hr", "hu", "hy", "id", "is", "it", "iw",
    "ja", "ka", "kk", "km", "kn", "ko", "ky", "lo", "lt", "lv", "mk", "ml", "mn",
    "mr", "ms", "my", "ne", "nl", "no", "pa", "pl", "pt-BR", "pt-PT", "ro", "ru",
    "si", "sk", "sl", "sq", "sr", "sv", "sw", "ta", "te", "th", "tr", "uk", "ur",
    "vi", "zh-CN", "zh-TW", "zh-HK", "zu",
]

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def fetch_page(app_id, hl, gl, retries=3):
    """(статус, дані). 404 від Google Play = апка недоступна в цій країні."""
    url = PLAY_URL.format(id=app_id, hl=hl, gl=gl)
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 404:
                return "unavailable", None
            r.raise_for_status()
            return "ok", parse_dom(r.text, app_id, url)
        except Exception:
            if attempt == retries - 1:
                return "error", None
            time.sleep(5 * (attempt + 1))


def parse_price_range(text, country):
    """'R$14.99 – R$449.99 per item' -> (14.99, 449.99, 'BRL')."""
    if not text:
        return None, None, None
    nums = [float(n.replace(",", "")) for n in NUM.findall(text)]
    if not nums:
        return None, None, None
    cur = "USD" if ("US$" in text or "USD" in text) else CURRENCY.get(country)
    return min(nums), max(nums), cur


def load_fx():
    try:
        r = requests.get(FX_URL, timeout=30)
        r.raise_for_status()
        rates = r.json()["rates"]
        (storage.DATA / "fx.json").write_text(json.dumps(rates), encoding="utf-8")
        return rates
    except Exception:
        p = storage.DATA / "fx.json"  # останній збережений курс як запасний варіант
        return json.loads(p.read_text()) if p.exists() else {}


def to_usd(amount, currency, rates):
    if amount is None or not currency or currency not in rates:
        return None
    return round(amount / rates[currency], 2)


def _listing_key(data):
    if not data:
        return None
    text = f"{data.get('title')}|{data.get('summary')}"
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def scan_app(app_id, countries, languages, rates, delay=(1, 2), fetch=fetch_page):
    result = {"countries": {}, "languages": [], "errors": []}

    for cc in countries:
        status, data = fetch(app_id, "en", cc)
        time.sleep(random.uniform(*delay)) if delay else None
        if status == "error":
            result["errors"].append(f"country {cc}")
            continue
        entry = {"available": status == "ok"}
        if data:
            lo, hi, cur = parse_price_range(data.get("inAppProductPrice"), cc)
            entry.update({"iap": data.get("inAppProductPrice"), "currency": cur,
                          "min_local": lo, "max_local": hi,
                          "min_usd": to_usd(lo, cur, rates), "max_usd": to_usd(hi, cur, rates),
                          "containsAds": data.get("containsAds")})
        result["countries"][cc] = entry

    # Локалізація = текст title+summary у мові відрізняється від англійського.
    _, base = fetch(app_id, "en", "us")
    base_key = _listing_key(base)
    for hl in languages:
        status, data = fetch(app_id, hl, "us")
        time.sleep(random.uniform(*delay)) if delay else None
        if status == "error":
            result["errors"].append(f"lang {hl}")
            continue
        key = _listing_key(data)
        if key and key != base_key:
            result["languages"].append(hl)
    return result


def diff_market(old, new, price_threshold=0.03):
    """Зміни між двома сканами: нові/зниклі ринки та мови, зміни цін у локальній валюті."""
    if not old:
        return []
    out = []
    old_av = {c for c, e in old["countries"].items() if e.get("available")}
    new_av = {c for c, e in new["countries"].items() if e.get("available")}
    scanned_both = set(old["countries"]) & set(new["countries"])
    if added := sorted((new_av - old_av) & scanned_both):
        out.append(("🌍 Нові країни", ", ".join(added)))
    if removed := sorted((old_av - new_av) & scanned_both):
        out.append(("🚫 Зникли з країн", ", ".join(removed)))
    if added := sorted(set(new["languages"]) - set(old["languages"])):
        out.append(("🗣 Нові локалізації", ", ".join(added)))
    if removed := sorted(set(old["languages"]) - set(new["languages"])):
        out.append(("Прибрали локалізації", ", ".join(removed)))
    for cc in sorted(scanned_both):
        a, b = old["countries"][cc], new["countries"][cc]
        for k, label in (("min_local", "мін."), ("max_local", "макс.")):
            x, y = a.get(k), b.get(k)
            if x and y and abs(y - x) / x >= price_threshold:
                out.append((f"💰 Ціна {label} [{cc}]",
                            f"{x:g} → {y:g} {b.get('currency') or ''} ({(y - x) / x:+.0%})"))
        if a.get("containsAds") is not None and a.get("containsAds") != b.get("containsAds"):
            out.append((f"📺 Реклама в апці [{cc}]", f"{a.get('containsAds')} → {b.get('containsAds')}"))
    return out


def price_summary(scan):
    usd_min = [e["min_usd"] for e in scan["countries"].values() if e.get("min_usd")]
    usd_max = [e["max_usd"] for e in scan["countries"].values() if e.get("max_usd")]
    return {
        "countries_available": sum(1 for e in scan["countries"].values() if e.get("available")),
        "languages": len(scan["languages"]),
        "median_min_usd": round(median(usd_min), 2) if usd_min else None,
        "median_max_usd": round(median(usd_max), 2) if usd_max else None,
        "us": scan["countries"].get("us", {}).get("iap"),
    }
