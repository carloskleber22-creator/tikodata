"""
Thin wrapper around the TikTok Shop Partner Center API
(https://partner.tiktokshop.com/docv2), confirmed against the official docs
on 2026-08-16 (Developer Guide > Authorization, API concepts > Sign your API
request, API Reference > Orders > Get Order List, Seller > Get Authorized
Shops, Affiliate seller > Seller Search Creator on Marketplace, Affiliate
seller > Seller Search Affiliate Open Collaboration Product).

Sales data (search_orders) is scoped to "own store" only — no official API
pulls other sellers' order history. But the Affiliate Seller API DOES expose
marketplace-wide data: creators (any creator in the Creator Marketplace, with
GMV/follower/category filters) and products from OTHER shops that are open to
affiliate collaboration (with shop name, units sold, price, commission). Both
still require an access_token + shop_cipher from OUR OWN connected shop — it's
not anonymous access, just a wider dataset than the seller's own catalog.

API surface can change; re-check partner.tiktokshop.com if something here
starts failing.
"""
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import requests

from app.config import settings

API_BASE = "https://open-api.tiktokglobalshop.com"
AUTH_BASE = "https://auth.tiktok-shops.com/api/v2"

# Authorization link domain differs by market. ROW = rest of world (non-US).
AUTHORIZE_URL_ROW = "https://services.tiktokshop.com/open/authorize"
AUTHORIZE_URL_US = "https://services.us.tiktokshop.com/open/authorize"

API_VERSION = "202309"


class TikTokShopAPIError(Exception):
    def __init__(self, code, message, payload):
        self.code = code
        self.message = message
        self.payload = payload
        super().__init__(f"TikTok Shop API error {code}: {message}")


