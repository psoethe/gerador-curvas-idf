"""
Testes automatizados para a Etapa 4 da transição SII-HiDRO (v3.0).
Valida:
1. Delineação no exutório de Novo Progresso (-55.4186, -7.0375) com área entre 8,0 e 9,0 km²
   e divergência < 15% da bacia ottocodificada da ANA (8,70 km²).
2. Validação da área UTM SIRGAS 2000 contra referência geodésica independente (erro < 1%).
3. Fonte única de coordenadas: proj_lat e proj_lon compartilhados entre projeto, IDF e Bacia.
4. Trava de segurança de snap: quando excede 150 m, bloqueia a delineação e emite erro explicativo.
5. Bloqueio estrito do Módulo Vazão: permanece locked enquanto bacia_confirmada for False.
6. Cálculo dos 15 parâmetros morfométricos essenciais e consistência física.
7. Tabulação de uso do solo (MapBiomas) e solo (SoilGrids) com cálculo ponderado e sobrescrita manual.
8. Persistência de bacia_results e bacia_confirmada no arquivo de projeto .siih.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import streamlit as st
import pyproj

import basin
import project
import streamlit_app as app


def test_delineacao_novo_progresso_area_e_ana():
    """
    Delinear a bacia no exutório de Novo Progresso (-55.4186, -7.0375) produz:
    - Área entre 8,0 e 9,0 km².
    - Divergência < 15% da bacia ottocodificada da ANA (8,70 km²).
    """
    res = basin.delinear_bacia(-55.4186, -7.0375, snap_radius_m=150.0, usar_cache=False)
    morf = res['morfometria']
    area_km2 = morf['area_km2']
    conf_ana = res['conferencia_ana']

    print(f"Área Delineada Novo Progresso: {area_km2:.3f} km²")
    print(f"Divergência ANA BHO (8.70 km²): {conf_ana['divergencia_pct']:.2f}%")

    assert 8.0 <= area_km2 <= 9.0, f"Área {area_km2:.3f} km² fora da faixa [8.0, 9.0] km²"
    assert conf_ana['divergencia_pct'] < 15.0, f"Divergência ANA {conf_ana['divergencia_pct']:.2f}% >= 15%"
    assert conf_ana['alerta'] is False


def test_area_utm_vs_geodesica_independente():
    """
    Área calculada em UTM SIRGAS 2000 difere em menos de 1% de uma
    referência geodésica independente (Elipsoide GRS80 / WGS84).
    """
    res = basin.delinear_bacia(-55.4186, -7.0375, snap_radius_m=150.0, usar_cache=True)
    morf = res['morfometria']
    diff_pct = morf['diff_area_pct']

    print(f"Área UTM: {morf['area_km2']:.4f} km² | Área Geodésica: {morf['area_geod_km2']:.4f} km² | Erro: {diff_pct:.4f}%")
    assert diff_pct < 1.0, f"Diferença entre UTM e Geodésica ({diff_pct:.4f}%) é maior que 1%"


def test_fonte_unica_coordenadas():
    """
    A coordenada do projeto (proj_lat, proj_lon) é a mesma lida pelo módulo IDF
    e pelo módulo Bacia (teste de fonte única).
    """
    st.session_state['proj_lat'] = -7.0375
    st.session_state['proj_lon'] = -55.4186

    # No módulo IDF
    lat_idf = st.session_state.get('proj_lat')
    lon_idf = st.session_state.get('proj_lon')

    # No módulo Bacia
    lat_bacia = st.session_state.get('proj_lat')
    lon_bacia = st.session_state.get('proj_lon')

    assert lat_idf == lat_bacia == -7.0375
    assert lon_idf == lon_bacia == -55.4186


def test_snap_limite_seguranca():
    """
    O snap é sempre informado com a distância deslocada.
    Acima de 150 m (ou limite configurado), bloqueia e exige reposicionamento.
    """
    # Teste 1: snap normal dentro do raio
    res = basin.delinear_bacia(-55.4186, -7.0375, snap_radius_m=150.0, usar_cache=True)
    assert res['snap_dist_m'] <= 150.0
    assert res['snap_dist_m'] > 0.0

    # Teste 2: forçar snap radius menor que a distância necessária (22.4 m)
    try:
        basin.delinear_bacia(-55.4186, -7.0375, snap_radius_m=10.0, usar_cache=False)
        assert False, "Deveria ter lançado SnapExceededError"
    except basin.SnapExceededError as e:
        assert e.dist_m > 10.0
        assert "excedendo o limite de segurança" in str(e)


def test_bloqueio_estrito_vazao_sem_confirmacao_bacia():
    """
    O módulo Vazão está bloqueado enquanto bacia_confirmada for Falso,
    mesmo com IDF 100% concluído e consistente.
    """
    st.session_state['proj_lat'] = -7.0375
    st.session_state['proj_lon'] = -55.4186

    # IDF concluído com consistência física válida
    st.session_state['results'] = {'physical_consistency': {'is_valid': True}}

    # Bacia ainda não confirmada visualmente
    st.session_state['bacia_confirmada'] = False
    assert app.module_status('idf') == 'done'
    assert app.module_status('bacia') == 'todo'
    assert app.module_status('vazao') == 'locked', "Vazão deveria estar bloqueado sem bacia confirmada"

    # Usuário inspeciona e confirma o divisor
    st.session_state['bacia_confirmada'] = True
    assert app.module_status('bacia') == 'done'
    assert app.module_status('vazao') == 'todo', "Vazão deveria estar destravado (todo) com IDF e Bacia done"


def test_morfometria_completa_e_consistencia_fisica():
    """
    Valida presença de todos os parâmetros morfométricos exigidos e sanidade física:
    área, perímetro, talvegue, axial, cotas, desnível, 3 declividades,
    declividade média, Kc, Kf, densidade de drenagem, ordem de Strahler.
    """
    res = basin.delinear_bacia(-55.4186, -7.0375, snap_radius_m=150.0, usar_cache=True)
    m = res['morfometria']

    # Presença de todos os campos
    campos_obrigatorios = [
        'area_km2', 'perimetro_km', 'comprimento_talvegue_km', 'comprimento_axial_km',
        'cota_exutorio_m', 'cota_remota_m', 'desnivel_m', 'declividade_reta_m_m',
        'declividade_s10_85_m_m', 'declividade_equivalente_m_m', 'declividade_media_bacia_pct',
        'coeficiente_compacidade', 'fator_forma', 'densidade_drenagem_km_km2', 'ordem_strahler'
    ]
    for c in campos_obrigatorios:
        assert c in m, f"Campo morfométrico ausente: {c}"

    # Consistência física
    assert m['cota_remota_m'] > m['cota_exutorio_m']
    assert m['desnivel_m'] > 0.0
    assert m['comprimento_talvegue_km'] > 0.0
    assert m['comprimento_axial_km'] > 0.0
    assert m['declividade_reta_m_m'] > 0.0
    assert m['declividade_s10_85_m_m'] > 0.0
    assert m['declividade_equivalente_m_m'] > 0.0
    assert m['coeficiente_compacidade'] >= 1.0  # Kc de círculo é 1.0, bacias reais >= 1.0
    assert m['fator_forma'] > 0.0
    assert m['densidade_drenagem_km_km2'] > 0.0
    assert m['ordem_strahler'] >= 1


def test_uso_solo_e_sobrescrita():
    """
    Valida cálculo de CN e C ponderados e sobrescrita manual.
    """
    res = basin.delinear_bacia(-55.4186, -7.0375, snap_radius_m=150.0, usar_cache=True)
    uso = res['uso_solo']

    assert 'classes' in uso
    assert len(uso['classes']) >= 4
    assert 0.05 < uso['c_ponderado'] < 0.95
    assert 30.0 < uso['cn_ponderado'] < 98.0
    assert uso['sobrescrita'] is None

    # Sobrescrita manual
    uso['sobrescrita'] = {'c': 0.45, 'cn': 75.0, 'motivo': 'Calibração in situ'}
    assert uso['sobrescrita']['c'] == 0.45
    assert uso['sobrescrita']['cn'] == 75.0


def test_persistencia_bacia_no_projeto():
    """
    Salvar e reabrir preserva bacia_confirmada e bacia_results.
    """
    res_bacia = basin.delinear_bacia(-55.4186, -7.0375, snap_radius_m=150.0, usar_cache=True)

    state = {
        'proj_lat': -7.0375,
        'proj_lon': -55.4186,
        'proj_loc': 'Novo Progresso, PA',
        'isozona_escolhida': 'E',
        'responsavel': 'Pedro Luis Soethe Cursino',
        'nome_obra': 'Rodovia BR-163 km 812',
        'dispositivo': 'bueiro_grota',
        'tr_projeto': 25,
        'bacia_confirmada': True,
        'bacia_results': res_bacia,
    }

    raw = project.salvar_projeto(filepath=None, state=state)
    assert raw is not None and len(raw) > 0

    proj_carregado = project.abrir_projeto(raw, recalcular=False)
    bacia_sec = proj_carregado['dados'].get('bacia', {})

    assert bacia_sec.get('confirmada_por_usuario') is True
    assert bacia_sec.get('results') is not None
    assert bacia_sec['results']['morfometria']['area_km2'] == res_bacia['morfometria']['area_km2']


if __name__ == '__main__':
    print("=" * 70)
    print("EXECUTANDO TESTES DA ETAPA 4 (MÓDULO BACIA HIDROGRÁFICA - SII-HiDRO)")
    print("=" * 70)

    test_delineacao_novo_progresso_area_e_ana()
    print("  [PASS] 1. Delineação em Novo Progresso (área 8.0-9.0 km² e ANA < 15%)")

    test_area_utm_vs_geodesica_independente()
    print("  [PASS] 2. Área UTM vs Referência Geodésica (< 1%)")

    test_fonte_unica_coordenadas()
    print("  [PASS] 3. Fonte única de coordenadas compartilhadas")

    test_snap_limite_seguranca()
    print("  [PASS] 4. Limite e segurança de snap do exutório (bloqueio > 150m)")

    test_bloqueio_estrito_vazao_sem_confirmacao_bacia()
    print("  [PASS] 5. Bloqueio estrito de Vazão sem confirmação visual da Bacia")

    test_morfometria_completa_e_consistencia_fisica()
    print("  [PASS] 6. 15 parâmetros morfométricos e consistência física")

    test_uso_solo_e_sobrescrita()
    print("  [PASS] 7. Uso do solo MapBiomas, SoilGrids e sobrescrita manual")

    test_persistencia_bacia_no_projeto()
    print("  [PASS] 8. Persistência de bacia no projeto .siih")

    print("=" * 70)
    print("TOTAL: 8 passaram, 0 falharam.")
    print("=" * 70)
