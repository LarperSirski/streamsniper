"""Upload saved StreamSniper recordings to YouTube."""
from __future__ import annotations

import io
import json
import logging
import mimetypes
from pathlib import Path
from typing import Callable

YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_KEYRING_SERVICE = "StreamSniper.YouTube"
MAX_YOUTUBE_TITLE_LENGTH = 100
YOUTUBE_THUMBNAIL_MAX_BYTES = 2_000_000


def build_prefixed_title(title: str, prefix: str) -> str:
    title = title.strip()
    prefix = prefix.strip()
    result = f"{prefix} {title}" if prefix else title
    if not result:
        raise ValueError("The upload title cannot be empty.")
    if len(result) > MAX_YOUTUBE_TITLE_LENGTH:
        raise ValueError(
            f"The prefixed title is {len(result)} characters; YouTube allows at most "
            f"{MAX_YOUTUBE_TITLE_LENGTH}."
        )
    return result


def _load_desktop_client(client_file: Path):
    try:
        data = json.loads(Path(client_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Select a valid Google Desktop OAuth client JSON file.") from exc
    client = data.get("installed")
    if not isinstance(client, dict):
        raise ValueError("Use a Desktop app OAuth client JSON downloaded from Google Cloud.")
    required = ("client_id", "client_secret", "auth_uri", "token_uri")
    if any(not client.get(key) for key in required):
        raise ValueError("The OAuth client JSON is missing required Desktop app fields.")
    return client


def has_youtube_connection(client_file: Path) -> bool:
    if not client_file or not Path(client_file).is_file():
        return False
    client = _load_desktop_client(client_file)
    import keyring

    return bool(keyring.get_password(YOUTUBE_KEYRING_SERVICE, client["client_id"]))


def disconnect_youtube(client_file: Path):
    client = _load_desktop_client(client_file)
    import keyring

    keyring.delete_password(YOUTUBE_KEYRING_SERVICE, client["client_id"])


def _youtube_credentials(client_file: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    import keyring

    client = _load_desktop_client(client_file)
    refresh_token = keyring.get_password(YOUTUBE_KEYRING_SERVICE, client["client_id"])
    if not refresh_token:
        raise RuntimeError("Connect a YouTube account before uploading.")

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=client["token_uri"],
        client_id=client["client_id"],
        client_secret=client["client_secret"],
        scopes=[YOUTUBE_SCOPE],
    )
    credentials.refresh(Request())
    if credentials.refresh_token and credentials.refresh_token != refresh_token:
        keyring.set_password(
            YOUTUBE_KEYRING_SERVICE,
            client["client_id"],
            credentials.refresh_token,
        )
    return credentials


def connect_youtube(client_file: Path) -> str:
    from google_auth_oauthlib.flow import InstalledAppFlow
    import keyring

    client = _load_desktop_client(client_file)
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_file), scopes=[YOUTUBE_SCOPE]
    )
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=True,
        access_type="offline",
        prompt="consent",
    )
    if not credentials.refresh_token:
        raise RuntimeError("Google did not return a refresh token. Reconnect and approve access.")

    keyring.set_password(
        YOUTUBE_KEYRING_SERVICE,
        client["client_id"],
        credentials.refresh_token,
    )
    return "YouTube account"


def _thumbnail_body(thumbnail_path: Path):
    from PIL import Image, ImageOps
    from googleapiclient.http import MediaIoBaseUpload

    output = io.BytesIO()
    with Image.open(thumbnail_path) as source:
        image = ImageOps.contain(source.convert("RGB"), (1280, 720))
        quality = 92
        while True:
            output.seek(0)
            output.truncate()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            if output.tell() <= YOUTUBE_THUMBNAIL_MAX_BYTES or quality <= 55:
                break
            quality -= 7
    if output.tell() > YOUTUBE_THUMBNAIL_MAX_BYTES:
        raise ValueError("The thumbnail is too large for YouTube's thumbnail limit.")
    output.seek(0)
    return MediaIoBaseUpload(output, mimetype="image/jpeg", resumable=False), output


def upload_to_youtube(
    media_path: Path,
    title: str,
    description: str,
    visibility: str,
    client_file: Path,
    thumbnail_path: Path | None = None,
    progress: Callable | None = None,
) -> tuple[str, str | None]:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload

    media_path = Path(media_path)
    if media_path.suffix.lower() == ".part" or not media_path.is_file():
        raise ValueError("Only completed recording files can be uploaded.")
    if visibility not in {"private", "unlisted", "public"}:
        raise ValueError("Choose a valid YouTube visibility setting.")
    if len(title) > MAX_YOUTUBE_TITLE_LENGTH:
        raise ValueError("The title exceeds YouTube's 100-character limit.")

    credentials = _youtube_credentials(client_file)
    service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    mimetype = mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
    with media_path.open("rb") as media_stream:
        request = service.videos().insert(
            part="snippet,status",
            body={
                "snippet": {"title": title, "description": description},
                "status": {"privacyStatus": visibility},
            },
            media_body=MediaIoBaseUpload(
                media_stream,
                mimetype=mimetype,
                chunksize=8 * 1024 * 1024,
                resumable=True,
            ),
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status and progress:
                progress(status.progress() * 100, "Uploading video to YouTube")

    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube did not return an ID for the uploaded video.")

    thumbnail_warning = None
    if thumbnail_path and Path(thumbnail_path).is_file():
        try:
            if progress:
                progress(98, "Applying thumbnail")
            thumbnail_body, thumbnail_stream = _thumbnail_body(Path(thumbnail_path))
            try:
                service.thumbnails().set(
                    videoId=video_id,
                    media_body=thumbnail_body,
                ).execute()
            finally:
                thumbnail_stream.close()
        except Exception as exc:
            logging.warning("YouTube video uploaded but thumbnail application failed: %s", exc)
            thumbnail_warning = f"Video uploaded, but thumbnail was not applied: {exc}"

    if progress:
        progress(100, "YouTube upload complete")
    return f"https://youtu.be/{video_id}", thumbnail_warning