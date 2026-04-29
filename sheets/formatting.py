"""Sheet formatting — colors, column widths, frozen headers, dropdowns, conditional formatting."""
from __future__ import annotations

import logging
from gspread import Worksheet, Spreadsheet
from gspread.utils import rowcol_to_a1

logger = logging.getLogger(__name__)


def _rgb(r: int, g: int, b: int) -> dict:
    return {"red": r / 255, "green": g / 255, "blue": b / 255}


# ── Color Palette ────────────────────────────────────────────
HEADER_BG = _rgb(26, 26, 46)        # Dark navy
HEADER_FG = _rgb(255, 255, 255)     # White text
APPLY_GREEN = _rgb(216, 243, 220)   # Light green for APPLY
MAYBE_YELLOW = _rgb(255, 243, 205)  # Light yellow for MAYBE
SKIP_RED = _rgb(255, 218, 218)      # Light red for SKIP
REJECTED_GRAY = _rgb(240, 240, 240) # Light gray for Audit
APPLIED_BLUE = _rgb(219, 234, 254)  # Light blue for Applied
ROW_ALT = _rgb(248, 249, 250)       # Alternating row stripe


def format_all_sheets(spreadsheet: Spreadsheet) -> None:
    """Apply formatting to all three tabs."""
    try:
        daily = spreadsheet.worksheet("Daily")
        format_daily(spreadsheet, daily)
    except Exception as e:
        logger.warning(f"Daily formatting failed: {e}")

    try:
        audit = spreadsheet.worksheet("Audit")
        format_audit(spreadsheet, audit)
    except Exception as e:
        logger.warning(f"Audit formatting failed: {e}")

    try:
        applied = spreadsheet.worksheet("Applied")
        format_applied(spreadsheet, applied)
    except Exception as e:
        logger.warning(f"Applied formatting failed: {e}")

    logger.info("Sheet formatting applied")


def _clear_banding(spreadsheet: Spreadsheet, sheet_id: int) -> None:
    """Remove existing banding before re-applying."""
    try:
        meta = spreadsheet.fetch_sheet_metadata()
        for sheet in meta.get("sheets", []):
            if sheet["properties"]["sheetId"] == sheet_id:
                for banding in sheet.get("bandedRanges", []):
                    spreadsheet.batch_update({"requests": [{
                        "deleteBanding": {"bandedRangeId": banding["bandedRangeId"]}
                    }]})
    except Exception:
        pass  # No banding to clear


def format_daily(spreadsheet: Spreadsheet, ws: Worksheet) -> None:
    """Format the Daily tab."""
    sheet_id = ws.id
    _clear_banding(spreadsheet, sheet_id)
    requests = []

    # Freeze header row
    requests.append(_freeze_rows(sheet_id, 1))

    # Header style: dark navy bg, white bold text (15 columns)
    requests.append(_header_format(sheet_id, 15))

    # Column widths — Risk Flags after Status, Sponsorship before Salary
    widths = [
        (0, 160),   # Company
        (1, 220),   # Job Title
        (2, 150),   # Location
        (3, 90),    # Confidence
        (4, 90),    # Status
        (5, 180),   # Risk Flags
        (6, 250),   # Apply Link
        (7, 90),    # Posted (e.g. "3h ago")
        (8, 130),   # Source
        (9, 300),   # AI Reasoning
        (10, 140),  # Suggested Angle
        (11, 180),  # Match Signals
        (12, 130),  # Sponsorship
        (13, 120),  # Salary Range
        (14, 150),  # Notes
    ]
    for col, width in widths:
        requests.append(_col_width(sheet_id, col, width))

    # Status dropdown (col 4): Apply, Skip, Maybe, Bookmark
    requests.append(_data_validation(
        sheet_id, col=4, values=["Apply", "Skip", "Maybe", "Bookmark"]
    ))

    # Conditional formatting on Status column (col 4)
    requests.append(_cond_format_text(sheet_id, col=4, text="Apply", bg=APPLY_GREEN))
    requests.append(_cond_format_text(sheet_id, col=4, text="Skip", bg=SKIP_RED))
    requests.append(_cond_format_text(sheet_id, col=4, text="Maybe", bg=MAYBE_YELLOW))

    # Conditional formatting on Confidence column (col 3): green for 4-5, yellow 3, red 1-2
    requests.append(_cond_format_number(sheet_id, col=3, op="NUMBER_GREATER_THAN_EQ", value="4", bg=APPLY_GREEN))
    requests.append(_cond_format_number(sheet_id, col=3, op="NUMBER_EQ", value="3", bg=MAYBE_YELLOW))
    requests.append(_cond_format_number(sheet_id, col=3, op="NUMBER_LESS_THAN_EQ", value="2", bg=SKIP_RED))

    # Alternating row colors
    requests.append(_banding(sheet_id, 15))

    spreadsheet.batch_update({"requests": requests})


def format_audit(spreadsheet: Spreadsheet, ws: Worksheet) -> None:
    """Format the Audit tab."""
    sheet_id = ws.id
    _clear_banding(spreadsheet, sheet_id)
    requests = []

    requests.append(_freeze_rows(sheet_id, 1))
    requests.append(_header_format(sheet_id, 6))

    widths = [
        (0, 160),   # Company
        (1, 200),   # Job Title
        (2, 160),   # Killed At
        (3, 350),   # Reason
        (4, 130),   # Source
        (5, 250),   # Apply Link
    ]
    for col, width in widths:
        requests.append(_col_width(sheet_id, col, width))

    requests.append(_banding(sheet_id, 6))

    spreadsheet.batch_update({"requests": requests})


