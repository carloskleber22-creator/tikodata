"""
Wrapper around the Shopee Open Platform API v2 (open.shopee.com), confirmed
against the official docs on 2026-08-16 (Developer Guide > Authorization and
Authentication, Developer Guide > API calls > Signature calculation, API
Reference > Order > get_order_list).

Candidatura como "Third-party Partner Platform" (ISV) enviada em 2026-08-16,
em avaliação — partner_id/partner_key só existem depois que a Shopee cria o
App dentro do perfil aprovado (etapa separada da aprovação do perfil, ver
README). Este cliente foi escrito a partir da doc oficial antes de termos
credenciais reais, mesmo padrão usado para o TikTok Shop e a Ad Library.

Diferente do TikTok Shop: a assinatura aqui é HMAC-SHA256 puro sobre uma
"base string" simples (partner_id + api_path + timestamp [+ access_token +
shop_id]), sem ordenar/concatenar query params — bem mais simples que o
esquema do TikTok Shop.
"""
import hashlib
import hmac
import time
from typing import Optional

import requests

from app.config import settings

API_VERSION = "v2"


class ShopeeAPIError(Exception):
    def __init__(self, error_code, message, payload):
        self.error_code = error_code
        self.message = message
        self.payload = payload
        super().__init__(f"Shopee API error {error_code}: {message}")


class ShopeeClient:
    def __init__(self):
        self.partner_id = settings.shopee_partner_id
        self.partner_key = settings.shopee_partner_key
        self.api_host = settings.shopee_api_host
        self.auth_host = settings.shopee_auth_host

    # ------------------------------------------------------------------ #
    # Assinatura — HMAC-SHA256 sobre "partner_id + path + timestamp [+
    # access_token + shop_id]", com o partner_key como chave. Confirmado
    # literalmente contra o exemplo da doc oficial ("Signature calculation").
    # ------------------------------------------------------------------ #
    def _sign(self, path: str, timestamp: int, access_token: str = "", shop_id: str = "") -> str:
        base_string = f"{self.partner_id}{path}{timestamp}{access_token}{shop_id}"
        return hmac.new(self.partner_key.encode(), base_string.encode(), hashlib.sha256).hexdigest()

    # ------------------------------------------------------------------ #
    # OAuth2 — autoriza o app a ler pedidos/produtos da loja
    # ------------------------------------------------------------------ #
    def get_authorization_url(self) -> str:
        timestamp = int(time.time())
        path = "/api/v2/shop/auth_partner"
        sign = self._sign(path, timestamp)
        return (
            f"{self.auth_host}/api/v2/shop/auth_partner"
            f"?partner_id={self.partner_id}&timestamp={timestamp}&sign={sign}"
            f"&redirect={settings.shopee_redirect_uri}"
        )

    def get_access_token(self, code: str, shop_id: str) -> dict:
        """Troca o `code` do redirect por access_token/refresh_token. É uma Public
        API (sem access_token/shop_id na assinatura), mas leva shop_id no corpo."""
        path = "/api/v2/auth/token/get"
        return self._public_post(path, {"code": code, "shop_id": int(shop_id), "partner_id": int(self.partner_id)})

    def refresh_access_token(self, refresh_token: str, shop_id: str) -> dict:
        path = "/api/v2/auth/access_token/get"
        return self._public_post(path, {
            "refresh_token": refresh_token,
            "shop_id": int(shop_id),
            "partner_id": int(self.partner_id),
        })

    def _public_post(self, path: str, body: dict) -> dict:
        timestamp = int(time.time())
        sign = self._sign(path, timestamp)
        resp = requests.post(
            f"{self.api_host}{path}",
            params={"partner_id": self.partner_id, "timestamp": timestamp, "sign": sign},
            json=body,
        )
        payload = resp.json()
        if payload.get("error"):
            raise ShopeeAPIError(payload["error"], payload.get("message", ""), payload)
        return payload

    # ------------------------------------------------------------------ #
    # Shop API — precisa de access_token + shop_id (loja autorizada)
    # ------------------------------------------------------------------ #
    def _shop_get(self, path: str, access_token: str, shop_id: str, params: Optional[dict] = None) -> dict:
        timestamp = int(time.time())
        sign = self._sign(path, timestamp, access_token, shop_id)
        query = {
            "partner_id": self.partner_id,
            "timestamp": timestamp,
            "sign": sign,
            "access_token": access_token,
            "shop_id": shop_id,
            **(params or {}),
        }
        resp = requests.get(f"{self.api_host}{path}", params=query)
        payload = resp.json()
        if payload.get("error"):
            raise ShopeeAPIError(payload["error"], payload.get("message", ""), payload)
        return payload

    def get_shop_info(self, access_token: str, shop_id: str) -> dict:
        return self._shop_get("/api/v2/shop/get_shop_info", access_token, shop_id)

    def get_order_list(
        self,
        access_token: str,
        shop_id: str,
        time_from: int,
        time_to: int,
        page_size: int = 100,
        cursor: str = "",
        time_range_field: str = "create_time",
    ) -> dict:
        """Parâmetros conferem com o padrão documentado da v2 (time_range_field,
        time_from/time_to em unix timestamp, cursor de paginação) — não cheguei a
        abrir a página de detalhe do endpoint pra confirmar campo a campo (site
        não carregou o conteúdo específico), então trate como boa-fé até testar
        com credencial real."""
        return self._shop_get("/api/v2/order/get_order_list", access_token, shop_id, {
            "time_range_field": time_range_field,
            "time_from": time_from,
            "time_to": time_to,
            "page_size": min(page_size, 100),
            "cursor": cursor,
        })

    def get_order_detail(self, access_token: str, shop_id: str, order_sn_list: list) -> dict:
        return self._shop_get("/api/v2/order/get_order_detail", access_token, shop_id, {
            "order_sn_list": ",".join(order_sn_list),
        })


shopee_client = ShopeeClient()
