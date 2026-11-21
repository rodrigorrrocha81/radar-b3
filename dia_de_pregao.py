"""Responde se hoje (horário de Brasília) é dia de pregão na B3.
Feriados conferir anualmente no calendário oficial da B3."""
import datetime as dt, os, sys
FERIADOS = {
 # 2026
 "2026-01-01","2026-02-16","2026-02-17","2026-04-03","2026-04-21","2026-05-01","2026-06-04",
 "2026-09-07","2026-10-12","2026-11-02","2026-11-20","2026-12-24","2026-12-25","2026-12-31",
 # 2027
 "2027-01-01","2027-02-08","2027-02-09","2027-03-26","2027-04-21","2027-05-27",
 "2027-09-07","2027-10-12","2027-11-02","2027-11-15","2027-12-24","2027-12-31",
}
if __name__ == "__main__":
    hoje = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).date()
    pregao = hoje.weekday() < 5 and str(hoje) not in FERIADOS
    if hoje.year > 2027: print("AVISO: atualizar lista de feriados", file=sys.stderr)
    print(f"{hoje}: {'dia de pregão' if pregao else 'sem pregão'}")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
        f.write(f"pregao={'sim' if pregao else 'nao'}\n")
