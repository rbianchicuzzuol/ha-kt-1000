from datetime import datetime, timezone
from .const import DOMAIN, METHOD_NAMES, CREDENTIAL_LABELS, UNLOCK_CODES
from .helpers import credential_key
from .offline import normalize
def _entry(hass, entry_id):
    return hass.config_entries.async_get_entry(entry_id)

def _resolve(people, code, value):
    key = credential_key(code, str(value))
    for p in people:
        if key in p.get('credentials', []):
            return p.get('name')
    return None

def _remember_credential(store, entry_id, cred):
    catalog=store.data.setdefault('credential_catalog', {}).setdefault(entry_id, [])
    if cred not in catalog:catalog.append(cred)

def _valid_credential(cred):
    code, sep, value=cred.partition(':')
    return bool(sep and code in UNLOCK_CODES and value.strip())

def _history_row(people, item):
    code = item.get('code')
    value = str(item.get('value', ''))
    ts = int(item.get('event_time', 0))
    dt = datetime.fromtimestamp(ts / 1000, timezone.utc).astimezone() if ts else None
    person = _resolve(people, code, value)
    return {'event_time': ts, 'datetime': dt.isoformat() if dt else None, 'person': person, 'identified': bool(person), 'method': METHOD_NAMES.get(code, code), 'code': code, 'credential_id': value}

async def ws_overview(hass, connection, msg):
    entries = hass.config_entries.async_entries(DOMAIN)
    entry = _entry(hass, msg.get('entry_id')) if msg.get('entry_id') else entries[0] if entries else None
    if not entry:
        connection.send_error(msg['id'], 'not_found', 'KT-1000 não configurada')
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]
    store = hass.data[DOMAIN]['store']
    people = store.people_for(entry.entry_id)
    history = store.history_for(entry.entry_id)
    rows = [_history_row(people, x) for x in history]
    discovered = {}
    for x in history:
        code, value = (x.get('code'), str(x.get('value', '')))
        key = credential_key(code, value)
        if key not in discovered:
            discovered[key] = {'key': key, 'code': code, 'id': value, 'type': CREDENTIAL_LABELS.get(code, code), 'last_used': int(x.get('event_time', 0)), 'count': 0}
        discovered[key]['count'] += 1
        discovered[key]['last_used'] = max(discovered[key]['last_used'], int(x.get('event_time', 0)))
    keys=list(store.data.get('credential_catalog',{}).get(entry.entry_id,[]))
    keys.extend(c for p in people for c in p.get('credentials',[]))
    for key in keys:
        if key not in discovered and _valid_credential(key):
            code, value=key.split(':',1)
            discovered[key]={'key':key,'code':code,'id':value,'type':CREDENTIAL_LABELS.get(code,code),'last_used':0,'count':0}
    for x in discovered.values():
        x['person'] = _resolve(people, x['code'], x['id'])
    connection.send_result(msg['id'], {'entry_id': entry.entry_id, 'title': entry.title, 'battery': (coordinator.data.get('latest_by_code', {}).get('residual_electricity') or {}).get('value'), 'online': coordinator.last_update_success, 'last_update': coordinator.last_successful_update.isoformat() if coordinator.last_successful_update else None, 'history': rows, 'people': people, 'credentials': list(discovered.values())})

def ws_people(hass, connection, msg):
    store = hass.data[DOMAIN]['store']
    connection.send_result(msg['id'], store.people_for(msg['entry_id']))

async def ws_save_person(hass, connection, msg):
    store=hass.data[DOMAIN]['store'];people=store.people_for(msg['entry_id'])
    name=msg['name'].strip();old=msg.get('old_name')
    if not name:
        connection.send_error(msg['id'],'invalid_name','Informe o nome.');return
    if any(p.get('name','').casefold()==name.casefold() and p.get('name')!=old for p in people):
        connection.send_error(msg['id'],'duplicate_name','Já existe uma pessoa com esse nome.');return
    if old is not None:
        person=next((p for p in people if p.get('name')==old),None)
        if not person:
            connection.send_error(msg['id'],'not_found','Pessoa não encontrada. Atualize a lista.');return
        person['name']=name
    else:people.append({'name':name,'credentials':[]})
    await store.async_save();connection.send_result(msg['id'],{'ok':True})

