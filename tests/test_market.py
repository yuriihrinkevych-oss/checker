import json

import pytest

import scan_markets
from tracker import market, report, storage
from tracker.ranking import build_ranking


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA", tmp_path / "data")
    monkeypatch.setattr(report, "REPORTS", tmp_path / "reports")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)


def test_parse_price_range():
    assert market.parse_price_range("R$14.99 – R$449.99 per item", "br") == (14.99, 449.99, "BRL")
    assert market.parse_price_range("₹8,500.00 – ₹89.00 per item", "in") == (89.0, 8500.0, "INR")
    assert market.parse_price_range("US$0.99 - US$49.99 per item", "ua")[2] == "USD"
    assert market.parse_price_range(None, "us") == (None, None, None)


def test_to_usd():
    assert market.to_usd(50, "BRL", {"BRL": 5.0}) == 10.0
    assert market.to_usd(50, "XXX", {"BRL": 5.0}) is None


RATES = {"USD": 1, "BRL": 5.0, "EUR": 0.9, "PLN": 4.0}


def make_fetch(state):
    def fetch(app_id, hl, gl):
        if gl == "pl" and not state.get("pl_open"):
            return "unavailable", None
        title = "Family Locator"
        if hl in state.get("langs", []):
            title = f"Locator {hl}"
        price = {"us": "$4.99 - $99.99 per item", "br": "R$14.99 – R$449.99 per item",
                 "de": "€4.99 - €99.99 per item", "pl": "PLN 19.99 – PLN 399.99 per item"}[gl]
        if gl == "br" and state.get("br_up"):
            price = "R$19.99 – R$449.99 per item"
        return "ok", {"title": title, "summary": "s", "inAppProductPrice": price, "containsAds": False}
    return fetch


def test_scan_and_diff():
    s1 = market.scan_app("x", ["us", "br", "pl"], ["de", "pt-BR"], RATES, delay=None,
                         fetch=make_fetch({"langs": ["pt-BR"]}))
    assert s1["languages"] == ["pt-BR"]
    assert not s1["countries"]["pl"]["available"]
    assert s1["countries"]["br"]["min_usd"] == 3.0
    s2 = market.scan_app("x", ["us", "br", "pl"], ["de", "pt-BR"], RATES, delay=None,
                         fetch=make_fetch({"langs": ["pt-BR", "de"], "pl_open": True, "br_up": True}))
    changes = dict(market.diff_market(s1, s2))
    assert changes["🌍 Нові країни"] == "pl"
    assert changes["🗣 Нові локалізації"] == "de"
    assert "+33%" in changes["💰 Ціна мін. [br]"]


def test_ranking_with_calibration():
    rows = []
    for d, own, comp in [("2026-09-01", 1000, 5000), ("2026-10-01", 2000, 9000)]:
        rows.append({"date": d, "app_id": "own", "country": "us", "lang": "en", "realInstalls": own})
        rows.append({"date": d, "app_id": "comp", "country": "us", "lang": "en", "realInstalls": comp})
    apps = [{"id": "own", "name": "Own"}, {"id": "comp", "name": "Comp"}]
    table, cal = build_ranking(rows, apps, {"country": "us", "lang": "en"},
                               {"own": 5.0, "comp": 2.5}, {"app_id": "own", "revenue_usd_30d": 10000})
    assert cal
    # конкурент: інсталлів x4, ціна x0.5 -> ревенью x2
    assert table[0]["app"] == "Comp" and table[0]["rev_index"] == 20000


def test_scan_markets_end_to_end(monkeypatch):
    monkeypatch.setattr(scan_markets, "CONFIG", scan_markets.CONFIG)
    state = {"langs": ["pt-BR"]}
    cfg_countries = ["us", "br", "de", "pl"]
    import yaml
    real_load = yaml.safe_load
    def fake_load(text):
        cfg = real_load(text)
        cfg["market_scan"]["countries"] = cfg_countries
        cfg["market_scan"]["languages"] = ["de", "pt-BR"]
        return cfg
    monkeypatch.setattr(scan_markets.yaml, "safe_load", fake_load)
    scan_markets.main(fetch=make_fetch(state), rates=RATES, today="2026-10-05", delay=0)
    state.update({"pl_open": True, "langs": ["pt-BR", "de"]})
    scan_markets.main(fetch=make_fetch(state), rates=RATES, today="2026-10-12", delay=0)
    text = (report.REPORTS / "2026-10-12-markets.md").read_text()
    assert "Нові країни" in text and "Нові локалізації" in text
    assert (storage.DATA / "prices.csv").exists()
