import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import streamlit as st

from app.aios import audit, memory, supervisor
from app.aios.providers import registry as providers
from app.aios.tools.registry import get_registry
from app.db import SessionLocal, init_db
from dashboard._theme import inject_base_css, require_demo_login

st.set_page_config(page_title="Assistente IA", page_icon="🤖", layout="wide")
init_db()
inject_base_css()
require_demo_login()

st.title("🤖 Assistente IA")
st.caption(
    "Camada de aplicação do AI OS: sua pergunta vai para o Supervisor, que escolhe o modelo "
    "(GPT, Claude, Gemini ou o agente local), roda as ferramentas de dados da sua loja e "
    "registra cada passo na auditoria."
)

disponiveis = providers.describe()
configurados = [p for p in disponiveis if p["configured"]]
if all(p["name"] == "local" for p in configurados):
    st.info(
        "Nenhuma chave de modelo configurada — respondendo pelo **agente local de regras**, que "
        "casa a pergunta com uma ferramenta e mostra o resultado cru. Para conversar de verdade, "
        "preencha `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` ou `GEMINI_API_KEY` no `.env`."
    )

with st.sidebar:
    st.subheader("Roteamento")
    opcoes = ["automático"] + [p["name"] for p in configurados]
    escolha = st.selectbox("Provedor", opcoes)
    permitir_escrita = st.toggle("Permitir ferramentas que escrevem", value=True)
    st.caption("Desligado, o supervisor recusa gravar memória e chamar servidores MCP.")

    st.subheader("Provedores")
    for p in disponiveis:
        marca = "✅" if p["configured"] else "⏳"
        st.markdown(f"{marca} **{p['label']}** — {', '.join(p['strengths'])}")

    st.subheader("Ferramentas")
    for t in get_registry().all_tools():
        st.markdown(f"`{t.name}` · {t.category}")

if "aios_session_id" not in st.session_state:
    st.session_state.aios_session_id = None
if "aios_chat" not in st.session_state:
    st.session_state.aios_chat = []

for papel, texto, rodape in st.session_state.aios_chat:
    with st.chat_message(papel):
        st.markdown(texto)
        if rodape:
            st.caption(rodape)

pergunta = st.chat_input("Ex.: quanto vendi nos últimos 30 dias?")
if pergunta:
    st.session_state.aios_chat.append(("user", pergunta, ""))
    with st.chat_message("user"):
        st.markdown(pergunta)

    with st.chat_message("assistant"), st.spinner("Supervisor roteando…"):
        with SessionLocal() as db:
            try:
                resultado = supervisor.run(
                    db,
                    pergunta,
                    session_id=st.session_state.aios_session_id,
                    provedor="" if escolha == "automático" else escolha,
                    permitir_escrita=permitir_escrita,
                    actor="dashboard",
                )
            except RuntimeError as e:
                st.error(str(e))
                st.stop()

        st.session_state.aios_session_id = resultado.session_id
        ferramentas = ", ".join(f["nome"] for f in resultado.tool_calls) or "nenhuma"
        rodape = (
            f"{resultado.provider} · {resultado.model} · {resultado.steps} passo(s) · "
            f"ferramentas: {ferramentas} · roteamento: {resultado.routing_reason} · "
            f"~US$ {resultado.cost_usd:.4f}"
        )
        st.markdown(resultado.answer)
        st.caption(rodape)
        st.session_state.aios_chat.append(("assistant", resultado.answer, rodape))

if st.session_state.aios_session_id:
    with st.expander("Auditoria desta conversa"):
        with SessionLocal() as db:
            totais = audit.totals(db, st.session_state.aios_session_id)
            eventos = audit.trail(db, st.session_state.aios_session_id, limit=60)
            st.json(totais)
            st.dataframe(
                [
                    {
                        "passo": e.step, "tipo": e.kind, "provedor": e.provider,
                        "modelo": e.model, "ferramenta": e.tool_name, "ok": e.ok,
                        "ms": e.latency_ms, "resposta": (e.response or "")[:160],
                    }
                    for e in reversed(eventos)
                ],
                width="stretch",
            )

    with st.expander("Memória de longo prazo"):
        with SessionLocal() as db:
            fatos = memory.recall(db, scope=str(st.session_state.aios_session_id))
        if fatos:
            st.dataframe(
                [{"chave": f.key, "valor": f.value, "escopo": f.scope or "global"} for f in fatos],
                width="stretch",
            )
        else:
            st.caption("Nada gravado ainda. Peça ao assistente para lembrar de algo.")
