"""Dashboard de vendas — dados da própria loja Shopee autorizada via OAuth.
Espelha sales_dashboard.py (TikTok Shop) de propósito — mesma lógica de
resumo/comparação de período, só a origem do dado muda."""
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.shopee_client import shopee_client
from app.models import ShopeeAccount, ShopeeOrder


def sync_orders(db: Session, account: ShopeeAccount, days: int = 90) -> int:
    """Busca pedidos da loja autorizada (últimos `days` dias) e grava localmente."""
    time_to = int(datetime.utcnow().timestamp())
    time_from = int((datetime.utcnow() - timedelta(days=days)).timestamp())

    saved = 0
    cursor = ""
    while True:
        page = shopee_client.get_order_list(
            account.access_token, account.shop_id, time_from, time_to, cursor=cursor
        )
        data = page.get("response", {})
        order_list = data.get("order_list", [])
        if not order_list:
            break

        order_sns = [o["order_sn"] for o in order_list if not db.query(ShopeeOrder).filter(ShopeeOrder.order_sn == o["order_sn"]).first()]
        if order_sns:
            detail_resp = shopee_client.get_order_detail(account.access_token, account.shop_id, order_sns)
            for order in detail_resp.get("response", {}).get("order_list", []):
                order_sn = order["order_sn"]
                create_time = datetime.utcfromtimestamp(order.get("create_time", 0))
                status = order.get("order_status", "")
                currency = order.get("currency", "")

                # NOTE: não confirmei o formato exato de item_list contra resposta
                # real (sem credencial ainda) — escrito de forma defensiva igual o
                # line_items do TikTok Shop, ajustar quando testar de verdade.
                items = order.get("item_list") or []
                if not items:
                    items = [{"item_name": "(detalhe de produto indisponível)", "model_quantity_purchased": 1,
                              "model_discounted_price": order.get("total_amount", 0)}]

                for item in items:
                    quantity = int(item.get("model_quantity_purchased") or 1)
                    price = float(item.get("model_discounted_price") or item.get("model_original_price") or 0)
                    db.add(
                        ShopeeOrder(
                            shopee_account_id=account.id,
                            order_sn=order_sn,
                            product_name=item.get("item_name", ""),
                            quantity=quantity,
                            total_amount=quantity * price,
                            currency=currency,
                            order_status=status,
                            create_time=create_time,
                        )
                    )
                    saved += 1

        cursor = data.get("next_cursor", "")
        if not data.get("more") or not cursor:
            break

    db.commit()
    return saved


def get_sales_summary(db: Session, shopee_account_id: int, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None) -> dict:
    query = db.query(ShopeeOrder).filter(ShopeeOrder.shopee_account_id == shopee_account_id)
    if date_from:
        query = query.filter(ShopeeOrder.create_time >= date_from)
    if date_to:
        query = query.filter(ShopeeOrder.create_time <= date_to)

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


def get_period_comparison(db: Session, shopee_account_id: int, days: int = 30) -> dict:
    now = datetime.utcnow()
    current = get_sales_summary(db, shopee_account_id, now - timedelta(days=days), now)
    previous = get_sales_summary(db, shopee_account_id, now - timedelta(days=2 * days), now - timedelta(days=days))

    return {
        "current": current,
        "previous": previous,
        "revenue_delta_pct": _pct_change(current["revenue"], previous["revenue"]),
        "units_delta_pct": _pct_change(current["units"], previous["units"]),
        "avg_ticket_delta_pct": _pct_change(current["avg_ticket"], previous["avg_ticket"]),
    }
