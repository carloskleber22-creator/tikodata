import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import SellerAccount
from app.services import sales_dashboard
from dashboard._theme import format_compact, inject_base_css, kalo_row, require_demo_login, stat_tile
from scripts.seed_demo_data import seed_demo_data

PAGES = {
    "pages/1_Dashboard de Vendas.py": ("💰", "Dashboard de Vendas", "Receita e unidades da sua loja"),
    "pages/2_Inspiracao de Criativos.py": ("🎨", "Inspiração de Criativos", "Criativos em alta (só Europa)"),
    "pages/3_Pesquisa de Mercado.py": ("🔎", "Pesquisa de Mercado", "Criadores e produtos de qualquer loja"),
}

st.set_page_config(page_title="Tikodata", page_icon="🎵", layout="wide")
init_db()
inject_base_css()
require_demo_login()

st.title("🎵 Tikodata")
st.caption("Dashboard de vendas da sua própria loja + inspiração de criativos via biblioteca oficial de anúncios do TikTok, sem raspagem.")

with st.expander("Por que os dados são limitados (sem raspagem)"):
    st.markdown(
        "Este projeto usa **só APIs oficiais do TikTok**: dados de vendas vêm apenas da **sua "
        "própria loja** (TikTok Shop Partner Center), e a inspiração de criativos usa a "
        "**Commercial Content API** — a biblioteca pública de transparência do TikTok, que só "
        "cobre anúncios veiculados na Europa e não tem gasto/engajamento. Como o Brasil não é "
        "coberto, o uso real é buscar por **categoria de produto** pra ver que tipo de criativo "
        "está pegando alcance lá fora, não achar concorrentes brasileiros específicos. "
        "Ferramentas como Kalodata/FastMoss/EchoTik/PiPiADS mostram mais porque raspam dados em "
        "larga escala, o que este projeto não faz."
    )

with SessionLocal() as db:
    sellers = db.query(SellerAccount).all()
has_real_seller = any(s.open_id != "demo-0000000000" for s in sellers)
adlib_configured = bool(settings.adlib_client_key and settings.adlib_client_secret)

st.subheader("Status")
status_lines = [
    "✅ Loja real conectada" if has_real_seller
    else "⏳ Aguardando loja real (bloqueado pela revisão de segurança/privacidade do TikTok Shop)",
    ("⚠️ Credenciais configuradas, mas a API tem retornado erro instável (500) do lado do TikTok"
     if adlib_configured else "⏳ Configure `ADLIB_CLIENT_KEY`/`ADLIB_CLIENT_SECRET` no `.env`"),
    "✅ Loja real conectada" if has_real_seller
    else "⏳ Aguardando a mesma loja real conectar (mesmo bloqueio do Dashboard de Vendas)",
]
for (icon, label, _), status in zip(PAGES.values(), status_lines):
    st.markdown(f"{icon} **{label}** — {status}")

st.subheader("Acesso rápido")
cols = st.columns(len(PAGES))
for col, (page_path, (icon, label, desc)) in zip(cols, PAGES.items()):
    with col:
        with st.container(border=True):
            st.page_link(page_path, label=f"{icon} **{label}**")
            st.caption(desc)

st.divider()

if not sellers:
    st.info("Nenhuma loja conectada ainda.")
    if st.button("🧪 Popular com dados de exemplo"):
        st.success(seed_demo_data())
        st.rerun()
else:
    now = datetime.utcnow()
    store_summaries = []
    with SessionLocal() as db:
        for s in sellers:
            summary = sales_dashboard.get_sales_summary(db, s.id, now - timedelta(days=30), now)
            store_summaries.append((s, summary))

    total_revenue = sum(summary["revenue"] for _, summary in store_summaries)
    total_units = sum(summary["units"] for _, summary in store_summaries)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(stat_tile("Lojas conectadas", str(len(sellers)), show_delta=False), unsafe_allow_html=True)
    with col2:
        st.markdown(stat_tile("Receita últimos 30 dias (todas as lojas)", f"R$ {format_compact(total_revenue)}", show_delta=False), unsafe_allow_html=True)
    with col3:
        st.markdown(stat_tile("Unidades vendidas (30 dias)", format_compact(total_units), show_delta=False), unsafe_allow_html=True)

    st.write("")
    st.subheader("Lojas conectadas")
    rows_html = "".join(
        kalo_row(
            "🧪" if s.open_id == "demo-0000000000" else "🛍️",
            "",
            s.shop_name or s.seller_name,
            s.seller_base_region or "—",
            "Receita",
            f'R$ {format_compact(summary["revenue"])}',
            summary["by_day"]["total_amount"].tolist() if not summary["by_day"].empty else [],
            [],
        )
        for s, summary in store_summaries
    )
    st.markdown(f'<div class="kalo-table">{rows_html}</div>', unsafe_allow_html=True)

st.write("")
col1, col2 = st.columns(2)
with col1:
    st.markdown("**Conectar loja real**")
    st.markdown(
        "Rode a API (`uvicorn app.api:app --reload --ssl-keyfile certs/localhost-key.pem "
        "--ssl-certfile certs/localhost.pem`) e acesse "
        "[https://lvh.me:8000/oauth/login](https://lvh.me:8000/oauth/login)."
    )
with col2:
    st.markdown("**Testar com dados de exemplo**")
    if st.button("🧪 Popular com dados de exemplo", key="seed_bottom"):
        st.success(seed_demo_data())
        st.rerun()
