"""
Cliente MCP (Model Context Protocol) por HTTP.

Servidores MCP são configurados em `AIOS_MCP_SERVERS`, um JSON:

    [{"nome": "docs", "url": "https://exemplo/mcp", "headers": {"Authorization": "Bearer ..."}}]

Na montagem do registro chamamos `tools/list` em cada servidor e registramos
cada ferramenta remota como `mcp__<servidor>__<ferramenta>`, com o mesmo
JSON Schema que o servidor declarou — do ponto de vista do supervisor e do
modelo elas são indistinguíveis de uma ferramenta local.

O transporte implementado é o HTTP streamable (JSON-RPC 2.0 por POST), que é o
que servidores MCP remotos expõem. Servidores stdio (processo local) não são
cobertos: exigiriam gerenciar subprocesso, que é outro problema. Se um servidor
estiver fora do ar, a falha é registrada e ignorada — um MCP quebrado não pode
derrubar o AI OS inteiro.
"""
import json
import logging

import httpx

from app.aios.tools.registry import Tool, ToolContext, ToolRegistry
from app.config import settings

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"


class MCPClient:
    def __init__(self, nome: str, url: str, headers: dict | None = None):
        self.nome = nome
        self.url = url
        self.headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        self.headers.update(headers or {})
        self._session_id = ""
        self._id = 0

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        headers = dict(self.headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        resp = httpx.post(
            self.url,
            headers=headers,
            json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}},
            timeout=settings.aios_request_timeout,
        )
        resp.raise_for_status()
        if resp.headers.get("mcp-session-id"):
            self._session_id = resp.headers["mcp-session-id"]

        # A resposta pode vir como JSON puro ou como um evento SSE único.
        body = resp.text.strip()
        if body.startswith("event:") or body.startswith("data:"):
            body = "\n".join(
                linha[5:].strip() for linha in body.splitlines() if linha.startswith("data:")
            )
        data = json.loads(body) if body else {}
        if "error" in data:
            raise RuntimeError(f"{data['error'].get('code')}: {data['error'].get('message')}")
        return data.get("result") or {}

    def initialize(self) -> None:
        self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "tikodata-aios", "version": "1"},
            },
        )

    def list_tools(self) -> list[dict]:
        return self._rpc("tools/list").get("tools", [])

    def call_tool(self, nome: str, argumentos: dict) -> dict:
        return self._rpc("tools/call", {"name": nome, "arguments": argumentos})


def load_servers() -> list[dict]:
    if not settings.aios_mcp_servers.strip():
        return []
    try:
        servidores = json.loads(settings.aios_mcp_servers)
    except json.JSONDecodeError as e:
        logger.warning("AIOS_MCP_SERVERS não é JSON válido: %s", e)
        return []
    return servidores if isinstance(servidores, list) else []


def register_all(registry: ToolRegistry) -> int:
    """Registra as ferramentas de todos os servidores MCP. Retorna quantas entraram."""
    total = 0
    for cfg in load_servers():
        nome = cfg.get("nome") or cfg.get("name") or "mcp"
        url = cfg.get("url", "")
        if not url:
            continue
        cliente = MCPClient(nome, url, cfg.get("headers"))
        try:
            cliente.initialize()
            remotas = cliente.list_tools()
        except (httpx.HTTPError, RuntimeError, json.JSONDecodeError) as e:
            logger.warning("Servidor MCP '%s' indisponível, ignorando: %s", nome, e)
            continue

        for remota in remotas:
            registry.register(_to_tool(cliente, nome, remota))
            total += 1
    return total


def _to_tool(cliente: MCPClient, servidor: str, remota: dict) -> Tool:
    nome_remoto = remota.get("name", "")

    def handler(ctx: ToolContext, **kwargs):
        try:
            resultado = cliente.call_tool(nome_remoto, kwargs)
        except (httpx.HTTPError, RuntimeError, json.JSONDecodeError) as e:
            return {"erro": f"MCP '{servidor}' falhou: {e}"}
        # O conteúdo padrão do MCP é uma lista de blocos; achatamos o texto.
        textos = [b.get("text", "") for b in resultado.get("content", []) if b.get("type") == "text"]
        return {"texto": "\n".join(textos), "structuredContent": resultado.get("structuredContent")}

    return Tool(
        name=f"mcp__{servidor}__{nome_remoto}",
        description=remota.get("description", f"Ferramenta MCP '{nome_remoto}' do servidor '{servidor}'"),
        parameters=remota.get("inputSchema") or {"type": "object", "properties": {}},
        handler=handler,
        category="mcp",
        # Não dá pra saber se uma ferramenta remota escreve; tratamos como se sim.
        writes=True,
    )
