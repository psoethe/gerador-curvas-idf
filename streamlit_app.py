"""
Gerador de Curvas IDF (Intensidade-Duração-Frequência) — versão Streamlit.

Reaproveita o núcleo de cálculo do app original (Gumbel, desagregação de Taborga,
ajuste de Sherman, integração com a API HidroWebService da ANA e geração de
relatórios em PDF/Word). A interface VIKTOR foi substituída por Streamlit.
"""
import os
import sys
from pathlib import Path

# Garante que os módulos irmãos sejam importáveis independentemente do diretório
# de trabalho (útil quando o host executa a partir da raiz do repositório).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import pandas as pd

from calculations import (
    run_full_analysis,
    parse_station_code,
    obter_serie_chuva_historica,
    listar_estacoes_historicas,
    calcular_distancia_km,
    filtrar_estacoes_por_raio,
    interpolar_series_idw,
    UF_PARA_NOME,
    AnaHidroWebService,
    UserError,
)
from plotting import (
    fig_historical_series,
    fig_gumbel_analysis,
    fig_pdf_curves,
    fig_idf_curves,
)
from report import generate_pdf_report
from report_word import generate_word_report
from i18n import t

# ── Configuração da página ────────────────────────────────────────────────────
st.set_page_config(
    page_title="Gerador de Curvas IDF",
    page_icon="🌧️",
    layout="wide",
)

ISOZONAS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']


# ── Credenciais da ANA (st.secrets → variáveis de ambiente → ana.env) ─────────
def ler_credenciais_ana():
    """Lê ANA_USER/ANA_PASS de st.secrets, do ambiente ou do arquivo ana.env."""
    user = pwd = None
    try:
        user = st.secrets.get("ANA_USER")
        pwd = st.secrets.get("ANA_PASS")
    except Exception:
        pass

    user = user or os.getenv("ANA_USER")
    pwd = pwd or os.getenv("ANA_PASS")

    if not user or not pwd:
        arquivo = Path(__file__).with_name("ana.env")
        if arquivo.is_file():
            valores = {}
            for linha in arquivo.read_text(encoding="utf-8").splitlines():
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, _, valor = linha.partition("=")
                valores[chave.strip()] = valor.strip().strip('"').strip("'")
            user = user or valores.get("ANA_USER")
            pwd = pwd or valores.get("ANA_PASS")

    return (user or "").strip(), (pwd or "").strip()


def cliente_ana():
    user, pwd = ler_credenciais_ana()
    if not user or not pwd:
        raise UserError(
            "Credenciais da ANA não configuradas. Defina ANA_USER e ANA_PASS em "
            "Secrets (Streamlit Cloud), em variáveis de ambiente, ou no arquivo ana.env."
        )
    return AnaHidroWebService(user, pwd)


@st.cache_data(show_spinner=False, ttl=3600)
def buscar_serie_ana(user_id: str, estacao: str, y0: int, y1: int, _progresso=None) -> list[str]:
    """
    Busca a série anual de máximas na ANA, com cache.

    O resultado fica cacheado por (usuário, estação, período) durante 1 h, então
    refazer a mesma consulta é instantâneo — não rebaixa tudo de novo da API.
    A senha é relida aqui dentro para não entrar na chave de cache, e o callback
    de progresso leva '_' no nome para o Streamlit não tentar incluí-lo na chave.
    """
    _, pwd = ler_credenciais_ana()
    cliente = AnaHidroWebService(user_id, pwd)
    df = cliente.obter_serie_chuva(estacao, y0, y1, progresso=_progresso)
    return df['Precipitacao'].astype(str).tolist()


@st.cache_data(show_spinner=False, ttl=3600)
def buscar_serie_historica(estacao: str, y0: int, y1: int) -> list[str]:
    """
    Busca a série anual pelo webservice histórico da ANA (estações convencionais).

    Não requer credenciais e traz todo o período numa única requisição. Cacheada
    por (estação, período) durante 1 h, então reconsultas são instantâneas.
    """
    df = obter_serie_chuva_historica(estacao, y0, y1)
    return df['Precipitacao'].astype(str).tolist()


@st.cache_data(show_spinner=False, ttl=3600)
def buscar_dataframe_ana(user_id: str, estacao: str, y0: int, y1: int) -> pd.DataFrame:
    """Retorna o DataFrame anual de máximas da API telemétrica."""
    _, pwd = ler_credenciais_ana()
    cliente = AnaHidroWebService(user_id, pwd)
    return cliente.obter_serie_chuva(estacao, y0, y1)


@st.cache_data(show_spinner=False, ttl=3600)
def buscar_dataframe_historico(estacao: str, y0: int, y1: int) -> pd.DataFrame:
    """Retorna o DataFrame anual de máximas do webservice histórico."""
    return obter_serie_chuva_historica(estacao, y0, y1)


@st.cache_data(show_spinner=False, ttl=3600)
def listar_estacoes_hist(uf: str) -> list:
    """Lista estações pluviométricas de uma UF pelo inventário legado (sem login)."""
    return listar_estacoes_historicas(uf)


