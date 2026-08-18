"""
Rotas HTTP do AI OS — a camada "AI OS API" do desenho.

É a única porta de entrada: usuário e aplicação falam com estes endpoints, e
tudo abaixo (supervisor, provedores, ferramentas, memória, auditoria) é interno.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.aios import audit, memory, supervisor
from app.aios.providers import registry as providers
from app.aios.tools.registry import get_registry
from app.db import get_db
from app.models import AISession

router = APIRouter(prefix="/api/ai", tags=["AI OS"])


class ChatRequest(BaseModel):
    mensagem: str = Field(..., min_length=1)
    session_id: Optional[int] = None
    provedor: str = ""  # gpt | claude | gemini | local — vazio deixa o supervisor decidir
    modelo: str = ""
    max_steps: int = 0
    permitir_escrita: bool = True
    actor: str = "usuario"


class MemoriaRequest(BaseModel):
    chave: str
    valor: str
    escopo: str = ""  # vazio = global


@router.get("/providers")
def listar_provedores():
    """Quem está disponível pra rotear, e o que está só declarado mas sem chave."""
    return providers.describe()


@router.get("/tools")
def listar_ferramentas():
    registro = get_registry()
    return [
        {"nome": t.name, "descricao": t.description, "categoria": t.category,
         "escreve": t.writes, "parametros": t.parameters}
        for t in registro.all_tools()
    ]


@router.post("/chat")
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    try:
        resultado = supervisor.run(
            db,
            req.mensagem,
            session_id=req.session_id,
            provedor=req.provedor,
            modelo=req.modelo,
            max_steps=req.max_steps,
            permitir_escrita=req.permitir_escrita,
            actor=req.actor,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return resultado.to_dict()


@router.get("/sessions")
def listar_sessoes(db: Session = Depends(get_db), limit: int = 50):
    sessoes = db.query(AISession).order_by(AISession.id.desc()).limit(limit).all()
    return [
        {"id": s.id, "titulo": s.title, "actor": s.actor, "provedor_fixado": s.pinned_provider,
         "criada_em": s.created_at, "mensagens": len(s.messages)}
        for s in sessoes
    ]


@router.get("/sessions/{session_id}/messages")
def mensagens_da_sessao(session_id: int, db: Session = Depends(get_db), limit: int = 100):
    sessao = db.query(AISession).filter(AISession.id == session_id).one_or_none()
    if sessao is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    return [
        {"papel": m.role, "conteudo": m.content, "ferramenta": m.tool_name,
         "provedor": m.provider, "modelo": m.model, "criada_em": m.created_at}
        for m in sessao.messages[-limit:]
    ]


@router.get("/audit")
def trilha_de_auditoria(session_id: Optional[int] = None, limit: int = 100, db: Session = Depends(get_db)):
    eventos = audit.trail(db, session_id, limit)
    return {
        "totais": audit.totals(db, session_id),
        "eventos": [
            {"id": e.id, "session_id": e.session_id, "passo": e.step, "tipo": e.kind,
             "provedor": e.provider, "modelo": e.model, "ferramenta": e.tool_name,
             "requisicao": e.request, "resposta": e.response,
             "tokens_entrada": e.input_tokens, "tokens_saida": e.output_tokens,
             "custo_usd": e.cost_usd, "latencia_ms": e.latency_ms, "ok": e.ok,
             "criado_em": e.created_at}
            for e in eventos
        ],
    }


@router.get("/memory")
def listar_memoria(consulta: str = "", escopo: str = "", db: Session = Depends(get_db)):
    return [
        {"chave": f.key, "valor": f.value, "escopo": f.scope or "global",
         "origem": f.source, "atualizado_em": f.updated_at}
        for f in memory.recall(db, consulta, escopo)
    ]


@router.post("/memory")
def gravar_memoria(req: MemoriaRequest, db: Session = Depends(get_db)):
    fato = memory.remember(db, req.chave, req.valor, scope=req.escopo, source="usuario")
    return {"gravado": True, "chave": fato.key, "escopo": fato.scope or "global"}
