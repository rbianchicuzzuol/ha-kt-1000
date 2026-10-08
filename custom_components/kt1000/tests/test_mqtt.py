import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from aiohttp import web, ClientSession
from aiohttp.test_utils import TestServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.api import KT1000Api
from app.server import Runtime,Store
from app.telemetry import snapshot
from app.mqtt import MQTTPublisher,state_payloads

class FakeClient:
    def __init__(self):
        self.publish=AsyncMock();self.subscribe=AsyncMock();self.queue=asyncio.Queue()
    @property
    def messages(self):
        async def messages():
            while True:yield await self.queue.get()
        return messages()

class Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.rt=Runtime(KT1000Api(None,'test-client','DO-NOT-EXPORT-SECRET','test-device'),Store(Path(self.tmp.name)/'access.json'),'Apartamento')
        self.rt.api._request=AsyncMock()
        self.rt.last_update_success=True;self.rt.poll_attempted=True
        self.rt.store.history_for('app').append({'code':'unlock_card','value':'9','event_time':1800000000000})
        self.rt.store.people_for('app').append({'name':'Ana','credentials':['unlock_card:9']})
        self.rt.store.offline_for('app').append({'id':'offline1','encrypted_code':'DO-NOT-EXPORT-PIN'})
        self.p=MQTTPublisher(self.rt,{},None);self.client=FakeClient()
    def tearDown(self):self.tmp.cleanup()
    async def test_discovery_all_entities_read_only_unique_ids(self):
        configs=self.p.configs()
        self.assertEqual(len(configs),17)
        self.assertEqual(len({x[1]['unique_id'] for x in configs}),17)
        for topic,config in configs:
            self.assertTrue(topic.startswith('homeassistant/'))
            self.assertNotIn('command_topic',config)
            self.assertEqual(config['device']['identifiers'],[self.p.node])
            if config['name'] not in ('Status da API','Última atualização da nuvem'):
                self.assertEqual(config['availability_mode'],'all')
        await self.p.discover(self.client)
        for call in self.client.publish.call_args_list:
            self.assertTrue(call.kwargs['retain']);self.assertEqual(call.kwargs['qos'],1)
        self.rt.api._request.assert_not_called()
    async def test_states_and_attributes_have_no_secrets(self):
        self.rt.data['latest_by_code']={'residual_electricity':{'value':80,'eventTime':1800000000000},'reverse_lock':{'value':True,'eventTime':1800000000000}}
        await self.p.publish_state(self.client)
        published=str(self.client.publish.call_args_list)
        self.assertNotIn('DO-NOT-EXPORT',published)
        data=state_payloads(snapshot(self.rt))
        self.assertEqual(data['battery']['value'],80)
        self.assertEqual(data['reverse_lock']['value'],'ON')
        self.assertEqual(data['last_user']['value'],'Ana')
        self.assertEqual(data['access_history']['attributes']['acessos'][0]['usuario'],'Ana')
        self.assertTrue(data['battery']['attributes']['ultimo_relato'])
        self.rt.api._request.assert_not_called()
    async def test_unknown_values_do_not_claim_unlocked(self):
        self.rt.data['latest_by_code']={'residual_electricity':{'value':'bad'},'reverse_lock':{'value':'unsupported'}}
        data=state_payloads(snapshot(self.rt))
        self.assertIsNone(data['battery']['value']);self.assertIsNone(data['reverse_lock']['value'])
    async def test_events_no_initial_replay_nonretained_new_event_once(self):
        await self.p.publish_state(self.client)
        self.assertFalse(any('unlock_event/state' in x.args[0] for x in self.client.publish.call_args_list))
        self.rt.store.history_for('app')[0]['event_time']+=1
        await self.p.publish_state(self.client);await self.p.publish_state(self.client)
        calls=[x for x in self.client.publish.call_args_list if 'unlock_event/state' in x.args[0]]
        self.assertEqual(len(calls),1)
        self.assertFalse(calls[0].kwargs['retain']);self.assertEqual(calls[0].kwargs['qos'],0)
        self.assertEqual(json.loads(calls[0].args[1])['event_type'],'cartao')
    async def test_ha_birth_republishes_discovery_and_states_without_events(self):
        task=asyncio.create_task(self.p.connected(self.client))
        for _ in range(100):
            if self.rt.mqtt_connected:break
            await asyncio.sleep(0)
        self.client.subscribe.assert_awaited_once_with('homeassistant/status',qos=1)
        self.client.publish.reset_mock()
        await self.client.queue.put(SimpleNamespace(topic='homeassistant/status',payload=b'online'))
        for _ in range(100):
            if self.client.publish.await_count>=33:break
            await asyncio.sleep(0)
        configs=[x for x in self.client.publish.call_args_list if x.args[0].endswith('/config')]
        self.assertEqual(len(configs),17)
        self.assertFalse(any('unlock_event/state' in x.args[0] for x in self.client.publish.call_args_list))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(self.rt.mqtt_connected)
    async def test_failed_cloud_availability_diagnostics_preserved(self):
        self.rt.last_update_success=False;self.rt.last_error='Falha de rede'
        await self.p.publish_state(self.client)
        self.assertIn(unittest.mock.call(self.p.base+'/cloud_availability','offline',qos=1,retain=True),self.client.publish.call_args_list)
        values=state_payloads(snapshot(self.rt))
        self.assertEqual(values['cloud_status']['value'],'Erro')
        self.assertEqual(values['cloud_status']['attributes']['ultimo_erro'],'Falha de rede')
    async def test_manual_broker_does_not_query_supervisor(self):
        session=SimpleNamespace(get=unittest.mock.Mock(side_effect=AssertionError('Supervisor should not be used')))
        p=MQTTPublisher(self.rt,{'mqtt_host':'broker.local','mqtt_username':'user','mqtt_password':'secret','mqtt_port':1884},session)
        options=await p.broker_options()
        self.assertEqual(options['hostname'],'broker.local');self.assertEqual(options['port'],1884)
        self.assertEqual(options['password'],'secret');session.get.assert_not_called()
    async def test_automatic_supervisor_credentials(self):
        received=[]
        async def mqtt_service(request):
            received.append((request.method,request.headers.get('Authorization')))
            return web.json_response({'result':'ok','data':{'host':'core-mosquitto','port':'1883','username':'supervisor-user','password':'secret','ssl':False}})
        app=web.Application();app.router.add_get('/services/mqtt',mqtt_service)
        async with TestServer(app) as server,ClientSession() as session:
            class RoutedSession:
                def get(self,url,**kwargs):
                    self_url=str(server.make_url('/services/mqtt'))
                    return session.get(self_url,**kwargs)
            p=MQTTPublisher(self.rt,{},RoutedSession())
            with patch.dict(os.environ,{'SUPERVISOR_TOKEN':'mock-token'}):options=await p.broker_options()
        self.assertEqual(received,[('GET','Bearer mock-token')])
        self.assertEqual(options['hostname'],'core-mosquitto');self.assertEqual(options['username'],'supervisor-user')
    async def test_graceful_shutdown_offline_and_last_will(self):
        import aiomqtt
        captured={}
        class Connection(FakeClient):
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        client=Connection()
        def factory(**kwargs):captured.update(kwargs);return client
        p=MQTTPublisher(self.rt,{'mqtt_host':'broker'},None)
        with patch.object(aiomqtt,'Client',side_effect=factory):
            task=asyncio.create_task(p.run())
            for _ in range(100):
                if self.rt.mqtt_connected:break
                await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(captured['will'].payload,'offline');self.assertTrue(captured['will'].retain)
        self.assertEqual(client.publish.call_args.args,(p.base+'/availability','offline'))
        self.assertFalse(self.rt.mqtt_connected)
    async def test_reconnection_forces_identical_states(self):
        await self.p.publish_state(self.client)
        self.client.publish.reset_mock()
        await self.p.publish_state(self.client)
        self.assertEqual(self.client.publish.await_count,1) # availability heartbeat
        await self.p.publish_state(self.client,force=True)
        self.assertEqual(self.client.publish.await_count,17)

