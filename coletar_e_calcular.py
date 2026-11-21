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
    json.dump(saida, open("dados.json", "w"), ensure_ascii=False, indent=1)
    for a in saida["ativos"]:
        print(f'{a["ativo"]:7} {a["data"]} R${a["preco"]:>7} dia {a["var_dia_pct"]:>6}% IFR {a["ifr14"]:>5} vol20 {a["vol20_pct"]:>5}% tend {a["tendencia"]}')
    print("Selic:", saida["selic_pct"], "| erros:", saida["erros"])