async def ws_delete_person(hass, connection, msg):
    store=hass.data[DOMAIN]['store'];people=store.people_for(msg['entry_id'])
    target=next((p for p in people if p.get('name')==msg['name']),None)
    if target:
        for cred in target.get('credentials',[]):_remember_credential(store,msg['entry_id'],cred)
    people[:]=[p for p in people if p.get('name')!=msg['name']]
    await store.async_save();connection.send_result(msg['id'],{'ok':True})

async def ws_assign(hass, connection, msg):
    store=hass.data[DOMAIN]['store'];people=store.people_for(msg['entry_id']);cred=msg['credential']
    target=next((p for p in people if p.get('name')==msg['person']),None)
    if not target:
        connection.send_error(msg['id'],'not_found','Pessoa não encontrada.');return
    if not _valid_credential(cred):
        connection.send_error(msg['id'],'invalid_credential','Credencial inválida.');return
    owner=next((p for p in people if cred in p.get('credentials',[])),None)
    expected=msg.get('expected_owner')
    if expected is not None and (not owner or owner['name']!=expected):
        connection.send_error(msg['id'],'ownership_changed','A associação mudou. Atualize antes de transferir.');return
    if owner and owner is not target and expected!=owner['name']:
        connection.send_error(msg['id'],'already_assigned','Credencial já associada. Use Transferir na pessoa atual.');return
    # Validate all conditions before modifying the previous association.
    for p in people:p['credentials']=[x for x in p.get('credentials',[]) if x!=cred]
    target.setdefault('credentials',[]).append(cred)
    target['credentials']=sorted(set(target['credentials']))
    _remember_credential(store,msg['entry_id'],cred)
    await store.async_save();connection.send_result(msg['id'],{'ok':True})

async def ws_unassign(hass, connection, msg):
    store=hass.data[DOMAIN]['store'];people=store.people_for(msg['entry_id']);cred=msg['credential']
    expected=msg.get('expected_person')
    owner=next((p for p in people if cred in p.get('credentials',[])),None)
    if expected is not None and (not owner or owner['name']!=expected):
        connection.send_error(msg['id'],'ownership_changed','A associação mudou. Atualize a pessoa antes de desassociar.');return
    _remember_credential(store,msg['entry_id'],cred)
    for p in people:p['credentials']=[x for x in p.get('credentials',[]) if x!=cred]
    await store.async_save();connection.send_result(msg['id'],{'ok':True})

def _safe_temp_password(item):
    """Mantém apenas metadados administrativos; nunca expõe segredo/chave."""
    if not isinstance(item, dict):
        return {'raw_type': type(item).__name__}
    allowed = ('id', 'password_id', 'name', 'phase', 'effective_time', 'invalid_time', 'create_time', 'delivery_status', 'schedule_list', 'time_zone', 'phone', 'type', 'password_type', 'sequence_number', 'status')
    result = {k: item.get(k) for k in allowed if k in item}
    if result.get('id') is None and result.get('password_id') is not None:
        result['id'] = result['password_id']
    return result

async def ws_temp_passwords(hass, connection, msg):
    entry = _entry(hass, msg['entry_id'])
    if not entry or entry.entry_id not in hass.data.get(DOMAIN, {}):
        connection.send_error(msg['id'], 'not_found', 'KT-1000 não configurada')
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]
    try:
        items = await coordinator.api.get_temporary_passwords(msg.get('valid'))
        connection.send_result(msg['id'], {'ok': True, 'items': [_safe_temp_password(x) for x in items or []]})
    except Exception as err:
        connection.send_result(msg['id'], {'ok': False, 'items': [], 'error': str(err)})

async def ws_temp_password_detail(hass, connection, msg):
    entry = _entry(hass, msg['entry_id'])
    if not entry or entry.entry_id not in hass.data.get(DOMAIN, {}):
        connection.send_error(msg['id'], 'not_found', 'KT-1000 não configurada')
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]
    try:
        item = await coordinator.api.get_temporary_password(msg['password_id'])
        connection.send_result(msg['id'], {'ok': True, 'item': _safe_temp_password(item or {})})
    except Exception as err:
        connection.send_result(msg['id'], {'ok': False, 'error': str(err)})

