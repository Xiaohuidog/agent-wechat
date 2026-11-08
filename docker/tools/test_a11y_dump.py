import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class Node:
    def __init__(self, role, name='', children=(), counts=None, forbid=False):
        self.role, self.name, self.children = role, name, list(children)
        self.counts = iter(counts) if counts else None
        self.forbid = forbid
        self.requested = []

    def get_role_name(self): return self.role
    def get_name(self): return self.name
    def get_child_count(self):
        if self.forbid: raise AssertionError('health must not enumerate virtualized rows')
        return next(self.counts) if self.counts else len(self.children)
    def get_child_at_index(self, index):
        self.requested.append(index)
        return self.children[index]


class AccessibilitySafetyTests(unittest.TestCase):
    def module(self, desktop):
        gi = types.ModuleType('gi');gi.require_version = lambda *args: None
        repo = types.ModuleType('gi.repository')
        repo.Atspi = types.SimpleNamespace(init=lambda: None, get_desktop=lambda _: desktop)
        with patch.dict(sys.modules, {'gi': gi, 'gi.repository': repo}):
            m = runpy.run_path(str(Path(__file__).with_name('a11y-dump')))
        g = m['dump_tree_nested'].__globals__
        g.update(get_bounds=lambda _: {'x': 0, 'y': 0, 'width': 100, 'height': 100},
                 get_states=lambda _: None, get_window_info=lambda _: {'pid': 1})
        return m

    def test_health_probe_keeps_list_shell_without_requesting_children(self):
        messages = Node('list', 'Messages', forbid=True)
        root = Node('desktop', children=[Node('frame', 'Weixin', [messages])])
        result = self.module(root)['dump_tree_nested'](health_probe=True)
        item = result['children'][0]['children'][0]
        self.assertEqual(item['name'], 'Messages')
        self.assertNotIn('children', item)
        self.assertEqual(messages.requested, [])

    def test_aria_health_probe_keeps_lists_without_enumeration(self):
        rows = Node('list', 'Chats', forbid=True)
        output = self.module(rows)['dump_tree_aria'](health_probe=True)
        self.assertIn('Chats', output)
        self.assertEqual(rows.requested, [])

    def test_changing_list_count_discards_partial_snapshot(self):
        rows = Node('list', 'Messages', [Node('list item', str(i)) for i in range(3)], counts=[3,3,1])
        result = self.module(rows)['dump_tree_nested']()
        self.assertEqual(rows.requested, [0])
        self.assertNotIn('children', result)
        self.assertTrue(result['childrenUnstable'])

    def test_stable_lists_keep_identity_rows_for_normal_operations(self):
        rows = Node('list', 'Messages', [Node('list item', 'a'), Node('list item', 'b')])
        result = self.module(rows)['dump_tree_nested']()
        self.assertEqual([n['name'] for n in result['children']], ['a', 'b'])


if __name__ == '__main__': unittest.main()
