# Método Radar: regras definidas ANTES do teste (pré-registro)

Este arquivo foi salvo no GitHub **antes** de rodar o teste, para provar que as regras
não foram ajustadas depois de ver o resultado. Qualquer mudança posterior fica registrada no histórico.

## Lições dos testes anteriores que orientam as regras
1. O custo de negociar (diferença entre o preço de compra e o de venda das opções) transformou empates em prejuízo.
   Por isso, as regras abaixo **só usam opções com essa diferença pequena**.
2. Os sinais só de gráfico não acertaram a direção. Por isso, as regras usam também **fundamentos** (empresa lucrativa),
   **eventos** (sem balanço no meio da operação) e **preço da opção comparado ao quanto a ação realmente oscila**.

## Filtro comum de qualidade (fundamentos, dados da CVM, só com o que já estava publicado na data)
- Lucro dos últimos 12 meses positivo **e** retorno sobre o patrimônio (ROE) acima de 12% ao ano.
- Sem balanço previsto entre a entrada e o vencimento da opção (usa a data real de entrega à CVM).
- BOVA11 não tem balanço próprio: entra sem esse filtro.

## H1: Comprar call barata em empresa boa que está subindo
- Preço > média de 50 dias > média de 200 dias.
- A opção está "barata": a volatilidade implícita é no máximo **0,9x** a oscilação real dos últimos 20 pregões.
- Opção: vencimento entre 25 e 60 dias úteis, delta entre 0,40 e 0,60, diferença compra/venda até **10%**, 20 negócios ou mais.
- Saída: quando valer **2x** o que foi pago, ou faltando 3 dias úteis para o vencimento.

## H2: Vender trava de put quando o seguro está caro, em empresa boa
- Preço > média de 200 dias.
- A put vendida tem volatilidade implícita de pelo menos **1,3x** a oscilação real dos últimos 20 pregões **e** acima da oscilação de 1 ano.
- Vende put com delta entre 0,20 e 0,35 e compra put de proteção com delta entre 0,05 e 0,15, mesmo vencimento (20 a 45 dias úteis).
- Diferença compra/venda até **15%** nas duas pernas, 10 negócios ou mais.
- Saída: com 50% do lucro máximo, ou faltando 3 dias úteis para o vencimento.

## H3: Vender trava de put depois de um susto do mercado, em empresa boa
- O BOVA11 caiu **7% ou mais** nos últimos 10 pregões.
- Mesma montagem e saída da H2, sem exigir a regra de volatilidade (o susto já encarece o seguro).

## Como avaliar
- 2023-2024 = desenvolvimento; 2025-2026 = confirmação. Uma hipótese só é aprovada se ganhar **nos dois períodos**.
- Preços conservadores: compra pela oferta de venda, vende pela oferta de compra, entrada no pregão seguinte ao sinal.
- R$ 100 por operação (na compra, o valor pago; na venda, a perda máxima possível), no máximo 5 abertas por hipótese.
- Não testável com dados do passado: notícias (não há arquivo histórico organizado). Fica para a carteira simulada.

## Capital mínimo
Só será calculado para hipóteses aprovadas. Considera lotes de 100 opções, taxas da B3, imposto de 15% sobre o lucro
e a comparação com o Tesouro Selic (o "lucro mínimo" é render mais do que deixar o dinheiro parado nele).
