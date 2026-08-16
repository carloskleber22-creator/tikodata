import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import streamlit as st

from app.db import SessionLocal, init_db
from app.models import SellerAccount
from app.tt_client import TikTokShopAPIError
from app.services import marketplace_intel
from dashboard._theme import inject_base_css, kalo_row

st.set_page_config(page_title="Pesquisa de Mercado", page_icon="🔎", layout="wide")
init_db()
inject_base_css()

st.title("🔎 Pesquisa de Mercado")
st.caption(
    "Criadores e produtos de QUALQUER loja no TikTok Shop, via Affiliate Seller API — a mesma "
    "API que serve o Creator Marketplace oficial do TikTok."
)
st.info(
    "**Não é raspagem**: a Affiliate Seller API expõe de propósito criadores do Creator "
    "Marketplace (com GMV, seguidores, categoria) e produtos que outras lojas abriram para "
    "colaboração de afiliados (com nome da loja, unidades vendidas, preço, comissão). Precisa "
    "de uma loja sua conectada via OAuth pra consultar (`shop_cipher` + `access_token`), mas os "
    "resultados cobrem o marketplace inteiro, não só o catálogo da sua loja."
)

with SessionLocal() as db:
    sellers = db.query(SellerAccount).filter(SellerAccount.open_id != "demo-0000000000").all()

if not sellers:
    st.warning(
        "Nenhuma loja real conectada ainda — a busca de verdade precisa de `shop_cipher`/"
        "`access_token` de uma loja real (dados de demonstração não servem aqui). Acesse "
        "https://lvh.me:8000/oauth/login pra conectar. Enquanto isso, veja como a tela fica com "
        "dados de exemplo:"
    )
    st.caption("🧪 Prévia com dados de exemplo — não vêm da API, só pra mostrar o layout")

    demo_tab_creators, demo_tab_products = st.tabs(["Criadores", "Produtos"])
    with demo_tab_creators:
        demo_creator_rows = "".join(
            kalo_row(
                i + 1, "", c["nickname"], f'@{c["username"]}', "GMV",
                f'{c["gmv_currency"]} {c["gmv_amount"]:,.0f}', None,
                [("Seguidores", f'{c["follower_count"]:,}'), ("Região", c["region"])], top=(i == 0),
            )
            for i, (_, c) in enumerate(marketplace_intel.demo_creators_preview().iterrows())
        )
        st.markdown(f'<div class="kalo-table">{demo_creator_rows}</div>', unsafe_allow_html=True)
    with demo_tab_products:
        demo_product_rows = "".join(
            kalo_row(
                i + 1, "", p["title"], p["shop_name"], "Vendidos", f'{p["units_sold"]:,}', None,
                [("Preço", f'{p["currency"]} {p["price_min"]:.0f}'), ("Comissão", f'{p["commission_pct"]:.1f}%'),
                 ("Categoria", p["category_name"])],
                top=(i == 0),
            )
            for i, (_, p) in enumerate(marketplace_intel.demo_products_preview().iterrows())
        )
        st.markdown(f'<div class="kalo-table">{demo_product_rows}</div>', unsafe_allow_html=True)

    st.stop()

seller_map = {s.id: f"{s.seller_name or s.shop_name} (#{s.id})" for s in sellers}
seller_id = st.selectbox("Loja usada para consultar", options=list(seller_map.keys()), format_func=lambda i: seller_map[i])

with SessionLocal() as db:
    seller = db.query(SellerAccount).filter(SellerAccount.id == seller_id).one()

tab_creators, tab_products = st.tabs(["Criadores", "Produtos"])

CREATOR_PRESETS = {
    "🌱 Emergentes": {"gmv_ranges": ["GMV_RANGE_0_100", "GMV_RANGE_100_1000"]},
    "🚀 Alto GMV": {"gmv_ranges": ["GMV_RANGE_10000_AND_ABOVE"]},
    "📦 Alto volume de vendas": {"units_sold_ranges": ["UNITS_SOLD_RANGE_1000_AND_ABOVE"]},
}

PRODUCT_PRESETS = {
    "🔥 Mais vendidos": {"sort_field": "units_sold", "sort_order": "DESC"},
    "💰 Maior comissão": {"sort_field": "commission_rate", "sort_order": "DESC"},
    "🏷️ Comissão acima de 20%": {"sort_field": "commission_rate", "sort_order": "DESC", "commission_rate_range": {"rate_ge": 2000, "rate_lt": 10000}},
}

