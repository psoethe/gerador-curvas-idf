"""
Suíte de Testes — Etapa 5: Módulo Vazão (discharge.py)
Validação das 6 fórmulas de tempo de concentração, domínios de calibração,
limiar de área normativo IPR-724 (1,00 km²), modelo HU SCS com blocos alternados
e persistência do estado no projeto .siih.
"""
import sys
import os
import math
import tempfile
from pathlib import Path
import numpy as np

# Garante importação a partir da raiz
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discharge
import project


def test_seis_formulas_tc_e_dominios():
    """
    Verifica se calcular_tempos_concentracao retorna rigorosamente as 6 fórmulas
    com seus domínios de calibração, marcação explícita de fora de domínio
    e estatísticas de dispersão completas.
    """
    # Caso 1: Microbacia íngreme (A = 0.8 km², L = 1.2 km, dH = 35 m, S = 0.029, S_pct = 5.0%, CN = 75)
    res_micro = discharge.calcular_tempos_concentracao(
        area_km2=0.8,
        comprimento_talvegue_km=1.2,
        desnivel_m=35.0,
        declividade_m_m=0.029,
        declividade_media_pct=5.0,
        cn=75.0,
    )

    formulas_micro = {f['id']: f for f in res_micro['formulas']}
    assert len(formulas_micro) == 6
    assert set(formulas_micro.keys()) == {
        'kirpich', 'giandotti', 'ven_te_chow', 'corps_engineers', 'dnos', 'scs_lag'
    }

    # Kirpich deve estar no domínio para microbacia rural íngreme
    assert formulas_micro['kirpich']['no_dominio'] is True
    assert formulas_micro['kirpich']['aviso'] == ""

    # Giandotti deve estar FORA do domínio (requer A >= 5 km²)
    assert formulas_micro['giandotti']['no_dominio'] is False
    assert "5 km²" in formulas_micro['giandotti']['aviso']

    # Estatísticas de dispersão
    stats = res_micro['estatisticas']
    assert stats['minimo_min'] <= stats['mediana_min'] <= stats['maximo_min']
    assert stats['dispersao_pct'] > 0.0

    # Caso 2: Bacia média Novo Progresso (A = 8.855 km², L = 3.561 km, dH = 58.2 m, S = 0.0163, CN = 60.5)
    res_bacia = discharge.calcular_tempos_concentracao(
        area_km2=8.855,
        comprimento_talvegue_km=3.561,
        desnivel_m=58.2,
        declividade_m_m=0.0163,
        declividade_media_pct=3.8,
        cn=60.5,
    )
    formulas_bacia = {f['id']: f for f in res_bacia['formulas']}
    # Para A = 8.855 km², Giandotti e DNOS estão no domínio
    assert formulas_bacia['giandotti']['no_dominio'] is True
    assert formulas_bacia['dnos']['no_dominio'] is True
    # Kirpich está fora de domínio (A > 4 km²)
    assert formulas_bacia['kirpich']['no_dominio'] is False


def test_limiar_normativo_ipr724():
    """
    Valida a constante única LIMIAR_AREA_RACIONAL_IPR724_KM2 == 1.00 (100 ha)
    e o comportamento do bloqueio com justificativa pedagógica do DNIT IPR-724.
    """
    assert hasattr(discharge, 'LIMIAR_AREA_RACIONAL_IPR724_KM2')
    assert discharge.LIMIAR_AREA_RACIONAL_IPR724_KM2 == 1.00

    # Microbacia (A = 0.65 km² <= 1.00 km²): Racional elegível e desbloqueado
    racional_micro = discharge.calcular_metodo_racional(
        area_km2=0.65,
        c_runoff=0.40,
        i_mm_h=95.0,
    )
    assert racional_micro['bloqueado'] is False
    assert racional_micro['motivo_bloqueio'] == ""
    # Q = (0.40 * 95.0 * 0.65) / 3.6 = 6.86 m³/s
    assert math.isclose(racional_micro['q_pico_m3s'], 6.86, rel_tol=0.02)

    # Bacia Novo Progresso (A = 8.855 km² > 1.00 km²): Racional BLOQUEADO
    racional_bacia = discharge.calcular_metodo_racional(
        area_km2=8.855,
        c_runoff=0.35,
        i_mm_h=70.0,
    )
    assert racional_bacia['bloqueado'] is True
    assert "IPR-724" in racional_bacia['motivo_bloqueio']
    assert "100 ha" in racional_bacia['motivo_bloqueio']


