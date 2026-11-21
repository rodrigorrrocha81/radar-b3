"""Teste com o passado (backtest) das regras R1-R4 e R8, no estilo "10 tiros".
Usa só os arquivos oficiais da B3 (preço de fechamento das ações e das opções).

Hipóteses para ser conservador:
- O sinal é calculado no fechamento de um dia e a compra acontece no fechamento do pregão seguinte,
  pagando a melhor oferta de VENDA (o preço mais caro da tela).
- A venda acontece pela melhor oferta de COMPRA (o preço mais barato da tela).
"""
import csv, glob, gzip, json, math, sys, datetime as dt
from collections import defaultdict
import numpy as np, pandas as pd

sys.path.insert(0, ".")
from opcoes import vol_implicita, gregas

# ---------------- Parâmetros das regras (aprovadas como ponto de partida) ----------------
P = dict(
    recuo_max=0.03,          # R1/R2: preço até 3% da média de 21 dias
    ifr_max_call=70, ifr_min_put=30,
    du_min=15, du_max=45,    # R3: vencimento entre 15 e 45 dias úteis
    delta_min=0.35, delta_max=0.55,
    min_negocios=20, min_volume=100_000, max_spread=0.40,
    caras=1.2,               # R4: VI acima de 1,2x a volatilidade de 1 ano
    alvo=2.5,                # R8: sair com 2,5x o valor pago
    du_saida=3,              # R8: zerar faltando 3 dias úteis para o vencimento
    stop_tendencia=True,     # R8: sair se o preço cruzar a média de 50 dias contra a operação
    capital=1000.0, fracao_tiro=0.10, max_abertas=5,
    custo=0.0005,            # taxas por lado (0,05%)
    selic=0.12,              # juros médios do período para o cálculo da VI
)


def carregar():
    dfs = [pd.read_csv(f, dtype={"data": str, "vencimento": str}) for f in sorted(glob.glob("historico/b3_*.csv.gz"))]
    df = pd.concat(dfs, ignore_index=True)
    df["data"] = pd.to_datetime(df.data, format="%Y%m%d")
    acoes = df[df.tipo == "acao"].copy()
    ops = df[df.tipo != "acao"].copy()
    ops["vencimento"] = pd.to_datetime(ops.vencimento, format="%Y%m%d")
    return acoes, ops


def indicadores(acoes):
    out = {}
    for t, g in acoes.groupby("ativo"):
        g = g.sort_values("data").set_index("data")
        f = g.ultimo
        d = f.diff()
        ganho = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        perda = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        x = pd.DataFrame({"preco": f, "mm21": f.rolling(21).mean(), "mm50": f.rolling(50).mean(),
                          "mm200": f.rolling(200).mean(), "ifr": 100 - 100 / (1 + ganho / perda),
                          "vol_ano": np.log(f / f.shift()).rolling(252).std() * math.sqrt(252)})
        out[t] = x
    return out


