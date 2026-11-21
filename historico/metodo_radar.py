"""Teste com o passado do Método Radar (regras pré-registradas em historico/METODO_RADAR.md)."""
import json, math, sys
import numpy as np, pandas as pd

sys.path.insert(0, "historico"); sys.path.insert(0, ".")
import simulador2 as s2
from opcoes import vol_implicita, gregas

COMUM = dict(tiro=100.0, max_abertas=5, custo=0.0005, selic=0.12, du_saida=3)
H = {
    "H1 compra de call barata": dict(acao="compra", tipo="call", du=(25, 60), delta=(0.40, 0.60), max_spread=0.10,
                                    min_neg=20, alvo=2.0),
    "H2 venda de trava de put com seguro caro": dict(acao="venda", tipo="put", du=(20, 45), delta=(0.20, 0.35),
                                                    delta_prot=(0.05, 0.15), max_spread=0.15, min_neg=10, lucro=0.5),
    "H3 venda de trava de put depois de susto": dict(acao="venda", tipo="put", du=(20, 45), delta=(0.20, 0.35),
                                                    delta_prot=(0.05, 0.15), max_spread=0.15, min_neg=10, lucro=0.5),
}


def preparar():
    acoes, ops, ind = s2.preparar()
    for t, x in ind.items():
        x["vol20"] = np.log(x.preco / x.preco.shift()).rolling(20).std() * math.sqrt(252)
    bova = ind["BOVA11"].preco
    queda10 = (bova / bova.shift(10) - 1)
    q = pd.read_csv("historico/qualidade.csv")
    entregas = json.load(open("historico/entregas_balancos.json"))
    return acoes, ops, ind, queda10, q, entregas


def boa_empresa(q, ativo, d):
    if ativo == "BOVA11": return True
    x = q[(q.ativo == ativo) & (q.entregue <= str(d.date()))]
    if x.empty: return False
    u = x.iloc[-1]
    return pd.notna(u.lucro_12m) and u.lucro_12m > 0 and pd.notna(u.roe) and u.roe > 12


def balanco_no_meio(entregas, ativo, d, venc):
    if ativo == "BOVA11": return False
    return any(str(d.date()) < e <= str(venc.date()) for e in entregas.get(ativo, []))


