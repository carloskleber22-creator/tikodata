"""
Ferramentas embutidas.

Três famílias, seguindo o desenho:

- **dados**: leem o banco do próprio Tikodata (vendas TikTok/Shopee, criadores,
  produtos, anúncios). São a razão de existir do AI OS aqui — é o que faz o
  supervisor responder sobre a loja em vez de conversar no vácuo.
- **arquivos**: leitura/listagem dentro do diretório do projeto, com o caminho
  resolvido e conferido contra a raiz (nada de `../../etc/passwd`).
- **apis**: GET HTTP genérico, restrito a uma allowlist de domínios
  (`AIOS_HTTP_ALLOWLIST`) — vazia por padrão, ou seja, desligado.
- **memória**: gravar/ler fatos de longo prazo.
"""
import json
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx

from app.aios import memory
from app.aios.tools.registry import ToolContext, ToolRegistry, object_schema
from app.config import BASE_DIR, settings
from app.models import SellerAccount, ShopeeAccount
from app.services import ad_library, marketplace_intel, sales_dashboard, shopee_sales

MAX_ROWS = 20  # o que volta pro modelo; mais que isso só gasta contexto
MAX_FILE_CHARS = 20_000


def _df_rows(df, limit: int = MAX_ROWS) -> list[dict]:
    if df is None or getattr(df, "empty", True):
        return []
    return json.loads(df.head(limit).to_json(orient="records", date_format="iso"))


def _periodo(dias: int) -> tuple[datetime, datetime]:
    fim = datetime.utcnow()
    return fim - timedelta(days=max(1, dias)), fim


