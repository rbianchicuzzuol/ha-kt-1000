"""MQTT Discovery publisher. Only HA birth messages are subscribed to."""
import asyncio
import hashlib
import json
import logging
import os
import ssl
from contextlib import suppress
from types import SimpleNamespace
from aiohttp import ClientTimeout
from .telemetry import snapshot
from .helpers import unlock_data, event_timestamp, event_datetime
from .const import ALARM_NAMES

_LOGGER = logging.getLogger(__name__)
EVENT_TYPES = {'unlock_fingerprint':'impressao_digital','unlock_password':'senha',
               'unlock_temporary':'senha_temporaria','unlock_card':'cartao','unlock_app':'aplicativo'}
SENSORS = [
 ('battery','Bateria',{'device_class':'battery','unit_of_measurement':'%','state_class':'measurement'}),
 ('last_user','Último usuário',{'icon':'mdi:account-key'}),
 ('last_method','Método do último acesso',{'icon':'mdi:key'}),
 ('last_credential','ID da credencial',{'icon':'mdi:identifier'}),
 ('last_unlock_time','Último acesso',{'device_class':'timestamp'}),
 ('access_count','Acessos no histórico',{'icon':'mdi:counter'}),
 ('unknown_credentials','Credenciais não associadas',{'icon':'mdi:account-question'}),
 ('access_history','Histórico de acessos',{'icon':'mdi:history'}),
 ('last_alarm','Último alarme',{'icon':'mdi:alarm-light'}),
 ('last_doorbell','Última campainha',{'device_class':'timestamp'}),
 ('cloud_status','Status da API',{'entity_category':'diagnostic','icon':'mdi:cloud-check'}),
 ('last_cloud_update','Última atualização da nuvem',{'entity_category':'diagnostic','device_class':'timestamp'}),
 ('last_event','Último evento recebido',{'icon':'mdi:history'}),
]

def timestamp(item):
    dt=event_datetime(item)
    return dt.isoformat() if dt else None

def state_payloads(data):
    latest=data['latest_by_code']
    entry=SimpleNamespace(options={'people':data['people']})
    last=data['last_unlock']
    user=unlock_data(entry,last)
    battery=latest.get('residual_electricity')
    try:
        battery_value=int(battery['value']) if battery else None
        if battery_value is not None and not 0<=battery_value<=100:battery_value=None
    except (ValueError,TypeError):battery_value=None
    bolt=latest.get('reverse_lock')
    bolt_value={'true':'ON','false':'OFF','1':'ON','0':'OFF'}.get(str(bolt.get('value')).lower()) if bolt else None
    alarm=latest.get('alarm_lock')
    unknown=[{'tipo':x['tipo'],'id':x['id'],'quantidade':x['quantidade']} for x in data['credentials'].values() if not x.get('pessoa')]
    rows=[unlock_data(entry,item) for item in data['logs']]
    def item(value,attributes=None):return {'value':value,'attributes':attributes or {}}
    return {
        'battery':item(battery_value,{'ultimo_relato':timestamp(battery)}),
        'reverse_lock':item(bolt_value,{'ultimo_relato':timestamp(bolt)}),
        'last_user':item(user.get('usuario'),user),
        'last_method':item(data['method_name']),
        'last_credential':item(str(last['value']) if last else None),
        'last_unlock_time':item(timestamp(last)),
        'access_count':item(data['access_count']),
        'unknown_credentials':item(len(unknown),{'credenciais':unknown[:25]}),
        'access_history':item(data['access_count'],{'acessos':rows}),
        'last_alarm':item(ALARM_NAMES.get(str(alarm['value']),str(alarm['value'])) if alarm else None,{'codigo':alarm.get('value') if alarm else None,'horario':timestamp(alarm)}),
        'last_doorbell':item(timestamp(latest.get('doorbell'))),
        'cloud_status':item('Online' if data['cloud_success'] else 'Erro' if data['poll_attempted'] else 'Conectando',{'ultimo_erro':data['cloud_error']}),
        'last_cloud_update':item(data['last_successful_update']),
        'last_event':item(data['last_event'].get('code') if data['last_event'] else None,{'valor':data['last_event'].get('value') if data['last_event'] else None,'horario':timestamp(data['last_event'])}),
    }

