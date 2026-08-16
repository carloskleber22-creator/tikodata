"""
Tokens de cor e helpers de estilo compartilhados pelas páginas do dashboard.
Paleta validada (contraste + CVD) do guia interno de dataviz — ver
references/palette.md do skill "dataviz". Modo escuro, já que é o tema
padrão do Streamlit aqui e combina com o resto do produto.
"""
import plotly.graph_objects as go
import streamlit as st

from app.config import settings

SURFACE = "#1a1a19"
PAGE = "#0d0d0d"
INK_PRIMARY = "#ffffff"
INK_SECONDARY = "#c3c2b7"
INK_MUTED = "#898781"
GRIDLINE = "#2c2c2a"
BASELINE = "#383835"
BORDER = "rgba(255,255,255,0.10)"

SEQUENTIAL_BLUE = "#3987e5"  # step 400, magnitude único (receita, unidades)
DELTA_GOOD = "#0ca30c"
DELTA_BAD = "#e66767"


def inject_base_css():
    st.markdown(
        f"""
        <style>
        .stat-tile {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 12px;
            padding: 16px 20px;
        }}
        .stat-tile__label {{
            color: {INK_SECONDARY};
            font-size: 0.85rem;
            margin-bottom: 6px;
        }}
        .stat-tile__value {{
            color: {INK_PRIMARY};
            font-size: 1.9rem;
            font-weight: 600;
            line-height: 1.1;
        }}
        .stat-tile__delta {{
            font-size: 0.85rem;
            margin-top: 6px;
        }}
        .stat-tile__delta--good {{ color: {DELTA_GOOD}; }}
        .stat-tile__delta--bad {{ color: {DELTA_BAD}; }}
        .stat-tile__delta--muted {{ color: {INK_MUTED}; }}
        .stat-tile__sparkline {{ margin-top: 8px; }}

        .kalo-table {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 12px;
            overflow: hidden;
        }}
        .kalo-row {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 14px;
            border-bottom: 1px solid {BORDER};
        }}
        .kalo-row:last-child {{ border-bottom: none; }}
        .kalo-row__rank {{
            width: 30px;
            color: {INK_MUTED};
            font-size: 0.78rem;
            font-weight: 600;
            flex-shrink: 0;
            text-align: center;
        }}
        .kalo-row__thumb {{
            width: 40px;
            height: 40px;
            border-radius: 8px;
            object-fit: cover;
            flex-shrink: 0;
            background: {GRIDLINE};
        }}
        .kalo-row__info {{
            flex: 1 1 auto;
            min-width: 0;
        }}
        .kalo-row__title {{
            color: {INK_PRIMARY};
            font-size: 0.85rem;
            font-weight: 600;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .kalo-row__subtitle {{
            color: {INK_MUTED};
            font-size: 0.74rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            margin-top: 1px;
        }}
        .kalo-row__primary {{
            width: 110px;
            flex-shrink: 0;
            text-align: right;
        }}
        .kalo-row__primary-label {{
            color: {INK_MUTED};
            font-size: 0.66rem;
        }}
        .kalo-row__primary-value {{
            color: {INK_PRIMARY};
            font-size: 0.92rem;
            font-weight: 700;
        }}
        .kalo-row__spark {{ display: flex; justify-content: flex-end; margin-top: 2px; }}
        .kalo-row__metrics {{
            display: flex;
            gap: 18px;
            flex-shrink: 0;
        }}
        .kalo-row__metric {{
            width: 78px;
            text-align: right;
        }}
        .kalo-row__metric-label {{
            color: {INK_MUTED};
            font-size: 0.64rem;
            white-space: nowrap;
        }}
        .kalo-row__metric-value {{
            color: {INK_SECONDARY};
            font-size: 0.82rem;
            font-weight: 600;
            white-space: nowrap;
        }}
        @media (max-width: 640px) {{
            .kalo-row__metrics {{ display: none; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def require_demo_login():
    """Portão de login opcional — sem efeito se DEMO_LOGIN_USERNAME/PASSWORD não
    estiverem configurados (padrão local/dev). Só existe pra satisfazer campos de
    "conta de teste" de formulários de parceiro (ex: Shopee ISV), configurado via
    secrets só no deploy público. Chamar logo no topo de cada página."""
    if not settings.demo_login_username or not settings.demo_login_password:
        return
    if st.session_state.get("demo_authenticated"):
        return

    st.title("🔒 Acesso de avaliação")
    st.caption("Esta instância pública pede login só para avaliação de parceiros (ex: Shopee).")
    user = st.text_input("Usuário")
    pwd = st.text_input("Senha", type="password")
    if st.button("Entrar", type="primary"):
        if user == settings.demo_login_username and pwd == settings.demo_login_password:
            st.session_state["demo_authenticated"] = True
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
    st.stop()


def sparkline_svg(values, width: int = 96, height: int = 28) -> str:
    """12-pontos (ou menos) em tom recessivo, com o ponto mais recente em destaque na cor de acento."""
    if not values or len(values) < 2 or max(values) == 0:
        return f'<svg width="{width}" height="{height}"></svg>'

    pts = values[-12:]
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1
    pad = 3
    step = (width - 2 * pad) / (len(pts) - 1)

    coords = [
        (pad + i * step, height - pad - (v - lo) / span * (height - 2 * pad))
        for i, v in enumerate(pts)
    ]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    last_x, last_y = coords[-1]

    # Uma linha só, sem quebras: blocos HTML separados por linha em branco confundem
    # o parser markdown do Streamlit e vazam como texto cru a partir do 2º bloco.
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<polyline points="{polyline}" fill="none" stroke="{INK_MUTED}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" opacity="0.7" />'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="{SEQUENTIAL_BLUE}" /></svg>'
    )


def kalo_row(rank, thumb_url: str, title: str, subtitle: str, primary_label: str, primary_value: str, trend, metrics: list, top: bool = False) -> str:
    """Linha de ranking densa, inspirada nas tabelas de Produto/Criador do Kalodata:
    título/subtítulo (+ miniatura opcional), uma métrica primária com sparkline, e
    uma fileira de métricas secundárias compactas (unidades, preço, comissão...).
    Componente único pra todo ranking do app — antes existiam dois (`rank_row` e
    `kalo_row`) com visual inconsistente entre páginas; unificado após revisão de
    UX. `thumb_url` vazio omite a miniatura (usado pela lista de lojas/produtos
    sem imagem). O 1º lugar (top=True) ganha um 🔥 ao lado do número, sem badge
    separado — um badge próprio quebrava linha e sobrepunha a miniatura em telas
    estreitas."""
    rank_display = f"🔥{rank}" if top else str(rank)
    metrics_html = "".join(
        f'<div class="kalo-row__metric"><div class="kalo-row__metric-label">{label}</div>'
        f'<div class="kalo-row__metric-value">{value}</div></div>'
        for label, value in metrics
    )
    thumb_html = f'<img class="kalo-row__thumb" src="{thumb_url}" />' if thumb_url else ""
    return (
        f'<div class="kalo-row">'
        f'<div class="kalo-row__rank">{rank_display}</div>'
        f'{thumb_html}'
        f'<div class="kalo-row__info"><div class="kalo-row__title" title="{title}">{title}</div>'
        f'<div class="kalo-row__subtitle">{subtitle}</div></div>'
        f'<div class="kalo-row__primary"><div class="kalo-row__primary-label">{primary_label}</div>'
        f'<div class="kalo-row__primary-value">{primary_value}</div>'
        f'<div class="kalo-row__spark">{sparkline_svg(trend)}</div></div>'
        f'<div class="kalo-row__metrics">{metrics_html}</div>'
        f'</div>'
    )


def format_compact(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}"


def stat_tile(label: str, value: str, delta_pct=None, higher_is_good: bool = True, trend=None, show_delta: bool = True) -> str:
    delta_html = ""
    if delta_pct is not None:
        is_good = (delta_pct >= 0) == higher_is_good
        cls = "good" if is_good else "bad"
        arrow = "↑" if delta_pct >= 0 else "↓"
        delta_html = f'<div class="stat-tile__delta stat-tile__delta--{cls}">{arrow} {abs(delta_pct):.1f}% vs período anterior</div>'
    elif show_delta:
        delta_html = '<div class="stat-tile__delta stat-tile__delta--muted">Sem período anterior para comparar</div>'

    spark_html = f'<div class="stat-tile__sparkline">{sparkline_svg(trend)}</div>' if trend else ""

    return (
        f'<div class="stat-tile">'
        f'<div class="stat-tile__label">{label}</div>'
        f'<div class="stat-tile__value">{value}</div>'
        f'{delta_html}{spark_html}'
        f'</div>'
    )


def style_layout(fig: go.Figure, show_legend: bool = False) -> go.Figure:
    """Chrome comum: superfície escura, grid hairline recessivo, sem legenda p/ série única."""
    fig.update_layout(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", color=INK_SECONDARY),
        showlegend=show_legend,
        margin=dict(l=10, r=10, t=10, b=10),
        hoverlabel=dict(bgcolor=SURFACE, font_color=INK_PRIMARY, bordercolor=BASELINE),
    )
    fig.update_xaxes(showgrid=False, linecolor=BASELINE, tickfont=dict(color=INK_MUTED))
    fig.update_yaxes(showgrid=True, gridcolor=GRIDLINE, gridwidth=1, zeroline=False, tickfont=dict(color=INK_MUTED))
    return fig
