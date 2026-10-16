import importlib.machinery
import importlib.util
from pathlib import Path
import unittest
from unittest import mock
import subprocess
source=Path(__file__).with_name('native-reply')
if source.with_name('native-reply.finder-original').is_file():
 source=source.with_name('native-reply.finder-original')
loader=importlib.machinery.SourceFileLoader('native_reply',str(source))
spec=importlib.util.spec_from_loader(loader.name,loader);reply=importlib.util.module_from_spec(spec);loader.exec_module(reply)

def row(i,body,kind=1):return {'local_id':i,'type':kind,'body':body}
def node(name):return {'name':name}
class NativeReplyTests(unittest.TestCase):
 def test_native_audio_label_matches_voice_in_ordered_context(self):
  rows=[row(211,'',3),row(212,'',43),row(213,'',34)]
  nodes=[node('Image'),node('Video Expired0:03'),node('Audio4"secUnplayed')]
  self.assertIs(reply.source_node(rows,nodes,213),nodes[2])
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
 def test_adjacent_identical_images_are_bound_by_ordered_context(self):
  rows=[row(1,'anchor'),row(2,'',3),row(3,'',3),row(4,'after')]
  nodes=[node('anchor'),node('Image'),node('Image'),node('after')]
  self.assertIs(reply.source_node(rows,nodes,3),nodes[2])
 def test_ambiguous_images_are_not_selected_by_label(self):
  with self.assertRaisesRegex(reply.ReplyError,'REPLY_SOURCE_AMBIGUOUS'):
   reply.source_node([row(1,'',3),row(2,'',3)],[node('Image')],2)
 def test_nontext_source_kind_matches_native_type(self):
  for kind,number in [('image',3),('voice',34),('video',43),('sticker',47)]:
   self.assertTrue(reply.source_kind_supported(row(1,'',number),kind))
  self.assertFalse(reply.source_kind_supported(row(1,'',3),'file'))
  self.assertFalse(reply.source_kind_supported(row(1,'',10000),'system'))
 def test_time_separators_are_removed_but_clock_text_is_kept(self):
  nodes=[{**node('08:43'),'role':'list-item','bounds':{'y':0,'height':41}}, {**node('08:43'),'role':'list-item','bounds':{'y':41,'height':72}}]
  messages={'bounds':{'y':0,'height':200},'children':nodes}
  self.assertEqual(reply.message_nodes(messages),nodes[1:])
 def test_media_quote_cleanup_selects_sibling_cancel_not_thumbnail(self):
  thumbnail={'role':'push-button','bounds':{'x':80,'y':10,'width':40,'height':40}}
  preview={'role':'invalid','name':'Quote source','bounds':{'x':0,'y':0,'width':130,'height':50},'children':[thumbnail]}
  cancel={'role':'push-button','bounds':{'x':136,'y':16,'width':16,'height':16}}
  duplicate={**cancel,'children':[cancel]}
  self.assertIs(reply.quote_cancel_button({'children':[preview,duplicate]},'Quote source'),cancel)
  self.assertIsNone(reply.quote_cancel_button({'children':[preview]},'Quote source'))
 def test_quote_cleanup_never_selects_unowned_preview(self):
  self.assertIsNone(reply.quote_cancel_button({'children':[{'role':'invalid','name':'user draft'}]},'Quote source'))
 def test_ready_chat_requires_unique_header_editor_messages_and_window(self):
  nodes=[{'role':'label','name':'target'},{'role':'list','name':'Messages'}, {'role':'text','name':'target','states':['EDITABLE']},{'role':'frame','name':'Weixin'}]
  self.assertTrue(reply.chat_ready(nodes,'target'))
  self.assertFalse(reply.chat_ready(nodes,'other'))
  for i in range(len(nodes)):
   self.assertFalse(reply.chat_ready(nodes[:i]+nodes[i+1:],'target'))
  self.assertFalse(reply.chat_ready(nodes+[nodes[0]],'target'))
 def test_quoted_media_caption_is_not_another_media_message(self):
  self.assertFalse(reply.row_matches(row(1,'',3),"reply\nQuote Sender's message: Image"))
  self.assertTrue(reply.row_matches(row(1,'',3),'Image'))