def test_intensidade_sherman():
    """
    Verifica a avaliação da equação de Sherman i = (A * TR^B) / (t + C)^D.
    """
    params = {'A': 4661.82, 'B': 0.215, 'C': 39.36, 'D': 0.9971}
    i_60_tr25 = discharge.calcular_intensidade_sherman(params, tc_min=60.0, tr_anos=25.0)
    assert i_60_tr25 > 0.0
    # Intensidade decresce com aumento da duração
    i_120_tr25 = discharge.calcular_intensidade_sherman(params, tc_min=120.0, tr_anos=25.0)
    assert i_60_tr25 > i_120_tr25
    # Intensidade cresce com aumento do período de retorno
    i_60_tr100 = discharge.calcular_intensidade_sherman(params, tc_min=60.0, tr_anos=100.0)
    assert i_60_tr100 > i_60_tr25


def test_hidrograma_scs_e_convolucao():
    """
    Testa o modelo completo do Hidrograma Unitário SCS com blocos alternados,
    fator de abatimento espacial (ARF) e convolução temporal.
    """
    params = {'A': 4661.82, 'B': 0.215, 'C': 39.36, 'D': 0.9971}
    res_scs = discharge.calcular_hidrograma_scs(
        area_km2=8.855,
        cn=60.5,
        tc_min=93.2,
        sherman_params=params,
        tr_anos=25.0,
        duracao_h=24.0,
        dt_min=5.0,
    )

    # 1. Coeficiente de abatimento espacial
    assert 0.70 <= res_scs['coef_abatimento_espacial'] <= 1.00

    # 2. Grandezas físicas do hidrograma
    assert res_scs['q_pico_m3s'] > 0.0
    assert res_scs['volume_total_m3'] > 0.0
    assert res_scs['lamina_total_mm'] > res_scs['lamina_efetiva_mm'] > 0.0
    assert res_scs['tempo_pico_min'] > 0.0

    # 3. Conservação de massa aproximada:
    # Volume total escoado ≈ Área * Lâmina Efetiva
    # V_esp = (8.855 * 1e6 m²) * (lamina_efetiva / 1000 m)
    vol_esperado = (8.855 * 1e6) * (res_scs['lamina_efetiva_mm'] / 1000.0)
    vol_calculado = res_scs['volume_total_m3']
    # A convolução truncada a 24h ou término da curva difere menos de 5%
    erro_balanco = abs(vol_calculado - vol_esperado) / vol_esperado
    assert erro_balanco < 0.05, f"Erro de balanço hídrico {erro_balanco*100:.2f}% excede 5%"

    # 4. DataFrame do hidrograma
    df = res_scs['df_hidrograma']
    assert 'Tempo_min' in df.columns
    assert 'Tempo_h' in df.columns
    assert 'Chuva_Total_mm' in df.columns
    assert 'Chuva_Efetiva_mm' in df.columns
    assert 'Vazao_m3s' in df.columns
    assert len(df) == int((24.0 * 60.0) / 5.0)


def test_calcular_vazao_projeto_decisao_normativa():
    """
    Verifica a função integradora de decisão normativa da vazão de projeto:
    - Bacia > 1,00 km²: Bloqueio do Racional e adoção mandatória de SCS.
    - Bacia <= 1,00 km²: Permissão de escolha do Racional.
    """
    params = {'A': 4661.82, 'B': 0.215, 'C': 39.36, 'D': 0.9971}

    # Bacia Novo Progresso (8.855 km²): Racional é forçado a bloquear
    vazao_np = discharge.calcular_vazao_projeto(
        area_km2=8.855,
        c_runoff=0.35,
        cn=60.5,
        tc_adotado_min=93.2,
        formula_tc_adotada='scs_lag',
        sherman_params=params,
        tr_anos=25.0,
        metodo_preferido='racional',  # Projetista tentou o Racional
    )
    # Deve rejeitar a preferência e aplicar SCS devido ao IPR-724
    assert vazao_np['metodo_adotado'] == 'scs'
    assert vazao_np['bloqueio_racional'] is True
    assert vazao_np['q_projeto_m3s'] == vazao_np['scs']['q_pico_m3s']

    # Microbacia (0.80 km²): Racional é aceito
    vazao_micro = discharge.calcular_vazao_projeto(
        area_km2=0.80,
        c_runoff=0.40,
        cn=75.0,
        tc_adotado_min=25.0,
        formula_tc_adotada='kirpich',
        sherman_params=params,
        tr_anos=25.0,
        metodo_preferido='racional',
    )
    assert vazao_micro['metodo_adotado'] == 'racional'
    assert vazao_micro['bloqueio_racional'] is False
    assert vazao_micro['q_projeto_m3s'] == vazao_micro['racional']['q_pico_m3s']


