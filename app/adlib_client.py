"""
Wrapper around TikTok's Commercial Content API (Ad Library), confirmed against
the official docs on 2026-08-16 (developers.tiktok.com/doc/commercial-content-api-*).

This is a DIFFERENT TikTok platform than TikTok Shop Partner Center — it's
TikTok for Developers, and needs its own app + a separate "Commercial Content
API" access application (public, ~2 business days review, no GMV requirement).

Hard limitation, not a bug: TikTok only publishes ad-transparency data for
Europe (EU/EEA + UK/Switzerland) — see SUPPORTED_COUNTRIES. There is no ad
spend or engagement/conversion data, only reach (unique users seen, bucketed
like "11K") and the creative itself. This is a transparency database, not an
ad-spy tool — see the project README for what it can't do.
"""
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

from app.config import settings

API_BASE = "https://open.tiktokapis.com/v2"

SUPPORTED_COUNTRIES = {
    "AT": "Áustria", "BE": "Bélgica", "BG": "Bulgária", "HR": "Croácia",
    "CY": "Chipre", "CZ": "República Tcheca", "DK": "Dinamarca", "EE": "Estônia",
    "FI": "Finlândia", "FR": "França", "DE": "Alemanha", "GR": "Grécia",
    "HU": "Hungria", "IE": "Irlanda", "IT": "Itália", "LV": "Letônia",
    "LT": "Lituânia", "LU": "Luxemburgo", "MT": "Malta", "NL": "Holanda",
    "PL": "Polônia", "PT": "Portugal", "RO": "Romênia", "SK": "Eslováquia",
    "SI": "Eslovênia", "ES": "Espanha", "SE": "Suécia",
    "NO": "Noruega", "IS": "Islândia", "LI": "Liechtenstein",
    "GB": "Reino Unido", "CH": "Suíça",
}


class AdLibraryAPIError(Exception):
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload
        super().__init__(f"Ad Library API error {status_code}: {payload}")


class AdLibraryClient:
    def __init__(self):
        self.client_key = settings.adlib_client_key
        self.client_secret = settings.adlib_client_secret

    def get_client_token(self) -> dict:
        """Client-credentials grant — no per-user authorization needed for this API."""
        resp = requests.post(
            f"{API_BASE}/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
        )
        payload = resp.json()
        if "access_token" not in payload:
            raise AdLibraryAPIError(resp.status_code, payload)
        payload["expires_at"] = datetime.utcnow() + timedelta(seconds=payload.get("expires_in", 7200))
        return payload

    def query_ads(
        self,
        access_token: str,
        search_term: Optional[str] = None,
        country_code: Optional[str] = None,
        advertiser_business_ids: Optional[list] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        max_count: int = 20,
        search_id: Optional[str] = None,
    ) -> dict:
        fields = ",".join([
            "ad.id", "ad.first_shown_date", "ad.last_shown_date", "ad.status",
            "ad.videos", "ad.image_urls", "ad.reach",
            "advertiser.business_id", "advertiser.business_name", "advertiser.paid_for_by",
        ])
        date_from = date_from or (datetime.utcnow() - timedelta(days=180)).strftime("%Y%m%d")
        date_to = date_to or (datetime.utcnow() - timedelta(days=1)).strftime("%Y%m%d")

        body = {
            "filters": {
                "ad_published_date_range": {"min": date_from, "max": date_to},
            },
            "max_count": min(max_count, 50),
        }
        if country_code:
            body["filters"]["country_code"] = country_code
        if advertiser_business_ids:
            body["filters"]["advertiser_business_ids"] = advertiser_business_ids
        elif search_term:
            body["search_term"] = search_term
        if search_id:
            body["search_id"] = search_id

        def _do_request():
            resp = requests.post(
                f"{API_BASE}/research/adlib/ad/query/",
                params={"fields": fields},
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json=body,
            )
            return resp.status_code, resp.json()

        status_code, payload = _do_request()
        error = payload.get("error") or {}
        # 500 internal_error tem se mostrado instável/transitório do lado do TikTok
        # (mesmo payload, mesmo token, log_id diferente a cada tentativa) — 1 retry
        # silencioso antes de propagar o erro pro usuário.
        if status_code == 500 and error.get("code") == "internal_error":
            time.sleep(1.5)
            status_code, payload = _do_request()
            error = payload.get("error") or {}

        if error.get("code") not in (None, "ok"):
            raise AdLibraryAPIError(status_code, payload)
        return payload.get("data", {})


adlib_client = AdLibraryClient()
