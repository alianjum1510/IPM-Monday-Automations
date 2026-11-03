"""The feature's routes, as monday calls them: route → mode, JWT, settings, errors."""
import pytest

from app.core.testing import monday_token

from .conftest import AUTO, BOARD_ID, C, FILL, FULL, TOKEN, VALIDATE, auth, client


def post(board, path, body=None, **auth_kwargs):
    return client.post(path, json=board.block_payload() if body is None else body, headers=auth(path, **auth_kwargs))


def test_fill_runs_the_address_mode(board):
    board.new_item({C["full_address"]: FULL})
    res = post(board, FILL)

    assert res.status_code == 200
    assert res.json() == {"outputFields": {}}
    assert board.text(C["postcode"]) == "51381"
    assert board.text(C["status"]) == "Complete"
    assert board.here_queries[0]["q"] == FULL


def test_validate_runs_the_fields_mode(board):
    board.new_item({C["full_address"]: "anything", C["address_line_1"]: "Borsigstr. 15", C["postcode"]: "51381"})
    assert post(board, VALIDATE).status_code == 200

    assert board.here_queries[0]["q"] == "Borsigstr. 15, 51381"
    assert board.text(C["address_line_1"]) == "Borsigstr. 15", "fields mode never overwrites its inputs"
    assert board.text(C["full_address"]).startswith("Borsigstraße 15, 51381, Leverkusen")


def test_the_same_item_does_different_things_by_route(board):
    """Re-entering the Full Address on a filled row: the route, not what is filled, picks the mode."""
    values = {C["full_address"]: FULL, C["address_line_1"]: "Old Street 1", C["postcode"]: "51381"}

    board.new_item(values)
    post(board, FILL)
    assert board.text(C["address_line_1"]) == "Borsigstraße 15"
    assert board.text(C["full_address"]) == FULL

    board.new_item(values)
    post(board, AUTO)
    assert board.text(C["address_line_1"]) == "Old Street 1", "auto picks fields mode when both are filled"


def test_auto_route_follows_the_old_action_url(board):
    board.new_item({C["full_address"]: FULL})
    assert post(board, AUTO).status_code == 200
    assert board.text(C["postcode"]) == "51381"


@pytest.mark.parametrize("path", [FILL, FILL + "/", VALIDATE, VALIDATE + "/", AUTO, AUTO + "/"])
def test_every_spelling_of_the_routes_works_without_a_redirect(board, path):
    board.new_item({C["full_address"]: FULL})
    res = post(board, path)
    assert res.status_code == 200
    assert not res.history


def test_the_echo_of_our_own_write_is_skipped_over_http(board):
    board.new_item({C["full_address"]: FULL})
    post(board, FILL)
    assert post(board, VALIDATE).status_code == 200
    assert post(board, VALIDATE).status_code == 200
    assert len(board.here_queries) == 1


def test_a_stuck_row_is_still_a_successful_run(board):
    board.new_item({C["full_address"]: "asdfgh qwerty"})
    res = post(board, FILL)
    assert res.status_code == 200
    assert board.text(C["status"]) == "Stuck"


# ---------- authentication ----------

def test_rejects_bad_or_missing_jwt(board):
    board.new_item({C["full_address"]: FULL})
    assert post(board, FILL, secret="wrong-signing-secret-0123456789abcdef").status_code == 401
    assert client.post(FILL, json=board.block_payload()).status_code == 401
    assert client.post(FILL, json=board.block_payload(), headers={"Authorization": "not-a-jwt"}).status_code == 401
    assert post(board, FILL, expires_in=-120).status_code == 401
    assert board.monday_tokens == [] and board.here_queries == []


def test_a_token_for_one_block_is_refused_on_the_other(board):
    board.new_item({C["full_address"]: FULL})
    assert client.post(VALIDATE, json=board.block_payload(), headers=auth(FILL)).status_code == 401
    assert client.post(FILL, json=board.block_payload(), headers=auth("/vendor-name-split")).status_code == 401
    assert board.monday_tokens == []


def test_missing_signing_secret_is_refused_never_let_through(board, monkeypatch):
    board.new_item({C["full_address"]: FULL})
    monkeypatch.delenv("MONDAY_SIGNING_SECRET")
    res = post(board, FILL)
    assert res.status_code == 400
    assert res.json()["severityCode"] == 4000
    assert board.monday_tokens == []


# ---------- settings and the monday token ----------

def test_missing_here_key_is_a_monday_error_and_nothing_runs(board, monkeypatch):
    board.new_item({C["full_address"]: FULL})
    monkeypatch.delenv("HERE_API_KEY")
    res = post(board, FILL)
    assert res.status_code == 400
    assert res.json()["severityCode"] == 4000
    assert "HERE_API_KEY" in res.json()["notificationErrorDescription"]
    assert board.monday_tokens == [] and board.here_queries == []


def test_monday_api_token_is_used_when_set(board):
    board.new_item({C["full_address"]: FULL})
    post(board, FILL)
    assert set(board.monday_tokens) == {TOKEN}


