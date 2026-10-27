#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera a dashboard estatica (index.html) do funil de LANCAMENTO PAGO
"Workshop 13 Salario" (cliente Rogerio). Funil direto, SEM captura de lead/MQL:

    Anuncio -> Pagina -> Checkout -> Compra

Ou seja, "o lead e a venda do ingresso". Duas planilhas DISTINTAS, somente leitura:

  - Meta Ads (SPREADSHEET_ID_META, aba "Pagina1", gid GID_META): investimento,
    impressoes, cliques e visitas a pagina (Landing Page Views) do gerenciador.
  - Compradores (SPREADSHEET_ID_SALES, aba "Wks 13o Salario", gid GID_SALES):
    uma linha por COMPRA do ingresso (Data, Nome, Valor da Compra, Forma de
    Pagto, utm_*). Cada compra vira um registro em sales[] (e tambem em leads[],
    pois lead = compra), na DATA REAL da compra.

Atribuicao por anuncio: usa as colunas utm_campaign/utm_medium/utm_content da
aba de Compradores QUANDO preenchidas. Hoje o checkout vem como "direct" (utm
vazio), entao toda compra entra nos TOTAIS (Visao Geral) como "(sem campanha)" /
src="org" — nao e atribuivel a campanha/anuncio do Meta (some apenas da quebra
por anuncio da aba de midia paga). Se o cliente passar a taguear os links, a
atribuicao por campanha/conjunto/anuncio passa a funcionar sozinha.

Este script apenas LE as planilhas (export CSV publico) e emite os REGISTROS
BRUTOS (leads[], meta[] e sales[]) dentro do HTML. Todos os filtros, agregacoes,
KPIs, tabelas e graficos sao calculados no navegador (client-side). Nunca
escreve nada de volta.

Teste local: --meta-file / --sales-file apontando para CSVs baixados.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

# Duas planilhas DISTINTAS (Meta Ads e Compradores ficam em arquivos separados).
SPREADSHEET_ID_META  = "11b9DiHAcYrNCAOg-egnpYf3y3kbrBM-gzFa16qBOwBc"  # planilha nova (Meta vendas + Seguidores)
GID_META  = "0"            # aba "Compradores 13 salario" (conteúdo = Meta Ads da campanha de vendas)
GID_SEG   = "954641868"    # aba "Seguidores" (mesma planilha): campanha de Atração de Seguidores
SPREADSHEET_ID_SALES = "1Qe1_LFcrd98hhOTa5rJAL78ZRUoHCZ-Pj4kIRgdiljI"  # "Partiu Empreender | 2026"
GID_SALES = "1583208180"   # aba "Wks 13º Salario" (Compradores: Data/Nome/Valor da Compra/Forma de Pagto/utm_*)
EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"

# Identificação do cliente/conta (usada só em textos/relatórios — não afeta o cruzamento de dados).
CLIENT_NAME = "Rogério"
MAIN_PRODUCT = "Workshop 13 Salário"
# Sigla/prefixo comum às campanhas do funil (vem do Campaign Name do Meta Ads:
# "W-13S | E4-VEN | P1-QUENTE | …"). Usado para agrupar campanhas no dashboard.
MAIN_PRODUCT_PREFIX = "W-13S"

BRT = timezone(timedelta(hours=-3))   # horario de Brasilia (exibicao)
TAX_FACTOR = 1.13806   # fator padrão de imposto/taxa sobre o gasto de mídia paga (Meta Ads) = 13,806%.
                       # Default do template para toda nova dash criada a partir dele; ajuste apenas
                       # se o cliente tiver um fator diferente, ou use 1.0 se não houver imposto.