def test_project_persistence_vazao_roundtrip():
    """
    Testa se os dados e decisões do Módulo Vazão são serializados e restaurados
    fielmente no arquivo .siih.
    """
    import streamlit as st

    params = {'A': 4661.82, 'B': 0.215, 'C': 39.36, 'D': 0.9971}
    vazao_calc = discharge.calcular_vazao_projeto(
        area_km2=8.855,
        c_runoff=0.35,
        cn=60.5,
        tc_adotado_min=93.2,
        formula_tc_adotada='scs_lag',
        sherman_params=params,
        tr_anos=25.0,
    )

    # Preenche o session_state simulando a sessão ativa
    st.session_state['responsavel'] = 'Pedro Luis Soethe Cursino'
    st.session_state['nome_obra'] = 'BR-163 km 812'
    st.session_state['dispositivo'] = 'bueiro_grota'
    st.session_state['proj_tr'] = 25
    st.session_state['proj_lat'] = -7.0375
    st.session_state['proj_lon'] = -55.4186
    st.session_state['proj_loc'] = 'Novo Progresso, PA'
    st.session_state['isozona_escolhida'] = 'F'
    st.session_state['isozona_origem'] = 'automatica'
    st.session_state['data_source_method'] = 'api'
    st.session_state['api_source'] = 'hist'
    st.session_state['selection_mode'] = 'idw'
    st.session_state['idw_p'] = 2.0
    st.session_state['estacoes_selecionadas'] = []
    st.session_state['series_brutas'] = {}
    st.session_state['results'] = {
        'mu': 96.3, 'sigma': 38.7, 'n_samples': 26,
        'sherman_params': params,
        'isozona': 'F',
        'isozona_origem': 'automatica',
        'physical_consistency': {'is_valid': True},
    }
    st.session_state['bacia_confirmada'] = True
    st.session_state['bacia_results'] = {'parametros': {'area_km2': 8.855}}

    # Atribui chaves do Módulo Vazão
    st.session_state['q_projeto_m3s'] = vazao_calc['q_projeto_m3s']
    st.session_state['vazao_results'] = vazao_calc
    st.session_state['tc_adotado_min'] = 93.2
    st.session_state['formula_tc_adotada'] = 'scs_lag'
    st.session_state['justificativa_tc'] = 'Bacia rural de 8.8 km² com declividade suave, adequada para SCS Lag.'
    st.session_state['metodo_adotado'] = 'scs'

    with tempfile.NamedTemporaryFile(suffix='.siih', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # Salva o projeto
        project.salvar_projeto(tmp_path)

        # Limpa o session_state
        st.session_state['q_projeto_m3s'] = None
        st.session_state['tc_adotado_min'] = None
        st.session_state['formula_tc_adotada'] = None

        # Abre o projeto
        aberto = project.abrir_projeto(tmp_path)
        project.carregar_projeto_no_session_state(aberto)

        # Verifica restauração
        assert st.session_state['q_projeto_m3s'] == vazao_calc['q_projeto_m3s']
        assert st.session_state['tc_adotado_min'] == 93.2
        assert st.session_state['formula_tc_adotada'] == 'scs_lag'
        assert st.session_state['metodo_adotado'] == 'scs'
    finally:
        Path(tmp_path).unlink(missing_ok=True)


if __name__ == '__main__':
    print("=" * 70)
    print("EXECUTANDO TESTES DA ETAPA 5 (MÓDULO VAZÃO - SII-HiDRO)")
    print("=" * 70)
    tests = [
        ("1. Seis fórmulas de tc e análise de domínio", test_seis_formulas_tc_e_dominios),
        ("2. Limiar normativo DNIT IPR-724 (1,00 km² / 100 ha)", test_limiar_normativo_ipr724),
        ("3. Equação de intensidade de chuva (Sherman)", test_intensidade_sherman),
        ("4. Modelo Hidrograma Unitário SCS e convolução", test_hidrograma_scs_e_convolucao),
        ("5. Decisão normativa de método de vazão de projeto", test_calcular_vazao_projeto_decisao_normativa),
        ("6. Persistência e restauração do Módulo Vazão no .siih", test_project_persistence_vazao_roundtrip),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("=" * 70)
    print(f"TOTAL: {passed} passaram, {failed} falharam.")
    print("=" * 70)
    if failed > 0:
        sys.exit(1)