async def ws_create_temp_password(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Somente administradores podem criar senhas.')
        return
    entry = _entry(hass, msg['entry_id'])
    if not entry or entry.entry_id not in hass.data.get(DOMAIN, {}):
        connection.send_error(msg['id'], 'not_found', 'KT-1000 não configurada')
        return
    name = msg['name'].strip()
    password = msg['password'].strip()
    start = int(msg['effective_time'])
    end = int(msg['invalid_time'])
    if not name:
        connection.send_error(msg['id'], 'invalid_name', 'Informe um nome.')
        return
    if not (password.isdigit() and len(password) == 7):
        connection.send_error(msg['id'], 'invalid_password', 'A senha deve ter exatamente 7 dígitos.')
        return
    if end <= start:
        connection.send_error(msg['id'], 'invalid_period', 'O fim deve ser posterior ao início.')
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]
    try:
        result = await coordinator.api.create_temporary_password(name, password, start, end, bool(msg.get('use_once')))
        connection.send_result(msg['id'], {'ok': True, 'result': result})
    except Exception as err:
        connection.send_result(msg['id'], {'ok': False, 'error': str(err)})

async def ws_delete_temp_password(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Somente administradores podem excluir senhas.')
        return
    entry = _entry(hass, msg['entry_id'])
    if not entry or entry.entry_id not in hass.data.get(DOMAIN, {}):
        connection.send_error(msg['id'], 'not_found', 'KT-1000 não configurada')
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]
    try:
        result = await coordinator.api.delete_temporary_password(msg['password_id'])
        connection.send_result(msg['id'], {'ok': True, 'result': result})
    except Exception as err:
        if getattr(err,'code',None)=='2304':
            connection.send_result(msg['id'], {'ok':False,'error':'A senha venceu. A Tuya não aceita excluí-la por este endpoint (2304). Atualize a lista e use Excluir registro para remover seu histórico na Tuya.','expired':True})
        else:
            connection.send_result(msg['id'], {'ok': False, 'error': str(err)})

async def ws_set_temp_password_frozen(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Somente administradores podem alterar o estado da senha.')
        return
    entry = _entry(hass, msg['entry_id'])
    if not entry or entry.entry_id not in hass.data.get(DOMAIN, {}):
        connection.send_error(msg['id'], 'not_found', 'KT-1000 não configurada')
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]
    try:
        if msg['frozen']:
            result = await coordinator.api.freeze_temporary_password(msg['password_id'])
        else:
            result = await coordinator.api.unfreeze_temporary_password(msg['password_id'])
        connection.send_result(msg['id'], {'ok': True, 'result': result})
    except Exception as err:
        connection.send_result(msg['id'], {'ok': False, 'error': str(err)})

def _safe_offline_password(item):
    if not isinstance(item, dict):
        return {'raw_type': type(item).__name__}
    allowed = ('id', 'password_id', 'offline_temp_password_id', 'name', 'offline_temp_password_name', 'effective_time', 'invalid_time', 'type', 'status', 'phase', 'create_time')
    return {k: item.get(k) for k in allowed if k in item}

async def ws_offline_temp_passwords(hass, connection, msg):
    entry = _entry(hass, msg['entry_id'])
    if not entry or entry.entry_id not in hass.data.get(DOMAIN, {}):
        connection.send_error(msg['id'], 'not_found', 'KT-1000 não configurada')
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]
    warning=None
    try:
        items = await coordinator.api.get_offline_temporary_passwords()
        normalized=[normalize(x) for x in items]
        cloud_ids={x['id'] for x in normalized}
        for row in coordinator.store.offline_for(entry.entry_id):row['cloud_present']=row['id'] in cloud_ids
        for item in normalized:coordinator.store.upsert_offline(entry.entry_id,{**item,'cloud_present':True})
        await coordinator.store.async_save()
    except Exception as err:
        warning="Não foi possível sincronizar a lista Tuya. Exibindo histórico local: " + str(err)
    coordinator.offline_sync_done=True
    coordinator.offline_sync_warning=warning
    if not warning:coordinator.offline_last_sync=datetime.now(timezone.utc).isoformat()
    items=coordinator.store.offline_metadata(entry.entry_id)
    connection.send_result(msg['id'], {'ok':True,'items':items,'warning':warning})

