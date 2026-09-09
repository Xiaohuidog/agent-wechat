import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).with_name("chat-select.py")
SPEC = importlib.util.spec_from_file_location("chat_select", MODULE_PATH)
chat_select = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chat_select)


class ChatSelectUiFallbackTest(unittest.TestCase):
    def test_exact_first_line_matches_chat_name(self):
        tree = {
            "children": [
                {
                    "role": "list-item",
                    "name": "群测试\n[13]\n成员: [File] 报告.docx\n09:01",
                    "bounds": {"x": 1, "y": 2, "width": 3, "height": 4},
                },
                {
                    "role": "list-item",
                    "name": "群测试备份\n成员: 文本",
                    "bounds": {"x": 1, "y": 2, "width": 3, "height": 4},
                },
            ]
        }

        matches = chat_select.find_chat_items(tree, "群测试")

        self.assertEqual(len(matches), 1)
        self.assertEqual(chat_select.chat_name_from_item(matches[0]), "群测试")

    def test_main_uses_ui_without_reading_build_profile(self):
        output = io.StringIO()
        argv = ["chat-select", "--chat-name", "群测试", "123@chatroom"]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(chat_select, "get_pid", return_value="55"),
            mock.patch.object(chat_select, "select_by_chat_name", return_value=(True, None)),
            mock.patch.object(
                chat_select,
                "get_profile",
                side_effect=AssertionError("Build profile must not be read"),
            ),
            contextlib.redirect_stdout(output),
            self.assertRaises(SystemExit) as exit_result,
        ):
            chat_select.main()

        self.assertEqual(exit_result.exception.code, 0)
        self.assertEqual(json.loads(output.getvalue())["method"], "a11y")


if __name__ == "__main__":
    unittest.main()
