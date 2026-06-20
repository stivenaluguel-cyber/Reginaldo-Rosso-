#!/bin/bash
# Coleta COMPLETA (matricula, financiamento, FGTS, 1a/2a praca).
# Precisa do Node instalado. Clique duas vezes.
cd "$(dirname "$0")"
if ! command -v node >/dev/null 2>&1; then
  echo "============================================"
  echo " Falta instalar o Node (so na primeira vez)."
  echo " Baixe em: https://nodejs.org  (botao verde LTS)"
  echo " Instale e rode este arquivo de novo."
  echo "============================================"
  read -p "Pressione Enter para sair..."; exit 1
fi
echo "Coletando imoveis (completo). Aguarde..."
node coletar-completo.js
echo ""
echo "Pronto! Suba imoveis-rs.json, imoveis-sc.json e meta.json no GitHub."
read -p "Pressione Enter para sair..."
