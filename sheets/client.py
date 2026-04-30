"""Google Sheets and Drive client initialization."""
from __future__ import annotations

import logging
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from config import (
    GOOGLE_SHEETS_CREDS_FILE, SPREADSHEET_NAME,
    DAILY_HEADERS, AUDIT_HEADERS, MATERIALS_HEADERS, TRACKER_HEADERS,
)

logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsClient:
    def __init__(self):
        self.creds = Credentials.from_service_account_file(
            GOOGLE_SHEETS_CREDS_FILE, scopes=SCOPES
        )
        self.gc = gspread.authorize(self.creds)
        self.spreadsheet = self._get_or_create_spreadsheet()
        self.drive_service = build("drive", "v3", credentials=self.creds)

    def _get_or_create_spreadsheet(self) -> gspread.Spreadsheet:
        try:
            return self.gc.open(SPREADSHEET_NAME)
        except gspread.SpreadsheetNotFound:
            logger.info(f"Creating new spreadsheet: {SPREADSHEET_NAME}")
            ss = self.gc.create(SPREADSHEET_NAME)
            daily = ss.sheet1
            daily.update_title("Daily")
            daily.append_row(DAILY_HEADERS)

            audit = ss.add_worksheet(title="Audit", rows=1000, cols=len(AUDIT_HEADERS))
            audit.append_row(AUDIT_HEADERS)

            materials = ss.add_worksheet(title="Materials", rows=1000, cols=len(MATERIALS_HEADERS))
            materials.append_row(MATERIALS_HEADERS)

            tracker = ss.add_worksheet(title="Tracker", rows=1000, cols=len(TRACKER_HEADERS))
            tracker.append_row(TRACKER_HEADERS)

            return ss

    def get_daily_sheet(self) -> gspread.Worksheet:
        try:
            ws = self.spreadsheet.worksheet("Daily")
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet("Daily", rows=1000, cols=len(DAILY_HEADERS))
            ws.append_row(DAILY_HEADERS)
            return ws
        _ensure_headers(ws, DAILY_HEADERS)
        return ws

    def get_audit_sheet(self) -> gspread.Worksheet:
        try:
            ws = self.spreadsheet.worksheet("Audit")
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet("Audit", rows=1000, cols=len(AUDIT_HEADERS))
            ws.append_row(AUDIT_HEADERS)
            return ws
        _ensure_headers(ws, AUDIT_HEADERS)
        return ws

    def get_materials_sheet(self) -> gspread.Worksheet:
        # Try "Materials" first; fall back to legacy "Applied" tab and rename it.
        try:
            ws = self.spreadsheet.worksheet("Materials")
        except gspread.WorksheetNotFound:
            try:
                ws = self.spreadsheet.worksheet("Applied")
                ws.update_title("Materials")
                logger.info("Renamed 'Applied' tab to 'Materials'")
            except gspread.WorksheetNotFound:
                ws = self.spreadsheet.add_worksheet("Materials", rows=1000, cols=len(MATERIALS_HEADERS))
                ws.append_row(MATERIALS_HEADERS)
                return ws
        _ensure_headers(ws, MATERIALS_HEADERS)
        return ws

    def get_tracker_sheet(self) -> gspread.Worksheet:
        try:
            ws = self.spreadsheet.worksheet("Tracker")
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet("Tracker", rows=1000, cols=len(TRACKER_HEADERS))
            ws.append_row(TRACKER_HEADERS)
            return ws
        _ensure_headers(ws, TRACKER_HEADERS)
        return ws

    # Legacy alias so existing callers don't break during transition
    def get_applied_sheet(self) -> gspread.Worksheet:
        return self.get_materials_sheet()


def _ensure_headers(ws: gspread.Worksheet, expected: list[str]) -> None:
    """Insert the expected header row at row 1 if it isn't already there."""
    first_row = ws.row_values(1)
    if first_row and first_row[0] == expected[0]:
        return
    ws.insert_row(expected, index=1)
    logger.warning(f"Restored missing header row on '{ws.title}'")