@st.cache_data(show_spinner=False, ttl=86400)
def geocodificar_local(query: str):
    """Geocodifica endereço ou município brasileiro via OpenStreetMap Nominatim."""
    try:
        geo = Nominatim(user_agent="idf_curves_brazil_geocoder")
        q = query.strip()
        loc = geo.geocode(q, country_codes="br", timeout=10)
        if not loc:
            loc = geo.geocode(q, timeout=10)
        if loc:
            return float(loc.latitude), float(loc.longitude), str(loc.address)
    except Exception:
        pass
    return None


@st.cache_data(show_spinner=False, ttl=86400)
def reverse_geocodificar(lat: float, lon: float):
    """Geocodificação reversa de coordenadas para identificar UF e Cidade no Brasil."""
    try:
        geo = Nominatim(user_agent="idf_curves_brazil_reverse")
        loc = geo.reverse((lat, lon), timeout=10)
        if loc and "address" in loc.raw:
            addr = loc.raw["address"]
            iso = addr.get("ISO3166-2-lvl4", "")
            uf = iso.split("-")[-1].upper() if iso.startswith("BR-") else None
            city = (addr.get("city") or addr.get("town") or
                    addr.get("municipality") or addr.get("village") or "")
            state = addr.get("state", "")
            return uf, city, state
    except Exception:
        pass
    return None, None, None


