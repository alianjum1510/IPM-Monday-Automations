from app.boards import kunden
from conftest import KUNDEN_DEV_BOARD, LONG_NAME, PART1, PART2, auth, body, client

BODY = body(KUNDEN_DEV_BOARD)


def test_splits_full_name_into_teil1_and_teil2(fake_monday):
    res = client.post("/monday/split-name", json=BODY, headers=auth())
    assert res.status_code == 200
    assert fake_monday["mutations"] == [{"text_mkt92ar9": PART1, "text_mksb1npw": PART2}]
    assert fake_monday["name"] == LONG_NAME  # full name is never touched


def test_rerun_is_noop(fake_monday):
    client.post("/monday/split-name", json=BODY, headers=auth())
    client.post("/monday/split-name", json=BODY, headers=auth())  # e.g. fired by our own write
    assert len(fake_monday["mutations"]) == 1


def test_short_name_is_copied_to_teil1_and_clears_teil2(fake_monday):
    fake_monday["name"] = "Müller & Söhne GmbH"
    fake_monday["text_mksb1npw"] = "old overflow"
    res = client.post("/monday/split-name", json=BODY, headers=auth())
    assert res.status_code == 200
    assert fake_monday["mutations"] == [{"text_mkt92ar9": "Müller & Söhne GmbH", "text_mksb1npw": ""}]


def test_only_changed_part_is_written(fake_monday):
    fake_monday["text_mkt92ar9"] = PART1
    client.post("/", json=BODY, headers=auth())
    assert fake_monday["mutations"] == [{"text_mksb1npw": PART2}]


def test_source_can_be_a_text_column(fake_monday, monkeypatch):
    fake_monday["text_voll"] = LONG_NAME
    fake_monday["name"] = "Item"
    monkeypatch.setattr(kunden, "SOURCE_COLUMN_ID", "text_voll")
    assert client.post("/", json=BODY, headers=auth()).status_code == 200
    assert fake_monday["mutations"] == [{"text_mkt92ar9": PART1, "text_mksb1npw": PART2}]


def test_missing_column_returns_monday_error(fake_monday, monkeypatch):
    monkeypatch.setattr(kunden, "PART2_COLUMN_ID", "text_gone")
    res = client.post("/", json=BODY, headers=auth())
    assert res.status_code == 400
    assert res.json()["notificationErrorTitle"] == "Name split failed"
    assert "text_gone" in res.json()["notificationErrorDescription"]
