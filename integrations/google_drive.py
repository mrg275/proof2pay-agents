"""
Google Drive integration.
Reads and writes files from the shared Proof2Pay knowledge base folder.
"""

import os
import io
import json
import logging
from typing import Optional
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]


class GoogleDriveClient:
    """Client for reading/writing files from the shared Google Drive folder."""

    def __init__(self):
        creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "./config/google_credentials.json")
        self.root_folder_id = os.environ.get("GDRIVE_ROOT_FOLDER_ID", "")

        if not os.path.exists(creds_path):
            logger.warning(f"Google credentials not found at {creds_path}. Drive integration disabled.")
            self.service = None
            return

        credentials = service_account.Credentials.from_service_account_file(
            creds_path, scopes=SCOPES
        )
        self.service = build("drive", "v3", credentials=credentials)
        logger.info("Google Drive client initialized")

        # Cache subfolder IDs
        self._folder_cache = {}

    def _get_subfolder_id(self, folder_name: str) -> Optional[str]:
        """Get the ID of a subfolder within the root knowledge base folder."""
        if not self.service:
            return None

        if folder_name in self._folder_cache:
            return self._folder_cache[folder_name]

        results = (
            self.service.files()
            .list(
                q=f"'{self.root_folder_id}' in parents and name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="files(id, name)",
            )
            .execute()
        )

        files = results.get("files", [])
        if files:
            folder_id = files[0]["id"]
            self._folder_cache[folder_name] = folder_id
            return folder_id

        logger.warning(f"Subfolder '{folder_name}' not found in Drive")
        return None

    def upload_file(
        self,
        filename: str,
        content: str,
        subfolder: str,
        mime_type: str = "text/plain",
    ) -> Optional[str]:
        """
        Upload a file to a subfolder in the knowledge base.

        Returns the file ID if successful, None otherwise.
        """
        if not self.service:
            logger.warning("Drive not initialized, skipping upload")
            return None

        folder_id = self._get_subfolder_id(subfolder)
        if not folder_id:
            logger.error(f"Cannot upload: subfolder '{subfolder}' not found")
            return None

        file_metadata = {
            "name": filename,
            "parents": [folder_id],
        }

        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype=mime_type,
        )

        try:
            file = (
                self.service.files()
                .create(body=file_metadata, media_body=media, fields="id")
                .execute()
            )
            file_id = file.get("id")
            logger.info(f"Uploaded {filename} to {subfolder} (ID: {file_id})")
            return file_id

        except Exception as e:
            logger.error(f"Failed to upload {filename}: {e}")
            return None

    def upload_metadata(
        self,
        document_name: str,
        subfolder: str,
        metadata: dict,
    ) -> Optional[str]:
        """Upload a metadata JSON file alongside a document."""
        meta_filename = f"{Path(document_name).stem}_metadata.json"
        content = json.dumps(metadata, indent=2)
        return self.upload_file(meta_filename, content, subfolder, "application/json")

    def list_files(self, subfolder: str, max_results: int = 50) -> list[dict]:
        """List files in a subfolder."""
        if not self.service:
            return []

        folder_id = self._get_subfolder_id(subfolder)
        if not folder_id:
            return []

        try:
            results = (
                self.service.files()
                .list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    fields="files(id, name, mimeType, modifiedTime, size)",
                    pageSize=max_results,
                    orderBy="modifiedTime desc",
                )
                .execute()
            )
            return results.get("files", [])

        except Exception as e:
            logger.error(f"Failed to list files in {subfolder}: {e}")
            return []

    def read_file(self, file_id: str) -> Optional[str]:
        """Read a text file's content by ID."""
        if not self.service:
            return None

        try:
            request = self.service.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)

            done = False
            while not done:
                _, done = downloader.next_chunk()

            return buffer.getvalue().decode("utf-8")

        except Exception as e:
            logger.error(f"Failed to read file {file_id}: {e}")
            return None

    def search_files(self, query: str, subfolder: Optional[str] = None) -> list[dict]:
        """Search for files by name in the knowledge base."""
        if not self.service:
            return []

        parent_id = self.root_folder_id
        if subfolder:
            parent_id = self._get_subfolder_id(subfolder) or self.root_folder_id

        try:
            q = f"name contains '{query}' and '{parent_id}' in parents and trashed=false"
            results = (
                self.service.files()
                .list(
                    q=q,
                    fields="files(id, name, mimeType, modifiedTime)",
                    pageSize=20,
                )
                .execute()
            )
            return results.get("files", [])

        except Exception as e:
            logger.error(f"Failed to search files: {e}")
            return []

    def get_knowledge_index(self) -> str:
        """Read the master knowledge index file."""
        files = self.list_files("Knowledge Index", max_results=5)
        for f in files:
            if "index" in f["name"].lower():
                content = self.read_file(f["id"])
                if content:
                    return content
        return ""

    def update_knowledge_index(self, content: str):
        """Update or create the master knowledge index."""
        self.upload_file(
            "knowledge_index.md",
            content,
            "Knowledge Index",
            "text/markdown",
        )
