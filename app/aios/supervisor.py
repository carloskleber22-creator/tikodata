"""
Supervisor Agent — o miolo do AI OS.

Ele faz três coisas, nessa ordem:

1. **Roteia**: escolhe qual cérebro atende o pedido (GPT, Claude, Gemini ou o
   agente local de regras), por preferência explícita, por sessão fixada ou por
   heurística de tarefa, sempre limitado ao que está de fato configurado. A
   decisão e o motivo vão para a auditoria.
2. **Executa o laço de ferramentas**: modelo pede ferramenta -> supervisor roda
   -> resultado volta pro modelo, até ele responder ou bater o teto de passos.
   O laço fica aqui, e não dentro de cada provedor, porque é ele que precisa
   ser igual para os quatro.
3. **Persiste**: mensagens na memória de curto prazo, fatos na de longo prazo,
   e um evento de auditoria por passo.

Se o provedor escolhido falhar (chave inválida, rede, 500), ele cai para o
próximo candidato da fila em vez de devolver erro — e registra a queda.
"""
import json
import time
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.aios import audit, memory
from app.aios.providers import registry as providers
from app.aios.providers.base import LLMProvider
from app.aios.schemas import LLMResponse, Message, ProviderError, ToolCall
from app.aios.tools.registry import ToolContext, get_registry
from app.config import settings

SYSTEM_PROMPT = """Você é o supervisor do Tikodata, um painel de vendas de TikTok Shop e Shopee.
Responde em português do Brasil, de forma direta e sem enrolação.

Regras:
- Para qualquer pergunta sobre vendas, produtos, criadores ou anúncios, use as ferramentas
  disponíveis em vez de responder de memória. Os números têm que vir do banco.
- Se uma ferramenta devolver `erro`, explique o erro ao usuário; não invente o dado que faltou.
- Os dados de vendas cobrem só as lojas conectadas do próprio usuário, e a biblioteca de
  anúncios só cobre a Europa. Não prometa dado de concorrente que o projeto não tem.
- Cite os números que você usou (receita, unidades, período) na resposta."""

# Heurística de roteamento: palavra na pergunta -> provedor preferido.
# É deliberadamente simples e legível — a decisão fica auditada, então dá pra
# revisar depois se a escolha faz sentido na prática.
ROUTING_HINTS: list[tuple[tuple[str, ...], str, str]] = [
    (("código", "codigo", "bug", "erro no", "refatorar", "sql", "python"), "claude", "tarefa de código/análise técnica"),
    (("resuma", "resumo do arquivo", "relatório longo", "relatorio longo", "documento"), "gemini", "texto longo/contexto grande"),
    (("estratégia", "estrategia", "analise", "análise", "por que", "porque"), "claude", "raciocínio analítico"),
    (("quanto", "quantos", "liste", "lista", "mostre"), "gpt", "consulta objetiva com ferramenta"),
]

# Ordem de preferência quando nada mais decide.
DEFAULT_ORDER = ("gpt", "claude", "gemini", "local")


@dataclass
class SupervisorResult:
    answer: str
    session_id: int
    provider: str
    model: str
    steps: int
    tool_calls: list[dict] = field(default_factory=list)
    routing_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    fallbacks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "resposta": self.answer,
            "session_id": self.session_id,
            "provedor": self.provider,
            "modelo": self.model,
            "passos": self.steps,
            "ferramentas": self.tool_calls,
            "motivo_roteamento": self.routing_reason,
            "tokens_entrada": self.input_tokens,
            "tokens_saida": self.output_tokens,
            "custo_usd_estimado": round(self.cost_usd, 6),
            "fallbacks": self.fallbacks,
        }


# --------------------------------------------------------------------------- #
# Roteamento
# --------------------------------------------------------------------------- #
def route(pergunta: str, preferido: str = "", fixado: str = "") -> tuple[list[LLMProvider], str]:
    """Devolve a fila de candidatos (o primeiro é o escolhido) e o motivo."""
    disponiveis = {p.name: p for p in providers.configured()}

    def fila(primeiro: str, motivo: str) -> tuple[list[LLMProvider], str]:
        ordem = [primeiro] + [n for n in DEFAULT_ORDER if n != primeiro]
        return [disponiveis[n] for n in ordem if n in disponiveis], motivo

    if preferido:
        if preferido in disponiveis:
            return fila(preferido, f"pedido explicitamente na requisição ({preferido})")
        provedor = providers.get(preferido)
        rotulo = provedor.label if provedor else preferido
        return fila(DEFAULT_ORDER[0], f"'{rotulo}' foi pedido mas não está configurado — caiu para a fila padrão")

    if fixado and fixado in disponiveis:
        return fila(fixado, f"fixado nesta sessão ({fixado})")

    alvo = pergunta.lower()
    for palavras, provedor, motivo in ROUTING_HINTS:
        if provedor in disponiveis and any(p in alvo for p in palavras):
            return fila(provedor, f"heurística: {motivo}")

    for nome in DEFAULT_ORDER:
        if nome in disponiveis:
            return fila(nome, f"primeiro provedor configurado da ordem padrão ({nome})")

    return [], "nenhum provedor disponível"


