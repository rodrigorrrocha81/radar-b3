"""Baixa os arquivos ANUAIS oficiais da B3 (COTAHIST_Aaaaa) e guarda só o que interessa:
preço diário das 10 ações e as opções delas que tiveram negócios. Roda no GitHub (a B3 bloqueia outros servidores)."""
import csv, gzip, io, sys, zipfile, requests

ATIVOS = ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "B3SA3", "ABEV3", "WEGE3", "PRIO3", "BOVA11"]
RAIZES = {t[:4]: t for t in ATIVOS}
p = lambda s: int(s) / 100

def processar(ano, com_opcoes):
    url = f"https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{ano}.ZIP"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=600)
    if r.content[:2] != b"PK":
        print(ano, "não veio ZIP:", r.status_code); return
    z = zipfile.ZipFile(io.BytesIO(r.content))
    n = 0
    with gzip.open(f"historico/b3_{ano}.csv.gz", "wt", newline="") as out:
        w = csv.writer(out)
        w.writerow(["data", "tipo", "codigo", "ativo", "abertura", "maxima", "minima", "ultimo",
                    "compra", "venda", "negocios", "volume", "strike", "vencimento"])
        with z.open(z.namelist()[0]) as f:
            for linha in io.TextIOWrapper(f, encoding="latin-1"):
                if not linha.startswith("01"):
                    continue
                cod, merc = linha[12:24].strip(), linha[24:27]
                if merc == "010" and cod in ATIVOS:
                    tipo = "acao"
                elif com_opcoes and merc in ("070", "080") and cod[:4] in RAIZES and int(linha[147:152]) >= 5:
                    tipo = "call" if merc == "070" else "put"
                else:
                    continue
                w.writerow([linha[2:10], tipo, cod, cod if tipo == "acao" else RAIZES[cod[:4]],
                            p(linha[56:69]), p(linha[69:82]), p(linha[82:95]), p(linha[108:121]),
                            p(linha[121:134]), p(linha[134:147]), int(linha[147:152]), int(linha[170:188]) / 100,
                            p(linha[188:201]) if tipo != "acao" else "", linha[202:210] if tipo != "acao" else ""])
                n += 1
    print(ano, n, "linhas")

if __name__ == "__main__":
    processar(2022, com_opcoes=False)   # só ações: para ter médias de 200 dias desde o início de 2023
    for ano in [2023, 2024, 2025, 2026]:
        processar(ano, com_opcoes=True)
