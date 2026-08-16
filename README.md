# Tikodata

Dashboard de vendas da sua própria loja no **TikTok Shop** + inspiração de criativos (veja que
tipo de anúncio está com mais alcance por categoria de produto) via **Commercial Content API**
(biblioteca pública de transparência do TikTok) — inspirado na UX de ferramentas como
Kalodata/FastMoss/EchoTik/PiPiADS, mas **sem raspar dados** (isso não é algo que este projeto
faz — ver "Por que não é um clone completo" abaixo). Só APIs oficiais.

## Status atual (2026-08-16)

App **Tikodata** já criado no Partner Center (categoria Conectores, mercado Brasil/Vendedores
locais, redirect URL e escopos `seller.order.info` + `seller.authorization.info` configurados,
credenciais salvas no `.env`). **Bloqueado esperando o TikTok aprovar a avaliação de segurança e
privacidade de dados da conta** — sem isso o app não pode ser publicado, e sem publicar a
autorização falha com "Não disponível na região da sua loja" (confirmado testando). Isso é fila
de revisão do TikTok, não tem como acelerar. Quando a avaliação sair (verifique em Aplicativos e
serviços > Tikodata), clique em "Publicar" e teste `https://lvh.me:8000/oauth/login` de novo.

## Escopo

| Área | O que faz | Status |
|---|---|---|
| Dashboard de Vendas | Receita e unidades vendidas da própria loja (pedidos reais via OAuth) | Implementado |
| Inspiração de Criativos | Busca por categoria de produto na Ad Library oficial do TikTok — peça criativa, período e alcance, ordenado do maior alcance pro menor | Implementado — **só cobre Europa** |
| Pesquisa de Mercado | Criadores e produtos de **qualquer loja** via Affiliate Seller API — GMV, seguidores, unidades vendidas, comissão | Implementado — **nunca testado com OAuth real, bloqueado esperando a mesma revisão do TikTok Shop** |

## Front-end

Layout de UI/UX inspirado nas telas reais do Kalodata (Explorar, Ranking de Produto, Ranking de
Criador — vistas ao vivo em 2026-08-16), **nunca a paleta de cores deles** — mantemos nossa
paleta escura validada (`references/palette.md` do skill `dataviz`). Padrões trazidos:
- **`kalo_row`** (`dashboard/_theme.py`): linha de ranking densa — miniatura, título/subtítulo,
  métrica primária com sparkline, e uma fileira de métricas secundárias compactas. Usada em
  Inspiração de Criativos e Pesquisa de Mercado no lugar da grade de cards antiga.
- **Chips de atalho** (`st.pills`) pra buscas rápidas por categoria/GMV/comissão, e presets de
  período (Ontem/7d/30d/90d/180d) no Dashboard de Vendas — mesmo padrão de filtro do Kalodata.
- **Home como hub**: linha de acesso rápido (`st.page_link` + `st.container(border=True)`) pras
  três páginas, espelhando a fileira de atalhos do "Explorar" do Kalodata.

## Por que não é um clone completo dessas ferramentas

Kalodata, FastMoss, EchoTik, Shoplus, WinningHunter, PiPiADS e TrendTrack.io mostram vendas,
produtos e métricas de anúncios (visualizações, **gasto**, conversão) de qualquer loja/anunciante
raspando o TikTok em larga escala — o que geralmente viola os Termos de Uso da plataforma. Este
projeto só usa **APIs oficiais e públicas do TikTok**, e isso limita o que dá pra mostrar:

- **Dashboard de Vendas**: só a própria loja (TikTok Shop Partner Center) — nenhuma API oficial
  dá acesso ao histórico de pedidos de terceiros.
- **Pesquisa de Mercado** (criadores e produtos): aqui, ao contrário do que a gente tinha
  concluído antes, o TikTok Shop **tem** uma API oficial de descoberta que cobre o marketplace
  inteiro — a Affiliate Seller API (`Seller Search Creator on Marketplace` e `Seller Search
  Affiliate Open Collaboration Product`), a mesma que move o Creator Marketplace real do TikTok.
  Não precisa de certificação de faturamento (GMV) como o Mercado Livre — só ativar o escopo
  `seller.creator_marketplace.read`. A limitação real: só retorna criadores que estão no Creator
  Marketplace e produtos que a loja dona abriu pra colaboração de afiliados — não é o catálogo
  100% completo do TikTok Shop, mas é uma fatia real e grande dele, sem raspagem.
