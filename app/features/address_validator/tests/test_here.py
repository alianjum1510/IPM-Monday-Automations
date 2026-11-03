"""Parsing and mapping - the same cases as the old app's ParsingTests (and its here.py)."""
import pytest

from app.features.address_validator import here

from .conftest import FULL, HERE_BORSIG


def test_parse_full_address_client_sheet_format():
    assert here.parse_full_address("Boschstraat 10, 6442, Pb Brunssum, Brunssum, Limburg, Niederlande") == \
        {"query": "Boschstraat 10, 6442 PB Brunssum", "postcode": "6442 PB", "cc": "NLD"}
    assert here.parse_full_address("Urmonderbaan, 22, 6167, Rd Sittard-Geleen, Sittard-Geleen, Limburg, Niederlande") == \
        {"query": "Urmonderbaan 22, 6167 RD Sittard-Geleen", "postcode": "6167 RD", "cc": "NLD"}
    assert here.parse_full_address("Borsigstraße 15, 51381, Leverkusen, Leverkusen, North Rhine-Westphalia, Deutschland") == \
        {"query": "Borsigstraße 15, 51381 Leverkusen", "postcode": "51381", "cc": "DEU"}


def test_parse_full_address_free_text_fallback():
    assert here.parse_full_address(FULL) == {"query": FULL, "postcode": "", "cc": "DEU"}


def test_postcodes_match():
    assert here.postcodes_match("51381", "51381")
    assert here.postcodes_match("6442 pb", "6442PB")
    assert here.postcodes_match("6442", "6442 PB")
    assert not here.postcodes_match("5138", "51381")
    assert not here.postcodes_match("51380", "51381")


def test_map_here_item():
    m = here.map_here_item(HERE_BORSIG)
    assert m["address_line_1"] == "Borsigstraße 15"
    assert m["district"] == "Leverkusen"
    assert m["state"] == "North Rhine-Westphalia"
    assert m["country"] == "Deutschland"
    assert m["latitude"] == "51.0457"
    assert m["longitude"] == "7.0123"
    assert m["note"] == "houseNumber PA, score 1"


def test_coord_rounds_like_js_to_fixed():
    assert here.coord(1.03125) == "1.0313"  # exact tie: half away from zero
    assert here.coord(-1.03125) == "-1.0313"
    assert here.coord("52.5") == "52.5000"
    assert here.coord("") == ""
    assert here.coord(None) == ""
    assert here.coord("abc") == ""


def test_the_here_key_comes_from_the_shared_settings(board, monkeypatch):
    monkeypatch.setenv("HERE_API_KEY", "key-from-settings")
    here.geocode("Borsigstraße 15, 51381", "DEU")
    assert board.here_queries == [{"q": "Borsigstraße 15, 51381", "in": "countryCode:DEU", "apiKey": "key-from-settings"}]


def test_geocode_without_a_key_raises(monkeypatch):
    monkeypatch.delenv("HERE_API_KEY")
    with pytest.raises(RuntimeError, match="HERE_API_KEY"):
        here.geocode("x")
