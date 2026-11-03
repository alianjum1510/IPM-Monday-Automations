"""
The two modes, the auto choice and the loop guard - the old app's TriggerFlowTests
and ActionBlockTests, case for case, against service.action().
"""
import pytest

from app.features.address_validator import service
from app.features.address_validator.boards import boards, get_board_config

from .conftest import BOARD_ID, C, FULL, LOCATION_ORIGINAL_BOARD, ORIGINAL_BOARD_ID, TOKEN


def run(payload, mode=None):
    return service.action(payload, mode, TOKEN)


# ---------- trigger flow (a column ID in the payload decides the mode) ----------

def test_full_address_fills_every_field(board):
    board.new_item({C["full_address"]: FULL})
    r = run(board.event(C["full_address"]))

    assert r["mode"] == "address"
    assert r["isComplete"] is True
    assert board.text(C["address_line_1"]) == "Borsigstraße 15"
    assert board.text(C["postcode"]) == "51381"
    assert board.text(C["city"]) == "Leverkusen"
    assert board.text(C["state"]) == "North Rhine-Westphalia"
    assert board.text(C["latitude"]) == "51.0457"
    assert board.text(C["status"]) == "Complete"
    assert board.text(C["full_address"]) == FULL
    assert C["full_address"] not in board.mutations[0]
    assert C["location"] in board.mutations[0]


def test_own_writes_do_not_retrigger(board):
    board.new_item({C["full_address"]: FULL})
    run(board.event(C["full_address"]))
    before = len(board.here_queries)

    r1 = run(board.event(C["address_line_1"]))
    r2 = run(board.event(C["postcode"]))
    assert r1["skipped"] is True
    assert r2["skipped"] is True
    assert len(board.here_queries) == before  # no extra HERE calls


def test_loop_stops_after_restart(board):
    board.new_item({C["full_address"]: FULL})
    run(board.event(C["full_address"]))

    service.recent_writes.clear()  # simulate restart: echo arrives at a fresh instance
    r1 = run(board.event(C["address_line_1"]))
    assert r1["mode"] == "fields"
    assert r1["written"] == [C["full_address"], C["location"]]  # only Full Address (+ pin) gets normalised

    service.recent_writes.clear()
    r2 = run(board.event(C["full_address"]))
    assert r2["mode"] == "address"
    assert r2["written"] == []  # nothing changed → no write → no further trigger


def test_fields_edit_refreshes_others_not_inputs(board):
    board.new_item({C["address_line_1"]: "Borsigstr. 15", C["postcode"]: "51381", C["country"]: "Deutschland"})
    r = run(board.event(C["postcode"]))

    assert r["mode"] == "fields"
    assert r["isComplete"] is True
    assert board.here_queries[-1]["q"] == "Borsigstr. 15, 51381"
    assert board.here_queries[-1]["in"] == "countryCode:DEU"
    assert board.text(C["address_line_1"]) == "Borsigstr. 15"  # user's input kept
    assert board.text(C["city"]) == "Leverkusen"
    assert board.text(C["full_address"]) == \
        "Borsigstraße 15, 51381, Leverkusen, Leverkusen, North Rhine-Westphalia, Deutschland"
    assert board.text(C["status"]) == "Complete"


def test_postcode_mismatch_is_stuck_and_writes_only_status(board):
    board.new_item({C["address_line_1"]: "Borsigstraße 15", C["postcode"]: "99999", C["city"]: "Old City"})
    r = run(board.event(C["postcode"]))

    assert r["isComplete"] is False
    assert "Postcode mismatch" in r["reason"]
    assert board.text(C["city"]) == "Old City"
    assert board.text(C["status"]) == "Stuck"
    assert list(board.mutations[0]) == [C["status"]]


def test_one_input_missing_is_stuck_without_here(board):
    board.new_item({C["address_line_1"]: "Borsigstraße 15"})
    r = run(board.event(C["address_line_1"]))
    assert r["isComplete"] is False
    assert board.text(C["status"]) == "Stuck"
    assert len(board.here_queries) == 0


def test_here_no_match_is_stuck(board):
    board.new_item({C["full_address"]: "asdfgh qwerty"})
    r = run(board.event(C["full_address"]))
    assert "no match" in r["reason"]
    assert board.text(C["status"]) == "Stuck"


def test_non_trigger_column_skipped(board):
    board.new_item({})
    r = run(board.event(C["city"]))
    assert r["skipped"] is True
    assert len(board.mutations) == 0


def test_no_column_id_uses_full_address(board):
    board.new_item({C["full_address"]: FULL})
    r = run({"event": {"pulseId": 111, "boardId": int(BOARD_ID)}})
    assert r["mode"] == "address"
    assert board.text(C["postcode"]) == "51381"


# ---------- monday action block (the route decides the mode) ----------

def test_address_block_then_fields_echo_skipped(board):
    board.new_item({C["full_address"]: FULL})
    r1 = run(board.block_payload(), "address")
    assert r1["mode"] == "address"
    assert board.text(C["postcode"]) == "51381"

    # monday fires the Adresszeile 1 and Postcode automations for the app's own writes
    r2 = run(board.block_payload(), "fields")
    r3 = run(board.block_payload(), "fields")
    assert r2["skipped"] is True
    assert r3["skipped"] is True
    assert len(board.here_queries) == 1


