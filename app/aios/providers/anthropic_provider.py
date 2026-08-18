"""
Claude (Anthropic Messages API) via SDK oficial `anthropic`.

Duas particularidades tratadas aqui e que não existem nos outros provedores:

1. `system` é parâmetro separado, não uma mensagem dentro de `messages`.
2. Nos modelos atuais o pensamento adaptativo vem ligado por padrão, e os
   blocos `thinking` da vez precisam voltar intactos junto com os `tool_use`
   quando devolvemos o resultado da ferramenta. Como o formato neutro não
   guarda blocos específicos de provedor (eles não são replayáveis em GPT ou
   Gemini), guardamos o conteúdo nativo num cache em memória indexado pelo id
   da primeira chamada de ferramenta do turno, e reusamos ele na hora de
   remontar o histórico. Só importa dentro de uma mesma execução do supervisor
   — turnos antigos podem perder os blocos sem problema.
"""
from collections import OrderedDict

from app.aios.providers.base import LLMProvider
from app.aios.schemas import LLMResponse, Message, ProviderError, ToolCall, Usage
from app.config import settings

_NATIVE_TURN_CACHE_SIZE = 64


class AnthropicProvider(LLMProvider):
    name = "claude"
    label = "Claude (Anthropic)"
    default_model = "claude-opus-5"
    strengths = ("raciocínio longo", "código", "análise de texto extenso")
    price_per_mtok = (5.0, 25.0)

    def __init__(self):
        # id da primeira tool_call do turno -> blocos de conteúdo nativos
        self._native_turns: "OrderedDict[str, list]" = OrderedDict()

    def is_configured(self) -> bool:
        if not settings.anthropic_api_key:
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def _client(self):
        import anthropic

        return anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=settings.aios_request_timeout)

    def _remember_turn(self, calls: list[ToolCall], content) -> None:
        if not calls:
            return
        self._native_turns[calls[0].id] = content
        while len(self._native_turns) > _NATIVE_TURN_CACHE_SIZE:
            self._native_turns.popitem(last=False)

    def _render_messages(self, messages: list[Message]) -> list[dict]:
        out: list[dict] = []
        pending_results: list[dict] = []

        def flush_results():
            if pending_results:
                out.append({"role": "user", "content": list(pending_results)})
                pending_results.clear()

        for m in messages:
            if m.role == "tool":
                # Resultados de ferramenta viram blocos tool_result numa
                # mensagem de user — e todos os resultados de um mesmo turno
                # precisam ir juntos, senão o modelo aprende a parar de pedir
                # ferramentas em paralelo.
                pending_results.append(
                    {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content or "(vazio)"}
                )
                continue

            flush_results()
            if m.role == "assistant" and m.tool_calls:
                native = self._native_turns.get(m.tool_calls[0].id)
                if native is not None:
                    out.append({"role": "assistant", "content": native})
                    continue
                blocks = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                blocks.extend(
                    {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in m.tool_calls
                )
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": m.role, "content": m.content or "(vazio)"})

        flush_results()
        return out

    def complete(self, messages, system="", tools=None, model="", max_tokens=4096) -> LLMResponse:
        if not settings.anthropic_api_key:
            raise ProviderError(self.name, "ANTHROPIC_API_KEY não configurada")
        try:
            import anthropic
        except ImportError:
            raise ProviderError(self.name, "pacote `anthropic` não instalado (pip install -r requirements.txt)")

        model_id = model or settings.anthropic_model or self.default_model
        kwargs: dict = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": self._render_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
            ]

        try:
            response = self._client().messages.create(**kwargs)
        except anthropic.APIStatusError as e:
            raise ProviderError(self.name, f"HTTP {e.status_code}: {e.message}")
        except anthropic.APIConnectionError as e:
            raise ProviderError(self.name, f"falha de rede: {e}")

        text_parts, calls = [], []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                # `input` já vem desserializado pelo SDK.
                calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {})))
        self._remember_turn(calls, response.content)

        return LLMResponse(
            text="\n".join(text_parts).strip(),
            tool_calls=calls,
            usage=Usage(response.usage.input_tokens, response.usage.output_tokens),
            model=response.model,
            provider=self.name,
            stop_reason=response.stop_reason or "",
            raw=response,
        )
