"""Read-only telemetry; never exports PINs or cloud credentials."""
from types import SimpleNamespace
from .helpers import discovered_credentials
from .const import METHOD_NAMES


def snapshot(rt):
    history = rt.store.history_for('app')
    people = rt.store.people_for('app')
    entry = SimpleNamespace(options={'people': people})
    latest = rt.data.get('latest_by_code', {})
    last = history[0] if history else None
    return {
        'schema_version': 1, 'app_version': '0.12.0',
        'device_id': rt.api.device_id, 'title': rt.title,
        'poll_attempted': rt.poll_attempted,
        'cloud_success': rt.last_update_success, 'cloud_error': rt.last_error,
        'last_successful_update': rt.last_successful_update.isoformat() if rt.last_successful_update else None,
        'latest_by_code': latest, 'last_unlock': last,
        'method_name': METHOD_NAMES.get(last.get('code')) if last else None,
        'last_event': max(latest.values(), key=lambda x: int(x.get('eventTime', x.get('event_time', 0)) or 0), default=None),
        'logs': history[:25], 'access_count': len(history), 'people': people,
        'credentials': discovered_credentials(entry, history),
        'offline_password_count': len(rt.store.offline_for('app')),
    }
