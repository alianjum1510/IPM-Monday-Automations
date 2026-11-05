# Per-board column IDs and status labels. monday regenerates column IDs when a
# board is duplicated, so each board needs its own mapping.
#
# The old app read COLUMN_*_ID, DONE_STATUS_LABEL, STUCK_STATUS_LABEL and
# DEFAULT_BOARD_ID at import time. Here they carry an ADDRESS_ prefix (the
# deployment is shared: DEFAULT_BOARD_ID is another feature's name) and are
# read when a request runs, so settings from monday-code are seen.
from app.core.config import setting

# The original board's overrides, as (column key, setting name, default).
ORIGINAL_BOARD_COLUMNS = (
    ("full_address",   "ADDRESS_COLUMN_FULL_ADDRESS_ID",   "text_mkw9pw3m"),     # Vollständige Adresse (legal)
    ("address_line_1", "ADDRESS_COLUMN_ADDRESS_LINE_1_ID", "text_mkw9v8an"),     # Adresszeile 1 (Legal)
    ("postcode",       "ADDRESS_COLUMN_POSTCODE_ID",       "text_mkxqtbr0"),     # Postleitzahl (legal)
    ("city",           "ADDRESS_COLUMN_CITY_ID",           "text_mkyw1a7a"),     # Ort
    ("district",       "ADDRESS_COLUMN_DISTRICT_ID",       "text_mkx4mpvc"),     # Landkreis / Kreis (legal)
    ("state",          "ADDRESS_COLUMN_STATE_ID",          "text_mkx5m5c3"),     # Bundesland (legal)
    ("country",        "ADDRESS_COLUMN_COUNTRY_ID",        "text_mkywm44h"),     # Land
    ("latitude",       "ADDRESS_COLUMN_LATITUDE_ID",       "numeric_mkw9x7h5"),  # Breitengrad (legal)
    ("longitude",      "ADDRESS_COLUMN_LONGITUDE_ID",      "numeric_mkw94cck"),  # Längengrad (legal)
    ("location",       "ADDRESS_COLUMN_LOCATION_ID",       None),                # Location (set via env on monday)
    ("status",         "ADDRESS_COLUMN_STATUS_ID",         "color_mm0851fj"),    # Match Zipcode
)

# Every setting this module reads - loaded at startup (Feature.optional_settings).
SETTINGS = (
    *(name for _, name, _ in ORIGINAL_BOARD_COLUMNS),
    "ADDRESS_DONE_STATUS_LABEL",
    "ADDRESS_STUCK_STATUS_LABEL",
    "ADDRESS_DEFAULT_BOARD_ID",
)


