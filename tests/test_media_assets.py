import io
from pathlib import Path
import tempfile
import unittest

from content_engine.media_assets import MediaAssetError, MediaAssetStore


def mp4_bytes():
    return b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


class MediaAssetStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = MediaAssetStore(
            Path(self.temp_dir.name), "test-signing-key-that-is-at-least-32-chars",
            "https://tak-auto.example.test",
        )

    def test_saves_mp4_and_lists_metadata_without_exposing_filesystem_path(self):
        payload = mp4_bytes()
        asset = self.store.save_stream(io.BytesIO(payload), len(payload), "../../approved.mp4")
        self.assertEqual(asset.filename, "approved.mp4")
        self.assertEqual(asset.path.read_bytes(), payload)
        self.assertEqual(self.store.index_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(asset.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.index_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(asset.path.stat().st_mode & 0o777, 0o600)
        public = self.store.list_assets()[0].to_public_dict()
        self.assertEqual(public["asset_id"], asset.asset_id)
        self.assertNotIn("path", public)

    def test_rejects_non_mp4_and_removes_partial_file(self):
        payload = b"this is not a video file"
        with self.assertRaisesRegex(MediaAssetError, "MP4 컨테이너"):
            self.store.save_stream(io.BytesIO(payload), len(payload), "bad.mp4")
        self.assertEqual(self.store.list_assets(), [])
        self.assertEqual(list(self.store.asset_dir.glob("*.mp4")), [])

    def test_rejects_non_mp4_extension_and_size_mismatch(self):
        payload = mp4_bytes()
        with self.assertRaisesRegex(MediaAssetError, "MP4 파일만"):
            self.store.save_stream(io.BytesIO(payload), len(payload), "video.mov")
        with self.assertRaisesRegex(MediaAssetError, "길이가 Content-Length"):
            self.store.save_stream(io.BytesIO(payload[:-1]), len(payload), "video.mp4")

    def test_signed_url_resolves_only_with_matching_signature_and_expiry(self):
        payload = mp4_bytes()
        asset = self.store.save_stream(io.BytesIO(payload), len(payload), "approved.mp4")
        url = self.store.signed_url(asset.asset_id, ttl_seconds=3600, now=1000)
        self.assertIn("/media/assets/" + asset.asset_id, url)
        self.assertEqual(self.store.resolve_signed(asset.asset_id, "4600", url.split("signature=")[1], now=2000), asset)
        with self.assertRaisesRegex(MediaAssetError, "서명"):
            self.store.resolve_signed(asset.asset_id, "4600", "0" * 64, now=2000)
        with self.assertRaisesRegex(MediaAssetError, "만료"):
            self.store.resolve_signed(asset.asset_id, "1500", url.split("signature=")[1], now=2000)

    def test_rejects_path_traversal_and_expired_or_excessive_ttl(self):
        with self.assertRaisesRegex(MediaAssetError, "ID 형식"):
            self.store.get_asset("../secret")
        payload = mp4_bytes()
        asset = self.store.save_stream(io.BytesIO(payload), len(payload), "approved.mp4")
        with self.assertRaisesRegex(MediaAssetError, "유효기간"):
            self.store.signed_url(asset.asset_id, ttl_seconds=31 * 24 * 60 * 60)

    def test_requires_strong_signing_key_and_https_public_origin(self):
        with self.assertRaisesRegex(MediaAssetError, "32자"):
            MediaAssetStore(self.temp_dir.name, "short", "https://example.test")
        invalid = MediaAssetStore(
            self.temp_dir.name, "test-signing-key-that-is-at-least-32-chars", "http://example.test",
        )
        payload = mp4_bytes()
        asset = invalid.save_stream(io.BytesIO(payload), len(payload), "approved.mp4")
        with self.assertRaisesRegex(MediaAssetError, "HTTPS"):
            invalid.signed_url(asset.asset_id)


if __name__ == "__main__":
    unittest.main()
