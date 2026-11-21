"""Teste: a B3 libera o arquivo diário de cotações (com opções) quando o pedido vem do GitHub?"""
import datetime as dt, io, sys, zipfile, requests

def tentar(dia):
    url = f"https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{dia:%d%m%Y}.ZIP"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    print(f"{dia:%d/%m/%Y}: HTTP {r.status_code}, {len(r.content)} bytes, tipo {r.headers.get('content-type')}")
    if r.content[:2] != b"PK":
        trecho = r.text[:300].replace("\n", " ")
        print("   não é ZIP. Início da resposta:", trecho[:200])
        return False
    z = zipfile.ZipFile(io.BytesIO(r.content))
    linhas = z.read(z.namelist()[0]).decode("latin-1").splitlines()
    calls = [l for l in linhas if l[24:27] == "070"]
    puts = [l for l in linhas if l[24:27] == "080"]
    print(f"   ZIP OK: {len(linhas)} linhas, {len(calls)} calls, {len(puts)} puts")
    for l in [l for l in calls if l[39:51].strip() == "PETROBRAS"][:3]:
        print("   ex. call PETR:", l[12:24].strip(), "strike", int(l[188:201]) / 100, "venc", l[202:210], "último", int(l[108:121]) / 100)
    return True

hoje = dt.date.today()
for i in range(1, 8):
    d = hoje - dt.timedelta(days=i)
    if d.weekday() < 5 and tentar(d):
        print("RESULTADO: B3 LIBEROU o download a partir do GitHub."); sys.exit(0)
print("RESULTADO: B3 BLOQUEOU ou não havia arquivo."); sys.exit(1)
