"""
Memória — o bloco "Memória + Banco" do desenho.

Dois níveis, de propósito:

- **Curto prazo**: as mensagens da sessão (`AIMessage`), que voltam inteiras
  para o modelo a cada turno, cortadas nas N últimas para não estourar o
  contexto (e o custo).
- **Longo prazo**: fatos (`AIMemoryFact`) que o supervisor grava explicitamente
  via ferramenta e que entram no prompt de sistema de toda sessão seguinte.

Não há embeddings/busca vetorial aqui: com o volume deste projeto, `LIKE` no
SQLite resolve, e a alternativa exigiria mais uma dependência e um índice pra
manter. Se a memória crescer a ponto de o `LIKE` não dar conta, é aí que trocar.
"""
import json
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.aios.schemas import Message, ToolCall
from app.models import AIMemoryFact, AIMessage, AISession


# --------------------------------------------------------------------------- #
# Sessões e mensagens (curto prazo)
# --------------------------------------------------------------------------- #
def get_or_create_session(db: Session, session_id: Optional[int], title: str = "", actor: str = "usuario") -> AISession:
    if session_id is not None:
        sessao = db.query(AISession).filter(AISession.id == session_id).one_or_none()
        if sessao is not None:
            return sessao
    sessao = AISession(title=title[:200], actor=actor)
    db.add(sessao)
    db.commit()
    db.refresh(sessao)
    return sessao


def append(db: Session, session_id: int, message: Message, provider: str = "", model: str = "") -> AIMessage:
    linha = AIMessage(
        session_id=session_id,
        role=message.role,
        content=message.content,
        tool_calls_json=json.dumps(
            [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in message.tool_calls], ensure_ascii=False
        )
        if message.tool_calls
        else "",
        tool_call_id=message.tool_call_id,
        tool_name=message.tool_name,
        provider=provider,
        model=model,
    )
    db.add(linha)
    db.commit()
    return linha


def history(db: Session, session_id: int, limit: int = 40) -> list[Message]:
    """Últimas mensagens da sessão, em ordem cronológica e no formato neutro."""
    linhas = (
        db.query(AIMessage)
        .filter(AIMessage.session_id == session_id)
        .order_by(AIMessage.id.desc())
        .limit(limit)
        .all()
    )
    mensagens = []
    for linha in reversed(linhas):
        chamadas = [ToolCall(**c) for c in json.loads(linha.tool_calls_json)] if linha.tool_calls_json else []
        mensagens.append(
            Message(
                role=linha.role,
                content=linha.content,
                tool_calls=chamadas,
                tool_call_id=linha.tool_call_id,
                tool_name=linha.tool_name,
            )
        )
    return _drop_dangling_tool_calls(mensagens)


def _drop_dangling_tool_calls(mensagens: list[Message]) -> list[Message]:
    """O corte pelas N últimas pode deixar um resultado de ferramenta órfão (sem
    o pedido correspondente) ou um pedido sem resultado — os três provedores
    rejeitam os dois casos. Aqui limpamos as duas pontas."""
    ids_pedidos = {c.id for m in mensagens for c in m.tool_calls}
    limpo = [m for m in mensagens if m.role != "tool" or m.tool_call_id in ids_pedidos]
    ids_respondidos = {m.tool_call_id for m in limpo if m.role == "tool"}
    return [
        m
        for m in limpo
        if not (m.role == "assistant" and m.tool_calls and not any(c.id in ids_respondidos for c in m.tool_calls))
    ]


# --------------------------------------------------------------------------- #
# Fatos (longo prazo)
# --------------------------------------------------------------------------- #
def remember(db: Session, key: str, value: str, scope: str = "", source: str = "supervisor") -> AIMemoryFact:
    fato = (
        db.query(AIMemoryFact)
        .filter(AIMemoryFact.scope == scope, AIMemoryFact.key == key)
        .one_or_none()
    )
    if fato is None:
        fato = AIMemoryFact(scope=scope, key=key, source=source)
        db.add(fato)
    fato.value = value
    fato.source = source
    db.commit()
    db.refresh(fato)
    return fato


def recall(db: Session, query: str = "", scope: str = "", limit: int = 20) -> list[AIMemoryFact]:
    """Fatos globais + os da sessão indicada, filtrados por texto."""
    q = db.query(AIMemoryFact).filter(or_(AIMemoryFact.scope == "", AIMemoryFact.scope == scope))
    if query:
        alvo = f"%{query}%"
        q = q.filter(or_(AIMemoryFact.key.ilike(alvo), AIMemoryFact.value.ilike(alvo)))
    return q.order_by(AIMemoryFact.updated_at.desc()).limit(limit).all()


def context_block(db: Session, scope: str = "", limit: int = 15) -> str:
    """Fatos formatados pra entrar no prompt de sistema."""
    fatos = recall(db, scope=scope, limit=limit)
    if not fatos:
        return ""
    return "\n".join(f"- {f.key}: {f.value}" for f in fatos)
