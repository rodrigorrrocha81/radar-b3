"""Extrai do arquivo anual oficial da B3 o fechamento e o volume de TODAS as ações (ON, PN e units), 2016-2026."""
import csv, gzip, io, zipfile, requests

def processar(ano):
    url = f"https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{ano}.ZIP"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=900)
    if r.content[:2] != b"PK":
        print(ano, "não veio ZIP"); return
    z = zipfile.ZipFile(io.BytesIO(r.content)); n = 0
    with gzip.open(f"historico/todas_{ano}.csv.gz", "wt", newline="") as out:
        w = csv.writer(out); w.writerow(["data", "codigo", "especie", "fechamento", "volume"])
        with z.open(z.namelist()[0]) as f:
            for l in io.TextIOWrapper(f, encoding="latin-1"):
                if not l.startswith("01") or l[24:27] != "010" or l[10:12] != "02":  # mercado à vista, lote padrão
                    continue
                esp = l[39:49].strip()
                if not (esp.startswith("ON") or esp.startswith("PN") or esp.startswith("UNT")):
                    continue
                w.writerow([l[2:10], l[12:24].strip(), esp, int(l[108:121]) / 100, int(l[170:188]) / 100]); n += 1
    print(ano, n, "linhas")

if __name__ == "__main__":
    for ano in range(2016, 2027):
        processar(ano)
