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

    def test_message_list_confirms_chat_is_open(self):
        self.assertTrue(
            chat_select.has_message_list(
                {"role": "list", "name": "Messages", "children": []}
            )
        )
        self.assertFalse(
            chat_select.has_message_list(
                {"role": "list", "name": "Chats", "children": []}
            )
        )

    def test_accessible_chat_selection_clicks_once(self):
        bounds = {"x": 261, "y": 226, "width": 240, "height": 65}
        trees = iter(
            [
                {
                    "role": "list-item",
                    "name": "群测试\n成员: [Video]",
                    "bounds": bounds,
                },
                {"role": "list", "name": "Messages", "children": []},
            ]
        )
        with (
            mock.patch.object(chat_select, "dump_a11y_tree", side_effect=trees),
            mock.patch.object(chat_select, "click_bounds", return_value=True) as click,
            mock.patch.object(chat_select.time, "sleep"),
        ):
            selected, error = chat_select.select_by_chat_name("群测试")

        self.assertTrue(selected)
        self.assertIsNone(error)
        click.assert_called_once_with(bounds, count=1)

    def test_search_prefers_full_group_card_over_suggestion(self):
        suggestion = {
            "bounds": {"x": 273, "y": 184, "width": 320, "height": 34}
        }
        group_card = {
            "bounds": {"x": 273, "y": 386, "width": 320, "height": 64}
        }

        self.assertIs(chat_select.choose_chat_item([suggestion, group_card]), group_card)


if __name__ == "__main__":
    unittest.main()
