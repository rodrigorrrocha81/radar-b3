"""Teste honesto do "caiu muito, agora sobe" com TODAS as ações da B3 (regras em historico/CAIU_MUITO.md)."""
import glob, json
import numpy as np, pandas as pd

FRACOES = [2, 3, 4, 5, 8, 10, 20, 25, 50, 100, 200, 1000]


def carregar():
    df = pd.concat([pd.read_csv(f, dtype={"data": str}) for f in sorted(glob.glob("historico/todas_*.csv.gz"))])
    df["data"] = pd.to_datetime(df.data, format="%Y%m%d")
    df = df.drop_duplicates(["data", "codigo"])
    P = df.pivot(index="data", columns="codigo", values="fechamento").sort_index()
    V = df.pivot(index="data", columns="codigo", values="volume").sort_index()
    return P, V


def ajustar_desdobramentos(P):
    """Corrige saltos de preço que são frações exatas (desdobramento/grupamento), mantendo quedas reais."""
    A = P.copy()
    ajustes = []
    for c in P.columns:
        s = P[c].dropna()
        if len(s) < 2: continue
        r = s / s.shift()
        fator = pd.Series(1.0, index=s.index)
        for d, x in r.dropna().items():
            if 0.7 < x < 1.4: continue
            for k in FRACOES:
                for alvo in (k, 1 / k):
                    if abs(x / alvo - 1) < 0.02:
                        fator.loc[:d] = fator.loc[:d]  # nada antes
                        fator.loc[fator.index < d] *= alvo
                        ajustes.append((c, str(d.date()), round(x, 4)))
                        break
                else:
                    continue
                break
        A.loc[s.index, c] = s * fator
    return A, ajustes


def main():
    P, V = carregar()
    A, ajustes = ajustar_desdobramentos(P)
    print("ações:", P.shape[1], "| ajustes de desdobramento/grupamento:", len(ajustes))
    liquida = V.rolling(60, min_periods=40).median().shift(1) >= 1_000_000
    mm50 = A.rolling(50, min_periods=50).mean()
    dist = A / mm50 - 1
    # "Bolsa toda": média da distância de todas as ações líquidas
    mercado = dist.where(liquida).mean(axis=1)
    fut = A.shift(-60) / A - 1  # 60 pregões depois (a ação pode ter deixado de ser negociada: fica sem resultado)
    # Se a ação parou de ser negociada (sumiu da Bolsa), usa o último preço conhecido dentro da janela
    ult = A.ffill(limit=60).shift(-60) / A - 1
    fut = fut.fillna(ult)
    base = liquida & fut.notna() & dist.notna()
    s1 = base & (dist <= -0.15)
    s2 = s1 & (mercado > -0.10).values[:, None]
    s3 = s1 & (mercado <= -0.10).values[:, None]

    def medir(mask, ini, fim):
        m = mask.loc[ini:fim]
        x = fut.loc[ini:fim][m].stack()
        if x.empty: return {"casos": 0}
        return {"casos": int(len(x)), "empresas": int(x.index.get_level_values(1).nunique()),
                "media_pct": round(x.mean() * 100, 1), "mediana_pct": round(x.median() * 100, 1),
                "subiu_pct": round((x > 0).mean() * 100, 0), "desastre_pct": round((x < -0.30).mean() * 100, 1)}

    periodos = {"2016-2019": ("2016", "2019"), "2020-2022": ("2020", "2022"), "2023-2026": ("2023", "2026"), "total": ("2016", "2026")}
    out = {}
    for nome, mask in [("qualquer dia (referência)", base), ("S1: 15%+ abaixo da média", s1),
                       ("S2: queda só da empresa", s2), ("S3: queda junto com a Bolsa", s3)]:
        out[nome] = {p: medir(mask, a, b) for p, (a, b) in periodos.items()}
    # aprovação pelo critério pré-registrado
    ref = out["qualquer dia (referência)"]
    for nome in list(out)[1:]:
        r = out[nome]
        ganhos = sum(1 for p in ["2016-2019", "2020-2022", "2023-2026"]
                     if r[p].get("mediana_pct") is not None and r[p]["mediana_pct"] > ref[p]["mediana_pct"])
        ok = ganhos >= 2 and r["total"]["mediana_pct"] > ref["total"]["mediana_pct"] and \
            r["total"]["desastre_pct"] <= 2 * ref["total"]["desastre_pct"]
        r["aprovado"] = bool(ok)
    # exemplos de "desastres" (para mostrar o risco real)
    x = fut[s1].stack()
    piores = x.sort_values().head(15)
    out["piores_casos_S1"] = [{"acao": c, "data": str(d.date()), "resultado_60d_pct": round(v * 100, 1)} for (d, c), v in piores.items()]
    out["amostra_ajustes"] = ajustes[:30]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open("historico/caiu_muito.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
