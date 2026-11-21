"""Módulo de opções: lê o arquivo oficial da B3 (COTAHIST), filtra opções com liquidez
e calcula volatilidade implícita e gregas (Black-Scholes, aproximação europeia).
São medidas calculadas, não recomendação de compra ou venda."""
import math, datetime as dt
import numpy as np
from dia_de_pregao import FERIADOS

# Regras de liquidez e de janela (ajustáveis)
MIN_NEGOCIOS = 20          # negócios no dia
MIN_VOLUME = 100_000       # R$ negociados no dia
DIAS_UTEIS_MIN, DIAS_UTEIS_MAX = 5, 60
FAIXA_STRIKE = (0.85, 1.15)  # strike entre 85% e 115% do preço da ação
MAX_SPREAD = 0.40          # diferença máxima entre oferta de compra e de venda (40% do preço médio)
FERIADOS_NP = np.array(sorted(FERIADOS), dtype="datetime64[D]")

def _preco(campo):  # campos de preço da B3 têm 2 casas decimais implícitas
    return int(campo) / 100

def ler_cotahist(texto, raizes):
    """raizes: {"PETR": "PETR4", ...}. Devolve (precos_acoes, opcoes)."""
    acoes, opcoes = {}, []
    tickers = set(raizes.values())
    for l in texto.splitlines():
        if not l.startswith("01"):
            continue
        cod, merc = l[12:24].strip(), l[24:27]
        if merc == "010" and cod in tickers:
            acoes[cod] = _preco(l[108:121])
        elif merc in ("070", "080") and cod[:4] in raizes:
            opcoes.append({
                "codigo": cod, "ativo": raizes[cod[:4]],
                "tipo": "call" if merc == "070" else "put",
                "ultimo": _preco(l[108:121]), "compra": _preco(l[121:134]), "venda": _preco(l[134:147]),
                "negocios": int(l[147:152]), "volume": int(l[170:188]) / 100,
                "strike": _preco(l[188:201]),
                "vencimento": dt.datetime.strptime(l[202:210], "%Y%m%d").date(),
                "pregao": dt.datetime.strptime(l[2:10], "%Y%m%d").date(),
            })
    return acoes, opcoes

def dias_uteis(de, ate):
    return int(np.busday_count(de, ate, holidays=FERIADOS_NP))

# --- Black-Scholes ---
def _N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def _n(x): return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)

def bs_preco(tipo, S, K, T, r, s):
    d1 = (math.log(S / K) + (r + s * s / 2) * T) / (s * math.sqrt(T)); d2 = d1 - s * math.sqrt(T)
    if tipo == "call": return S * _N(d1) - K * math.exp(-r * T) * _N(d2)
    return K * math.exp(-r * T) * _N(-d2) - S * _N(-d1)

def vol_implicita(tipo, preco, S, K, T, r):
    intrinseco = max(0.0, S - K * math.exp(-r * T)) if tipo == "call" else max(0.0, K * math.exp(-r * T) - S)
    if preco <= intrinseco + 1e-6:
        return None  # preço abaixo do valor mínimo teórico: não dá para calcular
    lo, hi = 0.01, 5.0
    if bs_preco(tipo, S, K, T, r, hi) < preco: return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if bs_preco(tipo, S, K, T, r, mid) > preco: hi = mid
        else: lo = mid
    return (lo + hi) / 2

def gregas(tipo, S, K, T, r, s):
    d1 = (math.log(S / K) + (r + s * s / 2) * T) / (s * math.sqrt(T)); d2 = d1 - s * math.sqrt(T)
    gamma = _n(d1) / (S * s * math.sqrt(T))
    vega = S * _n(d1) * math.sqrt(T) / 100                     # R$ por 1 ponto de volatilidade
    if tipo == "call":
        delta = _N(d1); theta = -S * _n(d1) * s / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * _N(d2)
    else:
        delta = _N(d1) - 1; theta = -S * _n(d1) * s / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * _N(-d2)
    return {"delta": delta, "gamma": gamma, "theta_dia": theta / 252, "vega": vega}

