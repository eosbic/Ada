"""
Ingesta automática de Drive (Google Drive / OneDrive) -> pipelines de analisis -> Qdrant.
"""

import io
import os
import asyncio
from typing import List, Dict, Tuple

from sqlalchemy import text
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from api.database import AsyncSessionLocal
from api.services.tenant_credentials import get_google_credentials
from api.agents.document_agent import document_agent
from api.agents.excel_agent import excel_agent
from api.agents.image_agent import image_agent


EXCEL_EXTENSIONS = {".xlsx", ".xls", ".csv"}
DOC_EXTENSIONS = {".pdf", ".txt", ".docx", ".doc"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


async def _ensure_state_table():
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS drive_ingestion_state (
                    empresa_id UUID NOT NULL,
                    file_id TEXT NOT NULL,
                    file_name TEXT,
                    modified_time TEXT NOT NULL,
                    processed_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (empresa_id, file_id)
                )
                """
            )
        )
        await db.commit()


async def _list_drive_tenants() -> List[Tuple[str, str]]:
    """Retorna lista de (empresa_id, provider) con Drive activo."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                """
                SELECT DISTINCT empresa_id, provider
                FROM tenant_credentials
                WHERE provider IN ('google_drive', 'google_shared_drive', 'onedrive', 'sharepoint')
                  AND is_active = TRUE
                """
            )
        )
        rows = result.fetchall()
    return [(str(r.empresa_id), r.provider) for r in rows]


def _build_drive_service(empresa_id: str, provider: str = "google_drive", user_id: str = ""):
    creds_data = get_google_credentials(empresa_id, provider, user_id=user_id)
    if "error" in creds_data:
        return None, creds_data["error"]

    creds = Credentials(
        token=creds_data.get("access_token"),
        refresh_token=creds_data.get("refresh_token"),
        client_id=creds_data.get("client_id"),
        client_secret=creds_data.get("client_secret"),
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False), ""


def _download_file_bytes(service, file_id: str) -> bytes:
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return fh.getvalue()


async def _already_processed(empresa_id: str, file_id: str, modified_time: str) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                """
                SELECT modified_time
                FROM drive_ingestion_state
                WHERE empresa_id = :eid AND file_id = :fid
                """
            ),
            {"eid": empresa_id, "fid": file_id},
        )
        row = result.fetchone()
    return bool(row and row.modified_time == modified_time)


async def _mark_processed(empresa_id: str, file_id: str, file_name: str, modified_time: str):
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                """
                INSERT INTO drive_ingestion_state (empresa_id, file_id, file_name, modified_time)
                VALUES (:eid, :fid, :fname, :mtime)
                ON CONFLICT (empresa_id, file_id)
                DO UPDATE SET
                    file_name = EXCLUDED.file_name,
                    modified_time = EXCLUDED.modified_time,
                    processed_at = NOW()
                """
            ),
            {"eid": empresa_id, "fid": file_id, "fname": file_name, "mtime": modified_time},
        )
        await db.commit()


def _ext(file_name: str) -> str:
    return "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""


def _dispatch_ingestion(empresa_id: str, file_name: str, file_bytes: bytes):
    ext = _ext(file_name)
    instruction = "Documento ingerido automaticamente desde Drive."

    if ext in EXCEL_EXTENSIONS:
        return excel_agent.invoke(
            {
                "file_bytes": file_bytes,
                "file_name": file_name,
                "empresa_id": empresa_id,
                "user_id": "",
                "user_instruction": instruction,
                "industry_type": "generic",
            }
        )

    if ext in DOC_EXTENSIONS:
        return document_agent.invoke(
            {
                "file_bytes": file_bytes,
                "file_name": file_name,
                "empresa_id": empresa_id,
                "user_id": "",
                "user_instruction": instruction,
            }
        )

    if ext in IMAGE_EXTENSIONS:
        mime_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }.get(ext, "image/jpeg")
        return image_agent.invoke(
            {
                "file_bytes": file_bytes,
                "file_name": file_name,
                "mime_type": mime_type,
                "empresa_id": empresa_id,
                "user_id": "",
                "user_instruction": instruction,
            }
        )

    return {"status": "skipped", "reason": f"extension_not_supported:{ext}"}


def _list_onedrive_files(empresa_id: str, folder_path: str = "", provider: str = "onedrive", user_id: str = "") -> List[Dict]:
    """Lista archivos en OneDrive/SharePoint vía Microsoft Graph."""
    try:
        from api.mcp_servers.mcp_microsoft365_server import m365_drive_list
        from api.services.tenant_credentials import get_microsoft_credentials
        creds = get_microsoft_credentials(empresa_id, provider, user_id=user_id)
        if "error" in creds:
            print(f"DRIVE INGESTION OneDrive creds error {empresa_id}: {creds['error']}")
            return []
        token = creds["access_token"]
        return asyncio.run(m365_drive_list(token, path=folder_path))
    except Exception as e:
        print(f"DRIVE INGESTION OneDrive list error {empresa_id}: {e}")
        return []


def _download_onedrive_file(empresa_id: str, file_id: str, provider: str = "onedrive", user_id: str = "") -> bytes:
    """Descarga archivo de OneDrive/SharePoint vía Microsoft Graph."""
    import httpx
    from api.services.tenant_credentials import get_microsoft_credentials
    creds = get_microsoft_credentials(empresa_id, provider, user_id=user_id)
    if "error" in creds:
        raise RuntimeError(creds["error"])
    token = creds["access_token"]

    resp = httpx.get(
        f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}/content",
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


async def _ingest_google_drive(empresa_id: str, folder_id: str, provider: str = "google_drive", user_id: str = ""):
    """Ingesta de archivos desde Google Drive / Shared Drive."""
    service, err = _build_drive_service(empresa_id, provider=provider, user_id=user_id)
    if err:
        print(f"DRIVE INGESTION Google {empresa_id}: {err}")
        return

    try:
        result = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="files(id,name,modifiedTime,mimeType)",
            pageSize=30,
            orderBy="modifiedTime desc",
        ).execute()
        files: List[Dict] = result.get("files", [])
    except Exception as e:
        print(f"DRIVE INGESTION list error {empresa_id}: {e}")
        return

    for f in files:
        file_id = f.get("id", "")
        file_name = f.get("name", "archivo")
        modified_time = f.get("modifiedTime", "")
        if not file_id or not modified_time:
            continue

        if await _already_processed(empresa_id, file_id, modified_time):
            continue

        try:
            blob = _download_file_bytes(service, file_id)
            _dispatch_ingestion(empresa_id, file_name, blob)
            await _mark_processed(empresa_id, file_id, file_name, modified_time)
            print(f"DRIVE INGESTION OK: {empresa_id} -> {file_name}")
        except Exception as e:
            print(f"DRIVE INGESTION file error {empresa_id}/{file_name}: {e}")


async def _ingest_onedrive(empresa_id: str, folder_path: str, provider: str = "onedrive", user_id: str = ""):
    """Ingesta de archivos desde OneDrive/SharePoint."""
    files = _list_onedrive_files(empresa_id, folder_path, provider=provider, user_id=user_id)

    for f in files:
        file_id = f.get("id", "")
        file_name = f.get("name", "archivo")
        modified_time = f.get("modified", "")
        is_folder = f.get("is_folder", False)

        if is_folder or not file_id:
            continue

        if await _already_processed(empresa_id, file_id, modified_time):
            continue

        try:
            blob = _download_onedrive_file(empresa_id, file_id, provider=provider, user_id=user_id)
            _dispatch_ingestion(empresa_id, file_name, blob)
            await _mark_processed(empresa_id, file_id, file_name, modified_time)
            print(f"DRIVE INGESTION OneDrive OK: {empresa_id} -> {file_name}")
        except Exception as e:
            print(f"DRIVE INGESTION OneDrive file error {empresa_id}/{file_name}: {e}")


async def run_drive_ingestion_once():
    folder_id = os.getenv("DRIVE_INGESTION_FOLDER_ID", "") or os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
    folder_id = folder_id.strip()
    onedrive_folder = os.getenv("ONEDRIVE_INGESTION_FOLDER", "").strip()

    if not folder_id and not onedrive_folder:
        return

    await _ensure_state_table()

    tenants = await _list_drive_tenants()
    if not tenants:
        return

    for empresa_id, provider in tenants:
        if provider in ("google_drive", "google_shared_drive") and folder_id:
            await _ingest_google_drive(empresa_id, folder_id, provider=provider)
        elif provider in ("onedrive", "sharepoint") and onedrive_folder:
            await _ingest_onedrive(empresa_id, onedrive_folder, provider=provider)
