import asyncio
import threading
import unittest
from types import SimpleNamespace
from plva.cloud_bridge import protected_state, scrub_tree, execute
from plva.privacy import PrivacySession

class CloudBridgeTests(unittest.TestCase):
    def test_original_frames_values_and_key_never_enter_cloud_state(self):
        privacy=PrivacySession()
        privacy._register('NAME','Mia Chen')
        server=SimpleNamespace(lock=threading.RLock(),api_key='secret-key',web_runtime=SimpleNamespace(scrub=privacy.scrub),state={
            'raw_frame':'private-pixels','api_key':'secret-key','protected_frame':'iVBORw0KGgo-protected',
            'task':'Look up Mia Chen','events':[{'message':'Found Mia Chen'}],
            'browser':{'tabs':[{'id':'1','title':'Mia Chen account','url':'https://example.com/account?token=secret#private'}]},
            'manifest':[{'token':'[NAME_1]','kind':'NAME'}], 'unexpected_private_object':{'value':'private'}})
        result=protected_state(server,'run-1')
        self.assertNotIn('raw_frame',result)
        self.assertNotIn('api_key',result)
        self.assertNotIn('unexpected_private_object',result)
        self.assertNotIn('Mia Chen',str(result))
        self.assertEqual(result['browser']['tabs'][0]['url'],'https://example.com')
        self.assertEqual(result['task'],'Look up [NAME_1]')
        self.assertTrue(result['can_run_astra'])
    def test_recursive_exports_remove_private_fields(self):
        result=scrub_tree({'nested':[{'raw_frame':'private','api_key':'secret','text':'hello'}]},lambda value:value)
        self.assertEqual(result,{'nested':[{'text':'hello'}]})
    def test_connector_rejects_api_key_config_fixture_and_unknown_commands(self):
        async def check():
            for path in ['/api/config','/api/receipt','/unknown']:
                status,_=await execute({'method':'POST','path':path},None,None,[''])
                self.assertEqual(status,403)
            status,_=await execute({'method':'POST','path':'/api/run','body':{'mode':'rehearsal','source':'fixture','task':'test'}},None,None,[''])
            self.assertEqual(status,400)
        asyncio.run(check())

if __name__=='__main__':
    unittest.main()