- **Inspiração de Criativos**: existe sim uma API pública e oficial pra isso (Commercial
  Content API, parte da TikTok for Developers), mas ela é uma ferramenta de **transparência
  regulatória** (exigência da lei europeia DSA), não um ad-spy: só cobre anúncios veiculados na
  **Europa** (UE/EEE + Reino Unido/Suíça) e não tem gasto nem métricas de engajamento/conversão —
  só a peça criativa, quando rodou, e uma faixa de alcance (ex.: "11K" usuários únicos).

## Arquitetura

```
tikodata/
  app/
    config.py          # variáveis de ambiente
    db.py               # engine/sessão SQLAlchemy (SQLite por padrão)
    models.py            # SellerAccount, Order, CompetitorAd, MarketplaceCreator, MarketplaceProduct
    tt_client.py          # wrapper da API do TikTok Shop (OAuth2 + assinatura HMAC + endpoints)
    adlib_client.py        # wrapper da Commercial Content API (client_credentials, sem HMAC)
    services/
      sales_dashboard.py    # sync de pedidos + resumo de vendas
      ad_library.py          # busca/track de anúncios de concorrentes (só Europa)
      marketplace_intel.py    # busca/track de criadores e produtos via Affiliate Seller API
    api.py                 # FastAPI: rotas OAuth + REST
  dashboard/
    _theme.py                # paleta validada + componentes (stat tile, sparkline, rank row, kalo_row)
    Home.py                   # Streamlit — landing page
    pages/
      1_Dashboard de Vendas.py
      2_Inspiracao de Criativos.py
      3_Pesquisa de Mercado.py
```

Mesma stack do projeto irmão [Mercadata](../mercadata) (FastAPI + SQLAlchemy + SQLite +
Streamlit) — Python porque esta máquina não tem Node.js instalado.

## Descobertas importantes (documentação oficial, verificada em 2026-08-16)

- **Onboarding tem review de conformidade em alguns mercados**: "US/UK e alguns mercados
  também exigem revisão de compliance & jurídica — reserve 3+ semanas" segundo o próprio guia
  de desenvolvedor do TikTok Shop. Não confirmei se o Brasil está nessa lista — descubra isso
  logo no início do cadastro em partner.tiktokshop.com, antes de investir tempo no resto.
- **Assinatura de requisição (HMAC-SHA256) é obrigatória em toda chamada**: `sign` é calculado
  sobre `app_secret + path + {chave}{valor} de cada query param (ordenados, exceto sign/
  access_token) + corpo da requisição (se houver) + app_secret`, via HMAC-SHA256 com o
  `app_secret` como chave. Implementado em `tt_client.py::_sign` — algoritmo copiado
  literalmente da doc oficial ("Sign your API request"), não é uma suposição.
- **`grant_type=authorized_code`, não `authorization_code`**: a doc oficial avisa
  explicitamente para não "corrigir" isso — é intencional e diferente do padrão OAuth.
- **Token de acesso vai no header, não na query**: para API versão 202309+, use o header
  `x-tts-access-token` (não `access_token` na query string, que é só para APIs legadas).
- **`shop_cipher` é obrigatório em endpoints de loja**: obtido via `GET
  /authorization/202309/shops` (`data.shops[].cipher`) depois de trocar o `auth_code` pelo
  token — sem ele, chamadas como `orders/search` não funcionam.
- **Timestamp tem janela curta**: válido apenas entre `agora - 5min` e `agora + 30s`. Se o
  relógio da máquina estiver dessincronizado, as chamadas falham.
- **Domínio de autorização depende do mercado**: usamos `services.tiktokshop.com` (ROW/resto
  do mundo — inclui Brasil). Se seu app for registrado como US, troque `TT_US_MARKET=true` no
  `.env` para usar `services.us.tiktokshop.com`.
