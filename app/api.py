from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db, init_db
from app.tt_client import tt_client, TikTokShopAPIError
from app.adlib_client import AdLibraryAPIError
from app.shopee_client import shopee_client, ShopeeAPIError
from app.models import SellerAccount, ShopeeAccount
from app.services import sales_dashboard, ad_library, marketplace_intel, shopee_sales
from app.aios.router import router as aios_router

app = FastAPI(title="Tikodata API", description="Dashboard de vendas da sua própria loja TikTok Shop + AI OS")

# Camada de orquestração de IA (supervisor + provedores + ferramentas) — ver app/aios/.
app.include_router(aios_router)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/")
def health():
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# OAuth — autoriza o app a ler dados de vendas da loja
# --------------------------------------------------------------------------- #
@app.get("/oauth/login")
def oauth_login():
    return RedirectResponse(tt_client.get_authorization_url())


@app.get("/oauth/callback")
def oauth_callback(code: str, db: Session = Depends(get_db)):
    try:
        token = tt_client.get_access_token(code)
        shops = tt_client.get_authorized_shops(token["access_token"])
    except TikTokShopAPIError as e:
        raise HTTPException(status_code=400, detail=f"{e.code}: {e.message}")

    shop_list = shops.get("shops", [])
    shop = shop_list[0] if shop_list else {}

    seller = db.query(SellerAccount).filter(SellerAccount.open_id == token["open_id"]).one_or_none()
    if seller is None:
        seller = SellerAccount(open_id=token["open_id"])
        db.add(seller)

    seller.seller_name = token.get("seller_name", "")
    seller.seller_base_region = token.get("seller_base_region", "")
    seller.access_token = token["access_token"]
    seller.refresh_token = token["refresh_token"]
    seller.access_token_expires_at = token["access_token_expire_at"]
    seller.refresh_token_expires_at = token["refresh_token_expire_at"]
    seller.shop_id = shop.get("id")
    seller.shop_cipher = shop.get("cipher")
    seller.shop_name = shop.get("name", "")
    db.commit()
    db.refresh(seller)

    return {
        "connected": True,
        "seller_account_id": seller.id,
        "seller_name": seller.seller_name,
        "shop_name": seller.shop_name,
    }


# --------------------------------------------------------------------------- #
# OAuth Shopee — app separado, credenciais de app só existem após a Shopee
# aprovar a candidatura ISV (ver README, "Status atual — Shopee").
# --------------------------------------------------------------------------- #
@app.get("/shopee/oauth/login")
def shopee_oauth_login():
    return RedirectResponse(shopee_client.get_authorization_url())


@app.get("/shopee/oauth/callback")
def shopee_oauth_callback(code: str, shop_id: str, db: Session = Depends(get_db)):
    try:
        token = shopee_client.get_access_token(code, shop_id)
        shop_info = shopee_client.get_shop_info(token["response"]["access_token"], shop_id)
    except ShopeeAPIError as e:
        raise HTTPException(status_code=400, detail=f"{e.error_code}: {e.message}")

    token_data = token["response"]
    account = db.query(ShopeeAccount).filter(ShopeeAccount.shop_id == shop_id).one_or_none()
    if account is None:
        account = ShopeeAccount(shop_id=shop_id)
        db.add(account)

    account.shop_name = shop_info.get("response", {}).get("shop_name", "")
    account.region = shop_info.get("response", {}).get("region", "")
    account.access_token = token_data["access_token"]
    account.refresh_token = token_data["refresh_token"]
    account.access_token_expires_at = datetime.utcnow() + timedelta(seconds=token_data.get("expire_in", 14400))
    db.commit()
    db.refresh(account)

    return {"connected": True, "shopee_account_id": account.id, "shop_name": account.shop_name}


@app.post("/api/shopee/sync/{shopee_account_id}")
def shopee_sync(shopee_account_id: int, db: Session = Depends(get_db)):
    account = db.query(ShopeeAccount).filter(ShopeeAccount.id == shopee_account_id).one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Shopee account not found")
    try:
        saved = shopee_sales.sync_orders(db, account)
    except ShopeeAPIError as e:
        raise HTTPException(status_code=400, detail=f"{e.error_code}: {e.message}")
    return {"items_saved": saved}