class TikTokShopClient:
    def __init__(self):
        self.app_key = settings.tt_app_key
        self.app_secret = settings.tt_app_secret
        self.service_id = settings.tt_service_id

    # ------------------------------------------------------------------ #
    # OAuth2
    # ------------------------------------------------------------------ #
    def get_authorization_url(self, state: str = "") -> str:
        domain = AUTHORIZE_URL_US if settings.tt_us_market else AUTHORIZE_URL_ROW
        params = {"service_id": self.service_id}
        if state:
            params["state"] = state
        return f"{domain}?{urlencode(params)}"

    def get_access_token(self, auth_code: str) -> dict:
        return self._token_request(
            "get",
            {
                "app_key": self.app_key,
                "app_secret": self.app_secret,
                "auth_code": auth_code,
                # Intentionally "authorized_code", not the standard OAuth
                # "authorization_code" — that's what TikTok's API expects.
                "grant_type": "authorized_code",
            },
        )

    def refresh_access_token(self, refresh_token: str) -> dict:
        return self._token_request(
            "refresh",
            {
                "app_key": self.app_key,
                "app_secret": self.app_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )

    def _token_request(self, endpoint: str, params: dict) -> dict:
        resp = requests.get(f"{AUTH_BASE}/token/{endpoint}", params=params)
        payload = resp.json()
        if payload.get("code") != 0:
            raise TikTokShopAPIError(payload.get("code"), payload.get("message"), payload)
        data = payload["data"]
        data["access_token_expire_at"] = datetime.utcnow() + timedelta(
            seconds=max(0, data["access_token_expire_in"] - int(time.time()))
        )
        data["refresh_token_expire_at"] = datetime.utcnow() + timedelta(
            seconds=max(0, data["refresh_token_expire_in"] - int(time.time()))
        )
        return data

    # ------------------------------------------------------------------ #
    # Request signing — see "Sign your API request" in the official docs.
    # HMAC-SHA256 over: path + sorted(key+value for query params, excluding
    # sign/access_token) + raw JSON body (if any, and if not multipart),
    # wrapped in app_secret on both ends.
    # ------------------------------------------------------------------ #
    def _sign(self, path: str, query: dict, body: bytes) -> str:
        keys = sorted(k for k in query if k not in ("sign", "access_token"))
        concatenated = "".join(f"{k}{query[k]}" for k in keys)
        message = path + concatenated
        if body:
            message += body.decode("utf-8")
        wrapped = self.app_secret + message + self.app_secret
        return hmac.new(self.app_secret.encode(), wrapped.encode(), hashlib.sha256).hexdigest()

    def _request(self, method: str, path: str, access_token: Optional[str] = None, query: Optional[dict] = None, json_body: Optional[dict] = None) -> dict:
        query = {k: v for k, v in (query or {}).items() if v is not None}
        query["app_key"] = self.app_key
        query["timestamp"] = str(int(time.time()))

        body_bytes = json.dumps(json_body, separators=(",", ":")).encode() if json_body is not None else b""
        query["sign"] = self._sign(path, query, body_bytes)

        headers = {"content-type": "application/json"}
        if access_token:
            headers["x-tts-access-token"] = access_token

        resp = requests.request(
            method,
            f"{API_BASE}{path}",
            params=query,
            data=body_bytes if json_body is not None else None,
            headers=headers,
        )
        payload = resp.json()
        if payload.get("code") != 0:
            raise TikTokShopAPIError(payload.get("code"), payload.get("message"), payload)
        return payload["data"]

    # ------------------------------------------------------------------ #
    # Seller-scoped calls (own shop only)
    # ------------------------------------------------------------------ #
    def get_authorized_shops(self, access_token: str) -> dict:
        return self._request("GET", f"/authorization/{API_VERSION}/shops", access_token=access_token)

    def search_orders(
        self,
        access_token: str,
        shop_cipher: str,
        page_size: int = 50,
        page_token: Optional[str] = None,
        sort_field: str = "create_time",
        sort_order: str = "DESC",
    ) -> dict:
        query = {
            "shop_cipher": shop_cipher,
            "page_size": page_size,
            "sort_field": sort_field,
            "sort_order": sort_order,
            "page_token": page_token,
        }
        return self._request(
            "POST",
            f"/order/{API_VERSION}/orders/search",
            access_token=access_token,
            query=query,
            json_body={},
        )

    # ------------------------------------------------------------------ #
    # Affiliate Seller API — marketplace-wide creator & product search.
    # Still needs OUR shop's access_token/shop_cipher, but results span
    # other sellers' shops and any creator in the Creator Marketplace.
    # ------------------------------------------------------------------ #
    def search_marketplace_creators(
        self,
        access_token: str,
        shop_cipher: str,
        keyword: Optional[str] = None,
        gmv_ranges: Optional[list] = None,
        units_sold_ranges: Optional[list] = None,
        page_size: int = 20,
        page_token: Optional[str] = None,
        search_key: Optional[str] = None,
    ) -> dict:
        query = {"shop_cipher": shop_cipher, "page_size": page_size, "page_token": page_token}
        body = {}
        if keyword:
            body["keyword"] = keyword
        if gmv_ranges:
            body["gmv_ranges"] = gmv_ranges
        if units_sold_ranges:
            body["units_sold_ranges"] = units_sold_ranges
        if search_key:
            body["search_key"] = search_key
        return self._request(
            "POST",
            "/affiliate_seller/202508/marketplace_creators/search",
            access_token=access_token,
            query=query,
            json_body=body,
        )

    def search_open_collaboration_products(
        self,
        access_token: str,
        shop_cipher: str,
        title_keywords: Optional[list] = None,
        category_id: Optional[str] = None,
        sales_price_range: Optional[dict] = None,
        commission_rate_range: Optional[dict] = None,
        sort_field: str = "units_sold",
        sort_order: str = "DESC",
        page_size: int = 20,
        page_token: Optional[str] = None,
    ) -> dict:
        query = {
            "shop_cipher": shop_cipher,
            "sort_field": sort_field,
            "sort_order": sort_order,
            "page_size": page_size,
            "page_token": page_token,
        }
        body = {}
        if title_keywords:
            body["title_keywords"] = title_keywords
        if category_id:
            body["category"] = {"id": category_id}
        if sales_price_range:
            body["sales_price_range"] = sales_price_range
        if commission_rate_range:
            body["commission_rate_range"] = commission_rate_range
        return self._request(
            "POST",
            "/affiliate_seller/202405/open_collaborations/products/search",
            access_token=access_token,
            query=query,
            json_body=body,
        )


tt_client = TikTokShopClient()
