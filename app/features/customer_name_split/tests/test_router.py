import pytest

from .conftest import (
    KUNDEN_DEV_BOARD, KUNDEN_SANDBOX_BOARD, LEGACY_PATH, LONG_NAME, PART1, PART2, PATH, WARM_LEAD_BOARD,
    WARM_LEAD_OLD_DEFAULT_BOARD, auth, body, client,
)


@pytest.mark.parametrize("board_id", [KUNDEN_DEV_BOARD, KUNDEN_SANDBOX_BOARD])
def test_kunden_boards_run_teil1_teil2_flow(fake_monday, board_id):
    assert client.post(PATH, json=body(board_id), headers=auth()).status_code == 200
    assert fake_monday["mutations"] == [{"text_mkt92ar9": PART1, "text_mksb1npw": PART2}]
    assert fake_monday["text_cust"] == LONG_NAME  # Warm Lead columns untouched


@pytest.mark.parametrize("board_id", [WARM_LEAD_BOARD, WARM_LEAD_OLD_DEFAULT_BOARD])
def test_warm_lead_boards_run_customer_name_flow(fake_monday, board_id):
    assert client.post(PATH, json=body(board_id), headers=auth()).status_code == 200
    assert fake_monday["mutations"] == [{"text_cust": PART1, "text_mm7qvqph": PART2}]
    assert fake_monday["text_mkt92ar9"] == ""  # Kunden columns untouched


@pytest.mark.parametrize("path", [PATH, PATH + "/", LEGACY_PATH])
def test_every_route_of_the_feature_runs_the_split(fake_monday, path):
    res = client.post(path, json=body(KUNDEN_DEV_BOARD), headers=auth(path))
    assert res.status_code == 200
    assert res.json() == {"outputFields": {}}
    assert len(fake_monday["mutations"]) == 1


def test_any_other_board_runs_customer_name_flow_like_the_old_app(fake_monday):
    assert client.post(PATH, json=body(999), headers=auth()).status_code == 200
    assert fake_monday["mutations"] == [{"text_cust": PART1, "text_mm7qvqph": PART2}]


def test_board_id_falls_back_to_warm_lead(fake_monday):
    assert client.post(PATH, json={"payload": {"inputFields": {"itemId": 42}}}, headers=auth()).status_code == 200
    assert fake_monday["mutations"] == [{"text_cust": PART1, "text_mm7qvqph": PART2}]


def test_missing_item_returns_monday_error(fake_monday):
    res = client.post(PATH, json={"payload": {"inputFields": {"boardId": KUNDEN_DEV_BOARD}}}, headers=auth())
    assert res.status_code == 400
    assert res.json()["notificationErrorTitle"] == "Missing input"
    assert fake_monday["calls"] == 0


def test_accepts_legacy_inbound_field_values(fake_monday):
    legacy = {"payload": {"inboundFieldValues": {"boardId": {"value": KUNDEN_DEV_BOARD}, "itemId": 42}}}
    res = client.post(PATH, json=legacy, headers=auth())
    assert res.status_code == 200
    assert res.json() == {"outputFields": {}}
    assert len(fake_monday["mutations"]) == 1


@pytest.mark.parametrize("content", [b"{not json", b"", b"[1, 2]", b'"text"', b'{"payload": "x"}',
                                     b'{"payload": {"inputFields": ["boardId"]}}'])
def test_malformed_body_returns_monday_error_not_a_crash(fake_monday, content):
    res = client.post(PATH, content=content, headers={**auth(), "Content-Type": "application/json"})
    assert res.status_code == 400
    assert res.json()["severityCode"] == 4000
    assert res.json()["notificationErrorTitle"] in ("Malformed request", "Missing input")
    assert fake_monday["calls"] == 0


def test_wrong_item_id_type_returns_monday_error(fake_monday):
    res = client.post(PATH, json=body(KUNDEN_DEV_BOARD, item_id="not-a-number"), headers=auth())
    assert res.status_code == 400
    assert res.json()["notificationErrorTitle"] == "Missing input"
    assert fake_monday["calls"] == 0


def test_rejects_bad_or_missing_jwt(fake_monday):
    wrong = auth(LEGACY_PATH, secret="wrong-signing-secret-0123456789abcdef")
    assert client.post(LEGACY_PATH, json=body(KUNDEN_DEV_BOARD), headers=wrong).status_code == 401
    assert client.post(LEGACY_PATH, json=body(KUNDEN_DEV_BOARD)).status_code == 401
    assert fake_monday["calls"] == 0


def test_reads_secret_from_monday_code_when_env_var_missing(monkeypatch):
    from app.core import config

    async def fake_monday_code(keys):
        found = {"MONDAY_SIGNING_SECRET": "from-monday-code-secret-0123456789"}
        return {key: found[key] for key in keys if key in found}

    monkeypatch.delenv("MONDAY_SIGNING_SECRET")
    monkeypatch.setattr(config, "_from_monday_code", fake_monday_code)
    monkeypatch.setattr(config, "_cache", {})
    res = client.post(PATH, json=body(KUNDEN_DEV_BOARD), headers=auth(secret="wrong-signing-secret-0123456789abcdef"))
    assert res.status_code == 401  # secret was found, so it got as far as checking the signature


def test_missing_api_token_is_a_monday_error_not_a_retried_500(fake_monday, monkeypatch):
    from app.core import config

    async def nothing(keys):
        return {}

    monkeypatch.delenv("MONDAY_API_TOKEN")
    monkeypatch.setattr(config, "_from_monday_code", nothing)
    res = client.post(PATH, json=body(KUNDEN_DEV_BOARD), headers=auth())
    assert res.status_code == 400
    assert res.json()["severityCode"] == 4000
    assert "MONDAY_API_TOKEN" in res.json()["notificationErrorDescription"]
    assert fake_monday["calls"] == 0


def test_the_enrichment_routes_are_not_part_of_this_feature():
    assert client.post("/company-enrichment", json=body(WARM_LEAD_BOARD), headers=auth("/company-enrichment")).status_code == 404
