import pytest

from app.features.vendor_name_split import service

from .conftest import LONG_NAME, PART1, PART2, PATH, VENDORS_BOARD, auth, body, client

PART1_ID, PART2_ID = "text_mkt92ar9", "text_mksb1npw"


def test_a_long_vendor_name_is_split_into_part1_and_part2(fake_monday):
    assert len(LONG_NAME) == 122
    res = client.post(PATH, json=body(), headers=auth())
    assert res.status_code == 200
    assert res.json() == {"outputFields": {}}
    assert fake_monday["mutations"] == [{PART1_ID: PART1, PART2_ID: PART2}]
    assert fake_monday["name"] == LONG_NAME, "the vendor name itself is never changed"


def test_shortening_the_name_moves_it_to_part1_and_empties_part2(fake_monday):
    client.post(PATH, json=body(), headers=auth())

    fake_monday["name"] = "KONRAD KLEINER GmbH"  # the user renames the vendor
    client.post(PATH, json=body(), headers=auth())

    assert fake_monday["mutations"][-1] == {PART1_ID: "KONRAD KLEINER GmbH", PART2_ID: ""}
    assert (fake_monday[PART1_ID], fake_monday[PART2_ID]) == ("KONRAD KLEINER GmbH", "")


def test_a_short_name_fills_part1_only(fake_monday):
    fake_monday["name"] = "Autohaus Quickborn"
    client.post(PATH, json=body(), headers=auth())
    assert fake_monday["mutations"] == [{PART1_ID: "Autohaus Quickborn"}], "Part 2 is already empty"


def test_a_word_is_never_cut(fake_monday):
    fake_monday["name"] = (
        "Internationale Gesellschaft für Logistik, Lagerhaltung und Transportdienstleistungen "
        "Nord Westens Ali Khan Holding GmbH"
    )
    client.post(PATH, json=body(), headers=auth())
    assert fake_monday[PART2_ID] == "Ali Khan Holding GmbH"


def test_rerun_is_a_no_op(fake_monday):
    client.post(PATH, json=body(), headers=auth())
    client.post(PATH, json=body(), headers=auth())  # e.g. fired again by a name-change trigger
    assert len(fake_monday["mutations"]) == 1


def test_only_the_part_that_changed_is_written(fake_monday):
    fake_monday[PART1_ID] = PART1
    client.post(PATH, json=body(), headers=auth())
    assert fake_monday["mutations"] == [{PART2_ID: PART2}]


def test_the_limit_follows_max_name_length(fake_monday, monkeypatch):
    monkeypatch.setenv("MAX_NAME_LENGTH", "50")
    client.post(PATH, json=body(), headers=auth())
    assert fake_monday[PART1_ID] == "Bayerische Maschinenbau und Anlagentechnik"


@pytest.mark.parametrize("path", [PATH, PATH + "/"])
def test_both_spellings_of_the_route_work(fake_monday, path):
    assert client.post(path, json=body(), headers=auth(path)).status_code == 200


@pytest.mark.parametrize("fields", [{"boardId": VENDORS_BOARD}, {"itemId": 42}, {"boardId": "x", "itemId": 42}])
def test_board_and_item_are_required(fake_monday, fields):
    res = client.post(PATH, json={"payload": {"inputFields": fields}}, headers=auth())
    assert res.status_code == 400
    assert res.json()["notificationErrorTitle"] == "Missing input"
    assert fake_monday["calls"] == 0


@pytest.mark.parametrize("content", [b"{not json", b"", b"[1]", b'{"payload": "x"}'])
def test_malformed_body_returns_monday_error(fake_monday, content):
    res = client.post(PATH, content=content, headers={**auth(), "Content-Type": "application/json"})
    assert res.status_code == 400
    assert res.json()["severityCode"] == 4000
    assert fake_monday["calls"] == 0


def test_a_missing_column_returns_monday_error(fake_monday, monkeypatch):
    monkeypatch.setattr(service, "PART2_COLUMN_ID", "text_gone")
    res = client.post(PATH, json=body(), headers=auth())
    assert res.status_code == 400
    assert res.json()["notificationErrorTitle"] == "Vendor name split failed"
    assert "text_gone" in res.json()["notificationErrorDescription"]


def test_rejects_bad_or_missing_jwt(fake_monday):
    assert client.post(PATH, json=body(), headers=auth(secret="wrong-signing-secret-0123456789abcdef")).status_code == 401
    assert client.post(PATH, json=body()).status_code == 401
    assert client.post(PATH, json=body(), headers=auth("/customer-name-split")).status_code == 401
    assert fake_monday["calls"] == 0


def test_the_other_features_routes_are_not_part_of_this_feature():
    for path in ("/company-enrichment", "/customer-name-split"):
        assert client.post(path, json=body(), headers=auth(path)).status_code == 404
