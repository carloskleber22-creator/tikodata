"""Contrato que todo provedor de modelo implementa."""
from abc import ABC, abstractmethod

from app.aios.schemas import LLMResponse, Message, ToolSpec


class LLMProvider(ABC):
    name: str = ""
    label: str = ""
    default_model: str = ""
    # Pontos fortes declarados — o roteador do supervisor usa isso pra escolher.
    strengths: tuple[str, ...] = ()
    # Preço por 1M de tokens (entrada, saída) em USD, só pra estimar custo na
    # auditoria. Aproximado e muda com o tempo: é estimativa, não fatura.
    price_per_mtok: tuple[float, float] = (0.0, 0.0)

    @abstractmethod
    def is_configured(self) -> bool:
        """True se dá pra chamar de verdade (credencial presente, lib instalada)."""

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        system: str = "",
        tools: list[ToolSpec] | None = None,
        model: str = "",
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Uma rodada de conversa. Não faz loop de ferramenta — quem faz o loop
        é o supervisor, que é o único lugar que precisa saber disso."""

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        in_price, out_price = self.price_per_mtok
        return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
