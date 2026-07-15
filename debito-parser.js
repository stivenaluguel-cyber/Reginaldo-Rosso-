// Heuristica compartilhada por imoveis.html e mapa.html: classifica o
// debito de tributos/condominio (client-side, fallback quando o campo vem
// vazio do backend) a partir do texto de descricao do imovel.
//
// Antes, cada uma das 2 paginas tinha sua propria copia inline (colada),
// e uma delas podia divergir silenciosamente da outra sem ninguem notar.
// Agora as 2 carregam este arquivo unico via <script src>.
function _parseTrib(d){if(!d)return null;const sv=d.toLowerCase();const iv=sv.indexOf('tributo');if(iv<0)return null;const sec=sv.substring(iv,Math.min(sv.length,iv+500));if((sec.includes('inferior a 10')||sec.includes('quando o debito for inferior'))&&(sec.includes('superior a 10')||sec.includes('caixa paga integralmente quando')))return'Caixa paga acima de 10%';if(sec.includes('caixa paga integralmente')||sec.includes('caixa paga'))return'Caixa Paga';if(sec.includes('responsabilidade do comprador')||sec.includes('arrematante paga'))return'Arrematante Paga';return null;}
function _parseCond(d){if(!d)return null;const sv=d.toLowerCase();const iv=sv.indexOf('condomin');if(iv<0)return null;const sec=sv.substring(iv,Math.min(sv.length,iv+500));if(sec.includes('ate o limite de 10%')||sec.includes('valor que exceder')||sec.includes('10% em relacao'))return'Caixa paga acima de 10%';if(sec.includes('caixa paga integralmente')||sec.includes('caixa paga'))return'Caixa Paga';if(sec.includes('responsabilidade do comprador')||sec.includes('arrematante paga'))return'Arrematante Paga';return null;}

// So exporta quando require()ado por um teste Node (mesmo padrao de
// gerar-imoveis.js) - `typeof module` e "undefined" no navegador, entao
// esta linha nao tem nenhum efeito no carregamento via <script src>.
if (typeof module !== "undefined") module.exports = { _parseTrib, _parseCond };
