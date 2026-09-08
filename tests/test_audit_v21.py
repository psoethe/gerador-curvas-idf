"""
Suíte de testes automatizada para as correções da revisão v2.1 do SII·IDF.
Cobre especificamente os 12 defeitos auditados:
- P0-1: Coluna de duração preservada em idf_df e disagg_df via reset_index e exportação CSV
- P0-2: Status de sucesso e chave is_valid em verificar_consistencia_fisica_idf
- P0-3: Formatação amigável (chave msg) em violacoes_tempo e violacoes_freq
- P0-4: Avaliação de violacoes_param contra SHERMAN_TYPICAL_RANGES
- P0-5: Validação das métricas R², RMSE, erro celular máximo e médio em fit_sherman
- P1-6: Alerta de co-localização / arranjo degenerado em IDW quando N_eff < 2.0 (Novo Progresso)
- P1-7: Default excluir_incompletos=True em analisar_qualidade_serie e run_full_analysis
- P1-8: Classificação de pixels pretos/grade como GRID (nunca C) e retorno FALLBACK com votação
- P2-9: Função _verificar_toque_bound sem bug de precedência ternária
- P2-10: Cobertura anual calculada sobre dias reais do ano civil (bissexto 366 vs comum 365)
- P2-11: Texto de plausibilidade de CV contextualizado no i18n
- P2-12: Centralização de SHERMAN_OPTIMIZER_BOUNDS e SHERMAN_TYPICAL_RANGES em calculations
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inspect
import io
import calendar
import pandas as pd
import numpy as np

import calculations as calc
from calculations import (
    compute_idf,
    disaggregate_rainfall,
    gumbel_analysis,
    fit_sherman,
    verificar_consistencia_fisica_idf,
    interpolar_series_idw,
    analisar_qualidade_serie,
    detectar_isozona_coordenadas,
    classificar_cor_isozona,
    _verificar_toque_bound,
    run_full_analysis,
    SHERMAN_OPTIMIZER_BOUNDS,
    SHERMAN_TYPICAL_RANGES,
    DURATIONS,
    RETURN_PERIODS,
)
from i18n import t
import report
import report_word
import streamlit_app


def _make_dummy_gumbel(lang='PT'):
    series_df = pd.DataFrame({
        'Ano': list(range(1995, 2020)),
        'Precipitacao': [75.0, 92.0, 84.0, 110.0, 68.0, 95.0, 105.0, 88.0, 115.0, 78.0,
                         85.0, 90.0, 99.0, 120.0, 70.0, 82.0, 101.0, 94.0, 89.0, 108.0,
                         77.0, 93.0, 86.0, 104.0, 91.0],
    })
    gumbel_df, _, _, _ = gumbel_analysis(series_df, lang=lang)
    return gumbel_df


# ── P0-1: Coluna de duração preservada ───────────────────────────────────────
def test_p0_1_duration_column_preserved():
    gumbel_df = _make_dummy_gumbel(lang='PT')
    disagg_df = disaggregate_rainfall(gumbel_df, isozona='B', lang='PT')
    idf_df = compute_idf(disagg_df, lang='PT')

    # Na interface, reset_index é chamado antes de exibir e exportar
    df_disagg_disp = disagg_df.reset_index()
    df_idf_disp = idf_df.reset_index()

    dur_col = t('col_duracao', 'PT')
    assert dur_col in df_disagg_disp.columns, "Coluna de duração ausente em disagg_df.reset_index()"
    assert dur_col in df_idf_disp.columns, "Coluna de duração ausente em idf_df.reset_index()"

    # Testa exportação CSV com index=False
    csv_bytes = df_idf_disp.to_csv(index=False).encode('utf-8')
    csv_str = csv_bytes.decode('utf-8')
    first_line = csv_str.splitlines()[0]
    assert dur_col in first_line, "Cabeçalho do CSV de curvas IDF não contém a coluna de duração"

    df_read = pd.read_csv(io.StringIO(csv_str))
    assert dur_col in df_read.columns
    assert len(df_read) == len(DURATIONS)
    assert list(df_read[dur_col]) == DURATIONS


# ── P0-2: Status de consistência física reportado corretamente ────────────────
def test_p0_2_physical_consistency_status_ok():
    # Uma matriz consistente (avaliada pela equação clássica de Sherman com parâmetros típicos)
    # deve satisfazer monotonicidade temporal e de frequência, retornando is_valid=True e status='OK'
    A, B, C, D = 1500.0, 0.20, 15.0, 0.80
    data = {}
    for tr in RETURN_PERIODS:
        col = f"TR={tr} anos"
        data[col] = [(A * (tr ** B)) / ((dur + C) ** D) for dur in DURATIONS]
    idf_consistente = pd.DataFrame(data, index=DURATIONS)

    sherman = {
        'A': A, 'B': B, 'C': C, 'D': D,
        'bounds_touched': [],
    }

    cons = verificar_consistencia_fisica_idf(idf_consistente, sherman, lang='PT')
    assert 'is_valid' in cons, "Chave is_valid deve estar presente no resultado"
    assert 'status' in cons, "Chave status deve estar presente no resultado"
    assert cons['is_valid'] is True, f"Esperado is_valid=True, obteve mensagens: {cons.get('mensagens')}"
    assert cons['status'] == 'OK', f"Esperado status='OK', obteve {cons.get('status')}"


# ── P0-3 & P0-4: Violações formatadas e violacoes_param ───────────────────────
def test_p0_3_p0_4_violations_message_and_params():
    # Cria idf_df com violação forçada de monotonicidade temporal
    idf_violado = pd.DataFrame(
        data=10.0,
        index=DURATIONS,
        columns=[f"TR={tr} anos" for tr in RETURN_PERIODS],
    )
    # Força t=10 min ter intensidade MAIOR que t=5 min
    idf_violado.loc[10, "TR=2 anos"] = 150.0
    idf_violado.loc[5, "TR=2 anos"] = 100.0

    # Parâmetros com B fora da faixa típica
    sherman_fake = {'A': 1000.0, 'B': 0.05, 'C': 20.0, 'D': 0.8, 'bounds_touched': []}

    cons = verificar_consistencia_fisica_idf(idf_violado, sherman_fake, lang='PT')
    assert cons['is_valid'] is False
    assert cons['status'] == 'VIOLATION'

    # P0-3: violacoes_tempo deve ter estrutura com 'msg' legível
    assert len(cons['violacoes_tempo']) > 0
    v_t = cons['violacoes_tempo'][0]
    assert isinstance(v_t, dict)
    assert 'msg' in v_t
    assert "Violação de monotonicidade temporal" in v_t['msg']

    # P0-4: violacoes_param deve conter parâmetros fora de SHERMAN_TYPICAL_RANGES
    assert len(cons['violacoes_param']) > 0
    v_p = cons['violacoes_param'][0]
    assert isinstance(v_p, dict)
    assert 'msg' in v_p
    assert v_p['param'] == 'B'
    assert "fora da faixa usual" in v_p['msg']


# ── P0-5: Métricas de validação em fit_sherman ─────────────────────────────────
def test_p0_5_sherman_regression_metrics():
    gumbel_df = _make_dummy_gumbel(lang='PT')
    disagg_df = disaggregate_rainfall(gumbel_df, isozona='B', lang='PT')
    idf_df = compute_idf(disagg_df, lang='PT')
    sherman = fit_sherman(idf_df, gumbel_df, lang='PT', modo_ajuste='log')

    assert 'R²' in sherman
    assert 'RMSE' in sherman
    assert 'erro_max_celula' in sherman
    assert 'erro_medio_celula' in sherman
    assert sherman['R²'] > 0.95
    assert sherman['RMSE'] > 0.0
    assert sherman['erro_max_celula'] >= 0.0
    assert sherman['erro_medio_celula'] >= 0.0


# ── P1-6: Alerta de co-localização / arranjo degenerado em IDW ─────────────────
def test_p1_6_idw_colocation_alert_novo_progresso():
    # Caso de regressão de Novo Progresso, PA:
    # 755001: 2.14 km, 755000: 2.83 km, 655000: 28.48 km
    anos = list(range(2000, 2020))
    df_dummy = pd.DataFrame({
        'Ano': anos,
        'Data': ['2000-01-01'] * len(anos),
        'Precipitacao': [100.0] * len(anos),
    })
    series_dict = {
        '755001': df_dummy.copy(),
        '755000': df_dummy.copy(),
        '655000': df_dummy.copy(),
    }
    distancias_km = {
        '755001': 2.14,
        '755000': 2.83,
        '655000': 28.48,
    }

    df_pond, pesos, n_eff, avisos_idw = interpolar_series_idw(
        series_dict, distancias_km, p=2.0, lang='PT'
    )

    # N_eff deve ser < 2.0 devido à concentração extrema de peso nas duas estações mais próximas
    assert n_eff < 2.0, f"Esperado N_eff < 2.0, obteve {n_eff}"

    # Deve conter alerta de co-localização / arranjo degenerado
    coloc_alert = [a for a in avisos_idw if "co-localização" in a or "hiperconcentrado" in a or "N_eff" in a]
    assert len(coloc_alert) > 0, f"Alerta de co-localização não disparou! Avisos: {avisos_idw}"


# ── P1-7: Default excluir_incompletos=True ─────────────────────────────────────
def test_p1_7_excluir_incompletos_defaults():
    sig_qual = inspect.signature(analisar_qualidade_serie)
    assert sig_qual.parameters['excluir_incompletos'].default is True, (
        "analisar_qualidade_serie deve ter excluir_incompletos=True por padrão"
    )

    sig_run = inspect.signature(run_full_analysis)
    assert sig_run.parameters['excluir_incompletos'].default is True, (
        "run_full_analysis deve ter excluir_incompletos=True por padrão"
    )


# ── P1-8: Classificação de cores de isozona e fallback ────────────────────────
def test_p1_8_isozone_grid_color_and_fallback():
    # 1. Pixel preto ou cinza escuro (linha de grade/borda) nunca deve retornar 'C'
    cor_preta = (0, 0, 0)
    assert classificar_cor_isozona(*cor_preta) == 'GRID'

    cor_cinza_escura = (40, 40, 40)
    assert classificar_cor_isozona(*cor_cinza_escura) == 'GRID'

    # 2. Coordenadas fora do Brasil devem retornar 'FALLBACK'
    iso_fora = detectar_isozona_coordenadas(lat=50.0, lon=10.0)
    assert iso_fora == 'FALLBACK'

    # 3. Pixel com baixa saturação (cinza/contorno) nunca deve ser classificado como isozona
    cor_cinza_media = (143, 141, 131)
    assert classificar_cor_isozona(*cor_cinza_media) in ('GRID', 'BACKGROUND')

    # 4. Coordenadas de capitais com isozonas conhecidas e calibradas
    # São Paulo, SP (-23.55, -46.63) -> B
    iso_sp = detectar_isozona_coordenadas(lat=-23.55, lon=-46.63)
    assert iso_sp == 'B', f"São Paulo deveria ser Isozona B, obteve {iso_sp}"

    # Curitiba, PR (-25.43, -49.27) -> D
    iso_curitiba = detectar_isozona_coordenadas(lat=-25.43, lon=-49.27)
    assert iso_curitiba == 'D', f"Curitiba deveria ser Isozona D, obteve {iso_curitiba}"

    # Belém, PA (-1.45, -48.49) -> E
    iso_pa = detectar_isozona_coordenadas(lat=-1.45, lon=-48.49)
    assert iso_pa == 'E', f"Belém deveria ser Isozona E, obteve {iso_pa}"


# ── P2-9: _verificar_toque_bound sem erro de sintaxe ───────────────────────────
def test_p2_9_verificar_toque_bound():
    # Parâmetro longe dos limites
    touched, _ = _verificar_toque_bound(val=20.0, low=3.0, high=70.0, tol=0.005)
    assert touched is False

    # Parâmetro encostando no limite inferior (margem de 0.5%)
    touched, bound_val = _verificar_toque_bound(val=3.01, low=3.0, high=70.0, tol=0.005)
    assert touched is True
    assert bound_val == 3.0

    # Parâmetro encostando no limite superior
    touched, bound_val = _verificar_toque_bound(val=69.8, low=3.0, high=70.0, tol=0.005)
    assert touched is True
    assert bound_val == 70.0

    # Teste de robustez com low <= 0
    touched, bound_val = _verificar_toque_bound(val=0.001, low=0.0, high=1.0, tol=0.005)
    assert touched is True
    assert bound_val == 0.0


# ── P2-10: Cobertura de dias civis reais (bissexto vs comum) ──────────────────
def test_p2_10_leap_year_days_coverage():
    # Ano 2024 é bissexto (366 dias), 2023 é comum (365 dias)
    assert calendar.isleap(2024) is True
    assert calendar.isleap(2023) is False

    df_test = pd.DataFrame({
        'Ano': [2023, 2024],
        'Precipitacao': [100.0, 110.0],
        'DiasValidos': [365.0, 366.0],
    })

    # Com limiar 99%, nenhum deve ser descartado pois ambos têm 100% de cobertura real
    diag = analisar_qualidade_serie(df_test, limiar_cobertura_pct=99.0, excluir_incompletos=True)
    assert len(diag['anos_descartados']) == 0, (
        f"Anos válidos foram descartados indevidamente: {diag['anos_descartados']}"
    )
    assert diag['n_bruto'] == 2
    assert diag['n_apos_descarte'] == 2
    assert diag['n_descartados'] == 0
    assert diag['pct_descarte'] == 0.0
    assert 'tendencia_significativa' in diag['mann_kendall']

    # Teste de ano incompleto descartado com chaves completas
    df_test2 = pd.DataFrame({
        'Ano': [2022, 2023, 2024],
        'Precipitacao': [90.0, 100.0, 110.0],
        'DiasValidos': [100.0, 365.0, 366.0],
    })
    diag2 = analisar_qualidade_serie(df_test2, limiar_cobertura_pct=90.0, excluir_incompletos=True)
    assert diag2['n_bruto'] == 3
    assert diag2['n_apos_descarte'] == 2
    assert diag2['n_descartados'] == 1
    assert abs(diag2['pct_descarte'] - (1.0 / 3.0 * 100.0)) < 0.1
    assert 'precipitacao' in diag2['anos_descartados'][0]
    assert 'valor' in diag2['anos_descartados'][0]



# ── P2-11: Texto de plausibilidade do CV no i18n ──────────────────────────────
def test_p2_11_cv_alert_i18n():
    alert_pt = t('diag_cv_alert', 'PT')
    alert_en = t('diag_cv_alert', 'EN')
    assert "referência empírica" in alert_pt or "semiárida" in alert_pt or "usual" in alert_pt
    assert "empirical reference" in alert_en or "semiarid" in alert_en or "typical" in alert_en


# ── P2-12: Centralização de constantes de Sherman ─────────────────────────────
def test_p2_12_sherman_constants_centralization():
    assert 'A' in SHERMAN_OPTIMIZER_BOUNDS
    assert 'B' in SHERMAN_OPTIMIZER_BOUNDS
    assert 'C' in SHERMAN_OPTIMIZER_BOUNDS
    assert 'D' in SHERMAN_OPTIMIZER_BOUNDS

    assert 'A' in SHERMAN_TYPICAL_RANGES
    assert 'B' in SHERMAN_TYPICAL_RANGES
    assert 'C' in SHERMAN_TYPICAL_RANGES
    assert 'D' in SHERMAN_TYPICAL_RANGES

    # As faixas típicas da literatura são estritamente contidas nos bounds do otimizador
    for p in ('A', 'B', 'C', 'D'):
        opt_low, opt_high = SHERMAN_OPTIMIZER_BOUNDS[p]
        typ_low, typ_high = SHERMAN_TYPICAL_RANGES[p]
        assert opt_low <= typ_low, f"Limite inferior típico de {p} menor que o do otimizador"
        assert typ_high <= opt_high, f"Limite superior típico de {p} maior que o do otimizador"

    # Verifica se os módulos importam as constantes sem redefini-las
    assert report.SHERMAN_TYPICAL_RANGES is SHERMAN_TYPICAL_RANGES
    assert report_word.SHERMAN_TYPICAL_RANGES is SHERMAN_TYPICAL_RANGES
    assert streamlit_app.SHERMAN_TYPICAL_RANGES is SHERMAN_TYPICAL_RANGES


# ── Regressão Completa: Caso de Novo Progresso, PA ───────────────────────────
def test_regression_novo_progresso():
    """
    Cenário de regressão obrigatório: Novo Progresso, PA (lat -7.0375, lon -55.4186),
    raio 35 km, estações 755001, 755000, 655000.
    """
    # Verifica que a Isozona E é detectada para Novo Progresso
    iso_np = detectar_isozona_coordenadas(lat=-7.0375, lon=-55.4186)
    assert iso_np == 'E', f"Novo Progresso, PA deve ser Isozona E, obteve {iso_np}"


if __name__ == '__main__':
    tests = [
        ('P0-1: Preservação de coluna de duração', test_p0_1_duration_column_preserved),
        ('P0-2: Status de consistência física OK e chave is_valid', test_p0_2_physical_consistency_status_ok),
        ('P0-3 & P0-4: Mensagens legíveis e violacoes_param', test_p0_3_p0_4_violations_message_and_params),
        ('P0-5: Métricas de validação de Sherman (R², RMSE, celular)', test_p0_5_sherman_regression_metrics),
        ('P1-6: Alerta IDW co-localização / degenerado (Novo Progresso)', test_p1_6_idw_colocation_alert_novo_progresso),
        ('P1-7: Defaults excluir_incompletos=True', test_p1_7_excluir_incompletos_defaults),
        ('P1-8: Isozona GRID para linhas/bordas e fallback seguro', test_p1_8_isozone_grid_color_and_fallback),
        ('P2-9: _verificar_toque_bound sem bug de precedência', test_p2_9_verificar_toque_bound),
        ('P2-10: Cobertura com dias de ano bissexto/comum', test_p2_10_leap_year_days_coverage),
        ('P2-11: Texto de plausibilidade do CV no i18n', test_p2_11_cv_alert_i18n),
        ('P2-12: Centralização de constantes de Sherman', test_p2_12_sherman_constants_centralization),
        ('Regressão: Novo Progresso, PA Isozona E', test_regression_novo_progresso),
    ]

    passed = 0
    failed = 0
    print("=" * 70)
    print("EXECUTANDO SUÍTE DE TESTES DE AUDITORIA v2.1 (SII·IDF)")
    print("=" * 70)
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name} -> {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("=" * 70)
    print(f"TOTAL: {passed} passaram, {failed} falharam.")
    print("=" * 70)
    if failed > 0:
        exit(1)
