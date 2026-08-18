"""
Auditoria — o último bloco do desenho.

Cada passo do supervisor vira uma linha em `ai_audit_events`: a decisão de
roteamento (com o motivo), cada chamada de modelo (com tokens, latência e custo
estimado) e cada chamada de ferramenta (com argumentos e resultado). Sem isso,
uma resposta errada do AI OS é impossível de investigar depois, porque a
escolha de modelo e as ferramentas usadas não aparecem no texto final.

Os campos `request`/`response` são texto truncado — a trilha é pra investigação
humana, não pra reprocessar a conversa (isso é papel de `ai_messages`).
"""
import json
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AIAuditEvent

MAX_LEN = 4000


def _resumir(valor) -> str:
    if valor is None:
        return ""
    texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False, default=str)
    return texto[:MAX_LEN]


def log(
    db: Session,
    session_id: Optional[int],
    kind: str,
    step: int = 0,
    provider: str = "",
    model: str = "",
    tool_name: str = "",
    request=None,
    response=None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    latency_ms: int = 0,
    ok: bool = True,
) -> AIAuditEvent:
    evento = AIAuditEvent(
        session_id=session_id,
        step=step,
        kind=kind,
        provider=provider,
        model=model,
        tool_name=tool_name,
        request=_resumir(request),
        response=_resumir(response),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        ok=ok,
    )
    db.add(evento)
    db.commit()
    db.refresh(evento)
    return evento


def trail(db: Session, session_id: Optional[int] = None, limit: int = 100) -> list[AIAuditEvent]:
    q = db.query(AIAuditEvent)
    if session_id is not None:
        q = q.filter(AIAuditEvent.session_id == session_id)
    return q.order_by(AIAuditEvent.id.desc()).limit(limit).all()


def totals(db: Session, session_id: Optional[int] = None) -> dict:
    eventos = trail(db, session_id, limit=10_000)
    return {
        "eventos": len(eventos),
        "chamadas_modelo": sum(1 for e in eventos if e.kind == "llm_call"),
        "chamadas_ferramenta": sum(1 for e in eventos if e.kind == "tool_call"),
        "erros": sum(1 for e in eventos if not e.ok),
        "tokens_entrada": sum(e.input_tokens for e in eventos),
        "tokens_saida": sum(e.output_tokens for e in eventos),
        "custo_usd_estimado": round(sum(e.cost_usd for e in eventos), 6),
    }
