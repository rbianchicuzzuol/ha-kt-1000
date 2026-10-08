"""Authenticated, read-only snapshot for native Home Assistant entities."""
import hmac
from types import SimpleNamespace
from aiohttp import web
from .helpers import discovered_credentials
from .const import METHOD_NAMES


def snapshot(rt):
    history = rt.store.history_for('app')
    people = rt.store.people_for('app')
    entry = SimpleNamespace(options={'people': people})
    latest = rt.data.get('latest_by_code', {})
    last = history[0] if history else None
    return {
        'schema_version': 1, 'app_version': '0.11.0',
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


def create_bridge_app(runtime, token):
    async def read(request):
        supplied = request.headers.get('Authorization', '')
        if len(token) < 32 or not hmac.compare_digest(supplied.encode(), ('Bearer '+token).encode()):
            raise web.HTTPUnauthorized()
        response = web.json_response(snapshot(runtime))
        response.headers['Cache-Control'] = 'no-store'
        return response
    app = web.Application(client_max_size=1024)
    app.router.add_get('/v1/snapshot', read, allow_head=False)
    return app