def main(P=P, verbose=True):
    acoes, ops = carregar()
    ind = indicadores(acoes)
    datas = sorted(acoes.data.unique())
    idx = {d: i for i, d in enumerate(datas)}
    r = math.log(1 + P["selic"])

    def du(d, venc):  # dias úteis pelo próprio calendário de pregões; depois do fim dos dados, dias de semana
        i = idx[d]
        if venc <= datas[-1]:
            return int(np.searchsorted(datas, venc, side="right")) - 1 - i
        return (len(datas) - 1 - i) + int(np.busday_count(datas[-1].date(), venc.date()))

    ops_dia = {d: g for d, g in ops.groupby("data")}
    ops_cod = {c: g.set_index("data") for c, g in ops.groupby("codigo")}

    def escolher(d, ativo, tipo):
        g = ops_dia.get(d)
        if g is None: return None
        S = ind[ativo].loc[d, "preco"]
        g = g[(g.ativo == ativo) & (g.tipo == tipo) & (g.negocios >= P["min_negocios"]) & (g.volume >= P["min_volume"])
              & (g.compra > 0) & (g.venda >= g.compra)]
        melhores = []
        for o in g.itertuples():
            if (o.venda - o.compra) / ((o.venda + o.compra) / 2) > P["max_spread"]: continue
            dias = du(d, o.vencimento)
            if not (P["du_min"] <= dias <= P["du_max"]): continue
            T = dias / 252
            vi = vol_implicita(tipo, (o.compra + o.venda) / 2, S, o.strike, T, r)
            if not vi: continue
            delta = abs(gregas(tipo, S, o.strike, T, r, vi)["delta"])
            if P["delta_min"] <= delta <= P["delta_max"]:
                melhores.append((o.volume, o.codigo, vi, delta, dias, o.strike, o.vencimento))
        return max(melhores) if melhores else None

    # -------- Passo 1: sinais e escolha da opção --------
    inicio = pd.Timestamp("2023-01-02")
    pendentes, trades = [], []
    abertas = {}  # ativo -> trade
    capital_caixa = P["capital"]
    curva = []
    for d in datas:
        if d < inicio: continue
        # 1a) executar entradas decididas ontem
        for s in pendentes:
            if len(abertas) >= P["max_abertas"] or s["ativo"] in abertas: continue
            o = ops_cod[s["codigo"]]
            if d not in o.index or o.loc[d, "venda"] <= 0: continue
            preco = float(o.loc[d, "venda"])
            patrimonio = capital_caixa + sum(t["custo_total"] for t in abertas.values())
            tiro = patrimonio * P["fracao_tiro"]
            if tiro <= 0 or capital_caixa < tiro: continue
            capital_caixa -= tiro
            abertas[s["ativo"]] = dict(s, entrada=str(d.date()), preco_entrada=preco, custo_total=tiro,
                                       qtd=tiro * (1 - P["custo"]) / preco)
        pendentes = []
        # 1b) saídas
        for ativo, t in list(abertas.items()):
            o = ops_cod[t["codigo"]]
            x = ind[ativo].loc[d]
            venc = pd.Timestamp(t["vencimento"])
            faltam = du(d, venc) if d <= venc else 0
            motivo = None
            bid = float(o.loc[d, "compra"]) if d in o.index else 0.0
            ult = float(o.loc[d, "ultimo"]) if d in o.index else 0.0
            if bid > 0 and bid >= P["alvo"] * t["preco_entrada"]:
                motivo = "alvo"
            elif P["stop_tendencia"] and ((t["tipo"] == "call" and x.preco < x.mm50) or (t["tipo"] == "put" and x.preco > x.mm50)):
                motivo = "tendência quebrou"
            elif faltam <= P["du_saida"]:
                motivo = "perto do vencimento"
            if not motivo: continue
            saida = bid if bid > 0 else (ult if ult > 0 else None)
            if saida is None:
                if d >= venc:  # venceu sem negócio: vale o que estiver dentro do dinheiro
                    saida = max(0.0, (x.preco - t["strike"]) if t["tipo"] == "call" else (t["strike"] - x.preco))
                else:
                    continue  # sem preço hoje; tenta amanhã
            valor = t["qtd"] * saida * (1 - P["custo"])
            capital_caixa += valor
            t.update(saida=str(d.date()), preco_saida=round(saida, 2), motivo=motivo,
                     resultado=round(valor - t["custo_total"], 2), multiplo=round(valor / t["custo_total"], 2))
            trades.append(t)
            del abertas[ativo]
        # 1c) novos sinais no fechamento de hoje
        for ativo, x_all in ind.items():
            if d not in x_all.index or ativo in abertas: continue
            x = x_all.loc[d]
            if x[["mm21", "mm50", "mm200", "ifr", "vol_ano"]].isna().any(): continue
            tipo = None
            if x.preco > x.mm50 > x.mm200 and abs(x.preco / x.mm21 - 1) <= P["recuo_max"] and x.ifr < P["ifr_max_call"]:
                tipo = "call"
            elif x.preco < x.mm50 < x.mm200 and abs(x.preco / x.mm21 - 1) <= P["recuo_max"] and x.ifr > P["ifr_min_put"]:
                tipo = "put"
            if not tipo: continue
            e = escolher(d, ativo, tipo)
            if not e: continue
            _, cod, vi, delta, dias, K, venc = e
            pendentes.append(dict(ativo=ativo, tipo=tipo, codigo=cod, sinal=str(d.date()), strike=K,
                                  vencimento=str(venc.date()), vi=round(vi * 100, 1), delta=round(delta, 2),
                                  vi_vs_vol=round(vi / x.vol_ano, 2), caras=bool(vi / x.vol_ano > P["caras"])))
        patrimonio = capital_caixa + sum(t["custo_total"] for t in abertas.values())
        curva.append((str(d.date()), round(patrimonio, 2)))

    # -------- Resumo --------
    tr = pd.DataFrame(trades)
    res = {"parametros": P, "periodo": [curva[0][0], curva[-1][0]], "n_operacoes": len(tr)}
    if len(tr):
        ganhos = tr[tr.resultado > 0]; perdas = tr[tr.resultado <= 0]
        seq = mx = 0
        for v in tr.resultado:
            seq = seq + 1 if v <= 0 else 0; mx = max(mx, seq)
        eq = pd.Series([c[1] for c in curva])
        res.update(
            pct_acerto=round(len(ganhos) / len(tr) * 100, 1),
            multiplo_medio_ganhos=round(ganhos.multiplo.mean(), 2) if len(ganhos) else None,
            multiplo_medio_perdas=round(perdas.multiplo.mean(), 2) if len(perdas) else None,
            maior_sequencia_perdas=int(mx),
            capital_final=curva[-1][1],
            pior_queda_pct=round(((eq / eq.cummax()) - 1).min() * 100, 1),
            por_motivo=tr.motivo.value_counts().to_dict(),
            por_ano={a: {"ops": int(len(g)), "acerto_pct": round((g.resultado > 0).mean() * 100, 1),
                         "resultado": round(g.resultado.sum(), 2)} for a, g in tr.groupby(tr.saida.str[:4])},
            por_ativo={a: {"ops": int(len(g)), "resultado": round(g.resultado.sum(), 2)} for a, g in tr.groupby("ativo")},
            caras_vs_nao={str(k): {"ops": int(len(g)), "acerto_pct": round((g.resultado > 0).mean() * 100, 1),
                                   "multiplo_medio": round(g.multiplo.mean(), 2)} for k, g in tr.groupby("caras")},
        )
    # Comparação: comprar BOVA11 e segurar
    b = ind["BOVA11"].preco
    b = b[b.index >= inicio]
    res["bova11_comprar_e_segurar_pct"] = round((b.iloc[-1] / b.iloc[0] - 1) * 100, 1)
    res["resultado_pct"] = round((curva[-1][1] / P["capital"] - 1) * 100, 1)
    if verbose:
        print(json.dumps({k: v for k, v in res.items() if k != "parametros"}, ensure_ascii=False, indent=1))
    return res, tr, curva


if __name__ == "__main__":
    res, tr, curva = main()
    json.dump({"resumo": res, "operacoes": tr.to_dict("records"), "curva": curva},
              open("historico/resultado.json", "w"), ensure_ascii=False, indent=1, default=str)
