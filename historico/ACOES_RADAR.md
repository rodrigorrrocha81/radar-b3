# Carteira de ações do Radar: regras definidas ANTES do teste (pré-registro)

Salvo no GitHub antes de rodar o teste. Mudanças posteriores ficam registradas no histórico.

## Objetivo
Escolher, a cada 3 meses, 10 ações de empresas **boas** (dão lucro e bom retorno) e **baratas** (preço baixo em relação ao lucro),
e verificar se essa carteira teria rendido mais do que (1) comprar o BOVA11 e esperar e (2) deixar o dinheiro no CDI/Tesouro Selic.

## Universo
Cerca de 45 empresas grandes e conhecidas da B3 (lista fixa no código), sem "units".
**Limitação conhecida:** a lista foi feita hoje, só com empresas que existem hoje. Isso favorece o teste,
porque empresas que faliram ou encolheram ficaram de fora ("viés de sobrevivência").

## Regras
1. Datas de troca da carteira: primeiro pregão a partir de 1º de abril, 16 de maio, 16 de agosto e 16 de novembro
   (logo depois dos prazos legais de entrega dos balanços à CVM).
2. Só entram empresas com **lucro dos últimos 12 meses positivo** e **ROE acima de 10% ao ano**,
   usando apenas balanços já entregues à CVM na data.
3. Nota de cada empresa = posição no ranking de ROE (maior é melhor) + posição no ranking de "lucro sobre preço"
   (o inverso do P/L; maior é melhor). As 10 melhores notas entram, com o mesmo valor em cada uma.
4. No máximo 3 empresas do mesmo setor (setor do cadastro da CVM).
5. Retorno inclui dividendos (preço ajustado). Custo de 0,05% a cada compra ou venda.

## Como avaliar
- Período: abril de 2018 até hoje, dividido em 3 partes: 2018-2020, 2021-2023 e 2024-2026.
- **Aprovada** se render mais que o BOVA11 em pelo menos 2 das 3 partes **e** no período todo.
- Também mostra a pior queda do caminho (para saber o "susto" que seria preciso aguentar).
