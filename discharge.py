"""
Módulo Vazão — SII-HiDRO (v3.0)
Cálculo de tempos de concentração multi-fórmula (Kirpich, Giandotti, Ven Te Chow,
Corps of Engineers, DNOS e SCS Lag) com análise explícita de domínio de calibração.
Decisão de método hidrológico por limiar normativo de área (DNIT IPR-724):
- Até 1,00 km² (100 ha): Método Racional.
- Acima de 1,00 km²: Bloqueio do Racional e condução mandatória para Hidrograma
  Unitário SCS com Hietograma de Blocos Alternados e Abatimento Espacial.
"""
from __future__ import annotations

import math
from typing import Any, Optional
import numpy as np
import pandas as pd


# ── Limiar Normativo Único e Documentado (DNIT IPR-724) ───────────────────────
# Manual de Drenagem de Rodovias do DNIT (Publicação IPR-724, item 3.2.1)
# O Método Racional tem validade restrita a microbacias de até 100 hectares (1,00 km²).
# Acima desse limite, efeitos de atenuação e variação espacial exigem modelo de hidrograma.
LIMIAR_AREA_RACIONAL_IPR724_KM2: float = 1.00


def calcular_tempos_concentracao(
    area_km2: float,
    comprimento_talvegue_km: float,
    desnivel_m: float,
    declividade_m_m: float,
    declividade_media_pct: float = 3.0,
    cn: float = 70.0,
) -> dict[str, Any]:
    """
    Calcula o tempo de concentração (tc) pelas 6 fórmulas clássicas de referência:
    1. Kirpich (1940)
    2. Giandotti (1934)
    3. Ven Te Chow (1962)
    4. US Army Corps of Engineers (1946)
    5. DNOS (Brasil)
    6. SCS Lag (NRCS 1972)

    Para cada fórmula, avalia o domínio de calibração físico e indica conformidade.
    Nunca apresenta um valor único sem evidenciar a dispersão técnica entre as estimativas.
    """
    L = max(float(comprimento_talvegue_km), 0.01)
    A = max(float(area_km2), 0.001)
    dH = max(float(desnivel_m), 0.5)
    S = max(float(declividade_m_m), 0.0001)
    S_pct = max(float(declividade_media_pct), 0.1)
    cn_val = min(max(float(cn), 30.0), 98.0)

    formulas = []

    # 1. Kirpich (1940): tc = 57 * (L³ / ΔH)^0.385 (min)
    tc_kirpich = 57.0 * ((L ** 3.0) / dH) ** 0.385
    val_kirpich = (A <= 4.0 and S >= 0.005)
    motivo_k = "" if val_kirpich else "Calibrada para microbacias rurais (A ≤ 4 km² e S ≥ 0,5%)"
    formulas.append({
        'id': 'kirpich',
        'nome': 'Kirpich (1940)',
        'tc_min': round(tc_kirpich, 1),
        'tc_h': round(tc_kirpich / 60.0, 2),
        'dominio': 'Microbacias rurais agrícolas íngremes (A ≤ 4 km², S ≥ 0,5%)',
        'no_dominio': val_kirpich,
        'aviso': motivo_k,
    })

    # 2. Giandotti (1934): tc = (4√A + 1.5L) / (0.8√ΔH) (h)
    tc_giandotti_h = (4.0 * math.sqrt(A) + 1.5 * L) / (0.8 * math.sqrt(dH))
    tc_giandotti = tc_giandotti_h * 60.0
    val_giandotti = (A >= 5.0 and A <= 1000.0)
    motivo_g = "" if val_giandotti else "Calibrada para bacias médias e grandes (5 km² ≤ A ≤ 1000 km²)"
    formulas.append({
        'id': 'giandotti',
        'nome': 'Giandotti (1934)',
        'tc_min': round(tc_giandotti, 1),
        'tc_h': round(tc_giandotti_h, 2),
        'dominio': 'Bacias naturais e montanhosas médias (5 km² ≤ A ≤ 1000 km²)',
        'no_dominio': val_giandotti,
        'aviso': motivo_g,
    })

    # 3. Ven Te Chow (1962): tc = 0.160 * (L / √S_pct)^0.64 (h)
    tc_vtc_h = 0.160 * ((L / math.sqrt(S_pct)) ** 0.64)
    tc_vtc = tc_vtc_h * 60.0
    val_vtc = (A <= 25.0 and S_pct >= 0.5)
    motivo_v = "" if val_vtc else "Calibrada para bacias naturais até 25 km² com declividade > 0,5%"
    formulas.append({
        'id': 'ven_te_chow',
        'nome': 'Ven Te Chow (1962)',
        'tc_min': round(tc_vtc, 1),
        'tc_h': round(tc_vtc_h, 2),
        'dominio': 'Bacias agrícolas com canais naturais bem definidos (A ≤ 25 km²)',
        'no_dominio': val_vtc,
        'aviso': motivo_v,
    })

    # 4. US Army Corps of Engineers (1946): tc = 0.191 * (L / √S)^0.76 (h)
    tc_corps_h = 0.191 * ((L / math.sqrt(S)) ** 0.76)
    tc_corps = tc_corps_h * 60.0
    val_corps = (A <= 50.0)
    motivo_c = "" if val_corps else "Calibrada para bacias até 50 km²"
    formulas.append({
        'id': 'corps_engineers',
        'nome': 'US Army Corps of Engineers (1946)',
        'tc_min': round(tc_corps, 1),
        'tc_h': round(tc_corps_h, 2),
        'dominio': 'Bacias rurais e semi-urbanas de relevo ondulado a acidentado (A ≤ 50 km²)',
        'no_dominio': val_corps,
        'aviso': motivo_c,
    })

    # 5. DNOS (Brasil): tc = 60 * 0.41 * (L / √S)^0.60 (min)
    tc_dnos = 60.0 * 0.41 * ((L / math.sqrt(S)) ** 0.60)
    val_dnos = (A >= 1.0 and A <= 100.0)
    motivo_d = "" if val_dnos else "Calibrada para bacias naturais brasileiras de 1 km² a 100 km²"
    formulas.append({
        'id': 'dnos',
        'nome': 'DNOS (Brasil)',
        'tc_min': round(tc_dnos, 1),
        'tc_h': round(tc_dnos / 60.0, 2),
        'dominio': 'Bacias naturais brasileiras com relevo suave a ondulado (1 km² ≤ A ≤ 100 km²)',
        'no_dominio': val_dnos,
        'aviso': motivo_d,
    })

    # 6. SCS Lag (NRCS 1972): tc = 5/3 * t_lag
    # t_lag_h = 0.0617 * (L*1000)^0.8 * (1000/CN - 9)^0.7 / (100 * S_pct^0.5)
    lag_num = 0.0617 * ((L * 1000.0) ** 0.8) * (((1000.0 / cn_val) - 9.0) ** 0.7)
    lag_den = 100.0 * (S_pct ** 0.5)
    t_lag_h = lag_num / lag_den if lag_den > 0 else 1.0
    tc_scs_h = (5.0 / 3.0) * t_lag_h
    tc_scs = tc_scs_h * 60.0
    val_scs = (A <= 80.0 and cn_val >= 50.0)
    motivo_s = "" if val_scs else "Calibrada para bacias rurais homogêneas (A ≤ 80 km², CN ≥ 50)"
    formulas.append({
        'id': 'scs_lag',
        'nome': 'SCS Lag (NRCS 1972)',
        'tc_min': round(tc_scs, 1),
        'tc_h': round(tc_scs_h, 2),
        'dominio': 'Bacias rurais com curva número homogênea (A ≤ 80 km², CN ≥ 50)',
        'no_dominio': val_scs,
        'aviso': motivo_s,
    })

    valores = [f['tc_min'] for f in formulas]
    tc_minimo = min(valores)
    tc_maximo = max(valores)
    tc_medio = float(np.mean(valores))
    tc_mediana = float(np.median(valores))
    dispersao_pct = ((tc_maximo - tc_minimo) / tc_medio) * 100.0 if tc_medio > 0 else 0.0

    return {
        'formulas': formulas,
        'estatisticas': {
            'minimo_min': round(tc_minimo, 1),
            'maximo_min': round(tc_maximo, 1),
            'medio_min': round(tc_medio, 1),
            'mediana_min': round(tc_mediana, 1),
            'dispersao_pct': round(dispersao_pct, 1),
        }
    }


