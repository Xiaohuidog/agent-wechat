import importlib.machinery
import importlib.util
import io
import pathlib
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

MODULE_PATH = pathlib.Path(__file__).with_name("image-download")
LOADER = importlib.machinery.SourceFileLoader("image_download", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
image_download = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(image_download)


class ImageMatchTest(unittest.TestCase):
    def setUp(self):
        self.target = Image.new("RGB", (40, 60), "#234b72")
        for x in range(8, 32):
            for y in range(12, 48):
                self.target.putpixel((x, y), (230, 180, 40))

    def test_returns_only_visually_matching_image_row(self):
        screenshot = Image.new("RGB", (800, 600), "#eeeeee")
        screenshot.paste(self.target.resize((80, 120)), (180, 350))
        rows = [
            {"role": "list-item", "name": "Image", "bounds": {"x": 100, "y": 120, "width": 600, "height": 150}},
            {"role": "list-item", "name": "Image", "bounds": {"x": 100, "y": 330, "width": 600, "height": 160}},
        ]

        match = image_download.find_unique_match(screenshot, self.target, rows)

        self.assertEqual(match["row"], rows[1])
        self.assertTrue(180 <= match["x"] <= 260)
        self.assertTrue(350 <= match["y"] <= 470)

    def test_rejects_ambiguous_visual_matches(self):
        screenshot = Image.new("RGB", (800, 600), "#eeeeee")
        screenshot.paste(self.target.resize((80, 120)), (180, 130))
        screenshot.paste(self.target.resize((80, 120)), (180, 350))
        rows = [
            {"role": "list-item", "name": "Image", "bounds": {"x": 100, "y": 110, "width": 600, "height": 150}},
            {"role": "list-item", "name": "Image", "bounds": {"x": 100, "y": 330, "width": 600, "height": 160}},
        ]

        with self.assertRaisesRegex(image_download.DownloadError, "IMAGE_IDENTITY_AMBIGUOUS"):
            image_download.find_unique_match(screenshot, self.target, rows)

    def test_rejects_rows_outside_the_safe_message_viewport(self):
        screenshot = Image.new("RGB", (800, 600), "#eeeeee")
        screenshot.paste(self.target.resize((80, 120)), (180, 10))
        rows = [
            {"role": "list-item", "name": "Image", "bounds": {"x": 100, "y": -5, "width": 600, "height": 150}},
        ]

        with self.assertRaisesRegex(image_download.DownloadError, "IMAGE_CARD_NOT_FOUND"):
            image_download.find_unique_match(screenshot, self.target, rows)

    def test_scrolls_up_to_match_latest_image_hidden_above_newer_video(self):
        screenshot = Image.new("RGB", (800, 600), "#eeeeee")
        screenshot.paste(self.target.resize((80, 120)), (180, 350))
        hidden = {"role": "list-item", "name": "Image", "bounds": {"x": 100, "y": -35, "width": 600, "height": 160}}
        visible = {"role": "list-item", "name": "Image", "bounds": {"x": 100, "y": 330, "width": 600, "height": 160}}
        trees = iter([{"children": [hidden]}, {"children": [visible]}])
        commands = []
        geometry = {"X": 0, "Y": 0, "WIDTH": 800, "HEIGHT": 600}

        with patch.object(image_download, "tree", side_effect=lambda: next(trees)), \
             patch.object(image_download, "capture", return_value=screenshot), \
             patch.object(image_download, "command", side_effect=lambda *args: commands.append(args)), \
             patch.object(image_download.time, "sleep"):
            match = image_download.find_image_match_in_chat(self.target, geometry)

        self.assertEqual(match["row"], visible)
        self.assertTrue(any(args[-1] == "4" for args in commands))

    def test_clicks_image_content_not_center_of_full_width_message_row(self):
        row = {"bounds": {"x": 423, "y": 472, "width": 704, "height": 121}}

        point = image_download.image_click_point(row)

        self.assertGreaterEqual(point["x"], 492)
        self.assertLessEqual(point["x"], 741)
        self.assertGreaterEqual(point["y"], 499)
        self.assertLessEqual(point["y"], 580)

    def test_clicks_right_aligned_image_sent_by_logged_in_user(self):
        row = {"bounds": {"x": 501, "y": 308, "width": 578, "height": 160}}

        self.assertEqual(image_download.image_click_point(row, side="right"), {"x": 999, "y": 388})

    def test_reads_image_side_from_agent_message_identity(self):
        payload = [{"localId": 121, "isSelf": True}]
        response = io.BytesIO(__import__("json").dumps(payload).encode())
        with patch.object(image_download.pathlib.Path, "read_text", return_value="token"), \
             patch.object(image_download.urllib.request, "urlopen", return_value=response):
            side = image_download.image_message_side("group@chatroom", 121)
        self.assertEqual(side, "right")

    def test_xdotool_error_identifies_failed_subcommand(self):
        failure = SimpleNamespace(returncode=1, stdout="", stderr="window vanished")
        with patch.object(image_download.subprocess, "run", return_value=failure):
            with self.assertRaisesRegex(image_download.DownloadError, "XDOTOOL_MOUSEMOVE_FAILED"):
                image_download.command("xdotool", "mousemove", "100", "200", "click", "1")

    def test_without_thumbnail_scrolls_to_newest_image_instead_of_older_visible_card(self):
        geometry = {"X": 100, "Y": 80, "WIDTH": 800, "HEIGHT": 640}
        older = {"role": "list-item", "name": "Image", "bounds": {"x": 200, "y": 220, "width": 600, "height": 180}}
        newest_clipped = {"role": "list-item", "name": "Image", "bounds": {"x": 200, "y": 430, "width": 600, "height": 250}}
        newest_safe = {"role": "list-item", "name": "Image", "bounds": {"x": 200, "y": 230, "width": 600, "height": 250}}
        trees = iter([{"children": [older, newest_clipped]}, {"children": [newest_safe]}])
        commands = []
        with patch.object(image_download, "tree", side_effect=lambda: next(trees)), \
             patch.object(image_download, "command", side_effect=lambda *args: commands.append(args)), \
             patch.object(image_download.time, "sleep"):
            point = image_download.find_newest_image_in_chat(geometry)
        self.assertEqual(point, image_download.image_click_point(newest_safe))
        self.assertTrue(any(call[-1] == "5" for call in commands))


class NativeImageSaveTest(unittest.TestCase):
    def test_select_chat_searches_when_target_is_not_in_visible_list(self):
        search = {"role": "text", "name": "Search", "bounds": {"x": 100, "y": 40, "width": 200, "height": 30}}
        target = {"role": "list-item", "name": "群测试 小晖: [Photo]", "bounds": {"x": 100, "y": 200, "width": 220, "height": 60}}
        selected = {**target, "states": ["SELECTED"]}
        trees = iter([
            {"children": [search]},
            {"children": [search, target]},
            {"children": [search, selected]},
        ])
        calls = []

        def command(*args, **_kwargs):
            calls.append(args)

        with patch.object(image_download, "tree", side_effect=lambda: next(trees)), \
             patch.object(image_download, "command", side_effect=command), \
             patch.object(image_download.time, "sleep"):
            image_download.select_chat("群测试")

        self.assertIn(("/opt/tools/input", "群测试"), calls)
        self.assertTrue(any(call[:2] == ("xdotool", "mousemove") and "click" in call for call in calls))

    def test_search_chooses_full_chat_row_over_same_name_suggestion(self):
        chat = {"role": "list-item", "name": "群测试", "bounds": {"x": 273, "y": 184, "width": 320, "height": 64}}
        suggestion = {"role": "list-item", "name": "群测试", "bounds": {"x": 273, "y": 280, "width": 320, "height": 34}}

        self.assertEqual(
            image_download.unique_chat_item({"children": [suggestion, chat]}, "群测试"),
            chat,
        )

    def test_open_chat_is_confirmed_by_header_when_search_results_disappear(self):
        opened = {"children": [
            {"role": "label", "name": "群测试"},
            {"role": "list", "name": "Messages"},
        ]}

        self.assertTrue(image_download.selected_chat(opened, "群测试"))

    def test_identifies_only_one_target_chat_item(self):
        target = {"role": "list-item", "name": "群测试 小晖Allen: [Photo]", "bounds": {"x": 212, "y": 318, "width": 210, "height": 68}}
        tree = {"children": [target, {"role": "list-item", "name": "其他群", "bounds": {"x": 212, "y": 400, "width": 210, "height": 68}}]}

        self.assertEqual(image_download.unique_chat_item(tree, "群测试"), target)
        with self.assertRaisesRegex(image_download.DownloadError, "CHAT_IDENTITY_AMBIGUOUS"):
            image_download.unique_chat_item({"children": [target, {**target, "bounds": {**target["bounds"], "y": 450}}]}, "群测试")

    def test_publishes_decoded_clipboard_image_at_full_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            data = io.BytesIO()
            Image.new("RGB", (1707, 1280), "#19a7c0").save(data, "PNG")
            target = folder / "image-a_preview.jpg"

            size = image_download.publish_clipboard_image(data.getvalue(), target)

            self.assertGreater(size, 0)
            with Image.open(target) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertEqual(image.size, (1707, 1280))
            self.assertEqual(target.read_bytes(), (folder / "image-a_h_preview.jpg").read_bytes())

    def test_rejects_non_image_clipboard_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "image-a_preview.jpg"
            with self.assertRaisesRegex(image_download.DownloadError, "IMAGE_CLIPBOARD_INVALID"):
                image_download.publish_clipboard_image(b"not an image", target)
            self.assertFalse(target.exists())

    def test_waits_past_invalid_clipboard_response_for_viewer_image(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "image-a_preview.jpg"
            encoded = io.BytesIO()
            Image.new("RGB", (80, 60), "#19a7c0").save(encoded, "PNG")
            clipboard = iter([
                SimpleNamespace(returncode=0, stdout=b"clipboard-not-ready"),
                SimpleNamespace(returncode=0, stdout=encoded.getvalue()),
            ])
            active = SimpleNamespace(stdout="Photos and Videos")
            with patch.object(image_download, "command", return_value=active), \
                 patch.object(image_download.subprocess, "run", side_effect=lambda *_args, **_kwargs: next(clipboard)), \
                 patch.object(image_download.time, "sleep"):
                size = image_download.copy_viewer_image(target)

            self.assertGreater(size, 0)
            with Image.open(target) as saved:
                self.assertEqual(saved.size, (80, 60))

    def test_native_path_is_bound_to_source_file_hash(self):
        stem = "b" * 32
        directory = pathlib.Path("/home/wechat/xwechat_files/account/msg/attach/" + "a" * 32 + "/2026-09/Img")
        self.assertEqual(
            image_download.native_image_path(directory, stem),
            pathlib.Path(f"/home/wechat/xwechat_files/account/temp/ImageUtils/{stem}_h.jpg"),
        )

    def test_missing_native_image_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            image_download.DownloadError, "IMAGE_NATIVE_DECODE_MISSING"
        ):
            image_download.native_image_size(pathlib.Path(directory) / "missing.jpg", timeout_seconds=0)

    def test_publishes_only_the_matching_native_image(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            stem = "a" * 32
            source = folder / f"{stem}_h.jpg"
            other = folder / f"{'b' * 32}_h.jpg"
            Image.new("RGB", (80, 60), "#19a7c0").save(source, "JPEG")
            Image.new("RGB", (80, 60), "#ff0000").save(other, "JPEG")
            target = folder / f"{stem}_preview.jpg"

            size = image_download.publish_native_image(source, folder, stem, 24, target)

            self.assertEqual(size, source.stat().st_size)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertNotEqual(target.read_bytes(), other.read_bytes())
            with self.assertRaisesRegex(image_download.DownloadError, "IMAGE_IDENTITY_MISMATCH"):
                image_download.publish_native_image(other, folder, stem, 24, target)

    def test_waits_for_native_high_resolution_image_after_opening_viewer(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            stem = "a" * 32
            source = folder / f"{stem}_h.jpg"
            target = folder / f"{stem}_preview.jpg"
            timer = threading.Timer(0.1, lambda: Image.new("RGB", (581, 194), "white").save(source, "JPEG"))
            timer.start()
            try:
                size = image_download.publish_native_image(
                    source, folder, stem, 26, target, timeout_seconds=2
                )
            finally:
                timer.join()

            self.assertGreater(size, 0)
            with Image.open(target) as image:
                self.assertEqual(image.size, (581, 194))

    def test_recognizes_selected_chat(self):
        tree = {"children": [
            {"role": "list-item", "name": "群测试 小晖Allen: [Photo]", "states": ["SELECTED"]},
            {"role": "list-item", "name": "其他群 [Photo]", "states": []},
        ]}
        self.assertTrue(image_download.selected_chat(tree, "群测试"))
        self.assertFalse(image_download.selected_chat(tree, "其他群"))

    def test_publishes_native_export_for_current_high_resolution_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            source = folder / "image-a_export_22.jpg"
            original = Image.new("RGB", (568, 568), "#19a7c0")
            original.save(source, "JPEG")
            target = folder / "image-a_preview.jpg"

            image_download.publish_saved_image(source, target)

            self.assertFalse(source.exists())
            self.assertEqual(target.read_bytes(), (folder / "image-a_h_preview.jpg").read_bytes())


if __name__ == "__main__":
    unittest.main()


class ChatIdentityRegressionTest(unittest.TestCase):
    def row(self, y=200, name='群测试'):
        return {'role': 'list-item', 'name': name,
                'bounds': {'x': 280, 'y': y, 'width': 240, 'height': 68}}

    def test_duplicate_accessibility_projection_is_one_visual_target(self):
        row = self.row()
        self.assertEqual(image_download.unique_chat_item({'children': [row, dict(row)]}, '群测试'), row)

    def test_message_content_cannot_be_selected_as_conversation(self):
        row = self.row()
        message = self.row(300)
        value = {'children': [row, {'role': 'list', 'name': 'Messages', 'children': [message]}]}
        self.assertEqual(image_download.unique_chat_item(value, '群测试'), row)

    def test_two_distinct_conversations_still_fail_closed(self):
        with self.assertRaisesRegex(image_download.DownloadError, 'CHAT_IDENTITY_AMBIGUOUS'):
            image_download.unique_chat_item({'children': [self.row(), self.row(300)]}, '群测试')

    def test_known_longer_group_name_is_not_target_prefix(self):
        value = {'children': [self.row(name='群测试 二群 张三: [Photo]')]}
        with self.assertRaisesRegex(image_download.DownloadError, 'CHAT_UI_NOT_FOUND'):
            image_download.unique_chat_item(value, '群测试', known_names=['群测试', '群测试 二群'])

    def test_wrong_open_header_overrides_stale_selected_sidebar(self):
        row = {**self.row(), 'states': ['SELECTED']}
        value = {'children': [row, {'role': 'label', 'name': '其他群'},
                              {'role': 'list', 'name': 'Messages'}]}
        self.assertFalse(image_download.selected_chat(value, '群测试'))


def test_historical_match_can_select_older_unique_thumbnail_but_not_newest_guess():
    screenshot = Image.new('RGB', (800, 600), '#eeeeee')
    target = Image.new('RGB', (40, 60), '#234b72')
    for x in range(8, 32):
        for y in range(12, 48):
            target.putpixel((x, y), (230, 180, 40))
    screenshot.paste(target.resize((80, 120)), (180, 130))
    rows = [dict(role='list-item', name='Image', bounds=dict(x=100, y=y, width=600, height=150)) for y in (110, 330)]
    assert image_download.find_unique_match(screenshot, target, rows, historical=True)['row'] == rows[0]
    with __import__('pytest').raises(image_download.DownloadError, match='IMAGE_NOT_NEWEST_VISIBLE_MESSAGE'):
        image_download.find_unique_match(screenshot, target, rows)


def test_historical_image_requires_hash_bound_native_cache_not_clipboard():
    from unittest.mock import Mock
    native = Mock(side_effect=image_download.DownloadError('IMAGE_NATIVE_DECODE_MISSING'))
    with patch.object(image_download, 'publish_native_image', native), \
         patch.object(image_download, 'copy_viewer_image') as clipboard:
        with __import__('pytest').raises(image_download.DownloadError, match='IMAGE_NATIVE_DECODE_MISSING'):
            image_download.publish_viewer_result('native', 'directory', 'stem', 42, 'preview', historical=True)
        clipboard.assert_not_called()
        assert native.call_args.kwargs['timeout_seconds'] == 20


def test_chat_identity_uses_stable_id_and_rejects_duplicate_display_names():
    import json
    from unittest.mock import patch
    chats = [{'id': 'one@chatroom', 'name': '群测试'}, {'id': 'two@chatroom', 'name': '群测试'}]
    with patch.object(image_download.pathlib.Path, 'read_text', return_value='token'), \
         patch.object(image_download.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(chats).encode())):
        with __import__('pytest').raises(image_download.DownloadError, match='CHAT_IDENTITY_AMBIGUOUS'):
            image_download.verify_chat_identity('one@chatroom', '群测试')


def test_chat_identity_rejects_renamed_or_changed_target_before_ui():
    import json
    chats = [{'id': 'one@chatroom', 'name': '新群名'}]
    with patch.object(image_download.pathlib.Path, 'read_text', return_value='token'), \
         patch.object(image_download.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(chats).encode())):
        with __import__('pytest').raises(image_download.DownloadError, match='CHAT_IDENTITY_CHANGED'):
            image_download.verify_chat_identity('one@chatroom', '群测试')

class NewestImagePositionRegressionTest(unittest.TestCase):
    def test_new_image_moves_into_view_without_oscillating_past_both_edges(self):
        geometry = {'X': 0, 'Y': 0, 'WIDTH': 800, 'HEIGHT': 500}
        state = {'top': 250.0}
        def snapshot():
            return {'children': [{'role': 'list-item', 'name': 'Image',
                'bounds': {'x': 100, 'y': state['top'], 'width': 600, 'height': 285}}]}
        def scroll(*args):
            count = int(args[args.index('--repeat') + 1])
            state['top'] += (80 if args[-1] == '4' else -80) * count
        with patch.object(image_download, 'tree', side_effect=snapshot), \
             patch.object(image_download, 'command', side_effect=scroll), \
             patch.object(image_download.time, 'sleep'):
            point = image_download.find_newest_image_in_chat(geometry)
        self.assertGreaterEqual(state['top'], 70)
        self.assertLessEqual(state['top'] + 285, 395)
        self.assertGreater(point['y'], state['top'])
        self.assertLess(point['y'], state['top'] + 285)

class NewImageAfterTextRegressionTest(unittest.TestCase):
    def test_finds_latest_image_after_many_newer_text_messages(self):
        geometry = {'X': 0, 'Y': 0, 'WIDTH': 800, 'HEIGHT': 640}
        state = {'top': -900.0}
        def snapshot():
            if state['top'] + 285 <= 0:
                return {'children': []}
            return {'children': [{'role': 'list-item', 'name': 'Image',
                'bounds': {'x': 100, 'y': state['top'], 'width': 600, 'height': 285}}]}
        def scroll(*args):
            state['top'] += (80 if args[-1] == '4' else -80) * int(args[args.index('--repeat') + 1])
        with patch.object(image_download, 'tree', side_effect=snapshot), \
             patch.object(image_download, 'command', side_effect=scroll), \
             patch.object(image_download.time, 'sleep'):
            point = image_download.find_newest_image_in_chat(geometry)
        self.assertGreaterEqual(state['top'], 70)
        self.assertLessEqual(state['top'] + 285, 535)
        self.assertGreater(point['y'], state['top'])

class PrepareNewImageChatTest(unittest.TestCase):
    def test_prepare_only_loads_verified_chat_without_clicking_image(self):
        args = SimpleNamespace(chat_id='123@chatroom', chat_name='Target', account_id='account')
        calls = []
        with patch.object(image_download, 'agent_json', return_value={'status': 'logged_in', 'loggedInUser': 'account'}), \
             patch.object(image_download, 'verify_chat_identity', return_value=['Target']), \
             patch.object(image_download, 'reject_existing_draft'), \
             patch.object(image_download, 'weixin_geometry'), \
             patch.object(image_download, 'select_chat', side_effect=lambda *a: calls.append(a)), \
             patch.object(image_download, 'find_newest_image_in_chat') as click_locator:
            image_download.prepare_new_image_chat(args)
        self.assertEqual(calls, [('Target', ['Target'])])
        click_locator.assert_not_called()

    def test_prepare_rejects_account_change_before_switching_chat(self):
        args = SimpleNamespace(chat_id='123@chatroom', chat_name='Target', account_id='expected')
        with patch.object(image_download, 'agent_json', return_value={'status': 'logged_in', 'loggedInUser': 'other'}), \
             patch.object(image_download, 'select_chat') as select, \
             self.assertRaisesRegex(image_download.DownloadError, 'IMAGE_ACCOUNT_CHANGED'):
            image_download.prepare_new_image_chat(args)
        select.assert_not_called()

    def test_prepare_does_not_hide_existing_draft(self):
        args = SimpleNamespace(chat_id='123@chatroom', chat_name='Target', account_id='account')
        with patch.object(image_download, 'agent_json', return_value={'status': 'logged_in', 'loggedInUser': 'account'}), \
             patch.object(image_download, 'verify_chat_identity', return_value=['Target']), \
             patch.object(image_download, 'reject_existing_draft', side_effect=image_download.DownloadError('IMAGE_EXISTING_DRAFT')), \
             patch.object(image_download, 'select_chat') as select, \
             self.assertRaisesRegex(image_download.DownloadError, 'IMAGE_EXISTING_DRAFT'):
            image_download.prepare_new_image_chat(args)
        select.assert_not_called()

    def test_prepare_rejects_unreadable_editor_in_open_chat(self):
        with patch.object(image_download, 'tree', return_value={'children': [{'role': 'list', 'name': 'Messages'}]}), \
             self.assertRaisesRegex(image_download.DownloadError, 'IMAGE_EDITOR_UNAVAILABLE'):
            image_download.reject_existing_draft()
