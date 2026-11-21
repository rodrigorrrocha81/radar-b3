"""Teste com o passado de alternativas: 3 sinais de entrada x 2 formas de montar a operação.
Para evitar "achar um vencedor por sorte", o período é dividido em dois:
  - 2023-2024: período de desenvolvimento;
  - 2025-2026: período de confirmação (uma regra só vale se funcionar nos dois).
Mesmas hipóteses conservadoras do simulador original: compra pela oferta de venda (mais cara)
e venda pela oferta de compra (mais barata), entrada no fechamento do dia seguinte ao sinal.
"""
import json, math, sys
import numpy as np, pandas as pd

sys.path.insert(0, "historico"); sys.path.insert(0, ".")
import simulador as base
from opcoes import vol_implicita, gregas

P = dict(du_min=25, du_max=60, delta_min=0.35, delta_max=0.55, delta_venda=(0.15, 0.30),
         min_negocios=20, min_volume=100_000, max_spread=0.40, alvo_seca=2.5, alvo_trava=2.0,
         du_saida=3, tiro=100.0, max_abertas=5, custo=0.0005, selic=0.12)


def preparar():
    acoes, ops = base.carregar()
    ind = base.indicadores(acoes)
    for t, g in acoes.groupby("ativo"):
        g = g.sort_values("data").set_index("data")
        ind[t]["max20"] = g.maxima.rolling(20).max().shift(1)
        ind[t]["min20"] = g.minima.rolling(20).min().shift(1)
    return acoes, ops, ind


def sinal(nome, x):
    if nome == "recuo (Góes)":
        if x.preco > x.mm50 > x.mm200 and abs(x.preco / x.mm21 - 1) <= 0.03 and x.ifr < 70: return "call"
        if x.preco < x.mm50 < x.mm200 and abs(x.preco / x.mm21 - 1) <= 0.03 and x.ifr > 30: return "put"
    elif nome == "rompimento":
        if x.preco > x.max20 and x.preco > x.mm50 > x.mm200: return "call"
        if x.preco < x.min20 and x.preco < x.mm50 < x.mm200: return "put"
    elif nome == "exagero":
        if x.preco > x.mm200 and x.ifr < 35: return "call"
        if x.preco < x.mm200 and x.ifr > 65: return "put"
    return None


