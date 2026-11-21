"""Fundamentos e eventos das empresas, a partir dos dados abertos oficiais da CVM
(balanços trimestrais ITR, anuais DFP e documentos IPE) e do histórico de proventos do Yahoo.
São medidas calculadas, não recomendação de compra ou venda."""
import datetime as dt, io, pathlib, re, zipfile
import pandas as pd, requests

BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"
CACHE = pathlib.Path("cvm_cache")
UA = {"User-Agent": "Mozilla/5.0"}

# Código oficial de cada empresa na CVM (conferido no cadastro da CVM)
EMPRESAS = {
    "PETR4": ("009512", "industria"), "VALE3": ("004170", "industria"), "ITUB4": ("019348", "banco"),
    "BBDC4": ("000906", "banco"), "BBAS3": ("001023", "banco"), "B3SA3": ("021610", "industria"),
    "ABEV3": ("023264", "industria"), "WEGE3": ("005410", "industria"), "PRIO3": ("022187", "industria"),
}
CATEGORIAS_EVENTO = ["Fato Relevante", "Comunicado ao Mercado", "Aviso aos Acionistas", "Calendário de Eventos Corporativos"]


def _zip(tipo, ano):
    """Baixa (com cache do dia) o arquivo anual da CVM. Devolve ZipFile ou None se não existir."""
    CACHE.mkdir(exist_ok=True)
    nome = f"{tipo}_cia_aberta_{ano}.zip"
    arq = CACHE / nome
    if not arq.exists() or dt.date.fromtimestamp(arq.stat().st_mtime) != dt.date.today():
        r = requests.get(f"{BASE}/{tipo.upper()}/DADOS/{nome}", headers=UA, timeout=300)
        if r.status_code != 200 or r.content[:2] != b"PK":
            return None
        arq.write_bytes(r.content)
    return zipfile.ZipFile(arq)


def _csv(z, parte, ano, codigos):
    if z is None:
        return pd.DataFrame()
    prefixo = z.namelist()[0].split("_cia_aberta")[0]
    nome = f"{prefixo}_cia_aberta_{parte}_{ano}.csv" if parte else f"{prefixo}_cia_aberta_{ano}.csv"
    if nome not in z.namelist():
        return pd.DataFrame()
    df = pd.read_csv(z.open(nome), sep=";", encoding="latin-1", dtype=str)
    if "CD_CVM" in df:
        df = df[df.CD_CVM.isin(codigos)]
    if "VERSAO" in df:  # fica só com a versão mais recente de cada documento
        df["VERSAO"] = df.VERSAO.astype(int)
        df = df[df.VERSAO == df.groupby(["CD_CVM", "DT_REFER"]).VERSAO.transform("max")] if "CD_CVM" in df else df
    if "VL_CONTA" in df:
        df["VL_CONTA"] = df.VL_CONTA.astype(float) * df.ESCALA_MOEDA.map({"MIL": 1000, "UNIDADE": 1}).fillna(1)
    return df


def carregar(ano=None):
    """Carrega os dados necessários da CVM para o ano corrente e o anterior."""
    ano = ano or dt.date.today().year
    codigos = [c for c, _ in EMPRESAS.values()]
    d = {k: [] for k in ["meta", "DRE", "BPA", "BPP", "cap"]}
    for tipo, anos in [("itr", [ano, ano - 1]), ("dfp", [ano, ano - 1, ano - 2])]:
        for a in anos:
            z = _zip(tipo, a)
            if z is None:
                continue
            m = _csv(z, None, a, codigos); m["TIPO"] = tipo; d["meta"].append(m)
            for parte, chave in [("DRE_con", "DRE"), ("BPA_con", "BPA"), ("BPP_con", "BPP")]:
                x = _csv(z, parte, a, codigos); x["TIPO"] = tipo; d[chave].append(x)
            cap = _csv(z, "composicao_capital", a, codigos); cap["TIPO"] = tipo; d["cap"].append(cap)
    d = {k: pd.concat(v, ignore_index=True) if v else pd.DataFrame() for k, v in d.items()}
    ipe = []
    for a in [ano, ano - 1]:
        z = _zip("ipe", a)
        if z is not None:
            ipe.append(pd.read_csv(z.open(z.namelist()[0]), sep=";", encoding="latin-1", dtype=str))
    d["ipe"] = pd.concat(ipe, ignore_index=True) if ipe else pd.DataFrame()
    return d