async def ws_create_offline_temp_password(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Somente administradores podem gerar senhas offline.')
        return
    entry = _entry(hass, msg['entry_id'])
    if not entry or entry.entry_id not in hass.data.get(DOMAIN, {}):
        connection.send_error(msg['id'], 'not_found', 'KT-1000 não configurada')
        return
    pwd_type = int(msg['pwd_type'])
    if pwd_type not in (0, 1, 8, 9):
        connection.send_error(msg['id'], 'invalid_type', 'Tipo de senha offline inválido.')
        return
    if pwd_type == 8 and (not msg.get('password_id')):
        connection.send_error(msg['id'], 'missing_password_id', 'Informe a senha offline que será apagada.')
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]
    try:
        result = await coordinator.api.create_offline_temporary_password(msg.get('name', '').strip(), pwd_type, msg.get('effective_time'), msg.get('invalid_time'), msg.get('password_id'))
        warning=None
        try:
            await coordinator.store.record_offline(entry.entry_id,result,msg.get('name','').strip(),pwd_type,msg.get('effective_time'),msg.get('invalid_time'))
        except Exception:
            warning="Senha gerada pela Tuya, mas não foi possível salvar o histórico local. Anote o código agora; não repita a criação para tentar salvar."
        connection.send_result(msg['id'], {'ok': True, 'result': result, 'warning':warning})
    except Exception as err:
        connection.send_result(msg['id'], {'ok': False, 'error': str(err)})

async def ws_lock_users(hass, connection, msg):
    coordinator = hass.data[DOMAIN].get(msg['entry_id'])
    if not coordinator:
        connection.send_error(msg['id'], 'not_found', 'Integração não encontrada')
        return
    try:
        result = await coordinator.api.get_lock_users()
        connection.send_result(msg['id'], {'ok': True, 'result': result})
    except Exception as exc:
        connection.send_result(msg['id'], {'ok': False, 'error': str(exc)})

