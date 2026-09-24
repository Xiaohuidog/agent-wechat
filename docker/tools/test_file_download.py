import importlib.machinery
import importlib.util
import io
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).with_name("file-download")
LOADER = importlib.machinery.SourceFileLoader("file_download", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
file_download = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(file_download)


class WeixinGeometryTest(unittest.TestCase):
    def test_duplicate_filename_uses_message_minute(self):
        old = {"role": "list-item", "name": "File\n报告.pdf\n12K\n微信电脑版", "bounds": {"x": 423, "y": 116, "width": 704, "height": 120}}
        new = {**old, "bounds": {"x": 423, "y": 400, "width": 704, "height": 120}}
        snapshot = {"role": "list", "name": "Messages", "children": [
            {"role": "list-item", "name": "10:09"}, old,
            {"role": "list-item", "name": "13:45"}, new,
        ]}
        self.assertEqual(file_download.matching_rows(snapshot, "报告.pdf", "2026-09-24T13:45:23+00:00"), [new])

    def test_duplicate_filename_same_minute_fails_closed(self):
        row = {"role": "list-item", "name": "File\n报告.pdf\n12K\n微信电脑版", "bounds": {"x": 423, "y": 116, "width": 704, "height": 120}}
        snapshot = {"role": "list", "name": "Messages", "children": [
            {"role": "list-item", "name": "13:45"}, row,
            {"role": "list-item", "name": "13:45"}, {**row, "bounds": {"x": 423, "y": 400, "width": 704, "height": 120}},
        ]}
        with self.assertRaises(file_download.DownloadError) as error:
            file_download.matching_rows(snapshot, "报告.pdf", "2026-09-24T13:45:23+00:00")
        self.assertEqual(str(error.exception), "FILE_IDENTITY_AMBIGUOUS")

    def test_uses_largest_visible_weixin_window(self):
        geometries = {
            "2": "X=359\nY=179\nWIDTH=560\nHEIGHT=440\n",
            "1": "X=200\nY=80\nWIDTH=880\nHEIGHT=640\n",
        }

        def command(*args, **_kwargs):
            if args[1] == "search":
                return SimpleNamespace(stdout="1\n2\n", returncode=0)
            if args[1] == "getwindowgeometry":
                return SimpleNamespace(stdout=geometries[args[-1]], returncode=0)
            if args[1] == "getactivewindow":
                return SimpleNamespace(stdout="1\n", returncode=0)
            return SimpleNamespace(stdout="", returncode=0)

        with mock.patch.object(file_download, "command", side_effect=command):
            geometry = file_download.weixin_geometry()

        self.assertEqual(geometry, {"X": 200, "Y": 80, "WIDTH": 880, "HEIGHT": 640})

    def test_find_row_tolerates_delayed_a11y_refresh(self):
        empty_tree = {"children": []}
        target = {
            "role": "list-item",
            "name": "File\n报告.docx\n12K\n微信电脑版",
            "bounds": {"x": 501, "y": 200, "width": 578, "height": 120},
        }
        with (
            mock.patch.object(
                file_download,
                "tree",
                side_effect=[empty_tree, empty_tree, empty_tree, empty_tree, target],
            ),
            mock.patch.object(file_download, "scroll"),
        ):
            row = file_download.find_row(
                "报告.docx", {"X": 200, "Y": 80, "WIDTH": 880, "HEIGHT": 640}
            )

        self.assertEqual(row, target)


class FileChatSelectionTest(unittest.TestCase):
    def test_selects_live_one_line_chat_card_and_confirms_group_header(self):
        card = {
            "role": "list-item",
            "name": "群测试 8 unread message(s) 小晖Allen: [File] 报告.pdf 10:09",
            "bounds": {"x": 212, "y": 182, "width": 210, "height": 68},
        }
        initial = {"role": "list", "name": "Chats", "children": [card]}
        opened = {
            "children": [
                {"role": "list", "name": "Chats", "children": [{**card, "states": ["SELECTED"]}]},
                {"role": "label", "name": "群测试"},
                {"role": "list", "name": "Messages"},
            ]
        }
        commands = []

        def command(*args, **_kwargs):
            commands.append(args)
            return SimpleNamespace(stdout="", returncode=0)

        with (
            mock.patch.object(file_download, "tree", side_effect=[initial, opened]),
            mock.patch.object(file_download, "command", side_effect=command),
            mock.patch.object(file_download.time, "sleep"),
        ):
            file_download.select_chat("群测试")

        self.assertEqual(commands, [("xdotool", "mousemove", "317", "216", "click", "1")])

    def test_similar_group_card_does_not_count_as_selected_group(self):
        wrong_group = {
            "children": [
                {"role": "list", "name": "Chats", "children": [
                    {"role": "list-item", "name": "群测试备份 小晖Allen: [File] 报告.pdf 10:09",
                     "bounds": {"x": 212, "y": 182, "width": 210, "height": 68}},
                ]},
            ]
        }
        with mock.patch.object(file_download, "tree", return_value=wrong_group):
            with self.assertRaises(file_download.DownloadError) as error:
                file_download.select_chat("群测试")

        self.assertEqual(str(error.exception), "CHAT_SEARCH_UNAVAILABLE")

    def test_file_download_main_uses_file_scoped_chat_selection(self):
        args = SimpleNamespace(
            chat_id="53250352594@chatroom", chat_name="群测试", local_id=46,
            filename="报告.pdf", sent_at="2026-09-24T10:09:04+00:00",
            output="/home/wechat/Downloads/agent-file-a59f5940-4528-4214-812e-b39213bbd7f0.pdf",
        )
        output = io.StringIO()
        with (
            mock.patch.object(file_download, "parse_args", return_value=args),
            mock.patch.object(file_download, "weixin_geometry", return_value={}),
            mock.patch.object(file_download, "prepare_download_dir"),
            mock.patch.object(file_download, "select_chat",
                              side_effect=file_download.DownloadError("CHAT_TEST_SENTINEL"),
                              create=True),
            mock.patch.object(file_download, "command",
                              side_effect=AssertionError("global chat-select must not run")),
            mock.patch.object(file_download.os, "makedirs"),
            mock.patch.object(file_download.os, "unlink"),
            mock.patch("sys.stdout", output),
            self.assertRaises(SystemExit),
        ):
            file_download.main()

        self.assertIn('"errorCode": "CHAT_TEST_SENTINEL"', output.getvalue())


class DownloadDirectoryTest(unittest.TestCase):
    def test_download_directory_is_owned_by_wechat_before_saving(self):
        with tempfile.TemporaryDirectory() as root:
            directory = pathlib.Path(root) / "home" / "wechat" / "Downloads"
            output = directory / "agent-file-a59f5940-4528-4214-812e-b39213bbd7f0.pdf"
            with mock.patch.object(file_download.os, "chown") as chown, \
                 mock.patch("pwd.getpwnam", return_value=SimpleNamespace(
                     pw_uid=1000, pw_gid=1000,
                 )):
                file_download.prepare_download_dir(str(output))

            self.assertTrue(directory.is_dir())
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            chown.assert_called_once_with(str(directory), 1000, 1000)


if __name__ == "__main__":
    unittest.main()