def calcular_intensidade_sherman(
    sherman_params: dict[str, float],
    tc_min: float,
    tr_anos: float = 25.0
) -> float:
    """
    Calcula a intensidade de chuva i (mm/h) a partir dos 4 parâmetros de Sherman:
    i = (A * TR^B) / (t + C)^D
    """
    A = float(sherman_params.get('A', 1500.0))
    B = float(sherman_params.get('B', 0.20))
    C = float(sherman_params.get('C', 15.0))
    D = float(sherman_params.get('D', 0.80))
    t = max(float(tc_min), 5.0)
    tr = max(float(tr_anos), 1.1)

    numerador = A * (tr ** B)
    denominador = (t + C) ** D
    return float(numerador / denominador) if denominador > 0 else 0.0


def calcular_metodo_racional(
    area_km2: float,
    c_runoff: float,
    i_mm_h: float
) -> dict[str, Any]:
    """
    Aplica o Método Racional clássico: Q = (C * i * A) / 3.6 [m³/s].
    Verifica o limiar de área do DNIT IPR-724 (1,00 km² / 100 ha).
    Se A > 1,00 km², sinaliza bloqueio normativo mandatário.
    """
    bloqueado = (area_km2 > LIMIAR_AREA_RACIONAL_IPR724_KM2)
    q_p = (c_runoff * i_mm_h * area_km2) / 3.6

    motivo = ""
    if bloqueado:
        motivo = (
            f"Bloqueado por limiar normativo: A área da bacia ({area_km2:.2f} km²) excede "
            f"o limite superior de {LIMIAR_AREA_RACIONAL_IPR724_KM2:.2f} km² (100 ha) "
            f"estabelecido pelo DNIT IPR-724. Efeitos de amortecimento na calha e a "
            f"não-uniformidade espacial da chuva invalidam o Método Racional."
        )

    return {
        'metodo': 'Método Racional',
        'bloqueado': bloqueado,
        'motivo_bloqueio': motivo,
        'limiar_area_km2': LIMIAR_AREA_RACIONAL_IPR724_KM2,
        'area_km2': area_km2,
        'c_runoff': round(c_runoff, 3),
        'i_mm_h': round(i_mm_h, 2),
        'q_pico_m3s': round(q_p, 2),
    }


