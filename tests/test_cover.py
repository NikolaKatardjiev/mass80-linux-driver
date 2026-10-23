"""Cover art encoding tests: JPEG size bound + base64 decodes to a real JPEG."""
import base64
import io
import os
import tempfile
import unittest

from PIL import Image

from mass80d.providers.cover import (
    MAX_IMAGE_DATA_B64_BYTES,
    CoverProvider,
    make_placeholder,
)

JPEG_SOI = b"\xff\xd8\xff"


class PlaceholderTest(unittest.TestCase):
    def test_placeholder_is_valid_jpeg(self):
        data = make_placeholder(480, 480)
        self.assertTrue(data.startswith(JPEG_SOI))
        img = Image.open(io.BytesIO(data))
        img.load()
        self.assertEqual(img.format, "JPEG")
        self.assertEqual(img.size, (480, 480))


class CoverProviderTest(unittest.TestCase):
    def test_no_art_url_returns_placeholder_b64(self):
        provider = CoverProvider()
        b64 = provider.get_cover_b64("", 480, 480)
        raw = base64.b64decode(b64, validate=True)
        self.assertTrue(raw.startswith(JPEG_SOI))
        self.assertLessEqual(len(b64), MAX_IMAGE_DATA_B64_BYTES)

    def test_real_art_file_is_cropped_resized_and_bounded(self):
        # A non-square source image to exercise center-crop-to-square.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "art.png")
            Image.new("RGB", (800, 400), (200, 50, 50)).save(path, format="PNG")
            url = "file://" + path

            provider = CoverProvider()
            b64 = provider.get_cover_b64(url, 480, 480)

        raw = base64.b64decode(b64, validate=True)
        self.assertTrue(raw.startswith(JPEG_SOI))
        img = Image.open(io.BytesIO(raw))
        img.load()
        self.assertEqual(img.format, "JPEG")
        self.assertEqual(img.size, (480, 480))
        # base64 line must stay comfortably under the device's 128KB RX cap.
        self.assertLessEqual(len(b64), MAX_IMAGE_DATA_B64_BYTES)

    def test_unreachable_url_falls_back_to_placeholder(self):
        provider = CoverProvider()
        b64 = provider.get_cover_b64("file:///nonexistent/path/art.jpg", 480, 480)
        raw = base64.b64decode(b64, validate=True)
        self.assertTrue(raw.startswith(JPEG_SOI))

    def test_small_dimensions_still_bounded(self):
        provider = CoverProvider()
        b64 = provider.get_cover_b64("", 64, 64)
        raw = base64.b64decode(b64, validate=True)
        img = Image.open(io.BytesIO(raw))
        img.load()
        self.assertEqual(img.size, (64, 64))


if __name__ == "__main__":
    unittest.main()
