"""Standalone Ingress application. No Home Assistant Core runtime dependency."""
import asyncio
import inspect
import json
import os
import uuid
from cryptography.fernet import Fernet
from .offline import normalize, creation_defaults, seconds
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
from aiohttp import web, ClientSession, ClientTimeout
from .api import KT1000Api, KT1000ApiError
from .const import DOMAIN, ALL_CODES, UNLOCK_CODES
from . import commands

INGRESS_IP = '172.30.32.2'
ENTRY_ID = 'app'

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {'history': {}, 'people': {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
        self.lock = asyncio.Lock()

    def history_for(self, entry_id):
        return self.data.setdefault('history', {}).setdefault(entry_id, [])

    def people_for(self, entry_id):
        return self.data.setdefault('people', {}).setdefault(entry_id, [])

    def offline_for(self, entry_id):
        return self.data.setdefault('offline_passwords', {}).setdefault(entry_id, [])

    def _vault(self, create=False):
        key_path=self.path.with_name('passwords.key')
        if not key_path.exists():
            if not create or any(x.get('encrypted_code') for rows in self.data.get('offline_passwords',{}).values() for x in rows):
                raise ValueError('Chave local ausente. Restaure passwords.key junto com access.json do backup do App.')
            fd=os.open(key_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(Fernet.generate_key());stream.flush();os.fsync(stream.fileno())
        return Fernet(key_path.read_bytes())

    def upsert_offline(self, entry_id, item, source='tuya'):
        rows=self.offline_for(entry_id)
        existing=next((x for x in rows if x['id']==item['id']),None)
        if existing is None:
            existing={'id':item['id']};rows.append(existing)
        existing.update({k:v for k,v in item.items() if v is not None})
        existing['source']=source if source=='tuya' else existing.get('source',source)
        return existing

    async def record_offline(self, entry_id, result, name, kind, start=None, end=None):
        if not isinstance(result,dict):raise ValueError('Resposta de geração inválida.')
        fallback=creation_defaults(name,kind,start,end)
        fallback['id']='local-'+uuid.uuid4().hex
        item=normalize(result,fallback)
        code=result.get('offline_temp_password') or result.get('password') or result.get('pwd')
        encrypted=None
        if code:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            encrypted=self._vault(create=True).encrypt(str(code).encode()).decode()
        row=self.upsert_offline(entry_id,item,source='local')
        if encrypted:row['encrypted_code']=encrypted
        await self.async_save()

    def offline_metadata(self, entry_id):
        return sorted([{**{k:v for k,v in x.items() if k!='encrypted_code'},'has_code':bool(x.get('encrypted_code'))} for x in self.offline_for(entry_id)],key=lambda x:x.get('create_time') or x.get('effective_time') or 0,reverse=True)

    def reveal_offline(self, entry_id, password_id):
        row=next((x for x in self.offline_for(entry_id) if x['id']==password_id),None)
        if not row or not row.get('encrypted_code'):raise ValueError('O código não foi salvo por este App; a Tuya devolve somente os metadados desta senha.')
        return self._vault().decrypt(row['encrypted_code'].encode()).decode()

    async def async_save(self):
        async with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            with tmp.open('w') as stream:
                os.chmod(tmp, 0o600)
                json.dump(self.data, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)

class Connection:
    def __init__(self):
        # Ingress authenticates HA users. Treat all allowed Ingress users as app operators.
        self.user = SimpleNamespace(is_admin=True)
        self.result = None
        self.error = None
    def send_result(self, _id, result):
        self.result = result
    def send_error(self, _id, code, message):
        self.error = message

class Runtime:
    def __init__(self, api, store, title):
        self.api, self.store = api, store
        self.title = title
        self.data = {'latest_by_code': store.data.get('latest_by_code', {})}
        self.last_update_success = False
        self.poll_attempted = False
        self.last_error = None
        self.offline_sync_warning = None
        self.offline_sync_done = False
        self.offline_last_sync = None
        self.last_successful_update = None
        entry = SimpleNamespace(entry_id=ENTRY_ID, title=title)
        self.hass = SimpleNamespace(data={DOMAIN: {ENTRY_ID: self, 'store': store}},
            config_entries=SimpleNamespace(async_entries=lambda domain: [entry],
                async_get_entry=lambda eid: entry if eid == ENTRY_ID else None))
        self.mutation_lock = asyncio.Lock()

    async def poll(self):
        try:
            result = await self.api.get_report_logs(ALL_CODES, hours=168, size=100)
            logs = result.get('logs', []) if isinstance(result, dict) else result or []
            logs = sorted(logs, key=lambda x:int(x.get('eventTime', x.get('event_time',0))), reverse=True)
            latest = dict(self.data.get("latest_by_code", {}))
            for item in logs:
                old = latest.get(item.get('code'))
                if not old or int(item.get('eventTime', item.get('event_time', 0)) or 0) >= int(old.get('eventTime', old.get('event_time', 0)) or 0):
                    latest[item.get('code')] = item
            async with self.mutation_lock:
                history = self.store.history_for(ENTRY_ID)
                known = {(x['event_time'], x['code'], str(x['value'])) for x in history}
                for item in logs:
                    ts = int(item.get('eventTime',item.get('event_time',0)))
                    key = (ts,item.get('code'),str(item.get('value','')))
                    if ts and key[1] in UNLOCK_CODES and key not in known:
                        history.append(dict(event_time=ts, code=key[1], value=key[2]))
                        known.add(key)
                history.sort(key=lambda x:x['event_time'], reverse=True)
                self.store.data['latest_by_code'] = latest
                await self.store.async_save()
            self.data = {'latest_by_code':latest}
            self.last_update_success = True
            self.last_error = None
            self.last_successful_update = datetime.now(timezone.utc)
        except Exception as exc:
            self.last_update_success = False
            self.last_error = str(exc) if isinstance(exc, KT1000ApiError) else f"Falha de rede/comunicação ({type(exc).__name__}). Confira internet, DNS e data/hora do host do HA."
            # Redact any accidental credential echoes from cloud errors.
            for value in (self.api.client_id, self.api.client_secret, self.api.device_id):
                if len(value) >= 8:self.last_error=self.last_error.replace(value, "[oculto]")
        finally:
            self.poll_attempted = True

    async def sync_offline(self):
        try:
            normalized=[normalize(x) for x in await self.api.get_offline_temporary_passwords()]
            async with self.mutation_lock:
                cloud_ids={x['id'] for x in normalized}
                for row in self.store.offline_for(ENTRY_ID):row['cloud_present']=row['id'] in cloud_ids
                for item in normalized:self.store.upsert_offline(ENTRY_ID,{**item,'cloud_present':True})
                await self.store.async_save()
            self.offline_sync_warning=None
            self.offline_last_sync=datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            self.offline_sync_warning='Falha ao sincronizar a lista offline; histórico local preservado: '+str(exc)
            for value in (self.api.client_id,self.api.client_secret,self.api.device_id):
                if len(value)>=8:self.offline_sync_warning=self.offline_sync_warning.replace(value,'[oculto]')
        self.offline_sync_done=True

    async def dispatch(self, payload):
        kind = payload.get('type')
        if kind == 'kt1000/delete_temp_password_record':
            if set(payload)!={'type','entry_id','password_id'} or payload['entry_id']!=ENTRY_ID or type(payload['password_id']) not in (str,int) or not str(payload['password_id']).isdigit():
                raise ValueError('Solicitação inválida.')
            async with self.mutation_lock:
                # Verify fresh cloud metadata rather than trust browser labels or timestamps.
                try:
                    items=await self.api.get_temporary_passwords()
                except KT1000ApiError as exc:
                    return {'ok':False,'error':'Não foi possível verificar o estado atual da senha: '+str(exc)}
                item=next((commands._safe_temp_password(x) for x in items or [] if str(x.get('id') if x.get('id') is not None else x.get('password_id',''))==str(payload['password_id'])),None)
                if not item:raise ValueError('Registro não encontrado. Atualize a lista.')
                end=seconds(item.get('invalid_time'))
                deleted=str(item.get('phase')) in ('0','4')
                if not deleted and (not end or end>int(datetime.now(timezone.utc).timestamp())):
                    raise ValueError('Excluir registro é permitido somente para senhas vencidas ou excluídas; use Excluir para uma senha ativa.')
                try:
                    await self.api.delete_temporary_password_record(payload['password_id'])
                except KT1000ApiError as exc:
                    return {'ok':False,'error':'A Tuya recusou a exclusão do registro histórico: '+str(exc)}
            return {'ok':True,'record_deleted':True}
        if kind == 'kt1000/offline_password_code':
            if set(payload)!={'type','entry_id','password_id'} or payload['entry_id']!=ENTRY_ID or not isinstance(payload['password_id'],str):raise ValueError('Solicitação inválida.')
            return {'ok':True,'code':self.store.reveal_offline(ENTRY_ID,payload['password_id'])}
        if kind == 'kt1000/refresh':
            if set(payload) != {'type'}:raise ValueError('Parâmetros desconhecidos.')
            await self.poll() # read-only history request; never an unlock command
            await self.sync_offline()
            return await self.dispatch({'type':'kt1000/overview'})
        if kind not in commands.COMMANDS:
            raise ValueError('Comando desconhecido.')
        name, fields = commands.COMMANDS[kind]
        if set(payload) - {'type'} - set(fields):
            raise ValueError('Parâmetros desconhecidos.')
        msg = {'type':kind, 'id':1}
        for key, field in fields.items():
            if key not in payload:
                if 'default' in field:msg[key] = field['default']
                elif field['required']:raise ValueError(f'Informe {key}.')
                continue
            value = payload[key]
            validator = field['validator']
            if validator == 'str' and not isinstance(value,str):raise ValueError(f'{key} deve ser texto.')
            if validator == 'bool' and type(value) is not bool:raise ValueError(f'{key} deve ser booleano.')
            if validator == 'vol.Coerce(int)':
                if isinstance(value,bool):raise ValueError(f'{key} inválido.')
                value = int(value)
            if validator == 'vol.Any(str, int)' and (type(value) not in (str,int)):raise ValueError(f'{key} inválido.')
            if validator.startswith('vol.In('):
                import ast
                if value not in ast.literal_eval(validator[7:-1]):raise ValueError(f'{key} inválido.')
            msg[key] = value
        if msg.get('entry_id', ENTRY_ID) != ENTRY_ID:raise ValueError('App não configurado para esta entrada.')
        connection = Connection()
        # Serialize mutations and disallow automatic retries of physical actions.
        async with self.mutation_lock:
            value = getattr(commands,name)(self.hass,connection,msg)
            if inspect.isawaitable(value):await value
        if connection.error:raise ValueError(connection.error)
        if kind == 'kt1000/overview':
            connection.result['remote_unlock_enabled'] = self.api.remote_unlock_enabled
            connection.result['communication_error'] = self.last_error
            connection.result['communication_pending'] = not self.poll_attempted
            connection.result['offline_items']=self.store.offline_metadata(ENTRY_ID)
            connection.result['offline_sync_done']=self.offline_sync_done
            connection.result['offline_sync_warning']=self.offline_sync_warning
            connection.result['offline_last_sync']=self.offline_last_sync
        return connection.result

@web.middleware
async def ingress_only(request, handler):
    # No host port is published. Supervisor is the only accepted caller.
    if request.remote != INGRESS_IP:
        raise web.HTTPForbidden(text='Acesso somente pelo Ingress do Home Assistant.')
    if request.method == 'POST' and request.headers.get('X-KT1000-Request') != '1':
        raise web.HTTPForbidden()
    response = await handler(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

async def command(request):
    try:
        payload = await request.json()
        if not isinstance(payload,dict):raise ValueError('Solicitação inválida.')
        return web.json_response(await request.app['runtime'].dispatch(payload))
    except (ValueError,TypeError) as exc:
        return web.json_response({'ok':False,'error':str(exc)},status=400)
    except Exception:
        return web.json_response({'ok':False,'error':'Falha interna na solicitação.'},status=500)

async def import_data(request):
    try:
        payload = await request.json()
        data = payload['data']
        entry_id = str(payload['entry_id'])
        if 'data' in data:data=data['data'] # HA .storage envelope
        history = data['history'][entry_id]
        people = data['people'][entry_id]
        if not isinstance(history,list) or not isinstance(people,list):raise ValueError()
        clean_history = []
        for x in history:
            if x['code'] not in UNLOCK_CODES:continue
            clean_history.append({'event_time':int(x['event_time']),'code':x['code'],'value':str(x['value'])})
        clean_people = [{'name':str(x['name']), 'credentials':[str(c) for c in x.get('credentials',[])]} for x in people]
        rt=request.app['runtime']
        async with rt.mutation_lock:
            current=rt.store.history_for(ENTRY_ID)
            known={(x['event_time'],x['code'],x['value']) for x in current}
            for x in clean_history:
                key=(x['event_time'],x['code'],x['value'])
                if key not in known:current.append(x);known.add(key)
            current.sort(key=lambda x:x['event_time'],reverse=True)
            target=rt.store.people_for(ENTRY_ID)
            for p in clean_people:
                existing=next((x for x in target if x['name']==p['name']),None)
                if existing:existing['credentials']=sorted(set(existing['credentials']+p['credentials']))
                else:target.append(p)
            await rt.store.async_save()
        return web.json_response({'ok':True})
    except (KeyError,TypeError,ValueError):
        return web.json_response({'ok':False,'error':'Arquivo ou entry_id inválido. Nenhum segredo Tuya é importado.'},status=400)

async def lifecycle(app):
    opts=json.loads(Path(os.environ.get('KT_OPTIONS','/data/options.json')).read_text())
    async with ClientSession(timeout=ClientTimeout(total=30)) as session:
        api=KT1000Api(session,opts['client_id'],opts['client_secret'],opts['device_id'])
        urls={'us':'https://openapi.tuyaus.com','eu':'https://openapi.tuyaeu.com','cn':'https://openapi.tuyacn.com','in':'https://openapi.tuyain.com'}
        api.base_url=urls[opts.get('region','us')]
        api.remote_unlock_enabled=opts.get('remote_unlock_enabled',False) is True
        api.remote_unlock_mode=opts.get('remote_unlock_mode','open_door')
        rt=Runtime(api,Store(os.environ.get('KT_STATE','/data/access.json')),opts.get('title','KT-1000'))
        app['runtime']=rt
        async def polling():
            while True:
                await rt.poll()
                await rt.sync_offline()
                await asyncio.sleep(max(30,int(opts.get('scan_interval',30))))
        from .bridge import create_bridge_app
        bridge_runner = None
        token = str(opts.get('bridge_token', '')).strip()
        if len(token) >= 32:
            bridge_runner = web.AppRunner(create_bridge_app(rt, token))
            await bridge_runner.setup()
            await web.TCPSite(bridge_runner, '0.0.0.0', 8100).start()
        task=asyncio.create_task(polling())
        try:
            yield
        finally:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
            if bridge_runner is not None:await bridge_runner.cleanup()

async def index(request):
    return web.FileResponse(Path(__file__).parent/'frontend'/'index.html')

def create_app():
    app=web.Application(middlewares=[ingress_only],client_max_size=16*1024*1024)
    app.cleanup_ctx.append(lifecycle)
    app.router.add_post('/api/command',command)
    app.router.add_post('/api/import',import_data)
    frontend=Path(__file__).parent/'frontend'
    app.router.add_get('/',index)
    app.router.add_static('/',frontend,show_index=False)
    return app

if __name__=='__main__':
    web.run_app(create_app(),host='0.0.0.0',port=8099,access_log=None)
