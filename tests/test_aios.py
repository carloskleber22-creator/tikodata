"""
Testes do AI OS. Rodam sem nenhuma credencial: um provedor falso substitui o
LLM, e o resto (roteamento, laço de ferramentas, memória, auditoria) é o código
real, apontado para um SQLite temporário.

    python -m pytest tests/test_aios.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Precisa vir antes de importar app.db, que lê a URL na importação.
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/aios_test.db")

import pytest  # noqa: E402

from app.aios import audit, memory, supervisor  # noqa: E402
from app.aios.providers import registry as providers  # noqa: E402
from app.aios.providers.base import LLMProvider  # noqa: E402
from app.aios.schemas import LLMResponse, Message, ProviderError, ToolCall, Usage  # noqa: E402
from app.aios.tools.registry import get_registry  # noqa: E402
from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.models import Order, SellerAccount  # noqa: E402


class FakeProvider(LLMProvider):
    """Devolve as respostas roteirizadas, na ordem, e guarda o que recebeu."""

    name = "fake"
    label = "Fake"
    default_model = "fake-1"
    price_per_mtok = (1.0, 2.0)

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.recebidas: list[list[Message]] = []

    def is_configured(self):
        return True

    def complete(self, messages, system="", tools=None, model="", max_tokens=4096):
        self.recebidas.append(list(messages))
        resposta = self.roteiro.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def resposta(texto="", chamadas=()):
    return LLMResponse(text=texto, tool_calls=list(chamadas), usage=Usage(100, 50), model="fake-1", provider="fake")


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    sessao = SessionLocal()
    yield sessao
    sessao.close()


@pytest.fixture()
def loja_com_pedidos(db):
    from datetime import datetime, timedelta

    seller = SellerAccount(
        open_id="test-0001", seller_name="Loja Teste", access_token="x", refresh_token="y",
        access_token_expires_at=datetime.utcnow() + timedelta(days=7),
        refresh_token_expires_at=datetime.utcnow() + timedelta(days=30),
        shop_cipher="cipher", shop_name="Loja Teste",
    )
    db.add(seller)
    db.commit()
    db.add_all([
        Order(seller_account_id=seller.id, tt_order_id=f"o{i}", product_name="Fone Bluetooth",
              quantity=2, total_amount=100.0, currency="BRL", status="COMPLETED",
              create_time=datetime.utcnow() - timedelta(days=i))
        for i in range(3)
    ])
    db.commit()
    return seller


def usar(monkeypatch, provedor, nome="fake"):
    """Coloca um provedor falso no registro e na fila de roteamento."""
    monkeypatch.setattr(providers, "_PROVIDERS", {nome: provedor})
    monkeypatch.setattr(supervisor, "DEFAULT_ORDER", (nome,))
    return provedor


# --------------------------------------------------------------------------- #
# Roteamento
# --------------------------------------------------------------------------- #
def test_roteia_por_heuristica_de_codigo():
    fila, motivo = supervisor.route("tem um bug no meu código de sync")
    assert fila and fila[0].name == "claude" or not fila or fila[0].name == "local"
    # Sem chave nenhuma configurada só sobra o agente local — e o motivo diz isso.
    assert motivo


def test_provedor_pedido_mas_nao_configurado_cai_para_a_fila_padrao():
    _, motivo = supervisor.route("quanto vendi?", preferido="gpt")
    assert "não está configurado" in motivo


def test_agente_local_sempre_disponivel():
    nomes = [p.name for p in providers.configured()]
    assert "local" in nomes


# --------------------------------------------------------------------------- #
# Laço de ferramentas
# --------------------------------------------------------------------------- #
def test_laco_executa_ferramenta_e_devolve_resposta_final(db, loja_com_pedidos, monkeypatch):
    fake = usar(monkeypatch, FakeProvider([
        resposta(chamadas=[ToolCall(id="c1", name="vendas_resumo", arguments={"dias": 30})]),
        resposta(texto="Você faturou R$ 300,00 com 6 unidades nos últimos 30 dias."),
    ]))

    r = supervisor.run(db, "quanto vendi nos últimos 30 dias?")

    assert r.steps == 2
    assert r.tool_calls == [{"nome": "vendas_resumo", "argumentos": {"dias": 30}}]
    assert "300" in r.answer
    # O resultado da ferramenta chegou de volta ao modelo na segunda rodada.
    ultima_rodada = fake.recebidas[-1]
    tool_msg = [m for m in ultima_rodada if m.role == "tool"][0]
    assert json.loads(tool_msg.content)["receita"] == 300.0


def test_ferramenta_desconhecida_volta_como_erro_e_nao_derruba(db, monkeypatch):
    usar(monkeypatch, FakeProvider([
        resposta(chamadas=[ToolCall(id="c1", name="nao_existe", arguments={})]),
        resposta(texto="Essa ferramenta não existe."),
    ]))
    r = supervisor.run(db, "faz algo impossível")
    assert r.answer == "Essa ferramenta não existe."
    erros = [e for e in audit.trail(db, r.session_id) if e.kind == "tool_call" and not e.ok]
    assert erros and "desconhecida" in erros[0].response


def test_modo_somente_leitura_bloqueia_ferramenta_que_escreve(db, monkeypatch):
    usar(monkeypatch, FakeProvider([
        resposta(chamadas=[ToolCall(id="c1", name="memoria_gravar",
                                    arguments={"chave": "x", "valor": "y"})]),
        resposta(texto="Não consigo gravar em modo somente leitura."),
    ]))
    r = supervisor.run(db, "grava isso na memória", permitir_escrita=False)
    assert memory.recall(db, "x") == []
    assert "somente leitura" in r.answer or "somente leitura" in str(r.tool_calls)


def test_teto_de_passos_encerra_o_laco(db, loja_com_pedidos, monkeypatch):
    # Modelo teimoso: pede ferramenta pra sempre.
    class Teimoso(FakeProvider):
        def complete(self, messages, system="", tools=None, model="", max_tokens=4096):
            return resposta(chamadas=[ToolCall(id=f"c{len(messages)}", name="listar_lojas", arguments={})])

    usar(monkeypatch, Teimoso([]))
    r = supervisor.run(db, "lista as lojas", max_steps=3)
    assert r.steps == 3
    assert "limite de 3 passos" in r.answer


# --------------------------------------------------------------------------- #
# Fallback entre provedores
# --------------------------------------------------------------------------- #
def test_cai_para_o_proximo_provedor_quando_o_primeiro_falha(db, monkeypatch):
    quebrado = FakeProvider([ProviderError("quebrado", "500 do servidor")])
    quebrado.name = "quebrado"
    bom = FakeProvider([resposta(texto="respondi eu")])
    bom.name = "bom"
    monkeypatch.setattr(providers, "_PROVIDERS", {"quebrado": quebrado, "bom": bom})
    monkeypatch.setattr(supervisor, "DEFAULT_ORDER", ("quebrado", "bom"))

    r = supervisor.run(db, "oi")
    assert r.provider == "bom"
    assert r.answer == "respondi eu"
    assert r.fallbacks == ["quebrado: 500 do servidor"]


# --------------------------------------------------------------------------- #
# Memória e auditoria
# --------------------------------------------------------------------------- #
def test_memoria_de_curto_prazo_volta_na_proxima_pergunta(db, monkeypatch):
    fake = usar(monkeypatch, FakeProvider([resposta(texto="oi"), resposta(texto="de novo")]))
    r1 = supervisor.run(db, "primeira pergunta")
    supervisor.run(db, "segunda pergunta", session_id=r1.session_id)
    papeis = [(m.role, m.content) for m in fake.recebidas[-1]]
    assert ("user", "primeira pergunta") in papeis
    assert ("assistant", "oi") in papeis


def test_fato_de_longo_prazo_entra_no_system_prompt(db):
    memory.remember(db, "nicho", "eletrônicos", scope="")
    assert "nicho: eletrônicos" in supervisor._montar_system(db, session_id=1)


def test_historico_descarta_chamada_de_ferramenta_orfa(db):
    sessao = memory.get_or_create_session(db, None)
    memory.append(db, sessao.id, Message(role="assistant", content="",
                                         tool_calls=[ToolCall("c1", "listar_lojas", {})]))
    memory.append(db, sessao.id, Message(role="tool", content="{}", tool_call_id="c9", tool_name="outra"))
    historico = memory.history(db, sessao.id)
    # O resultado órfão some, e o pedido sem resposta também — nenhum provedor aceita os dois.
    assert historico == []


def test_auditoria_registra_roteamento_modelo_e_ferramenta(db, loja_com_pedidos, monkeypatch):
    usar(monkeypatch, FakeProvider([
        resposta(chamadas=[ToolCall(id="c1", name="listar_lojas", arguments={})]),
        resposta(texto="pronto"),
    ]))
    r = supervisor.run(db, "quais lojas estão conectadas?")
    tipos = {e.kind for e in audit.trail(db, r.session_id)}
    assert {"routing", "llm_call", "tool_call"} <= tipos
    totais = audit.totals(db, r.session_id)
    assert totais["chamadas_modelo"] == 2 and totais["chamadas_ferramenta"] == 1
    # Custo estimado usa o preço declarado do provedor: 2 chamadas de 100/50 tokens.
    assert totais["custo_usd_estimado"] == pytest.approx((100 * 1.0 + 50 * 2.0) * 2 / 1_000_000)


# --------------------------------------------------------------------------- #
# Ferramentas
# --------------------------------------------------------------------------- #
def test_ferramenta_de_arquivo_nao_sai_do_projeto(db):
    ler = get_registry().get("arquivo_ler")
    from app.aios.tools.registry import ToolContext

    fora = ler.handler(ToolContext(db=db), caminho="../../etc/passwd")
    assert "erro" in fora


def test_http_get_desligado_sem_allowlist(db):
    from app.aios.tools.registry import ToolContext

    saida = get_registry().get("http_get").handler(ToolContext(db=db), url="https://exemplo.com")
    assert "AIOS_HTTP_ALLOWLIST" in saida["erro"]


def test_agente_local_responde_sem_nenhuma_chave(db, loja_com_pedidos):
    r = supervisor.run(db, "quanto vendi nos últimos 30 dias?", provedor="local")
    assert r.provider == "local"
    assert "receita" in r.answer  # veio do JSON da ferramenta vendas_resumo
