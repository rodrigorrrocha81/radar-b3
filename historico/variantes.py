"""Roda o simulador com algumas variações das regras para ver o que muda."""
import json, sys
sys.path.insert(0, "historico"); sys.path.insert(0, ".")
import simulador as s
V = {
 "A_aprovada (stop na média de 50 dias, alvo 2,5x)": {},
 "B_estilo_Goes (sem stop: o tiro é o limite, alvo 2,5x)": {"stop_tendencia": False},
 "C_sem_stop_alvo_2x": {"stop_tendencia": False, "alvo": 2.0},
 "D_sem_stop_alvo_3x": {"stop_tendencia": False, "alvo": 3.0},
 "E_sem_stop_vencimentos_25_a_60_dias": {"stop_tendencia": False, "du_min": 25, "du_max": 60},
}
out = {}
for nome, mud in V.items():
    p = dict(s.P); p.update(mud)
    r, tr, curva = s.main(p, verbose=False)
    chaves = ["n_operacoes", "pct_acerto", "multiplo_medio_ganhos", "multiplo_medio_perdas", "maior_sequencia_perdas",
              "capital_final", "resultado_pct", "pior_queda_pct", "por_ano", "bova11_comprar_e_segurar_pct"]
    out[nome] = {k: r.get(k) for k in chaves}
    out[nome]["resultado_medio_por_operacao_pct"] = round((tr.multiplo.mean() - 1) * 100, 1) if len(tr) else None
    print(nome, json.dumps({k: out[nome][k] for k in chaves[:8] + ["resultado_medio_por_operacao_pct"]}, ensure_ascii=False))
json.dump(out, open("historico/variantes.json", "w"), ensure_ascii=False, indent=1)
