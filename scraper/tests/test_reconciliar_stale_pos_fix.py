"""
Testes de scraper/reconciliar_stale_pos_fix.py::_aplicar_exclusao.

Feature de uso manual: permite excluir numero_imovel especificos de uma
rodada (ex: candidatos que uma checagem ao vivo ja confirmou ativos e que
nao devem ser reconciliados) sem precisar de gambiarra na linha de comando
nem tocar no banco.
"""
from datetime import datetime, timezone

import reconciliar_stale_pos_fix as rsf


def _candidato(numero, uf="RS", cidade="PORTO ALEGRE"):
    return (numero, uf, cidade, datetime(2026, 7, 1, tzinfo=timezone.utc), 20)


def test_sem_excluir_ids_retorna_lista_intacta():
    stale = [_candidato("1"), _candidato("2")]
    restante, excluidos = rsf._aplicar_exclusao(stale, set())
    assert restante == stale
    assert excluidos == []


def test_exclui_apenas_os_ids_informados():
    stale = [_candidato("1"), _candidato("2"), _candidato("3")]
    restante, excluidos = rsf._aplicar_exclusao(stale, {"2"})
    assert [c[0] for c in restante] == ["1", "3"]
    assert [c[0] for c in excluidos] == ["2"]


def test_excluir_id_inexistente_na_lista_nao_afeta_nada():
    stale = [_candidato("1"), _candidato("2")]
    restante, excluidos = rsf._aplicar_exclusao(stale, {"999"})
    assert restante == stale
    assert excluidos == []


def test_exclui_multiplos_ids():
    stale = [_candidato("1"), _candidato("2"), _candidato("3"), _candidato("4")]
    restante, excluidos = rsf._aplicar_exclusao(stale, {"1", "3"})
    assert [c[0] for c in restante] == ["2", "4"]
    assert [c[0] for c in excluidos] == ["1", "3"]