# --------------------------------------------------------------------------- #
# Regras da aba Relatório (Top/Piores anúncios)
# --------------------------------------------------------------------------- #
# Amostra mínima para julgar um anúncio como "vencedor" ou "ruim". Abaixo disso
# ele entra como "Em observação" (dado insuficiente). Neste funil de tráfego o
# resultado medido por anúncio é a VISITA à página (Landing Page View) e o
# Custo/Visita (CPV) — não há etapa de MQL.
SAMPLE_MIN_SPEND = 50.0    # gasto mínimo (R$) para amostra relevante
SAMPLE_MIN_MQLS = 50       # VISITAS mínimas p/ julgar o anúncio (reaproveita o slot "mqls")
TOP_ADS_N = 10             # nº de linhas em Top / Piores anúncios

# Metas & parâmetros da conta (DEFAULTS do painel editável da aba Relatório).
# São só o valor inicial: o usuário edita no navegador (persistido em
# localStorage) e as tabelas de anúncios recoram CPV/CAC e reavaliam a amostra
# ao vivo. None = "meta não definida" (métrica aparece sem cor até o gestor
# preencher). O slot "meta_cpmql" é reaproveitado como Meta de Custo/Visita (CPV).
META_CPMQL = None          # meta de Custo/Visita — R$/visita (None = não definida)
META_CAC = None            # meta de CAC — R$/compra (None = não definida)
VOLUME_MIN_AMOSTRAL = SAMPLE_MIN_MQLS  # visitas mínimas p/ amostra confiável do anúncio
N_DIAS_CORTE = 5           # dias consecutivos acima do teto p/ considerar corte


# --------------------------------------------------------------------------- #
# Leitura
# --------------------------------------------------------------------------- #
FETCH_RETRIES = 3       # tentativas totais em caso de timeout/erro de rede no export CSV
FETCH_RETRY_DELAY = 15  # segundos entre tentativas (o Google Sheets às vezes trava a resposta)


def fetch_csv(url: str) -> list[list[str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "dash-template-bot/1.0"})
    last_err: Exception | None = None
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            return list(csv.reader(io.StringIO(raw)))
        except (TimeoutError, urllib.error.URLError) as exc:
            last_err = exc
            if attempt < FETCH_RETRIES:
                print(f"[fetch_csv] tentativa {attempt}/{FETCH_RETRIES} falhou ({exc!r}); "
                      f"tentando de novo em {FETCH_RETRY_DELAY}s...", file=sys.stderr)
                time.sleep(FETCH_RETRY_DELAY)
    raise last_err


def read_csv_file(path: str) -> list[list[str]]:
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.reader(f))


def load_rows(url: str, local: str | None) -> list[list[str]]:
    return read_csv_file(local) if local else fetch_csv(url)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str | None) -> str:
    return strip_accents((s or "").strip().lower())


def to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v).strip())
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_date(v: str) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # dd/mm/aaaa (compradores vêm como "7/10/2026 19:01" ou "09/10/2026, 08:18:31"
    # — pega só a data, ignorando a hora que vier depois). Formato BR: dia/mês/ano.
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d/%m/%y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def is_test_lead(rowtext: str) -> bool:
    return "<test lead" in rowtext.lower()


# Funil de lançamento pago: NÃO há etapa de qualificação (MQL). O "lead" é a
# própria compra do ingresso, então toda compra de tráfego conta como conversão
# (q=1). Mantido como função só para compatibilidade com o restante do pipeline.
def is_medico(v: str | None) -> bool:
    """Sem critério de MQL neste funil — toda compra de tráfego é conversão."""
    return True


def pretty_specialty(v: str) -> str:
    s = (v or "").strip()
    return s if s else "Sem resposta"


def mask_email(e: str) -> str:
    e = (e or "").strip()
    if "@" not in e:
        return "—"
    user, dom = e.split("@", 1)
    keep = user[:2] if len(user) > 2 else user[:1]
    return f"{keep}****@{dom}"


def mask_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p or "")
    return f"…{digits[-4:]}" if len(digits) >= 4 else "—"


def norm_phone(p: str) -> str:
    return re.sub(r"\D", "", p or "")


