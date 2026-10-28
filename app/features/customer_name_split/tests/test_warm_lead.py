from app.features.customer_name_split.processors import warm_lead
from .conftest import LEGACY_PATH, LONG_NAME, PART1, PART2, PATH, WARM_LEAD_BOARD, auth, body, client

BODY = body(WARM_LEAD_BOARD)
LEGACY_BODY = body(WARM_LEAD_BOARD, sourceColumnId="text_cust", targetColumnId="text_mm7qvqph")


def test_splits_long_name_and_writes_both_columns(fake_monday):
    res = client.post(LEGACY_PATH, json=LEGACY_BODY, headers=auth(LEGACY_PATH))
    assert res.status_code == 200
    assert fake_monday["mutations"] == [{"text_cust": PART1, "text_mm7qvqph": PART2}]
    assert fake_monday["name"] == LONG_NAME  # item name is not the source on this board


def test_retrigger_after_own_write_is_noop(fake_monday):
    client.post(LEGACY_PATH, json=BODY, headers=auth(LEGACY_PATH))
    client.post(LEGACY_PATH, json=BODY, headers=auth(LEGACY_PATH))  # fired by our own write
    assert len(fake_monday["mutations"]) == 1


def test_short_name_does_not_write(fake_monday):
    fake_monday["text_cust"] = "Müller & Söhne GmbH"
    res = client.post(LEGACY_PATH, json=BODY, headers=auth(LEGACY_PATH))
    assert res.status_code == 200
    assert fake_monday["mutations"] == []


def test_same_column_returns_monday_error(fake_monday):
    same = body(WARM_LEAD_BOARD, sourceColumnId="text_cust", targetColumnId="text_cust")
    res = client.post(LEGACY_PATH, json=same, headers=auth(LEGACY_PATH))
    assert res.status_code == 400
    assert res.json()["notificationErrorTitle"] == "Same column selected"


def test_finds_source_by_title_and_uses_fixed_target(fake_monday):
    fake_monday["columns"][2]["title"] = "Renamed"  # target is pinned by id, so its title doesn't matter
    res = client.post(PATH, json=BODY, headers=auth())
    assert res.status_code == 200
    assert fake_monday["mutations"] == [{"text_cust": PART1, "text_mm7qvqph": PART2}]


def test_target_found_by_title_when_not_pinned(fake_monday, monkeypatch):
    monkeypatch.setattr(warm_lead, "TARGET_COLUMN_ID", None)
    fake_monday["columns"][2]["title"] = "company / customer name 2"  # case-insensitive
    assert client.post(PATH, json=BODY, headers=auth()).status_code == 200
    assert len(fake_monday["mutations"]) == 1


def test_missing_column_returns_monday_error(fake_monday):
    fake_monday["columns"] = [{"id": "name", "title": "Name", "type": "name"}]
    res = client.post(PATH, json=BODY, headers=auth())
    assert res.status_code == 400
    assert res.json()["notificationErrorTitle"] == "Column not found"
    assert fake_monday["mutations"] == []
