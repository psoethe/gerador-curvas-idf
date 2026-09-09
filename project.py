"""
Módulo de Persistência e Auditoria de Projetos Hidrológicos (SII-HiDRO v3.0).
Implementa o formato de arquivo .siih (JSON puro UTF-8 / gzip > 5MB) sob o esquema "siih/1".

Princípio estruturante da auditoria:
"Guarde entrada, recalcule saída."
- Séries brutas, decisões, filtros, justificativas e polígono da bacia são salvos.
- Gumbel, Sherman, matriz IDF e vazões nascem de novo a cada abertura.
- O snapshot salvo serve estritamente para auditoria de integridade e comparação de versão.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import calculations
from calculations import run_full_analysis, UserError

CURRENT_SCHEMA = "siih/1"
CURRENT_APP_VERSION = "3.0.0"
MAX_UNCOMPRESSED_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def calcular_hash_inputs(
    isozona: str,
    lat: float,
    lon: float,
    data_method: str,
    estacao_str: str,
    df_series: pd.DataFrame | None,
    y0: int | None,
    y1: int | None,
    limiar_cob: float,
    excluir_inc: bool,
    modo_sherman: str,
    idw_p: float = 2.0,
) -> str:
    """Calcula hash SHA-256 dos parâmetros de entrada para detecção de adulteração ou invalidação."""
    s_len = len(df_series) if df_series is not None and not df_series.empty else 0
    s_sum = 0.0
    if df_series is not None and not df_series.empty:
        col_p = 'Precipitacao' if 'Precipitacao' in df_series.columns else df_series.columns[1]
        try:
            s_sum = float(pd.to_numeric(df_series[col_p], errors='coerce').sum())
        except Exception:
            s_sum = 0.0

    payload = (
        f"{isozona}|{lat:.4f}|{lon:.4f}|{data_method}|{estacao_str}|"
        f"{s_len}|{s_sum:.2f}|{y0}|{y1}|{limiar_cob:.1f}|{excluir_inc}|"
        f"{modo_sherman}|{idw_p:.2f}"
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _json_default(o):
    if hasattr(o, 'to_dict'):
        return o.to_dict(orient='records')
    if hasattr(o, 'tolist'):
        return o.tolist()
    if isinstance(o, (np.integer, np.int64, np.int32)):
        return int(o)
    if isinstance(o, (np.floating, np.float64, np.float32)):
        return float(o)
    return str(o)


def serialize_project(data: dict) -> bytes:
    """Serializa o dicionário do projeto em JSON UTF-8. Se > 5MB, comprime com gzip."""
    json_str = json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)
    raw_bytes = json_str.encode('utf-8')
    if len(raw_bytes) > MAX_UNCOMPRESSED_SIZE_BYTES:
        return gzip.compress(raw_bytes, compresslevel=6)
    return raw_bytes


def deserialize_project(raw_bytes: bytes) -> dict:
    """Deserializa bytes (.siih) em dicionário, descompactando gzip se detectado magic header."""
    if raw_bytes.startswith(b'\x1f\x8b'):
        raw_bytes = gzip.decompress(raw_bytes)
    json_str = raw_bytes.decode('utf-8')
    return json.loads(json_str)


def extrair_df_series_brutas(idf_section: dict) -> pd.DataFrame:
    """Reconstrói um pd.DataFrame a partir da seção 'series_brutas' do projeto .siih."""
    series_brutas = idf_section.get("series_brutas", {})
    if not series_brutas:
        return pd.DataFrame(columns=['Ano', 'Precipitacao'])

    # Caso 1: Se houver chave unificada 'serie_unificada' ou 'serie_principal'
    if "serie_unificada" in series_brutas:
        records = series_brutas["serie_unificada"]
    elif "serie_principal" in series_brutas:
        records = series_brutas["serie_principal"]
    elif len(series_brutas) == 1:
        # Apenas uma estação
        primeira_chave = next(iter(series_brutas))
        records = series_brutas[primeira_chave]
    else:
        # Multi-estação / IDW: se houver tabela unificada gravada, usa; senão combina por IDW
        if "idw_sintetica" in series_brutas:
            records = series_brutas["idw_sintetica"]
        else:
            primeira_chave = next(iter(series_brutas))
            records = series_brutas[primeira_chave]

    df = pd.DataFrame(records)
    if 'ano' in df.columns and 'Ano' not in df.columns:
        df.rename(columns={'ano': 'Ano'}, inplace=True)
    if 'precipitacao' in df.columns and 'Precipitacao' not in df.columns:
        df.rename(columns={'precipitacao': 'Precipitacao'}, inplace=True)
    if 'dias_validos' in df.columns and 'DiasValidos' not in df.columns:
        df.rename(columns={'dias_validos': 'DiasValidos'}, inplace=True)

    if df.empty or 'Ano' not in df.columns or 'Precipitacao' not in df.columns:
        return pd.DataFrame(columns=['Ano', 'Precipitacao'])

    df['Ano'] = pd.to_numeric(df['Ano'], errors='coerce')
    df['Precipitacao'] = pd.to_numeric(df['Precipitacao'], errors='coerce')
    return df.dropna(subset=['Ano', 'Precipitacao']).sort_values('Ano').reset_index(drop=True)




def salvar_projeto(filepath: str | Path | None = None, state: dict | Any = None) -> bytes:
    """
    Grava o estado do projeto no formato .siih seguindo o esquema siih/1.
    Retorna os bytes gravados (JSON UTF-8 ou gzip > 5MB).
    """
    if state is None:
        try:
            import streamlit as st
            state = st.session_state
        except Exception:
            state = {}

    def _get(key, default=None):
        if hasattr(state, 'get'):
            return state.get(key, default)
        if isinstance(state, dict):
            return state.get(key, default)
        return getattr(state, key, default)

    lat = float(_get('proj_lat', -7.0375) or 0.0)
    lon = float(_get('proj_lon', -55.4186) or 0.0)
    loc_desc = str(_get('proj_loc', 'Novo Progresso, PA') or '')
    isozona = str(_get('isozona_escolhida', 'B') or 'B')
    isozona_origem = str(_get('isozona_origem', 'automatica') or 'automatica')
    isozona_just = _get('isozona_justificativa', None)

    # Coleta da série histórica
    loaded_df = _get('loaded_df')
    if loaded_df is None or not isinstance(loaded_df, pd.DataFrame) or loaded_df.empty:
        # Tenta reconstruir a partir de series_df de results se disponível
        res = _get('results')
        if res and isinstance(res, dict) and 'series_df' in res:
            loaded_df = res['series_df']

    series_records = []
    if loaded_df is not None and not loaded_df.empty:
        col_a = 'Ano' if 'Ano' in loaded_df.columns else loaded_df.columns[0]
        col_p = 'Precipitacao' if 'Precipitacao' in loaded_df.columns else loaded_df.columns[1]
        col_d = 'DiasValidos' if 'DiasValidos' in loaded_df.columns else None

        for _, row in loaded_df.iterrows():
            rec = {
                'ano': int(row[col_a]),
                'precipitacao': float(row[col_p]),
            }
            if col_d and pd.notna(row[col_d]):
                rec['dias_validos'] = int(row[col_d])
            series_records.append(rec)

    # Identificação da estação ou IDW
    estacao_cod = str(_get('estacao_input', '') or '')
    data_method = str(_get('data_source_method', 'api') or 'api')
    api_source = str(_get('api_source', 'hist') or 'hist')
    selection_mode = str(_get('selection_mode', 'single') or 'single')
    idw_p = float(_get('idw_p', 2.0) or 2.0)

    estacoes_meta = []
    station_info = _get('station_info')
    if station_info and isinstance(station_info, dict):
        estacoes_meta.append({
            'codigo': str(station_info.get('codigo', estacao_cod)),
            'nome': str(station_info.get('nome', '')),
            'lat': float(station_info.get('latitude', lat)),
            'lon': float(station_info.get('longitude', lon)),
            'distancia_km': float(station_info.get('distancia_km', 0.0)),
            'peso': 1.0,
        })
    idw_meta = _get('idw_meta')
    if idw_meta and isinstance(idw_meta, list):
        estacoes_meta = [
            {
                'codigo': str(stn.get('codigo', '')),
                'nome': str(stn.get('nome', '')),
                'lat': float(stn.get('latitude', 0.0)),
                'lon': float(stn.get('longitude', 0.0)),
                'distancia_km': float(stn.get('distancia_km', 0.0)),
                'peso': float(stn.get('peso', 0.0)),
            }
            for stn in idw_meta
        ]

    # Dicionário de séries brutas
    series_brutas = {}
    if estacao_cod:
        series_brutas[estacao_cod] = series_records
    series_brutas["serie_unificada"] = series_records

    # Filtros
    y0 = _get('year_start')
    y1 = _get('year_end')
    y0_val = int(y0) if y0 is not None else None
    y1_val = int(y1) if y1 is not None else None
    limiar_cob = float(_get('limiar_cobertura_pct', 90.0) or 90.0)
    excluir_inc = bool(_get('excluir_incompletos', True))
    modo_sherman = str(_get('modo_ajuste_sherman', 'log') or 'log')

    # Hash dos inputs
    h_inputs = calcular_hash_inputs(
        isozona=isozona,
        lat=lat,
        lon=lon,
        data_method=data_method,
        estacao_str=estacao_cod,
        df_series=loaded_df,
        y0=y0_val,
        y1=y1_val,
        limiar_cob=limiar_cob,
        excluir_inc=excluir_inc,
        modo_sherman=modo_sherman,
        idw_p=idw_p,
    )

    # Resultados snapshot (apenas para conferência e auditoria)
    res = _get('results')
    snapshot = {}
    if res and isinstance(res, dict) and 'sherman_params' in res:
        sh = res['sherman_params']
        snapshot = {
            'mu': float(res.get('mu', 0.0)),
            'sigma': float(res.get('sigma', 0.0)),
            'n_samples': int(res.get('n_samples', 0)),
            'sherman': {
                'A': float(sh.get('A', 0.0)),
                'B': float(sh.get('B', 0.0)),
                'C': float(sh.get('C', 0.0)),
                'D': float(sh.get('D', 0.0)),
                'R²': float(sh.get('R²', 0.0)),
                'RMSE': float(sh.get('RMSE', 0.0)),
                'erro_medio_celula': float(sh.get('erro_medio_celula', 0.0)),
            },
            'hash_inputs': f"sha256:{h_inputs}",
        }

    now_iso = datetime.now().astimezone().isoformat()

    project_dict = {
        "schema": CURRENT_SCHEMA,
        "app_version": CURRENT_APP_VERSION,
        "saved_at": now_iso,
        "identificacao": {
            "responsavel": str(_get('responsavel', 'Pedro Luis Soethe Cursino') or ''),
            "obra": str(_get('nome_obra', 'Rodovia BR-163 km 812') or ''),
            "dispositivo": str(_get('dispositivo', 'bueiro_grota') or ''),
            "tr_projeto": int(_get('tr_projeto', 25) or 25),
        },
        "local": {
            "lat": lat,
            "lon": lon,
            "descricao": loc_desc,
            "isozona": isozona,
            "isozona_origem": isozona_origem,
            "isozona_justificativa": isozona_just,
        },
        "idf": {
            "data_source_method": data_method,
            "api_source": api_source,
            "selection_mode": selection_mode,
            "idw_p": idw_p,
            "estacoes": estacoes_meta,
            "series_brutas": series_brutas,
            "consulta_ana": {
                "em": now_iso,
                "endpoint": "hidroweb/series",
            },
            "filtros": {
                "year_start": y0_val,
                "year_end": y1_val,
                "limiar_cobertura_pct": limiar_cob,
                "excluir_incompletos": excluir_inc,
                "modo_ajuste_sherman": modo_sherman,
            },
            "anos_reincluidos": _get('anos_reincluidos', []),
            "resultados_snapshot": snapshot,
        },
        "bacia": {
            "confirmada_por_usuario": bool(_get('bacia_confirmada', False)),
            "exutorio": {"lat": lat, "lon": lon},
            "results": _get('bacia_results'),
        },

        "vazao": {
            "tc_calculados": {
                f['id']: f['tc_min'] for f in (_get('vazao_results', {}).get('tc_data', {}).get('formulas', []))
            } if _get('vazao_results') else {},
            "tc_adotado": {
                "formula": _get('formula_tc_adotada', None),
                "valor_min": _get('tc_adotado_min', None),
                "justificativa": _get('justificativa_tc', ''),
            },
            "metodo": _get('metodo_adotado', None),
            "metodo_racional_bloqueado": {
                "bloqueado": bool(_get('vazao_results', {}).get('bloqueio_racional', False)),
                "motivo": _get('vazao_results', {}).get('motivo_bloqueio_racional', '')
            } if _get('vazao_results') else {},
            "q_projeto_m3s": _get('q_projeto_m3s', None),
            "results": _get('vazao_results', None),
            "tc_adotado_min": _get('tc_adotado_min', None),
            "formula_tc_adotada": _get('formula_tc_adotada', None),
            "metodo_adotado": _get('metodo_adotado', None),
        },

    }

    serialized_bytes = serialize_project(project_dict)

    if filepath is not None:
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(serialized_bytes)
        try:
            import streamlit as st
            st.session_state['project_dirty'] = False
            st.session_state['caminho_arquivo'] = str(p.resolve())
        except Exception:
            pass

    return serialized_bytes


def obter_mudancas_versao(versao_antiga: str) -> str:
    """Lê do CHANGELOG_BEHAVIOR.md as notas de alterações técnicas relevantes entre a versão gravada e a atual."""
    changelog_path = Path(__file__).resolve().parent / "CHANGELOG_BEHAVIOR.md"
    if not changelog_path.exists():
        return f"Arquivo gerado na versão {versao_antiga}. Versão atual do SII-HiDRO: {CURRENT_APP_VERSION}."

    content = changelog_path.read_text(encoding='utf-8')
    return content


def abrir_projeto(filepath_or_bytes: str | Path | bytes | io.BytesIO, recalcular: bool = True) -> dict:
    """
    Executa a sequência estrita de abertura de projeto:
    1. Deserializa e valida schema (rejeita se incompatível).
    2. Compara app_version contra a atual (sinaliza versão anterior e busca CHANGELOG_BEHAVIOR).
    3. Verifica integridade do hash SHA-256 (detecta adulteração manual).
    4. Revalida a isozona geograficamente via detectar_isozona_coordenadas.
    5. Reconstrói o DataFrame das séries brutas.
    6. Se recalcular=True, executa run_full_analysis com os parâmetros restaurados.
    7. Compara o recalculado com o resultados_snapshot (detecta divergências > 0,5%).
    8. Retorna relatório de integridade e payload restaurado.
    """
    if isinstance(filepath_or_bytes, (str, Path)):
        p = Path(filepath_or_bytes)
        if not p.exists():
            raise FileNotFoundError(f"Arquivo de projeto não encontrado: {p}")
        raw_bytes = p.read_bytes()
        file_path_str = str(p.resolve())
    elif isinstance(filepath_or_bytes, io.BytesIO):
        raw_bytes = filepath_or_bytes.getvalue()
        file_path_str = None
    elif isinstance(filepath_or_bytes, bytes):
        raw_bytes = filepath_or_bytes
        file_path_str = None
    else:
        raise TypeError("Entrada deve ser caminho (str/Path), bytes ou BytesIO.")

    proj_data = deserialize_project(raw_bytes)

    # 1. Validação de Schema
    schema = proj_data.get("schema")
    if schema != CURRENT_SCHEMA:
        raise ValueError(
            f"Esquema de projeto desconhecido ou incompatível: '{schema}'. "
            f"Este aplicativo SII-HiDRO suporta exclusivamente '{CURRENT_SCHEMA}'."
        )

    # 2. Validação de Versão
    proj_version = proj_data.get("app_version", "unknown")
    versao_anterior = (proj_version != CURRENT_APP_VERSION)
    changelog_text = obter_mudancas_versao(proj_version) if versao_anterior else ""

    # Extração de seções
    ident = proj_data.get("identificacao", {})
    loc = proj_data.get("local", {})
    idf = proj_data.get("idf", {})
    bacia = proj_data.get("bacia", {})
    vazao = proj_data.get("vazao", {})

    lat = float(loc.get("lat", 0.0))
    lon = float(loc.get("lon", 0.0))
    isozona_gravada = str(loc.get("isozona", "B"))
    isozona_origem_gravada = str(loc.get("isozona_origem", ""))

    # 3. Revalidação Geográfica da Isozona
    isozona_detectada = calculations.detectar_isozona_coordenadas(lat, lon)
    isozona_divergente = False
    if isozona_detectada != 'FALLBACK' and isozona_detectada != isozona_gravada:
        # Houve divergência entre a detectada no mapa atual e a gravada no projeto
        isozona_divergente = True

    # 4. Reconstrução do DataFrame de Chuvas
    df_series = extrair_df_series_brutas(idf)

    # 5. Integridade do Hash SHA-256
    filtros = idf.get("filtros", {})
    y0 = filtros.get("year_start")
    y1 = filtros.get("year_end")
    limiar_cob = float(filtros.get("limiar_cobertura_pct", 90.0))
    excluir_inc = bool(filtros.get("excluir_incompletos", True))
    modo_sherman = str(filtros.get("modo_ajuste_sherman", "log"))
    data_method = str(idf.get("data_source_method", "api"))
    estacoes = idf.get("estacoes", [])
    estacao_str = estacoes[0].get("codigo", "") if estacoes else ""
    idw_p = float(idf.get("idw_p", 2.0))

    hash_recalculado = calcular_hash_inputs(
        isozona=isozona_gravada,
        lat=lat,
        lon=lon,
        data_method=data_method,
        estacao_str=estacao_str,
        df_series=df_series,
        y0=y0,
        y1=y1,
        limiar_cob=limiar_cob,
        excluir_inc=excluir_inc,
        modo_sherman=modo_sherman,
        idw_p=idw_p,
    )

    snapshot = idf.get("resultados_snapshot", {})
    hash_gravado_raw = snapshot.get("hash_inputs", "")
    hash_gravado = hash_gravado_raw.replace("sha256:", "").strip() if hash_gravado_raw else ""

    hash_adulterado = False
    if hash_gravado and hash_gravado != hash_recalculado:
        hash_adulterado = True

    # 6. Recálculo dos Resultados a Quente (Guarde entrada, recalcule saída)
    resultados_recalculados = None
    divergencias_metricas = {}
    divergencia_critica = False

    if recalcular and df_series is not None and not df_series.empty:
        try:
            resultados_recalculados = run_full_analysis(
                df_input=df_series,
                isozona=isozona_gravada,
                lang='PT',
                year_start=y0,
                year_end=y1,
                limiar_cobertura_pct=limiar_cob,
                excluir_incompletos=excluir_inc,
                modo_ajuste_sherman=modo_sherman,
            )

            # Comparação com o snapshot (tolerância de 0,5%)
            if snapshot and 'sherman' in snapshot:
                snap_mu = snapshot.get('mu', 0.0)
                recalc_mu = resultados_recalculados.get('mu', 0.0)
                if snap_mu > 0:
                    diff_mu_pct = abs(recalc_mu - snap_mu) / snap_mu * 100.0
                    if diff_mu_pct > 0.5:
                        divergencias_metricas['mu'] = {'snapshot': snap_mu, 'recalculado': recalc_mu, 'diff_pct': diff_mu_pct}

                snap_sigma = snapshot.get('sigma', 0.0)
                recalc_sigma = resultados_recalculados.get('sigma', 0.0)
                if snap_sigma > 0:
                    diff_sigma_pct = abs(recalc_sigma - snap_sigma) / snap_sigma * 100.0
                    if diff_sigma_pct > 0.5:
                        divergencias_metricas['sigma'] = {'snapshot': snap_sigma, 'recalculado': recalc_sigma, 'diff_pct': diff_sigma_pct}

                snap_sh = snapshot.get('sherman', {})
                recalc_sh = resultados_recalculados.get('sherman_params', {})
                for p_nome in ('A', 'B', 'C', 'D'):
                    val_snap = snap_sh.get(p_nome, 0.0)
                    val_recalc = recalc_sh.get(p_nome, 0.0)
                    if val_snap > 0:
                        diff_p = abs(val_recalc - val_snap) / val_snap * 100.0
                        if diff_p > 0.5:
                            divergencias_metricas[p_nome] = {'snapshot': val_snap, 'recalculado': val_recalc, 'diff_pct': diff_p}

                if len(divergencias_metricas) > 0:
                    divergencia_critica = True

        except Exception as e:
            resultados_recalculados = None

    status_auditoria = {
        'schema_ok': True,
        'app_version': proj_version,
        'versao_anterior': versao_anterior,
        'changelog_behavior': changelog_text,
        'hash_ok': not hash_adulterado,
        'hash_adulterado': hash_adulterado,
        'hash_recalculado': hash_recalculado,
        'hash_gravado': hash_gravado,
        'isozona_divergente': isozona_divergente,
        'isozona_gravada': isozona_gravada,
        'isozona_detectada': isozona_detectada,
        'divergencia_critica': divergencia_critica,
        'divergencias_metricas': divergencias_metricas,
        'file_path': file_path_str,
    }

    return {
        "dados": proj_data,
        "df_series": df_series,
        "recalculado": resultados_recalculados,
        "status_auditoria": status_auditoria,
    }


def carregar_projeto_no_session_state(
    proj_payload: dict,
    isozona_escolhida: str | None = None,
) -> None:
    """Restaura completamente o projeto carregado no st.session_state."""
    import streamlit as st

    dados = proj_payload["dados"]
    ident = dados.get("identificacao", {})
    loc = dados.get("local", {})
    idf = dados.get("idf", {})
    bacia = dados.get("bacia", {})
    vazao = dados.get("vazao", {})
    audit = proj_payload.get("status_auditoria", {})

    st.session_state.responsavel = ident.get("responsavel", "Pedro Luis Soethe Cursino")
    st.session_state.nome_obra = ident.get("obra", "Rodovia BR-163 km 812")
    st.session_state.dispositivo = ident.get("dispositivo", "bueiro_grota")
    st.session_state.tr_projeto = int(ident.get("tr_projeto", 25))

    st.session_state.proj_lat = float(loc.get("lat", -7.0375))
    st.session_state.proj_lon = float(loc.get("lon", -55.4186))
    st.session_state.proj_loc = loc.get("descricao", "Novo Progresso, PA")

    iso_final = isozona_escolhida if isozona_escolhida else loc.get("isozona", "B")
    st.session_state.isozona_escolhida = iso_final
    st.session_state.isozona_origem = loc.get("isozona_origem", "Automática")

    st.session_state.loaded_df = proj_payload.get("df_series")
    st.session_state.data_source_method = idf.get("data_source_method", "api")
    st.session_state.api_source = idf.get("api_source", "hist")
    st.session_state.selection_mode = idf.get("selection_mode", "single")
    st.session_state.idw_p = float(idf.get("idw_p", 2.0))

    filtros = idf.get("filtros", {})
    st.session_state.year_start = filtros.get("year_start")
    st.session_state.year_end = filtros.get("year_end")
    st.session_state.limiar_cobertura_pct = float(filtros.get("limiar_cobertura_pct", 90.0))
    st.session_state.excluir_incompletos = bool(filtros.get("excluir_incompletos", True))
    st.session_state.modo_ajuste_sherman = filtros.get("modo_ajuste_sherman", "log")

    st.session_state.bacia_confirmada = bool(bacia.get("confirmada_por_usuario", False))
    st.session_state.bacia_results = bacia.get("results")
    st.session_state.q_projeto_m3s = vazao.get("q_projeto_m3s")
    st.session_state.vazao_results = vazao.get("results")
    tc_adotado_obj = vazao.get("tc_adotado", {})
    if isinstance(tc_adotado_obj, dict):
        st.session_state.tc_adotado_min = tc_adotado_obj.get("valor_min") or vazao.get("tc_adotado_min")
        st.session_state.formula_tc_adotada = tc_adotado_obj.get("formula") or vazao.get("formula_tc_adotada")
        st.session_state.justificativa_tc = tc_adotado_obj.get("justificativa") or vazao.get("justificativa_tc", "")
    else:
        st.session_state.tc_adotado_min = vazao.get("tc_adotado_min")
        st.session_state.formula_tc_adotada = vazao.get("formula_tc_adotada")
        st.session_state.justificativa_tc = vazao.get("justificativa_tc", "")
    st.session_state.metodo_adotado = vazao.get("metodo") or vazao.get("metodo_adotado")



    # Injeta os resultados recalculados a quente
    recalc = proj_payload.get("recalculado")
    st.session_state.results = recalc
    st.session_state.calc_hash = audit.get("hash_recalculado")

    if audit.get("file_path"):
        st.session_state.caminho_arquivo = audit.get("file_path")

    st.session_state.project_dirty = False
    st.session_state.active_module = 'idf'
    st.session_state.step = 3 if recalc else 0
    st.session_state.current_step = 4 if recalc else 1