def rodar(acoes, ops, ind, nome_sinal, estrutura, P=P):
    datas = sorted(acoes.data.unique()); idx = {d: i for i, d in enumerate(datas)}
    r = math.log(1 + P["selic"])

    def du(d, venc):
        i = idx[d]
        if venc <= datas[-1]:
            return int(np.searchsorted(datas, venc, side="right")) - 1 - i
        return (len(datas) - 1 - i) + int(np.busday_count(datas[-1].date(), venc.date()))

    ops_dia = {d: g for d, g in ops.groupby("data")}
    ops_cod = {c: g.set_index("data") for c, g in ops.groupby("codigo")}

    def candidatas(d, ativo, tipo, min_neg):
        g = ops_dia.get(d)
        if g is None: return []
        S = ind[ativo].loc[d, "preco"]
        g = g[(g.ativo == ativo) & (g.tipo == tipo) & (g.negocios >= min_neg) & (g.compra > 0) & (g.venda >= g.compra)]
        out = []
        for o in g.itertuples():
            if (o.venda - o.compra) / ((o.venda + o.compra) / 2) > P["max_spread"]: continue
            dias = du(d, o.vencimento)
            if not (P["du_min"] <= dias <= P["du_max"]): continue
            vi = vol_implicita(tipo, (o.compra + o.venda) / 2, S, o.strike, dias / 252, r)
            if not vi: continue
            out.append(dict(codigo=o.codigo, strike=o.strike, venc=o.vencimento, volume=o.volume,
                            delta=abs(gregas(tipo, S, o.strike, dias / 252, r, vi)["delta"])))
        return out

    def escolher(d, ativo, tipo):
        c = [o for o in candidatas(d, ativo, tipo, P["min_negocios"]) if o["volume"] >= P["min_volume"]
             and P["delta_min"] <= o["delta"] <= P["delta_max"]]
        if not c: return None
        compra = max(c, key=lambda o: o["volume"])
        if estrutura == "seca":
            return compra, None
        vend = [o for o in candidatas(d, ativo, tipo, 5) if o["venc"] == compra["venc"]
                and P["delta_venda"][0] <= o["delta"] <= P["delta_venda"][1]
                and ((o["strike"] > compra["strike"]) if tipo == "call" else (o["strike"] < compra["strike"]))]
        if not vend: return None
        return compra, min(vend, key=lambda o: abs(o["delta"] - 0.22))

    def cot(cod, d, campo):
        o = ops_cod[cod]
        if d not in o.index: return 0.0
        if P.get("usar_meio") and o.loc[d, "compra"] > 0 and o.loc[d, "venda"] > 0:  # teste ideal, sem custo de spread
            return float((o.loc[d, "compra"] + o.loc[d, "venda"]) / 2)
        return float(o.loc[d, campo])

    inicio = pd.Timestamp("2023-01-02")
    pend, abertas, trades = [], {}, []
    for d in datas:
        if d < inicio: continue
        for s in pend:  # entradas
            if len(abertas) >= P["max_abertas"] or s["ativo"] in abertas: continue
            pc = cot(s["compra"]["codigo"], d, "venda")
            pv = cot(s["venda"]["codigo"], d, "compra") if s["venda"] else 0.0
            if pc <= 0 or (s["venda"] and pv <= 0): continue
            debito = pc - pv
            if debito <= 0.01: continue
            qtd = P["tiro"] * (1 - P["custo"]) / debito
            abertas[s["ativo"]] = dict(s, entrada=d, debito=debito, qtd=qtd)
        pend = []
        for ativo, t in list(abertas.items()):  # saídas
            if t["entrada"] == d: continue
            venc = pd.Timestamp(t["compra"]["venc"])
            faltam = du(d, venc) if d <= venc else 0
            bc = cot(t["compra"]["codigo"], d, "compra")
            av = cot(t["venda"]["codigo"], d, "venda") if t["venda"] else 0.0
            valor_tela = (bc - av) if (bc > 0 and (not t["venda"] or av > 0)) else None
            alvo = P["alvo_trava"] if t["venda"] else P["alvo_seca"]
            motivo = None
            if valor_tela is not None and valor_tela >= alvo * t["debito"]: motivo = "alvo"
            elif faltam <= P["du_saida"]: motivo = "vencimento"
            if not motivo: continue
            if valor_tela is None:
                if d < venc: continue
                S = ind[ativo].loc[d, "preco"]
                intr = lambda K: max(0.0, (S - K) if t["tipo"] == "call" else (K - S))
                valor_tela = intr(t["compra"]["strike"]) - (intr(t["venda"]["strike"]) if t["venda"] else 0.0)
            valor = max(0.0, valor_tela) * t["qtd"] * (1 - P["custo"])
            trades.append(dict(ativo=ativo, tipo=t["tipo"], entrada=str(t["entrada"].date()), saida=str(d.date()),
                               motivo=motivo, resultado=round(valor - P["tiro"], 2)))
            del abertas[ativo]
        for ativo, xa in ind.items():  # sinais
            if d not in xa.index or ativo in abertas: continue
            x = xa.loc[d]
            if x[["mm21", "mm50", "mm200", "ifr", "max20", "min20"]].isna().any(): continue
            tipo = sinal(nome_sinal, x)
            if not tipo: continue
            e = escolher(d, ativo, tipo)
            if e: pend.append(dict(ativo=ativo, tipo=tipo, compra=e[0], venda=e[1]))
    return pd.DataFrame(trades)


def resumir(tr):
    if tr.empty: return {"ops": 0}
    out = {}
    for nome, g in [("2023-2024 (desenvolvimento)", tr[tr.saida < "2025"]), ("2025-2026 (confirmação)", tr[tr.saida >= "2025"]),
                    ("total", tr)]:
        if g.empty: out[nome] = {"ops": 0}; continue
        out[nome] = {"ops": int(len(g)), "acerto_pct": round((g.resultado > 0).mean() * 100, 1),
                     "resultado_R$_com_tiros_de_100": round(g.resultado.sum(), 0),
                     "media_por_operacao_pct": round(g.resultado.mean(), 1)}
    return out


if __name__ == "__main__":
    acoes, ops, ind = preparar()
    resultados = {}
    for s in ["recuo (Góes)", "rompimento", "exagero"]:
        for e in ["seca", "trava"]:
            tr = rodar(acoes, ops, ind, s, e)
            resultados[f"{s} | {e}"] = resumir(tr)
            print(f"{s} | {e}:", json.dumps(resultados[f'{s} | {e}'], ensure_ascii=False), flush=True)
    json.dump(resultados, open("historico/alternativas.json", "w"), ensure_ascii=False, indent=1)
