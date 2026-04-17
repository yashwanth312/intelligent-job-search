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


def format_daily(spreadsheet: Spreadsheet, ws: Worksheet) -> None:
    """Format the Daily tab."""
    sheet_id = ws.id
    requests = []

    # Freeze header row
    requests.append(_freeze_rows(sheet_id, 1))

    # Header style: dark navy bg, white bold text
    requests.append(_header_format(sheet_id, 14))  # 14 columns

    # Column widths
    widths = [
        (0, 100),   # Date Scraped
        (1, 160),   # Company
        (2, 200),   # Job Title
        (3, 150),   # Location
        (4, 130),   # Source
        (5, 80),    # Confidence
        (6, 300),   # AI Reasoning
        (7, 140),   # Suggested Angle
        (8, 180),   # Risk Flags
        (9, 180),   # Match Signals
        (10, 120),  # Salary Range
        (11, 250),  # Apply Link
        (12, 90),   # Status
        (13, 150),  # Notes
    ]
    for col, width in widths:
        requests.append(_col_width(sheet_id, col, width))

    # Status dropdown: Apply, Skip, Maybe, Bookmark
    requests.append(_data_validation(
        sheet_id, col=12, values=["Apply", "Skip", "Maybe", "Bookmark"]
    ))

    # Conditional formatting on Status column (M = col 12)
    requests.append(_cond_format_text(sheet_id, col=12, text="Apply", bg=APPLY_GREEN))
    requests.append(_cond_format_text(sheet_id, col=12, text="Skip", bg=SKIP_RED))
    requests.append(_cond_format_text(sheet_id, col=12, text="Maybe", bg=MAYBE_YELLOW))

    # Conditional formatting on Confidence column (F = col 5): green for 4-5, yellow 3, red 1-2
    requests.append(_cond_format_number(sheet_id, col=5, op="NUMBER_GREATER_THAN_EQ", value="4", bg=APPLY_GREEN))
    requests.append(_cond_format_number(sheet_id, col=5, op="NUMBER_EQ", value="3", bg=MAYBE_YELLOW))
    requests.append(_cond_format_number(sheet_id, col=5, op="NUMBER_LESS_THAN_EQ", value="2", bg=SKIP_RED))

    # Alternating row colors
    requests.append(_banding(sheet_id))

    spreadsheet.batch_update({"requests": requests})


def format_audit(spreadsheet: Spreadsheet, ws: Worksheet) -> None:
    """Format the Audit tab."""
    sheet_id = ws.id
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

    requests.append(_banding(sheet_id))

    spreadsheet.batch_update({"requests": requests})


def format_applied(spreadsheet: Spreadsheet, ws: Worksheet) -> None:
    """Format the Applied tab."""
    sheet_id = ws.id
    requests = []

    requests.append(_freeze_rows(sheet_id, 1))
    requests.append(_header_format(sheet_id, 15))

    widths = [
        (0, 100),   # Date Applied
        (1, 160),   # Company
        (2, 200),   # Job Title
        (3, 130),   # Location
        (4, 200),   # Resume Link
        (5, 200),   # Cover Letter Link
        (6, 250),   # Apply Link
        (7, 140),   # Angle Used
        (8, 80),    # Screen Confidence
        (9, 130),   # Source
        (10, 110),  # Status
        (11, 80),   # Days Waiting
        (12, 100),  # Follow-up Date
        (13, 90),   # Follow-up Sent
        (14, 150),  # Notes
    ]
    for col, width in widths:
        requests.append(_col_width(sheet_id, col, width))

    # Status dropdown
    requests.append(_data_validation(
        sheet_id, col=10,
        values=["Ready to Apply", "Applied", "Phone Screen", "Interview", "Offer", "Rejected", "No Response"]
    ))

    # Follow-up Sent dropdown
    requests.append(_data_validation(sheet_id, col=13, values=["No", "Yes"]))

    # Conditional formatting on Status
    requests.append(_cond_format_text(sheet_id, col=10, text="Offer", bg=APPLY_GREEN))
    requests.append(_cond_format_text(sheet_id, col=10, text="Interview", bg=APPLY_GREEN))
    requests.append(_cond_format_text(sheet_id, col=10, text="Phone Screen", bg=MAYBE_YELLOW))
    requests.append(_cond_format_text(sheet_id, col=10, text="Rejected", bg=SKIP_RED))
    requests.append(_cond_format_text(sheet_id, col=10, text="No Response", bg=REJECTED_GRAY))
    requests.append(_cond_format_text(sheet_id, col=10, text="Applied", bg=APPLIED_BLUE))

    requests.append(_banding(sheet_id))

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


def _banding(sheet_id: int) -> dict:
    return {
        "addBanding": {
            "bandedRange": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                },
                "rowProperties": {
                    "headerColor": HEADER_BG,
                    "firstBandColor": _rgb(255, 255, 255),
                    "secondBandColor": ROW_ALT,
                },
            }
        }
    }
