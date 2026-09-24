"""Fail-closed visual identity tests for the native video download helper."""

import importlib.machinery
import importlib.util
import pathlib
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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

    def test_new_group_video_uses_accessibility_chat_selection_without_legacy_selector(self):
        selected = False

        def select_chat(_name):
            nonlocal selected
            selected = True

        def command(*args, **_kwargs):
            if args[0] == "/opt/tools/chat-select":
                raise video_download.DownloadError("CHAT_SELECT_FAILED")
            return SimpleNamespace(stdout="")

        with (
            patch.object(video_download, "parse_args", return_value=SimpleNamespace(
                chat_id="53250352594@chatroom", chat_name="群测试", local_id=35,
                video_dir="/home/wechat/xwechat_files/test/msg/video/2026-09",
                stem="a" * 32, thumbnail="/tmp/agent-video-aabb.jpg",
            )),
            patch.object(video_download, "valid_video", side_effect=[None, 2048]),
            patch.object(video_download.image_helper, "weixin_geometry", return_value={"X": 0, "Y": 0, "WIDTH": 900, "HEIGHT": 700}),
            patch.object(video_download.image_helper, "tree", return_value={}),
            patch.object(video_download.image_helper, "selected_chat", side_effect=lambda *_: selected),
            patch.object(video_download.image_helper, "select_chat", side_effect=select_chat),
            patch.object(video_download.image_helper, "command", side_effect=command),
            patch.object(video_download.image_helper, "capture", return_value=Image.new("RGB", (900, 700))),
            patch.object(video_download, "video_rows", return_value=[self.row]),
            patch.object(video_download, "find_unique_video_match", return_value={"x": 200, "y": 200}),
            patch.object(video_download.Image, "open", return_value=self.target),
            patch.object(video_download.time, "sleep"),
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            video_download.main()

        self.assertEqual(json.loads(output.getvalue()), {"ok": True, "sizeBytes": 2048})


if __name__ == "__main__":
    unittest.main()