with tab_creators:
    col1, col2 = st.columns([3, 1])
    creator_keyword = col1.text_input("Buscar criador por nome/usuário ou nicho", key="creator_kw")
    creator_max = col2.number_input("Qtd.", min_value=5, max_value=20, value=20, step=5, key="creator_max")
    creator_preset = st.pills("Atalhos", options=list(CREATOR_PRESETS.keys()), key="creator_preset")

    if st.button("Buscar criadores", type="primary", key="creator_btn"):
        if not creator_keyword:
            st.warning("Informe um termo de busca.")
        else:
            preset_kwargs = CREATOR_PRESETS.get(creator_preset, {})
            with st.spinner("Buscando criadores no marketplace..."):
                with SessionLocal() as db:
                    try:
                        saved = marketplace_intel.search_and_track_creators(
                            db, seller.access_token, seller.shop_cipher, creator_keyword, creator_max, **preset_kwargs
                        )
                        st.success(f"{saved} criadores encontrados e salvos.")
                    except TikTokShopAPIError as e:
                        st.error(f"Erro na API do TikTok Shop: {e.code} — {e.message}")

    st.divider()

    with SessionLocal() as db:
        creators = marketplace_intel.list_tracked_creators(db, creator_keyword or None)

    if creators.empty:
        st.info("Nenhum criador salvo ainda para esse termo. Faça uma busca acima.")
    else:
        st.subheader(f"{len(creators)} criadores, ordenados por GMV")
        rows_html = "".join(
            kalo_row(
                i + 1,
                c["avatar_url"],
                c["nickname"],
                f'@{c["username"]}',
                "GMV",
                f'{c["gmv_currency"]} {c["gmv_amount"]:,.0f}',
                None,
                [("Seguidores", f'{c["follower_count"]:,}'), ("Região", c["region"])],
                top=(i == 0),
            )
            for i, (_, c) in enumerate(creators.iterrows())
        )
        st.markdown(f'<div class="kalo-table">{rows_html}</div>', unsafe_allow_html=True)

        with st.expander("Ver tabela completa"):
            st.dataframe(
                creators[["nickname", "username", "follower_count", "gmv_amount", "gmv_currency", "region"]],
                use_container_width=True,
                hide_index=True,
            )

with tab_products:
    col1, col2 = st.columns([3, 1])
    product_keyword = col1.text_input("Buscar produto por palavra-chave", key="product_kw", placeholder="ex: skincare, fone bluetooth")
    product_max = col2.number_input("Qtd.", min_value=5, max_value=20, value=20, step=5, key="product_max")
    product_preset = st.pills("Atalhos", options=list(PRODUCT_PRESETS.keys()), key="product_preset", default="🔥 Mais vendidos")

    if st.button("Buscar produtos", type="primary", key="product_btn"):
        if not product_keyword:
            st.warning("Informe uma palavra-chave.")
        else:
            preset_kwargs = PRODUCT_PRESETS.get(product_preset, PRODUCT_PRESETS["🔥 Mais vendidos"])
            with st.spinner("Buscando produtos no marketplace..."):
                with SessionLocal() as db:
                    try:
                        saved = marketplace_intel.search_and_track_products(
                            db, seller.access_token, seller.shop_cipher, product_keyword, product_max, **preset_kwargs
                        )
                        st.success(f"{saved} produtos encontrados e salvos.")
                    except TikTokShopAPIError as e:
                        st.error(f"Erro na API do TikTok Shop: {e.code} — {e.message}")

    st.divider()

    with SessionLocal() as db:
        products = marketplace_intel.list_tracked_products(db, product_keyword or None)

    if products.empty:
        st.info("Nenhum produto salvo ainda para esse termo. Faça uma busca acima.")
    else:
        st.subheader(f"{len(products)} produtos, ordenados por unidades vendidas")
        rows_html = "".join(
            kalo_row(
                i + 1,
                p["main_image_url"],
                p["title"],
                p["shop_name"],
                "Vendidos",
                f'{p["units_sold"]:,}',
                None,
                [
                    ("Preço", f'{p["currency"]} {p["price_min"]:.0f}' if p["price_min"] == p["price_max"] else f'{p["currency"]} {p["price_min"]:.0f}-{p["price_max"]:.0f}'),
                    ("Comissão", f'{p["commission_pct"]:.1f}%'),
                    ("Categoria", p["category_name"]),
                ],
                top=(i == 0),
            )
            for i, (_, p) in enumerate(products.iterrows())
        )
        st.markdown(f'<div class="kalo-table">{rows_html}</div>', unsafe_allow_html=True)

        with st.expander("Ver tabela completa"):
            st.dataframe(
                products[["title", "shop_name", "units_sold", "price_min", "price_max", "currency", "commission_pct", "category_name"]],
                use_container_width=True,
                hide_index=True,
            )
