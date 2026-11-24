"""Sinal "queda geral da Bolsa" (aprovado no teste com todas as ações da B3, 2016-2026).
Mantém os últimos ~120 pregões de todas as ações (ON, PN e units) a partir do arquivo diário oficial da B3."""
import gzip, io, pathlib
import pandas as pd

ARQ = pathlib.Path("mercado_precos.csv.gz")
FRACOES = [2, 3, 4, 5, 8, 10, 20, 25, 50, 100, 200, 1000]
TESTE = {"subiu_pct": 72, "mediana_pct": 15.3, "desastre_pct": 3.7, "ref_subiu_pct": 50, "ref_mediana_pct": 0.2,
         "ref_desastre_pct": 6.2, "episodios": "2018, 2020, 2021-2022, final de 2024 e 2026"}


def ler_dia(texto):
    linhas = []
    for l in texto.splitlines():
        if not l.startswith("01") or l[24:27] != "010" or l[10:12] != "02": continue
        esp = l[39:49].strip()
        if esp.startswith(("ON", "PN", "UNT")):
            linhas.append((pd.Timestamp(l[2:10]), l[12:24].strip(), int(l[108:121]) / 100, int(l[170:188]) / 100))
    return pd.DataFrame(linhas, columns=["data", "codigo", "fechamento", "volume"])


def _ajustar(P):
    A = P.copy()
    for c in P.columns:
        s = P[c].dropna()
        r = (s / s.shift()).dropna()
        fator = pd.Series(1.0, index=s.index)
        for d, x in r[(r <= 0.7) | (r >= 1.4)].items():
            for k in FRACOES:
                alvo = next((a for a in (k, 1 / k) if abs(x / a - 1) < 0.02), None)
                if alvo:
                    fator[fator.index < d] *= alvo
                    break
        A.loc[s.index, c] = s * fator
    return A


def atualizar(texto_b3, carteira_radar):
    hist = pd.read_csv(ARQ, parse_dates=["data"]) if ARQ.exists() else pd.DataFrame(columns=["data", "codigo", "fechamento", "volume"])
    novo = ler_dia(texto_b3)
    hist = pd.concat([hist, novo]).drop_duplicates(["data", "codigo"], keep="last")
    datas = sorted(hist.data.unique())[-120:]
    hist = hist[hist.data.isin(datas)].sort_values(["data", "codigo"])
    hist.to_csv(ARQ, index=False, compression="gzip")
    P = hist.pivot(index="data", columns="codigo", values="fechamento")
    V = hist.pivot(index="data", columns="codigo", values="volume")
    A = _ajustar(P)
    liquida = (V.rolling(60, min_periods=40).median().shift(1) >= 1_000_000).iloc[-1]
    dist = (A / A.rolling(50, min_periods=50).mean() - 1).iloc[-1]
    mercado = dist[liquida & dist.notna()].mean()
    quedas = sorted(({"ticker": t, "dist_pct": round(dist[t] * 100, 1)} for t in carteira_radar if t in dist and pd.notna(dist[t])),
                    key=lambda x: x["dist_pct"])
    # Destaques do pregão: maiores altas, maiores quedas e mais negociadas (só ações com bom volume)
    var = (A.iloc[-1] / A.iloc[-2] - 1) if len(A) >= 2 else pd.Series(dtype=float)
    vol = V.iloc[-1]
    ok = liquida & var.notna() & vol.notna()
    item = lambda t: {"ticker": t, "preco": round(float(P.iloc[-1][t]), 2), "var_pct": round(float(var[t]) * 100, 2),
                      "volume_mi": round(float(vol[t]) / 1e6, 1)}
    destaques = {"altas": [item(t) for t in var[ok].sort_values(ascending=False).index[:5]],
                 "quedas": [item(t) for t in var[ok].sort_values().index[:5]],
                 "mais_negociadas": [item(t) for t in vol[ok].sort_values(ascending=False).index[:5]],
                 "subiram": int((var[ok] > 0).sum()), "cairam": int((var[ok] < 0).sum()),
                 "media_pct": round(float(var[ok].mean()) * 100, 2) if ok.any() else None}
    # "Faca caindo": ação que despencou sozinha (15%+ abaixo da média) enquanto a Bolsa estava bem.
    # No teste com todas as ações (2016-2026), esse sinal foi REPROVADO: caso típico -1,3% e 14% de desastres.
    faca = []
    if pd.notna(mercado) and mercado > -0.10:
        sel = dist[liquida & (dist <= -0.15)]
        faca = [{"ticker": t, "dist_pct": round(float(sel[t]) * 100, 1), "volume_mi": round(float(vol.get(t, 0)) / 1e6, 1)}
                for t in sel.index]
        faca = sorted(faca, key=lambda x: -x["volume_mi"])[:5]
    return {"data": str(pd.Timestamp(datas[-1]).date()), "acoes_liquidas": int(liquida.sum()), "destaques": destaques, "faca_caindo": faca,
            "dist_mercado_pct": None if pd.isna(mercado) else round(mercado * 100, 1),
            "queda_geral": bool(pd.notna(mercado) and mercado <= -0.10),
            "carteira_radar": quedas, "teste": TESTE}
