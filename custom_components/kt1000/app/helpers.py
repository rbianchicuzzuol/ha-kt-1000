from datetime import datetime, timezone

from .const import CREDENTIAL_LABELS, METHOD_NAMES, OPT_PEOPLE, UNLOCK_CODES


def event_timestamp(item):
    if not item:
        return 0
    return int(item.get("eventTime", item.get("event_time", 0)) or 0)


def event_datetime(item):
    ms = event_timestamp(item)
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).astimezone()


def credential_key(code, value):
    return f"{code}:{value}"


def people(entry):
    value = entry.options.get(OPT_PEOPLE, [])
    return value if isinstance(value, list) else []


def resolve_person(entry, code, value):
    target = credential_key(code, str(value))
    for person in people(entry):
        if target in person.get("credentials", []):
            return person.get("name")
    return None


def credential_owner(entry, key):
    for person in people(entry):
        if key in person.get("credentials", []):
            return person.get("name")
    return None


def unlock_data(entry, item):
    if not item:
        return {}
    code = item.get("code")
    value = str(item.get("value", ""))
    person = resolve_person(entry, code, value)
    dt = event_datetime(item)
    return {
        "usuario": person or "Não identificado",
        "identificado": person is not None,
        "metodo": METHOD_NAMES.get(code, code),
        "codigo_metodo": code,
        "credencial_id": value,
        "event_time": event_timestamp(item),
        "horario": dt.isoformat() if dt else None,
    }


def discovered_credentials(entry, logs):
    result = {}
    for item in logs:
        code = item.get("code")
        if code not in UNLOCK_CODES:
            continue
        value = str(item.get("value", ""))
        if not value:
            continue
        key = credential_key(code, value)
        ts = event_timestamp(item)
        if key not in result:
            result[key] = {
                "key": key,
                "code": code,
                "id": value,
                "tipo": CREDENTIAL_LABELS.get(code, code),
                "ultimo_uso": ts,
                "quantidade": 0,
            }
        result[key]["quantidade"] += 1
        result[key]["ultimo_uso"] = max(result[key]["ultimo_uso"], ts)

    for item in result.values():
        item["pessoa"] = credential_owner(entry, item["key"])
    return result


def access_history(entry, logs, limit=50):
    rows = []
    for item in logs:
        if item.get("code") not in UNLOCK_CODES:
            continue
        row = unlock_data(entry, item)
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows
