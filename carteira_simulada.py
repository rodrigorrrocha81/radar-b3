"""Carteira simulada (dinheiro de mentira): registra, todo dia de pregão, o que as regras mandariam fazer
e acompanha o resultado como se fosse de verdade. Nada aqui é ordem real nem recomendação.

Duas estratégias, as mesmas do teste com o passado:
  "compra"  -> estilo Góes: compra seca de call/put depois de um recuo dentro da tendência;
               sai com 2,5x o valor pago ou faltando 3 dias úteis para o vencimento.
  "venda"   -> estilo "seguradora": venda de trava (vende uma opção e compra outra mais distante
               como proteção) a favor da tendência de longo prazo; sai com 50% do lucro máximo
               ou faltando 3 dias úteis para o vencimento.
Cada operação usa R$ 100 (na compra, o valor pago; na venda, a perda máxima possível).
Preços conservadores: entra no fechamento do pregão seguinte ao sinal, comprando pela oferta de
venda e vendendo pela oferta de compra.
"""
import datetime as dt, json, math, pathlib
from opcoes import ler_cotahist, dias_uteis, vol_implicita, gregas

ARQ = pathlib.Path("carteira_simulada.json")
TIRO = 100.0
MAX_ABERTAS = 5
CUSTO = 0.0005


def _estado():
    if ARQ.exists():
        return json.loads(ARQ.read_text())
    return {"inicio": None, "ultimo_pregao": None, "pendentes": [], "abertas": [], "fechadas": []}


def _candidatas(opcoes, ativo, tipo, S, pregao, r, du_min, du_max, min_neg):
    out = []
    for o in opcoes:
        if o["ativo"] != ativo or o["tipo"] != tipo or o["negocios"] < min_neg: continue
        if o["compra"] <= 0 or o["venda"] < o["compra"]: continue
        if (o["venda"] - o["compra"]) / ((o["venda"] + o["compra"]) / 2) > 0.40: continue
        du = dias_uteis(pregao, o["vencimento"])
        if not (du_min <= du <= du_max): continue
        vi = vol_implicita(tipo, (o["compra"] + o["venda"]) / 2, S, o["strike"], du / 252, r)
        if not vi: continue
        out.append(dict(o, du=du, delta=abs(gregas(tipo, S, o["strike"], du / 252, r, vi)["delta"])))
    return out


def _sinal_compra(a):
    p, m21, m50, m200, ifr = a["preco"], a["mm21"], a["mm50"], a["mm200"], a["ifr14"]
    perto = abs(p / m21 - 1) <= 0.03
    if p > m50 > m200 and perto and ifr < 70: return "call"
    if p < m50 < m200 and perto and ifr > 30: return "put"
    return None


