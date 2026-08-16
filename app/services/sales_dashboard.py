"""Dashboard de vendas — dados da própria loja TikTok Shop autorizada via OAuth."""
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.tt_client import tt_client
from app.models import SellerAccount, Order


def ensure_fresh_token(db: Session, seller: SellerAccount) -> SellerAccount:
    """Renova o access_token do vendedor se estiver perto de expirar (validade padrão: 7 dias)."""
    if seller.access_token_expires_at > datetime.utcnow() + timedelta(minutes=10):
        return seller

    data = tt_client.refresh_access_token(seller.refresh_token)
    seller.access_token = data["access_token"]
    seller.refresh_token = data["refresh_token"]
    seller.access_token_expires_at = data["access_token_expire_at"]
    seller.refresh_token_expires_at = data["refresh_token_expire_at"]
    db.commit()
    return seller


def sync_orders(db: Session, seller: SellerAccount, max_pages: int = 20) -> int:
    """Busca pedidos da loja autorizada e grava localmente. Retorna quantos itens foram gravados."""
    seller = ensure_fresh_token(db, seller)
    if not seller.shop_cipher:
        raise ValueError("Conta sem shop_cipher — reconecte a conta para obter a loja autorizada.")

    saved = 0
    page_token = None
    for _ in range(max_pages):
        page = tt_client.search_orders(seller.access_token, seller.shop_cipher, page_token=page_token)
        order_list = page.get("orders", [])
        if not order_list:
            break

        for order in order_list:
            tt_order_id = str(order["id"])
            existing = db.query(Order).filter(Order.tt_order_id == tt_order_id).first()
            if existing:
                continue

            create_time = datetime.utcfromtimestamp(order.get("create_time", 0))
            status = order.get("status", "")
            payment = order.get("payment") or {}
            currency = payment.get("currency", "")
            order_total = float(payment.get("total_amount") or 0)

            # NOTE: the official docs' example response for Get Order List is
            # truncated before reaching per-product data, so the exact shape
            # of a line-item entry (field names below) is a best guess based
            # on common TikTok Shop API conventions — verify against a real
            # response and adjust before relying on per-product numbers.
            # payment.total_amount (order-level) IS confirmed by the docs, so
            # we fall back to one synthetic row per order using that figure
            # if line_items is missing/empty, to avoid silently losing revenue.
            line_items = order.get("line_items") or []
            if not line_items:
                line_items = [{"product_name": "(detalhe de produto indisponível)", "sku_name": "", "sale_price": order_total}]

            for item in line_items:
                quantity = int(item.get("quantity") or 1)
                sale_price = float(item.get("sale_price") or item.get("original_price") or 0)
                db.add(
                    Order(
                        seller_account_id=seller.id,
                        tt_order_id=tt_order_id,
                        product_name=item.get("product_name", ""),
                        sku_name=item.get("sku_name", ""),
                        quantity=quantity,
                        sale_price=sale_price,
                        total_amount=quantity * sale_price,
                        currency=currency,
                        status=status,
                        create_time=create_time,
                    )
                )
                saved += 1

        page_token = page.get("next_page_token")
        if not page_token:
            break

    db.commit()
    return saved


def get_sales_summary(db: Session, seller_account_id: int, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None) -> dict:
    query = db.query(Order).filter(Order.seller_account_id == seller_account_id)
    if date_from:
        query = query.filter(Order.create_time >= date_from)
    if date_to:
        query = query.filter(Order.create_time <= date_to)

    df = pd.DataFrame(
        [
            {
                "create_time": o.create_time,
                "product_name": o.product_name,
                "quantity": o.quantity,
                "total_amount": o.total_amount,
            }
            for o in query.all()
        ]
    )
    if df.empty:
        return {"revenue": 0.0, "units": 0, "avg_ticket": 0.0, "by_day": df, "top_products": df}

    by_day = df.groupby(df["create_time"].dt.date)["total_amount"].sum().reset_index()
    top_products = (
        df.groupby("product_name")
        .agg(units=("quantity", "sum"), revenue=("total_amount", "sum"))
        .sort_values("revenue", ascending=False)
        .reset_index()
    )

    # Série diária por produto, pra desenhar um sparkline ao lado de cada linha do ranking.
    df["date"] = df["create_time"].dt.date
    all_days = sorted(df["date"].unique())
    daily_by_product = df.groupby(["product_name", "date"])["total_amount"].sum()
    top_products["trend"] = top_products["product_name"].apply(
        lambda name: [float(daily_by_product.get((name, d), 0.0)) for d in all_days]
    )

    return {
        "revenue": float(df["total_amount"].sum()),
        "units": int(df["quantity"].sum()),
        "avg_ticket": float(df["total_amount"].sum() / df["quantity"].sum()) if df["quantity"].sum() else 0.0,
        "by_day": by_day,
        "top_products": top_products,
    }


def _pct_change(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None
    return (current - previous) / previous * 100


def get_period_comparison(db: Session, seller_account_id: int, days: int = 30) -> dict:
    """Resumo do período atual + delta % contra o período imediatamente anterior, de mesma duração."""
    now = datetime.utcnow()
    current = get_sales_summary(db, seller_account_id, now - timedelta(days=days), now)
    previous = get_sales_summary(db, seller_account_id, now - timedelta(days=2 * days), now - timedelta(days=days))

    return {
        "current": current,
        "previous": previous,
        "revenue_delta_pct": _pct_change(current["revenue"], previous["revenue"]),
        "units_delta_pct": _pct_change(current["units"], previous["units"]),
        "avg_ticket_delta_pct": _pct_change(current["avg_ticket"], previous["avg_ticket"]),
    }
