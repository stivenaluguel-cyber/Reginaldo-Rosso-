#!/bin/bash
# ============================================================
#  Atualizar imoveis Caixa - rode no SEU Mac (IP brasileiro)
#  Baixa as listas reais da Caixa (RS e SC) e salva raw-RS.csv
#  e raw-SC.csv. Depois suba esses 2 arquivos no GitHub.
# ============================================================
cd "$(dirname "$0")"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
BASE="https://venda-imoveis.caixa.gov.br"

echo "============================================"
echo " Baixando imoveis da Caixa (RS e SC)"
echo "============================================"
echo ""
echo "Aquecendo a sessao..."
curl -sL -c cookies.txt -A "$UA" --connect-timeout 30 "$BASE/sistema/busca-imovel.asp" -o /dev/null
sleep 3

for UF in RS SC; do
  OK=0
  for TRY in 1 2 3 4; do
    curl -sL -b cookies.txt -A "$UA" -e "$BASE/sistema/busca-imovel.asp" \
      --connect-timeout 30 --max-time 180 \
      "$BASE/listaweb/Lista_imoveis_${UF}.csv" -o "raw-${UF}.csv"
    SZ=$(wc -c < "raw-${UF}.csv" 2>/dev/null | tr -d ' ')
    [ -z "$SZ" ] && SZ=0
    echo "  $UF tentativa $TRY -> $SZ bytes"
    if [ "$SZ" -gt 5000 ]; then OK=1; break; fi
    sleep 5
  done
  if [ "$OK" = "1" ]; then echo "  $UF: OK!"; else echo "  $UF: nao baixou - tente de novo em 1 minuto."; rm -f "raw-${UF}.csv"; fi
  echo ""
  sleep 4
done
rm -f cookies.txt

echo "============================================"
echo " Concluido!"
echo " Suba raw-RS.csv e raw-SC.csv no GitHub."
echo "============================================"
echo ""
read -p "Pressione Enter para sair..."
