"""Збір даних зі сторінки апки в Google Play і приведення до стабільного формату."""
import time

from google_play_scraper import app as gp_app
from google_play_scraper.exceptions import NotFoundError

# Поля, зміни яких вважаємо подією (ASO, монетизація, продукт).
TRACKED_FIELDS = {
    "title": "Назва",
    "summary": "Short description",
    "description": "Full description",
    "icon": "Іконка",
    "headerImage": "Feature graphic",
    "screenshots": "Скріншоти",
    "video": "Промо-відео",
    "version": "Версія",
    "inAppProductPrice": "Діапазон цін IAP",
    "price": "Ціна апки",
    "containsAds": "Реклама в апці",
    "contentRating": "Віковий рейтинг",
    "genre": "Категорія",
    "installs": "Бакет інсталів",
    "developer": "Розробник",
}

# Числові показники, які пишемо в часовий ряд.
METRIC_FIELDS = ["realInstalls", "minInstalls", "score", "ratings", "reviews"]


def _clean_image(url):
    """URL картинок Google Play мають хвіст з розміром (=w720-h310). Відрізаємо,
    щоб зміна розміру не виглядала як зміна картинки."""
    if not url:
        return url
    return url.split("=")[0]


def normalize(raw):
    snap = {k: raw.get(k) for k in TRACKED_FIELDS}
    snap["icon"] = _clean_image(snap["icon"])
    snap["headerImage"] = _clean_image(snap["headerImage"])
    snap["screenshots"] = [_clean_image(s) for s in (raw.get("screenshots") or [])]
    snap["metrics"] = {k: raw.get(k) for k in METRIC_FIELDS}
    snap["histogram"] = raw.get("histogram")
    snap["lastUpdatedOn"] = raw.get("lastUpdatedOn")
    return snap


def fetch(app_id, country, lang, retries=3):
    """Повертає нормалізований snapshot або None, якщо апку не знайдено."""
    for attempt in range(retries):
        try:
            return normalize(gp_app(app_id, lang=lang, country=country))
        except NotFoundError:
            return None
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
