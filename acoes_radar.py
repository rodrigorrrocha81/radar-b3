"""Carteira de ações do Radar (regras aprovadas no teste com o passado, 2018-2026).

Regras: a cada troca (1º/abr, 16/mai, 16/ago, 16/nov), entre ~45 empresas grandes, ficam só as que têm lucro
nos últimos 12 meses e ROE acima de 10% ao ano. Nota = ranking de ROE + ranking de lucro sobre preço.
As 10 melhores entram com o mesmo valor, no máximo 3 do mesmo setor.
"""
import datetime as dt, json, pathlib, sys, time, zipfile
import pandas as pd, requests
import fundamentos as f

UNIVERSO = ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "B3SA3", "ABEV3", "WEGE3", "PRIO3", "ITSA4", "SBSP3",
            "EQTL3", "RENT3", "SUZB3", "GGBR4", "RADL3", "RDOR3", "LREN3", "MGLU3", "TIMS3", "VIVT3", "CMIG4",
            "BBSE3", "CXSE3", "HYPE3", "UGPA3", "VBBR3", "ENEV3", "TOTS3", "RAIL3", "CMIN3", "CSAN3", "EGIE3",
            "CPFE3", "CSMG3", "FLRY3", "MULT3", "CYRE3", "DIRR3", "POMO4", "ODPV3", "PSSA3", "KLBN4", "TAEE4", "SANB4"]
ARQ = pathlib.Path("carteira_acoes.json")
CACHE = pathlib.Path("cvm_cache"); CACHE.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}
BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA"
TROCAS = [(4, 1), (5, 16), (8, 16), (11, 16)]
TESTE = {"periodo": "abril/2018 a novembro/2026",
         "radar_pct": 383.2, "bova11_pct": 99.9, "cdi_pct": 115.6,
         "partes": {"2018-2020": [89.8, 40.1, 14.0], "2021-2023": [65.3, 14.3, 32.7], "2024-2026": [54.4, 27.1, 42.5]},
         "pior_queda_radar_pct": -35.7, "pior_queda_bova11_pct": -46.9}


# Teste com o passado de "realizar lucro": vender a ação quando sobe X% desde a compra e deixar o dinheiro
# no CDI até a próxima troca (2018-2026, com dividendos).
TESTE_LUCRO = {"sem_realizar": {"total_pct": 378.1, "pior_queda_pct": -35.7},
               "15": {"total_pct": 420.8, "pior_queda_pct": -17.0},
               "20": {"total_pct": 366.6, "pior_queda_pct": -23.2},
               "30": {"total_pct": 332.0, "pior_queda_pct": -31.2},
               "50": {"total_pct": 351.8, "pior_queda_pct": -35.7}}


def _baixar(url, destino, max_dias=0):
    if destino.exists() and (dt.date.today() - dt.date.fromtimestamp(destino.stat().st_mtime)).days <= max_dias:
        return destino
    r = requests.get(url, headers=UA, timeout=600); r.raise_for_status(); destino.write_bytes(r.content)
    return destino


def _mapa():
    z = zipfile.ZipFile(_baixar(f"{BASE}/DOC/FCA/DADOS/fca_cia_aberta_{dt.date.today().year}.zip", CACHE / "fca.zip", 30))
    n = [x for x in z.namelist() if "valor_mobiliario" in x][0]
    v = pd.read_csv(z.open(n), sep=";", encoding="latin-1", dtype=str)
    v = v[v.Codigo_Negociacao.isin(UNIVERSO)].drop_duplicates("Codigo_Negociacao")
    cad = pd.read_csv(_baixar(f"{BASE}/CAD/DADOS/cad_cia_aberta.csv", CACHE / "cad.csv", 30), sep=";", encoding="latin-1", dtype=str)
    setor = cad.drop_duplicates("CNPJ_CIA", keep="last").set_index("CNPJ_CIA").SETOR_ATIV
    return {r.Codigo_Negociacao: {"cnpj": r.CNPJ_Companhia, "setor": setor.get(r.CNPJ_Companhia, "?")} for r in v.itertuples()}