# --------------------------------------------------------------------------- #
# Execução
# --------------------------------------------------------------------------- #
def run(
    db: Session,
    pergunta: str,
    session_id: Optional[int] = None,
    provedor: str = "",
    modelo: str = "",
    max_steps: int = 0,
    permitir_escrita: bool = True,
    actor: str = "usuario",
) -> SupervisorResult:
    max_steps = max_steps or settings.aios_max_steps
    sessao = memory.get_or_create_session(db, session_id, title=pergunta[:200], actor=actor)

    candidatos, motivo = route(pergunta, provedor, sessao.pinned_provider)
    audit.log(
        db, sessao.id, "routing", request=pergunta,
        response={"escolhido": candidatos[0].name if candidatos else None, "motivo": motivo,
                  "fila": [c.name for c in candidatos]},
        provider=candidatos[0].name if candidatos else "",
    )
    if not candidatos:
        raise RuntimeError("Nenhum provedor de modelo disponível — nem o agente local foi registrado.")

    registro = get_registry()
    ferramentas = registro.specs(allow_writes=permitir_escrita)
    system = _montar_system(db, sessao.id)

    memory.append(db, sessao.id, Message(role="user", content=pergunta))
    mensagens = memory.history(db, sessao.id, limit=settings.aios_history_limit)

    resultado = SupervisorResult(
        answer="", session_id=sessao.id, provider="", model="", steps=0, routing_reason=motivo
    )
    ctx = ToolContext(db=db, session_id=sessao.id)

    for passo in range(1, max_steps + 1):
        resposta, provedor_usado = _chamar_com_fallback(
            db, sessao.id, candidatos, mensagens, system, ferramentas, modelo, passo, resultado
        )
        resultado.steps = passo
        resultado.provider = provedor_usado.name
        resultado.model = resposta.model
        resultado.input_tokens += resposta.usage.input_tokens
        resultado.output_tokens += resposta.usage.output_tokens
        resultado.cost_usd += provedor_usado.estimate_cost(
            resposta.usage.input_tokens, resposta.usage.output_tokens
        )

        assistente = Message(role="assistant", content=resposta.text, tool_calls=resposta.tool_calls)
        mensagens.append(assistente)
        memory.append(db, sessao.id, assistente, provider=provedor_usado.name, model=resposta.model)

        if not resposta.tool_calls:
            resultado.answer = resposta.text
            return resultado

        for chamada in resposta.tool_calls:
            saida = _executar_ferramenta(db, sessao.id, ctx, registro, chamada, passo, permitir_escrita)
            resultado.tool_calls.append({"nome": chamada.name, "argumentos": chamada.arguments})
            retorno = Message(
                role="tool", content=saida, tool_call_id=chamada.id, tool_name=chamada.name
            )
            mensagens.append(retorno)
            memory.append(db, sessao.id, retorno)

    resultado.answer = (
        resposta.text
        or f"Parei no limite de {max_steps} passos sem uma resposta final. "
        "Veja a auditoria da sessão para o que foi executado."
    )
    return resultado


def _montar_system(db: Session, session_id: int) -> str:
    fatos = memory.context_block(db, scope=str(session_id))
    if not fatos:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n\nMemória de longo prazo sobre este usuário/negócio:\n{fatos}"


def _chamar_com_fallback(
    db, session_id, candidatos, mensagens, system, ferramentas, modelo, passo, resultado
) -> tuple[LLMResponse, LLMProvider]:
    erros = []
    for i, provedor in enumerate(candidatos):
        inicio = time.monotonic()
        try:
            # `modelo` só vale para o provedor originalmente escolhido — não faz
            # sentido mandar um id de modelo da OpenAI para o Gemini.
            resposta = provedor.complete(
                mensagens, system=system, tools=ferramentas,
                model=modelo if i == 0 else "",
                max_tokens=settings.aios_max_tokens,
            )
        except ProviderError as e:
            latencia = int((time.monotonic() - inicio) * 1000)
            erros.append(str(e))
            resultado.fallbacks.append(f"{provedor.name}: {e.message}")
            audit.log(
                db, session_id, "error", step=passo, provider=provedor.name,
                request="chamada de modelo", response=str(e), latency_ms=latencia, ok=False,
            )
            continue

        latencia = int((time.monotonic() - inicio) * 1000)
        audit.log(
            db, session_id, "llm_call", step=passo, provider=provedor.name, model=resposta.model,
            request={"mensagens": len(mensagens), "ferramentas": len(ferramentas)},
            response={"texto": resposta.text[:500],
                      "ferramentas_pedidas": [c.name for c in resposta.tool_calls],
                      "stop_reason": resposta.stop_reason},
            input_tokens=resposta.usage.input_tokens,
            output_tokens=resposta.usage.output_tokens,
            cost_usd=provedor.estimate_cost(resposta.usage.input_tokens, resposta.usage.output_tokens),
            latency_ms=latencia,
        )
        return resposta, provedor

    raise RuntimeError("Todos os provedores falharam: " + "; ".join(erros))


def _executar_ferramenta(db, session_id, ctx, registro, chamada: ToolCall, passo: int, permitir_escrita: bool) -> str:
    inicio = time.monotonic()
    ferramenta = registro.get(chamada.name)

    if ferramenta is None:
        saida = {"erro": f"ferramenta desconhecida: {chamada.name}"}
        ok = False
    elif ferramenta.writes and not permitir_escrita:
        saida = {"erro": f"'{chamada.name}' escreve dados e esta sessão está em modo somente leitura"}
        ok = False
    else:
        try:
            saida = ferramenta.handler(ctx, **chamada.arguments)
            ok = True
        except TypeError as e:
            # Argumento inventado pelo modelo: devolvemos como resultado de
            # ferramenta (não como exceção) pra ele poder se corrigir sozinho.
            saida, ok = {"erro": f"argumentos inválidos: {e}"}, False
        except Exception as e:  # noqa: BLE001 — falha de ferramenta não pode derrubar o laço
            saida, ok = {"erro": f"{type(e).__name__}: {e}"}, False

    texto = saida if isinstance(saida, str) else json.dumps(saida, ensure_ascii=False, default=str)
    audit.log(
        db, session_id, "tool_call", step=passo, tool_name=chamada.name,
        request=chamada.arguments, response=texto,
        latency_ms=int((time.monotonic() - inicio) * 1000), ok=ok,
    )
    return texto