# ── Textos da interface (PT / EN) ─────────────────────────────────────────────
UI = {
    'PT': {
        'title': '🌧️ Gerador de Curvas IDF',
        'subtitle': 'Intensidade – Duração – Frequência · Método de Gumbel + Taborga + Sherman',
        'footer': 'Desenvolvido por <a href="https://pedrosoethe.vercel.app/engenheiro/soethe-ii" target="_blank">Soethe Infrastructure Inteligence</a>',
        'sidebar_cfg': '⚙️ Configuração',
        'meta': 'Identificação',
        'resp': 'Responsável Técnico',
        'loc': 'Localização',
        'est': 'Código da Estação',
        'data_src': 'Fonte dos Dados',
        'method': 'Método de Importação',
        'm_csv': '📥 Arquivo CSV/TXT',
        'm_api': '📡 API HidroWeb (Automático)',
        'm_manual': '✍️ Manual',
        'upload': 'Arquivo ANA/HidroWeb (CSV ou TXT)',
        'manual_lbl': 'Dados manuais — um valor de máxima anual (mm) por linha',
        'manual_ph': '95.2\n88.5\n120.0\n76.4',
        'api_fonte': 'Fonte de dados',
        'fonte_hist': '⚡ Histórica (convencional, recomendada)',
        'fonte_tele': '📡 Telemétrica (automática)',
        'api_cod_manual': 'Código da estação (opcional)',
        'api_cod_manual_ph': 'ex.: 1943000',
        'hint_hist': 'Rápida e sem credenciais: traz toda a série de uma vez. Ideal para curvas IDF.',
        'api_uf': 'UF da Estação',
        'api_buscar': '🔍 Buscar estações da UF',
        'api_sel_est': 'Estação pluviométrica',
        'api_baixar': '📡 Baixar série da ANA',
        'api_hint': 'A busca vai ano a ano e pode levar vários minutos para períodos longos.',
        'period': 'Filtro de Período (opcional)',
        'y0': 'Ano inicial',
        'y1': 'Ano final',
        'region': 'Parâmetros da Região',
        'isozona': 'Isozona de Taborga',
        'lat': 'Latitude',
        'lon': 'Longitude',
        'run': '▶️ Gerar Análise IDF',
        'no_data_yet': 'Configure os dados na barra lateral e clique em **Gerar Análise IDF**.',
        'tab_serie': '📈 Série Histórica',
        'tab_gumbel': '📊 Gumbel',
        'tab_pdf': '🔔 Curvas PDF',
        'tab_idf': '🌧️ Curvas IDF',
        'tab_tables': '🔢 Tabelas',
        'tab_sherman': '🧮 Equação de Sherman',
        'downloads': '⬇️ Exportar Memorial de Cálculo',
        'dl_pdf': '📄 Baixar PDF',
        'dl_word': '📝 Baixar Word',
        'n_years': 'Anos de dados',
        'series_loaded': 'Série carregada da ANA',
        'sherman_eq': 'Equação ajustada',
        'params': 'Parâmetros',
        'gof': 'Qualidade do ajuste',
        'fetching': 'Baixando dados da ANA…',
        'fetch_ok': 'Série baixada: {n} anos.',
        'select_est_first': 'Selecione uma estação antes de baixar.',
        'no_stations': 'Nenhuma estação encontrada para esta UF.',
        # Geoespacial
        'map_title': '🗺️ Localização do Projeto e Estações ANA no Mapa',
        'search_addr_label': 'Buscar por Endereço, Cidade ou CEP',
        'search_addr_ph': 'ex.: Taubaté, SP ou Curitiba, PR ou Av. Paulista, São Paulo',
        'btn_search_addr': '🔍 Localizar',
        'radius_label': 'Raio de busca (km)',
        'click_hint': '💡 Dica: Pesquise o endereço acima ou clique diretamente no mapa para reposicionar o local do projeto.',
        'mode_label': 'Modo de Seleção das Estações',
        'mode_single': '🟢 Estação Mais Próxima',
        'mode_idw': '🔵 Interpolação Multi-estação (IDW)',
        'closest_station': 'Estação selecionada no raio',
        'idw_stations_select': 'Selecione 2 ou mais estações para interpolação IDW:',
        'btn_download_single': '📡 Baixar Dados desta Estação',
        'btn_download_idw': '📡 Baixar e Interpolar Dados via IDW',
        'geo_station_code': 'Código',
        'geo_station_name': 'Nome da Estação',
        'geo_distance_km': 'Distância (km)',
        'geo_weight_pct': 'Peso IDW (%)',
        'idw_success': '✅ Série sintética ponderada gerada via IDW a partir de {n} estações ({anos} anos)!',
        'no_stations_radius': 'Nenhuma estação pluviométrica com coordenadas encontrada no raio de {r} km. Aumente o raio de busca.',
        'stations_found_count': '{n} estações pluviométricas encontradas no raio de {r} km.',
    },
    'EN': {
        'title': '🌧️ IDF Curve Generator',
        'subtitle': 'Intensity – Duration – Frequency · Gumbel + Taborga + Sherman method',
        'footer': 'Developed by <a href="https://pedrosoethe.vercel.app/engenheiro/soethe-ii" target="_blank">Soethe Infrastructure Inteligence</a>',
        'sidebar_cfg': '⚙️ Configuration',
        'meta': 'Identification',
        'resp': 'Technical Responsible',
        'loc': 'Location',
        'est': 'Station Code',
        'data_src': 'Data Source',
        'method': 'Import Method',
        'm_csv': '📥 CSV/TXT File',
        'm_api': '📡 HidroWeb API (Automatic)',
        'm_manual': '✍️ Manual',
        'upload': 'ANA/HidroWeb file (CSV or TXT)',
        'manual_lbl': 'Manual data — one annual maximum (mm) per line',
        'manual_ph': '95.2\n88.5\n120.0\n76.4',
        'api_fonte': 'Data source',
        'fonte_hist': '⚡ Historical (conventional, recommended)',
        'fonte_tele': '📡 Telemetric (automatic)',
        'api_cod_manual': 'Station code (optional)',
        'api_cod_manual_ph': 'e.g. 1943000',
        'hint_hist': 'Fast and credential-free: fetches the whole series at once. Ideal for IDF curves.',
        'api_uf': 'Station State (UF)',
        'api_buscar': '🔍 Search stations in state',
        'api_sel_est': 'Rain gauge station',
        'api_baixar': '📡 Download series from ANA',
        'api_hint': 'The search runs year by year and may take several minutes for long periods.',
        'period': 'Period Filter (optional)',
        'y0': 'Start year',
        'y1': 'End year',
        'region': 'Regional Parameters',
        'isozona': 'Taborga Isozone',
        'lat': 'Latitude',
        'lon': 'Longitude',
        'run': '▶️ Generate IDF Analysis',
        'no_data_yet': 'Configure the data in the sidebar and click **Generate IDF Analysis**.',
        'tab_serie': '📈 Historical Series',
        'tab_gumbel': '📊 Gumbel',
        'tab_pdf': '🔔 PDF Curves',
        'tab_idf': '🌧️ IDF Curves',
        'tab_tables': '🔢 Tables',
        'tab_sherman': '🧮 Sherman Equation',
        'downloads': '⬇️ Export Calculation Report',
        'dl_pdf': '📄 Download PDF',
        'dl_word': '📝 Download Word',
        'n_years': 'Years of data',
        'series_loaded': 'Series loaded from ANA',
        'sherman_eq': 'Fitted equation',
        'params': 'Parameters',
        'gof': 'Goodness of fit',
        'fetching': 'Downloading data from ANA…',
        'fetch_ok': 'Series downloaded: {n} years.',
        'select_est_first': 'Select a station before downloading.',
        'no_stations': 'No stations found for this state.',
        # Geospatial
        'map_title': '🗺️ Project Location & ANA Stations on Map',
        'search_addr_label': 'Search Address, City or ZIP/CEP',
        'search_addr_ph': 'e.g., Taubaté, SP or Curitiba, PR',
        'btn_search_addr': '🔍 Locate',
        'radius_label': 'Search radius (km)',
        'click_hint': '💡 Tip: Search address above or click directly on the map to set project location.',
        'mode_label': 'Station Selection Mode',
        'mode_single': '🟢 Closest Station',
        'mode_idw': '🔵 Multi-station Interpolation (IDW)',
        'closest_station': 'Selected station in radius',
        'idw_stations_select': 'Select 2 or more stations for IDW interpolation:',
        'btn_download_single': '📡 Download Data for this Station',
        'btn_download_idw': '📡 Download & Interpolate Data via IDW',
        'geo_station_code': 'Code',
        'geo_station_name': 'Station Name',
        'geo_distance_km': 'Distance (km)',
        'geo_weight_pct': 'IDW Weight (%)',
        'idw_success': '✅ Synthetic weighted series generated via IDW from {n} stations ({anos} years)!',
        'no_stations_radius': 'No rain gauge stations with coordinates found within {r} km radius. Increase radius.',
        'stations_found_count': '{n} rain gauge stations found within {r} km radius.',
    },
}