def _ultimo_balanco(mapa):
    """Lucro de 12 meses, patrimônio e ações do balanço mais recente de cada empresa."""
    ano = dt.date.today().year
    cnpjs = {m["cnpj"] for m in mapa.values()}
    partes = {k: [] for k in ["meta", "DRE", "BPP", "cap"]}
    for tipo, anos in [("itr", [ano, ano - 1]), ("dfp", [ano, ano - 1, ano - 2])]:
        for a in anos:
            try:
                z = zipfile.ZipFile(_baixar(f"{BASE}/DOC/{tipo.upper()}/DADOS/{tipo}_cia_aberta_{a}.zip", CACHE / f"{tipo}_cia_aberta_{a}.zip"))
            except Exception:
                continue
            meta = pd.read_csv(z.open(f"{tipo}_cia_aberta_{a}.csv"), sep=";", encoding="latin-1", dtype=str)
            meta = meta[meta.CNPJ_CIA.isin(cnpjs)]; meta["TIPO"] = tipo; partes["meta"].append(meta)
            cods = list(set(meta.CD_CVM))
            for parte, k in [("DRE_con", "DRE"), ("BPP_con", "BPP")]:
                x = f._csv(z, parte, a, cods); x["TIPO"] = tipo; partes[k].append(x)
            nome = f"{tipo}_cia_aberta_composicao_capital_{a}.csv"
            if nome in z.namelist():
                c = pd.read_csv(z.open(nome), sep=";", encoding="latin-1", dtype=str); partes["cap"].append(c[c.CNPJ_CIA.isin(cnpjs)])
    meta, dre, bpp, cap = (pd.concat(partes[k], ignore_index=True) for k in ["meta", "DRE", "BPP", "cap"])
    out = {}
    for tk, m in mapa.items():
        mm = meta[meta.CNPJ_CIA == m["cnpj"]].sort_values(["DT_REFER", "TIPO"])
        if mm.empty: continue
        cd = mm.CD_CVM.iloc[0]
        lucro, ref = f._ultimos_12m(dre, mm.assign(CD_CVM=cd), cd, "lucro")
        if ref is None: continue
        tipo = mm[mm.DT_REFER == ref].TIPO.iloc[-1]
        b = bpp[bpp.TIPO == tipo]
        pl = f._conta(b, cd, ref, descricao=r"Patrim[ôo]nio L[íi]quido Atribu[íi]do ao Controlador")
        pl = pl if pl is not None else f._conta(b, cd, ref, descricao=r"^Patrim[ôo]nio L[íi]quido Consolidado")
        c = cap[cap.CNPJ_CIA == m["cnpj"]].sort_values("DT_REFER")
        acoes = None
        if not c.empty:
            u = c.iloc[-1]
            acoes = float(u.QT_ACAO_TOTAL_CAP_INTEGR or 0) - float(u.QT_ACAO_TOTAL_TESOURO or 0)
            if 0 < acoes < 1e8: acoes *= 1000
        out[tk] = dict(setor=m["setor"], balanco=ref, lucro_12m=lucro, pl=pl, acoes=acoes)
    return out


def _preco(tk):
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}.SA?range=5d&interval=1d", headers=UA, timeout=30)
    q = r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    return [x for x in q if x is not None][-1]


def _ultima_data_troca(hoje):
    datas = [dt.date(a, m, d) for a in (hoje.year - 1, hoje.year) for m, d in TROCAS]
    return max(d for d in datas if d <= hoje)


def montar_carteira(hoje):
    mapa = _mapa()
    fund = _ultimo_balanco(mapa)
    linhas = []
    for tk, x in fund.items():
        try:
            preco = _preco(tk)
        except Exception:
            continue
        if not (x["lucro_12m"] and x["pl"] and x["acoes"]) or x["pl"] <= 0: continue
        roe = x["lucro_12m"] / x["pl"]
        if x["lucro_12m"] > 0 and roe > 0.10:
            lpa = x["lucro_12m"] / x["acoes"]
            linhas.append(dict(ticker=tk, setor=x["setor"], preco=round(preco, 2), roe_pct=round(roe * 100, 1),
                               p_l=round(preco / lpa, 1), ly=lpa / preco, balanco=x["balanco"]))
    df = pd.DataFrame(linhas)
    df["nota"] = df.roe_pct.rank(ascending=False) + df.ly.rank(ascending=False)
    escolhidas, setores = [], {}
    for r in df.sort_values("nota").itertuples():
        if setores.get(r.setor, 0) >= 3: continue
        escolhidas.append({k: getattr(r, k) for k in ["ticker", "setor", "preco", "roe_pct", "p_l", "balanco"]})
        setores[r.setor] = setores.get(r.setor, 0) + 1
        if len(escolhidas) == 10: break
    return {"data_troca": str(hoje), "acoes": escolhidas, "analisadas": int(len(fund)), "aprovadas_no_filtro": int(len(df))}


def atualizar(hoje=None):
    hoje = hoje or (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).date()
    est = json.loads(ARQ.read_text()) if ARQ.exists() else None
    troca = _ultima_data_troca(hoje)
    if est is None or est["data_troca"] < str(troca):
        est = montar_carteira(hoje)
        est["montada_em"], est["data_troca"] = str(hoje), str(troca)
    # desempenho desde a troca
    for a in est["acoes"]:
        try:
            a["preco_hoje"] = round(_preco(a["ticker"]), 2)
            a["var_desde_troca_pct"] = round((a["preco_hoje"] / a["preco"] - 1) * 100, 1)
        except Exception:
            pass
    # Preço de hoje de todas as empresas acompanhadas (para a área "Minha carteira")
    precos = {}
    for tk in UNIVERSO:
        try:
            precos[tk] = round(_preco(tk), 2)
        except Exception:
            pass
    est["precos"] = precos
    est["teste_realizar_lucro"] = TESTE_LUCRO
    v = [a["var_desde_troca_pct"] for a in est["acoes"] if "var_desde_troca_pct" in a]
    est["var_media_desde_troca_pct"] = round(sum(v) / len(v), 1) if v else None
    prox = [dt.date(a, m, d) for a in (hoje.year, hoje.year + 1) for m, d in TROCAS]
    est["proxima_troca"] = str(min(d for d in prox if d > hoje))
    est["teste"] = TESTE
    ARQ.write_text(json.dumps(est, ensure_ascii=False, indent=1, default=str))
    return est


if __name__ == "__main__":
    print(json.dumps(atualizar(), ensure_ascii=False, indent=1))
