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

# Основна мова Google Play в країні: так сторінку бачать місцеві користувачі.
COUNTRY_LANG = {
    "us": "en", "ca": "en", "mx": "es-419", "br": "pt-BR", "ar": "es-419", "cl": "es-419",
    "co": "es-419", "pe": "es-419", "gb": "en-GB", "ie": "en-GB", "de": "de", "fr": "fr",
    "es": "es", "it": "it", "nl": "nl", "be": "nl", "at": "de", "pt": "pt-PT", "fi": "fi",
    "gr": "el", "sk": "sk", "si": "sl", "ee": "et", "lv": "lv", "lt": "lt", "hr": "hr",
    "bg": "bg", "pl": "pl", "cz": "cs", "hu": "hu", "ro": "ro", "se": "sv", "no": "no",
    "dk": "da", "ch": "de", "ua": "uk", "tr": "tr", "il": "iw", "ae": "ar", "sa": "ar",
    "qa": "ar", "eg": "ar", "ma": "ar", "za": "en", "ng": "en", "ke": "en", "in": "en-IN",
    "pk": "en", "bd": "bn", "id": "id", "my": "ms", "th": "th", "vn": "vi", "ph": "en",
    "sg": "en", "jp": "ja", "kr": "ko", "tw": "zh-TW", "hk": "zh-HK", "au": "en-AU",
    "nz": "en", "kz": "ru", "rs": "sr",
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

RANGE_SPLIT = re.compile(r"\s[-–]\s")
NUMBER = re.compile(r"\d(?:[\d.,\s\u00a0\u202f]*\d)?")


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


def parse_amount(token):
    """Число в будь-якому локальному форматі Google Play:
    '2 299,99' -> 2299.99, 'Rp 1.490.000' -> 1490000, '9,400.00' -> 9400.0, '€ 2,99' -> 2.99."""
    t = re.sub(r"[\s\u00a0\u202f]", "", token)
    if "." in t and "," in t:
        dec = "." if t.rfind(".") > t.rfind(",") else ","
        t = t.replace("," if dec == "." else ".", "").replace(dec, ".")
    elif "." in t or "," in t:
        parts = t.split("." if "." in t else ",")
        # один роздільник і рівно 2 цифри після нього = десяткові; інакше тисячі
        if len(parts) == 2 and len(parts[1]) == 2:
            t = parts[0] + "." + parts[1]
        else:
            t = "".join(parts)
    return float(t)


def parse_price_range(text, country):
    """'R$14.99 - R$449.99 per item' -> (14.99, 449.99, 'BRL')."""
    if not text:
        return None, None, None
    nums = []
    for part in RANGE_SPLIT.split(text):
        m = NUMBER.search(part)
        if m:
            try:
                nums.append(parse_amount(m.group()))
            except ValueError:
                pass
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
    text = f"{data.get('title')}|{data.get('summary')}|{data.get('description')}"
    return hashlib.md5(text.encode("utf-8")).hexdigest()


KEY_VERSION = 2  # ключ = назва + short + повний опис


def _screens(data):
    return sorted(u.split("=")[0] for u in (data or {}).get("screenshots") or [])


def _listing(data, base_screens=None):
    if not data:
        return None
    return {"title": data.get("title"), "summary": data.get("summary"), "key": _listing_key(data), "v": KEY_VERSION,
            # Google автоматично перекладає текст, але не скріншоти. Власні скріншоти мови =
            # справжня ручна локалізація.
            "own_screens": base_screens is not None and _screens(data) != base_screens}


def scan_app(app_id, countries, languages, rates, delay=(1, 2), fetch=fetch_page, country_pages=True):
    result = {"countries": {}, "languages": [], "errors": [], "country_pages": {}}

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
        # Сторінка країни її основною мовою (ціни парсимо з англійської, вона стабільніша)
        if country_pages and status == "ok":
            hl = COUNTRY_LANG.get(cc, "en")
            if hl == "en":
                page = data
            else:
                st2, page = fetch(app_id, hl, cc)
                time.sleep(random.uniform(*delay)) if delay else None
                if st2 == "error":
                    result["errors"].append(f"page {cc}")
            if page:
                result["country_pages"][cc] = {"lang": hl, "data": page}

    # Мовні версії сторінки. Текст зберігаємо, щоб відрізнити ручні локалізації
    # від автоперекладу Google: автопереклад змінюється разом з англійським текстом,
    # ручна локалізація — сама по собі.
    _, base = fetch(app_id, "en", "us")
    base_key, base_screens = _listing_key(base), _screens(base)
    result["base"] = _listing(base)
    result["listings"] = {}
    result["full"] = {"en": base} if base else {}  # повні сторінки, зберігаються окремо в snapshots
    for hl in languages:
        status, data = fetch(app_id, hl, "us")
        time.sleep(random.uniform(*delay)) if delay else None
        if status == "error":
            result["errors"].append(f"lang {hl}")
            continue
        key = _listing_key(data)
        if key and key != base_key:
            result["languages"].append(hl)
            result["listings"][hl] = _listing(data, base_screens)
            result["full"][hl] = data
    return result


def diff_market(old, new, price_threshold=0.03):
    """Структуровані зміни між двома сканами одного застосунку."""
    if not old:
        return []
    out = []
    oc, nc = old.get("countries", {}), new.get("countries", {})
    both = set(oc) & set(nc)
    old_av = {c for c in both if oc[c].get("available")}
    new_av = {c for c in both if nc[c].get("available")}
    if new_av - old_av:
        out.append({"type": "country_added", "countries": sorted(new_av - old_av)})
    if old_av - new_av:
        out.append({"type": "country_removed", "countries": sorted(old_av - new_av)})

    ol, nl = set(old.get("languages", [])), set(new.get("languages", []))
    if nl - ol:
        out.append({"type": "lang_added", "langs": sorted(nl - ol)})
    if ol - nl:
        out.append({"type": "lang_removed", "langs": sorted(ol - nl)})

    olist0, nlist0 = old.get("listings") or {}, new.get("listings") or {}
    screens_new = sorted(hl for hl, l in nlist0.items() if l and l.get("own_screens")
                         and hl in olist0 and olist0[hl] and olist0[hl].get("own_screens") is False)
    if screens_new:
        out.append({"type": "own_screens_added", "langs": screens_new})

    # Ключі різних версій формату не порівнюємо (інакше одноразова хибна "зміна" всього)
    if (old.get("base") or {}).get("v") != (new.get("base") or {}).get("v"):
        return out + _price_and_ads(oc, nc, both, price_threshold)

    # Ручні правки локалізацій: текст мови змінився, а англійський — ні.
    base_same = (old.get("base") or {}).get("key") == (new.get("base") or {}).get("key")
    olist, nlist = old.get("listings") or {}, new.get("listings") or {}
    edited = sorted(hl for hl in set(olist) & set(nlist)
                    if olist[hl] and nlist[hl] and olist[hl]["key"] != nlist[hl]["key"])
    if edited and base_same:
        out.append({"type": "listing_edited", "langs": edited,
                    "samples": [(hl, olist[hl]["title"], nlist[hl]["title"]) for hl in edited[:3]]})
    elif not base_same and old.get("base") and new.get("base"):
        out.append({"type": "base_changed", "old": old["base"]["title"], "new": new["base"]["title"],
                    "followed": len(edited)})

    return out + _price_and_ads(oc, nc, both, price_threshold)


def _price_and_ads(oc, nc, both, price_threshold):
    out = []
    prices = []
    for cc in sorted(both):
        a, b = oc[cc], nc[cc]
        for k, kind in (("min_local", "entry"), ("max_local", "top")):
            x, y = a.get(k), b.get(k)
            if x and y and abs(y - x) / x >= price_threshold:
                prices.append({"country": cc, "kind": kind, "old": x, "new": y,
                               "currency": b.get("currency"), "pct": (y - x) / x})
    if prices:
        out.append({"type": "price", "changes": prices})

    ads = [cc for cc in sorted(both) if oc[cc].get("containsAds") is not None
           and nc[cc].get("containsAds") is not None
           and oc[cc]["containsAds"] != nc[cc]["containsAds"]]
    if ads:
        out.append({"type": "ads", "countries": ads, "now": nc[ads[0]]["containsAds"]})
    return out


def merge_first_seen(old, new, today):
    """Коли апка вперше з'явилась у країні / мові. 'baseline' = була вже на першому скані."""
    prev = (old or {}).get("first_seen")
    stamp = today if prev else "baseline"
    prev = prev or {"countries": {}, "languages": {}}
    fs = {"countries": {}, "languages": {}}
    for cc, e in new["countries"].items():
        if e.get("available"):
            fs["countries"][cc] = prev["countries"].get(cc, stamp)
    for hl in new["languages"]:
        fs["languages"][hl] = prev["languages"].get(hl, stamp)
    return fs


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
