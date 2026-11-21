"""Teste com o passado do lado "seguradora": VENDA de trava (risco máximo conhecido na entrada).

Venda de trava de alta com puts: vende uma put um pouco abaixo do preço e compra outra put mais abaixo
como proteção. Recebe dinheiro na entrada; ganha se a ação não cair muito até o vencimento.
Venda de trava de baixa com calls: o espelho, para quando a ação não deve subir muito.

Hipóteses conservadoras: na entrada vende pela oferta de compra e compra pela oferta de venda;
na saída, o contrário. Entrada no fechamento do dia seguinte ao sinal.
Tamanho: cada operação arrisca no máximo R$ 100 (perda máxima possível = R$ 100).
"""
import json, math, sys
import numpy as np, pandas as pd

sys.path.insert(0, "historico"); sys.path.insert(0, ".")
import simulador2 as s2
from opcoes import vol_implicita, gregas

P = dict(du_min=20, du_max=45, delta_vendida=(0.20, 0.35), delta_comprada=(0.05, 0.15),
         min_negocios=10, max_spread=0.40, lucro_alvo=0.50, stop_multiplo=2.0, du_saida=3,
         risco=100.0, max_abertas=5, custo=0.0005, selic=0.12)


def rodar(acoes, ops, ind, filtro, P=P):
    datas = sorted(acoes.data.unique()); idx = {d: i for i, d in enumerate(datas)}
    r = math.log(1 + P["selic"])

    def du(d, venc):
        i = idx[d]
        if venc <= datas[-1]:
            return int(np.searchsorted(datas, venc, side="right")) - 1 - i
        return (len(datas) - 1 - i) + int(np.busday_count(datas[-1].date(), venc.date()))

    ops_dia = {d: g for d, g in ops.groupby("data")}
    ops_cod = {c: g.set_index("data") for c, g in ops.groupby("codigo")}
    def cot(c, d, k):
        o = ops_cod[c]
        if d not in o.index: return 0.0
        if P.get("usar_meio") and o.loc[d, "compra"] > 0 and o.loc[d, "venda"] > 0:  # teste ideal, sem custo de spread
            return float((o.loc[d, "compra"] + o.loc[d, "venda"]) / 2)
        return float(o.loc[d, k])

    def montar(d, ativo, tipo):
        g = ops_dia.get(d)
        if g is None: return None
        S = ind[ativo].loc[d, "preco"]
        g = g[(g.ativo == ativo) & (g.tipo == tipo) & (g.negocios >= P["min_negocios"]) & (g.compra > 0) & (g.venda >= g.compra)]
        c = []
        for o in g.itertuples():
            if (o.venda - o.compra) / ((o.venda + o.compra) / 2) > P["max_spread"]: continue
            dias = du(d, o.vencimento)
            if not (P["du_min"] <= dias <= P["du_max"]): continue
            vi = vol_implicita(tipo, (o.compra + o.venda) / 2, S, o.strike, dias / 252, r)
            if not vi: continue
            c.append(dict(codigo=o.codigo, strike=o.strike, venc=o.vencimento, volume=o.volume,
                          delta=abs(gregas(tipo, S, o.strike, dias / 252, r, vi)["delta"])))
        vend = [o for o in c if P["delta_vendida"][0] <= o["delta"] <= P["delta_vendida"][1]]
        if not vend: return None
        v = max(vend, key=lambda o: o["volume"])
        prot = [o for o in c if o["venc"] == v["venc"] and P["delta_comprada"][0] <= o["delta"] <= P["delta_comprada"][1]
                and ((o["strike"] < v["strike"]) if tipo == "put" else (o["strike"] > v["strike"]))]
        if not prot: return None
        return v, max(prot, key=lambda o: o["volume"])

    inicio = pd.Timestamp("2023-01-02")
    pend, abertas, trades = [], {}, []
    for d in datas:
        if d < inicio: continue
        for s in pend:
            if len(abertas) >= P["max_abertas"] or s["ativo"] in abertas: continue
            v, p = s["vendida"], s["comprada"]
            credito = cot(v["codigo"], d, "compra") - cot(p["codigo"], d, "venda")
            if cot(v["codigo"], d, "compra") <= 0 or cot(p["codigo"], d, "venda") <= 0 or credito <= 0.01: continue
            largura = abs(v["strike"] - p["strike"])
            perda_max = largura - credito
            if perda_max <= 0.01: continue
            qtd = P["risco"] / perda_max
            abertas[s["ativo"]] = dict(s, entrada=d, credito=credito, largura=largura, qtd=qtd)
        pend = []
        for ativo, t in list(abertas.items()):
            if t["entrada"] == d: continue
            v, p = t["vendida"], t["comprada"]
            venc = pd.Timestamp(v["venc"])
            faltam = du(d, venc) if d <= venc else 0
            av, bp = cot(v["codigo"], d, "venda"), cot(p["codigo"], d, "compra")
            custo_zerar = (av - bp) if av > 0 else None  # quanto custa desfazer hoje
            motivo = None
            if custo_zerar is not None and custo_zerar <= (1 - P["lucro_alvo"]) * t["credito"]: motivo = "lucro"
            elif custo_zerar is not None and custo_zerar >= P["stop_multiplo"] * t["credito"]: motivo = "stop"
            elif faltam <= P["du_saida"]: motivo = "vencimento"
            if not motivo: continue
            if custo_zerar is None:
                if d < venc: continue
                S = ind[ativo].loc[d, "preco"]
                intr = lambda K: max(0.0, (K - S) if t["tipo"] == "put" else (S - K))
                custo_zerar = intr(v["strike"]) - intr(p["strike"])
            custo_zerar = min(max(custo_zerar, 0.0), t["largura"])
            res = (t["credito"] - custo_zerar) * t["qtd"] - P["custo"] * 2 * t["qtd"] * t["largura"]
            trades.append(dict(ativo=ativo, tipo=t["tipo"], entrada=str(t["entrada"].date()), saida=str(d.date()),
                               motivo=motivo, resultado=round(res, 2)))
            del abertas[ativo]
        for ativo, xa in ind.items():
            if d not in xa.index or ativo in abertas: continue
            x = xa.loc[d]
            if x[["mm50", "mm200", "vol_ano"]].isna().any(): continue
            tipo = filtro(x)
            if not tipo: continue
            m = montar(d, ativo, tipo)
            if m: pend.append(dict(ativo=ativo, tipo=tipo, vendida=m[0], comprada=m[1]))
    return pd.DataFrame(trades)