def rodar(nome, dados):
    acoes, ops, ind, queda10, q, entregas = dados
    h = dict(COMUM, **H[nome])
    datas = sorted(acoes.data.unique()); idx = {d: i for i, d in enumerate(datas)}
    r = math.log(1 + h["selic"])

    def du(d, venc):
        i = idx[d]
        if venc <= datas[-1]:
            return int(np.searchsorted(datas, venc, side="right")) - 1 - i
        return (len(datas) - 1 - i) + int(np.busday_count(datas[-1].date(), venc.date()))

    ops_dia = {d: g for d, g in ops.groupby("data")}
    ops_cod = {c: g.set_index("data") for c, g in ops.groupby("codigo")}
    cot = lambda c, d, k: float(ops_cod[c].loc[d, k]) if d in ops_cod[c].index else 0.0

    def candidatas(d, ativo):
        g = ops_dia.get(d)
        if g is None: return []
        S = ind[ativo].loc[d, "preco"]
        g = g[(g.ativo == ativo) & (g.tipo == h["tipo"]) & (g.negocios >= h["min_neg"]) & (g.compra > 0) & (g.venda >= g.compra)]
        out = []
        for o in g.itertuples():
            if (o.venda - o.compra) / ((o.venda + o.compra) / 2) > h["max_spread"]: continue
            dias = du(d, o.vencimento)
            if not (h["du"][0] <= dias <= h["du"][1]): continue
            vi = vol_implicita(h["tipo"], (o.compra + o.venda) / 2, S, o.strike, dias / 252, r)
            if not vi: continue
            out.append(dict(codigo=o.codigo, strike=o.strike, venc=o.vencimento, volume=o.volume, vi=vi,
                            delta=abs(gregas(h["tipo"], S, o.strike, dias / 252, r, vi)["delta"])))
        return out

    def montar(d, ativo, x):
        c = candidatas(d, ativo)
        principal = [o for o in c if h["delta"][0] <= o["delta"] <= h["delta"][1]]
        if not principal: return None
        p = max(principal, key=lambda o: o["volume"])
        if balanco_no_meio(entregas, ativo, d, p["venc"]): return None
        if nome.startswith("H1") and not (p["vi"] <= 0.9 * x.vol20): return None
        if nome.startswith("H2") and not (p["vi"] >= 1.3 * x.vol20 and p["vi"] > x.vol_ano): return None
        if h["acao"] == "compra": return p, None
        prot = [o for o in c if o["venc"] == p["venc"] and h["delta_prot"][0] <= o["delta"] <= h["delta_prot"][1]
                and o["strike"] < p["strike"]]
        return (p, max(prot, key=lambda o: o["volume"])) if prot else None

    def sinal(ativo, x, d):
        if not boa_empresa(q, ativo, d): return False
        if nome.startswith("H1"): return x.preco > x.mm50 > x.mm200
        if nome.startswith("H2"): return x.preco > x.mm200
        if nome.startswith("H3"): return d in queda10.index and queda10.loc[d] <= -0.07
        return False

    inicio = pd.Timestamp("2023-01-02")
    pend, abertas, trades = [], {}, []
    for d in datas:
        if d < inicio: continue
        for s in pend:
            if len(abertas) >= h["max_abertas"] or s["ativo"] in abertas: continue
            a, b = s["p"], s["prot"]
            if h["acao"] == "compra":
                preco = cot(a["codigo"], d, "venda")
                if preco <= 0: continue
                abertas[s["ativo"]] = dict(s, entrada=d, base=preco, qtd=h["tiro"] * (1 - h["custo"]) / preco)
            else:
                cred = cot(a["codigo"], d, "compra") - cot(b["codigo"], d, "venda")
                if cot(a["codigo"], d, "compra") <= 0 or cot(b["codigo"], d, "venda") <= 0 or cred <= 0.01: continue
                larg = a["strike"] - b["strike"]
                if larg - cred <= 0.01: continue
                abertas[s["ativo"]] = dict(s, entrada=d, base=cred, larg=larg, qtd=h["tiro"] / (larg - cred))
        pend = []
        for ativo, t in list(abertas.items()):
            if t["entrada"] == d: continue
            a, b = t["p"], t["prot"]
            venc = pd.Timestamp(a["venc"])
            faltam = du(d, venc) if d <= venc else 0
            S = ind[ativo].loc[d, "preco"]
            intr = lambda K: max(0.0, (S - K) if h["tipo"] == "call" else (K - S))
            motivo = None
            if h["acao"] == "compra":
                bid = cot(a["codigo"], d, "compra")
                if bid > 0 and bid >= h["alvo"] * t["base"]: motivo, val = "alvo", bid
                elif faltam <= h["du_saida"]:
                    motivo = "vencimento"
                    val = bid if bid > 0 else (intr(a["strike"]) if d >= venc else None)
                if not motivo or val is None: continue
                res = t["qtd"] * val * (1 - h["custo"]) - h["tiro"]
            else:
                av, bp = cot(a["codigo"], d, "venda"), cot(b["codigo"], d, "compra")
                custo = (av - bp) if av > 0 else None
                if custo is not None and custo <= (1 - h["lucro"]) * t["base"]: motivo = "lucro"
                elif faltam <= h["du_saida"]: motivo = "vencimento"
                if not motivo: continue
                if custo is None:
                    if d < venc: continue
                    custo = intr(a["strike"]) - intr(b["strike"])
                custo = min(max(custo, 0.0), t["larg"])
                res = (t["base"] - custo) * t["qtd"] - h["custo"] * 2 * t["qtd"] * t["larg"]
            trades.append(dict(ativo=ativo, entrada=str(t["entrada"].date()), saida=str(d.date()), motivo=motivo,
                               resultado=round(res, 2), preco_base=round(t["base"], 2), codigo=a["codigo"],
                               dias=int((d - t["entrada"]).days)))
            del abertas[ativo]
        for ativo, xa in ind.items():
            if d not in xa.index or ativo in abertas: continue
            x = xa.loc[d]
            if x[["mm50", "mm200", "vol20", "vol_ano"]].isna().any(): continue
            if not sinal(ativo, x, d): continue
            m = montar(d, ativo, x)
            if m: pend.append(dict(ativo=ativo, p=m[0], prot=m[1]))
    return pd.DataFrame(trades)


if __name__ == "__main__":
    dados = preparar()
    out = {}
    for nome in H:
        tr = rodar(nome, dados)
        out[nome] = s2.resumir(tr)
        if not tr.empty:
            out[nome]["por_motivo"] = tr.motivo.value_counts().to_dict()
            out[nome]["preco_medio_por_opcao_ou_credito"] = round(tr.preco_base.mean(), 2)
            out[nome]["dias_medios"] = round(tr.dias.mean(), 1)
            tr.to_csv(f"historico/radar_{nome.split()[0]}.csv", index=False)
        print(nome, json.dumps(out[nome], ensure_ascii=False), flush=True)
    json.dump(out, open("historico/metodo_radar.json", "w"), ensure_ascii=False, indent=1)
