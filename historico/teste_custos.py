"""Separa o efeito do método do efeito do custo: refaz testes usando o preço do MEIO da tela (sem pagar a diferença entre compra e venda)."""
import json, sys
sys.path.insert(0, "historico"); sys.path.insert(0, ".")
import simulador2 as s2, simulador3 as s3
acoes, ops, ind = s2.preparar()
out = {}
p2 = dict(s2.P, usar_meio=True)
out["comprador: recuo (Góes) + compra seca | preço do meio"] = s2.resumir(s2.rodar(acoes, ops, ind, "recuo (Góes)", "seca", p2))
print(json.dumps(out, ensure_ascii=False), flush=True)
p3 = dict(s3.P, usar_meio=True, stop_multiplo=1e9)
for nome, f in s3.FILTROS.items():
    out[f"vendedor: {nome} sem stop | preço do meio"] = s2.resumir(s3.rodar(acoes, ops, ind, f, p3))
    print(nome, json.dumps(out[f"vendedor: {nome} sem stop | preço do meio"], ensure_ascii=False), flush=True)
json.dump(out, open("historico/custos.json", "w"), ensure_ascii=False, indent=1)
