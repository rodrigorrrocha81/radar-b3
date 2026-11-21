"""Monta o histórico de qualidade (lucro de 12 meses e ROE) de cada empresa, na data em que cada balanço
foi ENTREGUE à CVM (para não usar informação que ainda não existia), e as datas de entrega dos balanços."""
import json, sys
import pandas as pd
sys.path.insert(0, ".")
import fundamentos as f


def carregar_anos(itr_anos, dfp_anos):
    cods = [c for c, _ in f.EMPRESAS.values()]
    d = {k: [] for k in ["meta", "DRE", "BPP"]}
    for tipo, anos in [("itr", itr_anos), ("dfp", dfp_anos)]:
        for a in anos:
            z = f._zip(tipo, a)
            if z is None: continue
            m = f._csv(z, None, a, cods); m["TIPO"] = tipo; d["meta"].append(m)
            for parte, k in [("DRE_con", "DRE"), ("BPP_con", "BPP")]:
                x = f._csv(z, parte, a, cods); x["TIPO"] = tipo; d[k].append(x)
    return {k: pd.concat(v, ignore_index=True) for k, v in d.items()}


def historico():
    d = carregar_anos([2022, 2023, 2024, 2025, 2026], [2021, 2022, 2023, 2024, 2025])
    meta, dre, bpp = d["meta"], d["DRE"], d["BPP"]
    linhas, entregas = [], {}
    for ativo, (cd, _) in f.EMPRESAS.items():
        docs = meta[meta.CD_CVM == cd].groupby(["DT_REFER", "TIPO"]).DT_RECEB.min().reset_index()
        entregas[ativo] = sorted(docs.DT_RECEB.unique().tolist())
        for r in docs.itertuples():
            ref = r.DT_REFER
            if r.TIPO == "dfp":
                lucro = f._acumulado(dre[dre.TIPO == "dfp"], cd, ref, "ÚLTIMO", "lucro")
            else:
                ytd = f._acumulado(dre[dre.TIPO == "itr"], cd, ref, "ÚLTIMO", "lucro")
                ytd_ant = f._acumulado(dre[dre.TIPO == "itr"], cd, ref, "PENÚLTIMO", "lucro")
                fy = f._acumulado(dre[dre.TIPO == "dfp"], cd, f"{int(ref[:4]) - 1}-12-31", "ÚLTIMO", "lucro")
                lucro = None if None in (ytd, ytd_ant, fy) else ytd + fy - ytd_ant
            b = bpp[bpp.TIPO == r.TIPO]
            pl = f._conta(b, cd, ref, descricao=r"Patrim[ôo]nio L[íi]quido Atribu[íi]do ao Controlador")
            pl = pl if pl is not None else f._conta(b, cd, ref, descricao=r"^Patrim[ôo]nio L[íi]quido Consolidado")
            roe = (lucro / pl * 100) if (lucro is not None and pl) else None
            linhas.append(dict(ativo=ativo, ref=ref, entregue=r.DT_RECEB, lucro_12m=lucro, roe=roe))
    return pd.DataFrame(linhas).sort_values(["ativo", "entregue"]), entregas


if __name__ == "__main__":
    h, e = historico()
    pd.set_option("display.width", 200)
    print(h.assign(roe=h.roe.round(1), lucro_bi=(h.lucro_12m / 1e9).round(1)).drop(columns="lucro_12m").to_string())
    h.to_csv("historico/qualidade.csv", index=False)
    json.dump(e, open("historico/entregas_balancos.json", "w"), indent=1)