def canon_phone(p: str) -> str:
    """Chave CANÔNICA de telefone p/ cruzar Compradores × Conversas, robusta às
    3 variações que faziam o mesmo número não bater quando comparado só por
    dígitos (norm_phone):
      - DDI "55" presente de um lado e ausente do outro
        (5511988887777 vs 11988887777);
      - 9º dígito do celular presente/ausente
        (11988887777 vs 1188887777);
      - máscara/espacos/parênteses (já removidos por norm_phone).
    Estratégia: remove o DDI 55 (quando sobra DDD+número) e usa DDD (2 díg.) +
    ÚLTIMOS 8 DÍGITOS — que é o mesmo com ou sem o 9. Devolve chave de 10 díg.
    (DDD+8). Números curtos/estrangeiros (< 10 díg. após limpar) voltam como
    estão, pra não colidir à toa."""
    d = norm_phone(p)
    if len(d) > 11 and d.startswith("55"):
        d = d[2:]            # tira DDI do Brasil, sobrando DDD + local
    if len(d) >= 10:
        return d[:2] + d[-8:]   # DDD + últimos 8 (drop do 9º dígito, se houver)
    return d


def first_last_initial(name: str) -> str:
    parts = (name or "").strip().split()
    if not parts:
        return "—"
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][:1]}."


def valid_utm(campaign: str) -> bool:
    c = norm(campaign)
    return bool(c) and c not in ("-", "—", "nao encontrado")


# --------------------------------------------------------------------------- #
# Indexacao das colunas
# --------------------------------------------------------------------------- #
def header_index(header, wanted, fallback):
    idx = {}
    hn = [norm(h) for h in header]
    for key, aliases in wanted.items():
        found = None
        for a in aliases:
            a = norm(a)
            for i, h in enumerate(hn):
                if h == a or (a and a in h):
                    found = i
                    break
            if found is not None:
                break
        idx[key] = found if found is not None else fallback.get(key)
    return idx


def cell(row, i):
    if i is None or i < 0 or i >= len(row):
        return ""
    return (row[i] or "").strip()


# --------------------------------------------------------------------------- #
# Processamento -> registros brutos (lançamento pago: lead = compra do ingresso)
# --------------------------------------------------------------------------- #
def placement_label(v):
    """Posicionamento a partir do utm_medium dos compradores
    ("Instagram_Stories" / "Instagram_Reels" / "Instagram_Feed"). Fallback: valor cru."""
    s = norm(v)
    if "stories" in s or "story" in s:
        return "Stories"
    if "reels" in s or "reel" in s:
        return "Reels"
    if "feed" in s:
        return "Feed"
    return "Outros"


def process_seguidores(seg_rows):
    """Aba "Seguidores IG" (campanha de Atração de Seguidores, mesma planilha do Meta).
    Colunas: Day · Campaign Name · Ad Set Name · Ad Set ID · Impressions ·
    Amount Spent · Link Clicks · Seguidores (H) · Custo por Seguidor (I).
    Seguidores é preenchido à mão: célula VAZIA conta como 0 seguidores naquele
    dia/criativo (o gasto continua contando). O custo por seguidor NÃO é lido da
    coluna I — é recalculado como gasto ÷ seguidores, para somar certo em qualquer
    período (e dar "-" quando o período/criativo teve 0 seguidores).
    O criativo é o último trecho do Ad Set Name ("... | Reels07" -> "Reels07")."""
    if not seg_rows:
        return []
    idx = header_index(
        seg_rows[0],
        {"day": ["day", "data"], "campaign": ["campaign name", "campaign"],
         "adset": ["ad set name"], "impr": ["impressions"], "spent": ["amount spent", "valor gasto"],
         "clicks": ["link clicks", "cliques"], "seg": ["seguidores"]},
        {"day": 0, "campaign": 1, "adset": 2, "impr": 4, "spent": 5, "clicks": 6, "seg": 7},
    )
    out = []
    for row in seg_rows[1:]:
        if not any((c or "").strip() for c in row):
            continue
        d = parse_date(cell(row, idx["day"]))
        if not d:
            continue
        adset = cell(row, idx["adset"]) or "(sem conjunto)"
        creative = adset.split("|")[-1].strip() or adset
        seg_raw = cell(row, idx["seg"])
        out.append({
            "d": d,
            "camp": cell(row, idx["campaign"]) or "(sem campanha)",
            "adset": adset,
            "ad": creative,
            "sp": round(to_float(cell(row, idx["spent"])), 4),
            "im": to_float(cell(row, idx["impr"])),
            "cl": to_float(cell(row, idx["clicks"])),
            "seg": to_float(seg_raw),
            "inf": 1 if seg_raw else 0,   # 1 = célula preenchida na planilha
        })
    return out


