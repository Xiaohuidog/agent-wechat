"""Fail-closed visual identity tests for the native video download helper."""

import importlib.machinery
import importlib.util
import pathlib
import unittest

from PIL import Image


HELPER = pathlib.Path(__file__).with_name("video-download")
loader = importlib.machinery.SourceFileLoader("video_download", str(HELPER))
spec = importlib.util.spec_from_loader(loader.name, loader)
video_download = importlib.util.module_from_spec(spec)
loader.exec_module(video_download)


class VideoMatchTests(unittest.TestCase):
    def setUp(self):
        self.target = Image.new("RGB", (42, 72))
        for y in range(72):
            for x in range(42):
                self.target.putpixel((x, y), ((x * 11) % 256, (y * 5) % 256, ((x + y) * 7) % 256))
        self.screen = Image.new("RGB", (800, 600), "#eeeeee")
        self.row = {"role": "list-item", "name": "Video0:04\n", "bounds": {"x": 100, "y": 100, "width": 600, "height": 110}}
        self.screen.paste(self.target, (168, 120))

    def test_unique_video_thumbnail_selects_matching_card(self):
        match = video_download.find_unique_video_match(self.screen, self.target, [self.row])
        self.assertLess(abs(match["x"] - 189), 8)
        self.assertLess(abs(match["y"] - 156), 8)

    def test_duplicate_visual_matches_fail_closed(self):
        other = {"role": "list-item", "name": "Video0:04\n", "bounds": {"x": 100, "y": 300, "width": 600, "height": 110}}
        self.screen.paste(self.target, (168, 320))
        with self.assertRaisesRegex(video_download.DownloadError, "VIDEO_IDENTITY_AMBIGUOUS"):
            video_download.find_unique_video_match(self.screen, self.target, [self.row, other])

    def test_no_matching_video_card_fails_closed(self):
        self.screen = Image.new("RGB", (800, 600), "#eeeeee")
        with self.assertRaisesRegex(video_download.DownloadError, "VIDEO_CARD_NOT_FOUND"):
            video_download.find_unique_video_match(self.screen, self.target, [self.row])


if __name__ == "__main__":
    unittest.main()