class ViewportContextTests(unittest.TestCase):
 def test_partial_anchor_disambiguates_adjacent_images(self):
  rows=[row(1,'anchor'),row(2,'',3),row(3,'',3),row(4,'other'),row(5,'second anchor'),row(6,'',3),row(7,'',3)]
  children=[dict(node('second anchor'),role='list-item',bounds={'x':0,'y':60,'width':300,'height':71}),
            dict(node('Image'),role='list-item',bounds={'x':0,'y':131,'width':300,'height':198}),
            dict(node('Image'),role='list-item',bounds={'x':0,'y':329,'width':300,'height':178})]
  messages={'bounds':{'x':0,'y':100,'width':300,'height':450},'children':children}
  self.assertIs(reply.source_node(rows,reply.message_nodes(messages),6),children[1])
 def test_offscreen_rows_are_not_context(self):
  children=[dict(node('old'),role='list-item',bounds={'x':0,'y':0,'width':300,'height':80}),
            dict(node('new'),role='list-item',bounds={'x':0,'y':120,'width':300,'height':80})]
  messages={'bounds':{'x':0,'y':100,'width':300,'height':300},'children':children}
  self.assertEqual(reply.message_nodes(messages),children[1:])
 def test_partial_source_cannot_be_clicked_outside_viewport(self):
  target={'bounds':{'x':0,'y':0,'width':300,'height':150}}
  messages={'bounds':{'x':0,'y':100,'width':300,'height':300}}
  self.assertIsNone(reply.fully_visible_target(target,messages))
  target['bounds']['y']=120
  self.assertIs(reply.fully_visible_target(target,messages),target)