@app.get("/api/sellers")
def list_sellers(db: Session = Depends(get_db)):
    sellers = db.query(SellerAccount).all()
    return [
        {"id": s.id, "seller_name": s.seller_name, "shop_name": s.shop_name, "open_id": s.open_id}
        for s in sellers
    ]


# --------------------------------------------------------------------------- #
# Dashboard de vendas
# --------------------------------------------------------------------------- #
@app.post("/api/sales/sync/{seller_account_id}")
def sales_sync(seller_account_id: int, db: Session = Depends(get_db)):
    seller = db.query(SellerAccount).filter(SellerAccount.id == seller_account_id).one_or_none()
    if seller is None:
        raise HTTPException(status_code=404, detail="Seller not found")
    try:
        saved = sales_dashboard.sync_orders(db, seller)
    except TikTokShopAPIError as e:
        raise HTTPException(status_code=400, detail=f"{e.code}: {e.message}")
    return {"items_saved": saved}


@app.get("/api/sales/summary/{seller_account_id}")
def sales_summary(seller_account_id: int, days: int = 30, db: Session = Depends(get_db)):
    summary = sales_dashboard.get_sales_summary(
        db, seller_account_id, datetime.utcnow() - timedelta(days=days), datetime.utcnow()
    )
    return {
        "revenue": summary["revenue"],
        "units": summary["units"],
        "by_day": summary["by_day"].to_dict(orient="records"),
        "top_products": summary["top_products"].to_dict(orient="records"),
    }


# --------------------------------------------------------------------------- #
# Ad Library (Commercial Content API) — anúncios de concorrentes, só Europa.
# App de credenciais client_credentials — não depende de nenhuma loja conectada.
# --------------------------------------------------------------------------- #
@app.get("/api/adlib/search")
def adlib_search(search_term: str, country_code: str = "", max_count: int = 20, db: Session = Depends(get_db)):
    try:
        token = ad_library.get_client_token()
        saved = ad_library.search_and_track(db, token, search_term, country_code or None, max_count)
    except AdLibraryAPIError as e:
        raise HTTPException(status_code=400, detail=str(e.payload))
    return {"ads_saved": saved}


@app.get("/api/adlib/ads")
def adlib_list(search_term: str = "", db: Session = Depends(get_db)):
    return ad_library.list_tracked_ads(db, search_term or None).to_dict(orient="records")


# --------------------------------------------------------------------------- #
# Pesquisa de mercado (Affiliate Seller API) — criadores e produtos de
# QUALQUER loja, via shop_cipher + access_token da própria loja conectada.
# --------------------------------------------------------------------------- #
def _get_connected_seller(seller_account_id: int, db: Session) -> SellerAccount:
    seller = db.query(SellerAccount).filter(SellerAccount.id == seller_account_id).one_or_none()
    if seller is None:
        raise HTTPException(status_code=404, detail="Seller not found")
    if not seller.shop_cipher:
        raise HTTPException(status_code=400, detail="Seller has no shop_cipher — reconnect via OAuth")
    return seller


@app.get("/api/marketplace/creators/search")
def marketplace_creators_search(seller_account_id: int, keyword: str, max_count: int = 20, db: Session = Depends(get_db)):
    seller = _get_connected_seller(seller_account_id, db)
    try:
        saved = marketplace_intel.search_and_track_creators(db, seller.access_token, seller.shop_cipher, keyword, max_count)
    except TikTokShopAPIError as e:
        raise HTTPException(status_code=400, detail=f"{e.code}: {e.message}")
    return {"creators_saved": saved}


@app.get("/api/marketplace/creators")
def marketplace_creators_list(keyword: str = "", db: Session = Depends(get_db)):
    return marketplace_intel.list_tracked_creators(db, keyword or None).to_dict(orient="records")


@app.get("/api/marketplace/products/search")
def marketplace_products_search(seller_account_id: int, keyword: str, max_count: int = 20, db: Session = Depends(get_db)):
    seller = _get_connected_seller(seller_account_id, db)
    try:
        saved = marketplace_intel.search_and_track_products(db, seller.access_token, seller.shop_cipher, keyword, max_count)
    except TikTokShopAPIError as e:
        raise HTTPException(status_code=400, detail=f"{e.code}: {e.message}")
    return {"products_saved": saved}


@app.get("/api/marketplace/products")
def marketplace_products_list(keyword: str = "", db: Session = Depends(get_db)):
    return marketplace_intel.list_tracked_products(db, keyword or None).to_dict(orient="records")