def boards():
    return {
        # Address Master Board (original). IDs can be overridden with the ADDRESS_COLUMN_*
        # settings; the live app sets the location column's id.
        "5063711037": {
            "columns": {key: setting(name) or default for key, name, default in ORIGINAL_BOARD_COLUMNS},
            "labels": {
                "done":  setting("ADDRESS_DONE_STATUS_LABEL", default="Done"),
                "stuck": setting("ADDRESS_STUCK_STATUS_LABEL", default="Stuck"),
            },
        },
        # Address Master Board (replica)
        "5090777446": {
            "columns": {
                "full_address":   "text_mkzzbqtq",    # Vollständige Adresse          — TRIGGER (mode "address")
                "address_line_1": "text_mkzzhve4",    # Adresszeile 1                 — TRIGGER (mode "fields")
                "postcode":       "text_mkzzxn2",     # Postcode                      — TRIGGER (mode "fields")
                "city":           "text_mkzza1ky",    # Ort
                "district":       "text_mm00ck6x",    # Landkreis / Kreis
                "state":          "text_mm00gat6",    # Bundesland
                "country":        "text_mm002s0c",    # Land
                "latitude":       "text_mm00sfst",    # Breitengrad
                "longitude":      "text_mm00m1qf",    # Längengrad
                "location":       "location_mm4s5wm1",
                "status":         "color_mm00ymfp",   # Address Check
            },
            "labels": {"done": "Complete", "stuck": "Stuck"},
        },
        # ✅ (Dev) Sandbox Address Master Board. Duplicated from the original, so it kept
        # its column IDs; only the location column is new.
        "5099246179": {
            "columns": {
                "full_address":   "text_mkw9pw3m",    # ✅Vollständige Adresse (legal) — TRIGGER (mode "address")
                "address_line_1": "text_mkw9v8an",    # ✅Adresszeile 1 (Legal)        — TRIGGER (mode "fields")
                "address_line_2": "text_mkw9et45",    # ✅Adresszeile 2 (Legal)        — HERE's Ortsteil, only when empty
                "postcode":       "text_mkxqtbr0",    # ✅Postleitzahl (legal)         — TRIGGER (mode "fields")
                "city":           "text_mkyw1a7a",    # ✅Ort
                "district":       "text_mkx4mpvc",    # ✅Landkreis / Kreis (legal)
                "state":          "text_mkx5m5c3",    # ✅Bundesland (legal)
                "country":        "text_mkywm44h",    # Land (text)
                "country_flag":   "country_mm2ghytw", # ✅Land (country column, flag)
                "latitude":       "numeric_mkw9x7h5", # ✅Breitengrad (legal)
                "longitude":      "numeric_mkw94cck", # ✅Längengrad (legal)
                "location":       "location_mm8m8p0w",
                "status":         "color_mm0851fj",   # Match Zipcode
            },
            "labels": {"done": "Done", "stuck": "Stuck"},
        },
        # ✅Sandbox Address Master Board (English columns). Same IDs as the original except
        # location. Its color_mm0851fj is "Get Sales Area" (one label, "Fetch Sales Area",
        # used by another automation), so this board has no address status column.
        "5094089644": {
            "columns": {
                "full_address":   "text_mkw9pw3m",    # ✅Complete Address — TRIGGER (mode "address")
                "address_line_1": "text_mkw9v8an",    # ✅Address Line 1   — TRIGGER (mode "fields")
                "address_line_2": "text_mkw9et45",    # ✅Address Line 2   — HERE's Ortsteil, only when empty
                "postcode":       "text_mkxqtbr0",    # ✅Postcode (text)  — TRIGGER (mode "fields")
                "city":           "text_mkyw1a7a",    # ✅City
                "district":       "text_mkx4mpvc",    # ✅Province
                "state":          "text_mkx5m5c3",    # ✅State
                "country":        "text_mkywm44h",    # Land (text)
                "country_flag":   "country_mm2ghytw", # ✅Country (country column, flag)
                "latitude":       "numeric_mkw9x7h5", # ✅Latitude
                "longitude":      "numeric_mkw94cck", # ✅Longitude
                "location":       "location_mm4sptqw",
                "status":         None,
            },
            "labels": {"done": "Done", "stuck": "Stuck"},
        },
    }


def default_board_id():
    """Board used when an item's board isn't in the map."""
    return setting("ADDRESS_DEFAULT_BOARD_ID", default="5063711037")


def get_board_config(board_id):
    all_boards = boards()
    return all_boards.get(str(board_id)) or all_boards[default_board_id()]


# Column IDs are globally unique in monday, so these lists can span boards.
def address_trigger_ids():
    return [b["columns"]["full_address"] for b in boards().values()]


def field_trigger_ids():
    return [
        col for b in boards().values()
        for col in (b["columns"]["address_line_1"], b["columns"]["postcode"])
    ]


# Fields that must be filled for the status to be Done/Complete.
REQUIRED_FIELDS = [
    {"key": "address_line_1", "label": "Adresszeile 1"},
    {"key": "postcode",       "label": "Postcode"},
    {"key": "city",           "label": "Ort"},
    {"key": "country",        "label": "Land"},
]