def test_without_monday_api_token_the_verified_short_lived_token_is_used(board, monkeypatch):
    monkeypatch.delenv("MONDAY_API_TOKEN")
    board.new_item({C["full_address"]: FULL})
    res = client.post(FILL, json=board.block_payload(),
                      headers={"Authorization": monday_token(FILL, shortLivedToken="short-lived-from-jwt")})
    assert res.status_code == 200
    assert set(board.monday_tokens) == {"short-lived-from-jwt"}


def test_without_any_token_it_is_a_monday_error(board, monkeypatch):
    monkeypatch.delenv("MONDAY_API_TOKEN")
    board.new_item({C["full_address"]: FULL})
    res = client.post(FILL, json=board.block_payload(), headers={"Authorization": monday_token(FILL, shortLivedToken=None)})
    assert res.status_code == 400
    assert res.json()["notificationErrorTitle"] == "Address validation failed"
    assert "MONDAY_API_TOKEN" in res.json()["notificationErrorDescription"]


def test_a_token_in_the_body_is_never_used(board, monkeypatch):
    monkeypatch.delenv("MONDAY_API_TOKEN")
    board.new_item({C["full_address"]: FULL})
    body = board.block_payload()
    body["payload"]["shortLivedToken"] = "attacker-token"
    client.post(FILL, json=body, headers={"Authorization": monday_token(FILL, shortLivedToken="from-jwt")})
    assert "attacker-token" not in board.monday_tokens


# ---------- malformed requests and failures ----------

@pytest.mark.parametrize("content", [b"{not json", b"", b"[1]", b'"text"'])
def test_malformed_body_returns_monday_error(board, content):
    res = client.post(FILL, content=content, headers={**auth(FILL), "Content-Type": "application/json"})
    assert res.status_code == 400
    assert res.json()["severityCode"] == 4000
    assert res.json()["notificationErrorTitle"] == "Malformed request"
    assert board.monday_tokens == []


@pytest.mark.parametrize("body", [{"payload": {"inputFields": {"boardId": int(BOARD_ID)}}}, {"payload": "x"}, {}])
def test_missing_item_returns_monday_error(board, body):
    res = client.post(FILL, json=body, headers=auth(FILL))
    assert res.status_code == 400
    assert res.json()["notificationErrorTitle"] == "Missing input"
    assert board.monday_tokens == []


def test_item_not_found_returns_monday_error(board):
    board.new_item({C["full_address"]: FULL})
    body = board.block_payload()
    board.item = None
    res = client.post(FILL, json=body, headers=auth(FILL))
    assert res.status_code == 400
    assert res.json()["notificationErrorTitle"] == "Address validation failed"
    assert "Item 111 not found" in res.json()["notificationErrorDescription"]


def test_a_here_error_returns_monday_error_and_writes_nothing(board, monkeypatch):
    import io
    import urllib.error

    board.new_item({C["full_address"]: FULL})
    real = board.urlopen

    def here_down(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "hereapi" in url:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b'{"error":"bad key"}'))
        return real(req, timeout)

    monkeypatch.setattr("urllib.request.urlopen", here_down)
    res = post(board, FILL)
    assert res.status_code == 400
    assert "HERE API error: HTTP 401" in res.json()["notificationErrorDescription"]
    assert "test-here-key" not in res.text, "the HERE key is never echoed"
    assert board.mutations == []


def test_a_monday_api_error_returns_monday_error(board, monkeypatch):
    from .conftest import FakeResponse

    board.new_item({C["full_address"]: FULL})
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: FakeResponse({"errors": [{"message": "No access"}]}))
    res = post(board, FILL)
    assert res.status_code == 400
    assert "monday API error" in res.json()["notificationErrorDescription"]


# ---------- logging and independence ----------

def test_the_request_line_names_this_feature(board, caplog):
    caplog.set_level("INFO", logger="monday_apps")
    board.new_item({C["full_address"]: FULL})
    post(board, FILL)

    [line] = [r for r in caplog.records if r.name == "monday_apps" and r.getMessage().startswith("POST")]
    assert line.getMessage().startswith(f"POST {FILL} -> address_validator 200 ")
    assert line.payload["board_id"] == BOARD_ID
    assert line.payload["item_id"] == "111"


def test_feature_log_lines_carry_the_feature_and_never_a_token(board, caplog):
    caplog.set_level("INFO")
    board.new_item({C["full_address"]: FULL})
    post(board, FILL)

    lines = [r for r in caplog.records if r.name == "address_validator"]
    assert lines and all(r.payload["item_id"] == "111" for r in lines)
    everything = " ".join(f"{r.getMessage()} {getattr(r, 'payload', '')}" for r in caplog.records)
    for secret in (TOKEN, "test-here-key", "short-lived-token-never-logged"):
        assert secret not in everything


def test_the_other_features_routes_are_not_part_of_this_feature(board):
    for path in ("/company-enrichment", "/customer-name-split", "/vendor-name-split"):
        assert client.post(path, json={}, headers=auth(path)).status_code == 404
