"""Upload generated PDFs to Google Drive."""
from __future__ import annotations

import logging
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials

from config import GOOGLE_SHEETS_CREDS_FILE, GOOGLE_DRIVE_FOLDER_ID

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveUploader:
    def __init__(self):
        creds = Credentials.from_service_account_file(
            GOOGLE_SHEETS_CREDS_FILE, scopes=SCOPES
        )
        self.service = build("drive", "v3", credentials=creds)
        self.root_folder_id = GOOGLE_DRIVE_FOLDER_ID

    def upload_file(self, local_path: Path, drive_folder_id: str, filename: str) -> str:
        """Upload a file and return its web view link."""
        media = MediaFileUpload(str(local_path), mimetype="application/pdf")
        metadata = {
            "name": filename,
            "parents": [drive_folder_id],
        }
        file = self.service.files().create(
            body=metadata, media_body=media, fields="id, webViewLink"
        ).execute()

        link = file.get("webViewLink", "")
        logger.info(f"Uploaded {filename} to Drive: {link}")
        return link

    def get_or_create_folder(self, folder_name: str, parent_id: str | None = None) -> str:
        """Get or create a folder in Drive. Returns folder ID."""
        parent = parent_id or self.root_folder_id
        query = (
            f"name = '{folder_name}' and "
            f"'{parent}' in parents and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"trashed = false"
        )
        results = self.service.files().list(
            q=query, fields="files(id, name)", spaces="drive"
        ).execute()

        files = results.get("files", [])
        if files:
            return files[0]["id"]

        metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent],
        }
        folder = self.service.files().create(
            body=metadata, fields="id"
        ).execute()

        logger.info(f"Created Drive folder: {folder_name}")
        return folder["id"]