# ── Estado da sessão ──────────────────────────────────────────────────────────
def init_state():
    st.session_state.setdefault('ana_stations', [])   # [{codigo, nome, latitude, longitude, ...}]
    st.session_state.setdefault('ana_series_text', '')  # série baixada, formato manual
    st.session_state.setdefault('results', None)
    st.session_state.setdefault('report_ctx', {})
    st.session_state.setdefault('proj_lat', -23.0289)
    st.session_state.setdefault('proj_lon', -45.5569)
    st.session_state.setdefault('proj_loc', 'Taubaté - SP')
    st.session_state.setdefault('estacao_input', '')
    st.session_state.setdefault('search_radius_km', 35)
    st.session_state.setdefault('selection_mode', 'single')  # 'single' ou 'idw'
    st.session_state.setdefault('idw_meta', None)
    st.session_state.setdefault('last_clicked_coords', None)
    st.session_state.setdefault('uf_sel', 'SP')


init_state()


# ── Barra lateral: idioma ─────────────────────────────────────────────────────
lang_label = st.sidebar.radio('🌐 Idioma / Language', ['PT 🇧🇷', 'EN 🇺🇸'], horizontal=True)
lang = lang_label.split()[0]
L = UI[lang]

st.title(L['title'])
st.caption(L['subtitle'])

st.sidebar.header(L['sidebar_cfg'])

# ── Identificação ─────────────────────────────────────────────────────────────
with st.sidebar.expander('🏷️ ' + L['meta'], expanded=True):
    responsavel = st.text_input(L['resp'], value='Pedro Luis Soethe Cursino')
    localizacao = st.text_input(L['loc'], value=st.session_state.proj_loc)
    st.session_state.proj_loc = localizacao
    estacao = st.text_input(L['est'], value=st.session_state.estacao_input)
    st.session_state.estacao_input = estacao

# ── Fonte dos dados ───────────────────────────────────────────────────────────
st.sidebar.subheader('📂 ' + L['data_src'])
method = st.sidebar.radio(L['method'], [L['m_csv'], L['m_api'], L['m_manual']])

file_bytes = None
manual_text = None

if method == L['m_csv']:
    up = st.sidebar.file_uploader(L['upload'], type=['csv', 'txt'])
    if up is not None:
        file_bytes = up.getvalue()
        # tenta detectar o código da estação automaticamente
        try:
            code = parse_station_code(file_bytes)
            if code and not estacao:
                estacao = code
                st.sidebar.info(f'{L["est"]}: {code}')
        except Exception:
            pass

elif method == L['m_manual']:
    manual_text = st.sidebar.text_area(L['manual_lbl'], height=180, placeholder=L['manual_ph'])

elif method == L['m_api']:
    fonte = st.sidebar.radio(L['api_fonte'], [L['fonte_hist'], L['fonte_tele']])
    usar_historica = (fonte == L['fonte_hist'])
    st.sidebar.caption(L['hint_hist'] if usar_historica else L['api_hint'])

    # Busca de estações por UF disponível nas duas fontes: a histórica usa o
    # inventário legado (sem login); a telemétrica usa o inventário autenticado.
    uf = st.sidebar.selectbox(L['api_uf'], sorted(AnaHidroWebService.UFS_BRASIL))

    if st.sidebar.button(L['api_buscar'], use_container_width=True):
        try:
            with st.spinner(L['api_buscar']):
                if usar_historica:
                    estacoes = listar_estacoes_hist(uf)
                else:
                    estacoes = cliente_ana().listar_estacoes_por_uf(uf)
            if not estacoes:
                st.sidebar.warning(L['no_stations'])
            st.session_state.ana_stations = estacoes
        except UserError as e:
            st.sidebar.error(str(e))
        except Exception as e:
            st.sidebar.error(f'ANA: {e}')

    estacoes = st.session_state.ana_stations
    if estacoes:
        rotulos = [f"{e['codigo']} — {e['nome']}" for e in estacoes]
        escolha = st.sidebar.selectbox(L['api_sel_est'], rotulos)
        estacao = escolha.split(' — ')[0]

    # Código manual — alternativa direta à busca por UF (opcional em ambas as fontes).
    cod_manual = st.sidebar.text_input(L['api_cod_manual'], placeholder=L['api_cod_manual_ph'])
    if cod_manual.strip():
        estacao = cod_manual.strip()

    col_a, col_b = st.sidebar.columns(2)
    api_y0 = col_a.number_input(L['y0'], min_value=1900, max_value=2100, value=1990, step=1)
    api_y1 = col_b.number_input(L['y1'], min_value=1900, max_value=2100, value=2024, step=1)

    if st.sidebar.button(L['api_baixar'], type='primary', use_container_width=True):
        if not estacao:
            st.sidebar.warning(L['select_est_first'])
        else:
            barra = st.sidebar.progress(0.0)
            aviso = st.sidebar.empty()

            def _prog(feito, total, ano):
                barra.progress(feito / total)
                aviso.caption(f'{ano} ({feito}/{total})')

            try:
                with st.spinner(L['fetching']):
                    if usar_historica:
                        valores = buscar_serie_historica(estacao, int(api_y0), int(api_y1))
                    else:
                        cliente_ana()  # valida credenciais (levanta UserError se faltarem)
                        user_id, _ = ler_credenciais_ana()
                        valores = buscar_serie_ana(
                            user_id, estacao, int(api_y0), int(api_y1), _progresso=_prog)
                st.session_state.ana_series_text = '\n'.join(valores)
                aviso.empty()
                barra.empty()
                st.sidebar.success(L['fetch_ok'].format(n=len(valores)))
            except UserError as e:
                st.sidebar.error(str(e))
            except Exception as e:
                st.sidebar.error(f'ANA: {e}')

    if st.session_state.ana_series_text:
        manual_text = st.session_state.ana_series_text
        st.sidebar.caption(f"{L['series_loaded']}: "
                           f"{len(manual_text.splitlines())} {L['n_years'].lower()}")

