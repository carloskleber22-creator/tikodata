"""
GPT (OpenAI Chat Completions). Sem SDK oficial no projeto — o resto do
Tikodata já fala HTTP direto com as APIs (ver tt_client/shopee_client), então
mantivemos o mesmo padrão aqui com httpx.
"""
import json

import httpx

from app.aios.providers.base import LLMProvider
from app.aios.schemas import LLMResponse, Message, ProviderError, ToolCall, Usage
from app.config import settings


class OpenAIProvider(LLMProvider):
    name = "gpt"
    label = "GPT (OpenAI)"
    default_model = "gpt-4.1"
    strengths = ("uso de ferramentas", "resposta rápida", "tarefas gerais")
    price_per_mtok = (2.0, 8.0)

    def is_configured(self) -> bool:
        return bool(settings.openai_api_key)

    # ------------------------------------------------------------------ #
    # Tradução do formato neutro para o dialeto da OpenAI
    # ------------------------------------------------------------------ #
    def _render_messages(self, messages: list[Message], system: str) -> list[dict]:
        out: list[dict] = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            if m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
            elif m.role == "assistant" and m.tool_calls:
                out.append({
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)},
                        }
                        for c in m.tool_calls
                    ],
                })
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    def complete(self, messages, system="", tools=None, model="", max_tokens=4096) -> LLMResponse:
        if not self.is_configured():
            raise ProviderError(self.name, "OPENAI_API_KEY não configurada")

        payload: dict = {
            "model": model or settings.openai_model or self.default_model,
            "max_completion_tokens": max_tokens,
            "messages": self._render_messages(messages, system),
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]

        try:
            resp = httpx.post(
                f"{settings.openai_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json=payload,
                timeout=settings.aios_request_timeout,
            )
        except httpx.HTTPError as e:
            raise ProviderError(self.name, f"falha de rede: {e}")
        if resp.status_code >= 400:
            raise ProviderError(self.name, f"HTTP {resp.status_code}: {resp.text[:400]}")

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = []
        for raw in msg.get("tool_calls") or []:
            fn = raw.get("function") or {}
            # Sempre json.loads — nunca casar string crua com o argumento.
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=raw.get("id", ""), name=fn.get("name", ""), arguments=args))

        usage = data.get("usage") or {}
        return LLMResponse(
            text=msg.get("content") or "",
            tool_calls=calls,
            usage=Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
            model=data.get("model", payload["model"]),
            provider=self.name,
            stop_reason=choice.get("finish_reason", ""),
            raw=data,
        )