async def ws_rename_opmode(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Administrador necessário')
        return
    try:
        r = await hass.data[DOMAIN][msg['entry_id']].api.rename_opmode(msg['unlock_sn'], msg['name'].strip())
        connection.send_result(msg['id'], {'ok': True, 'result': r})
    except Exception as exc:
        connection.send_result(msg['id'], {'ok': False, 'error': str(exc)})

async def ws_delete_unlock_method(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Administrador necessário')
        return
    try:
        r = await hass.data[DOMAIN][msg['entry_id']].api.delete_unlock_method(msg['user_id'], msg['unlock_type'], msg['unlock_no'], msg['user_type'])
        connection.send_result(msg['id'], {'ok': True, 'result': r})
    except Exception as exc:
        connection.send_result(msg['id'], {'ok': False, 'error': str(exc)})

async def ws_start_password_enrollment(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Administrador necessário')
        return
    try:
        r = await hass.data[DOMAIN][msg['entry_id']].api.start_password_enrollment(msg['user_id'], msg['user_type'])
        connection.send_result(msg['id'], {'ok': True, 'result': r})
    except Exception as exc:
        connection.send_result(msg['id'], {'ok': False, 'error': str(exc)})

async def ws_cancel_password_enrollment(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Administrador necessário')
        return
    try:
        r = await hass.data[DOMAIN][msg['entry_id']].api.cancel_password_enrollment()
        connection.send_result(msg['id'], {'ok': True, 'result': r})
    except Exception as exc:
        connection.send_result(msg['id'], {'ok': False, 'error': str(exc)})

async def ws_remote_unlock_methods(hass, connection, msg):
    try:
        r = await hass.data[DOMAIN][msg['entry_id']].api.get_remote_unlock_methods()
        connection.send_result(msg['id'], {'ok': True, 'result': r})
    except Exception as exc:
        connection.send_result(msg['id'], {'ok': False, 'error': str(exc)})

async def ws_remote_unlock(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Administrador necessário')
        return
    if not msg.get('confirmed'):
        connection.send_error(msg['id'], 'confirmation_required', 'Confirmação obrigatória')
        return
    try:
        r = await hass.data[DOMAIN][msg['entry_id']].api.remote_unlock()
        connection.send_result(msg['id'], {'ok': True, 'result': r})
    except Exception as exc:
        connection.send_result(msg['id'], {'ok': False, 'error': str(exc)})

async def ws_add_device_user(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Administrador necessário')
        return
    try:
        r = await hass.data[DOMAIN][msg['entry_id']].api.add_device_user(msg['nick_name'].strip(), msg.get('sex', 1), msg.get('contact'))
        connection.send_result(msg['id'], {'ok': True, 'result': r})
    except Exception as exc:
        connection.send_result(msg['id'], {'ok': False, 'error': str(exc)})

async def ws_update_device_user(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Administrador necessário')
        return
    try:
        r = await hass.data[DOMAIN][msg['entry_id']].api.update_device_user(msg['user_id'], msg['nick_name'].strip(), msg.get('sex', 1))
        connection.send_result(msg['id'], {'ok': True, 'result': r})
    except Exception as exc:
        connection.send_result(msg['id'], {'ok': False, 'error': str(exc)})

async def ws_delete_device_user(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Administrador necessário')
        return
    try:
        r = await hass.data[DOMAIN][msg['entry_id']].api.delete_device_user(msg['user_id'])
        connection.send_result(msg['id'], {'ok': True, 'result': r})
    except Exception as exc:
        connection.send_result(msg['id'], {'ok': False, 'error': str(exc)})

async def ws_set_user_role(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Administrador necessário')
        return
    try:
        r = await hass.data[DOMAIN][msg['entry_id']].api.set_user_role(msg['user_id'], msg['role'])
        connection.send_result(msg['id'], {'ok': True, 'result': r})
    except Exception as exc:
        connection.send_result(msg['id'], {'ok': False, 'error': str(exc)})

async def ws_start_credential_enrollment(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Administrador necessário')
        return
    try:
        r = await hass.data[DOMAIN][msg['entry_id']].api.start_credential_enrollment(msg['user_id'], msg['unlock_type'], msg.get('user_type', 2))
        connection.send_result(msg['id'], {'ok': True, 'result': r})
    except Exception as exc:
        connection.send_result(msg['id'], {'ok': False, 'error': str(exc)})

async def ws_cancel_credential_enrollment(hass, connection, msg):
    if not connection.user.is_admin:
        connection.send_error(msg['id'], 'unauthorized', 'Administrador necessário')
        return
    try:
        r = await hass.data[DOMAIN][msg['entry_id']].api.cancel_credential_enrollment(msg['unlock_type'])
        connection.send_result(msg['id'], {'ok': True, 'result': r})
    except Exception as exc:
        connection.send_result(msg['id'], {'ok': False, 'error': str(exc)})
COMMANDS = {'kt1000/overview': ('ws_overview', {'entry_id': {'required': False, 'validator': 'str'}}), 'kt1000/people': ('ws_people', {'entry_id': {'required': True, 'validator': 'str'}}), 'kt1000/save_person': ('ws_save_person', {'entry_id': {'required': True, 'validator': 'str'}, 'name': {'required': True, 'validator': 'str'}, 'old_name': {'required': False, 'validator': 'str'}}), 'kt1000/delete_person': ('ws_delete_person', {'entry_id': {'required': True, 'validator': 'str'}, 'name': {'required': True, 'validator': 'str'}}), 'kt1000/assign': ('ws_assign', {'entry_id': {'required': True, 'validator': 'str'}, 'person': {'required': True, 'validator': 'str'}, 'credential': {'required': True, 'validator': 'str'}}), 'kt1000/unassign': ('ws_unassign', {'entry_id': {'required': True, 'validator': 'str'}, 'credential': {'required': True, 'validator': 'str'}}), 'kt1000/temp_passwords': ('ws_temp_passwords', {'entry_id': {'required': True, 'validator': 'str'}, 'valid': {'required': False, 'validator': 'bool'}}), 'kt1000/temp_password_detail': ('ws_temp_password_detail', {'entry_id': {'required': True, 'validator': 'str'}, 'password_id': {'required': True, 'validator': 'vol.Any(str, int)'}}), 'kt1000/create_temp_password': ('ws_create_temp_password', {'entry_id': {'required': True, 'validator': 'str'}, 'name': {'required': True, 'validator': 'str'}, 'password': {'required': True, 'validator': 'str'}, 'effective_time': {'required': True, 'validator': 'vol.Coerce(int)'}, 'invalid_time': {'required': True, 'validator': 'vol.Coerce(int)'}, 'use_once': {'required': False, 'validator': 'bool', 'default': False}}), 'kt1000/delete_temp_password': ('ws_delete_temp_password', {'entry_id': {'required': True, 'validator': 'str'}, 'password_id': {'required': True, 'validator': 'vol.Any(str, int)'}}), 'kt1000/set_temp_password_frozen': ('ws_set_temp_password_frozen', {'entry_id': {'required': True, 'validator': 'str'}, 'password_id': {'required': True, 'validator': 'vol.Any(str, int)'}, 'frozen': {'required': True, 'validator': 'bool'}}), 'kt1000/offline_temp_passwords': ('ws_offline_temp_passwords', {'entry_id': {'required': True, 'validator': 'str'}, 'target_status': {'required': False, 'validator': 'str', 'default': ''}}), 'kt1000/create_offline_temp_password': ('ws_create_offline_temp_password', {'entry_id': {'required': True, 'validator': 'str'}, 'pwd_type': {'required': True, 'validator': 'vol.Coerce(int)'}, 'name': {'required': False, 'validator': 'str', 'default': ''}, 'effective_time': {'required': False, 'validator': 'vol.Coerce(int)'}, 'invalid_time': {'required': False, 'validator': 'vol.Coerce(int)'}, 'password_id': {'required': False, 'validator': 'vol.Any(str, int)'}}), 'kt1000/lock_users': ('ws_lock_users', {'entry_id': {'required': True, 'validator': 'str'}}), 'kt1000/rename_opmode': ('ws_rename_opmode', {'entry_id': {'required': True, 'validator': 'str'}, 'unlock_sn': {'required': True, 'validator': 'vol.Any(str, int)'}, 'name': {'required': True, 'validator': 'str'}}), 'kt1000/delete_unlock_method': ('ws_delete_unlock_method', {'entry_id': {'required': True, 'validator': 'str'}, 'user_id': {'required': True, 'validator': 'str'}, 'unlock_type': {'required': True, 'validator': 'str'}, 'unlock_no': {'required': True, 'validator': 'vol.Coerce(int)'}, 'user_type': {'required': False, 'validator': 'vol.Coerce(int)', 'default': 1}}), 'kt1000/start_password_enrollment': ('ws_start_password_enrollment', {'entry_id': {'required': True, 'validator': 'str'}, 'user_id': {'required': True, 'validator': 'str'}, 'user_type': {'required': False, 'validator': 'vol.Coerce(int)', 'default': 1}}), 'kt1000/cancel_password_enrollment': ('ws_cancel_password_enrollment', {'entry_id': {'required': True, 'validator': 'str'}}), 'kt1000/remote_unlock_methods': ('ws_remote_unlock_methods', {'entry_id': {'required': True, 'validator': 'str'}}), 'kt1000/remote_unlock': ('ws_remote_unlock', {'entry_id': {'required': True, 'validator': 'str'}, 'confirmed': {'required': True, 'validator': 'bool'}}), 'kt1000/add_device_user': ('ws_add_device_user', {'entry_id': {'required': True, 'validator': 'str'}, 'nick_name': {'required': True, 'validator': 'str'}, 'sex': {'required': False, 'validator': 'vol.Coerce(int)', 'default': 1}, 'contact': {'required': False, 'validator': 'str'}}), 'kt1000/update_device_user': ('ws_update_device_user', {'entry_id': {'required': True, 'validator': 'str'}, 'user_id': {'required': True, 'validator': 'str'}, 'nick_name': {'required': True, 'validator': 'str'}, 'sex': {'required': False, 'validator': 'vol.Coerce(int)', 'default': 1}}), 'kt1000/delete_device_user': ('ws_delete_device_user', {'entry_id': {'required': True, 'validator': 'str'}, 'user_id': {'required': True, 'validator': 'str'}}), 'kt1000/set_user_role': ('ws_set_user_role', {'entry_id': {'required': True, 'validator': 'str'}, 'user_id': {'required': True, 'validator': 'str'}, 'role': {'required': True, 'validator': "vol.In(['admin', 'normal'])"}}), 'kt1000/start_credential_enrollment': ('ws_start_credential_enrollment', {'entry_id': {'required': True, 'validator': 'str'}, 'user_id': {'required': True, 'validator': 'str'}, 'unlock_type': {'required': True, 'validator': "vol.In(['password', 'fingerprint', 'card'])"}, 'user_type': {'required': False, 'validator': 'vol.Coerce(int)', 'default': 2}}), 'kt1000/cancel_credential_enrollment': ('ws_cancel_credential_enrollment', {'entry_id': {'required': True, 'validator': 'str'}, 'unlock_type': {'required': True, 'validator': "vol.In(['password', 'fingerprint', 'card'])"}})}

COMMANDS["kt1000/assign"][1]["expected_owner"]={"required":False,"validator":"str"}
COMMANDS["kt1000/unassign"][1]["expected_person"]={"required":False,"validator":"str"}