FILTROS = {
    # Vende trava de puts quando a ação está acima da média de 200 dias (alta de longo prazo); calls no contrário.
    "segue a tendência longa": lambda x: "put" if x.preco > x.mm200 else "call",
    # Só vende trava de puts em alta clara (preço > média 50 > média 200); calls em baixa clara.
    "só em tendência clara": lambda x: "put" if x.preco > x.mm50 > x.mm200 else ("call" if x.preco < x.mm50 < x.mm200 else None),
}

if __name__ == "__main__":
    acoes, ops, ind = s2.preparar()
    out = {}
    for nome, f in FILTROS.items():
        for stop in [2.0, None]:
            p = dict(P); p["stop_multiplo"] = stop if stop else 1e9
            tr = rodar(acoes, ops, ind, f, p)
            chave = f"{nome} | {'com stop (perda de 1x o crédito)' if stop else 'sem stop'}"
            out[chave] = s2.resumir(tr)
            if not tr.empty:
                out[chave]["por_motivo"] = tr.motivo.value_counts().to_dict()
                out[chave]["pior_operacao"] = float(tr.resultado.min())
            print(chave, json.dumps(out[chave], ensure_ascii=False), flush=True)
    json.dump(out, open("historico/vendedor.json", "w"), ensure_ascii=False, indent=1)
