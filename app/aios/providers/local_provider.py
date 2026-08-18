"""
Agentes locais — o quarto ramo do desenho, e o único que não é um LLM.

É um agente determinístico por regras: casa palavra-chave da pergunta com uma
ferramenta registrada, roda ela e devolve o resultado formatado. Serve pra dois
papéis reais:

- **Fallback**: sem nenhuma API key configurada, o AI OS continua respondendo
  as perguntas operacionais ("quanto vendi nos últimos 30 dias?") em vez de
  quebrar. É o modo em que o projeto roda hoje, já que nenhuma chave está
  configurada.
- **Rota barata**: perguntas que são só uma consulta ao banco não precisam
  gastar token de modelo grande.

Ele não entende linguagem natural de verdade — se nenhuma regra casar, ele diz
isso explicitamente em vez de inventar resposta. Também aceita a sintaxe
explícita `/tool <nome> {json}` pra chamar uma ferramenta na mão.
"""
import json
import re

from app.aios.providers.base import LLMProvider
from app.aios.schemas import LLMResponse, ToolCall, Usage

# palavra-chave -> (ferramenta, argumentos padrão)
RULES: list[tuple[tuple[str, ...], str, dict]] = [
    (("vendas", "faturamento", "receita", "vendi", "gmv da loja"), "vendas_resumo", {"dias": 30}),
    (("shopee",), "shopee_resumo", {"dias": 30}),
    (("criador", "creators", "influenciador"), "mercado_criadores", {}),
    (("produto", "produtos", "concorrente"), "mercado_produtos", {}),
    (("anúncio", "anuncio", "criativo", "ads"), "adlib_anuncios", {}),
    (("loja", "lojas", "conta", "contas", "conectad"), "listar_lojas", {}),
    (("lembre", "memória", "memoria", "anotado", "sabe sobre"), "memoria_buscar", {"consulta": ""}),
]


class LocalAgentProvider(LLMProvider):
    name = "local"
    label = "Agentes locais (regras)"
    default_model = "regras-v1"
    strengths = ("consulta direta ao banco", "custo zero", "funciona offline")
    price_per_mtok = (0.0, 0.0)

    def is_configured(self) -> bool:
        return True  # não depende de credencial nenhuma

    def complete(self, messages, system="", tools=None, model="", max_tokens=4096) -> LLMResponse:
        tool_names = {t.name for t in (tools or [])}

        # Segunda passada: já temos resultado de ferramenta, é hora de responder.
        results = [m for m in messages if m.role == "tool"]
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if results and messages[-1].role == "tool":
            linhas = [f"**{m.tool_name}**\n```json\n{m.content}\n```" for m in results]
            texto = (
                "Resposta montada pelo agente local (sem modelo de linguagem) a partir das "
                "ferramentas abaixo:\n\n" + "\n\n".join(linhas)
            )
            return self._response(texto, [], model)

        call = self._match(last_user, tool_names)
        if call is not None:
            return self._response("", [call], model)

        disponiveis = ", ".join(sorted(tool_names)) or "nenhuma"
        return self._response(
            "O agente local responde por regras e não achou nenhuma que case com essa pergunta. "
            "Configure `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` ou `GEMINI_API_KEY` para o supervisor "
            "poder rotear para um modelo de linguagem, ou chame uma ferramenta direto com "
            "`/tool <nome> {\"arg\": valor}`.\n\nFerramentas disponíveis: " + disponiveis,
            [],
            model,
        )

    def _match(self, pergunta: str, tool_names: set[str]) -> ToolCall | None:
        explicit = re.match(r"\s*/tool\s+([\w.]+)\s*(\{.*\})?\s*$", pergunta, re.DOTALL)
        if explicit and explicit.group(1) in tool_names:
            try:
                args = json.loads(explicit.group(2) or "{}")
            except json.JSONDecodeError:
                args = {}
            return ToolCall(id=f"local-{explicit.group(1)}", name=explicit.group(1), arguments=args)

        alvo = pergunta.lower()
        for palavras, tool, args in RULES:
            if tool in tool_names and any(p in alvo for p in palavras):
                args = dict(args)
                if "consulta" in args:
                    args["consulta"] = pergunta.strip()
                dias = re.search(r"(\d+)\s*dias?", alvo)
                if dias and "dias" in args:
                    args["dias"] = int(dias.group(1))
                return ToolCall(id=f"local-{tool}", name=tool, arguments=args)
        return None

    def _response(self, text: str, calls: list[ToolCall], model: str) -> LLMResponse:
        return LLMResponse(
            text=text,
            tool_calls=calls,
            usage=Usage(0, 0),
            model=model or self.default_model,
            provider=self.name,
            stop_reason="tool_use" if calls else "end_turn",
        )