class ReplyViewportSafetyTests(unittest.TestCase):
 def fixture(self, message='source'):
  item={'role':'list-item','name':message,'bounds':{'x':300,'y':180,'width':500,'height':70}}
  return {'children':[
   {'role':'frame','name':'Weixin','window':{'pid':100},'bounds':{'x':0,'y':0,'width':1000,'height':700}},
   {'role':'label','name':'target'},
   {'role':'list','name':'Messages','bounds':{'x':280,'y':100,'width':600,'height':400},'children':[item]},
   {'role':'text','name':'target','states':['EDITABLE']}]}
 def test_visible_source_is_located_without_any_scroll(self):
  tree=self.fixture()
  with mock.patch.object(reply,'tree',return_value=tree), mock.patch.object(reply.subprocess,'run',side_effect=AssertionError('visible source must not scroll')):
   found=reply.locate_source([row(1,'source')],1,'target',100)
  self.assertEqual(found['name'],'source')
 def test_preview_of_visible_source_never_scrolls_or_sends(self):
  state={'quoted':False}
  quote={'role':'menu-item','name':'Quote','bounds':{'x':0,'y':0,'width':1,'height':1}}
  cancel={'role':'push-button','name':'cancel'}
  def tree():
   t=self.fixture();t['children'].append(quote)
   if state['quoted']:t['children'].append({'role':'invalid','name':"Quote Sender's message: source"})
   return t
  def click(n,*args,**kw):
   if n is quote:state['quoted']=True
   if n is cancel:state['quoted']=False
  def api(request,**kw):
   from io import BytesIO
   import json
   url=request.full_url
   value=({'loggedInUser':'account'} if '/status/auth' in url else
          [{'id':'group@chatroom','isGroup':True,'name':'target'}] if '/chats?' in url else
          [{'localId':1,'serverId':'123','senderName':'Sender','isSelf':False}])
   return BytesIO(json.dumps(value).encode())
  def run(argv,*args,**kw):
   if argv[0]=='xdotool' or argv[0] in ['/opt/tools/input','/opt/tools/key']:
    raise AssertionError('visible preview must not scroll, type, or send')
   return subprocess.CompletedProcess(argv,0,stdout='')
  params={'accountId':'account','chatId':'group@chatroom','sourceMessageId':'123','sourceText':'source','text':'must not send','previewOnly':True}
  queries=[[{'db_name':'message_0.db','hex_key':'abc'}],[{'local_id':1,'server_id':123,'type':1,'body':'source'.encode().hex()}]]
  with mock.patch.dict(reply.os.environ,{'AGENT_WECHAT_TOKEN':'token'}), mock.patch.object(reply.urllib.request,'urlopen',side_effect=api), mock.patch.object(reply,'query',side_effect=queries), mock.patch.object(reply.Path,'exists',return_value=True), mock.patch.object(reply,'tree',side_effect=tree), mock.patch.object(reply,'get_text',return_value=''), mock.patch.object(reply,'click',side_effect=click), mock.patch.object(reply,'quote_cancel_button',return_value=cancel), mock.patch.object(reply.subprocess,'run',side_effect=run), mock.patch.object(reply.time,'sleep'):
   self.assertEqual(reply.main(params)['status'],'validated')
  self.assertFalse(state['quoted'])
 def test_client_restart_is_distinguished_from_changed_chat(self):
  nodes=list(reply.flatten(self.fixture()))
  frame=next(n for n in nodes if n.get('role')=='frame');frame['window']['pid']=101
  with self.assertRaisesRegex(reply.ReplyError,'REPLY_CLIENT_RESTARTED'):
   reply.require_target(nodes,'target',100)
 def test_missing_client_is_not_reported_as_changed_chat(self):
  with self.assertRaisesRegex(reply.ReplyError,'REPLY_CLIENT_UNAVAILABLE'):
   reply.require_target([], 'target',100)
 def test_different_chat_is_still_rejected(self):
  with self.assertRaisesRegex(reply.ReplyError,'REPLY_TARGET_CHANGED'):
   reply.require_target(list(reply.flatten(self.fixture())),'other',100)
 def test_unavailable_source_uses_paced_bounded_scroll(self):
  with mock.patch.object(reply,'tree',return_value=self.fixture('other')), mock.patch.object(reply.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run, mock.patch.object(reply.time,'sleep'):
   self.assertIsNone(reply.locate_source([row(1,'source'),row(2,'other')],1,'target',100))
  self.assertEqual(run.call_count,2)
  for call in run.call_args_list:
   argv=call.args[0]
   self.assertLessEqual(int(argv[argv.index('--repeat')+1]),12)
   self.assertGreaterEqual(int(argv[argv.index('--delay')+1]),80)


class MixedMediaIdentityTests(unittest.TestCase):
 def channels(self,i,author='Fixture Author'):
  return row(i,'<msg><appmsg><type>51</type><title></title><finderFeed><nickname>'+author+'</nickname></finderFeed></appmsg></msg>',49)
 def test_channels_card_matches_exact_author_label(self):
  r=self.channels(1)
  self.assertTrue(reply.row_matches(r,'ChannelsFixture Author'))
  self.assertFalse(reply.row_matches(r,'ChannelsFixture Author extended'))
  self.assertFalse(reply.row_matches(r,'ChannelsAnother Author'))
 def test_repeated_image_is_bound_by_channels_and_text_context(self):
  rows=[row(1,'',3),row(2,'old'),row(3,'',3),self.channels(4),row(5,'anchor')]
  visible=[node('Image'),node('ChannelsFixture Author'),node('anchor')]
  self.assertIs(reply.source_node(rows,visible,3),visible[0])
 def test_repeated_channels_author_requires_unique_ordered_context(self):
  rows=[self.channels(1),row(2,'old'),self.channels(3),row(4,'anchor')]
  visible=[node('ChannelsFixture Author'),node('anchor')]
  self.assertIs(reply.source_node(rows,visible,3),visible[0])
  with self.assertRaisesRegex(reply.ReplyError,'REPLY_SOURCE_AMBIGUOUS'):
   reply.source_node(rows,[node('ChannelsFixture Author')],3)
 def test_system_template_can_anchor_nontext_source(self):
  system=row(2,'<sysmsg><sysmsgtemplate><content_template><template>$member$ joined</template><link_list><link name="member"><plain>Fixture Member</plain></link></link_list></content_template></sysmsgtemplate></sysmsg>',10000)
  rows=[row(1,'',3),system,row(3,'',3),row(4,'anchor')]
  visible=[node('Fixture Member joined'),node('Image'),node('anchor')]
  self.assertIs(reply.source_node(rows,visible,3),visible[1])
 def test_unresolved_system_template_is_not_an_identity_anchor(self):
  self.assertFalse(reply.row_matches(row(1,'<sysmsg/>',10000),'unrelated'))

if __name__=='__main__':unittest.main()
