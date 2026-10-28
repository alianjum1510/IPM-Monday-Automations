import pytest

from conftest import (
    KUNDEN_DEV_BOARD, KUNDEN_SANDBOX_BOARD, LONG_NAME, PART1, PART2, WARM_LEAD_BOARD,
    WARM_LEAD_OLD_DEFAULT_BOARD, auth, body, client,
)


@pytest.mark.parametrize("board_id", [KUNDEN_DEV_BOARD, KUNDEN_SANDBOX_BOARD])
def test_kunden_boards_run_teil1_teil2_flow(fake_monday, board_id):
    assert client.post("/", json=body(board_id), headers=auth()).status_code == 200
    assert fake_monday["mutations"] == [{"text_mkt92ar9": PART1, "text_mksb1npw": PART2}]
    assert fake_monday["text_cust"] == LONG_NAME  # Warm Lead columns untouched


@pytest.mark.parametrize("board_id", [WARM_LEAD_BOARD, WARM_LEAD_OLD_DEFAULT_BOARD])
def test_warm_lead_boards_run_customer_name_flow(fake_monday, board_id):
    assert client.post("/", json=body(board_id), headers=auth()).status_code == 200
    assert fake_monday["mutations"] == [{"text_cust": PART1, "text_mm7qvqph": PART2}]
    assert fake_monday["text_mkt92ar9"] == ""  # Kunden columns untouched


@pytest.mark.parametrize("path", ["/", "/health"])
def test_health_answers_get_and_head(path):
    assert client.get(path).json() == {"ok": True}
    assert client.head(path).status_code == 200  # monday's health checker uses HEAD


def test_any_other_board_runs_customer_name_flow_like_the_old_app(fake_monday):
    assert client.post("/", json=body(999), headers=auth()).status_code == 200
    assert fake_monday["mutations"] == [{"text_cust": PART1, "text_mm7qvqph": PART2}]


def test_board_id_falls_back_to_warm_lead(fake_monday):
    assert client.post("/", json={"payload": {"inputFields": {"itemId": 42}}}, headers=auth()).status_code == 200
    assert fake_monday["mutations"] == [{"text_cust": PART1, "text_mm7qvqph": PART2}]


def test_missing_item_returns_monday_error(fake_monday):
    res = client.post("/", json={"payload": {"inputFields": {"boardId": KUNDEN_DEV_BOARD}}}, headers=auth())
    assert res.status_code == 400
    assert res.json()["notificationErrorTitle"] == "Missing input"
    assert fake_monday["calls"] == 0


def test_accepts_legacy_inbound_field_values(fake_monday):
    legacy = {"payload": {"inboundFieldValues": {"boardId": {"value": KUNDEN_DEV_BOARD}, "itemId": 42}}}
    res = client.post("/", json=legacy, headers=auth())
    assert res.status_code == 200
    assert res.json() == {"outputFields": {}}
    assert len(fake_monday["mutations"]) == 1


def test_rejects_bad_or_missing_jwt(fake_monday):
    assert client.post("/monday/split-name", json=body(KUNDEN_DEV_BOARD), headers=auth("wrong-signing-secret-0123456789abcdef")).status_code == 401
    assert client.post("/monday/split-name", json=body(KUNDEN_DEV_BOARD)).status_code == 401
    assert fake_monday["calls"] == 0


def test_reads_secret_from_monday_code_when_env_var_missing(monkeypatch):
    from app import config

    async def fake_monday_code(key):
        return {"MONDAY_SIGNING_SECRET": "from-monday-code-secret-0123456789"}.get(key)

    monkeypatch.delenv("MONDAY_SIGNING_SECRET")
    monkeypatch.setattr(config, "_from_monday_code", fake_monday_code)
    monkeypatch.setattr(config, "_cache", {})
    res = client.post("/", json=body(KUNDEN_DEV_BOARD), headers=auth("wrong-signing-secret-0123456789abcdef"))
    assert res.status_code == 401  # secret was found, so it got as far as checking the signature