class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_aiomqtt_client_local_protocol_fixture(self):
        """Use the installed MQTT client over localhost TCP, never the user's broker."""
        packets=[];published=[];subscriptions=[]
        async def handle(reader,writer):
            try:
                while True:
                    header=(await reader.readexactly(1))[0]
                    remaining=0;multiplier=1
                    while True:
                        digit=(await reader.readexactly(1))[0]
                        remaining+=(digit&127)*multiplier
                        if not digit&128:break
                        multiplier*=128
                    payload=await reader.readexactly(remaining)
                    packets.append((header,payload))
                    kind=header>>4
                    if kind==1:writer.write(b'\x20\x02\x00\x00')
                    elif kind==8:
                        size=int.from_bytes(payload[2:4],'big')
                        subscriptions.append(payload[4:4+size].decode())
                        writer.write(b'\x90\x03'+payload[:2]+b'\x01')
                    elif kind==3:
                        size=int.from_bytes(payload[:2],'big');topic=payload[2:2+size].decode();offset=2+size
                        qos=(header>>1)&3
                        if qos:
                            mid=payload[offset:offset+2];offset+=2
                            writer.write(b'\x40\x02'+mid)
                        published.append((topic,payload[offset:].decode(),bool(header&1)))
                    elif kind==12:writer.write(b'\xd0\x00')
                    elif kind==14:break
                    await writer.drain()
            except (asyncio.IncompleteReadError,ConnectionError):pass
            finally:
                writer.close();await writer.wait_closed()
        server=await asyncio.start_server(handle,'127.0.0.1',0)
        port=server.sockets[0].getsockname()[1]
        with tempfile.TemporaryDirectory() as directory:
            rt=Runtime(KT1000Api(None,'fake','secret','transport-device'),Store(Path(directory)/'access.json'),'Teste local')
            publisher=MQTTPublisher(rt,{'mqtt_host':'127.0.0.1','mqtt_port':port},None)
            task=asyncio.create_task(publisher.run())
            try:
                async with asyncio.timeout(5):
                    while not rt.mqtt_connected:await asyncio.sleep(.01)
                self.assertEqual(subscriptions,['homeassistant/status'])
                configs=[x for x in published if x[0].endswith('/config')]
                self.assertEqual(len(configs),17)
                self.assertTrue(all(x[2] for x in configs))
                self.assertTrue(any(b'offline' in payload for kind,payload in packets if kind>>4==1))
                self.assertFalse(any('command' in topic for topic,_,_ in published))
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
                server.close();await server.wait_closed()
            self.assertEqual(published[-1],(publisher.base+'/availability','offline',True))
