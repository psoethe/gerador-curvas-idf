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
from folium.plugins import Fullscreen, Draw
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import pandas as pd
import unicodedata

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
def buscar_serie_historica(estacao: str, y0: int = None, y1: int = None) -> list[str]:
    """
    Busca a série anual pelo webservice histórico da ANA (estações convencionais).
    Se y0 e y1 forem omitidos, baixa todo o período histórico disponível da estação.
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
def buscar_dataframe_historico(estacao: str, y0: int = None, y1: int = None) -> pd.DataFrame:
    """
    Retorna o DataFrame anual de máximas do webservice histórico.
    Se y0 e y1 forem omitidos, baixa toda a série histórica completa disponível.
    """
    return obter_serie_chuva_historica(estacao, y0, y1)


@st.cache_data(show_spinner=False, ttl=3600)
def listar_estacoes_hist(uf: str) -> list:
    """Lista estações pluviométricas de uma UF pelo inventário legado (sem login)."""
    return listar_estacoes_historicas(uf)


def _remover_acentos(texto: str) -> str:
    """Remove acentos e converte para minúsculas para matching resiliente."""
    return ''.join(c for c in unicodedata.normalize('NFD', str(texto))
                   if unicodedata.category(c) != 'Mn').lower().strip()


# Base instantânea das 27 capitais e principais cidades do Brasil (sem necessidade de rede)
CIDADES_BRASIL = {
    'recife': (-8.0476, -34.8770, 'Recife, PE, Brasil', 'PE'),
    'sao paulo': (-23.5505, -46.6333, 'São Paulo, SP, Brasil', 'SP'),
    'rio de janeiro': (-22.9068, -43.1729, 'Rio de Janeiro, RJ, Brasil', 'RJ'),
    'salvador': (-12.9777, -38.5016, 'Salvador, BA, Brasil', 'BA'),
    'fortaleza': (-3.7319, -38.5267, 'Fortaleza, CE, Brasil', 'CE'),
    'belo horizonte': (-19.9167, -43.9345, 'Belo Horizonte, MG, Brasil', 'MG'),
    'brasilia': (-15.7975, -47.8919, 'Brasília, DF, Brasil', 'DF'),
    'curitiba': (-25.4284, -49.2733, 'Curitiba, PR, Brasil', 'PR'),
    'manaus': (-3.1190, -60.0217, 'Manaus, AM, Brasil', 'AM'),
    'belem': (-1.4558, -48.4902, 'Belém, PA, Brasil', 'PA'),
    'porto alegre': (-30.0346, -51.2177, 'Porto Alegre, RS, Brasil', 'RS'),
    'goiania': (-16.6869, -49.2648, 'Goiânia, GO, Brasil', 'GO'),
    'sao luis': (-2.5307, -44.3068, 'São Luís, MA, Brasil', 'MA'),
    'maceio': (-9.6658, -35.7351, 'Maceió, AL, Brasil', 'AL'),
    'natal': (-5.7945, -35.2110, 'Natal, RN, Brasil', 'RN'),
    'campo grande': (-20.4697, -54.6201, 'Campo Grande, MS, Brasil', 'MS'),
    'teresina': (-5.0920, -42.8038, 'Teresina, PI, Brasil', 'PI'),
    'joao pessoa': (-7.1195, -34.8450, 'João Pessoa, PB, Brasil', 'PB'),
    'aracaju': (-10.9472, -37.0731, 'Aracaju, SE, Brasil', 'SE'),
    'cuiaba': (-15.6014, -56.0979, 'Cuiabá, MT, Brasil', 'MT'),
    'porto velho': (-8.7619, -63.9039, 'Porto Velho, RO, Brasil', 'RO'),
    'florianopolis': (-27.5954, -48.5480, 'Florianópolis, SC, Brasil', 'SC'),
    'macapa': (0.0389, -51.0664, 'Macapá, AP, Brasil', 'AP'),
    'rio branco': (-9.9753, -67.8249, 'Rio Branco, AC, Brasil', 'AC'),
    'vitoria': (-20.3155, -40.3128, 'Vitória, ES, Brasil', 'ES'),
    'boa vista': (2.8235, -60.6758, 'Boa Vista, RR, Brasil', 'RR'),
    'palmas': (-10.2491, -48.3243, 'Palmas, TO, Brasil', 'TO'),
    'campinas': (-22.9099, -47.0626, 'Campinas, SP, Brasil', 'SP'),
    'taubate': (-23.0289, -45.5569, 'Taubaté, SP, Brasil', 'SP'),
    'sao jose dos campos': (-23.1791, -45.8872, 'São José dos Campos, SP, Brasil', 'SP'),
    'sorocaba': (-23.5015, -47.4526, 'Sorocaba, SP, Brasil', 'SP'),
    'ribeirao preto': (-21.1767, -47.8108, 'Ribeirão Preto, SP, Brasil', 'SP'),
    'uberlandia': (-18.9186, -48.2772, 'Uberlândia, MG, Brasil', 'MG'),
    'juiz de fora': (-21.7587, -43.3496, 'Juiz de Fora, MG, Brasil', 'MG'),
    'londrina': (-23.3045, -51.1696, 'Londrina, PR, Brasil', 'PR'),
    'maringa': (-23.4209, -51.9331, 'Maringá, PR, Brasil', 'PR'),
    'joinville': (-26.3045, -48.8487, 'Joinville, SC, Brasil', 'SC'),
    'caxias do sul': (-29.1678, -51.1794, 'Caxias do Sul, RS, Brasil', 'RS'),
    'pelotas': (-31.7654, -52.3376, 'Pelotas, RS, Brasil', 'RS'),
    'niteroi': (-22.8833, -43.1036, 'Niterói, RJ, Brasil', 'RJ'),
    'santos': (-23.9608, -46.3331, 'Santos, SP, Brasil', 'SP'),
    'caruaru': (-8.2837, -35.9754, 'Caruaru, PE, Brasil', 'PE'),
    'petrolina': (-9.3989, -40.5008, 'Petrolina, PE, Brasil', 'PE'),
    'campina grande': (-7.2307, -35.8817, 'Campina Grande, PB, Brasil', 'PB'),
    'feira de santana': (-12.2664, -38.9663, 'Feira de Santana, BA, Brasil', 'BA'),
    'vitoria da conquista': (-14.8661, -40.8394, 'Vitória da Conquista, BA, Brasil', 'BA'),
    'anapolis': (-16.3268, -48.9534, 'Anápolis, GO, Brasil', 'GO'),
}


@st.cache_data(show_spinner=False, ttl=86400)
def geocodificar_local(query: str):
    """Geocodifica endereço ou município brasileiro via base interna e OpenStreetMap Nominatim."""
    q_norm = _remover_acentos(query)
    
    # 1. Busca rápida na base de cidades conhecidas (ex.: 'recife', 'recife, pe', 'recife - pe')
    q_limpa = q_norm.split(',')[0].split('-')[0].strip()
    if q_limpa in CIDADES_BRASIL:
        lat, lon, addr, _ = CIDADES_BRASIL[q_limpa]
        return float(lat), float(lon), addr
    if q_norm in CIDADES_BRASIL:
        lat, lon, addr, _ = CIDADES_BRASIL[q_norm]
        return float(lat), float(lon), addr

    # 2. Busca via Nominatim do OpenStreetMap
    try:
        geo = Nominatim(user_agent="idf_curves_brasil_app_v2", timeout=12)
        q = query.strip()
        loc = geo.geocode(q, country_codes="br")
        if not loc and "brasil" not in q.lower() and "brazil" not in q.lower():
            loc = geo.geocode(f"{q}, Brasil")
        if not loc:
            loc = geo.geocode(q)
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


# Centróides das 27 UFs para fallback geográfico instantâneo e offline
CENTROIDES_UF = {
    'AC': (-9.97, -67.81), 'AL': (-9.66, -35.73), 'AP': (0.03, -51.06), 'AM': (-3.11, -60.02),
    'BA': (-12.97, -38.51), 'CE': (-3.73, -38.52), 'DF': (-15.79, -47.88), 'ES': (-20.31, -40.33),
    'GO': (-16.68, -49.25), 'MA': (-2.53, -44.30), 'MT': (-15.60, -56.09), 'MS': (-20.46, -54.62),
    'MG': (-19.92, -43.93), 'PA': (-1.45, -48.50), 'PB': (-7.11, -34.86), 'PR': (-25.42, -49.27),
    'PE': (-8.05, -34.88), 'PI': (-5.08, -42.80), 'RJ': (-22.90, -43.17), 'RN': (-5.79, -35.20),
    'RS': (-30.03, -51.22), 'RO': (-8.76, -63.90), 'RR': (2.82, -60.67), 'SC': (-27.59, -48.54),
    'SP': (-23.55, -46.63), 'SE': (-10.94, -37.07), 'TO': (-10.18, -48.33),
}


def detectar_uf_offline(lat: float, lon: float) -> str:
    """Identifica a UF brasileira mais próxima das coordenadas por proximidade geográfica."""
    melhor_uf = 'SP'
    menor_d = float('inf')
    for uf, (c_lat, c_lon) in CENTROIDES_UF.items():
        d = (lat - c_lat) ** 2 + (lon - c_lon) ** 2
        if d < menor_d:
            menor_d = d
            melhor_uf = uf
    return melhor_uf


def detectar_uf_coordenadas(lat: float, lon: float) -> tuple[str, str]:
    """Detecta a UF e o nome do local via geocodificação reversa com fallback offline."""
    uf_det, c_det, s_det = reverse_geocodificar(lat, lon)
    if uf_det and uf_det in AnaHidroWebService.UFS_BRASIL:
        loc_str = f"{c_det} - {uf_det}" if c_det else f"Ponto em {uf_det}"
        return uf_det, loc_str
    # Fallback geográfico
    uf_fb = detectar_uf_offline(lat, lon)
    return uf_fb, f"Ponto em {uf_fb}"


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
    st.session_state.setdefault('download_info', None)


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
                        df_baixado = buscar_dataframe_historico(estacao)
                    else:
                        cliente_ana()  # valida credenciais (levanta UserError se faltarem)
                        user_id, _ = ler_credenciais_ana()
                        df_baixado = buscar_dataframe_ana(
                            user_id, estacao, 1970, 2025)

                aviso.empty()
                barra.empty()

                if df_baixado is None or df_baixado.empty:
                    st.sidebar.warning(f"A estação {estacao} não possui registros de chuva na base da ANA.")
                else:
                    valores = df_baixado['Precipitacao'].astype(str).tolist()
                    anos_disp = sorted(df_baixado['Ano'].dropna().unique().astype(int))
                    ano_ini, ano_fim = anos_disp[0], anos_disp[-1]
                    n_anos = len(anos_disp)
                    msg_anos = f"{n_anos} anos ({ano_ini} a {ano_fim})"
                    st.session_state.ana_series_text = '\n'.join(valores)
                    st.session_state.download_info = {
                        'tipo': 'single', 'cod': estacao, 'nome': '',
                        'n_anos': n_anos, 'ano_ini': ano_ini, 'ano_fim': ano_fim,
                    }
                    st.sidebar.success(f"Série baixada: {msg_anos}.")
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
        # 1. Campo de busca por endereço com st.form (permite submissão com tecla ENTER)
        with st.form("form_busca_endereco", clear_on_submit=False):
            c_search, c_btn = st.columns([4, 1])
            endereco_digitado = c_search.text_input(
                L['search_addr_label'],
                value='',
                placeholder=L['search_addr_ph'],
                label_visibility='collapsed',
            )
            submitted = c_btn.form_submit_button(L['btn_search_addr'], use_container_width=True)

        if submitted and endereco_digitado.strip():
            with st.spinner("Buscando localização..."):
                res_geo = geocodificar_local(endereco_digitado)
                if res_geo:
                    lat_f, lon_f, addr_f = res_geo
                    st.session_state.proj_lat = round(lat_f, 4)
                    st.session_state.proj_lon = round(lon_f, 4)
                    nova_uf, novo_loc = detectar_uf_coordenadas(lat_f, lon_f)
                    st.session_state.uf_sel = nova_uf
                    st.session_state.proj_loc = (
                        endereco_digitado.strip() + (f" - {nova_uf}" if nova_uf not in endereco_digitado else "")
                    )
                    st.success(f"📍 {addr_f} (Estado detectado: **{nova_uf}**)")
                    st.rerun()
                else:
                    st.warning("Endereço não localizado. Tente digitar o nome da cidade e estado (ex.: Recife, PE ou Taubaté, SP).")

        # 2. Controles de Coordenadas, Raio, UF e Botão para Fixar Pin
        c_lat, c_lon, c_raio, c_uf, c_pin = st.columns([2, 2, 2.5, 2, 1.5])
        lat_val = c_lat.number_input(L['lat'], value=float(st.session_state.proj_lat), format="%.4f", step=0.01)
        lon_val = c_lon.number_input(L['lon'], value=float(st.session_state.proj_lon), format="%.4f", step=0.01)
        if lat_val != st.session_state.proj_lat or lon_val != st.session_state.proj_lon:
            st.session_state.proj_lat = lat_val
            st.session_state.proj_lon = lon_val
            nova_uf, novo_loc = detectar_uf_coordenadas(lat_val, lon_val)
            st.session_state.uf_sel = nova_uf
            st.session_state.proj_loc = novo_loc
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

        if c_pin.button("📍 Fixar Pin", use_container_width=True, help="Centraliza o pin no mapa e atualiza a busca"):
            st.rerun()

        # 3. Carregamento do Inventário da UF selecionada
        with st.spinner(f"Carregando inventário de estações da ANA ({st.session_state.uf_sel})..."):
            try:
                if usar_historica:
                    estacoes_uf = listar_estacoes_hist(st.session_state.uf_sel)
                else:
                    estacoes_uf = cliente_ana().listar_estacoes_por_uf(st.session_state.uf_sel)
            except Exception as exc:
                st.error(f"Falha ao obter inventário da ANA: {exc}")
                estacoes_uf = []

        # 4. Filtragem das estações no raio especificado (ordenadas por distância crescente)
        estacoes_no_raio = filtrar_estacoes_por_raio(
            st.session_state.proj_lat,
            st.session_state.proj_lon,
            estacoes_uf,
            raio_km=st.session_state.search_radius_km,
        )

        # Informação visual do ponto de projeto
        st.markdown(
            f"📍 **Local do Projeto:** Lat `{st.session_state.proj_lat:.4f}` | "
            f"Lon `{st.session_state.proj_lon:.4f}` — *{st.session_state.proj_loc}* "
            f"(Inventário da ANA: **{st.session_state.uf_sel}**)"
        )

        # 5. Renderização do Mapa com Folium (Ferramenta de Pin, Camadas compactas, Zoom e Escala)
        m = folium.Map(
            location=[st.session_state.proj_lat, st.session_state.proj_lon],
            zoom_start=10,
            tiles=None,
            control_scale=True,
        )

        # Camadas base selecionáveis pelo usuário
        folium.TileLayer('OpenStreetMap', name='🗺️ Padrão (OSM)').add_to(m)
        folium.TileLayer('CartoDB positron', name='⚪ Claro (Positron)').add_to(m)
        folium.TileLayer('CartoDB dark_matter', name='⚫ Escuro (Dark)').add_to(m)
        folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attr='Esri World Imagery',
            name='🛰️ Satélite (Esri)',
        ).add_to(m)
        folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
            attr='Esri World Topo',
            name='⛰️ Relevo (Topo)',
        ).add_to(m)

        # Ferramentas: Tela Cheia e Controle de Desenho com Botão de Pin
        Fullscreen(position='topleft').add_to(m)
        Draw(
            export=False,
            position='topleft',
            draw_options={
                'polyline': False,
                'polygon': False,
                'circle': False,
                'rectangle': False,
                'circlemarker': False,
                'marker': True,
            },
            edit_options={'edit': False, 'remove': False},
        ).add_to(m)

        # Controle de Camadas com escala 50% menor aplicada via CSS
        folium.LayerControl(position='topright', collapsed=False).add_to(m)
        css_layers_compact = """
        <style>
        .leaflet-control-layers {
            transform: scale(0.52) !important;
            transform-origin: top right !important;
            font-size: 10px !important;
            padding: 3px 6px !important;
            border-radius: 4px !important;
            box-shadow: 0 1px 4px rgba(0,0,0,0.3) !important;
        }
        .leaflet-control-layers label {
            font-size: 10px !important;
            margin-bottom: 2px !important;
            cursor: pointer;
        }
        </style>
        """
        m.get_root().html.add_child(folium.Element(css_layers_compact))

        # Marcador Vermelho: Local do Projeto
        folium.Marker(
            [st.session_state.proj_lat, st.session_state.proj_lon],
            popup=f"<b>📍 Local do Projeto</b><br>Lat: {st.session_state.proj_lat:.4f}<br>Lon: {st.session_state.proj_lon:.4f}<br>{st.session_state.proj_loc}",
            tooltip="📍 Local do Projeto (Clique no botão de marcador ou em qualquer ponto do mapa para reposicionar)",
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

        # Marcadores das Estações: A mais próxima em AZUL com estrela, as demais em VERDE
        for idx, est in enumerate(estacoes_no_raio):
            is_closest = (idx == 0)
            dist_km = est['distancia_km']
            cod = est['codigo']
            nome = est['nome']
            mun = est.get('municipio', '')

            if is_closest:
                pop_html = f"""
                <div style='font-family:sans-serif; min-width:190px;'>
                    <span style='background:#0d6efd; color:white; padding:2px 6px; border-radius:4px; font-size:11px; font-weight:bold;'>⭐ MAIS PRÓXIMA</span><br>
                    <b style='color:#0d6efd; font-size:13px;'>{cod} — {nome}</b><br>
                    <b>Município:</b> {mun}<br>
                    <b>Distância:</b> <span style='color:#0d6efd; font-weight:bold;'>{dist_km:.2f} km</span><br>
                    <b>Coordenadas:</b> {est['latitude']:.4f}, {est['longitude']:.4f}
                </div>
                """
                folium.Marker(
                    [est['latitude'], est['longitude']],
                    popup=folium.Popup(pop_html, max_width=280),
                    tooltip=f"⭐ [MAIS PRÓXIMA - {dist_km:.1f} km] {cod} — {nome}",
                    icon=folium.Icon(color='blue', icon='star'),
                ).add_to(m)
            else:
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

        st.caption("💡 Dica: Clique no botão 📍 no canto superior esquerdo do mapa ou clique em qualquer ponto para reposicionar o pin do projeto.")
        map_out = st_folium(m, height=450, use_container_width=True, returned_objects=["last_clicked", "last_active_drawing"])

        # Detecta clique no mapa ou posicionamento de marcador via Draw
        novo_ponto = None
        if map_out and map_out.get("last_active_drawing"):
            geom = map_out["last_active_drawing"].get("geometry", {})
            if geom.get("type") == "Point":
                coords = geom.get("coordinates", [])
                if len(coords) >= 2:
                    novo_ponto = (round(coords[1], 4), round(coords[0], 4))

        if not novo_ponto and map_out and map_out.get("last_clicked"):
            novo_ponto = (round(map_out["last_clicked"]["lat"], 4), round(map_out["last_clicked"]["lng"], 4))

        if novo_ponto and st.session_state.last_clicked_coords != novo_ponto:
            st.session_state.last_clicked_coords = novo_ponto
            c_lat, c_lon = novo_ponto
            st.session_state.proj_lat = c_lat
            st.session_state.proj_lon = c_lon

            # Identifica a UF e localização imediatamente
            nova_uf, novo_loc = detectar_uf_coordenadas(c_lat, c_lon)
            st.session_state.uf_sel = nova_uf
            st.session_state.proj_loc = novo_loc
            st.rerun()

        # Banner de feedback dos dados baixados (mostra anos disponíveis e intervalo)
        if st.session_state.get('download_info'):
            dinfo = st.session_state.download_info
            if dinfo.get('tipo') == 'idw':
                st.success(
                    f"✅ **Série sintética IDW gerada com sucesso!**\n\n"
                    f"- **Estações combinadas:** {dinfo['n_est']}\n"
                    f"- **Período disponível na ANA:** **{dinfo['ano_ini']} a {dinfo['ano_fim']}** ({dinfo['n_anos']} anos com dados)\n"
                    f"- 💡 *Dica:* Toda a base histórica disponível foi baixada. Caso deseje restringir o período de cálculo (ex.: últimos 30 anos), utilize o **'🗓️ Filtro de Período'** na barra lateral."
                )
            else:
                st.success(
                    f"✅ **Série histórica completa baixada com sucesso!**\n\n"
                    f"- **Estação:** `{dinfo['cod']}` — {dinfo.get('nome', '')}\n"
                    f"- **Período disponível na ANA:** **{dinfo['ano_ini']} a {dinfo['ano_fim']}** ({dinfo['n_anos']} anos com dados)\n"
                    f"- 💡 *Dica:* Toda a base histórica disponível foi baixada. Caso deseje restringir o período de cálculo (ex.: últimos 30 anos), utilize o **'🗓️ Filtro de Período'** na barra lateral."
                )

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

            # ── Metodologia IDW (Fonte ~30% menor) ──────────────────────────────────
            if st.session_state.selection_mode == 'idw':
                with st.container(border=True):
                    st.markdown(
                        """
                        <div style="font-size: 0.72rem; line-height: 1.4; color: #333;">
                            <div style="font-weight: bold; font-size: 0.85rem; margin-bottom: 6px; color: #1a5276;">
                                📐 Metodologia de Interpolação Multi-estação (IDW — Inverse Distance Weighting)
                            </div>
                            <p style="margin-bottom: 6px;">
                                O método da <b>Ponderação pelo Inverso da Distância (IDW)</b> estima chuvas pontuais a partir das estações vizinhas adotando o inverso do quadrado da distância:
                            </p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    st.latex(r"w_i = \frac{1 / d_i^2}{\sum_{k=1}^m \frac{1}{d_k^2}}")
                    st.markdown(
                        r"""
                        <div style="font-size: 0.72rem; line-height: 1.4; color: #333;">
                            <b>Onde:</b>
                            <ul style="margin-top: 2px; margin-bottom: 6px; padding-left: 18px;">
                                <li><b>d<sub>i</sub>:</b> distância geodésica da estação <i>i</i> até o ponto do projeto (km).</li>
                                <li><b>p:</b> expoente da distância adotado (<i>p = 2</i>, inverso do quadrado).</li>
                                <li><b>w<sub>i</sub>:</b> peso relativo ponderado da estação (\(\sum w_i = 100\%\)).</li>
                            </ul>
                            <b>Procedimento Hidrológico:</b>
                            <ol style="margin-top: 2px; margin-bottom: 4px; padding-left: 18px;">
                                <li><b>Ponderação Ano a Ano:</b> Para cada ano civil das séries históricas, a precipitação máxima anual no ponto do projeto é estimada pela soma ponderada: \(P_{\text{proj}}(t) = \sum w_i^*(t) \cdot P_i(t)\).</li>
                                <li><b>Re-normalização Dinâmica:</b> Se uma estação não operou em determinado ano civil, os pesos \(w_i^*(t)\) são re-normalizados automaticamente entre as estações ativas remanescentes.</li>
                                <li><b>Série Sintética Local:</b> A série ponderada resultante reflete as precipitações na coordenada exata da obra e alimenta o ajuste de Gumbel, Taborga e a equação de Sherman.</li>
                            </ol>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            if st.session_state.selection_mode == 'single':
                opcoes_est = [
                    f"{'⭐ ' if i == 0 else ''}{e['codigo']} — {e['nome']} ({e['distancia_km']:.1f} km)"
                    for i, e in enumerate(estacoes_no_raio)
                ]
                escolha_est = st.selectbox(L['closest_station'], opcoes_est, index=0)
                cod_sel = escolha_est.replace('⭐ ', '').split(" — ")[0]
                est_obj = next(e for e in estacoes_no_raio if e['codigo'] == cod_sel)

                if st.button(L['btn_download_single'], type='primary', use_container_width=True):
                    try:
                        with st.spinner("Baixando série completa da ANA (sem restrição de datas)..."):
                            if usar_historica:
                                df_baixado = buscar_dataframe_historico(cod_sel)
                            else:
                                cliente_ana()
                                user_id, _ = ler_credenciais_ana()
                                df_baixado = buscar_dataframe_ana(user_id, cod_sel, 1970, 2025)

                        if df_baixado is None or df_baixado.empty:
                            st.warning(f"A estação {cod_sel} não possui registros de chuva na base da ANA. Selecione outra estação no raio.")
                        else:
                            anos_disp = sorted(df_baixado['Ano'].dropna().unique().astype(int))
                            ano_ini = anos_disp[0]
                            ano_fim = anos_disp[-1]
                            n_anos = len(anos_disp)

                            st.session_state.ana_series_text = '\n'.join(df_baixado['Precipitacao'].astype(str).tolist())
                            st.session_state.estacao_input = f"{cod_sel} ({est_obj['nome']})"
                            st.session_state.idw_meta = None
                            st.session_state.download_info = {
                                'tipo': 'single',
                                'cod': cod_sel,
                                'nome': est_obj['nome'],
                                'n_anos': n_anos,
                                'ano_ini': ano_ini,
                                'ano_fim': ano_fim,
                            }
                            st.rerun()
                    except UserError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error(f'ANA: {e}')

            else:
                # Modo IDW: Multiselect de estações + cálculo de pesos em tempo real
                mapa_opcoes = {
                    f"{'⭐ ' if i == 0 else ''}{e['codigo']} — {e['nome']} ({e['distancia_km']:.1f} km)": e
                    for i, e in enumerate(estacoes_no_raio)
                }
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
                            estacoes_sem_dados = []
                            barra_dl = st.progress(0.0)
                            aviso_dl = st.empty()
                            total_sel = len(estacoes_sel)

                            for idx_est, est_item in enumerate(estacoes_sel):
                                c_code = est_item['codigo']
                                aviso_dl.caption(f"Baixando série completa da estação {c_code} — {est_item['nome']} ({idx_est + 1}/{total_sel})...")
                                try:
                                    if usar_historica:
                                        df_est = buscar_dataframe_historico(c_code)
                                    else:
                                        cliente_ana()
                                        user_id, _ = ler_credenciais_ana()
                                        df_est = buscar_dataframe_ana(user_id, c_code, 1970, 2025)
                                except Exception:
                                    df_est = None

                                if df_est is not None and not df_est.empty:
                                    series_dict[c_code] = df_est
                                else:
                                    estacoes_sem_dados.append(f"{c_code} ({est_item['nome']})")

                                barra_dl.progress((idx_est + 1) / total_sel)

                            aviso_dl.empty()
                            barra_dl.empty()

                            if estacoes_sem_dados:
                                st.info(f"Nota: A(s) estação(ões) {', '.join(estacoes_sem_dados)} não possui(em) registros de chuva na base da ANA e foi(ram) desconsiderada(s).")

                            if not series_dict:
                                st.warning("Nenhuma das estações selecionadas possui registros de chuva na base da ANA. Selecione outras estações no raio.")
                            else:
                                # Interpola via IDW normalmente com as estações válidas
                                df_interp, pesos_finais = interpolar_series_idw(series_dict, dists_map, p=2.0)
                                anos_disp = sorted(df_interp['Ano'].dropna().unique().astype(int))
                                ano_ini = anos_disp[0]
                                ano_fim = anos_disp[-1]
                                n_anos = len(anos_disp)

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
                                st.session_state.download_info = {
                                    'tipo': 'idw',
                                    'n_est': len(series_dict),
                                    'n_anos': n_anos,
                                    'ano_ini': ano_ini,
                                    'ano_fim': ano_fim,
                                }
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
