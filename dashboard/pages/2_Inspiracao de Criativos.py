import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import streamlit as st

from app.config import settings
from app.db import SessionLocal, init_db
from app.adlib_client import AdLibraryAPIError, SUPPORTED_COUNTRIES
from app.services import ad_library
from dashboard._theme import inject_base_css, kalo_row

st.set_page_config(page_title="Inspiração de Criativos", page_icon="🎨", layout="wide")
init_db()
inject_base_css()

st.title("🎨 Inspiração de Criativos")
st.caption(
    "Busque por categoria/nicho de produto e veja os criativos com mais alcance rodando no "
    "TikTok — direto da Commercial Content API, a biblioteca oficial e pública de transparência "
    "de anúncios do TikTok."
)

st.warning(
    "**Cobre só anúncios veiculados na Europa** (UE/EEE + Reino Unido/Suíça) — exigência legal "
    "de transparência (lei DSA), não uma limitação nossa. Como o Brasil não está coberto, isso "
    "**não serve pra achar concorrentes brasileiros específicos** — o valor real é buscar por "
    "**categoria/nicho** (\"skincare\", \"fone bluetooth\", \"pet toys\"...) pra ver que formato de "
    "vídeo, gancho e estilo de criativo está conseguindo alcance lá fora, como referência pros "
    "seus próprios anúncios. **Não tem gasto nem engajamento** — só a peça, o período em que "
    "rodou, e uma faixa de alcance (ex.: \"11K\")."
)

if not settings.adlib_client_key or not settings.adlib_client_secret:
    st.info(
        "Configure `ADLIB_CLIENT_KEY` e `ADLIB_CLIENT_SECRET` no `.env` (app separado em "
        "[developers.tiktok.com](https://developers.tiktok.com), aprovação para a Commercial "
        "Content API — ver README) para buscar de verdade."
    )
    st.stop()

col1, col2, col3 = st.columns([3, 2, 1])
search_term = col1.text_input("Categoria ou nicho de produto", placeholder="ex: skincare, fone bluetooth, pet toys")
country_label = col2.selectbox(
    "País (opcional)",
    options=["Todos os países cobertos"] + [f"{name} ({code})" for code, name in SUPPORTED_COUNTRIES.items()],
)
country_code = None if country_label.startswith("Todos") else country_label.split("(")[-1].rstrip(")")
max_count = col3.number_input("Qtd.", min_value=5, max_value=50, value=20, step=5)

preset = st.pills(
    "Sugestões rápidas (usa a categoria acima se você já digitou algo)",
    options=["Skincare", "Fone bluetooth", "Pet toys", "Beleza", "Casa e cozinha", "Fitness"],
    key="ad_preset",
)
effective_term = search_term or preset or ""

if st.button("Buscar criativos", type="primary"):
    if not effective_term:
        st.warning("Informe uma categoria ou termo de busca, ou clique num atalho.")
    else:
        with st.spinner("Buscando criativos na Ad Library..."):
            with SessionLocal() as db:
                try:
                    token = ad_library.get_client_token()
                    saved = ad_library.search_and_track(db, token, effective_term, country_code, max_count)
                    st.success(f"{saved} criativos encontrados e salvos.")
                except AdLibraryAPIError as e:
                    st.error(f"Erro na Ad Library API: {e}")

st.divider()

with SessionLocal() as db:
    ads = ad_library.list_tracked_ads(db, effective_term or None)

if ads.empty:
    st.info("Nenhum criativo salvo ainda para esse termo. Faça uma busca acima.")
else:
    st.subheader(f"{len(ads)} criativos, ordenados por alcance")
    rows_html = "".join(
        kalo_row(
            i + 1,
            ad["thumbnail_url"],
            ad["advertiser_name"],
            f'{ad["country_code"] or "Europa"} · {ad["status"]}',
            "Alcance",
            ad["reach_label"] or "—",
            None,
            [("Início", ad["first_shown_date"] or "—"), ("Fim", ad["last_shown_date"] or "—")],
            top=(i == 0),
        )
        for i, (_, ad) in enumerate(ads.iterrows())
    )
    st.markdown(f'<div class="kalo-table">{rows_html}</div>', unsafe_allow_html=True)

    videos = ads[ads["video_url"] != ""].head(4)
    if not videos.empty:
        st.write("")
        st.caption("Prévia dos vídeos (top criativos com vídeo disponível)")
        video_cols = st.columns(len(videos))
        for col, (_, ad) in zip(video_cols, videos.iterrows()):
            with col:
                st.video(ad["video_url"])
                st.caption(ad["advertiser_name"])

    with st.expander("Ver tabela completa"):
        st.dataframe(
            ads[["advertiser_name", "search_term", "country_code", "reach_label", "first_shown_date", "last_shown_date", "status"]],
            use_container_width=True,
            hide_index=True,
        )
