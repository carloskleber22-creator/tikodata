import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import plotly.express as px
import streamlit as st

from app.db import SessionLocal, init_db
from app.tt_client import TikTokShopAPIError
from app.models import SellerAccount
from app.services import sales_dashboard
from dashboard._theme import (
    SEQUENTIAL_BLUE,
    format_compact,
    inject_base_css,
    kalo_row,
    require_demo_login,
    stat_tile,
    style_layout,
)
from scripts.seed_demo_data import seed_demo_data

st.set_page_config(page_title="Dashboard de Vendas", page_icon="💰", layout="wide")
init_db()
inject_base_css()
require_demo_login()

st.title("💰 Dashboard de Vendas")
st.caption("Receita e unidades vendidas da sua própria loja no TikTok Shop (requer conexão OAuth).")

with SessionLocal() as db:
    sellers = db.query(SellerAccount).all()

if not sellers:
    st.warning(
        "Nenhuma loja conectada. Rode a API (`uvicorn app.api:app --reload --ssl-keyfile "
        "certs/localhost-key.pem --ssl-certfile certs/localhost.pem`) e acesse "
        "https://lvh.me:8000/oauth/login para conectar sua loja do TikTok Shop."
    )
    if st.button("🧪 Popular com dados de exemplo"):
        st.success(seed_demo_data())
        st.rerun()
    st.stop()

col_a, col_b = st.columns([3, 2])
seller_map = {s.id: f"{s.seller_name or s.shop_name} (#{s.id})" for s in sellers}
seller_id = col_a.selectbox("Loja", options=list(seller_map.keys()), format_func=lambda i: seller_map[i])
with col_b:
    period_options = {"Ontem": 1, "7d": 7, "30d": 30, "90d": 90, "180d": 180}
    period_label = st.pills("Período", options=list(period_options.keys()), default="30d", key="sales_period")
    days = period_options.get(period_label, 30)

with SessionLocal() as db:
    seller = db.query(SellerAccount).filter(SellerAccount.id == seller_id).one()
    is_demo = seller.open_id == "demo-0000000000"

if is_demo:
    st.caption("🧪 Conta de demonstração — dados de exemplo gerados localmente, não vêm do TikTok Shop.")
elif st.button("Sincronizar pedidos", type="primary"):
    with st.spinner("Sincronizando pedidos com o TikTok Shop..."):
        with SessionLocal() as db:
            seller = db.query(SellerAccount).filter(SellerAccount.id == seller_id).one()
            try:
                saved = sales_dashboard.sync_orders(db, seller)
                st.success(f"{saved} itens de pedido sincronizados.")
            except (TikTokShopAPIError, ValueError) as e:
                st.error(f"Erro na API do TikTok Shop: {e}")

with SessionLocal() as db:
    comparison = sales_dashboard.get_period_comparison(db, seller_id, days=days)

current = comparison["current"]

revenue_trend = current["by_day"]["total_amount"].tolist() if not current["by_day"].empty else None

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(
        stat_tile(
            "Receita no período", f"R$ {format_compact(current['revenue'])}",
            comparison["revenue_delta_pct"], trend=revenue_trend,
        ),
        unsafe_allow_html=True,
    )
with col2:
    st.markdown(
        stat_tile("Unidades vendidas", format_compact(current["units"]), comparison["units_delta_pct"]),
        unsafe_allow_html=True,
    )
with col3:
    st.markdown(
        stat_tile("Ticket médio", f"R$ {current['avg_ticket']:.2f}", comparison["avg_ticket_delta_pct"]),
        unsafe_allow_html=True,
    )

st.write("")

if not current["by_day"].empty:
    st.subheader("Receita por dia")
    fig = px.bar(current["by_day"], x="create_time", y="total_amount", labels={"create_time": "", "total_amount": ""})
    fig.update_traces(marker_color=SEQUENTIAL_BLUE, marker_line_width=0)
    fig.update_yaxes(tickprefix="R$ ")
    style_layout(fig)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

st.subheader("Top produtos")
if current["top_products"].empty:
    st.info("Sem vendas sincronizadas ainda para esse período.")
else:
    top = current["top_products"].head(8)
    rows_html = "".join(
        kalo_row(
            i + 1, "", row["product_name"], f'{row["units"]:,} un.',
            "Receita", f'R$ {format_compact(row["revenue"])}', row["trend"], [],
        )
        for i, row in top.iterrows()
    )
    st.markdown(f'<div class="kalo-table">{rows_html}</div>', unsafe_allow_html=True)

    with st.expander("Ver tabela completa"):
        st.dataframe(
            current["top_products"][["product_name", "units", "revenue"]],
            use_container_width=True,
            hide_index=True,
        )