class MQTTPublisher:
    def __init__(self,rt,opts,session):
        self.rt,self.opts,self.session=rt,opts,session
        self.node='kt1000_'+hashlib.sha256(rt.api.device_id.encode()).hexdigest()[:20]
        self.base='kt1000/'+self.node
        self.seen=None
        self.publish_lock=asyncio.Lock()
        self.published={}

    def configs(self):
        device={'identifiers':[self.node],'name':self.rt.title,'manufacturer':'KELTECH / Tuya','model':'KT-1000','sw_version':'App 0.12.0'}
        result=[]
        def add(component,key,name,extra):
            config={'name':name,'unique_id':self.node+'_'+key,'device':device,
                    'state_topic':self.base+'/'+key+'/state','availability':[{'topic':self.base+'/availability'}],
                    'qos':1,**extra}
            if key not in ('cloud_status','last_cloud_update'):
                config['availability'].append({'topic':self.base+'/cloud_availability'})
                config['availability_mode']='all'
            if component!='event':
                config['value_template']='{{ value_json.value }}'
                config['json_attributes_topic']=config['state_topic']
                config['json_attributes_template']='{{ value_json.attributes | tojson }}'
            result.append(('homeassistant/'+component+'/'+self.node+'/'+key+'/config',config))
        for key,name,extra in SENSORS:add('sensor',key,name,extra)
        add('binary_sensor','reverse_lock','Tranca de segurança interna',{'payload_on':'ON','payload_off':'OFF','icon':'mdi:lock'})
        add('event','unlock_event','Desbloqueio',{'event_types':list(EVENT_TYPES.values()),'qos':0})
        add('event','doorbell_event','Campainha',{'event_types':['campainha'],'device_class':'doorbell','qos':0})
        add('event','alarm_event','Alarme',{'event_types':['alarme'],'qos':0})
        return result

    async def discover(self,client):
        for topic,config in self.configs():
            await client.publish(topic,json.dumps(config,ensure_ascii=False),qos=1,retain=True)

    async def publish_state(self,client,force=False):
        async with self.publish_lock:
            await self._publish_state(client,force)

    async def _publish_state(self,client,force):
        data=snapshot(self.rt)
        cloud='online' if data['cloud_success'] else 'offline'
        if force or self.published.get('cloud')!=cloud:
            await client.publish(self.base+'/cloud_availability',cloud,qos=1,retain=True)
            self.published['cloud']=cloud
        for key,payload in state_payloads(data).items():
            encoded=json.dumps(payload,ensure_ascii=False)
            if force or self.published.get(key)!=encoded:
                await client.publish(self.base+'/'+key+'/state',encoded,qos=1,retain=True)
                self.published[key]=encoded
        await client.publish(self.base+'/availability','online',qos=1,retain=True)
        await self.publish_events(client,data)

    async def publish_events(self,client,data):
        if not data['cloud_success']:return
        current={'unlock_event':data['last_unlock'],'doorbell_event':data['latest_by_code'].get('doorbell'),'alarm_event':data['latest_by_code'].get('alarm_lock')}
        if self.seen is None:
            self.seen={key:event_timestamp(item) for key,item in current.items()}
            return
        entry=SimpleNamespace(options={'people':data['people']})
        for key,item in current.items():
            ts=event_timestamp(item)
            if ts<=self.seen[key]:continue
            if key=='unlock_event':payload={'event_type':EVENT_TYPES[item['code']],**unlock_data(entry,item)}
            elif key=='doorbell_event':payload={'event_type':'campainha','valor':item.get('value'),'event_time':ts,'horario':timestamp(item)}
            else:payload={'event_type':'alarme','alarme':ALARM_NAMES.get(str(item.get('value')),str(item.get('value'))),'codigo':item.get('value'),'event_time':ts,'horario':timestamp(item)}
            payload['device_id']=self.rt.api.device_id
            # Events are transient; never retain/replay them on HA startup.
            await client.publish(self.base+'/'+key+'/state',json.dumps(payload,ensure_ascii=False),qos=0,retain=False)
            self.seen[key]=ts

    async def broker_options(self):
        host=str(self.opts.get('mqtt_host','')).strip()
        if host:
            return {'hostname':host,'port':int(self.opts.get('mqtt_port',1883)),
                    'username':self.opts.get('mqtt_username') or None,'password':self.opts.get('mqtt_password') or None,
                    'tls_context':ssl.create_default_context() if self.opts.get('mqtt_tls') else None}
        token=os.environ.get('SUPERVISOR_TOKEN')
        if not token:raise ValueError('Serviço MQTT automático indisponível.')
        async with self.session.get('http://supervisor/services/mqtt',headers={'Authorization':'Bearer '+token},timeout=ClientTimeout(total=10),allow_redirects=False) as response:
            if response.status!=200:raise ValueError('Serviço MQTT automático indisponível.')
            result=await response.json()
        data=result.get('data',result)
        if result.get('result','ok')!='ok' or not data.get('host'):raise ValueError('Serviço MQTT automático indisponível.')
        return {'hostname':data['host'],'port':int(data['port']),'username':data.get('username') or None,'password':data.get('password') or None,
                'tls_context':ssl.create_default_context() if data.get('ssl') else None}

    async def connected(self,client):
        await client.subscribe('homeassistant/status',qos=1)
        await self.discover(client)
        await self.publish_state(client,force=True)
        self.rt.mqtt_connected=True;self.rt.mqtt_error=None
        async def births():
            async for message in client.messages:
                if str(message.topic)=='homeassistant/status' and message.payload==b'online':
                    await self.discover(client)
                    await self.publish_state(client,force=True)
        async def updates():
            while True:
                await asyncio.sleep(5)
                await self.publish_state(client)
        workers=[asyncio.create_task(births()),asyncio.create_task(updates())]
        try:
            done,_=await asyncio.wait(workers,return_when=asyncio.FIRST_COMPLETED)
            for task in done:task.result()
        finally:
            for task in workers:task.cancel()
            await asyncio.gather(*workers,return_exceptions=True)
            self.rt.mqtt_connected=False

    async def run(self):
        import aiomqtt
        while True:
            try:
                options=await self.broker_options()
                async with aiomqtt.Client(**options,identifier=self.node,keepalive=30,timeout=10,
                    will=aiomqtt.Will(self.base+'/availability','offline',qos=1,retain=True)) as client:
                    try:
                        await self.connected(client)
                    finally:
                        self.rt.mqtt_connected=False
                        # Also covers failure during initial discovery/state.
                        with suppress(Exception):
                            await client.publish(self.base+'/availability','offline',qos=1,retain=True,timeout=3)
            except asyncio.CancelledError:raise
            except Exception as exc:
                self.rt.mqtt_connected=False
                self.rt.mqtt_error='Falha no MQTT. Confira o serviço do Supervisor ou configure host, porta e credenciais nas opções do App.'
                _LOGGER.warning('KT-1000: conexão/publicação MQTT falhou (%s); nova tentativa em 15s.',type(exc).__name__)
                await asyncio.sleep(15)
