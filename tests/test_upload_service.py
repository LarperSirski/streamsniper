import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

import upload_service


class UploadServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.media = self.folder / "clip_id.mp4"
        self.media.write_bytes(b"video")

    def tearDown(self):
        self.temporary.cleanup()

    def test_prefix_validation(self):
        self.assertEqual(
            upload_service.build_prefixed_title("Saved title", "NEW"),
            "NEW Saved title",
        )
        self.assertEqual(
            upload_service.build_prefixed_title("Saved title", ""),
            "Saved title",
        )
        with self.assertRaises(ValueError):
            upload_service.build_prefixed_title("Saved title", "x" * 100)
        with self.assertRaises(ValueError):
            upload_service.build_prefixed_title("", " ")

    def test_youtube_upload_preserves_metadata_and_converts_thumbnail(self):
        thumbnail = self.folder / "thumb.webp"
        Image.new("RGB", (32, 18), (20, 80, 120)).save(thumbnail, "WEBP")
        request = MagicMock()
        status = MagicMock()
        status.progress.return_value = 0.5
        request.next_chunk.side_effect = [(status, None), (None, {"id": "video-id"})]
        api = MagicMock()
        api.videos.return_value.insert.return_value = request
        api.thumbnails.return_value.set.return_value.execute.return_value = {}
        progress = []

        with (
            patch.object(upload_service, "_youtube_credentials", return_value=object()),
            patch("googleapiclient.discovery.build", return_value=api),
        ):
            url, warning = upload_service.upload_to_youtube(
                self.media,
                "NEW Saved title",
                "Saved description",
                "unlisted",
                self.folder / "client.json",
                thumbnail,
                lambda percent, message: progress.append(percent),
            )

        body = api.videos.return_value.insert.call_args.kwargs["body"]
        self.assertEqual(
            body["snippet"],
            {"title": "NEW Saved title", "description": "Saved description"},
        )
        self.assertEqual(body["status"]["privacyStatus"], "unlisted")
        self.assertEqual(url, "https://youtu.be/video-id")
        self.assertIsNone(warning)
        api.thumbnails.return_value.set.assert_called_once()
        self.assertTrue(progress)
        self.assertTrue(
            api.videos.return_value.insert.call_args.kwargs["media_body"]._fd.closed
        )

    def test_upload_rejects_partial_recording(self):
        partial = self.folder / "clip_id.mp4.part"
        partial.touch()
        with self.assertRaises(ValueError):
            upload_service.upload_to_youtube(
                partial,
                "title",
                "description",
                "private",
                self.folder / "client.json",
            )

    def test_oauth_stores_refresh_token_in_credential_store(self):
        client_file = self.folder / "client_secret_streamsniper.json"
        client_file.write_text(
            json.dumps({
                "installed": {
                    "client_id": "desktop-client",
                    "client_secret": "client-secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }),
            encoding="utf-8",
        )
        credentials = MagicMock(refresh_token="secure-refresh-token")
        flow = MagicMock()
        flow.run_local_server.return_value = credentials
        with (
            patch(
                "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                return_value=flow,
            ),
            patch("keyring.set_password") as set_password,
        ):
            channel_name = upload_service.connect_youtube(client_file)

        self.assertEqual(channel_name, "YouTube account")
        flow.run_local_server.assert_called_once_with(
            host="127.0.0.1",
            port=0,
            open_browser=True,
            access_type="offline",
            prompt="consent",
        )
        set_password.assert_called_once_with(
            upload_service.YOUTUBE_KEYRING_SERVICE,
            "desktop-client",
            "secure-refresh-token",
        )


if __name__ == "__main__":
    unittest.main()