# ── Filtro de período ─────────────────────────────────────────────────────────
with st.sidebar.expander('🗓️ ' + L['period'], expanded=False):
    usar_periodo = st.checkbox('Filtrar por período' if lang == 'PT' else 'Filter by period')
    year_start = year_end = None
    if usar_periodo:
        c0, c1 = st.columns(2)
        year_start = c0.number_input(L['y0'], min_value=1800, max_value=2100, value=1950, step=1)
        year_end = c1.number_input(L['y1'], min_value=1800, max_value=2100, value=2024, step=1)

# ── Parâmetros da região ──────────────────────────────────────────────────────
with st.sidebar.expander('🗺️ ' + L['region'], expanded=True):
    isozona = st.selectbox(L['isozona'], ISOZONAS, index=ISOZONAS.index('B'))
    c0, c1 = st.columns(2)
    latitude_sb = c0.number_input(L['lat'], value=float(st.session_state.proj_lat), format='%.4f')
    longitude_sb = c1.number_input(L['lon'], value=float(st.session_state.proj_lon), format='%.4f')
    if latitude_sb != st.session_state.proj_lat or longitude_sb != st.session_state.proj_lon:
        st.session_state.proj_lat = latitude_sb
        st.session_state.proj_lon = longitude_sb

# ── Botão principal ───────────────────────────────────────────────────────────
run = st.sidebar.button(L['run'], type='primary', use_container_width=True)

# ── Crédito na barra lateral ──────────────────────────────────────────────────
st.sidebar.markdown(
    f"<div style='color:#888; font-size:0.8em; padding-top:1rem;'>{L['footer']}</div>",
    unsafe_allow_html=True,
)


# ── Execução da análise ───────────────────────────────────────────────────────
def figuras(results):
    return (
        fig_historical_series(results['series_df'], lang),
        fig_gumbel_analysis(results['gumbel_df'], results['mu'], results['sigma'],
                            results['n_samples'], lang),
        fig_pdf_curves(results['disagg_df'], lang),
        fig_idf_curves(results['idf_df'], results['sherman_params'], lang),
    )


if run:
    try:
        with st.spinner(L['run']):
            results = run_full_analysis(
                file_bytes=file_bytes,
                manual_text=manual_text,
                isozona=isozona,
                lang=lang,
                year_start=int(year_start) if year_start else None,
                year_end=int(year_end) if year_end else None,
            )
        st.session_state.results = results
        st.session_state.report_ctx = {
            'responsavel': responsavel,
            'localizacao': localizacao,
            'estacao': estacao or '—',
            'lang': lang,
            'coords': (float(st.session_state.proj_lat), float(st.session_state.proj_lon)),
            'idw_meta': st.session_state.idw_meta,
        }
    except UserError as e:
        st.error(str(e))
        st.session_state.results = None
    except Exception as e:
        st.error(f'Erro na análise: {e}')
        st.session_state.results = None


# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO GEOESPACIAL: MAPA INTERATIVO, RAIO DE BUSCA E INTERPOLAÇÃO IDW
# ══════════════════════════════════════════════════════════════════════════════
if method == L['m_api']:
    with st.expander(L['map_title'], expanded=True):
        # 1. Campo de busca por endereço
        c_search, c_btn = st.columns([4, 1])
        endereco_digitado = c_search.text_input(
            L['search_addr_label'],
            value='',
            placeholder=L['search_addr_ph'],
            label_visibility='collapsed',
        )
        if c_btn.button(L['btn_search_addr'], use_container_width=True):
            if endereco_digitado.strip():
                with st.spinner("Buscando localização..."):
                    res_geo = geocodificar_local(endereco_digitado)
                    if res_geo:
                        lat_f, lon_f, addr_f = res_geo
                        st.session_state.proj_lat = round(lat_f, 4)
                        st.session_state.proj_lon = round(lon_f, 4)
                        uf_det, c_det, s_det = reverse_geocodificar(lat_f, lon_f)
                        if uf_det and uf_det in AnaHidroWebService.UFS_BRASIL:
                            st.session_state.uf_sel = uf_det
                        st.session_state.proj_loc = c_det + (f" - {uf_det}" if uf_det else "") or endereco_digitado
                        st.success(f"📍 {addr_f}")
                        st.rerun()
                    else:
                        st.warning("Endereço não localizado. Tente digitar o nome da cidade e estado (ex.: Taubaté, SP).")

        # 2. Controles de Coordenadas, Raio e UF do Inventário
        c_lat, c_lon, c_raio, c_uf = st.columns([2, 2, 3, 2])
        lat_val = c_lat.number_input(L['lat'], value=float(st.session_state.proj_lat), format="%.4f", step=0.01)
        lon_val = c_lon.number_input(L['lon'], value=float(st.session_state.proj_lon), format="%.4f", step=0.01)
        if lat_val != st.session_state.proj_lat or lon_val != st.session_state.proj_lon:
            st.session_state.proj_lat = lat_val
            st.session_state.proj_lon = lon_val
            st.rerun()

        raio_km = c_raio.slider(
            L['radius_label'],
            min_value=5,
            max_value=150,
            value=int(st.session_state.search_radius_km),
            step=5,
        )
        if raio_km != st.session_state.search_radius_km:
            st.session_state.search_radius_km = raio_km

        ufs_ordenadas = sorted(AnaHidroWebService.UFS_BRASIL)
        uf_atual = st.session_state.uf_sel
        idx_uf = ufs_ordenadas.index(uf_atual) if uf_atual in ufs_ordenadas else 0
        uf_escolhida = c_uf.selectbox("UF do Inventário ANA", ufs_ordenadas, index=idx_uf)
        if uf_escolhida != uf_atual:
            st.session_state.uf_sel = uf_escolhida
            st.rerun()

        # 3. Carregamento do Inventário da UF selecionada
        with st.spinner("Carregando inventário de estações da ANA..."):
            try:
                if usar_historica:
                    estacoes_uf = listar_estacoes_hist(uf_escolhida)
                else:
                    estacoes_uf = cliente_ana().listar_estacoes_por_uf(uf_escolhida)
            except Exception as exc:
                st.error(f"Falha ao obter inventário da ANA: {exc}")
                estacoes_uf = []

        # 4. Filtragem das estações no raio especificado
        estacoes_no_raio = filtrar_estacoes_por_raio(
            st.session_state.proj_lat,
            st.session_state.proj_lon,
            estacoes_uf,
            raio_km=st.session_state.search_radius_km,
        )

        # 5. Renderização do Mapa com Folium
        m = folium.Map(
            location=[st.session_state.proj_lat, st.session_state.proj_lon],
            zoom_start=10,
            tiles='OpenStreetMap',
        )

        # Marcador Vermelho: Local do Projeto
        folium.Marker(
            [st.session_state.proj_lat, st.session_state.proj_lon],
            popup=f"<b>Local do Projeto</b><br>Lat: {st.session_state.proj_lat:.4f}<br>Lon: {st.session_state.proj_lon:.4f}",
            tooltip="Local do Projeto",
            icon=folium.Icon(color='red', icon='info-sign'),
        ).add_to(m)

        # Círculo Azul de Raio (Buffer em metros)
        folium.Circle(
            location=[st.session_state.proj_lat, st.session_state.proj_lon],
            radius=st.session_state.search_radius_km * 1000,
            color='#1a5276',
            weight=2,
            fill=True,
            fill_color='#2980b9',
            fill_opacity=0.15,
            tooltip=f"Raio de busca: {st.session_state.search_radius_km} km",
        ).add_to(m)

        # Marcadores Verdes: Estações Pluviométricas no Raio
        for est in estacoes_no_raio:
            dist_km = est['distancia_km']
            cod = est['codigo']
            nome = est['nome']
            mun = est.get('municipio', '')
            pop_html = f"""
            <div style='font-family:sans-serif; min-width:180px;'>
                <b style='color:#1a5276;'>{cod} — {nome}</b><br>
                <b>Município:</b> {mun}<br>
                <b>Distância:</b> {dist_km:.2f} km<br>
                <b>Coordenadas:</b> {est['latitude']:.4f}, {est['longitude']:.4f}
            </div>
            """
            folium.Marker(
                [est['latitude'], est['longitude']],
                popup=folium.Popup(pop_html, max_width=260),
                tooltip=f"Estação {cod} — {nome} ({dist_km:.1f} km)",
                icon=folium.Icon(color='green', icon='tint'),
            ).add_to(m)

        st.caption(L['click_hint'])
        map_out = st_folium(m, height=430, use_container_width=True, returned_objects=["last_clicked"])

        # Detecta clique no mapa para atualizar localização do projeto
        if map_out and map_out.get("last_clicked"):
            c_lat = round(map_out["last_clicked"]["lat"], 4)
            c_lon = round(map_out["last_clicked"]["lng"], 4)
            if st.session_state.last_clicked_coords != (c_lat, c_lon):
                st.session_state.last_clicked_coords = (c_lat, c_lon)
                st.session_state.proj_lat = c_lat
                st.session_state.proj_lon = c_lon
                uf_det, c_det, s_det = reverse_geocodificar(c_lat, c_lon)
                if uf_det and uf_det in AnaHidroWebService.UFS_BRASIL:
                    st.session_state.uf_sel = uf_det
                if c_det:
                    st.session_state.proj_loc = f"{c_det} - {uf_det or s_det}"
                st.rerun()

        # 6. Seleção de Estações (Mais Próxima vs. Interpolação IDW)
        if not estacoes_no_raio:
            st.warning(L['no_stations_radius'].format(r=st.session_state.search_radius_km))
        else:
            st.info(L['stations_found_count'].format(n=len(estacoes_no_raio), r=st.session_state.search_radius_km))

            modo = st.radio(
                L['mode_label'],
                [L['mode_single'], L['mode_idw']],
                horizontal=True,
                index=0 if st.session_state.selection_mode == 'single' else 1,
            )
            st.session_state.selection_mode = 'single' if modo == L['mode_single'] else 'idw'

            if st.session_state.selection_mode == 'single':
                opcoes_est = [f"{e['codigo']} — {e['nome']} ({e['distancia_km']:.1f} km)" for e in estacoes_no_raio]
                escolha_est = st.selectbox(L['closest_station'], opcoes_est, index=0)
                cod_sel = escolha_est.split(" — ")[0]
                est_obj = next(e for e in estacoes_no_raio if e['codigo'] == cod_sel)

                if st.button(L['btn_download_single'], type='primary', use_container_width=True):
                    try:
                        with st.spinner(L['fetching']):
                            if usar_historica:
                                valores = buscar_serie_historica(cod_sel, int(api_y0), int(api_y1))
                            else:
                                cliente_ana()
                                user_id, _ = ler_credenciais_ana()
                                valores = buscar_serie_ana(user_id, cod_sel, int(api_y0), int(api_y1))
                        st.session_state.ana_series_text = '\n'.join(valores)
                        st.session_state.estacao_input = f"{cod_sel} ({est_obj['nome']})"
                        st.session_state.idw_meta = None
                        st.success(L['fetch_ok'].format(n=len(valores)))
                        st.rerun()
                    except UserError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error(f'ANA: {e}')

            else:
                # Modo IDW: Multiselect de estações + cálculo de pesos em tempo real
                mapa_opcoes = {f"{e['codigo']} — {e['nome']} ({e['distancia_km']:.1f} km)": e for e in estacoes_no_raio}
                padrao_keys = list(mapa_opcoes.keys())[:min(3, len(mapa_opcoes))]

                selecionadas_keys = st.multiselect(
                    L['idw_stations_select'],
                    options=list(mapa_opcoes.keys()),
                    default=padrao_keys,
                )

                if selecionadas_keys:
                    estacoes_sel = [mapa_opcoes[k] for k in selecionadas_keys]
                    dists_map = {e['codigo']: e['distancia_km'] for e in estacoes_sel}

                    # Calcula pesos IDW nominais para visualização na tabela
                    invs = {c: (1.0 / max(d, 0.1)) ** 2 for c, d in dists_map.items()}
                    soma_inv = sum(invs.values())
                    pesos_preview = {c: round((invs[c] / soma_inv) * 100.0, 1) for c in dists_map}

                    df_preview_idw = pd.DataFrame([
                        {
                            L['geo_station_code']: e['codigo'],
                            L['geo_station_name']: e['nome'],
                            L['geo_distance_km']: f"{e['distancia_km']:.2f} km",
                            L['geo_weight_pct']: f"{pesos_preview[e['codigo']]:.1f}%",
                        }
                        for e in estacoes_sel
                    ])
                    st.dataframe(df_preview_idw, use_container_width=True, hide_index=True)

                    if st.button(L['btn_download_idw'], type='primary', use_container_width=True):
                        try:
                            series_dict = {}
                            barra_dl = st.progress(0.0)
                            aviso_dl = st.empty()
                            total_sel = len(estacoes_sel)

                            for idx_est, est_item in enumerate(estacoes_sel):
                                c_code = est_item['codigo']
                                aviso_dl.caption(f"Baixando dados da estação {c_code} — {est_item['nome']}...")
                                if usar_historica:
                                    df_est = buscar_dataframe_historico(c_code, int(api_y0), int(api_y1))
                                else:
                                    cliente_ana()
                                    user_id, _ = ler_credenciais_ana()
                                    df_est = buscar_dataframe_ana(user_id, c_code, int(api_y0), int(api_y1))

                                if df_est is not None and not df_est.empty:
                                    series_dict[c_code] = df_est
                                barra_dl.progress((idx_est + 1) / total_sel)

                            aviso_dl.empty()
                            barra_dl.empty()

                            # Interpola via IDW
                            df_interp, pesos_finais = interpolar_series_idw(series_dict, dists_map, p=2.0)
                            st.session_state.ana_series_text = '\n'.join(df_interp['Precipitacao'].astype(str).tolist())
                            codigos_str = ', '.join(series_dict.keys())
                            st.session_state.estacao_input = f"IDW ({codigos_str})"

                            # Metadados de IDW para os relatórios
                            st.session_state.idw_meta = {
                                'stations': [
                                    {
                                        'codigo': e['codigo'],
                                        'nome': e['nome'],
                                        'distancia_km': e['distancia_km'],
                                        'peso_pct': pesos_finais.get(e['codigo'], 0.0) * 100.0,
                                    }
                                    for e in estacoes_sel if e['codigo'] in series_dict
                                ],
                                'coords': (st.session_state.proj_lat, st.session_state.proj_lon),
                            }
                            st.success(L['idw_success'].format(n=len(series_dict), anos=len(df_interp)))
                            st.rerun()
                        except UserError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f'Erro no download/interpolação IDW: {e}')