def test_user_edits_postcode_after_population(board):
    board.new_item({C["full_address"]: FULL})
    run(board.block_payload(), "address")

    board.set_text(C["postcode"], "99999")  # user edit
    r = run(board.block_payload(), "fields")
    assert r["mode"] == "fields"
    assert "Postcode mismatch" in r["reason"]
    assert board.text(C["status"]) == "Stuck"


def test_user_reenters_full_address(board):
    board.new_item({C["full_address"]: "asdfgh qwerty"})
    run(board.block_payload(), "address")  # Stuck, no match

    board.set_text(C["full_address"], FULL)
    r = run(board.block_payload(), "address")
    assert r["mode"] == "address"
    assert r["isComplete"] is True
    assert board.text(C["address_line_1"]) == "Borsigstraße 15"


def test_auto_mode(board):
    board.new_item({C["address_line_1"]: "Borsigstraße 15", C["postcode"]: "51381", C["full_address"]: "x"})
    assert run(board.block_payload())["mode"] == "fields"

    board.new_item({C["full_address"]: FULL})
    assert run(board.block_payload())["mode"] == "address"


def test_original_board_uses_location_setting(board):
    o = boards()[ORIGINAL_BOARD_ID]["columns"]
    assert o["location"] == LOCATION_ORIGINAL_BOARD

    board.new_item({o["full_address"]: FULL}, ORIGINAL_BOARD_ID)
    r = run(board.block_payload(ORIGINAL_BOARD_ID), "address")
    assert r["isComplete"] is True
    assert o["location"] in board.mutations[0]
    assert board.mutations[0][o["status"]] == {"label": "Done"}


# ---------- added: what the port must not change ----------

def test_original_board_without_location_setting_writes_no_pin(board, monkeypatch):
    monkeypatch.delenv("ADDRESS_COLUMN_LOCATION_ID")
    o = boards()[ORIGINAL_BOARD_ID]["columns"]
    assert o["location"] is None

    board.new_item({o["full_address"]: FULL}, ORIGINAL_BOARD_ID)
    run(board.block_payload(ORIGINAL_BOARD_ID), "address")
    assert LOCATION_ORIGINAL_BOARD not in board.mutations[0]
    assert board.text(o["postcode"]) == "51381"


def test_unknown_board_uses_the_default_boards_columns(board):
    original = boards()[ORIGINAL_BOARD_ID]["columns"]
    board.new_item({original["full_address"]: FULL}, ORIGINAL_BOARD_ID)
    board.item["board"]["id"] = "999"
    run(board.block_payload("999"), "address")
    assert board.text(original["postcode"]) == "51381"


def test_status_labels_and_column_ids_can_be_overridden(board, monkeypatch):
    monkeypatch.setenv("ADDRESS_DONE_STATUS_LABEL", "Fertig")
    monkeypatch.setenv("ADDRESS_COLUMN_POSTCODE_ID", "text_custom_postcode")
    o = boards()[ORIGINAL_BOARD_ID]["columns"]
    assert o["postcode"] == "text_custom_postcode"

    board.new_item({o["full_address"]: FULL}, ORIGINAL_BOARD_ID)
    run(board.block_payload(ORIGINAL_BOARD_ID), "address")
    assert board.text("text_custom_postcode") == "51381"
    assert board.mutations[0][o["status"]] == {"label": "Fertig"}


def test_another_features_default_board_id_does_not_change_this_one(board, monkeypatch):
    monkeypatch.setenv("DEFAULT_BOARD_ID", BOARD_ID)  # the shared app's other DEFAULT_BOARD_ID
    original = boards()[ORIGINAL_BOARD_ID]["columns"]
    board.new_item({original["full_address"]: FULL}, ORIGINAL_BOARD_ID)
    board.item["board"]["id"] = "999"
    run(board.block_payload("999"), "address")
    assert board.text(original["postcode"]) == "51381", "still the original board's columns"

    monkeypatch.setenv("ADDRESS_DEFAULT_BOARD_ID", BOARD_ID)
    assert get_board_config("999") == boards()[BOARD_ID]


def test_no_token_raises(board):
    board.new_item({C["full_address"]: FULL})
    with pytest.raises(RuntimeError, match="MONDAY_API_TOKEN"):
        service.action(board.block_payload(), "address", None)
    assert board.monday_tokens == []


def test_missing_item_id_is_not_a_success(board):
    board.new_item({})
    r = run({"payload": {"inputFields": {"boardId": int(BOARD_ID)}}}, "address")
    assert r["success"] is False and r["skipped"] is True
    assert board.monday_tokens == []


def test_old_logs_wording_is_kept(board, caplog):
    caplog.set_level("INFO", logger="address_validator")
    board.new_item({C["full_address"]: FULL})
    run(board.block_payload(), "address")
    run(board.block_payload(), "fields")

    messages = [r.getMessage() for r in caplog.records if r.name == "address_validator"]
    assert messages[0] == f'Item 111 [address]: HERE query "{FULL}" in DEU'
    assert messages[1].startswith("Item 111 [address]: Complete (houseNumber PA, score 1; ")
    assert messages[2] == "Item 111 [fields]: ignoring — no address input changed since this app's last write."