- **A Affiliate Seller API tem busca de mercado de verdade, não só dados da própria loja** —
  descoberta em 2026-08-16, corrige uma suposição anterior deste README. Dois endpoints:
  `POST /affiliate_seller/202508/marketplace_creators/search` (escopo
  `seller.creator_marketplace.read`, filtra por GMV, unidades vendidas, seguidores, categoria —
  cobre qualquer criador do Creator Marketplace) e
  `POST /affiliate_seller/202405/open_collaborations/products/search` (filtra por palavra-chave,
  categoria, preço, comissão — cobre produtos de **qualquer loja** aberta a colaboração de
  afiliados, com `shop.name` no retorno). Ambos ainda exigem `shop_cipher` + `access_token` da
  própria loja conectada — não são endpoints anônimos — mas não têm exigência de faturamento/GMV
  pra liberar acesso, diferente do Developer Partner Program do Mercado Livre.
- **Formato exato dos itens do pedido (`line_items`) não foi confirmado**: o exemplo de
  resposta na doc oficial do "Get Order List" está truncado antes de chegar nos produtos do
  pedido. `sales_dashboard.sync_orders` foi escrito de forma defensiva — se `line_items` não
  vier no formato esperado (ou não vier), a receita do pedido (`payment.total_amount`, esse sim
  confirmado na doc) ainda é capturada como uma linha sintética, só sem o nome do produto
  correto. **Teste com uma conta real e ajuste `sales_dashboard.py` se o formato vier diferente.**

### Commercial Content API (Ad Library) — descobertas

