"""
Pesquisa de mercado via TikTok Shop Affiliate Seller API — criadores e
produtos de QUALQUER loja aberta a colaboração de afiliados, não só a
própria. Confirmado contra a doc oficial em 2026-08-16 (partner.tiktokshop.com
/docv2 > Affiliate seller). Requer shop_cipher + access_token da própria loja
conectada (o mesmo OAuth do Dashboard de Vendas) — não é acesso anônimo, mas
os resultados cobrem o marketplace inteiro, não só o catálogo da sua loja.
"""
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models import MarketplaceCreator, MarketplaceProduct
from app.tt_client import tt_client


def search_and_track_creators(
    db: Session,
    access_token: str,
    shop_cipher: str,
    keyword: str,
    max_count: int = 20,
    gmv_ranges: Optional[list] = None,
    units_sold_ranges: Optional[list] = None,
) -> int:
    data = tt_client.search_marketplace_creators(
        access_token, shop_cipher, keyword=keyword, gmv_ranges=gmv_ranges,
        units_sold_ranges=units_sold_ranges, page_size=20,
    )
    creators = data.get("creators", [])[:max_count]

    saved = 0
    for c in creators:
        username = c.get("username", "")
        existing = (
            db.query(MarketplaceCreator)
            .filter(MarketplaceCreator.username == username, MarketplaceCreator.search_keyword == keyword)
            .one_or_none()
        )
        if existing is None:
            existing = MarketplaceCreator(username=username, search_keyword=keyword)
            db.add(existing)

        gmv = c.get("gmv") or {}
        existing.nickname = c.get("nickname", "")
        existing.avatar_url = (c.get("avatar") or {}).get("url", "")
        existing.follower_count = c.get("follower_count", 0)
        existing.gmv_amount = float(gmv.get("amount") or 0)
        existing.gmv_currency = gmv.get("currency", "")
        existing.category_ids = ",".join(c.get("category_ids") or [])
        existing.region = c.get("selection_region", "")
        existing.captured_at = datetime.utcnow()
        saved += 1

    db.commit()
    return saved


def list_tracked_creators(db: Session, search_keyword: Optional[str] = None) -> pd.DataFrame:
    query = db.query(MarketplaceCreator)
    if search_keyword:
        query = query.filter(MarketplaceCreator.search_keyword == search_keyword)

    rows = [
        {
            "username": c.username,
            "nickname": c.nickname or c.username,
            "avatar_url": c.avatar_url,
            "follower_count": c.follower_count,
            "gmv_amount": c.gmv_amount,
            "gmv_currency": c.gmv_currency or "USD",
            "region": c.region or "—",
        }
        for c in query.order_by(MarketplaceCreator.captured_at.desc()).all()
    ]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("gmv_amount", ascending=False).reset_index(drop=True)
    return df


def search_and_track_products(
    db: Session,
    access_token: str,
    shop_cipher: str,
    keyword: str,
    max_count: int = 20,
    sort_field: str = "units_sold",
    sort_order: str = "DESC",
    commission_rate_range: Optional[dict] = None,
) -> int:
    data = tt_client.search_open_collaboration_products(
        access_token, shop_cipher, title_keywords=[keyword] if keyword else None,
        sort_field=sort_field, sort_order=sort_order, commission_rate_range=commission_rate_range,
        page_size=20,
    )
    products = data.get("products", [])[:max_count]

    saved = 0
    for p in products:
        tt_product_id = str(p.get("id"))
        existing = (
            db.query(MarketplaceProduct)
            .filter(MarketplaceProduct.tt_product_id == tt_product_id, MarketplaceProduct.search_keyword == keyword)
            .one_or_none()
        )
        if existing is None:
            existing = MarketplaceProduct(tt_product_id=tt_product_id, search_keyword=keyword)
            db.add(existing)

        price = p.get("sales_price") or {}
        commission = p.get("commission") or {}
        category_chains = p.get("category_chains") or []

        existing.title = p.get("title", "")
        existing.shop_name = (p.get("shop") or {}).get("name", "")
        existing.main_image_url = p.get("main_image_url", "")
        existing.detail_link = p.get("detail_link", "")
        existing.units_sold = p.get("units_sold", 0)
        existing.price_min = float(price.get("minimum_amount") or 0)
        existing.price_max = float(price.get("maximum_amount") or 0)
        existing.currency = price.get("currency", "")
        existing.commission_rate = commission.get("rate", 0)
        existing.category_name = category_chains[0].get("local_name", "") if category_chains else ""
        existing.captured_at = datetime.utcnow()
        saved += 1

    db.commit()
    return saved


def list_tracked_products(db: Session, search_keyword: Optional[str] = None) -> pd.DataFrame:
    query = db.query(MarketplaceProduct)
    if search_keyword:
        query = query.filter(MarketplaceProduct.search_keyword == search_keyword)

    rows = [
        {
            "title": p.title,
            "shop_name": p.shop_name or "(loja não informada)",
            "main_image_url": p.main_image_url,
            "detail_link": p.detail_link,
            "units_sold": p.units_sold,
            "price_min": p.price_min,
            "price_max": p.price_max,
            "currency": p.currency or "USD",
            "commission_pct": p.commission_rate / 100,
            "category_name": p.category_name or "—",
        }
        for p in query.order_by(MarketplaceProduct.captured_at.desc()).all()
    ]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("units_sold", ascending=False).reset_index(drop=True)
    return df


def demo_creators_preview() -> pd.DataFrame:
    """Prévia estática (não vem de API nenhuma) pra página não ficar 100% vazia
    enquanto nenhuma loja real está conectada — mesmo formato de list_tracked_creators."""
    return pd.DataFrame([
        {"username": "exemplo.criador1", "nickname": "Criador Exemplo 1", "avatar_url": "",
         "follower_count": 182_000, "gmv_amount": 45_200.0, "gmv_currency": "USD", "region": "BR"},
        {"username": "exemplo.criador2", "nickname": "Criador Exemplo 2", "avatar_url": "",
         "follower_count": 54_300, "gmv_amount": 12_800.0, "gmv_currency": "USD", "region": "BR"},
        {"username": "exemplo.criador3", "nickname": "Criador Exemplo 3", "avatar_url": "",
         "follower_count": 9_100, "gmv_amount": 640.0, "gmv_currency": "USD", "region": "BR"},
    ])


def demo_products_preview() -> pd.DataFrame:
    """Prévia estática (não vem de API nenhuma) pra página não ficar 100% vazia
    enquanto nenhuma loja real está conectada — mesmo formato de list_tracked_products."""
    return pd.DataFrame([
        {"title": "Produto exemplo — fone bluetooth", "shop_name": "Loja Exemplo A", "main_image_url": "",
         "detail_link": "", "units_sold": 4_300, "price_min": 39.9, "price_max": 39.9, "currency": "USD",
         "commission_pct": 12.0, "category_name": "Eletrônicos"},
        {"title": "Produto exemplo — creme facial", "shop_name": "Loja Exemplo B", "main_image_url": "",
         "detail_link": "", "units_sold": 1_120, "price_min": 24.9, "price_max": 29.9, "currency": "USD",
         "commission_pct": 18.0, "category_name": "Beleza"},
    ])
