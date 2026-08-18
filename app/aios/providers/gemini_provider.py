"""
Gemini (Google Generative Language API, `generateContent`).

Dialeto mais distante dos três: papéis são "user"/"model" (não "assistant"),
tudo vira `parts`, e chamada/resposta de ferramenta são partes especiais
(`functionCall` / `functionResponse`) sem id — o casamento é feito pelo NOME
da função. Por isso o id da ToolCall aqui é sintetizado a partir do nome.
"""
import httpx

from app.aios.providers.base import LLMProvider
from app.aios.schemas import LLMResponse, Message, ProviderError, ToolCall, Usage
from app.config import settings


class GeminiProvider(LLMProvider):
    name = "gemini"
    label = "Gemini (Google)"
    default_model = "gemini-2.5-pro"
    strengths = ("contexto muito longo", "multimodal", "custo por token")
    price_per_mtok = (1.25, 10.0)

    def is_configured(self) -> bool:
        return bool(settings.gemini_api_key)

    def _render_contents(self, messages: list[Message]) -> list[dict]:
        contents: list[dict] = []
        for m in messages:
            if m.role == "tool":
                contents.append({
                    "role": "user",
                    "parts": [{"functionResponse": {"name": m.tool_name, "response": {"result": m.content}}}],
                })
            elif m.role == "assistant":
                parts = []
                if m.content:
                    parts.append({"text": m.content})
                parts.extend({"functionCall": {"name": c.name, "args": c.arguments}} for c in m.tool_calls)
                contents.append({"role": "model", "parts": parts or [{"text": "(vazio)"}]})
            else:
                contents.append({"role": "user", "parts": [{"text": m.content or "(vazio)"}]})
        return contents

    def complete(self, messages, system="", tools=None, model="", max_tokens=4096) -> LLMResponse:
        if not self.is_configured():
            raise ProviderError(self.name, "GEMINI_API_KEY não configurada")

        model_id = model or settings.gemini_model or self.default_model
        payload: dict = {
            "contents": self._render_contents(messages),
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = [{
                "functionDeclarations": [
                    {"name": t.name, "description": t.description, "parameters": t.parameters} for t in tools
                ]
            }]

        try:
            resp = httpx.post(
                f"{settings.gemini_base_url}/models/{model_id}:generateContent",
                headers={"x-goog-api-key": settings.gemini_api_key},
                json=payload,
                timeout=settings.aios_request_timeout,
            )
        except httpx.HTTPError as e:
            raise ProviderError(self.name, f"falha de rede: {e}")
        if resp.status_code >= 400:
            raise ProviderError(self.name, f"HTTP {resp.status_code}: {resp.text[:400]}")

        data = resp.json()
        candidate = (data.get("candidates") or [{}])[0]
        text_parts, calls = [], []
        for i, part in enumerate((candidate.get("content") or {}).get("parts") or []):
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                calls.append(ToolCall(id=f"{fc.get('name', 'fn')}-{i}", name=fc.get("name", ""), arguments=dict(fc.get("args") or {})))

        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text="\n".join(text_parts).strip(),
            tool_calls=calls,
            usage=Usage(usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0)),
            model=model_id,
            provider=self.name,
            stop_reason=candidate.get("finishReason", ""),
            raw=data,
        )