def calcular_hidrograma_scs(
    area_km2: float,
    cn: float,
    tc_min: float,
    sherman_params: dict[str, float],
    tr_anos: float = 25.0,
    duracao_h: float = 24.0,
    dt_min: float = 5.0,
) -> dict[str, Any]:
    """
    Modela o hidrograma de cheia pelo Método do Hidrograma Unitário Sintético do SCS:
    1. Fator de Abatimento Espacial da Chuva (ARF): K_abat = 1 - 0.005 * √A
    2. Hietograma de Precipitação por Blocos Alternados a partir da curva IDF
    3. Perdas e Chuva Efetiva pelo modelo Curve Number (SCS / NRCS NEH-4)
    4. Hidrograma Unitário Triangular Adimensional SCS
    5. Convolução Temporal discreta para obtenção de Q(t)
    """
    A = max(float(area_km2), 0.01)
    cn_val = min(max(float(cn), 30.0), 98.0)
    tc = max(float(tc_min), 5.0)

    # 1. Coeficiente de Abatimento Espacial
    k_abat = max(0.70, min(1.0, 1.0 - 0.005 * math.sqrt(A)))

    # 2. Hietograma por Blocos Alternados
    total_dur_min = duracao_h * 60.0
    n_passos = int(total_dur_min / dt_min)
    t_passos = np.arange(1, n_passos + 1) * dt_min

    # Chuva acumulada da IDF
    intensidades = [calcular_intensidade_sherman(sherman_params, t, tr_anos) for t in t_passos]
    intensidades = np.array(intensidades)
    p_cum_raw = intensidades * (t_passos / 60.0) * k_abat
    p_inc_raw = np.diff(np.insert(p_cum_raw, 0, 0.0))

    # Ordenação decrescente e posicionamento alternado
    p_sorted = np.sort(p_inc_raw)[::-1]
    hietograma = np.zeros(n_passos)
    idx_centro = n_passos // 2
    hietograma[idx_centro] = p_sorted[0]

    left = idx_centro - 1
    right = idx_centro + 1
    for k in range(1, len(p_sorted)):
        if k % 2 == 1:
            if right < n_passos:
                hietograma[right] = p_sorted[k]
                right += 1
        else:
            if left >= 0:
                hietograma[left] = p_sorted[k]
                left -= 1

    p_cum = np.cumsum(hietograma)

    # 3. Chuva Efetiva SCS
    S_ret = (25400.0 / cn_val) - 254.0
    Ia = 0.20 * S_ret  # Abstração inicial

    pe_cum = np.zeros(n_passos)
    for idx, p_val in enumerate(p_cum):
        if p_val > Ia:
            pe_cum[idx] = ((p_val - Ia) ** 2) / (p_val - Ia + S_ret)
        else:
            pe_cum[idx] = 0.0

    pe_inc = np.diff(np.insert(pe_cum, 0, 0.0))
    pe_inc = np.maximum(0.0, pe_inc)

    # 4. Hidrograma Unitário SCS
    t_p_min = (dt_min / 2.0) + (0.6 * tc)
    t_p_h = t_p_min / 60.0
    q_up = (0.208 * A) / t_p_h  # m³/s por mm de chuva efetiva
    t_b_min = 2.67 * t_p_min

    n_hu = int(math.ceil(t_b_min / dt_min)) + 1
    hu = np.zeros(n_hu)
    for idx in range(n_hu):
        t_cur = idx * dt_min
        if t_cur <= t_p_min:
            hu[idx] = q_up * (t_cur / t_p_min)
        elif t_cur <= t_b_min:
            hu[idx] = q_up * (t_b_min - t_cur) / (t_b_min - t_p_min)
        else:
            hu[idx] = 0.0

    # 5. Convolução Temporal
    q_hidro = np.convolve(pe_inc, hu)[:n_passos]
    q_pico = float(np.max(q_hidro))
    idx_pico = int(np.argmax(q_hidro))
    tempo_pico_min = float((idx_pico + 1) * dt_min)

    # Volume total escoado em m³
    volume_m3 = float(np.sum(q_hidro) * dt_min * 60.0)
    lamina_total_mm = float(p_cum[-1])
    lamina_efetiva_mm = float(pe_cum[-1])

    df_series = pd.DataFrame({
        'Tempo_min': t_passos,
        'Tempo_h': np.round(t_passos / 60.0, 2),
        'Chuva_Total_mm': np.round(hietograma, 2),
        'Chuva_Efetiva_mm': np.round(pe_inc, 2),
        'Vazao_m3s': np.round(q_hidro, 2),
    })

    return {
        'metodo': 'Hidrograma Unitário SCS (NRCS)',
        'q_pico_m3s': round(q_pico, 2),
        'tempo_pico_min': round(tempo_pico_min, 1),
        'tempo_pico_h': round(tempo_pico_min / 60.0, 2),
        'volume_total_m3': round(volume_m3, 1),
        'lamina_total_mm': round(lamina_total_mm, 1),
        'lamina_efetiva_mm': round(lamina_efetiva_mm, 1),
        'coef_abatimento_espacial': round(k_abat, 3),
        'tempo_pico_unitario_tp_min': round(t_p_min, 1),
        'tempo_base_tb_min': round(t_b_min, 1),
        'vazao_pico_unitaria_qu_m3s_mm': round(q_up, 3),
        'df_hidrograma': df_series,
    }


