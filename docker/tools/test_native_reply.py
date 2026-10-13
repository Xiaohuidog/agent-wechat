import importlib.machinery
import importlib.util
from pathlib import Path
import unittest
loader=importlib.machinery.SourceFileLoader('native_reply',str(Path(__file__).with_name('native-reply')))
spec=importlib.util.spec_from_loader(loader.name,loader);reply=importlib.util.module_from_spec(spec);loader.exec_module(reply)

def row(i,body,kind=1):return {'local_id':i,'type':kind,'body':body}
def node(name):return {'name':name}
class NativeReplyTests(unittest.TestCase):
 def test_unique_original_is_located_by_id(self):
  nodes=[node('other'),node('source')]
  self.assertIs(reply.source_node([row(1,'other'),row(2,'source')],nodes,2),nodes[1])
 def test_repeated_text_is_resolved_by_unique_ordered_context(self):
  rows=[row(1,'yes'),row(2,'anchor'),row(3,'yes'),row(4,'next')]
  nodes=[node('anchor'),node('yes'),node('next')]
  self.assertIs(reply.source_node(rows,nodes,3),nodes[1])
 def test_ambiguous_repeated_text_is_rejected(self):
  with self.assertRaisesRegex(reply.ReplyError,'REPLY_SOURCE_AMBIGUOUS'):
   reply.source_node([row(1,'yes'),row(2,'yes')],[node('yes')],2)
 def test_source_outside_visible_window_is_not_substituted(self):
  self.assertIsNone(reply.source_node([row(1,'old'),row(2,'new')],[node('new')],1))
 def test_native_reference_preserves_large_id(self):
  ref=reply.reference('<msg><appmsg><refermsg><svrid>6088777209553577378</svrid><type>1</type><content>2110</content></refermsg></appmsg></msg>')
  self.assertEqual(ref['svrid'],'6088777209553577378')
 def test_quote_row_matches_body_and_original(self):
  r=row(1,'<msg><appmsg><title>reply</title><refermsg><content>source</content></refermsg></appmsg></msg>',49)
  self.assertTrue(reply.row_matches(r,"reply\nQuote Someone's message: source"))
  self.assertFalse(reply.row_matches(r,"reply\nQuote Someone's message: different"))
 def test_native_quote_can_itself_be_selected_for_reply(self):
  body='<msg><appmsg><title>reply</title><refermsg><svrid>123</svrid><content>source</content></refermsg></appmsg></msg>'
  nodes=[node("reply\nQuote Someone's message: source")]
  self.assertIs(reply.source_node([row(7,body,49)],nodes,7),nodes[0])
if __name__=='__main__':unittest.main()
