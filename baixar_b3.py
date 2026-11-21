"""Baixa o arquivo diário oficial da B3 (COTAHIST) do último pregão disponível."""
import datetime as dt, io, pathlib, zipfile, requests

PASTA = pathlib.Path("b3_cache")

def baixar_dia(dia):
    url = f"https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{dia:%d%m%Y}.ZIP"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
    if r.status_code != 200 or r.content[:2] != b"PK":
        return None
    z = zipfile.ZipFile(io.BytesIO(r.content))
    return z.read(z.namelist()[0]).decode("latin-1")

def ultimo_pregao(max_dias=10):
    """Devolve (data, texto) do pregão mais recente encontrado."""
    hoje = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).date()
    for i in range(0, max_dias):
        d = hoje - dt.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        txt = baixar_dia(d)
        if txt:
            PASTA.mkdir(exist_ok=True)
            (PASTA / f"COTAHIST_{d:%Y%m%d}.TXT").write_text(txt, encoding="latin-1")
            return d, txt
    raise RuntimeError("Nenhum arquivo da B3 encontrado nos últimos dias")

if __name__ == "__main__":
    d, txt = ultimo_pregao()
    print(d, len(txt.splitlines()), "linhas")
