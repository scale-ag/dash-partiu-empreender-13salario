# Dashboard de Tráfego Pago · Workshop 13 Salário (Rogério)

Dashboard **100% na nuvem** do funil de **lançamento pago** do *Workshop 13 Salário*
(cliente Rogério). Cruza o investimento de mídia paga (**Meta Ads**) com a lista de
**Compradores**, atribui cada **compra com UTM** ao anúncio de origem e calcula
**CAC, ROAS, Custo/Visita e ticket médio**. Publicado no **GitHub Pages**, reconstrói
sozinho a cada ~30 min, disparado pelo **cron-job.org** — sem depender de nenhum PC ligado.

Funil (lead = compra do ingresso): **Investimento → Impressões → Cliques → Visitas à Página → Compras → Faturamento**.

**URL pública:** `https://scale-ag.github.io/dash-partiu-empreender-13salario/`

---

## O que ela mostra

- **KPIs**: Investimento, Impressões, CPM, Cliques, CTR, CPC, Visitas à Página, Custo/Visita, **Compras**, **CAC**, Faturamento, **ROAS**, ticket médio.
- **Evolução diária**: compras/dia (barras) × investimento e CAC (linhas) + tabela diária com heatmap.
- **Distribuição das compras**: por anúncio, por forma de pagamento, por posicionamento (Stories/Reels/Feed) e faturamento por anúncio.
- **Tráfego Pago (Meta)**: funil do Meta, CTR, visitas por anúncio e hierarquia **Campanha → Conjunto → Anúncio** com Custo/Visita por dia.
- **Tabela de compras** (nome **abreviado**, pois a página é pública).
- **Toggle de imposto da mídia paga** e **modo claro/escuro**.
- **Aba Relatório**: painel de metas editável (Custo/Visita e CAC) + Top Anúncios + Insights de Tráfego (texto — ver `build/GUIA-RELATORIOS.md`).

## Regra de atribuição (só tráfego pago)

Entra no dashboard **apenas a compra com `utm_campaign` preenchido** (checkout vindo
do anúncio). Compras "direct"/orgânicas (checkout sem UTM, agente Hotmart etc.) ficam
de fora. A atribuição por anúncio usa `utm_content` (= `Ad Name` do Meta: AD01…AD06);
campanha/conjunto vêm da estrutura real do Meta para aquele anúncio. Lógica em
`build/build.py` → `process()`.

## Fontes de dados (somente leitura — duas planilhas distintas)

| Planilha / aba | gid | Uso |
|-----|-----|-----|
| **Meta Ads** — "Extração Dashboard" (`1OMB7k…`), aba **Página1** | `0` | investimento, impressões, cliques, visitas à página (LP Views) |
| **Compradores** — "Partiu Empreender \| 2026" (`1Qe1_L…`), aba **Wks 13º Salario** | `1583208180` | compras do ingresso (Data, Valor, Forma de Pagto, utm_*) |

| **Seguidores IG** — "Extração Dashboard" (`1OMB7k…`), aba **Seguidores IG** | `1003041051` | campanha de Atração de Seguidores: investimento, impressões, cliques, seguidores (col. H, manual) |

Páginas: **Visão Geral** (consolidado das duas campanhas) · **Funil de Vendas / Tráfego Pago / Relatório** (captação de leads) · **Funil Captação de Seguidores**.

O build lê as abas via **export CSV público** (`.../export?format=csv&gid=...`).
**Nada é escrito de volta** nas planilhas.

---

## Arquitetura

```
cron-job.org  ──(POST workflow_dispatch a cada 30 min)──▶  GitHub Actions
                                                              │
                          build/build.py  lê os CSVs ◀────────┘
                                 │  atribui compras (UTM) ao anúncio
                                 ▼
                          dist/index.html  ──▶  deploy  ──▶  GitHub Pages (URL pública)
```

- `build/build.py` — baixa os CSVs, atribui as compras com UTM, gera `dist/index.html`.
- `build/template.html` — layout/gráficos/tema (Chart.js via CDN).
- `.github/workflows/deploy.yml` — roda o build e publica no Pages.

**Cache-bust:** a página usa `Cache-Control: no-cache`, mostra o horário do último
build, tem botão **Atualizar** e se recarrega sozinha (`?t=timestamp`) ~30 min após
aberta — sempre pegando a versão mais nova.

## Rodar localmente (opcional)

```bash
python build/build.py --out dist/index.html            # busca os CSVs ao vivo
# ou, com arquivos locais para teste:
python build/build.py --meta-file meta.csv --sales-file compradores.csv --out dist/index.html
```

---

## Ativação (uma vez) e cron-job.org

O disparo por `workflow_dispatch` só funciona quando o workflow está na branch
**`main`**. Veja **`SETUP-CRON.md`** para o passo a passo e os valores exatos
(URL, headers e body, com marcadores a preencher) a colar no cron-job.org.

> ⚠️ **Segurança:** nunca comite tokens no repositório. Gere um token
> *fine-grained*, só com **Actions: read/write** neste repositório, e use-o
> apenas no cron-job.org (ou em GitHub Secrets, se aplicável).

## Como usar este template para um novo cliente

Veja o **CHECKLIST DE NOVO CLIENTE** no topo de `CLAUDE.md` (ou `AGENTS.md`) e
o passo a passo completo em `GUIA-REPLICACAO.md`.