def _conta(df, cd, ref, ordem="ÚLTIMO", codigo=None, descricao=None, inicio=None):
    """Valor de uma conta. Busca pelo código ou por um trecho da descrição (pega o nível mais alto)."""
    x = df[(df.CD_CVM == cd) & (df.DT_REFER == ref) & (df.ORDEM_EXERC == ordem)]
    if inicio is not None and "DT_INI_EXERC" in x:
        x = x[x.DT_INI_EXERC == inicio]
    if codigo:
        x = x[x.CD_CONTA == codigo]
    if descricao:
        x = x[x.DS_CONTA.str.contains(descricao, case=False, regex=True, na=False)]
        x = x.assign(nivel=x.CD_CONTA.str.count(r"\.")).sort_values(["nivel", "CD_CONTA"])
    return None if x.empty else float(x.VL_CONTA.iloc[0])


LUCRO_CONTROLADOR = r"Atribu[íi]do a S[óo]cios da Empresa Controladora|Atribu[íi]do ao Controlador|Atribu[íi]do aos Acionistas Controladores"
LUCRO_TOTAL = r"^Lucro.*(?:Consolidado|L[íi]quido).*Per[íi]odo"


def _lucro(dre, cd, ref, ordem, inicio):
    v = _conta(dre, cd, ref, ordem, descricao=LUCRO_CONTROLADOR, inicio=inicio)
    return v if v is not None else _conta(dre, cd, ref, ordem, descricao=LUCRO_TOTAL, inicio=inicio)


def _acumulado(dre, cd, ref, ordem, campo):
    """Valor acumulado no ano (de 1º de janeiro até a data de referência)."""
    ano = int(ref[:4]) - (1 if ordem == "PENÚLTIMO" else 0)
    ini = f"{ano}-01-01"
    if campo == "lucro":
        return _lucro(dre, cd, ref, ordem, ini)
    return _conta(dre, cd, ref, ordem, codigo={"receita": "3.01", "ebit": "3.05"}[campo], inicio=ini)


def _ultimos_12m(dre, meta, cd, campo):
    """Soma dos últimos 12 meses: acumulado do ano + ano anterior completo - acumulado do ano anterior."""
    docs = meta[meta.CD_CVM == cd].sort_values(["DT_REFER", "TIPO"])
    if docs.empty:
        return None, None
    ult = docs.iloc[-1]
    ref = ult.DT_REFER
    if ult.TIPO == "dfp":
        return _acumulado(dre, cd, ref, "ÚLTIMO", campo), ref
    ytd = _acumulado(dre, cd, ref, "ÚLTIMO", campo)
    ytd_ant = _acumulado(dre, cd, ref, "PENÚLTIMO", campo)
    ano_ant = f"{int(ref[:4]) - 1}-12-31"
    fy = _acumulado(dre[dre.TIPO == "dfp"], cd, ano_ant, "ÚLTIMO", campo)
    if None in (ytd, ytd_ant, fy):
        return None, ref
    return ytd + fy - ytd_ant, ref


