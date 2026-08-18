"""
Registro de ferramentas — o "Tools / MCP / APIs / Arquivos" do desenho.

Uma ferramenta é só um nome, um JSON Schema e um handler Python. O supervisor
nunca importa `builtin`/`mcp` direto: pede o registro pronto por
`get_registry()`, que monta as embutidas na primeira chamada e, se houver
servidores MCP configurados, tenta anexar as ferramentas remotas também.
"""
from dataclasses import dataclass
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.aios.schemas import ToolSpec


@dataclass
class ToolContext:
    """O que um handler recebe além dos argumentos do modelo."""

    db: Session
    session_id: Optional[int] = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., object]  # handler(ctx, **kwargs)
    category: str = "geral"
    # Ferramentas que escrevem/saem pra fora ficam marcadas: o supervisor só
    # roda elas se a sessão foi criada permitindo efeitos colaterais.
    writes: bool = False

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.parameters, self.category)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        self._tools[tool.name] = tool
        return tool

    def add(self, name: str, description: str, parameters: dict, category: str = "geral", writes: bool = False):
        """Decorador: `@registry.add("nome", "descrição", {...})`."""

        def wrapper(fn):
            self.register(Tool(name, description, parameters, fn, category, writes))
            return fn

        return wrapper

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all_tools(self, allow_writes: bool = True) -> list[Tool]:
        return [t for t in self._tools.values() if allow_writes or not t.writes]

    def specs(self, allow_writes: bool = True) -> list[ToolSpec]:
        return [t.spec() for t in self.all_tools(allow_writes)]


_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        from app.aios.tools import builtin, mcp

        _registry = ToolRegistry()
        builtin.register_all(_registry)
        mcp.register_all(_registry)
    return _registry


def reset_registry() -> None:
    """Usado em testes e quando a configuração de MCP muda em runtime."""
    global _registry
    _registry = None


def object_schema(properties: dict, required: list[str] | None = None) -> dict:
    """Atalho pro JSON Schema que os três provedores aceitam."""
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }
