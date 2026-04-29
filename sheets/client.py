"""Google Sheets and Drive client initialization."""
from __future__ import annotations

import logging
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from config import (
    GOOGLE_SHEETS_CREDS_FILE, SPREADSHEET_NAME,
    DAILY_HEADERS, AUDIT_HEADERS, APPLIED_HEADERS,
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

            applied = ss.add_worksheet(title="Applied", rows=1000, cols=len(APPLIED_HEADERS))
            applied.append_row(APPLIED_HEADERS)

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

    def get_applied_sheet(self) -> gspread.Worksheet:
        try:
            ws = self.spreadsheet.worksheet("Applied")
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet("Applied", rows=1000, cols=len(APPLIED_HEADERS))
            ws.append_row(APPLIED_HEADERS)
            return ws
        _ensure_headers(ws, APPLIED_HEADERS)
        return ws


def _ensure_headers(ws: gspread.Worksheet, expected: list[str]) -> None:
    """Insert the expected header row at row 1 if it isn't already there.

    Detects a missing header by checking row 1's first cell against the first
    expected header. If the sheet is empty or row 1 holds data instead of
    headers (e.g. user cleared the tab), the headers are prepended and any
    existing data is pushed down.
    """
    first_row = ws.row_values(1)
    if first_row and first_row[0] == expected[0]:
        return
    ws.insert_row(expected, index=1)
    logger.warning(f"Restored missing header row on '{ws.title}'")