def proventos_12m(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.SA?range=1y&interval=1mo&events=div"
    r = requests.get(url, headers=UA, timeout=30); r.raise_for_status()
    divs = r.json()["chart"]["result"][0].get("events", {}).get("dividends", {}).values()
    lista = sorted(((dt.date.fromtimestamp(v["date"]), v["amount"]) for v in divs), reverse=True)
    return sum(v for _, v in lista), [{"data": str(d), "valor": round(v, 4)} for d, v in lista]


def _proximo_balanco(meta, cd, ref):
    """Estima a data do próximo balanço pela data de entrega do mesmo período no ano anterior."""
    ref_d = dt.date.fromisoformat(ref)
    prox = {3: (6, 30), 6: (9, 30), 9: (12, 31), 12: (3, 31)}[ref_d.month]
    ano = ref_d.year + (1 if ref_d.month == 12 else 0)
    prox_ref = dt.date(ano, *prox)
    ant = f"{prox_ref.year - 1}-{prox_ref.month:02d}-{prox_ref.day:02d}"
    x = meta[(meta.CD_CVM == cd) & (meta.DT_REFER == ant)]
    if x.empty:
        return str(prox_ref), None
    entrega_ant = dt.date.fromisoformat(x.DT_RECEB.min())
    try:
        estimada = entrega_ant.replace(year=entrega_ant.year + 1)
    except ValueError:
        estimada = entrega_ant + dt.timedelta(days=365)
    return str(prox_ref), str(estimada)


def analisar_empresa(d, ticker, preco):
    cd, tipo = EMPRESAS[ticker]
    dre, meta, bpa, bpp, cap, ipe = d["DRE"], d["meta"], d["BPA"], d["BPP"], d["cap"], d["ipe"]
    res = {"tipo": tipo, "fonte": "CVM"}
    lucro, ref = _ultimos_12m(dre, meta, cd, "lucro")
    if ref is None:
        return {"erro": "sem dados na CVM"}
    res["data_balanco"] = ref
    res["entregue_em"] = meta[(meta.CD_CVM == cd) & (meta.DT_REFER == ref)].DT_RECEB.max()
    res["lucro_12m"] = lucro
    # Patrimônio: do controlador quando existir, senão o consolidado
    pl = _conta(bpp, cd, ref, descricao=r"Patrim[ôo]nio L[íi]quido Atribu[íi]do ao Controlador")
    pl = pl if pl is not None else _conta(bpp, cd, ref, descricao=r"^Patrim[ôo]nio L[íi]quido Consolidado")
    res["patrimonio"] = pl
    # Ações em circulação (total menos tesouraria)
    cnpj = meta[meta.CD_CVM == cd].CNPJ_CIA.iloc[0]
    c = cap[cap.CNPJ_CIA == cnpj].sort_values(["DT_REFER", "VERSAO"])
    acoes = None
    if not c.empty:
        u = c.iloc[-1]
        acoes = float(u.QT_ACAO_TOTAL_CAP_INTEGR) - float(u.QT_ACAO_TOTAL_TESOURO or 0)
        if acoes < 1e8:  # algumas empresas informam a quantidade em milhares (o arquivo não indica a escala)
            acoes *= 1000
    res["acoes"] = acoes
    if lucro and acoes:
        lpa = lucro / acoes
        res["lpa"] = round(lpa, 2)
        res["p_l"] = round(preco / lpa, 1) if lpa > 0 else None
    if pl and acoes:
        res["p_vp"] = round(preco / (pl / acoes), 2)
    if lucro and pl:
        res["roe_pct"] = round(lucro / pl * 100, 1)
    # Crescimento do lucro: acumulado do ano contra o mesmo período do ano anterior
    l_atual = _acumulado(dre, cd, ref, "ÚLTIMO", "lucro")
    l_ant = _acumulado(dre, cd, ref, "PENÚLTIMO", "lucro")
    if l_atual is not None and l_ant:
        res["cresc_lucro_pct"] = round((l_atual / l_ant - 1) * 100, 1) if l_ant > 0 else None
    if tipo == "industria":
        receita, _ = _ultimos_12m(dre, meta, cd, "receita")
        ebit, _ = _ultimos_12m(dre, meta, cd, "ebit")
        if receita:
            res["margem_liquida_pct"] = round(lucro / receita * 100, 1) if lucro is not None else None
            res["margem_ebit_pct"] = round(ebit / receita * 100, 1) if ebit is not None else None
        divida = sum(v for v in [_conta(bpp, cd, ref, codigo="2.01.04"), _conta(bpp, cd, ref, codigo="2.02.01")] if v)
        caixa = sum(v for v in [_conta(bpa, cd, ref, codigo="1.01.01"), _conta(bpa, cd, ref, codigo="1.01.02")] if v)
        res["divida_liquida"] = divida - caixa
        if ebit and ebit > 0:
            res["div_liq_ebit"] = round((divida - caixa) / ebit, 2)
    # Proventos (Yahoo) e rendimento
    try:
        total, lista = proventos_12m(ticker)
        res["proventos_12m"] = round(total, 2)
        res["dividend_yield_pct"] = round(total / preco * 100, 1) if preco else None
        res["ultimos_proventos"] = lista[:4]
    except Exception as e:
        res["proventos_erro"] = str(e)
    # Eventos: próximo balanço (estimado) e documentos recentes na CVM
    prox_ref, estimada = _proximo_balanco(meta, cd, ref)
    res["proximo_balanco_ref"], res["proximo_balanco_estimado"] = prox_ref, estimada
    if not ipe.empty:
        hoje = dt.date.today()
        x = ipe[(ipe.Codigo_CVM.str.zfill(6) == cd) & ipe.Categoria.isin(CATEGORIAS_EVENTO)].copy()
        x = x[x.Data_Entrega >= str(hoje - dt.timedelta(days=30))].sort_values("Data_Entrega", ascending=False)
        x = x.drop_duplicates(["Data_Entrega", "Assunto"])
        res["eventos_30d"] = [{"data": r.Data_Entrega, "categoria": r.Categoria,
                               "assunto": (r.Assunto if isinstance(r.Assunto, str) else r.Tipo) or "",
                               "link": r.Link_Download} for r in x.head(6).itertuples()]
        res["provento_anunciado_30d"] = bool(x.Assunto.fillna("").str.contains(
            r"dividend|juros sobre (?:o )?capital|JCP|proventos|remunera", case=False, regex=True).any())
    return res


def analisar(tickers_precos):
    d = carregar()
    saida = {}
    for t, preco in tickers_precos.items():
        if t not in EMPRESAS:
            saida[t] = None
            continue
        try:
            saida[t] = analisar_empresa(d, t, preco)
        except Exception as e:
            saida[t] = {"erro": str(e)}
    return saida