def calcular_vazao_projeto(
    area_km2: float,
    c_runoff: float,
    cn: float,
    tc_adotado_min: float,
    formula_tc_adotada: str,
    sherman_params: dict[str, float],
    tr_anos: float = 25.0,
    metodo_preferido: Optional[str] = None,
) -> dict[str, Any]:
    """
    Executa a determinação completa da vazão de projeto:
    - Avalia elegibilidade do Método Racional conforme IPR-724 (A ≤ 1,00 km²).
    - Executa cálculo do Método Racional.
    - Executa modelo do Hidrograma Unitário SCS.
    - Seleciona o método adotado com base no limiar normativo e/ou escolha do usuário.
    """
    # Intensidade da IDF correspondente ao tc adotado
    i_chuva = calcular_intensidade_sherman(sherman_params, tc_adotado_min, tr_anos)

    res_racional = calcular_metodo_racional(area_km2, c_runoff, i_chuva)
    res_scs = calcular_hidrograma_scs(area_km2, cn, tc_adotado_min, sherman_params, tr_anos=tr_anos)

    # Decisão normativa
    if area_km2 <= LIMIAR_AREA_RACIONAL_IPR724_KM2:
        metodo_adotado = metodo_preferido if metodo_preferido in ['racional', 'scs'] else 'racional'
    else:
        metodo_adotado = 'scs'

    if metodo_adotado == 'racional':
        q_final = res_racional['q_pico_m3s']
        nome_metodo = 'Método Racional'
    else:
        q_final = res_scs['q_pico_m3s']
        nome_metodo = 'Hidrograma Unitário SCS (NRCS)'

    return {
        'metodo_adotado': metodo_adotado,
        'nome_metodo_adotado': nome_metodo,
        'q_projeto_m3s': q_final,
        'tr_anos': tr_anos,
        'tc_adotado_min': tc_adotado_min,
        'formula_tc_adotada': formula_tc_adotada,
        'intensidade_chuva_mm_h': round(i_chuva, 2),
        'limiar_ipr724_km2': LIMIAR_AREA_RACIONAL_IPR724_KM2,
        'bloqueio_racional': res_racional['bloqueado'],
        'motivo_bloqueio_racional': res_racional['motivo_bloqueio'],
        'racional': res_racional,
        'scs': res_scs,
    }