def format_applied(spreadsheet: Spreadsheet, ws: Worksheet) -> None:
    """Format the Applied tab."""
    sheet_id = ws.id
    _clear_banding(spreadsheet, sheet_id)
    requests = []

    requests.append(_freeze_rows(sheet_id, 1))
    requests.append(_header_format(sheet_id, 14))

    widths = [
        (0, 100),   # Date Applied
        (1, 160),   # Company
        (2, 220),   # Job Title
        (3, 130),   # Location
        (4, 220),   # Resume Link
        (5, 220),   # Cover Letter Link
        (6, 250),   # Apply Link
        (7, 150),   # Angle Used
        (8, 80),    # Screen Confidence
        (9, 130),   # Source
        (10, 120),  # Status
        (11, 100),  # Follow-up Date
        (12, 90),   # Follow-up Sent
        (13, 200),  # Notes
    ]
    for col, width in widths:
        requests.append(_col_width(sheet_id, col, width))

    # Status dropdown (col 10 = column K)
    requests.append(_data_validation(
        sheet_id, col=10,
        values=["Ready to Apply", "Applied", "Phone Screen", "Interview", "Offer", "Rejected", "No Response"]
    ))

    # Follow-up Sent dropdown (col 12 = column M)
    requests.append(_data_validation(sheet_id, col=12, values=["No", "Yes"]))

    # Row-level conditional formatting — entire row colored by Status (col K = index 10).
    # Each status gets a distinct vibrant color; Ready to Apply stays plain white.
    row_rules = [
        ("No Response",  _rgb(229, 231, 235)),   # gray-200   — faded, ghosted
        ("Rejected",     _rgb(254, 202, 202)),   # red-200    — clear red
        ("Applied",      _rgb(191, 219, 254)),   # blue-200   — calm blue, in-flight
        ("Phone Screen", _rgb(253, 230, 138)),   # amber-200  — warm amber, heating up
        ("Interview",    _rgb(221, 214, 254)),   # violet-200 — vibrant purple, exciting
        ("Offer",        _rgb(187, 247, 208)),   # green-200  — bright green, celebrate
    ]
    for status_text, bg in row_rules:
        requests.append(_row_cond_format(sheet_id, 14, f'=$K2="{status_text}"', bg))

    spreadsheet.batch_update({"requests": requests})


# ── Helper functions ─────────────────────────────────────────

def _freeze_rows(sheet_id: int, rows: int) -> dict:
    return {
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": rows},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    }


def _header_format(sheet_id: int, num_cols: int) -> dict:
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": num_cols,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": HEADER_BG,
                    "textFormat": {
                        "foregroundColor": HEADER_FG,
                        "bold": True,
                        "fontSize": 10,
                    },
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "padding": {"top": 6, "bottom": 6, "left": 4, "right": 4},
                    "wrapStrategy": "WRAP",
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,padding,wrapStrategy)",
        }
    }


def _col_width(sheet_id: int, col: int, width: int) -> dict:
    return {
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": col,
                "endIndex": col + 1,
            },
            "properties": {"pixelSize": width},
            "fields": "pixelSize",
        }
    }


def _data_validation(sheet_id: int, col: int, values: list[str]) -> dict:
    return {
        "setDataValidation": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1, "endRowIndex": 1000,
                "startColumnIndex": col, "endColumnIndex": col + 1,
            },
            "rule": {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": v} for v in values],
                },
                "showCustomUi": True,
                "strict": False,
            },
        }
    }


def _cond_format_text(sheet_id: int, col: int, text: str, bg: dict) -> dict:
    return {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [{
                    "sheetId": sheet_id,
                    "startRowIndex": 1, "endRowIndex": 1000,
                    "startColumnIndex": col, "endColumnIndex": col + 1,
                }],
                "booleanRule": {
                    "condition": {
                        "type": "TEXT_EQ",
                        "values": [{"userEnteredValue": text}],
                    },
                    "format": {"backgroundColor": bg},
                },
            },
            "index": 0,
        }
    }


def _cond_format_number(sheet_id: int, col: int, op: str, value: str, bg: dict) -> dict:
    return {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [{
                    "sheetId": sheet_id,
                    "startRowIndex": 1, "endRowIndex": 1000,
                    "startColumnIndex": col, "endColumnIndex": col + 1,
                }],
                "booleanRule": {
                    "condition": {
                        "type": op,
                        "values": [{"userEnteredValue": value}],
                    },
                    "format": {"backgroundColor": bg},
                },
            },
            "index": 0,
        }
    }


def _row_cond_format(sheet_id: int, num_cols: int, formula: str, bg: dict) -> dict:
    """Conditional format that colors the entire row based on a custom formula."""
    return {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [{
                    "sheetId": sheet_id,
                    "startRowIndex": 1, "endRowIndex": 1000,
                    "startColumnIndex": 0, "endColumnIndex": num_cols,
                }],
                "booleanRule": {
                    "condition": {
                        "type": "CUSTOM_FORMULA",
                        "values": [{"userEnteredValue": formula}],
                    },
                    "format": {"backgroundColor": bg},
                },
            },
            "index": 0,
        }
    }


def _banding(sheet_id: int, num_cols: int) -> dict:
    return {
        "addBanding": {
            "bandedRange": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1000,
                    "startColumnIndex": 0,
                    "endColumnIndex": num_cols,
                },
                "rowProperties": {
                    "headerColor": HEADER_BG,
                    "firstBandColor": _rgb(255, 255, 255),
                    "secondBandColor": ROW_ALT,
                },
            }
        }
    }
