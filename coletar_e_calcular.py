"""Protótipo: baixa preços diários (Yahoo) e calcula indicadores técnicos por código.
Nada aqui é recomendação de compra ou venda; são apenas medidas calculadas."""
import json, datetime as dt
import numpy as np, pandas as pd, requests

ATIVOS = ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "B3SA3", "ABEV3", "WEGE3", "PRIO3", "BOVA11"]
UA = {"User-Agent": "Mozilla/5.0"}

def baixar(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.SA?range=2y&interval=1d"
    r = requests.get(url, headers=UA, timeout=30); r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"abertura": q["open"], "maxima": q["high"], "minima": q["low"],
                       "fechamento": q["close"], "volume": q["volume"]},
                      index=pd.to_datetime(res["timestamp"], unit="s").date)
    return df.dropna()

def ifr(fech, n=14):
    d = fech.diff()
    ganho = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    perda = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + ganho / perda)

def atr(df, n=14):
    tr = pd.concat([df.maxima - df.minima, (df.maxima - df.fechamento.shift()).abs(),
                    (df.minima - df.fechamento.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def analisar(ticker):
    df = baixar(ticker)
    f = df.fechamento
    mm21, mm50, mm200 = f.rolling(21).mean(), f.rolling(50).mean(), f.rolling(200).mean()
    ret = np.log(f / f.shift())
    vol20 = ret.rolling(20).std() * np.sqrt(252) * 100
    vol_ano = ret.rolling(252).std() * np.sqrt(252) * 100
    p, a, b, c = f.iloc[-1], mm21.iloc[-1], mm50.iloc[-1], mm200.iloc[-1]
    if p > b > c: tend = "alta"
    elif p < b < c: tend = "baixa"
    else: tend = "lateral"
    r = ifr(f).iloc[-1]
    hist = df.tail(120)
    return {
        "ativo": ticker, "data": str(df.index[-1]), "preco": round(p, 2),
        "var_dia_pct": round((p / f.iloc[-2] - 1) * 100, 2),
        "var_21d_pct": round((p / f.iloc[-22] - 1) * 100, 2),
        "mm21": round(a, 2), "mm50": round(b, 2), "mm200": round(c, 2),
        "dist_mm50_pct": round((p / b - 1) * 100, 2),
        "ifr14": round(r, 1),
        "ifr_leitura": "sobrecomprado (>70)" if r > 70 else "sobrevendido (<30)" if r < 30 else "neutro",
        "atr14": round(atr(df).iloc[-1], 2), "atr_pct": round(atr(df).iloc[-1] / p * 100, 2),
        "vol20_pct": round(vol20.iloc[-1], 1), "vol_1ano_pct": round(vol_ano.iloc[-1], 1),
        "suporte_20d": round(df.minima.tail(20).min(), 2),
        "resistencia_20d": round(df.maxima.tail(20).max(), 2),
        "volume_vs_media20": round(df.volume.iloc[-1] / df.volume.tail(20).mean(), 2),
        "tendencia": tend,
        "historico": {"datas": [str(d) for d in hist.index], "fech": [round(x, 2) for x in hist.fechamento],
                      "mm50": [None if pd.isna(x) else round(x, 2) for x in mm50.tail(120)]},
    }

def selic():
    r = requests.get("https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json", timeout=30)
    return float(r.json()[0]["valor"])

if __name__ == "__main__":
    saida = {"gerado_em": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).replace(tzinfo=None).isoformat(timespec="minutes"), "selic_pct": selic(), "ativos": [], "erros": []}
    for t in ATIVOS:
        try: saida["ativos"].append(analisar(t))
        except Exception as e: saida["erros"].append(f"{t}: {e}")
    # --- Opções (arquivo oficial da B3) ---
    try:
        import baixar_b3, opcoes, csv, pathlib
        dia_b3, texto = baixar_b3.ultimo_pregao()
        raizes = {t[:4]: t for t in ATIVOS}
        vh = {a["ativo"]: {"vol20": a["vol20_pct"], "vol_ano": a["vol_1ano_pct"]} for a in saida["ativos"]}
        res = opcoes.analisar_opcoes(texto, raizes, saida["selic_pct"], vh)
        saida["pregao_opcoes"] = str(dia_b3)
        for a in saida["ativos"]:
            a["opcoes"] = res.get(a["ativo"])
        # Histórico diário da volatilidade implícita (base para comparações futuras)
        hist = pathlib.Path("historico_vi.csv"); novo = not hist.exists()
        linhas_existentes = hist.read_text() if hist.exists() else ""
        with hist.open("a", newline="") as f:
            w = csv.writer(f)
            if novo: w.writerow(["pregao", "ativo", "vi_atm", "vol20", "vol_ano", "series_liquidas"])
            for a in saida["ativos"]:
                o = a.get("opcoes") or {}
                if f"{dia_b3},{a['ativo']}," not in linhas_existentes:
                    w.writerow([dia_b3, a["ativo"], o.get("vi_atm"), a["vol20_pct"], a["vol_1ano_pct"], o.get("n_liquidas", 0)])
        # Carteira simulada (dinheiro de mentira) com as regras testadas
        try:
            import carteira_simulada
            saida["carteira_simulada"] = carteira_simulada.atualizar(texto, dia_b3, saida["ativos"], saida["selic_pct"])
        except Exception as e:
            saida["erros"].append(f"carteira simulada: {e}")
    except Exception as e:
        saida["erros"].append(f"opções: {e}")
    # --- Fundamentos e eventos (CVM) ---
    try:
        import fundamentos
        fund = fundamentos.analisar({a["ativo"]: a["preco"] for a in saida["ativos"]})
        hoje = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).date()
        for a in saida["ativos"]:
            f = fund.get(a["ativo"])
            if not f:
                continue
            alertas = []
            est = f.get("proximo_balanco_estimado")
            if est:
                dias = (dt.date.fromisoformat(est) - hoje).days
                f["dias_ate_balanco"] = dias
                venc = (a.get("opcoes") or {}).get("vencimento_ref")
                if venc and est <= venc:
                    alertas.append("balanço previsto antes do vencimento das opções de referência")
                elif 0 <= dias <= 21:
                    alertas.append(f"balanço previsto em cerca de {dias} dias")
            if f.get("provento_anunciado_30d"):
                alertas.append("provento anunciado nos últimos 30 dias: confira a data-com (strikes podem ser ajustados)")
            f["alertas"] = alertas
            a["fundamentos"] = f
    except Exception as e:
        saida["erros"].append(f"fundamentos: {e}")
    # --- Carteira de ações do Radar (troca a cada 3 meses) ---
    try:
        import acoes_radar
        saida["carteira_acoes"] = acoes_radar.atualizar()
    except Exception as e:
        saida["erros"].append(f"carteira de ações: {e}")
    # --- Sinal "queda geral da Bolsa" (todas as ações, arquivo oficial da B3) ---
    try:
        import mercado
        if "texto" not in dir():
            import baixar_b3
            _, texto = baixar_b3.ultimo_pregao()
        lista = [a["ticker"] for a in (saida.get("carteira_acoes") or {}).get("acoes", [])]
        saida["mercado"] = mercado.atualizar(texto, lista)
    except Exception as e:
        saida["erros"].append(f"queda geral: {e}")
    json.dump(saida, open("dados.json", "w"), ensure_ascii=False, indent=1, default=str)
    for a in saida["ativos"]:
        print(f'{a["ativo"]:7} {a["data"]} R${a["preco"]:>7} dia {a["var_dia_pct"]:>6}% IFR {a["ifr14"]:>5} vol20 {a["vol20_pct"]:>5}% tend {a["tendencia"]}')
    for a in saida["ativos"]:
        o = a.get("opcoes") or {}
        print(f'  {a["ativo"]:7} opções líquidas {o.get("n_liquidas")}, VI no dinheiro {o.get("vi_atm")}% ({o.get("leitura_vi")})')
    print("Selic:", saida["selic_pct"], "| erros:", saida["erros"])
