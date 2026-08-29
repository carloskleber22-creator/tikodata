import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Absolute, so the FastAPI process and the Streamlit process resolve to the
# same file regardless of which directory each one was launched from
# (bit us on the Mercadata project — same fix applied here from the start).
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_URL = f"sqlite:///{BASE_DIR / 'tikodata.db'}"


def _get(key: str, default: str = "") -> str:
    """os.getenv first (FastAPI/.env locally), falling back to Streamlit
    Cloud's st.secrets when running inside Streamlit — plain env vars alone
    weren't reliably populated from secrets.toml on Streamlit Community
    Cloud (same issue that first showed up with the demo login gate)."""
    value = os.getenv(key)
    if value:
        return value
    try:
        import streamlit as st

        return st.secrets.get(key, default)
    except Exception:
        return default


class Settings:
    tt_app_key: str = _get("TT_APP_KEY")
    tt_app_secret: str = _get("TT_APP_SECRET")
    tt_service_id: str = _get("TT_SERVICE_ID")
    tt_redirect_uri: str = _get("TT_REDIRECT_URI", "https://lvh.me:8000/oauth/callback")
    # ROW = rest of world (não-US). Troque para True se seu app TikTok Shop for do mercado US.
    tt_us_market: bool = _get("TT_US_MARKET", "false").lower() == "true"

    # App SEPARADO em developers.tiktok.com (TikTok for Developers), não tem
    # relação com o app do TikTok Shop Partner Center acima. Precisa de
    # aprovação específica para a Commercial Content API (ver README).
    adlib_client_key: str = _get("ADLIB_CLIENT_KEY")
    adlib_client_secret: str = _get("ADLIB_CLIENT_SECRET")

    # App na Shopee Open Platform (open.shopee.com), tipo "Third-party Partner
    # Platform" — candidatura em avaliação (ver README). partner_id/partner_key
    # só existem depois que a Shopee cria o App dentro do perfil aprovado.
    shopee_partner_id: str = _get("SHOPEE_PARTNER_ID")
    shopee_partner_key: str = _get("SHOPEE_PARTNER_KEY")
    shopee_redirect_uri: str = _get("SHOPEE_REDIRECT_URI", "https://lvh.me:8000/shopee/oauth/callback")
    # BR usa domínio próprio, diferente do resto do mundo — ver Descobertas no README.
    shopee_api_host: str = _get("SHOPEE_API_HOST", "https://openplatform.shopee.com.br")
    shopee_auth_host: str = _get("SHOPEE_AUTH_HOST", "https://open.shopee.com.br")

    database_url: str = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

    # Portão de login opcional — só ativo se as duas vars estiverem setadas (ex: nos
    # secrets do deploy público), pra satisfazer campos de "conta de teste" de
    # formulários de parceiro (Shopee ISV etc.). Vazio localmente = sem login.
    demo_login_username: str = _get("DEMO_LOGIN_USERNAME")
    demo_login_password: str = _get("DEMO_LOGIN_PASSWORD")

    # Credenciais de UMA loja real do TikTok Shop, pra "importar" ela pro banco
    # efêmero do deploy público sem precisar do backend FastAPI local rodando
    # publicamente — o próprio Streamlit Cloud consegue renovar o token e
    # sincronizar pedidos direto via API. Preenchido só nos secrets do deploy
    # público, nunca commitado. Ver dashboard/_theme.py::import_real_seller_once.
    tt_real_open_id: str = _get("TT_REAL_OPEN_ID")
    tt_real_seller_name: str = _get("TT_REAL_SELLER_NAME")
    tt_real_seller_region: str = _get("TT_REAL_SELLER_REGION")
    tt_real_shop_id: str = _get("TT_REAL_SHOP_ID")
    tt_real_shop_cipher: str = _get("TT_REAL_SHOP_CIPHER")
    tt_real_shop_name: str = _get("TT_REAL_SHOP_NAME")
    tt_real_access_token: str = _get("TT_REAL_ACCESS_TOKEN")
    tt_real_refresh_token: str = _get("TT_REAL_REFRESH_TOKEN")
    tt_real_access_token_expires_at: str = _get("TT_REAL_ACCESS_TOKEN_EXPIRES_AT")
    tt_real_refresh_token_expires_at: str = _get("TT_REAL_REFRESH_TOKEN_EXPIRES_AT")


settings = Settings()
