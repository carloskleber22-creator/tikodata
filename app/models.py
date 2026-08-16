from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class SellerAccount(Base):
    __tablename__ = "seller_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    open_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    seller_name: Mapped[str] = mapped_column(String(120), default="")
    seller_base_region: Mapped[str] = mapped_column(String(10), default="")
    shop_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    shop_cipher: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    shop_name: Mapped[str] = mapped_column(String(120), default="")
    access_token: Mapped[str] = mapped_column(String(255))
    refresh_token: Mapped[str] = mapped_column(String(255))
    access_token_expires_at: Mapped[datetime] = mapped_column(DateTime)
    refresh_token_expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    orders: Mapped[list["Order"]] = relationship(back_populates="seller")


class Order(Base):
    """One row per order line item — mirrors the sibling Mercado Livre project's shape."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_account_id: Mapped[int] = mapped_column(ForeignKey("seller_accounts.id"), index=True)
    tt_order_id: Mapped[str] = mapped_column(String(32), index=True)
    product_name: Mapped[str] = mapped_column(String(255), default="")
    sku_name: Mapped[str] = mapped_column(String(255), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    sale_price: Mapped[float] = mapped_column(Float, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="")
    status: Mapped[str] = mapped_column(String(40), default="")
    create_time: Mapped[datetime] = mapped_column(DateTime, index=True)

    seller: Mapped["SellerAccount"] = relationship(back_populates="orders")


class CompetitorAd(Base):
    """
    Um anúncio encontrado via TikTok Commercial Content API (Ad Library).
    Só cobre anúncios veiculados na Europa (EU/EEA/UK/Suíça) — ver
    adlib_client.SUPPORTED_COUNTRIES — e não tem gasto/engajamento, só
    alcance (reach) em faixas ("11K") e a peça criativa.
    """

    __tablename__ = "competitor_ads"
    __table_args__ = (UniqueConstraint("tt_ad_id", name="uq_competitor_ad_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tt_ad_id: Mapped[str] = mapped_column(String(32), index=True)
    search_term: Mapped[str] = mapped_column(String(120), default="", index=True)
    country_code: Mapped[str] = mapped_column(String(10), default="")
    advertiser_business_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    advertiser_name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="")
    first_shown_date: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    last_shown_date: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    reach_label: Mapped[str] = mapped_column(String(20), default="")  # ex.: "11K", vem assim da API
    thumbnail_url: Mapped[str] = mapped_column(String(1000), default="")
    video_url: Mapped[str] = mapped_column(String(1000), default="")
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ShopeeAccount(Base):
    """Loja Shopee conectada via OAuth — modelo separado do SellerAccount (TikTok
    Shop) porque os dois têm conceitos diferentes (shop_id da Shopee é numérico,
    não tem open_id/shop_cipher). Mesmo padrão de manter clientes/modelos por
    plataforma sem forçar abstração prematura entre eles."""

    __tablename__ = "shopee_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    shop_name: Mapped[str] = mapped_column(String(120), default="")
    region: Mapped[str] = mapped_column(String(10), default="")
    access_token: Mapped[str] = mapped_column(String(255))
    refresh_token: Mapped[str] = mapped_column(String(255))
    access_token_expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    orders: Mapped[list["ShopeeOrder"]] = relationship(back_populates="account")


class ShopeeOrder(Base):
    """Um pedido da Shopee (get_order_list + get_order_detail). Estrutura mais
    simples que o Order do TikTok Shop porque ainda não temos credencial real
    pra confirmar o formato exato de item_list — ajustar quando testar de
    verdade, mesma ressalva que já vale pro line_items do TikTok Shop."""

    __tablename__ = "shopee_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    shopee_account_id: Mapped[int] = mapped_column(ForeignKey("shopee_accounts.id"), index=True)
    order_sn: Mapped[str] = mapped_column(String(32), index=True)
    product_name: Mapped[str] = mapped_column(String(255), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="")
    order_status: Mapped[str] = mapped_column(String(40), default="")
    create_time: Mapped[datetime] = mapped_column(DateTime, index=True)

    account: Mapped["ShopeeAccount"] = relationship(back_populates="orders")


class MarketplaceCreator(Base):
    """
    Um criador encontrado via TikTok Shop Affiliate Seller API (Seller Search
    Creator on Marketplace) — qualquer criador do Creator Marketplace, não só
    os já conectados à loja. Precisa de shop_cipher + access_token da própria
    loja pra consultar, mas os resultados cobrem o marketplace inteiro.
    """

    __tablename__ = "marketplace_creators"
    __table_args__ = (UniqueConstraint("username", "search_keyword", name="uq_marketplace_creator"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(120), index=True)
    nickname: Mapped[str] = mapped_column(String(120), default="")
    search_keyword: Mapped[str] = mapped_column(String(120), default="", index=True)
    avatar_url: Mapped[str] = mapped_column(String(1000), default="")
    follower_count: Mapped[int] = mapped_column(Integer, default=0)
    gmv_amount: Mapped[float] = mapped_column(Float, default=0.0)
    gmv_currency: Mapped[str] = mapped_column(String(10), default="")
    category_ids: Mapped[str] = mapped_column(String(255), default="")
    region: Mapped[str] = mapped_column(String(10), default="")
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class MarketplaceProduct(Base):
    """
    Um produto encontrado via TikTok Shop Affiliate Seller API (Seller Search
    Affiliate Open Collaboration Product) — produtos de QUALQUER loja aberta a
    colaboração de afiliados, não só a própria. Mesma exigência de
    shop_cipher + access_token da própria loja pra consultar.
    """

    __tablename__ = "marketplace_products"
    __table_args__ = (UniqueConstraint("tt_product_id", "search_keyword", name="uq_marketplace_product"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tt_product_id: Mapped[str] = mapped_column(String(32), index=True)
    search_keyword: Mapped[str] = mapped_column(String(120), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    shop_name: Mapped[str] = mapped_column(String(255), default="")
    main_image_url: Mapped[str] = mapped_column(String(1000), default="")
    detail_link: Mapped[str] = mapped_column(String(1000), default="")
    units_sold: Mapped[int] = mapped_column(Integer, default=0)
    price_min: Mapped[float] = mapped_column(Float, default=0.0)
    price_max: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="")
    commission_rate: Mapped[int] = mapped_column(Integer, default=0)
    category_name: Mapped[str] = mapped_column(String(120), default="")
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
