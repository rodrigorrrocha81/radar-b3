"""Teste com o passado da carteira de ações do Radar (regras em historico/ACOES_RADAR.md).
Fontes: CVM (balanços, cadastro, códigos de negociação), Yahoo (preços com dividendos), Banco Central (CDI)."""
import datetime as dt, io, json, pathlib, sys, time, zipfile
import numpy as np, pandas as pd, requests

sys.path.insert(0, ".")
import fundamentos as f

UNIVERSO = ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "B3SA3", "ABEV3", "WEGE3", "PRIO3", "ITSA4", "SBSP3",
            "EQTL3", "RENT3", "SUZB3", "GGBR4", "RADL3", "RDOR3", "LREN3", "MGLU3", "TIMS3", "VIVT3", "CMIG4",
            "BBSE3", "CXSE3", "HYPE3", "UGPA3", "VBBR3", "ENEV3", "TOTS3", "RAIL3", "CMIN3", "CSAN3", "EGIE3",
            "CPFE3", "CSMG3", "FLRY3", "MULT3", "CYRE3", "DIRR3", "POMO4", "ODPV3", "PSSA3", "KLBN4", "TAEE4", "SANB4"]
CACHE = pathlib.Path("cvm_cache"); CACHE.mkdir(exist_ok=True)
SAIDA = pathlib.Path("historico/acoes"); SAIDA.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}
BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA"


def baixar(url, destino):
    if not destino.exists():
        r = requests.get(url, headers=UA, timeout=600); r.raise_for_status(); destino.write_bytes(r.content)
    return destino


def mapa_tickers():
    z = zipfile.ZipFile(baixar(f"{BASE}/DOC/FCA/DADOS/fca_cia_aberta_2026.zip", CACHE / "fca_2026.zip"))
    n = [x for x in z.namelist() if "valor_mobiliario" in x][0]
    v = pd.read_csv(z.open(n), sep=";", encoding="latin-1", dtype=str)
    v = v[v.Codigo_Negociacao.isin(UNIVERSO)].drop_duplicates("Codigo_Negociacao")
    cad = pd.read_csv(baixar(f"{BASE}/CAD/DADOS/cad_cia_aberta.csv", CACHE / "cad.csv"), sep=";", encoding="latin-1", dtype=str)
    setor = cad.drop_duplicates("CNPJ_CIA", keep="last").set_index("CNPJ_CIA").SETOR_ATIV
    return {r.Codigo_Negociacao: {"cnpj": r.CNPJ_Companhia, "setor": setor.get(r.CNPJ_Companhia, "?")} for r in v.itertuples()}


def ler_ano(tipo, ano, cnpjs):
    arq = CACHE / f"{tipo}_cia_aberta_{ano}.zip"
    try:
        baixar(f"{BASE}/DOC/{tipo.upper()}/DADOS/{tipo}_cia_aberta_{ano}.zip", arq)
    except Exception:
        return None
    z = zipfile.ZipFile(arq)
    def rd(nome):
        if nome not in z.namelist():  # arquivos antigos não têm a composição do capital
            return pd.DataFrame(columns=["CNPJ_CIA", "DT_REFER", "QT_ACAO_TOTAL_CAP_INTEGR", "QT_ACAO_TOTAL_TESOURO"])
        x = pd.read_csv(z.open(nome), sep=";", encoding="latin-1", dtype=str)
        return x[x.CNPJ_CIA.isin(cnpjs)]
    meta = rd(f"{tipo}_cia_aberta_{ano}.csv")
    cods = set(meta.CD_CVM)
    out = {"meta": meta}
    for parte in ["DRE_con", "BPP_con"]:
        x = pd.read_csv(z.open(f"{tipo}_cia_aberta_{parte}_{ano}.csv"), sep=";", encoding="latin-1", dtype=str)
        x = x[x.CD_CVM.isin(cods)]
        x["VERSAO"] = x.VERSAO.astype(int)
        x = x[x.VERSAO == x.groupby(["CD_CVM", "DT_REFER"]).VERSAO.transform("max")]
        x["VL_CONTA"] = x.VL_CONTA.astype(float) * x.ESCALA_MOEDA.map({"MIL": 1000, "UNIDADE": 1}).fillna(1)
        out[parte] = x
    out["cap"] = rd(f"{tipo}_cia_aberta_composicao_capital_{ano}.csv")
    for k in out: out[k]["TIPO"] = tipo
    return out


