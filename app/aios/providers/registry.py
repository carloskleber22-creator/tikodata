"""Registro de provedores — o supervisor só conhece esta lista."""
from app.aios.providers.anthropic_provider import AnthropicProvider
from app.aios.providers.base import LLMProvider
from app.aios.providers.gemini_provider import GeminiProvider
from app.aios.providers.local_provider import LocalAgentProvider
from app.aios.providers.openai_provider import OpenAIProvider

# Instâncias únicas: o provedor do Claude guarda cache de blocos nativos entre
# chamadas de um mesmo turno, então não pode ser recriado a cada requisição.
_PROVIDERS: dict[str, LLMProvider] = {
    p.name: p for p in (OpenAIProvider(), AnthropicProvider(), GeminiProvider(), LocalAgentProvider())
}


def get(name: str) -> LLMProvider | None:
    return _PROVIDERS.get(name)


def all_providers() -> list[LLMProvider]:
    return list(_PROVIDERS.values())


def configured() -> list[LLMProvider]:
    return [p for p in _PROVIDERS.values() if p.is_configured()]


def describe() -> list[dict]:
    return [
        {
            "name": p.name,
            "label": p.label,
            "default_model": p.default_model,
            "strengths": list(p.strengths),
            "configured": p.is_configured(),
        }
        for p in _PROVIDERS.values()
    ]
