"""Junta os dados calculados com o modelo e grava o painel em docs/index.html."""
import json, pathlib
dados = json.load(open("dados.json"))
corpo = open("painel_modelo.html").read().replace("/*DADOS*/null", json.dumps(dados, ensure_ascii=False))
html = ('<!doctype html>\n<html lang="pt-BR">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<style>body{margin:0}</style>\n</head>\n<body>\n' + corpo + '\n</body>\n</html>\n')
pathlib.Path("docs").mkdir(exist_ok=True)
open("docs/index.html", "w").write(html)
print("docs/index.html gerado")