def qualidade(mapa):
    cnpjs = {m["cnpj"] for m in mapa.values()}
    partes = {k: [] for k in ["meta", "DRE_con", "BPP_con", "cap"]}
    for tipo, anos in [("itr", range(2017, 2027)), ("dfp", range(2016, 2026))]:
        for a in anos:
            x = ler_ano(tipo, a, cnpjs)
            if x:
                for k in partes: partes[k].append(x[k])
            print("CVM", tipo, a, "ok" if x else "sem arquivo", flush=True)
    meta, dre, bpp, cap = (pd.concat(partes[k], ignore_index=True) for k in ["meta", "DRE_con", "BPP_con", "cap"])
    linhas = []
    for tk, m in mapa.items():
        mm = meta[meta.CNPJ_CIA == m["cnpj"]]
        if mm.empty: continue
        cd = mm.CD_CVM.iloc[0]
        docs = mm.groupby(["DT_REFER", "TIPO"]).DT_RECEB.min().reset_index()
        for r in docs.itertuples():
            ref = r.DT_REFER
            if r.TIPO == "dfp":
                lucro = f._acumulado(dre[dre.TIPO == "dfp"], cd, ref, "ÚLTIMO", "lucro")
            else:
                ytd = f._acumulado(dre[dre.TIPO == "itr"], cd, ref, "ÚLTIMO", "lucro")
                ytd_a = f._acumulado(dre[dre.TIPO == "itr"], cd, ref, "PENÚLTIMO", "lucro")
                fy = f._acumulado(dre[dre.TIPO == "dfp"], cd, f"{int(ref[:4]) - 1}-12-31", "ÚLTIMO", "lucro")
                lucro = None if None in (ytd, ytd_a, fy) else ytd + fy - ytd_a
            b = bpp[bpp.TIPO == r.TIPO]
            pl = f._conta(b, cd, ref, descricao=r"Patrim[ôo]nio L[íi]quido Atribu[íi]do ao Controlador")
            pl = pl if pl is not None else f._conta(b, cd, ref, descricao=r"^Patrim[ôo]nio L[íi]quido Consolidado")
            c = cap[(cap.CNPJ_CIA == m["cnpj"]) & (cap.DT_REFER == ref)]
            acoes = None
            if not c.empty:
                u = c.iloc[-1]
                acoes = float(u.QT_ACAO_TOTAL_CAP_INTEGR or 0) - float(u.QT_ACAO_TOTAL_TESOURO or 0)
                if 0 < acoes < 1e8: acoes *= 1000
            linhas.append(dict(ticker=tk, setor=m["setor"], ref=ref, entregue=r.DT_RECEB, lucro_12m=lucro, pl=pl, acoes=acoes))
    q = pd.DataFrame(linhas).sort_values(["ticker", "entregue"])
    # Balanços antigos sem quantidade de ações: usa a quantidade mais próxima disponível (muda pouco com o tempo)
    q["acoes"] = q.groupby("ticker").acoes.transform(lambda s: s.ffill().bfill())
    q.to_csv(SAIDA / "qualidade.csv", index=False)
    return q


def precos(tickers):
    p1, p2 = int(dt.datetime(2017, 1, 1).timestamp()), int(time.time())
    fech, ajust = {}, {}
    for t in tickers:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{t}.SA?period1={p1}&period2={p2}&interval=1d&events=div,split"
        try:
            r = requests.get(url, headers=UA, timeout=60).json()["chart"]["result"][0]
            idx = pd.to_datetime(r["timestamp"], unit="s").normalize()
            fech[t] = pd.Series(r["indicators"]["quote"][0]["close"], index=idx)
            ajust[t] = pd.Series(r["indicators"]["adjclose"][0]["adjclose"], index=idx)
        except Exception as e:
            print("sem preço:", t, e)
    F, A = pd.DataFrame(fech).sort_index(), pd.DataFrame(ajust).sort_index()
    F = F[~F.index.duplicated()]; A = A[~A.index.duplicated()]
    F.to_csv(SAIDA / "precos_fechamento.csv"); A.to_csv(SAIDA / "precos_ajustados.csv")
    return F, A


def cdi():
    partes = []
    for ini, fim in [("01/01/2018", "31/12/2022"), ("01/01/2023", dt.date.today().strftime("%d/%m/%Y"))]:
        u = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial={ini}&dataFinal={fim}"
        partes.append(pd.DataFrame(requests.get(u, timeout=60).json()))
    x = pd.concat(partes)
    s = pd.Series(x.valor.astype(float).values / 100, index=pd.to_datetime(x.data, format="%d/%m/%Y"))
    return (1 + s).cumprod()


