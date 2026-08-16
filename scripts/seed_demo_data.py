"""
Popula o banco com uma conta demo + ~90 dias de pedidos fake, só para
desenvolver e testar o visual do dashboard sem depender do TikTok liberar
a conta de verdade. Roda de forma independente da API do TikTok Shop.

Uso:
    source .venv/bin/activate && python3 scripts/seed_demo_data.py [--reset]
"""
import argparse
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import SessionLocal, init_db
from app.models import SellerAccount, Order, ShopeeAccount, ShopeeOrder

DEMO_OPEN_ID = "demo-0000000000"
DEMO_SHOPEE_SHOP_ID = "000000000"

PRODUCTS = [
    ("Fone Bluetooth TWS Pro", "Preto", 79.90, 38),
    ("Luminária LED Pôr do Sol", "Padrão", 49.90, 30),
    ("Mini Ventilador Portátil USB", "Branco", 34.90, 26),
    ("Organizador de Cabos Magnético", "Kit 6un", 24.90, 18),
    ("Escova Alisadora Iônica", "Rosa", 119.90, 16),
    ("Suporte de Celular Articulado", "Preto", 29.90, 14),
    ("Capinha Transparente Anti-Impacto", "Diversos modelos", 19.90, 12),
    ("Relógio Smartwatch Fitness", "Preto", 149.90, 9),
    ("Colar Magnético Anti-Ronco", "Prata", 22.90, 8),
    ("Óculos de Sol Polarizado", "Preto fosco", 39.90, 6),
    ("Kit Miçangas para Cabelo", "Colorido", 14.90, 5),
    ("Espremedor de Alho Manual", "Aço inox", 18.90, 4),
]


def _build_order_rows(days: int, seed: int) -> list:
    """Gera linhas de pedido genéricas (dict) — cada seeder por plataforma
    (TikTok Shop, Shopee) transforma essas linhas no seu próprio modelo ORM,
    já que os dois têm campos e nomes de tabela diferentes."""
    rng = random.Random(seed)
    rows = []
    today = datetime.utcnow().date()
    order_seq = 0

    for day_offset in range(days, -1, -1):
        day = today - timedelta(days=day_offset)
        weekday = day.weekday()
        weekend_boost = 1.35 if weekday >= 5 else 1.0
        growth = 1.0 + (days - day_offset) / days * 0.6  # tendência de crescimento
        base_orders_today = rng.randint(6, 14)
        n_orders = max(1, round(base_orders_today * weekend_boost * growth))

        for _ in range(n_orders):
            order_seq += 1
            hour = rng.randint(8, 23)
            minute = rng.randint(0, 59)
            create_time = datetime(day.year, day.month, day.day, hour, minute)

            weights = [w for *_, w in PRODUCTS]
            product_name, sku_name, price, _ = rng.choices(PRODUCTS, weights=weights, k=1)[0]
            quantity = rng.choices([1, 2, 3], weights=[75, 20, 5], k=1)[0]

            rows.append({
                "order_seq": order_seq,
                "create_time": create_time,
                "product_name": product_name,
                "sku_name": sku_name,
                "price": price,
                "quantity": quantity,
            })
    return rows


def build_orders(seller_id: int, days: int, seed: int):
    return [
        Order(
            seller_account_id=seller_id,
            tt_order_id=f"DEMO{row['order_seq']:06d}",
            product_name=row["product_name"],
            sku_name=row["sku_name"],
            quantity=row["quantity"],
            sale_price=row["price"],
            total_amount=round(row["quantity"] * row["price"], 2),
            currency="BRL",
            status="COMPLETED",
            create_time=row["create_time"],
        )
        for row in _build_order_rows(days, seed)
    ]


def build_shopee_orders(shopee_account_id: int, days: int, seed: int):
    return [
        ShopeeOrder(
            shopee_account_id=shopee_account_id,
            order_sn=f"DEMOSHOPEE{row['order_seq']:06d}",
            product_name=row["product_name"],
            quantity=row["quantity"],
            total_amount=round(row["quantity"] * row["price"], 2),
            currency="BRL",
            order_status="COMPLETED",
            create_time=row["create_time"],
        )
        # seed diferente do TikTok pra não gerar a mesma série de números exata
        for row in _build_order_rows(days, seed + 1)
    ]


