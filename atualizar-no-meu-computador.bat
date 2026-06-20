@echo off
cd /d "%~dp0"
set "UA=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
set "BASE=https://venda-imoveis.caixa.gov.br"
echo Baixando imoveis da Caixa (RS e SC)...
echo Aquecendo a sessao...
curl -sL -c cookies.txt -A "%UA%" "%BASE%/sistema/busca-imovel.asp" -o NUL
timeout /t 3 >NUL
for %%U in (RS SC) do (
  curl -sL -b cookies.txt -A "%UA%" -e "%BASE%/sistema/busca-imovel.asp" --max-time 180 "%BASE%/listaweb/Lista_imoveis_%%U.csv" -o "raw-%%U.csv"
  for %%S in ("raw-%%U.csv") do echo   %%U baixado: %%~zS bytes
)
del cookies.txt >NUL 2>&1
echo.
echo Concluido! Suba raw-RS.csv e raw-SC.csv no GitHub.
pause