def datas_troca(indice):
    out = []
    for ano in range(2018, 2027):
        for m, d in [(4, 1), (5, 16), (8, 16), (11, 16)]:
            alvo = pd.Timestamp(ano, m, d)
            pos = indice[indice >= alvo]
            if len(pos) and pos[0] <= indice[-1]: out.append(pos[0])
    return [d for d in out if d <= indice[-1]]


def escolher(q, F, data, mapa):
    linhas = []
    for tk in F.columns:
        if tk == "BOVA11": continue
        x = q[(q.ticker == tk) & (q.entregue <= str(data.date()))]
        if x.empty: continue
        u = x.iloc[-1]
        preco = F.loc[:data, tk].dropna()
        if preco.empty or pd.isna(u.lucro_12m) or pd.isna(u.pl) or not u.acoes or u.pl <= 0: continue
        roe = u.lucro_12m / u.pl
        ly = (u.lucro_12m / u.acoes) / preco.iloc[-1]  # lucro por ação / preço
        if u.lucro_12m > 0 and roe > 0.10:
            linhas.append(dict(ticker=tk, setor=mapa[tk]["setor"], roe=roe, ly=ly))
    df = pd.DataFrame(linhas)
    if df.empty: return []
    df["nota"] = df.roe.rank(ascending=False) + df.ly.rank(ascending=False)
    escolhidas, por_setor = [], {}
    for r in df.sort_values("nota").itertuples():
        if por_setor.get(r.setor, 0) >= 3: continue
        escolhidas.append(r.ticker); por_setor[r.setor] = por_setor.get(r.setor, 0) + 1
        if len(escolhidas) == 10: break
    return escolhidas


def simular(q, F, A, mapa, custo=0.0005):
    A = A.ffill()
    trocas = datas_troca(A.index)
    valor, carteira, hist, comp = 1.0, [], [], []
    curva = pd.Series(dtype=float)
    for i, d in enumerate(trocas):
        nova = escolher(q, F, d, mapa)
        giro = len(set(nova) ^ set(carteira)) / max(len(nova), 1) / 2 if carteira else 1.0
        valor *= (1 - custo * 2 * giro)
        carteira = nova
        comp.append({"data": str(d.date()), "acoes": nova})
        fim = trocas[i + 1] if i + 1 < len(trocas) else A.index[-1]
        trecho = A.loc[d:fim, carteira]
        rel = (trecho / trecho.iloc[0]).mean(axis=1) * valor
        curva = pd.concat([curva, rel.iloc[(1 if len(curva) else 0):]])
        valor = rel.iloc[-1]
    return curva, comp


if __name__ == "__main__":
    mapa = mapa_tickers()
    print("empresas mapeadas:", len(mapa), "faltaram:", sorted(set(UNIVERSO) - set(mapa)))
    q = qualidade(mapa)
    F, A = precos(list(mapa) + ["BOVA11"])
    curva, comp = simular(q, F, A, mapa)
    bova = A.BOVA11.ffill().loc[curva.index[0]:]; bova = bova / bova.iloc[0]
    c = cdi(); c = c.loc[curva.index[0]:]; c = c / c.iloc[0]
    res = {}
    for nome, (a, b) in {"2018-2020": ("2018-01-01", "2020-12-31"), "2021-2023": ("2021-01-01", "2023-12-31"),
                         "2024-2026": ("2024-01-01", "2026-12-31"), "total": ("2018-01-01", "2026-12-31")}.items():
        def ret(s):
            s = s.loc[a:b].dropna()
            return round((s.iloc[-1] / s.iloc[0] - 1) * 100, 1)
        res[nome] = {"carteira_radar_pct": ret(curva), "bova11_pct": ret(bova), "cdi_pct": ret(c)}
    res["pior_queda_carteira_pct"] = round(((curva / curva.cummax()) - 1).min() * 100, 1)
    res["pior_queda_bova11_pct"] = round(((bova / bova.cummax()) - 1).min() * 100, 1)
    res["carteira_atual"] = comp[-1]
    print(json.dumps(res, ensure_ascii=False, indent=1))
    json.dump({"resumo": res, "composicoes": comp}, open(SAIDA / "resultado.json", "w"), ensure_ascii=False, indent=1)
    pd.DataFrame({"radar": curva, "bova11": bova.reindex(curva.index), "cdi": c.reindex(curva.index, method="ffill")}).to_csv(SAIDA / "curva.csv")
