import copy

import pytest

import run
from tracker import report, storage
from tracker.diff import diff_snapshots, velocity_alert


def make_raw(ratings=1000, title="Family Locator", shots=("a", "b")):
    return {
        "title": title, "summary": "Find your family", "description": "Line 1\nLine 2",
        "icon": "https://play-lh/icon=w240", "headerImage": None,
        "screenshots": [f"https://play-lh/{s}=w720" for s in shots], "video": None,
        "version": "1.0", "inAppProductPrice": "$0.99 - $49.99", "price": 0,
        "containsAds": False, "contentRating": "Everyone", "genre": "Lifestyle",
        "installs": "1,000,000+", "developer": "Dev", "realInstalls": 1234567,
        "minInstalls": 1000000, "score": 4.5, "ratings": ratings, "reviews": 300,
        "histogram": [1, 2, 3, 4, 5], "lastUpdatedOn": "Oct 1, 2026",
    }


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA", tmp_path / "data")
    monkeypatch.setattr(report, "REPORTS", tmp_path / "reports")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)


def test_diff_detects_aso_changes():
    from tracker.collect import normalize
    old = normalize(make_raw())
    new_raw = make_raw(title="Family Locator: GPS Tracker", shots=("a", "c", "d"))
    new_raw["description"] = "Line 1\nLine 2 changed"
    new = normalize(new_raw)
    fields = {c["field"]: c for c in diff_snapshots(old, new)}
    assert "title" in fields
    assert "нових: 2" in fields["screenshots"]["detail"]
    assert "+Line 2 changed" in fields["description"]["detail"]
    assert "ratings" not in fields  # метрики не є "змінами"


def test_image_size_suffix_is_ignored():
    from tracker.collect import normalize
    a = make_raw(); b = copy.deepcopy(a)
    b["icon"] = "https://play-lh/icon=w512"
    assert diff_snapshots(normalize(a), normalize(b)) == []


def test_velocity_alert():
    hist = [{"ratings": str(1000 + 10 * i)} for i in range(8)]  # ~10/день
    assert velocity_alert(hist, 1070 + 50, 2.0, 20, 7)["today_delta"] == 50
    assert velocity_alert(hist, 1070 + 15, 2.0, 20, 7) is None
    assert velocity_alert(hist[:2], 5000, 2.0, 20, 7) is None  # замало історії


def test_end_to_end_runs(monkeypatch):
    state = {"day": 0}
    def fake_fetch(app_id, country, lang):
        from tracker.collect import normalize
        d = state["day"]
        raw = make_raw(ratings=1000 + 10 * d)
        if d >= 5 and app_id == "org.findmykids.app":
            raw = make_raw(ratings=1000 + 10 * 4 + 200, title="New title")
        return normalize(raw)

    for d in range(6):
        state["day"] = d
        events, errors = run.main(fetch_fn=fake_fetch, today=f"2026-10-0{d + 1}", sleep=False)
        if d == 0:
            assert events == []
    types = {(e["app_id"], e["type"]) for e in events}
    assert ("org.findmykids.app", "change") in types
    assert ("org.findmykids.app", "velocity") in types
    assert not errors
    rows = storage.read_metrics()
    assert len({r["date"] for r in rows}) == 6