- **É um app totalmente separado**: fica em [developers.tiktok.com](https://developers.tiktok.com)
  ("TikTok for Developers"), não em `partner.tiktokshop.com`. Precisa de outro `client_key`/
  `client_secret` (`ADLIB_CLIENT_KEY`/`ADLIB_CLIENT_SECRET` no `.env`), sem relação com as
  credenciais do TikTok Shop.
- **Acesso é bem mais fácil que o do TikTok Shop**: aberto ao público (não só pesquisador
  credenciado), aprovação em ~2 dias úteis, **sem exigência de faturamento/GMV** — bem diferente
  do Developer Partner Program do Mercado Livre ou do processo do TikTok Shop Partner Center.
  Aplique em developers.tiktok.com → Commercial Content API → "Fill up the online application
  form".
- **Autenticação é `client_credentials` simples**: `POST /v2/oauth/token/`
  (`application/x-www-form-urlencoded`: `client_key`, `client_secret`,
  `grant_type=client_credentials`) → `access_token` válido por 2h. **Sem HMAC, sem
  shop_cipher, sem autorização de usuário** — bem mais simples que a API do TikTok Shop.
- **Só cobre Europa**: `POST /v2/research/adlib/ad/query/` só retorna anúncios veiculados nos
  países listados em `adlib_client.SUPPORTED_COUNTRIES` (UE/EEE + Reino Unido/Suíça). É
  exigência da lei DSA, não uma opção de configuração.
- **Sem gasto nem engajamento**: o campo `ad.reach.unique_user_seen` vem em faixas (`"11K"`,
  `"2M"`) — não é um número exato, e não existe campo de gasto (spend) nem de
  cliques/conversão. Só dá pra saber *quem* anunciou, *o quê* (peça criativa) e *quando*.
- **`ad_published_date_range.min` precisa ser depois de 1º de outubro de 2022** — data mais
  antiga que isso é rejeitada pela API.
- **`ad_published_date_range.max` precisa ser antes de hoje** (`invalid_params` se for hoje ou
  no futuro) — `adlib_client.query_ads` usa `hoje - 1 dia` como default, não `hoje`.
- **Aprovado em 2026-08-16, mas a query real (`/v2/research/adlib/ad/query/`) devolveu
  `500 internal_error` ("Something is wrong. Please try again later.") em todas as variações de
  payload testadas** (com/sem `search_term`, com/sem `country_code`, `fields` mínimo vs. completo)
  — inclusive testado direto via `requests`, fora do Streamlit, pra descartar bug nosso. O token
  (`client_credentials`) é emitido normalmente e o projeto aparece como "Connected" em
  developers.tiktok.com → My research. Como o erro é genérico e consistente entre payloads
  diferentes, é provável atraso de propagação do acesso recém-aprovado do lado do TikTok, não um
  problema de código — **tentar de novo depois de algumas horas**. Se persistir, abrir chamado de
  suporte no portal citando um dos `log_id` retornados.

## Setup

```bash
cd ~/tikodata
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

1. ~~Crie uma conta de desenvolvedor em [partner.tiktokshop.com](https://partner.tiktokshop.com)~~
   — feito. Categoria "Conectores" aprovada para o mercado Brasil.
2. ~~Registre um app~~ — feito (app "Tikodata", ID de serviço `7673833015814293255`). Redirect
   URL `https://lvh.me:8000/oauth/callback` e escopos `seller.order.info` +
   `seller.authorization.info` já habilitados em Gerenciar API.
3. ~~Preencha `TT_APP_KEY`, `TT_APP_SECRET` e `TT_SERVICE_ID` no `.env`~~ — feito.
   **Falta:** publicar o app (bloqueado pela avaliação de segurança/privacidade — ver "Status
   atual" acima) e então testar o login de verdade.
4. Gere o certificado autoassinado (já tem um pronto em `certs/`, gerado com `openssl`;
   regenere se quiser):
   ```bash
   mkdir -p certs && openssl req -x509 -newkey rsa:2048 -keyout certs/localhost-key.pem \
     -out certs/localhost.pem -days 825 -nodes -subj "/CN=lvh.me" \
     -addext "subjectAltName=DNS:lvh.me,DNS:localhost,IP:127.0.0.1"
   ```
5. Suba a API com SSL:
   ```bash
   source .venv/bin/activate && uvicorn app.api:app --reload \
     --ssl-keyfile certs/localhost-key.pem --ssl-certfile certs/localhost.pem
   ```
   O navegador vai mostrar um aviso de certificado autoassinado na primeira visita — clique em
   "Avançado" → "Continuar mesmo assim" (é o seu próprio localhost).
6. Em outro terminal, suba o dashboard:
   ```bash
   source .venv/bin/activate && streamlit run dashboard/Home.py
   ```
7. Acesse `https://lvh.me:8000/oauth/login`, autorize com sua conta de vendedor do TikTok Shop.
8. Volte para `http://localhost:8501` — a loja aparece na Home e no Dashboard de Vendas.

### Setup — Inspiração de Criativos (Commercial Content API)

Independente do setup do TikTok Shop acima — é outro app, outro portal.

1. Crie/entre na conta em [developers.tiktok.com](https://developers.tiktok.com) com seu e-mail.
2. ~~Acesse developers.tiktok.com/products/commercial-content-api e preencha o formulário de
   aplicação~~ — feito em 2026-08-16. Resposta em até 2 dias úteis por e-mail
   (`commercial-research-questions@tiktok.com`) ou pela página "Manage apps" do portal.
3. Quando aprovado, pegue `client key` e `client secret` do seu projeto de pesquisa aprovado e
   coloque em `ADLIB_CLIENT_KEY`/`ADLIB_CLIENT_SECRET` no `.env`.
4. Com a API rodando (passo 5 acima), acesse a página "Inspiração de Criativos" no dashboard e
   busque por um termo — não precisa de login OAuth, é autenticação de app (`client_credentials`).

## Limitações conhecidas / próximos passos

- **Bloqueado por revisão do TikTok** — ver "Status atual" no topo. O fluxo OAuth foi construído
  a partir da documentação oficial e o `/oauth/login` já redireciona corretamente para o domínio
  certo com o `service_id` real, mas o teste ponta a ponta (autorizar de verdade e sincronizar
  pedidos) ainda não foi possível por causa do bloqueio de publicação.
- Formato de `line_items` não confirmado — ver descoberta acima.
- **Inspiração de Criativos: aprovado e testado com credenciais reais em 2026-08-16, mas a
  query (`/v2/research/adlib/ad/query/`) devolve `500 internal_error` consistente** — ver
  descoberta acima ("Aprovado em 2026-08-16..."). Provável atraso de propagação do lado do
  TikTok; tentar de novo mais tarde.
- **Pesquisa de Mercado (`marketplace_intel.py`, `3_Pesquisa de Mercado.py`) nunca testada com
  OAuth real** — escrita em 2026-08-16 a partir da doc oficial confirmada (request/response de
  exemplo completos pros dois endpoints), mas depende do mesmo `shop_cipher`/`access_token` de
  loja conectada que está bloqueado pela revisão de segurança/privacidade do TikTok Shop (ver
  "Status atual"). Testar assim que a revisão liberar e o OAuth funcionar de ponta a ponta.
- Sem testes automatizados — só verificação manual (servidor sobe limpo, páginas renderizam,
  estado vazio tratado sem erro).
- SQLite é suficiente para uso pessoal; migre para Postgres antes de qualquer uso multiusuário.