# ── Apresentação dos resultados ───────────────────────────────────────────────
results = st.session_state.results

if not results:
    st.info(L['no_data_yet'])
else:
    fh, fg, fp, fi = figuras(results)

    sherman = results['sherman_params']
    n = results['n_samples']
    m1, m2, m3 = st.columns(3)
    m1.metric(L['n_years'], n)
    m2.metric('μ (Gumbel)', f"{results['mu']:.2f}")
    m3.metric('σ (Gumbel)', f"{results['sigma']:.2f}")

    tabs = st.tabs([L['tab_serie'], L['tab_gumbel'], L['tab_pdf'], L['tab_idf'],
                    L['tab_tables'], L['tab_sherman']])

    with tabs[0]:
        st.plotly_chart(fh, use_container_width=True)
        st.dataframe(results['series_df'], use_container_width=True, hide_index=True)

    with tabs[1]:
        st.plotly_chart(fg, use_container_width=True)
        st.dataframe(results['gumbel_df'], use_container_width=True, hide_index=True)

    with tabs[2]:
        st.plotly_chart(fp, use_container_width=True)
        st.dataframe(results['disagg_df'], use_container_width=True, hide_index=True)

    with tabs[3]:
        st.plotly_chart(fi, use_container_width=True)
        st.dataframe(results['idf_df'], use_container_width=True, hide_index=True)

    with tabs[4]:
        st.markdown(f"**{L['tab_serie']}**")
        st.dataframe(results['series_df'], use_container_width=True, hide_index=True)
        st.markdown(f"**{L['tab_gumbel']}**")
        st.dataframe(results['gumbel_df'], use_container_width=True, hide_index=True)
        st.markdown(f"**{L['tab_idf']}**")
        st.dataframe(results['idf_df'], use_container_width=True, hide_index=True)

    with tabs[5]:
        A, B, C, D = sherman['A'], sherman['B'], sherman['C'], sherman['D']
        st.markdown(f"### {L['sherman_eq']}")
        st.latex(r"i = \frac{%.4f \cdot T^{%.4f}}{(t + %.4f)^{%.4f}}" % (A, B, C, D))
        st.markdown(f"**{L['params']}**")
        st.json({'A': round(A, 4), 'B': round(B, 4), 'C': round(C, 4), 'D': round(D, 4)})
        g1, g2, g3 = st.columns(3)
        if 'R²' in sherman:
            g1.metric('R²', f"{sherman['R²']:.4f}")
        if 'RMSE' in sherman:
            g2.metric('RMSE', f"{sherman['RMSE']:.3f}")
        if 'NSE' in sherman:
            g3.metric('NSE', f"{sherman['NSE']:.4f}")

    # ── Downloads ─────────────────────────────────────────────────────────────
    st.divider()
    st.subheader(L['downloads'])
    ctx = st.session_state.report_ctx
    d1, d2 = st.columns(2)

    with d1:
        try:
            pdf_bytes = generate_pdf_report(
                results, ctx['responsavel'], ctx['localizacao'], ctx['estacao'],
                fh, fg, fp, fi, lang=lang,
                coords=ctx.get('coords'), idw_meta=ctx.get('idw_meta'),
            )
            st.download_button(L['dl_pdf'], data=pdf_bytes,
                               file_name='memorial_calculo_idf.pdf',
                               mime='application/pdf', use_container_width=True)
        except Exception as e:
            st.warning(f'PDF: {e}')

    with d2:
        try:
            docx_bytes = generate_word_report(
                results, ctx['responsavel'], ctx['localizacao'], ctx['estacao'],
                fh, fg, fp, fi, lang=lang,
                coords=ctx.get('coords'), idw_meta=ctx.get('idw_meta'),
            )
            st.download_button(
                L['dl_word'], data=docx_bytes,
                file_name='memorial_calculo_idf.docx',
                mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                use_container_width=True)
        except Exception as e:
            st.warning(f'Word: {e}')

# ── Rodapé / créditos ─────────────────────────────────────────────────────────
st.divider()
st.markdown(
    f"<div style='text-align:center; color:#888; font-size:0.85em; padding:0.5rem 0;'>"
    f"{L['footer']}</div>",
    unsafe_allow_html=True,
)