def atualizar(texto_b3, pregao, ativos, selic_pct):
    """texto_b3: arquivo diário da B3; pregao: data (date); ativos: lista de dicts do dados.json."""
    est = _estado()
    if est["ultimo_pregao"] == str(pregao):
        return resumo(est)  # já processado hoje
    est["inicio"] = est["inicio"] or str(pregao)
    raizes = {a["ativo"][:4]: a["ativo"] for a in ativos}
    precos, opcoes = ler_cotahist(texto_b3, raizes)
    por_cod = {o["codigo"]: o for o in opcoes}
    r = math.log(1 + selic_pct / 100)
    q = lambda cod, campo: (por_cod.get(cod) or {}).get(campo, 0.0)

    # 1) entradas decididas no pregão anterior
    for s in est["pendentes"]:
        if sum(1 for t in est["abertas"] if t["estrategia"] == s["estrategia"]) >= MAX_ABERTAS: continue
        if any(t["ativo"] == s["ativo"] and t["estrategia"] == s["estrategia"] for t in est["abertas"]): continue
        if s["estrategia"] == "compra":
            preco = q(s["codigo"], "venda")
            if preco <= 0: continue
            est["abertas"].append(dict(s, entrada=str(pregao), preco_entrada=preco, qtd=TIRO * (1 - CUSTO) / preco))
        else:
            credito = q(s["vendida"], "compra") - q(s["protecao"], "venda")
            if q(s["vendida"], "compra") <= 0 or q(s["protecao"], "venda") <= 0 or credito <= 0.01: continue
            perda_max = s["largura"] - credito
            if perda_max <= 0.01: continue
            est["abertas"].append(dict(s, entrada=str(pregao), credito=round(credito, 2), qtd=TIRO / perda_max))
    est["pendentes"] = []

    # 2) atualizar e encerrar operações abertas
    restantes = []
    for t in est["abertas"]:
        S = precos.get(t["ativo"])
        faltam = dias_uteis(pregao, dt.date.fromisoformat(t["vencimento"]))
        if t["estrategia"] == "compra":
            bid = q(t["codigo"], "compra")
            valor_un = bid if bid > 0 else t.get("valor_un", t["preco_entrada"])
            t["valor_un"] = valor_un
            t["resultado"] = round(t["qtd"] * valor_un * (1 - CUSTO) - TIRO, 2)
            motivo = "alvo (2,5x)" if bid >= 2.5 * t["preco_entrada"] else ("vencimento próximo" if faltam <= 3 else None)
            if motivo is None and faltam <= 0 and S:
                valor_un = max(0.0, (S - t["strike"]) if t["tipo"] == "call" else (t["strike"] - S)); motivo = "venceu"
                t["resultado"] = round(t["qtd"] * valor_un - TIRO, 2)
        else:
            ask_v, bid_p = q(t["vendida"], "venda"), q(t["protecao"], "compra")
            custo = (ask_v - bid_p) if ask_v > 0 else t.get("custo_zerar", t["credito"])
            custo = min(max(custo, 0.0), t["largura"])
            t["custo_zerar"] = round(custo, 2)
            t["resultado"] = round((t["credito"] - custo) * t["qtd"], 2)
            motivo = "lucro (50%)" if custo <= 0.5 * t["credito"] else ("vencimento próximo" if faltam <= 3 else None)
        if motivo and t["entrada"] != str(pregao):
            t.update(saida=str(pregao), motivo=motivo)
            est["fechadas"].append(t)
        else:
            restantes.append(t)
    est["abertas"] = restantes

    # 3) sinais de hoje (entram no próximo pregão)
    for a in ativos:
        S = precos.get(a["ativo"])
        if not S or any(a.get(k) is None for k in ["mm21", "mm50", "mm200", "ifr14"]): continue
        # compra (estilo Góes)
        tipo = _sinal_compra(a)
        if tipo and not any(t["ativo"] == a["ativo"] and t["estrategia"] == "compra" for t in est["abertas"]):
            c = [o for o in _candidatas(opcoes, a["ativo"], tipo, S, pregao, r, 25, 60, 20)
                 if o["volume"] >= 100_000 and 0.35 <= o["delta"] <= 0.55]
            if c:
                o = max(c, key=lambda x: x["volume"])
                est["pendentes"].append(dict(estrategia="compra", ativo=a["ativo"], tipo=tipo, codigo=o["codigo"],
                                             strike=o["strike"], vencimento=str(o["vencimento"]), sinal=str(pregao)))
        # venda de trava (seguradora), a favor da tendência longa
        tipo_v = "put" if a["preco"] > a["mm200"] else "call"
        if not any(t["ativo"] == a["ativo"] and t["estrategia"] == "venda" for t in est["abertas"]):
            c = _candidatas(opcoes, a["ativo"], tipo_v, S, pregao, r, 20, 45, 10)
            vend = [o for o in c if 0.20 <= o["delta"] <= 0.35]
            if vend:
                v = max(vend, key=lambda x: x["volume"])
                prot = [o for o in c if o["vencimento"] == v["vencimento"] and 0.05 <= o["delta"] <= 0.15
                        and ((o["strike"] < v["strike"]) if tipo_v == "put" else (o["strike"] > v["strike"]))]
                if prot:
                    p = max(prot, key=lambda x: x["volume"])
                    est["pendentes"].append(dict(estrategia="venda", ativo=a["ativo"], tipo=tipo_v,
                                                 vendida=v["codigo"], protecao=p["codigo"],
                                                 strike_vendida=v["strike"], strike_protecao=p["strike"],
                                                 largura=round(abs(v["strike"] - p["strike"]), 2),
                                                 vencimento=str(v["vencimento"]), sinal=str(pregao)))
    est["ultimo_pregao"] = str(pregao)
    ARQ.write_text(json.dumps(est, ensure_ascii=False, indent=1, default=str))
    return resumo(est)


def resumo(est):
    out = {"inicio": est["inicio"], "ultimo_pregao": est["ultimo_pregao"], "estrategias": {}}
    for e, nome in [("compra", "Compra de opções (estilo Góes)"), ("venda", "Venda de trava (estilo seguradora)")]:
        f = [t for t in est["fechadas"] if t["estrategia"] == e]
        a = [t for t in est["abertas"] if t["estrategia"] == e]
        out["estrategias"][e] = {
            "nome": nome, "fechadas": len(f), "ganhou": sum(1 for t in f if t["resultado"] > 0),
            "resultado_fechadas": round(sum(t["resultado"] for t in f), 2),
            "resultado_abertas": round(sum(t.get("resultado", 0) for t in a), 2),
            "abertas": a, "ultimas_fechadas": f[-5:],
            "aguardando_entrada": [p for p in est["pendentes"] if p["estrategia"] == e],
        }
    return out