def register_all(registry: ToolRegistry) -> None:
    # ----------------------------------------------------------------- #
    # Dados da própria operação
    # ----------------------------------------------------------------- #
    @registry.add(
        "listar_lojas",
        "Lista as lojas conectadas (TikTok Shop e Shopee) com seus ids. Use antes de "
        "qualquer ferramenta que peça um id de loja.",
        object_schema({}),
        category="dados",
    )
    def listar_lojas(ctx: ToolContext):
        tiktok = [
            {"seller_account_id": s.id, "loja": s.shop_name or s.seller_name, "plataforma": "tiktok"}
            for s in ctx.db.query(SellerAccount).all()
        ]
        shopee = [
            {"shopee_account_id": a.id, "loja": a.shop_name, "plataforma": "shopee"}
            for a in ctx.db.query(ShopeeAccount).all()
        ]
        return {"tiktok_shop": tiktok, "shopee": shopee}

    @registry.add(
        "vendas_resumo",
        "Receita, unidades, ticket médio, série diária e produtos mais vendidos da loja "
        "TikTok Shop conectada, num período em dias.",
        object_schema(
            {
                "dias": {"type": "integer", "description": "Tamanho do período em dias (padrão 30)"},
                "seller_account_id": {"type": "integer", "description": "Id da loja; omita para usar a primeira conectada"},
            }
        ),
        category="dados",
    )
    def vendas_resumo(ctx: ToolContext, dias: int = 30, seller_account_id: int | None = None):
        if seller_account_id is None:
            seller = ctx.db.query(SellerAccount).first()
            if seller is None:
                return {"erro": "nenhuma loja TikTok Shop conectada — rode o OAuth ou carregue os dados de demonstração"}
            seller_account_id = seller.id
        inicio, fim = _periodo(dias)
        resumo = sales_dashboard.get_sales_summary(ctx.db, seller_account_id, inicio, fim)
        return {
            "periodo_dias": dias,
            "receita": round(resumo["revenue"], 2),
            "unidades": resumo["units"],
            "ticket_medio": round(resumo["avg_ticket"], 2),
            "por_dia": _df_rows(resumo["by_day"]),
            "top_produtos": [
                {k: v for k, v in row.items() if k != "trend"} for row in _df_rows(resumo["top_products"], 10)
            ],
        }

    @registry.add(
        "shopee_resumo",
        "Mesmo resumo de vendas, mas da loja Shopee conectada.",
        object_schema(
            {
                "dias": {"type": "integer", "description": "Tamanho do período em dias (padrão 30)"},
                "shopee_account_id": {"type": "integer", "description": "Id da conta Shopee; omita para a primeira"},
            }
        ),
        category="dados",
    )
    def shopee_resumo(ctx: ToolContext, dias: int = 30, shopee_account_id: int | None = None):
        if shopee_account_id is None:
            conta = ctx.db.query(ShopeeAccount).first()
            if conta is None:
                return {"erro": "nenhuma loja Shopee conectada"}
            shopee_account_id = conta.id
        inicio, fim = _periodo(dias)
        resumo = shopee_sales.get_sales_summary(ctx.db, shopee_account_id, inicio, fim)
        return {
            "periodo_dias": dias,
            "receita": round(resumo["revenue"], 2),
            "unidades": resumo["units"],
            "ticket_medio": round(resumo["avg_ticket"], 2),
            "top_produtos": [
                {k: v for k, v in row.items() if k != "trend"} for row in _df_rows(resumo["top_products"], 10)
            ],
        }

    @registry.add(
        "mercado_criadores",
        "Criadores já pesquisados na Pesquisa de Mercado (GMV, seguidores, categoria). "
        "Lê o que está gravado localmente — não dispara busca nova na API do TikTok.",
        object_schema({"palavra_chave": {"type": "string", "description": "Filtra pela palavra-chave da busca"}}),
        category="dados",
    )
    def mercado_criadores(ctx: ToolContext, palavra_chave: str = ""):
        return {"criadores": _df_rows(marketplace_intel.list_tracked_creators(ctx.db, palavra_chave or None))}

    @registry.add(
        "mercado_produtos",
        "Produtos já pesquisados na Pesquisa de Mercado (unidades vendidas, preço, comissão).",
        object_schema({"palavra_chave": {"type": "string", "description": "Filtra pela palavra-chave da busca"}}),
        category="dados",
    )
    def mercado_produtos(ctx: ToolContext, palavra_chave: str = ""):
        return {"produtos": _df_rows(marketplace_intel.list_tracked_products(ctx.db, palavra_chave or None))}

    @registry.add(
        "adlib_anuncios",
        "Anúncios já capturados da Ad Library oficial do TikTok (só Europa): anunciante, "
        "período e alcance.",
        object_schema({"termo": {"type": "string", "description": "Filtra pelo termo buscado"}}),
        category="dados",
    )
    def adlib_anuncios(ctx: ToolContext, termo: str = ""):
        return {"anuncios": _df_rows(ad_library.list_tracked_ads(ctx.db, termo or None))}

    # ----------------------------------------------------------------- #
    # Memória
    # ----------------------------------------------------------------- #
    @registry.add(
        "memoria_gravar",
        "Grava um fato de longo prazo (preferência do usuário, contexto do negócio) para "
        "usar em conversas futuras.",
        object_schema(
            {
                "chave": {"type": "string", "description": "Identificador curto do fato"},
                "valor": {"type": "string", "description": "O fato em si"},
                "todas_as_sessoes": {"type": "boolean", "description": "true grava para todas as sessões (padrão); false grava só nesta"},
            },
            required=["chave", "valor"],
        ),
        category="memoria",
        writes=True,
    )
    def memoria_gravar(ctx: ToolContext, chave: str, valor: str, todas_as_sessoes: bool = True):
        escopo = "" if todas_as_sessoes else str(ctx.session_id or "")
        fato = memory.remember(ctx.db, chave, valor, scope=escopo, source="supervisor")
        return {"gravado": True, "chave": fato.key, "escopo": fato.scope or "global"}

    @registry.add(
        "memoria_buscar",
        "Busca fatos gravados na memória de longo prazo.",
        object_schema({"consulta": {"type": "string", "description": "Texto a procurar em chave e valor"}}),
        category="memoria",
    )
    def memoria_buscar(ctx: ToolContext, consulta: str = ""):
        fatos = memory.recall(ctx.db, consulta, scope=str(ctx.session_id or ""))
        return {"fatos": [{"chave": f.key, "valor": f.value, "escopo": f.scope or "global"} for f in fatos]}

    # ----------------------------------------------------------------- #
    # Arquivos — sempre resolvidos e conferidos contra a raiz do projeto
    # ----------------------------------------------------------------- #
    @registry.add(
        "arquivos_listar",
        "Lista arquivos de um diretório do projeto (caminho relativo à raiz do repositório).",
        object_schema({"caminho": {"type": "string", "description": "Diretório relativo, ex.: 'app/services'"}}),
        category="arquivos",
    )
    def arquivos_listar(ctx: ToolContext, caminho: str = "."):
        alvo = _resolver(caminho)
        if isinstance(alvo, dict):
            return alvo
        if not alvo.is_dir():
            return {"erro": f"'{caminho}' não é um diretório"}
        return {
            "caminho": str(alvo.relative_to(BASE_DIR)),
            "itens": sorted(
                f"{p.name}/" if p.is_dir() else p.name for p in alvo.iterdir() if not p.name.startswith(".")
            )[:200],
        }

    @registry.add(
        "arquivo_ler",
        "Lê um arquivo de texto do projeto (truncado em 20 mil caracteres).",
        object_schema({"caminho": {"type": "string", "description": "Arquivo relativo à raiz"}}, required=["caminho"]),
        category="arquivos",
    )
    def arquivo_ler(ctx: ToolContext, caminho: str):
        alvo = _resolver(caminho)
        if isinstance(alvo, dict):
            return alvo
        if not alvo.is_file():
            return {"erro": f"arquivo não encontrado: {caminho}"}
        try:
            texto = alvo.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {"erro": str(e)}
        return {
            "caminho": str(alvo.relative_to(BASE_DIR)),
            "truncado": len(texto) > MAX_FILE_CHARS,
            "conteudo": texto[:MAX_FILE_CHARS],
        }

    # ----------------------------------------------------------------- #
    # APIs externas
    # ----------------------------------------------------------------- #
    @registry.add(
        "http_get",
        "GET numa API externa. Só funciona para domínios listados em AIOS_HTTP_ALLOWLIST "
        "(vazia por padrão, ou seja, desligada).",
        object_schema({"url": {"type": "string", "description": "URL https completa"}}, required=["url"]),
        category="apis",
    )
    def http_get(ctx: ToolContext, url: str):
        allowlist = [d.strip().lower() for d in settings.aios_http_allowlist.split(",") if d.strip()]
        host = (urlparse(url).hostname or "").lower()
        if not allowlist:
            return {"erro": "http_get desligado: nenhum domínio em AIOS_HTTP_ALLOWLIST"}
        if not any(host == d or host.endswith("." + d) for d in allowlist):
            return {"erro": f"domínio '{host}' fora da allowlist ({', '.join(allowlist)})"}
        try:
            resp = httpx.get(url, timeout=settings.aios_request_timeout, follow_redirects=True)
        except httpx.HTTPError as e:
            return {"erro": f"falha de rede: {e}"}
        return {"status": resp.status_code, "corpo": resp.text[:MAX_FILE_CHARS]}


def _resolver(caminho: str):
    """Resolve o caminho e garante que ele fica dentro da raiz do projeto."""
    try:
        alvo = (BASE_DIR / caminho).resolve()
    except OSError as e:
        return {"erro": str(e)}
    if alvo != BASE_DIR and BASE_DIR not in alvo.parents:
        return {"erro": "caminho fora do diretório do projeto"}
    if not alvo.exists():
        return {"erro": f"caminho não encontrado: {caminho}"}
    return alvo
