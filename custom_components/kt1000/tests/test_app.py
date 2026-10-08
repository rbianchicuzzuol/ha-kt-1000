import unittest
import tempfile
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.api import KT1000Api, KT1000ApiError
from app.commands import _safe_temp_password
from app.server import Store, Runtime, ingress_only, import_data, create_app
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

class Tests(unittest.IsolatedAsyncioTestCase):
    def api(self):
        api=KT1000Api(None,'fake','0'*32,'test-device')
        api._request=AsyncMock(return_value=True)
        return api

    async def test_offline_once(self):
        api=self.api()
        with patch('app.api.time.time',return_value=1800000123):
            await api.create_offline_temporary_password('Teste',1)
        body=api._request.call_args.kwargs['json_body']
        self.assertEqual(body['type'],'once')
        self.assertEqual(body['effective_time']%3600,0)
        self.assertEqual(body['invalid_time']-body['effective_time'],21600)

    async def test_offline_multiple_validation(self):
        api=self.api()
        with self.assertRaises(KT1000ApiError):await api.create_offline_temporary_password('x',0,3601,3700)
        api._request.assert_not_called()
        await api.create_offline_temporary_password('x',0,3601,10801)
        self.assertEqual(api._request.call_args.kwargs['json_body']['type'],'multiple')

    async def test_offline_clear_requires_id(self):
        api=self.api()
        with self.assertRaises(KT1000ApiError):await api.create_offline_temporary_password('x',8,3600)
        api._request.assert_not_called()

    async def test_password_id_preserved(self):
        result=_safe_temp_password({'password_id':1202237313,'password':'secret','ticket_key':'secret','phase':2})
        self.assertEqual(result['id'],1202237313)
        self.assertNotIn('password',result)
        self.assertNotIn('ticket_key',result)

    async def test_expired_delete(self):
        api=self.api()
        await api.delete_temporary_password(1202237313)
        self.assertEqual(api._request.call_args.args[0],'DELETE')
        self.assertTrue(api._request.call_args.args[1].endswith('/1202237313'))
        api._request.reset_mock()
        with self.assertRaises(KT1000ApiError):await api.delete_temporary_password('')
        api._request.assert_not_called()

    async def test_delete_false_is_error(self):
        api=self.api();api._request.return_value=False
        with self.assertRaises(KT1000ApiError):await api.delete_temporary_password(1)

    async def test_unlock_disabled_no_ticket_or_command(self):
        api=self.api()
        with self.assertRaises(KT1000ApiError):await api.remote_unlock()
        api._request.assert_not_called()

    async def test_unlock_paths_mock_only(self):
        for mode,path in [('open_door','/door-lock/password-free/open-door'),('door_operate','/password-free/door-operate')]:
            api=self.api();api.remote_unlock_enabled=True;api.remote_unlock_mode=mode
            api._request.side_effect=[{'ticket_id':'fake-ticket'},True]
            self.assertTrue(await api.remote_unlock())
            self.assertTrue(api._request.call_args.args[1].endswith(path))
            self.assertEqual('open' in api._request.call_args.kwargs['json_body'],mode=='door_operate')

    async def test_dispatch_confirmation_schema_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'state.json');api=self.api();rt=Runtime(api,store,'Teste')
            with self.assertRaises(ValueError):await rt.dispatch({'type':'kt1000/remote_unlock','entry_id':'app','confirmed':False})
            api._request.assert_not_called()
            with self.assertRaises(ValueError):await rt.dispatch({'type':'kt1000/remote_unlock','entry_id':'app','confirmed':'true'})
            await rt.dispatch({'type':'kt1000/save_person','entry_id':'app','name':'Pessoa'})
            self.assertEqual(Store(store.path).people_for('app')[0]['name'],'Pessoa')
            result=await rt.dispatch({'type':'kt1000/overview'})
            self.assertFalse(result['remote_unlock_enabled'])

    async def test_history_collision_and_read_only_poll(self):
        with tempfile.TemporaryDirectory() as folder:
            api=self.api();api._request.return_value={'logs':[{'code':c,'value':'1','eventTime':1000} for c in ['unlock_password','unlock_card']]}
            rt=Runtime(api,Store(Path(folder)/'state.json'),'Test')
            await rt.poll();await rt.poll()
            self.assertEqual(len(rt.store.history_for('app')),2)
            self.assertTrue(all(call.args[0]=='GET' for call in api._request.call_args_list))

    async def test_ingress_rejects_other_callers(self):
        handler=AsyncMock()
        with self.assertRaises(web.HTTPForbidden):await ingress_only(type('Request',(),{'remote':'127.0.0.1'})(),handler)
        handler.assert_not_called()

    async def test_import_merges(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=Runtime(self.api(),Store(Path(folder)/'state.json'),'Test')
            class Request:
                app={'runtime':rt}
                async def json(self):return {'entry_id':'old','data':{'data':{'history':{'old':[{'event_time':1000,'code':'unlock_card','value':'2'}]},'people':{'old':[{'name':'Ana','credentials':['unlock_card:2']}]}}}}
            self.assertEqual((await import_data(Request())).status,200)
            await import_data(Request())
            self.assertEqual(len(rt.store.history_for('app')),1)
            self.assertEqual(len(rt.store.people_for('app')),1)

class CommunicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_signature_cross_language_fixture(self):
        # Independently generated with Node crypto HMAC-SHA256; no live credentials.
        api=KT1000Api(None,'test-client','test-secret','test-device')
        with patch('app.api.time.time',return_value=1588925778):
            timestamp,signature=api._sign('GET','/v1.0/token?grant_type=1')
        self.assertEqual(timestamp,'1588925778000')
        self.assertEqual(signature,'09BCCB8654D63513F682D7B67BA0FEB7FB04B23ADA97599C675EB91B56CE7999')

    async def test_masked_credentials_never_contact_tuya(self):
        for secret in ('', '*****', '•••••', 'bad secret'):
            api=KT1000Api(None,'test-id',secret,'test-device')
            with self.assertRaises(KT1000ApiError):await api.get_token()

    async def test_normalize_external_whitespace(self):
        api=KT1000Api(None,' test-id\n',' test-secret\r\n',' device-id ')
        self.assertEqual(api.client_id,'test-id')
        self.assertEqual(api.client_secret,'test-secret')
        self.assertEqual(api.device_id,'device-id')

    async def test_poll_error_visible_and_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            api=KT1000Api(None,'test-id','0'*32,'test-device')
            api.get_report_logs=AsyncMock(side_effect=KT1000ApiError('Tuya token error 1004: sign invalid'))
            api.get_offline_temporary_passwords=AsyncMock(return_value=[])
            api._request=AsyncMock()
            rt=Runtime(api,Store(Path(folder)/'state.json'),'Test')
            initial=await rt.dispatch({'type':'kt1000/overview'})
            self.assertTrue(initial['communication_pending'])
            result=await rt.dispatch({'type':'kt1000/refresh'})
            self.assertIn('1004',result['communication_error'])
            self.assertFalse(result['online'])
            self.assertFalse(result['communication_pending'])
            api._request.assert_not_called()
            api.get_report_logs.side_effect=None
            api.get_report_logs.return_value={'logs':[]}
            result=await rt.dispatch({'type':'kt1000/refresh'})
            self.assertTrue(result['online'])
            self.assertIsNone(result['communication_error'])

    async def test_token_1004_has_actionable_message(self):
        class Response:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def json(self,**kwargs):return {'success':False,'code':1004,'msg':'sign invalid'}
        class Session:
            def get(self,*args,**kwargs):return Response()
        api=KT1000Api(Session(),'test-id','test-secret','test-device')
        with self.assertRaisesRegex(KT1000ApiError,'client_secret reais'):await api.get_token()

class OfflineTests(unittest.IsolatedAsyncioTestCase):
    async def test_cloud_pages_types_and_aliases(self):
        from app.offline import normalize
        api=KT1000Api(None,'fake','0'*32,'fake-device')
        api._request=AsyncMock(side_effect=[{'records':[{'pwd_id':'1','pwd_name':'Celular','pwd_type_code':'once','gmt_start':'3600','gmt_expired':'25200','status':1,'password':'discard'}],'has_more':True},{'records':[{'pwd_id':'2'}],'has_more':False}])
        result=await api.get_offline_temporary_passwords()
        self.assertEqual(len(result),2)
        for call in api._request.call_args_list:
            self.assertEqual(call.args[0],'GET')
            self.assertEqual(call.args[2]['pwd_type_codes'],'multiple,once,clear_one,clear_all')
        self.assertEqual(api._request.call_args.args[2]['page_no'],2)
        item=normalize(result[0]);self.assertEqual(item['name'],'Celular');self.assertEqual(item['invalid_time'],25200);self.assertNotIn('password',item)

    async def test_creation_saved_encrypted_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            api=KT1000Api(None,'fake','0'*32,'fake-device')
            api.create_offline_temporary_password=AsyncMock(return_value={'offline_temp_password_id':'321','offline_temp_password':'0282554135','offline_temp_password_name':'Teste','effective_time':3600,'invalid_time':25200})
            path=Path(folder)/'access.json';rt=Runtime(api,Store(path),'Test')
            result=await rt.dispatch({'type':'kt1000/create_offline_temp_password','entry_id':'app','pwd_type':1,'name':'Teste'})
            self.assertTrue(result['ok']);self.assertIsNone(result['warning'])
            self.assertNotIn('0282554135',path.read_text())
            store=Store(path)
            self.assertEqual(store.reveal_offline('app','321'),'0282554135')
            metadata=store.offline_metadata('app');self.assertTrue(metadata[0]['has_code']);self.assertNotIn('encrypted_code',metadata[0]);self.assertEqual(metadata[0]['type'],'once')
            self.assertEqual((path.parent/'passwords.key').stat().st_mode&0o777,0o600)

    async def test_sync_native_changes_and_preserves_local_code(self):
        with tempfile.TemporaryDirectory() as folder:
            api=KT1000Api(None,'fake','0'*32,'fake-device');store=Store(Path(folder)/'state.json')
            await store.record_offline('app',{'offline_temp_password_id':'1','offline_temp_password':'1234567890'},'Old',1)
            api.get_offline_temporary_passwords=AsyncMock(return_value=[{'pwd_id':'1','pwd_name':'Renomeada pelo celular','pwd_type_code':'once','gmt_expired':'25200','status':2},{'pwd_id':'2','pwd_name':'Criada pelo celular','pwd_type_code':'multiple','status':1}])
            rt=Runtime(api,store,'Test');await rt.sync_offline()
            rows=store.offline_metadata('app');by_id={x['id']:x for x in rows}
            self.assertEqual(by_id['1']['name'],'Renomeada pelo celular');self.assertEqual(by_id['1']['status'],2)
            self.assertTrue(by_id['1']['has_code']);self.assertFalse(by_id['2']['has_code'])
            self.assertEqual(store.reveal_offline('app','1'),'1234567890')
            with self.assertRaises(ValueError):store.reveal_offline('app','2')

    async def test_sync_failure_keeps_history(self):
        with tempfile.TemporaryDirectory() as folder:
            api=KT1000Api(None,'fake','0'*32,'fake-device');api.get_offline_temporary_passwords=AsyncMock(side_effect=KT1000ApiError('not supported'))
            store=Store(Path(folder)/'state.json');store.upsert_offline('app',{'id':'1','name':'Local'})
            rt=Runtime(api,store,'Test');await rt.sync_offline()
            self.assertEqual(len(store.offline_metadata('app')),1)
            self.assertIn('preservado',rt.offline_sync_warning)
            response=await rt.dispatch({'type':'kt1000/offline_temp_passwords','entry_id':'app'})
            self.assertTrue(response['ok']);self.assertEqual(len(response['items']),1);self.assertTrue(response['warning'])

    async def test_missing_cloud_record_not_falsely_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            api=KT1000Api(None,'fake','0'*32,'fake-device');api.get_offline_temporary_passwords=AsyncMock(return_value=[])
            store=Store(Path(folder)/'state.json');store.upsert_offline('app',{'id':'1','status':1})
            rt=Runtime(api,store,'Test');await rt.sync_offline()
            row=store.offline_metadata('app')[0]
            self.assertFalse(row['cloud_present']);self.assertEqual(row['status'],1)

    async def test_failed_local_save_does_not_hide_generated_code(self):
        with tempfile.TemporaryDirectory() as folder:
            api=KT1000Api(None,'fake','0'*32,'fake-device');api.create_offline_temporary_password=AsyncMock(return_value={'offline_temp_password_id':'1','offline_temp_password':'1234567890'})
            store=Store(Path(folder)/'state.json');store.record_offline=AsyncMock(side_effect=OSError('disk full'))
            result=await Runtime(api,store,'Test').dispatch({'type':'kt1000/create_offline_temp_password','entry_id':'app','pwd_type':1,'name':'Teste'})
            self.assertTrue(result['ok']);self.assertEqual(result['result']['offline_temp_password'],'1234567890');self.assertIn('não repita',result['warning'])
            self.assertEqual(api.create_offline_temporary_password.await_count,1)

    async def test_vault_missing_key_does_not_replace_it(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'state.json');await store.record_offline('app',{'offline_temp_password_id':'1','offline_temp_password':'1234567890'},'Test',1)
            key=store.path.parent/'passwords.key';key.unlink()
            with self.assertRaises(ValueError):store.reveal_offline('app','1')
            with self.assertRaises(ValueError):await store.record_offline('app',{'offline_temp_password_id':'2','offline_temp_password':'9999999999'},'Test',1)
            self.assertFalse(key.exists())

    async def test_legacy_store_upgrades_without_data_loss(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json';path.write_text('{"people":{"app":[{"name":"Rodrigo","credentials":[]}]},"history":{"app":[]}}')
            store=Store(path);await store.record_offline('app',{'offline_temp_password_id':'1','offline_temp_password':'1234567890'},'Test',1)
            self.assertEqual(Store(path).people_for('app')[0]['name'],'Rodrigo')

class RecordDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_record_uses_cloud_record_endpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            api=KT1000Api(None,'fake','0'*32,'fake-device')
            api.get_temporary_passwords=AsyncMock(return_value=[{'password_id':1202237313,'invalid_time':1,'phase':2}])
            api._request=AsyncMock(return_value=True)
            rt=Runtime(api,Store(Path(folder)/'state.json'),'Test')
            result=await rt.dispatch({'type':'kt1000/delete_temp_password_record','entry_id':'app','password_id':'1202237313'})
            self.assertTrue(result['record_deleted'])
            api._request.assert_awaited_once_with('DELETE','/v1.0/devices/fake-device/door-lock/temp-passwords/1202237313/record')

    async def test_active_record_never_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            api=KT1000Api(None,'fake','0'*32,'fake-device')
            api.get_temporary_passwords=AsyncMock(return_value=[{'id':1,'invalid_time':4102444800,'phase':2}]);api._request=AsyncMock()
            rt=Runtime(api,Store(Path(folder)/'state.json'),'Test')
            with self.assertRaises(ValueError):await rt.dispatch({'type':'kt1000/delete_temp_password_record','entry_id':'app','password_id':'1'})
            api._request.assert_not_called()

    async def test_missing_record_or_id_never_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            api=KT1000Api(None,'fake','0'*32,'fake-device');api.get_temporary_passwords=AsyncMock(return_value=[]);api._request=AsyncMock()
            rt=Runtime(api,Store(Path(folder)/'state.json'),'Test')
            for value in ('', '1', True):
                with self.assertRaises(ValueError):await rt.dispatch({'type':'kt1000/delete_temp_password_record','entry_id':'app','password_id':value})
            api._request.assert_not_called()

    async def test_record_false_is_not_success(self):
        api=KT1000Api(None,'fake','0'*32,'fake-device');api._request=AsyncMock(return_value=False)
        with self.assertRaises(KT1000ApiError):await api.delete_temporary_password_record('1')

    async def test_original_delete_2304_instructs_record_no_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            api=KT1000Api(None,'fake','0'*32,'fake-device');api.delete_temporary_password=AsyncMock(side_effect=KT1000ApiError('password has expired!',code=2304));api._request=AsyncMock()
            rt=Runtime(api,Store(Path(folder)/'state.json'),'Test')
            result=await rt.dispatch({'type':'kt1000/delete_temp_password','entry_id':'app','password_id':'1'})
            self.assertFalse(result['ok']);self.assertTrue(result['expired']);self.assertIn('Excluir registro',result['error']);api._request.assert_not_called()

    async def test_record_cloud_rejection_remains_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            api=KT1000Api(None,'fake','0'*32,'fake-device');api.get_temporary_passwords=AsyncMock(return_value=[{'id':1,'invalid_time':1}]);api._request=AsyncMock(side_effect=KT1000ApiError('permission denied',code=1106))
            result=await Runtime(api,Store(Path(folder)/'state.json'),'Test').dispatch({'type':'kt1000/delete_temp_password_record','entry_id':'app','password_id':'1'})
            self.assertFalse(result['ok']);self.assertIn('permission denied',result['error']);self.assertEqual(api._request.await_count,1)

class PersonManagementTests(unittest.IsolatedAsyncioTestCase):
    async def make_runtime(self, folder):
        api=KT1000Api(None,'fake','0'*32,'fake-device');api._request=AsyncMock()
        store=Store(Path(folder)/'state.json')
        store.data={'people':{'app':[{'name':'Ana','credentials':['unlock_card:1']},{'name':'Bia','credentials':[]}]},'history':{'app':[]}}
        return Runtime(api,store,'Test')

    async def test_adding_owned_credential_does_not_steal(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=await self.make_runtime(folder)
            with self.assertRaises(ValueError):await rt.dispatch({'type':'kt1000/assign','entry_id':'app','person':'Bia','credential':'unlock_card:1'})
            self.assertEqual(rt.store.people_for('app')[0]['credentials'],['unlock_card:1']);self.assertEqual(rt.store.people_for('app')[1]['credentials'],[]);rt.api._request.assert_not_called()

    async def test_explicit_transfer_persists_single_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=await self.make_runtime(folder)
            await rt.dispatch({'type':'kt1000/assign','entry_id':'app','person':'Bia','credential':'unlock_card:1','expected_owner':'Ana'})
            people=Store(rt.store.path).people_for('app')
            self.assertEqual(people[0]['credentials'],[]);self.assertEqual(people[1]['credentials'],['unlock_card:1']);rt.api._request.assert_not_called()

    async def test_stale_transfer_or_unassign_does_not_modify(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=await self.make_runtime(folder)
            with self.assertRaises(ValueError):await rt.dispatch({'type':'kt1000/assign','entry_id':'app','person':'Bia','credential':'unlock_card:1','expected_owner':'Old'})
            with self.assertRaises(ValueError):await rt.dispatch({'type':'kt1000/unassign','entry_id':'app','credential':'unlock_card:1','expected_person':'Bia'})
            self.assertEqual(rt.store.people_for('app')[0]['credentials'],['unlock_card:1'])

    async def test_invalid_destination_does_not_drop_previous_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=await self.make_runtime(folder)
            with self.assertRaises(ValueError):await rt.dispatch({'type':'kt1000/assign','entry_id':'app','person':'Missing','credential':'unlock_card:1','expected_owner':'Ana'})
            self.assertEqual(rt.store.people_for('app')[0]['credentials'],['unlock_card:1'])

    async def test_desassociate_retains_available_credential_without_history(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=await self.make_runtime(folder)
            await rt.dispatch({'type':'kt1000/unassign','entry_id':'app','credential':'unlock_card:1','expected_person':'Ana'})
            rt=Runtime(rt.api,Store(rt.store.path),'Test');data=await rt.dispatch({'type':'kt1000/overview'})
            credential=next(x for x in data['credentials'] if x['key']=='unlock_card:1');self.assertIsNone(credential['person']);rt.api._request.assert_not_called()

    async def test_delete_person_retains_credentials_and_other_person(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=await self.make_runtime(folder)
            await rt.dispatch({'type':'kt1000/delete_person','entry_id':'app','name':'Ana'})
            data=await rt.dispatch({'type':'kt1000/overview'})
            self.assertEqual([p['name'] for p in data['people']],['Bia']);self.assertEqual(data['credentials'][0]['key'],'unlock_card:1');self.assertIsNone(data['credentials'][0]['person'])

    async def test_rename_keeps_links_rejects_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=await self.make_runtime(folder)
            with self.assertRaises(ValueError):await rt.dispatch({'type':'kt1000/save_person','entry_id':'app','old_name':'Ana','name':'bia'})
            await rt.dispatch({'type':'kt1000/save_person','entry_id':'app','old_name':'Ana','name':'Maria'})
            self.assertEqual(rt.store.people_for('app')[0],{'name':'Maria','credentials':['unlock_card:1']})

    async def test_enrollment_commands_retained_mock_only(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=await self.make_runtime(folder);rt.api.start_credential_enrollment=AsyncMock(return_value=True)
            for kind in ('password','fingerprint','card'):
                result=await rt.dispatch({'type':'kt1000/start_credential_enrollment','entry_id':'app','user_id':'native-user','unlock_type':kind,'user_type':2})
                self.assertTrue(result['ok']);rt.api.start_credential_enrollment.assert_awaited_with('native-user',kind,2)
            rt.api._request.assert_not_called()

class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_standalone_http_assets_and_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            api=KT1000Api(None,'fake','0'*32,'fake-device')
            api._request=AsyncMock(return_value=True)
            app=create_app();app.cleanup_ctx.clear()
            app['runtime']=Runtime(api,Store(Path(folder)/'state.json'),'Test')
            with patch('app.server.INGRESS_IP','127.0.0.1'):
                async with TestClient(TestServer(app)) as client:
                    response=await client.get('/')
                    self.assertEqual(response.status,200)
                    self.assertIn('<kt1000-panel>',await response.text())
                    self.assertEqual((await client.get('/kt1000-panel.js')).status,200)
                    self.assertEqual((await client.get('/assets/icon-64.png')).status,200)
                    response=await client.post('/api/command',json={'type':'kt1000/overview'},headers={'X-KT1000-Request':'1'})
                    self.assertEqual(response.status,200)
                    self.assertFalse((await response.json())['remote_unlock_enabled'])
                    response=await client.post('/api/command',json={'type':'kt1000/remote_unlock','entry_id':'app','confirmed':True},headers={'X-KT1000-Request':'1'})
                    self.assertEqual(response.status,200)
                    self.assertFalse((await response.json())['ok'])
                    api._request.assert_not_called()
                    response=await client.post('/api/command',json={'type':'kt1000/overview'})
                    self.assertEqual(response.status,403)
                    response=await client.post('/api/command',json={'type':'kt1000/nonexistent'},headers={'X-KT1000-Request':'1'})
                    self.assertEqual(response.status,400)

if __name__=='__main__':unittest.main()

class TelemetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_counts_full_history_attributes_bounded(self):
        from app.telemetry import snapshot
        with tempfile.TemporaryDirectory() as directory:
            rt=Runtime(KT1000Api(None,'fake','secret','test'),Store(Path(directory)/'access.json'),'Teste')
            rt.store.history_for('app').extend({'code':'unlock_card','value':'1','event_time':1800000000000+i} for i in range(101))
            data=snapshot(rt)
            self.assertEqual(data['access_count'],101)
            self.assertEqual(len(data['logs']),25)
            self.assertEqual(data['credentials']['unlock_card:1']['quantidade'],101)

    async def test_latest_status_survives_sparse_logs_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            api=KT1000Api(None,'fake','secret','test')
            api.get_report_logs=AsyncMock(side_effect=[{'logs':[{'code':'residual_electricity','value':80,'eventTime':1800000000000},{'code':'reverse_lock','value':True,'eventTime':1800000000001}]},{'logs':[{'code':'unlock_card','value':'7','eventTime':1800000000002}]}])
            path=Path(directory)/'access.json'
            rt=Runtime(api,Store(path),'Teste')
            await rt.poll();await rt.poll()
            self.assertEqual(rt.data['latest_by_code']['residual_electricity']['value'],80)
            restored=Runtime(api,Store(path),'Teste')
            self.assertTrue(restored.data['latest_by_code']['reverse_lock']['value'])
            self.assertFalse(restored.last_update_success)
