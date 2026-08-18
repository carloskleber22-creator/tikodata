"""
Formato interno neutro entre provedores.

Cada provedor (GPT, Claude, Gemini, agentes locais) fala um dialeto diferente
de "mensagem" e de "chamada de ferramenta". Em vez de vazar o formato de um
deles pro resto do sistema, tudo aqui dentro trafega nestes dataclasses e cada
provedor traduz na fronteira (`app/aios/providers/*.py`). É isso que deixa o
supervisor trocar de modelo no meio da conversa sem perder o histórico.
"""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolCall:
    """Pedido do modelo pra rodar uma ferramenta."""

    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: str  # user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""  # preenchido quando role == "tool"
    tool_name: str = ""


@dataclass
class ToolSpec:
    """Ferramenta exposta ao modelo. `parameters` é JSON Schema puro — os três
    provedores aceitam JSON Schema, só mudam o nome do campo em volta."""

    name: str
    description: str
    parameters: dict
    category: str = "geral"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    provider: str = ""
    stop_reason: str = ""
    raw: Optional[Any] = None


class ProviderError(Exception):
    """Falha ao falar com um provedor — o supervisor trata como recuperável e
    tenta o próximo da fila de fallback."""

    def __init__(self, provider: str, message: str):
        self.provider = provider
        self.message = message
        super().__init__(f"{provider}: {message}")