def process(meta_rows, sales_rows, seg_rows=None):
    seg = process_seguidores(seg_rows)
    # ---- Meta Ads (investimento / impressões / cliques / visitas à página) ----
    mheader = meta_rows[0] if meta_rows else []
    midx = header_index(
        mheader,
        {"day": ["day", "data"], "campaign": ["campaign name", "campaign"], "adset": ["ad set name", "adset"],
         "ad": ["ad name"], "spent": ["amount spent", "valor gasto", "gasto"], "impr": ["impressions", "impress"],
         "clicks": ["link clicks", "clicks", "cliques"],
         "pv": ["landing page views", "page views", "pageviews"],
         # colunas opcionais (não existem nesta conta hoje) — ficam 0 / "—":
         "chk": ["adds to cart", "add to cart", "initiate checkout", "checkouts iniciados", "checkouts"],
         "link": ["creative instagram permalink", "instagram permalink", "permalink",
                  "creative link", "link do anuncio", "link do criativo"]},
        {"day": 0, "campaign": 1, "adset": 2, "ad": 3, "impr": 4, "clicks": 5, "pv": 6, "spent": 7},
    )

    meta = []
    ad_links = {}
    # Anúncio (Ad Name) -> {(camp, adset): gasto} p/ achar a campanha/conjunto
    # DOMINANTES (maior gasto) de cada anúncio. Usado para alinhar a compra
    # atribuída por utm_content à estrutura real do Meta (ver abaixo).
    ad_spend = {}
    for row in meta_rows[1:]:
        if not any((c or "").strip() for c in row):
            continue
        ad = cell(row, midx["ad"]) or "(sem anúncio)"
        camp = cell(row, midx["campaign"]) or "(sem campanha)"
        adset = cell(row, midx["adset"]) or "(sem conjunto)"
        sp = round(to_float(cell(row, midx["spent"])), 4)
        link = cell(row, midx["link"])
        if link and ad not in ad_links:
            ad_links[ad] = link
        ad_spend.setdefault(ad, {})
        ad_spend[ad][(camp, adset)] = ad_spend[ad].get((camp, adset), 0.0) + sp
        meta.append({
            "d": parse_date(cell(row, midx["day"])),
            "camp": camp,
            "adset": adset,
            "ad": ad,
            "sp": sp,
            "im": to_float(cell(row, midx["impr"])),
            "cl": to_float(cell(row, midx["clicks"])),
            "pv": to_float(cell(row, midx["pv"])),
            "ck": to_float(cell(row, midx["chk"])),
            "ml": 0.0,
        })
    # Anúncio -> (campanha, conjunto) de MAIOR gasto no Meta (estrutura canônica).
    ad_struct = {ad: max(combos.items(), key=lambda kv: kv[1])[0] for ad, combos in ad_spend.items()}

    # ---- Compradores: SÓ as compras COM UTM (= tráfego pago) ----
    # Regra do cliente: entram apenas as compras cujo checkout trouxe UTM
    # (utm_campaign preenchido) — essas vieram do anúncio. As demais (checkout
    # "direct", agente Hotmart, etc.) são orgânicas/outros canais e NÃO entram no
    # dashboard. Cada compra vira um registro em sales[] e em leads[] (lead =
    # compra), na DATA REAL da compra. Atribuição: utm_content = Ad Name do Meta
    # (AD01…AD06); camp/adset vêm da estrutura real do Meta p/ aquele anúncio
    # (ad_struct), caindo para os próprios utm_* se o anúncio não existir no Meta.
    sheader = sales_rows[0] if sales_rows else []
    sidx = header_index(
        sheader,
        {"date": ["data"], "name": ["nome"],
         "value": ["valor da compra", "valor", "faturamento"],
         "pay": ["forma de pagto", "forma de pagamento", "forma"],
         "usrc": ["utm_source", "utm source"], "ucamp": ["utm_campaign", "utm campaign"],
         "umed": ["utm_medium", "utm medium"], "ucont": ["utm_content", "utm content"]},
        {"date": 0, "name": 1, "value": 3, "pay": 4, "usrc": 5, "ucamp": 6, "umed": 7, "ucont": 8},
    )

    leads = []
    sales = []
    compras_total = 0
    compras_sem_utm = 0
    for row in sales_rows[1:]:
        if not any((c or "").strip() for c in row):
            continue
        compras_total += 1
        ucamp = cell(row, sidx["ucamp"])
        if not valid_utm(ucamp):          # só tráfego pago (compra COM UTM)
            compras_sem_utm += 1
            continue
        d = parse_date(cell(row, sidx["date"]))
        val = round(to_float(cell(row, sidx["value"])), 2)
        pay = cell(row, sidx["pay"]) or "—"
        ad = cell(row, sidx["ucont"]) or "(sem anúncio)"
        if ad in ad_struct:
            camp, adset = ad_struct[ad]
        else:
            camp = ucamp
            adset = cell(row, sidx["umed"]) or "(sem conjunto)"
        plat = placement_label(cell(row, sidx["umed"]))
        leads.append({
            "d": d, "src": "meta", "plat": plat,
            "camp": camp, "adset": adset, "ad": ad,
            "prof": pay, "bucket": pay, "q": 1, "utm": 1,
            "nm": first_last_initial(cell(row, sidx["name"])), "em": "—", "ph": "—",
            "val": val,
        })
        sales.append({
            "d": d, "src": "meta", "camp": camp, "adset": adset, "ad": ad,
            "vendas": 1, "fat": val, "receita": val,
        })
    print(f"  compras totais: {compras_total}  ·  com UTM (tráfego): {len(sales)}  ·  "
          f"sem UTM descartadas: {compras_sem_utm}", file=sys.stderr)

    dates = sorted({d for d in (
        [l["d"] for l in leads if l["d"]] + [m["d"] for m in meta if m["d"]] + [s["d"] for s in sales if s["d"]]
        + [g["d"] for g in seg if g["d"]]
    )})
    now_brt = datetime.now(BRT)
    return {
        "build": {
            "generated_at_brt": now_brt.strftime("%d/%m/%Y %H:%M"),
            "build_id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "today": now_brt.strftime("%Y-%m-%d"),
            "date_min": dates[0] if dates else None,
            "date_max": dates[-1] if dates else None,
            "tax_factor": TAX_FACTOR,
            # config da aba Relatório (lida pelo front)
            "sample_min_spend": SAMPLE_MIN_SPEND,
            "sample_min_mqls": SAMPLE_MIN_MQLS,
            "top_ads_n": TOP_ADS_N,
            # metas & parâmetros (defaults do painel editável; None = não definida)
            "meta_cpmql": META_CPMQL,
            "meta_cac": META_CAC,
            "volume_min_amostral": VOLUME_MIN_AMOSTRAL,
            "n_dias_corte": N_DIAS_CORTE,
        },
        "leads": leads,
        "meta": meta,
        "sales": sales,
        # Campanha de Atração de Seguidores (aba "Seguidores IG").
        "seg": seg,
        # Anúncio -> permalink do criativo (aba Relatório).
        "ad_links": ad_links,
        # Insights de Tráfego (texto pré-escrito, lido de relatorios.json). Preenchido
        # em main() via load_briefings(); fica {} se relatorios.json não existir.
        "briefings": {},
    }


