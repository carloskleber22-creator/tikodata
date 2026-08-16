import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Absolute, so the FastAPI process and the Streamlit process resolve to the
# same file regardless of which directory each one was launched from
# (bit us on the Mercadata project — same fix applied here from the start).
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_URL = f"sqlite:///{BASE_DIR / 'tikodata.db'}"


class Settings:
    tt_app_key: str = os.getenv("TT_APP_KEY", "")
    tt_app_secret: str = os.getenv("TT_APP_SECRET", "")
    tt_service_id: str = os.getenv("TT_SERVICE_ID", "")
    tt_redirect_uri: str = os.getenv("TT_REDIRECT_URI", "https://lvh.me:8000/oauth/callback")
    # ROW = rest of world (não-US). Troque para True se seu app TikTok Shop for do mercado US.
    tt_us_market: bool = os.getenv("TT_US_MARKET", "false").lower() == "true"

    # App SEPARADO em developers.tiktok.com (TikTok for Developers), não tem
    # relação com o app do TikTok Shop Partner Center acima. Precisa de
    # aprovação específica para a Commercial Content API (ver README).
    adlib_client_key: str = os.getenv("ADLIB_CLIENT_KEY", "")
    adlib_client_secret: str = os.getenv("ADLIB_CLIENT_SECRET", "")

    # App na Shopee Open Platform (open.shopee.com), tipo "Third-party Partner
    # Platform" — candidatura em avaliação (ver README). partner_id/partner_key
    # só existem depois que a Shopee cria o App dentro do perfil aprovado.
    shopee_partner_id: str = os.getenv("SHOPEE_PARTNER_ID", "")
    shopee_partner_key: str = os.getenv("SHOPEE_PARTNER_KEY", "")
    shopee_redirect_uri: str = os.getenv("SHOPEE_REDIRECT_URI", "https://lvh.me:8000/shopee/oauth/callback")
    # BR usa domínio próprio, diferente do resto do mundo — ver Descobertas no README.
    shopee_api_host: str = os.getenv("SHOPEE_API_HOST", "https://openplatform.shopee.com.br")
    shopee_auth_host: str = os.getenv("SHOPEE_AUTH_HOST", "https://open.shopee.com.br")

    database_url: str = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

    # Portão de login opcional — só ativo se as duas vars estiverem setadas (ex: nos
    # secrets do deploy público), pra satisfazer campos de "conta de teste" de
    # formulários de parceiro (Shopee ISV etc.). Vazio localmente = sem login.
    demo_login_username: str = os.getenv("DEMO_LOGIN_USERNAME", "")
    demo_login_password: str = os.getenv("DEMO_LOGIN_PASSWORD", "")


settings = Settings()