def preco_referencia(o):
    """Usa o meio entre compra e venda quando ambos existem e o spread é razoável; senão, o último negócio."""
    c, v = o["compra"], o["venda"]
    if c > 0 and v > 0 and v >= c and (v - c) / ((v + c) / 2) <= 0.25:
        return (c + v) / 2, "meio"
    return o["ultimo"], "último"

def analisar_opcoes(texto, raizes, selic_pct, vol_hist):
    """vol_hist: {"PETR4": {"vol20": 0.43, "vol_ano": 0.31}}. Devolve {ativo: resumo}."""
    acoes, opcoes = ler_cotahist(texto, raizes)
    r = math.log(1 + selic_pct / 100)
    resultado = {}
    for ativo in raizes.values():
        S = acoes.get(ativo)
        res = {"preco_b3": S, "total_series": 0, "liquidas": [], "vi_atm": None, "vencimento_ref": None}
        if not S:
            resultado[ativo] = res; continue
        todas = [o for o in opcoes if o["ativo"] == ativo]
        res["total_series"] = len(todas)
        for o in todas:
            du = dias_uteis(o["pregao"], o["vencimento"])
            if not (o["compra"] > 0 and o["venda"] >= o["compra"]
                    and (o["venda"] - o["compra"]) / ((o["venda"] + o["compra"]) / 2) <= MAX_SPREAD
                    and o["negocios"] >= MIN_NEGOCIOS and o["volume"] >= MIN_VOLUME
                    and DIAS_UTEIS_MIN <= du <= DIAS_UTEIS_MAX
                    and FAIXA_STRIKE[0] <= o["strike"] / S <= FAIXA_STRIKE[1]):
                continue
            T = du / 252
            p, origem = preco_referencia(o)
            vi = vol_implicita(o["tipo"], p, S, o["strike"], T, r)
            if vi is None: continue
            g = gregas(o["tipo"], S, o["strike"], T, r, vi)
            spread = (o["venda"] - o["compra"]) / ((o["venda"] + o["compra"]) / 2) * 100 if o["compra"] > 0 and o["venda"] > 0 else None
            res["liquidas"].append({
                "codigo": o["codigo"], "tipo": o["tipo"], "strike": o["strike"],
                "vencimento": str(o["vencimento"]), "dias_uteis": du,
                "preco": round(p, 2), "preco_origem": origem, "compra": o["compra"], "venda": o["venda"],
                "spread_pct": None if spread is None else round(spread, 1),
                "negocios": o["negocios"], "volume": round(o["volume"]),
                "moneyness_pct": round((o["strike"] / S - 1) * 100, 1),
                "vi_pct": round(vi * 100, 1), "delta": round(g["delta"], 2), "gamma": round(g["gamma"], 3),
                "theta_dia": round(g["theta_dia"], 3), "vega": round(g["vega"], 3),
            })
        liq = res["liquidas"]
        # Volatilidade implícita "no dinheiro": média das opções mais próximas do preço,
        # no vencimento líquido mais próximo com pelo menos 10 dias úteis.
        vencs = sorted({(x["dias_uteis"], x["vencimento"]) for x in liq if x["dias_uteis"] >= 10})
        for _, ref in vencs:
            perto = sorted([x for x in liq if x["vencimento"] == ref], key=lambda x: abs(x["moneyness_pct"]))[:4]
            if len(perto) >= 2:  # com uma série só, a medida não é confiável
                res["vi_atm"] = round(sum(x["vi_pct"] for x in perto) / len(perto), 1)
                res["vencimento_ref"] = ref
                break
        vh = vol_hist.get(ativo, {})
        if res["vi_atm"] and vh.get("vol_ano"):
            # Compara com a volatilidade de 1 ano (mais estável que a de 20 dias, que oscila com eventos pontuais)
            razao = res["vi_atm"] / vh["vol_ano"]
            res["vi_vs_vol_ano"] = round(razao, 2)
            res["leitura_vi"] = ("caras" if razao > 1.2 else "baratas" if razao < 0.8 else "em linha")
        if res["vi_atm"] and vh.get("vol20"):
            res["vi_vs_vol20"] = round(res["vi_atm"] / vh["vol20"], 2)
        res["liquidas"].sort(key=lambda x: -x["volume"])
        res["n_liquidas"] = len(res["liquidas"])
        res["liquidas"] = res["liquidas"][:10]
        resultado[ativo] = res
    return resultado