# --------------------------------------------------------------------------- #
# Insights de Tráfego (aba Relatório)
# --------------------------------------------------------------------------- #
def load_briefings(path: str) -> dict:
    """Lê build/relatorios.json. Estrutura:
        {"generated_at": "...", "periodos": {"<preset>": {"html": "..."}, ...}}
    Retorna o dict inteiro (ou {} se o arquivo não existir/for inválido).
    A geração NÃO acontece aqui — este build só lê o texto já pronto, sem
    chamar nenhuma API (custo zero no build/no navegador)."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except (ValueError, OSError):
        return {}


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def render(data, template_path):
    # A dashboard e montada a partir de arquivos separados (visual x logica):
    #   template.html          -> esqueleto HTML (placeholders __STYLES__/__APP_JS__)
    #   identidade-visual.css  -> TODAS as cores (edite aqui p/ mexer so em cor)
    #   estilos.css            -> layout/componentes
    #   app.js                 -> logica + renderizacao
    # Esta funcao so COSTURA os arquivos e injeta os dados; nao altera nada deles.
    base = os.path.dirname(os.path.abspath(template_path))

    def readf(name):
        with open(os.path.join(base, name), "r", encoding="utf-8") as f:
            return f.read()

    with open(template_path, "r", encoding="utf-8") as f:
        tpl = f.read()
    styles = readf("identidade-visual.css") + "\n" + readf("estilos.css")
    tpl = tpl.replace("__STYLES__", styles)
    tpl = tpl.replace("__APP_JS__", readf("app.js"))
    tpl = tpl.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    tpl = tpl.replace("__BUILD_ID__", data["build"]["build_id"])
    tpl = tpl.replace("__GENERATED_BRT__", data["build"]["generated_at_brt"])
    return tpl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta-file", help="CSV local da aba Meta Ads (Página1)")
    ap.add_argument("--sales-file", help="CSV local da aba Compradores (Wks 13º Salario)")
    ap.add_argument("--seg-file", help="CSV local da aba Seguidores IG")
    ap.add_argument("--template", default="build/template.html")
    ap.add_argument("--out", default="dist/index.html")
    args = ap.parse_args()

    meta_rows = load_rows(EXPORT_URL.format(sid=SPREADSHEET_ID_META, gid=GID_META), args.meta_file)
    sales_rows = load_rows(EXPORT_URL.format(sid=SPREADSHEET_ID_SALES, gid=GID_SALES), args.sales_file)

    seg_rows = load_rows(EXPORT_URL.format(sid=SPREADSHEET_ID_META, gid=GID_SEG), args.seg_file)

    data = process(meta_rows, sales_rows, seg_rows)

    # Insights de Tráfego (texto pré-escrito) — lidos do arquivo versionado ao
    # lado do template. Sem chamada de API no build.
    briefings_path = os.path.join(os.path.dirname(os.path.abspath(args.template)), "relatorios.json")
    data["briefings"] = load_briefings(briefings_path)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(render(data, args.template))

    b = data["build"]
    vd = sum(s["vendas"] for s in data["sales"])
    fat = sum(s["fat"] for s in data["sales"])
    sp = sum(m["sp"] for m in data["meta"])
    print("== build ok ==", file=sys.stderr)
    print(f"  periodo   : {b['date_min']} -> {b['date_max']}", file=sys.stderr)
    print(f"  compras (tráfego, c/ UTM): {vd}  faturamento: R$ {fat:,.2f}", file=sys.stderr)
    print(f"  investimento Meta        : R$ {sp:,.2f}  (CAC R$ {(sp/vd if vd else 0):,.2f})", file=sys.stderr)
    print(f"  meta      : {len(data['meta'])} linhas", file=sys.stderr)
    sg = data["seg"]
    print(f"  seguidores: {sum(g['seg'] for g in sg):.0f} ganhos · investimento R$ {sum(g['sp'] for g in sg):,.2f} "
          f"· {len(sg)} linhas ({sum(g['inf'] for g in sg)} com seguidores preenchidos)", file=sys.stderr)
    print(f"  out       : {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
