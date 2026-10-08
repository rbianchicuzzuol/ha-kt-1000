import hashlib
import hmac
import time
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import TUYA_BASE_URL


class KT1000ApiError(Exception):
    """Erro retornado pela API Tuya."""
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = str(code) if code is not None else None


class KT1000Api:
    def __init__(self, session, client_id, client_secret, device_id):
        self.session = session
        self.client_id = str(client_id).strip().strip("\ufeff\u200b").strip()
        self.client_secret = str(client_secret).strip().strip("\ufeff\u200b").strip()
        self.device_id = str(device_id).strip()
        self.base_url = TUYA_BASE_URL
        self.remote_unlock_enabled = False
        self.remote_unlock_mode = "open_door"
        self._token = None
        self._token_expire_at = 0

    def _sign(self, method, request_path, token="", body=b""):
        t = str(int(time.time() * 1000))
        content_hash = hashlib.sha256(body).hexdigest()
        string_to_sign = f"{method}\n{content_hash}\n\n{request_path}"
        payload = self.client_id + token + t + string_to_sign
        sign = hmac.new(
            self.client_secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest().upper()
        return t, sign

    async def _request(self, method, path, params=None, token_required=True, json_body=None):
        params = params or {}
        query = urlencode(sorted((k, str(v)) for k, v in params.items()), safe=",")
        request_path = path + (f"?{query}" if query else "")
        token = await self.get_token() if token_required else ""

        body = b""
        if json_body is not None:
            # A assinatura Tuya precisa usar exatamente os mesmos bytes enviados.
            body = json.dumps(
                json_body, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")

        t, sign = self._sign(method, request_path, token, body)
        headers = {
            "client_id": self.client_id,
            "t": t,
            "sign_method": "HMAC-SHA256",
            "sign": sign,
        }
        if token:
            headers["access_token"] = token
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        async with self.session.request(
            method,
            self.base_url + request_path,
            headers=headers,
            data=body if json_body is not None else None,
        ) as response:
            data = await response.json(content_type=None)

        if not data.get("success"):
            raise KT1000ApiError(
                f"Tuya API error {data.get('code')}: {data.get('msg')}", code=data.get("code")
            )
        return data.get("result")

    async def get_token(self):
        for label, value in (("client_id", self.client_id), ("client_secret", self.client_secret)):
            if not value or set(value) <= set("*•●"):
                raise KT1000ApiError(f"Preencha {label} nas opções do App com o valor real do projeto Tuya, não o valor mascarado.")
            if any(c.isspace() or c in "\ufeff\u200b" for c in value):
                raise KT1000ApiError(f"{label} contém espaços ou caracteres invisíveis no meio. Copie novamente das credenciais do projeto Tuya.")
        now = time.time()
        if self._token and now < self._token_expire_at:
            return self._token

        path = "/v1.0/token"
        query = urlencode(sorted({"grant_type": "1"}.items()))
        request_path = f"{path}?{query}"
        t, sign = self._sign("GET", request_path)
        headers = {
            "client_id": self.client_id,
            "t": t,
            "sign_method": "HMAC-SHA256",
            "sign": sign,
        }

        async with self.session.get(
            self.base_url + request_path, headers=headers
        ) as response:
            data = await response.json(content_type=None)

        if not data.get("success"):
            if str(data.get('code')) == '1004':
                raise KT1000ApiError("Tuya token error 1004: sign invalid. Confira client_id e client_secret reais do mesmo projeto Tuya nas opções do App. A região deve ser a mesma da integração antiga (us na versão 0.8). Salve e reinicie somente o App.")
            raise KT1000ApiError(f"Tuya token error {data.get('code')}: {data.get('msg')}")

        result = data["result"]
        self._token = result["access_token"]
        expire = int(result.get("expire_time", 7200))
        self._token_expire_at = now + max(60, expire - 60)
        return self._token

    async def get_report_logs(self, codes, hours=48, size=100):
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=hours)
        return await self._request(
            "GET",
            f"/v2.1/cloud/thing/{self.device_id}/report-logs",
            {
                "codes": ",".join(codes),
                "end_time": int(now.timestamp() * 1000),
                "size": size,
                "start_time": int(start.timestamp() * 1000),
            },
        )

    async def get_temporary_passwords(self, valid=None):
        """Lista senhas temporárias cadastradas na fechadura pela Tuya Cloud."""
        params = {}
        if valid is not None:
            params["valid"] = "true" if valid else "false"
        result = await self._request(
            "GET",
            f"/v1.0/devices/{self.device_id}/door-lock/temp-passwords",
            params,
        )
        return result or []

    async def get_temporary_password(self, password_id):
        """Consulta os metadados de uma senha temporária específica."""
        return await self._request(
            "GET",
            f"/v1.0/devices/{self.device_id}/door-lock/temp-password/{password_id}",
        )

    @staticmethod
    def _aes_ecb_decrypt_hex(ciphertext_hex, key):
        decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        plaintext = decryptor.update(bytes.fromhex(ciphertext_hex)) + decryptor.finalize()
        # O ticket pode vir com PKCS7. Se não vier, preservamos os bytes.
        try:
            unpadder = padding.PKCS7(128).unpadder()
            return unpadder.update(plaintext) + unpadder.finalize()
        except ValueError:
            return plaintext

    @staticmethod
    def _aes_ecb_encrypt_hex(plaintext, key):
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        encrypted = encryptor.update(padded) + encryptor.finalize()
        return encrypted.hex().upper()

    async def get_password_ticket(self):
        return await self._request(
            "POST",
            f"/v1.0/devices/{self.device_id}/door-lock/password-ticket",
        )

    async def _encrypt_lock_password(self, password, ticket_key):
        if not (password.isdigit() and len(password) == 7):
            raise KT1000ApiError("A senha da fechadura Wi-Fi deve ter exatamente 7 dígitos.")

        # A Tuya entrega ticket_key em HEX, cifrado com o Access Secret.
        # O Access Secret/Client Secret da plataforma é a chave AES-256 (32 bytes).
        access_key = self.client_secret.encode("utf-8")
        if len(access_key) not in (16, 24, 32):
            raise KT1000ApiError(
                "O Client Secret possui tamanho incompatível com AES."
            )

        ticket_plain = self._aes_ecb_decrypt_hex(ticket_key, access_key)
        # A chave resultante usada para a senha é AES-128.
        lock_key = ticket_plain[:16]
        if len(lock_key) != 16:
            raise KT1000ApiError("A Tuya retornou uma chave temporária inválida.")

        return self._aes_ecb_encrypt_hex(password.encode("utf-8"), lock_key)

    async def create_temporary_password(
        self, name, password, effective_time, invalid_time, use_once=False
    ):
        ticket = await self.get_password_ticket()
        if not isinstance(ticket, dict) or not ticket.get("ticket_id") or not ticket.get("ticket_key"):
            raise KT1000ApiError("A Tuya não retornou um password ticket válido.")

        encrypted = await self._encrypt_lock_password(password, ticket["ticket_key"])
        body = {
            "name": name,
            "password": encrypted,
            "password_type": "ticket",
            "ticket_id": ticket["ticket_id"],
            "effective_time": int(effective_time),
            "invalid_time": int(invalid_time),
            "type": 1 if use_once else 0,
        }
        return await self._request(
            "POST",
            f"/v1.0/devices/{self.device_id}/door-lock/temp-password",
            json_body=body,
        )

    async def delete_temporary_password(self, password_id):
        if not str(password_id).isdigit():
            raise KT1000ApiError("ID de senha inválido. Atualize a lista.")
        result = await self._request(
            "DELETE",
            f"/v1.0/devices/{self.device_id}/door-lock/temp-passwords/{password_id}",
        )
        if result is not True:
            raise KT1000ApiError("A Tuya não confirmou a exclusão. Atualize a lista para conferir o estado.")
        return result

    async def delete_temporary_password_record(self, password_id):
        """Remove only the cloud history record; never modify validity or unlock."""
        if not str(password_id).isdigit():
            raise KT1000ApiError("ID de senha inválido.")
        result=await self._request("DELETE", f"/v1.0/devices/{self.device_id}/door-lock/temp-passwords/{password_id}/record")
        if result is not True:
            raise KT1000ApiError("A Tuya não confirmou a exclusão do registro histórico.")
        return result

    async def freeze_temporary_password(self, password_id):
        """Congela uma senha temporária já cadastrada."""
        return await self._request(
            "PUT",
            f"/v1.0/devices/{self.device_id}/door-lock/temp-passwords/{password_id}/freeze-password",
        )

    async def unfreeze_temporary_password(self, password_id):
        """Reativa uma senha temporária congelada, mantendo o período original."""
        return await self._request(
            "PUT",
            f"/v1.0/devices/{self.device_id}/door-lock/temp-passwords/{password_id}/unfreeze-password",
        )

    async def get_offline_temporary_passwords(self, pwd_type_codes="multiple,once,clear_one,clear_all", target_status="", page_no=1, page_size=100):
        """Read all cloud pages; never issue lock operations."""
        items=[]
        for page in range(int(page_no),int(page_no)+100):
            result=await self._request("GET",f"/v1.0/devices/{self.device_id}/door-lock/offline-temp-password",{
                "pwd_type_codes":pwd_type_codes,"target_status":target_status,
                "page_no":page,"page_size":int(page_size)})
            if isinstance(result,list):return items+result
            if not isinstance(result,dict):raise KT1000ApiError("Resposta inválida da listagem offline.")
            records=result.get("records") or result.get("list") or result.get("data") or []
            if not isinstance(records,list):raise KT1000ApiError("Lista offline inválida.")
            items.extend(records)
            more=result.get("has_more") is True or page<int(result.get("total_pages") or page)
            if not more:return items
            if not records:raise KT1000ApiError("Paginação offline inconsistente; histórico local preservado.")
        raise KT1000ApiError("A listagem offline ultrapassou 100 páginas; histórico local preservado.")

    async def create_offline_temporary_password(self, name, pwd_type, effective_time=None, invalid_time=None, password_id=None):
        """Gera senha/código offline via API v1.1 da Tuya."""
        types = {0: "multiple", 1: "once", 8: "clear_one", 9: "clear_all"}
        pwd_type = int(pwd_type)
        if pwd_type not in types:
            raise KT1000ApiError("Tipo offline inválido.")
        body = {"type": types[pwd_type], "lang": "en"}
        if name:
            body["name"] = name
        hour = int(time.time()) // 3600 * 3600
        if pwd_type in (1, 9):
            body["effective_time"] = hour
            body["invalid_time"] = hour + (6 if pwd_type == 1 else 24) * 3600
        else:
            if effective_time is None or (pwd_type == 0 and invalid_time is None):
                raise KT1000ApiError("Informe o período da senha offline.")
            body["effective_time"] = int(effective_time) // 3600 * 3600
            if invalid_time is not None:
                body["invalid_time"] = int(invalid_time) // 3600 * 3600
                if body["invalid_time"] <= body["effective_time"]:
                    raise KT1000ApiError("O período deve ter pelo menos uma hora após arredondamento.")
        if pwd_type == 8:
            if not password_id:
                raise KT1000ApiError("Informe o ID da senha a apagar.")
            body["password_id"] = str(password_id)
        return await self._request(
            "POST",
            f"/v1.1/devices/{self.device_id}/door-lock/offline-temp-password",
            json_body=body,
        )

    async def validate(self):
        result = await self.get_report_logs(
            ["residual_electricity"], hours=24, size=1
        )
        return result is not None

# v0.8.0 - gerenciamento Tuya de usuários/credenciais e desbloqueio remoto
async def _kt_get_lock_users(self, page_no=1, page_size=100):
    result = await self._request("GET", f"/v1.0/smart-lock/devices/{self.device_id}/users", {
        "codes": "unlock_fingerprint,unlock_card,unlock_password,unlock_face,unlock_hand,unlock_finger_vein",
        "page_no": int(page_no), "page_size": int(page_size),
    })
    return result or {}

async def _kt_get_user_opmodes(self, user_id):
    return await self._request("GET", f"/v1.0/smart-lock/devices/{self.device_id}/opmodes/{user_id}", {"codes":"", "unlock_name":""})

async def _kt_rename_opmode(self, unlock_sn, name):
    return await self._request("PUT", f"/v1.0/devices/{self.device_id}/door-lock/opmodes/{unlock_sn}", json_body={"unlock_name": name})

async def _kt_delete_unlock_method(self, user_id, unlock_type, unlock_no, user_type=1):
    return await self._request("DELETE", f"/v1.0/devices/{self.device_id}/door-lock/user-types/{int(user_type)}/users/{user_id}/unlock-types/{unlock_type}/keys/{int(unlock_no)}")

async def _kt_start_password_enrollment(self, user_id, user_type=1):
    return await self._request("PUT", f"/v1.0/devices/{self.device_id}/door-lock/actions/entry", json_body={"user_id": str(user_id), "user_type": int(user_type), "unlock_type": "password"})

async def _kt_cancel_password_enrollment(self):
    return await self._request("PUT", f"/v1.0/devices/{self.device_id}/door-lock/unlock-types/password/actions/cancel")

async def _kt_remote_unlock_methods(self):
    return await self._request("GET", f"/v1.0/devices/{self.device_id}/door-lock/remote-unlocks")

async def _kt_remote_unlock(self):
    if not self.remote_unlock_enabled:
        raise KT1000ApiError("Desbloqueio remoto desativado nas opções do App.")
    if self.remote_unlock_mode == "door_operate":
        ticket = await self._request("POST", f"/v1.0/smart-lock/devices/{self.device_id}/password-ticket")
        path = f"/v1.0/smart-lock/devices/{self.device_id}/password-free/door-operate"
        body = {"open": True}
    elif self.remote_unlock_mode == "open_door":
        ticket = await self.get_password_ticket()
        path = f"/v1.0/devices/{self.device_id}/door-lock/password-free/open-door"
        body = {}
    else:
        raise KT1000ApiError("Modo de desbloqueio inválido.")
    if not isinstance(ticket, dict) or not ticket.get("ticket_id"):
        raise KT1000ApiError("A Tuya não retornou ticket para desbloqueio remoto.")
    body["ticket_id"] = ticket["ticket_id"]
    result = await self._request("POST", path, json_body=body)
    if result is not True:
        raise KT1000ApiError("A Tuya não confirmou o comando de desbloqueio.")
    return result

KT1000Api.get_lock_users = _kt_get_lock_users
KT1000Api.get_user_opmodes = _kt_get_user_opmodes
KT1000Api.rename_opmode = _kt_rename_opmode
KT1000Api.delete_unlock_method = _kt_delete_unlock_method
KT1000Api.start_password_enrollment = _kt_start_password_enrollment
KT1000Api.cancel_password_enrollment = _kt_cancel_password_enrollment
KT1000Api.get_remote_unlock_methods = _kt_remote_unlock_methods
KT1000Api.remote_unlock = _kt_remote_unlock

# v0.8.0 - ciclo completo de usuarios e enrollment de credenciais
async def _kt_add_device_user(self, nick_name, sex=1, contact=None):
    body={"nick_name": str(nick_name), "sex": int(sex)}
    if contact: body["contact"]=str(contact)
    return await self._request("POST", f"/v1.0/devices/{self.device_id}/user", json_body=body)

async def _kt_update_device_user(self, user_id, nick_name, sex=1):
    return await self._request("PUT", f"/v1.0/devices/{self.device_id}/users/{user_id}", json_body={"nick_name":str(nick_name),"sex":int(sex)})

async def _kt_delete_device_user(self, user_id):
    return await self._request("DELETE", f"/v1.0/devices/{self.device_id}/users/{user_id}")

async def _kt_set_user_role(self, user_id, role):
    if role not in ("admin","normal"):
        raise KT1000ApiError("Perfil inválido.")
    return await self._request("PUT", f"/v1.0/smart-lock/devices/{self.device_id}/users/{user_id}/actions/role", json_body={"role":role})

async def _kt_start_credential_enrollment(self, user_id, unlock_type, user_type=2):
    if unlock_type not in ("password","fingerprint","card"):
        raise KT1000ApiError("Tipo de credencial inválido.")
    return await self._request("PUT", f"/v1.0/devices/{self.device_id}/door-lock/actions/entry", json_body={"user_id":str(user_id),"user_type":int(user_type),"unlock_type":unlock_type})

async def _kt_cancel_credential_enrollment(self, unlock_type):
    if unlock_type not in ("password","fingerprint","card"):
        raise KT1000ApiError("Tipo de credencial inválido.")
    return await self._request("PUT", f"/v1.0/devices/{self.device_id}/door-lock/unlock-types/{unlock_type}/actions/cancel")

KT1000Api.add_device_user=_kt_add_device_user
KT1000Api.update_device_user=_kt_update_device_user
KT1000Api.delete_device_user=_kt_delete_device_user
KT1000Api.set_user_role=_kt_set_user_role
KT1000Api.start_credential_enrollment=_kt_start_credential_enrollment
KT1000Api.cancel_credential_enrollment=_kt_cancel_credential_enrollment
