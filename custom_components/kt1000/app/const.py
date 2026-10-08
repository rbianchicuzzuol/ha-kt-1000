DOMAIN = "kt1000"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_DEVICE_ID = "device_id"

OPT_PEOPLE = "people"
DEFAULT_SCAN_INTERVAL = 30
HISTORY_HOURS = 168
HISTORY_SIZE = 100

TUYA_BASE_URL = "https://openapi.tuyaus.com"

UNLOCK_CODES = (
    "unlock_fingerprint",
    "unlock_password",
    "unlock_temporary",
    "unlock_card",
    "unlock_app",
)

ALL_CODES = (
    "unlock_fingerprint",
    "unlock_password",
    "unlock_temporary",
    "unlock_card",
    "alarm_lock",
    "unlock_request",
    "residual_electricity",
    "reverse_lock",
    "unlock_app",
    "hijack",
    "doorbell",
)

METHOD_NAMES = {
    "unlock_fingerprint": "Impressão digital",
    "unlock_password": "Senha",
    "unlock_temporary": "Senha temporária",
    "unlock_card": "Cartão / tag",
    "unlock_app": "Aplicativo",
}

CREDENTIAL_LABELS = {
    "unlock_fingerprint": "Digital",
    "unlock_password": "Senha",
    "unlock_temporary": "Senha temporária",
    "unlock_card": "Cartão / tag",
    "unlock_app": "Aplicativo",
}

ALARM_NAMES = {
    "wrong_finger": "Impressão digital incorreta",
    "wrong_password": "Senha incorreta",
    "wrong_card": "Cartão / tag incorreto",
    "wrong_face": "Reconhecimento facial incorreto",
    "tongue_bad": "Falha no trinco",
    "too_hot": "Temperatura elevada",
    "unclosed_time": "Porta não fechada no tempo esperado",
    "tongue_not_out": "Trinco não projetado",
    "pry": "Tentativa de violação",
    "key_in": "Chave inserida",
    "low_battery": "Bateria baixa",
    "power_off": "Falha / desligamento de energia",
    "shock": "Impacto detectado",
    "defense": "Modo de defesa",
    "stay_alarm": "Alarme de permanência",
    "doorbell": "Campainha",
    "wrong_unlock": "Tentativa de desbloqueio incorreta",
}