def seed_demo_data(days: int = 90, reset: bool = False) -> str:
    """Cria (ou reaproveita) a conta demo com pedidos de exemplo. Usada tanto pelo
    CLI (`python3 scripts/seed_demo_data.py`) quanto pelo botão de prévia da Home
    no deploy público, onde não há acesso a terminal pra rodar o script."""
    init_db()
    with SessionLocal() as db:
        seller = db.query(SellerAccount).filter(SellerAccount.open_id == DEMO_OPEN_ID).one_or_none()

        if seller and reset:
            db.query(Order).filter(Order.seller_account_id == seller.id).delete()
            db.delete(seller)
            db.commit()
            seller = None

        if seller is None:
            seller = SellerAccount(
                open_id=DEMO_OPEN_ID,
                seller_name="[DEMO] Loja Exemplo",
                seller_base_region="BR",
                shop_id="demo-shop",
                shop_cipher="demo-cipher-not-real",
                shop_name="[DEMO] Loja Exemplo TikTok Shop",
                access_token="DEMO_NO_REAL_TOKEN",
                refresh_token="DEMO_NO_REAL_TOKEN",
                access_token_expires_at=datetime.utcnow() + timedelta(days=3650),
                refresh_token_expires_at=datetime.utcnow() + timedelta(days=3650),
            )
            db.add(seller)
            db.commit()
            db.refresh(seller)
        else:
            existing_orders = db.query(Order).filter(Order.seller_account_id == seller.id).count()
            if existing_orders:
                return f"Conta demo já tem {existing_orders} pedidos. Use --reset para recriar."

        orders = build_orders(seller.id, days, seed=42)
        db.add_all(orders)
        db.commit()
        return f"Conta demo '{seller.seller_name}' (id={seller.id}) com {len(orders)} pedidos de exemplo criada."


def seed_shopee_demo_data(days: int = 90, reset: bool = False) -> str:
    """Equivalente ao seed_demo_data acima, mas para a loja Shopee — mesma
    razão de existir: testar o visual sem depender da aprovação da candidatura
    ISV (ver README)."""
    init_db()
    with SessionLocal() as db:
        account = db.query(ShopeeAccount).filter(ShopeeAccount.shop_id == DEMO_SHOPEE_SHOP_ID).one_or_none()

        if account and reset:
            db.query(ShopeeOrder).filter(ShopeeOrder.shopee_account_id == account.id).delete()
            db.delete(account)
            db.commit()
            account = None

        if account is None:
            account = ShopeeAccount(
                shop_id=DEMO_SHOPEE_SHOP_ID,
                shop_name="[DEMO] Loja Exemplo Shopee",
                region="BR",
                access_token="DEMO_NO_REAL_TOKEN",
                refresh_token="DEMO_NO_REAL_TOKEN",
                access_token_expires_at=datetime.utcnow() + timedelta(days=3650),
            )
            db.add(account)
            db.commit()
            db.refresh(account)
        else:
            existing_orders = db.query(ShopeeOrder).filter(ShopeeOrder.shopee_account_id == account.id).count()
            if existing_orders:
                return f"Conta demo Shopee já tem {existing_orders} pedidos. Use reset para recriar."

        orders = build_shopee_orders(account.id, days, seed=42)
        db.add_all(orders)
        db.commit()
        return f"Conta demo '{account.shop_name}' (id={account.id}) com {len(orders)} pedidos de exemplo criada."


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Apaga dados demo existentes antes de recriar.")
    parser.add_argument("--days", type=int, default=90, help="Quantos dias de histórico gerar (padrão: 90).")
    args = parser.parse_args()
    print(seed_demo_data(days=args.days, reset=args.reset))
    print(seed_shopee_demo_data(days=args.days, reset=args.reset))


if __name__ == "__main__":
    main()
