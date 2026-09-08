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
    parse_ana_file,
    parse_manual_data,
    obter_serie_chuva_historica,
    listar_estacoes_historicas,
    calcular_distancia_km,
    filtrar_estacoes_por_raio,
    interpolar_series_idw,
    detectar_isozona_coordenadas,
    desenhar_pin_mapa_isozonas,
    verificar_consistencia_fisica_idf,
    analisar_qualidade_serie,
    UF_PARA_NOME,
    AnaHidroWebService,
    UserError,
    ISOZONAS,
    DURATIONS,
    RETURN_PERIODS,
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
    st.session_state.setdefault('current_step', 1)       # Stepper linear: 1, 2, 3 ou 4
    st.session_state.setdefault('ana_stations', [])       # [{codigo, nome, latitude, longitude, ...}]
    st.session_state.setdefault('ana_series_text', '')    # texto manual ou baixado
    st.session_state.setdefault('loaded_df', None)        # DataFrame unificado da série histórica
    st.session_state.setdefault('results', None)
    st.session_state.setdefault('calc_hash', None)        # Hash dos parâmetros no momento do cálculo
    st.session_state.setdefault('report_ctx', {})
    st.session_state.setdefault('proj_lat', -23.0289)
    st.session_state.setdefault('proj_lon', -45.5569)
    st.session_state.setdefault('proj_loc', 'Taubaté - SP')
    st.session_state.setdefault('estacao_input', '')
    st.session_state.setdefault('search_radius_km', 35)
    st.session_state.setdefault('selection_mode', 'single')  # 'single' ou 'idw'
    st.session_state.setdefault('idw_meta', None)
    st.session_state.setdefault('idw_p', 2.0)             # Expoente de distância IDW
    st.session_state.setdefault('last_clicked_coords', None)
    st.session_state.setdefault('uf_sel', 'SP')
    st.session_state.setdefault('download_info', None)
    st.session_state.setdefault('data_source_method', 'api') # 'api', 'csv', 'manual'
    st.session_state.setdefault('api_source', 'hist')        # 'hist' ou 'tele'
    st.session_state.setdefault('isozona_escolhida', 'B')
    st.session_state.setdefault('isozona_origem', 'Automática (detectada no mapa)')
    st.session_state.setdefault('limiar_cobertura_pct', 90.0)
    st.session_state.setdefault('excluir_incompletos', False)
    st.session_state.setdefault('modo_ajuste_sherman', 'log')
    st.session_state.setdefault('year_start', None)
    st.session_state.setdefault('year_end', None)


init_state()


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
    """Calcula hash SHA-256 dos parâmetros de entrada para detecção de invalidação de estado."""
    import hashlib
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


# ── Barra lateral: identificação, idioma e reset ──────────────────────────────
lang_label = st.sidebar.radio('🌐 Idioma / Language', ['PT 🇧🇷', 'EN 🇺🇸'], horizontal=True)
lang = lang_label.split()[0]
L = UI[lang]

st.sidebar.header(L['sidebar_cfg'])

with st.sidebar.expander('🏷️ ' + L['meta'], expanded=True):
    responsavel = st.text_input(L['resp'], value='Pedro Luis Soethe Cursino')
    localizacao = st.text_input(L['loc'], value=st.session_state.proj_loc)
    st.session_state.proj_loc = localizacao
    estacao = st.text_input(L['est'], value=st.session_state.estacao_input)
    st.session_state.estacao_input = estacao

st.sidebar.markdown(f"**Versão:** `Soethe·ii / SII·IDF v2.1`")

if st.sidebar.button("🔄 " + t('btn_reset_analysis', lang), use_container_width=True):
    st.session_state.results = None
    st.session_state.calc_hash = None
    st.session_state.loaded_df = None
    st.session_state.ana_series_text = ''
    st.session_state.download_info = None
    st.session_state.year_start = None
    st.session_state.year_end = None
    st.session_state.current_step = 1
    st.rerun()

st.sidebar.markdown(
    f"<div style='color:#888; font-size:0.8em; padding-top:1rem;'>{L['footer']}</div>",
    unsafe_allow_html=True,
)

# ── Cabeçalho Principal e Stepper em 4 Etapas ─────────────────────────────────
st.title(L['title'])
st.caption(L['subtitle'])

curr_s = st.session_state.current_step
c_s1, c_s2, c_s3, c_s4 = st.columns(4)

with c_s1:
    btn_type = 'primary' if curr_s == 1 else 'secondary'
    icon = '📍 ' if curr_s == 1 else ('✅ ' if curr_s > 1 else '1️⃣ ')
    if st.button(f"{icon}{t('stepper_step1', lang)}", key='nav_s1', use_container_width=True, type=btn_type):
        st.session_state.current_step = 1
        st.rerun()

with c_s2:
    btn_type = 'primary' if curr_s == 2 else 'secondary'
    icon = '🌧️ ' if curr_s == 2 else ('✅ ' if curr_s > 2 else '2️⃣ ')
    if st.button(f"{icon}{t('stepper_step2', lang)}", key='nav_s2', use_container_width=True, type=btn_type):
        st.session_state.current_step = 2
        st.rerun()

with c_s3:
    btn_type = 'primary' if curr_s == 3 else 'secondary'
    icon = '🔍 ' if curr_s == 3 else ('✅ ' if curr_s > 3 else '3️⃣ ')
    if st.button(f"{icon}{t('stepper_step3', lang)}", key='nav_s3', use_container_width=True, type=btn_type):
        st.session_state.current_step = 3
        st.rerun()

with c_s4:
    btn_type = 'primary' if curr_s == 4 else 'secondary'
    icon = '📊 ' if curr_s == 4 else '4️⃣ '
    if st.button(f"{icon}{t('stepper_step4', lang)}", key='nav_s4', use_container_width=True, type=btn_type):
        st.session_state.current_step = 4
        st.rerun()

st.divider()
def figuras(results):
    return (
        fig_historical_series(results['series_df'], lang),
        fig_gumbel_analysis(results['gumbel_df'], results['mu'], results['sigma'],
                            results['n_samples'], lang),
        fig_pdf_curves(results['disagg_df'], lang),
        fig_idf_curves(results['idf_df'], results['sherman_params'], lang),
    )


# ══════════════════════════════════════════════════════════════════════════════
# NAVEGAÇÃO LINEAR DO WORKFLOW EM 4 ETAPAS (STEPPER)
# ══════════════════════════════════════════════════════════════════════════════

# ──────────────────────────────────────────────────────────────────────────────
# ETAPA 1: 📍 Localização do Projeto e Isozona
# ──────────────────────────────────────────────────────────────────────────────
if curr_s == 1:
    st.subheader(f"📍 {t('stepper_step1', lang)}")
    st.caption(
        "Busque o endereço ou município do projeto, ajuste as coordenadas e o raio de busca no mapa, e confirme a Isozona de Taborga detectada."
        if lang == 'PT'
        else "Search for project address or municipality, adjust coordinates and radius on map, and confirm detected Taborga Isozone."
    )

    # 1. Campo de busca por endereço com st.form (ENTER submete)
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
                iso_det = detectar_isozona_coordenadas(lat_f, lon_f)
                st.session_state.isozona_escolhida = iso_det
                st.session_state.isozona_origem = f"Automática ({iso_det})"
                st.success(f"📍 {addr_f} (UF: **{nova_uf}** | Isozona: **{iso_det}**)")
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
        iso_det = detectar_isozona_coordenadas(lat_val, lon_val)
        st.session_state.isozona_escolhida = iso_det
        st.session_state.isozona_origem = f"Automática ({iso_det})"
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

    st.markdown(
        f"📍 **Local do Projeto:** Lat `{st.session_state.proj_lat:.4f}` | "
        f"Lon `{st.session_state.proj_lon:.4f}` — *{st.session_state.proj_loc}* "
        f"(Inventário da ANA: **{st.session_state.uf_sel}**)"
    )

    # 3. Colunas: Mapa Folium Interativo (esquerda) e Mapa Oficial de Isozonas (direita)
    col_mapa, col_isozona = st.columns([1.15, 0.85])

    with col_mapa:
        st.markdown("**🗺️ Mapa de Localização e Estações Pluviométricas**")
        with st.spinner(f"Carregando inventário de estações da ANA ({st.session_state.uf_sel})..."):
            try:
                estacoes_uf = listar_estacoes_hist(st.session_state.uf_sel)
            except Exception:
                estacoes_uf = []

        estacoes_no_raio = filtrar_estacoes_por_raio(
            st.session_state.proj_lat,
            st.session_state.proj_lon,
            estacoes_uf,
            raio_km=st.session_state.search_radius_km,
        )
        st.session_state.ana_stations = estacoes_no_raio

        m = folium.Map(
            location=[st.session_state.proj_lat, st.session_state.proj_lon],
            zoom_start=10,
            tiles=None,
            control_scale=True,
        )
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

        folium.Marker(
            [st.session_state.proj_lat, st.session_state.proj_lon],
            popup=f"<b>📍 Local do Projeto</b><br>Lat: {st.session_state.proj_lat:.4f}<br>Lon: {st.session_state.proj_lon:.4f}<br>{st.session_state.proj_loc}",
            tooltip="📍 Local do Projeto",
            icon=folium.Icon(color='red', icon='info-sign'),
        ).add_to(m)

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

        st.caption("💡 Dica: Clique no botão 📍 no canto superior esquerdo ou em qualquer ponto do mapa para reposicionar o projeto.")
        map_out = st_folium(m, height=460, use_container_width=True, returned_objects=["last_clicked", "last_active_drawing"])

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
            nova_uf, novo_loc = detectar_uf_coordenadas(c_lat, c_lon)
            st.session_state.uf_sel = nova_uf
            st.session_state.proj_loc = novo_loc
            iso_det = detectar_isozona_coordenadas(c_lat, c_lon)
            st.session_state.isozona_escolhida = iso_det
            st.session_state.isozona_origem = f"Automática ({iso_det})"
            st.rerun()

    with col_isozona:
        st.markdown(f"**🗺️ {t('isozona_label', lang)}**")
        img_pin = desenhar_pin_mapa_isozonas(st.session_state.proj_lat, st.session_state.proj_lon)
        if img_pin is not None:
            st.image(img_pin, caption="Mapa Oficial de Isozonas de Chuvas Intensas do Brasil (Taborga, 1974)", use_container_width=True)

        iso_det = detectar_isozona_coordenadas(st.session_state.proj_lat, st.session_state.proj_lon)
        idx_padrao = ISOZONAS.index(st.session_state.isozona_escolhida) if st.session_state.isozona_escolhida in ISOZONAS else (ISOZONAS.index(iso_det) if iso_det in ISOZONAS else 1)
        iso_sel = st.selectbox(f"{t('isozona_label', lang)} (A a H)", ISOZONAS, index=idx_padrao)
        if iso_sel != iso_det:
            st.caption(f"✏️ **{t('isozona_manual_badge', lang).format(iso_sel)}**")
            st.session_state.isozona_origem = f"Manual ({iso_sel}) - Sobrescrita"
        else:
            st.caption(f"🎯 **{t('isozona_auto_badge', lang).format(iso_det)}**")
            st.session_state.isozona_origem = f"Automática ({iso_det})"
        st.session_state.isozona_escolhida = iso_sel

    st.divider()
    if st.button(t('btn_confirm_loc', lang), type='primary', use_container_width=True):
        st.session_state.current_step = 2
        st.rerun()

# ──────────────────────────────────────────────────────────────────────────────
# ETAPA 2: 🌧️ Dados Pluviométricos
# ──────────────────────────────────────────────────────────────────────────────
elif curr_s == 2:
    st.subheader(f"🌧️ {t('stepper_step2', lang)}")

    with st.container(border=True):
        c_r1, c_r2 = st.columns([3, 1])
        c_r1.markdown(
            f"📍 **Local:** {st.session_state.proj_loc} (`{st.session_state.proj_lat:.4f}`, `{st.session_state.proj_lon:.4f}`) | "
            f"**Raio:** {st.session_state.search_radius_km} km | "
            f"**Isozona:** {st.session_state.isozona_escolhida} (*{st.session_state.isozona_origem}*)"
        )
        if c_r2.button("✏️ Alterar Localização", use_container_width=True):
            st.session_state.current_step = 1
            st.rerun()

    metodo = st.radio(
        L['method'],
        [L['m_api'], L['m_csv'], L['m_manual']],
        horizontal=True,
        index=0 if st.session_state.data_source_method == 'api' else (1 if st.session_state.data_source_method == 'csv' else 2),
    )
    st.session_state.data_source_method = 'api' if metodo == L['m_api'] else ('csv' if metodo == L['m_csv'] else 'manual')

    if st.session_state.data_source_method == 'api':
        c_f1, c_f2 = st.columns([1.5, 2.5])
        fonte_escolhida = c_f1.radio(
            L['api_fonte'],
            [L['fonte_hist'], L['fonte_tele']],
            horizontal=True,
            index=0 if st.session_state.api_source == 'hist' else 1,
        )
        st.session_state.api_source = 'hist' if fonte_escolhida == L['fonte_hist'] else 'tele'
        usar_historica = (st.session_state.api_source == 'hist')
        c_f2.caption(L['hint_hist'] if usar_historica else L['api_hint'])

        with st.spinner(f"Carregando inventário de estações da ANA ({st.session_state.uf_sel})..."):
            try:
                if usar_historica:
                    estacoes_uf = listar_estacoes_hist(st.session_state.uf_sel)
                else:
                    estacoes_uf = cliente_ana().listar_estacoes_por_uf(st.session_state.uf_sel)
            except Exception as exc:
                st.error(f"Falha ao obter inventário da ANA: {exc}")
                estacoes_uf = []

        estacoes_no_raio = filtrar_estacoes_por_raio(
            st.session_state.proj_lat,
            st.session_state.proj_lon,
            estacoes_uf,
            raio_km=st.session_state.search_radius_km,
        )

        if not estacoes_no_raio:
            st.warning(L['no_stations_radius'].format(r=st.session_state.search_radius_km))
        else:
            st.info(L['stations_found_count'].format(n=len(estacoes_no_raio), r=st.session_state.search_radius_km))

            df_tbl_est = pd.DataFrame([{
                'Código': e['codigo'],
                'Nome': e['nome'],
                'Município': e.get('municipio', '—'),
                'Operadora': e.get('operadora', '—'),
                'Alt. (m)': e.get('altitude', '—'),
                'Período': e.get('periodo_operacao', '—'),
                'Anos': e.get('anos_operacao', '—'),
                'Status': '🟢 Ativa' if e.get('status_operando') else '⚪ Inativa',
                'Distância (km)': f"{e['distancia_km']:.2f}",
            } for e in estacoes_no_raio])
            st.dataframe(df_tbl_est, use_container_width=True, hide_index=True)

            modo = st.radio(
                L['mode_label'],
                [L['mode_single'], L['mode_idw']],
                horizontal=True,
                index=0 if st.session_state.selection_mode == 'single' else 1,
            )
            st.session_state.selection_mode = 'single' if modo == L['mode_single'] else 'idw'

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
                            col_ano = 'Ano' if 'Ano' in df_baixado.columns else t('col_ano', lang)
                            anos_disp = sorted(df_baixado[col_ano].dropna().unique().astype(int))
                            ano_ini, ano_fim, n_anos = anos_disp[0], anos_disp[-1], len(anos_disp)

                            st.session_state.loaded_df = df_baixado
                            col_p = 'Precipitacao' if 'Precipitacao' in df_baixado.columns else t('col_precip', lang)
                            st.session_state.ana_series_text = '\n'.join(df_baixado[col_p].astype(str).tolist())
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
                with st.container(border=True):
                    st.markdown(
                        """
                        <div style="font-size: 0.72rem; line-height: 1.4; color: #333;">
                            <div style="font-weight: bold; font-size: 0.85rem; margin-bottom: 6px; color: #1a5276;">
                                📐 Metodologia de Interpolação Multi-estação (IDW — Inverse Distance Weighting)
                            </div>
                            <p style="margin-bottom: 6px;">
                                O método da <b>Ponderação pelo Inverso da Distância (IDW)</b> estima chuvas pontuais a partir das estações vizinhas adotando o inverso da distância elevado a uma potência <i>p</i>:
                            </p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    st.latex(r"w_i = \frac{1 / d_i^p}{\sum_{k=1}^m \frac{1}{d_k^p}}")
                    st.markdown(
                        r"""
                        <div style="font-size: 0.72rem; line-height: 1.4; color: #333;">
                            <b>Onde:</b>
                            <ul style="margin-top: 2px; margin-bottom: 6px; padding-left: 18px;">
                                <li><b>d<sub>i</sub>:</b> distância geodésica da estação <i>i</i> até o ponto do projeto (km).</li>
                                <li><b>p:</b> expoente da distância configurável (padrão <i>p = 2</i>, inverso do quadrado).</li>
                                <li><b>w<sub>i</sub>:</b> peso ponderado da estação (\(\sum w_i = 100\%\)).</li>
                            </ul>
                            <b>Procedimento Hidrológico:</b>
                            <ol style="margin-top: 2px; margin-bottom: 4px; padding-left: 18px;">
                                <li><b>Ponderação Ano a Ano:</b> Para cada ano civil coincidente das séries históricas, a precipitação máxima anual no ponto do projeto é estimada pela soma ponderada: \(P_{\text{proj}}(t) = \sum w_i^*(t) \cdot P_i(t)\).</li>
                                <li><b>Re-normalização Dinâmica:</b> Se uma estação não operou em determinado ano civil, os pesos \(w_i^*(t)\) são re-normalizados automaticamente entre as estações ativas remanescentes.</li>
                                <li><b>Série Sintética Local:</b> A série ponderada resultante reflete as precipitações na coordenada exata da obra e alimenta o ajuste de Gumbel, Taborga e Sherman.</li>
                            </ol>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                idw_p = st.slider(
                    "Expoente de distância (p):",
                    min_value=1.0,
                    max_value=4.0,
                    value=float(st.session_state.idw_p),
                    step=0.5,
                    help="O expoente padrão p=2 corresponde ao inverso do quadrado da distância.",
                )
                st.session_state.idw_p = idw_p

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

                    invs = {c: (1.0 / max(d, 0.1)) ** idw_p for c, d in dists_map.items()}
                    soma_inv = sum(invs.values())
                    pesos_preview = {c: round((invs[c] / soma_inv) * 100.0, 1) for c in dists_map}
                    sum_sq_w = sum((w / 100.0) ** 2 for w in pesos_preview.values())
                    n_eff_preview = round(1.0 / sum_sq_w, 2) if sum_sq_w > 0 else 1.0

                    df_preview_idw = pd.DataFrame([
                        {
                            L['geo_station_code']: e['codigo'],
                            L['geo_station_name']: e['nome'],
                            'Operadora': e.get('operadora', '—'),
                            'Alt. (m)': e.get('altitude', '—'),
                            L['geo_distance_km']: f"{e['distancia_km']:.2f} km",
                            L['geo_weight_pct']: f"{pesos_preview[e['codigo']]:.1f}%",
                        }
                        for e in estacoes_sel
                    ])
                    st.dataframe(df_preview_idw, use_container_width=True, hide_index=True)
                    st.caption(f"**{t('idw_neff_label', lang)}:** `{n_eff_preview}`")

                    for c_cod, w_val in pesos_preview.items():
                        if w_val < 2.0:
                            st.warning(t('idw_weight_alert', lang).format(c_cod, w_val))
                    dists_list = list(dists_map.values())
                    if len(dists_list) > 1 and max(dists_list) - min(dists_list) < 2.0 and min(dists_list) < 3.0:
                        st.info(t('idw_colocated_alert', lang))

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
                                df_interp, pesos_finais, n_eff_val, avisos_idw = interpolar_series_idw(
                                    series_dict, dists_map, p=idw_p, lang=lang
                                )
                                col_ano = 'Ano' if 'Ano' in df_interp.columns else t('col_ano', lang)
                                anos_disp = sorted(df_interp[col_ano].dropna().unique().astype(int))
                                ano_ini, ano_fim, n_anos = anos_disp[0], anos_disp[-1], len(anos_disp)

                                st.session_state.loaded_df = df_interp
                                col_p = 'Precipitacao' if 'Precipitacao' in df_interp.columns else t('col_precip', lang)
                                st.session_state.ana_series_text = '\n'.join(df_interp[col_p].astype(str).tolist())
                                codigos_str = ', '.join(series_dict.keys())
                                st.session_state.estacao_input = f"IDW ({codigos_str})"

                                st.session_state.idw_meta = {
                                    'stations': [
                                        {
                                            'codigo': e['codigo'],
                                            'nome': e['nome'],
                                            'distancia_km': e['distancia_km'],
                                            'peso_pct': pesos_finais.get(e['codigo'], 0.0) * 100.0,
                                            'operadora': e.get('operadora', '—'),
                                            'altitude': e.get('altitude', '—'),
                                        }
                                        for e in estacoes_sel if e['codigo'] in series_dict
                                    ],
                                    'coords': (st.session_state.proj_lat, st.session_state.proj_lon),
                                    'p': idw_p,
                                    'n_eff': n_eff_val,
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

    elif st.session_state.data_source_method == 'csv':
        up_file = st.file_uploader(L['upload'], type=['csv', 'txt'])
        if up_file is not None:
            try:
                df_up = parse_ana_file(up_file.getvalue(), lang=lang)
                st.session_state.loaded_df = df_up
                col_p = 'Precipitacao' if 'Precipitacao' in df_up.columns else t('col_precip', lang)
                st.session_state.ana_series_text = '\n'.join(df_up[col_p].astype(str).tolist())
                col_ano = 'Ano' if 'Ano' in df_up.columns else t('col_ano', lang)
                anos = sorted(df_up[col_ano].dropna().unique().astype(int))
                st.session_state.download_info = {
                    'tipo': 'csv',
                    'n_anos': len(anos),
                    'ano_ini': anos[0],
                    'ano_fim': anos[-1],
                }
                st.success(f"Arquivo carregado com sucesso: {len(anos)} anos ({anos[0]} a {anos[-1]}).")
            except Exception as e:
                st.error(f"Erro ao processar arquivo: {e}")

    else:
        manual_in = st.text_area(
            L['manual_lbl'],
            value=st.session_state.ana_series_text,
            placeholder=L['manual_ph'],
            height=160,
        )
        if st.button("Confirmar Dados Manuais", type='primary', use_container_width=True):
            if manual_in.strip():
                try:
                    df_man = parse_manual_data(manual_in, lang=lang)
                    st.session_state.loaded_df = df_man
                    st.session_state.ana_series_text = manual_in
                    col_ano = 'Ano' if 'Ano' in df_man.columns else t('col_ano', lang)
                    anos = sorted(df_man[col_ano].dropna().unique().astype(int))
                    st.session_state.download_info = {
                        'tipo': 'manual',
                        'n_anos': len(anos),
                        'ano_ini': anos[0],
                        'ano_fim': anos[-1],
                    }
                    st.success(f"Dados manuais carregados: {len(anos)} valores.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao processar dados manuais: {e}")

    if st.session_state.loaded_df is not None and not st.session_state.loaded_df.empty:
        df_cur = st.session_state.loaded_df
        col_ano = 'Ano' if 'Ano' in df_cur.columns else t('col_ano', lang)
        anos = sorted(df_cur[col_ano].dropna().unique().astype(int))
        st.success(f"✅ **Série pluviométrica pronta!** {len(anos)} anos disponíveis ({anos[0]} a {anos[-1]}).")
        with st.expander("👁️ Visualizar Prévia da Série Carregada", expanded=False):
            st.dataframe(df_cur, height=220, use_container_width=True, hide_index=True)

        st.divider()
        if st.button("Avançar para Diagnóstico e Parâmetros ➡️", type='primary', use_container_width=True):
            st.session_state.current_step = 3
            st.rerun()
    else:
        st.info("Baixe a série da ANA acima ou carregue um arquivo/dados manuais para prosseguir.")

# ──────────────────────────────────────────────────────────────────────────────
# ETAPA 3: 🔍 Diagnóstico e Parâmetros
# ──────────────────────────────────────────────────────────────────────────────
elif curr_s == 3:
    st.subheader(f"🔍 {t('stepper_step3', lang)}")

    if st.session_state.loaded_df is None or st.session_state.loaded_df.empty:
        st.warning("Nenhum dado pluviométrico foi carregado ainda. Por favor, volte para a Etapa 2 para baixar ou inserir dados.")
        if st.button("⬅️ Voltar para Etapa 2", use_container_width=True):
            st.session_state.current_step = 2
            st.rerun()
    else:
        df_base = st.session_state.loaded_df.copy()
        col_ano = 'Ano' if 'Ano' in df_base.columns else t('col_ano', lang)
        anos_disp = sorted(df_base[col_ano].dropna().unique().astype(int))
        ano_min, ano_max = int(anos_disp[0]), int(anos_disp[-1])

        st.markdown(f"### 🗓️ {t('sec_period_title', lang)}")
        c_y0, c_y1 = st.columns(2)
        def_y0 = st.session_state.year_start if st.session_state.year_start is not None else ano_min
        def_y1 = st.session_state.year_end if st.session_state.year_end is not None else ano_max
        def_y0 = max(ano_min, min(int(def_y0), ano_max))
        def_y1 = max(ano_min, min(int(def_y1), ano_max))

        y0 = c_y0.number_input(t('year_start_label', lang), min_value=ano_min, max_value=ano_max, value=def_y0)
        y1 = c_y1.number_input(t('year_end_label', lang), min_value=ano_min, max_value=ano_max, value=def_y1)
        st.session_state.year_start = int(y0)
        st.session_state.year_end = int(y1)

        mask_temp = (df_base[col_ano] >= y0) & (df_base[col_ano] <= y1)
        df_temp = df_base[mask_temp].reset_index(drop=True)

        st.markdown(f"### 🛡️ {t('diag_quality_title', lang)}")
        c_limiar, c_excluir = st.columns([1.5, 2.5])
        limiar_cob = c_limiar.slider(
            t('diag_coverage_label', lang),
            min_value=50.0,
            max_value=100.0,
            value=float(st.session_state.limiar_cobertura_pct),
            step=5.0,
            help=t('diag_coverage_help', lang),
        )
        st.session_state.limiar_cobertura_pct = limiar_cob

        excluir_inc = c_excluir.checkbox(
            "Descartar anos civis com cobertura de dias válidos inferior ao limiar",
            value=st.session_state.excluir_incompletos,
            help="Se ativo, anos com menos dias válidos que o limiar são excluídos do cálculo e documentados no memorial.",
        )
        st.session_state.excluir_incompletos = excluir_inc

        diag_prev = analisar_qualidade_serie(
            df_temp,
            limiar_cobertura_pct=limiar_cob,
            excluir_incompletos=excluir_inc,
            lang=lang,
        )

        q1, q2, q3 = st.columns(3)
        q1.metric("Anos na Série", f"{diag_prev['n_apos_descarte']} de {diag_prev['n_bruto']}")
        cv = diag_prev['cv']
        cv_status = "✅ Normal (0.15 - 0.30)" if (0.15 <= cv <= 0.30) else "⚠️ Fora do intervalo usual"
        q2.metric("Coef. Variação (CV)", f"{cv:.2f}", cv_status)
        mk = diag_prev['mann_kendall']
        mk_status = "⚠️ Tendência detectada" if mk['tendencia_significativa'] else "✅ Estacionária"
        q3.metric("Mann-Kendall (τ)", f"{mk['tau']:.3f}", mk_status)

        if diag_prev['anos_descartados']:
            with st.expander(f"📋 {t('diag_discarded_years', lang)} ({len(diag_prev['anos_descartados'])} anos)", expanded=False):
                df_desc = pd.DataFrame([{
                    'Ano': item['ano'],
                    'Precipitação (mm)': item['precipitacao'],
                    'Dias Válidos': item.get('dias_validos', '—'),
                    'Motivo': item['motivo'],
                } for item in diag_prev['anos_descartados']])
                st.dataframe(df_desc, use_container_width=True, hide_index=True)

        outs = diag_prev['outliers']
        if outs:
            for o in outs:
                st.warning(f"⚠️ {t('diag_outlier_found', lang).format(o['ano'], o['valor'], o['teste'])}")

        st.markdown("### 🧮 Método de Ajuste da Equação de Sherman")
        modo_opts = [
            "Ajuste em Espaço Logarítmico com Bounds da Literatura (Recomendado)",
            "Ajuste Linear Direto sem Bounds (Legado)",
        ]
        idx_m = 0 if st.session_state.modo_ajuste_sherman == 'log' else 1
        modo_sel = st.radio("Metodologia de regressão não-linear:", modo_opts, index=idx_m)
        st.session_state.modo_ajuste_sherman = 'log' if modo_sel == modo_opts[0] else 'linear_sem_bounds'

        st.divider()
        if st.button(f"⚡ {t('btn_run_analysis', lang)}", type='primary', use_container_width=True):
            try:
                with st.spinner(L['run']):
                    results = run_full_analysis(
                        df_input=df_base,
                        isozona=st.session_state.isozona_escolhida,
                        lang=lang,
                        year_start=int(y0),
                        year_end=int(y1),
                        limiar_cobertura_pct=limiar_cob,
                        excluir_incompletos=excluir_inc,
                        modo_ajuste_sherman=st.session_state.modo_ajuste_sherman,
                    )
                st.session_state.results = results
                h = calcular_hash_inputs(
                    isozona=st.session_state.isozona_escolhida,
                    lat=float(st.session_state.proj_lat),
                    lon=float(st.session_state.proj_lon),
                    data_method=st.session_state.data_source_method,
                    estacao_str=st.session_state.estacao_input,
                    df_series=df_base,
                    y0=int(y0),
                    y1=int(y1),
                    limiar_cob=float(limiar_cob),
                    excluir_inc=bool(excluir_inc),
                    modo_sherman=st.session_state.modo_ajuste_sherman,
                    idw_p=float(st.session_state.idw_p),
                )
                st.session_state.calc_hash = h
                st.session_state.report_ctx = {
                    'responsavel': responsavel,
                    'localizacao': localizacao,
                    'estacao': estacao or st.session_state.estacao_input or '—',
                    'lang': lang,
                    'coords': (float(st.session_state.proj_lat), float(st.session_state.proj_lon)),
                    'idw_meta': st.session_state.idw_meta,
                }
                st.session_state.current_step = 4
                st.rerun()
            except UserError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Erro na análise: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# ETAPA 4: 📊 Resultados e Memorial
# ──────────────────────────────────────────────────────────────────────────────
elif curr_s == 4:
    st.subheader(f"📊 {t('stepper_step4', lang)}")

    results = st.session_state.results
    if not results:
        st.info(L['no_data_yet'])
        if st.button("⬅️ Ir para Etapa 3 (Diagnóstico e Execução)", use_container_width=True):
            st.session_state.current_step = 3
            st.rerun()
    else:
        current_hash = calcular_hash_inputs(
            isozona=st.session_state.isozona_escolhida,
            lat=float(st.session_state.proj_lat),
            lon=float(st.session_state.proj_lon),
            data_method=st.session_state.data_source_method,
            estacao_str=st.session_state.estacao_input,
            df_series=st.session_state.loaded_df,
            y0=st.session_state.year_start,
            y1=st.session_state.year_end,
            limiar_cob=float(st.session_state.limiar_cobertura_pct),
            excluir_inc=bool(st.session_state.excluir_incompletos),
            modo_sherman=st.session_state.modo_ajuste_sherman,
            idw_p=float(st.session_state.idw_p),
        )
        params_changed = (st.session_state.calc_hash is not None and current_hash != st.session_state.calc_hash)

        if params_changed:
            st.warning(f"⚠️ **{t('hash_warning_title', lang)}**\n\n{t('hash_warning_desc', lang)}")
            if st.button(f"⚡ {t('btn_run_analysis', lang)} (Recalcular com parâmetros atuais)", type='primary', use_container_width=True):
                st.session_state.current_step = 3
                st.rerun()

        cons = results.get('physical_consistency', {})
        if cons.get('status') == 'OK':
            st.success(t('phys_cons_ok', lang))
        else:
            with st.expander(f"⚠️ {t('phys_cons_title', lang)} — Informações Metodológicas", expanded=False):
                for v in cons.get('violacoes_tempo', []):
                    st.caption(f"- {v}")
                for v in cons.get('violacoes_freq', []):
                    st.caption(f"- {v}")

        sherman = results['sherman_params']
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric(L['n_years'], results['n_samples'])
        m2.metric('μ (Gumbel)', f"{results['mu']:.2f} mm")
        m3.metric('σ (Gumbel)', f"{results['sigma']:.2f} mm")
        m4.metric('R² (Sherman)', f"{sherman['R²']:.4f}")
        m5.metric('NSE (Sherman)', f"{sherman['NSE']:.4f}")

        fh, fg, fp, fi = figuras(results)

        t1, t2, t3 = st.tabs([t('tab_data_diag', lang), t('tab_stat_fit', lang), t('tab_curves_eq', lang)])

        with t1:
            st.plotly_chart(fh, use_container_width=True)
            st.dataframe(results['series_df'], height=320, use_container_width=True, hide_index=True)
            csv_s = results['series_df'].to_csv(index=False).encode('utf-8')
            st.download_button(f"📥 {t('btn_dl_csv', lang)} (Série Histórica)", data=csv_s, file_name="serie_historica.csv", mime="text/csv")

            with st.container(border=True):
                st.markdown(f"**{t('diag_quality_title', lang)}**")
                q_diag = results.get('quality_diag', {})
                if q_diag:
                    cv_val = q_diag.get('cv', 0.0)
                    st.markdown(f"- **{t('diag_cv_label', lang)}:** `{cv_val:.2f}` — {'✅ ' + t('diag_cv_ok', lang).format(cv_val) if 0.15 <= cv_val <= 0.30 else '⚠️ ' + t('diag_cv_alert', lang).format(cv_val)}")
                    mk_info = q_diag.get('mann_kendall', {})
                    if mk_info:
                        tau_val = mk_info.get('tau', 0.0)
                        pval = mk_info.get('p_value', 1.0)
                        st.markdown(f"- **{t('diag_mk_title', lang)}:** τ=`{tau_val:.4f}`, p-valor=`{pval:.4f}` — {t('diag_mk_trend', lang).format(tau_val, pval) if mk_info.get('tendencia_significativa') else t('diag_mk_no_trend', lang).format(tau_val, pval)}")

                desc_anos = results.get('anos_descartados', [])
                if desc_anos:
                    st.markdown(f"**{t('diag_discarded_years', lang)}:**")
                    df_desc_r = pd.DataFrame([{
                        'Ano': a['ano'],
                        'Precipitação (mm)': a['precipitacao'],
                        'Dias Válidos': a.get('dias_validos', '—'),
                        'Motivo': a['motivo'],
                    } for a in desc_anos])
                    st.dataframe(df_desc_r, use_container_width=True, hide_index=True)

        with t2:
            st.plotly_chart(fg, use_container_width=True)
            st.dataframe(results['gumbel_df'], use_container_width=True, hide_index=True)
            csv_g = results['gumbel_df'].to_csv(index=False).encode('utf-8')
            st.download_button(f"📥 {t('btn_dl_csv', lang)} (Gumbel)", data=csv_g, file_name="gumbel_analise.csv", mime="text/csv")

            st.plotly_chart(fp, use_container_width=True)
            st.dataframe(results['disagg_df'], height=320, use_container_width=True, hide_index=True)
            csv_d = results['disagg_df'].to_csv(index=False).encode('utf-8')
            st.download_button(f"📥 {t('btn_dl_csv', lang)} (Desagregação Taborga)", data=csv_d, file_name="desagregacao_taborga.csv", mime="text/csv")

            with st.expander("📐 " + t('gumbel_mem_card', lang), expanded=False):
                gm = results.get('gumbel_memory', {})
                if gm:
                    c_g1, c_g2, c_g3 = st.columns(3)
                    c_g1.metric("K1 (Yn)", f"{gm.get('yn', 0.0):.4f}")
                    c_g2.metric("K2 (Sn)", f"{gm.get('sn', 0.0):.4f}")
                    c_g3.metric("Fórmula Ven Te Chow", "Pt = μ + Kt · σ")
                    st.dataframe(gm.get('ordered_df'), height=280, use_container_width=True, hide_index=True)

        with t3:
            st.plotly_chart(fi, use_container_width=True)
            st.dataframe(results['idf_df'], height=320, use_container_width=True, hide_index=True)
            csv_i = results['idf_df'].to_csv(index=False).encode('utf-8')
            st.download_button(f"📥 {t('btn_dl_csv', lang)} (Curvas IDF)", data=csv_i, file_name="curvas_idf.csv", mime="text/csv")

            A, B, C, D = sherman['A'], sherman['B'], sherman['C'], sherman['D']
            st.markdown(f"### {L['sherman_eq']}")
            st.latex(r"i = \frac{%.4f \cdot TR^{%.4f}}{(t + %.4f)^{%.4f}}" % (A, B, C, D))

            df_sherman_params = pd.DataFrame([
                {'Parâmetro': 'A', 'Valor Ajustado': f"{A:.4f}", 'Erro Padrão': f"{sherman.get('se_A', 0.0):.4f}", 'IC 95% Inferior': f"{sherman.get('ci_A', (0,0))[0]:.2f}", 'IC 95% Superior': f"{sherman.get('ci_A', (0,0))[1]:.2f}", 'Faixa da Literatura': '10.0 a 20000.0'},
                {'Parâmetro': 'B', 'Valor Ajustado': f"{B:.4f}", 'Erro Padrão': f"{sherman.get('se_B', 0.0):.4f}", 'IC 95% Inferior': f"{sherman.get('ci_B', (0,0))[0]:.4f}", 'IC 95% Superior': f"{sherman.get('ci_B', (0,0))[1]:.4f}", 'Faixa da Literatura': '0.08 a 0.45'},
                {'Parâmetro': 'C', 'Valor Ajustado': f"{C:.4f}", 'Erro Padrão': f"{sherman.get('se_C', 0.0):.4f}", 'IC 95% Inferior': f"{sherman.get('ci_C', (0,0))[0]:.2f}", 'IC 95% Superior': f"{sherman.get('ci_C', (0,0))[1]:.2f}", 'Faixa da Literatura': '3.0 a 70.0'},
                {'Parâmetro': 'D', 'Valor Ajustado': f"{D:.4f}", 'Erro Padrão': f"{sherman.get('se_D', 0.0):.4f}", 'IC 95% Inferior': f"{sherman.get('ci_D', (0,0))[0]:.4f}", 'IC 95% Superior': f"{sherman.get('ci_D', (0,0))[1]:.4f}", 'Faixa da Literatura': '0.50 a 0.98'},
            ])
            st.dataframe(df_sherman_params, use_container_width=True, hide_index=True)

            g1, g2, g3, g4, g5 = st.columns(5)
            g1.metric('R²', f"{sherman['R²']:.4f}")
            g2.metric('NSE', f"{sherman['NSE']:.4f}")
            g3.metric('RMSE', f"{sherman['RMSE']:.2f} mm/h")
            g4.metric(t('max_cell_error', lang), f"{sherman.get('erro_max_celula', 0.0):.2f}%")
            g5.metric(t('mean_cell_error', lang), f"{sherman.get('erro_medio_celula', 0.0):.2f}%")

            for p_name, b_val in sherman.get('bounds_touched', []):
                st.warning(t('bound_touch_alert', lang).format(p_name, sherman[p_name], b_val))

        st.divider()
        st.subheader(L['downloads'])
        if params_changed:
            st.error(f"🚫 {t('export_blocked_msg', lang)}")

        ctx = st.session_state.report_ctx
        d1, d2 = st.columns(2)

        with d1:
            try:
                pdf_bytes = generate_pdf_report(
                    results,
                    ctx.get('responsavel', responsavel),
                    ctx.get('localizacao', localizacao),
                    ctx.get('estacao', estacao or '—'),
                    fh, fg, fp, fi,
                    lang=lang,
                    coords=ctx.get('coords'),
                    idw_meta=ctx.get('idw_meta'),
                ) if not params_changed else b''
                st.download_button(
                    L['dl_pdf'],
                    data=pdf_bytes,
                    file_name='memorial_calculo_idf.pdf',
                    mime='application/pdf',
                    use_container_width=True,
                    disabled=params_changed,
                )
            except Exception as e:
                st.warning(f'PDF: {e}')

        with d2:
            try:
                docx_bytes = generate_word_report(
                    results,
                    ctx.get('responsavel', responsavel),
                    ctx.get('localizacao', localizacao),
                    ctx.get('estacao', estacao or '—'),
                    fh, fg, fp, fi,
                    lang=lang,
                    coords=ctx.get('coords'),
                    idw_meta=ctx.get('idw_meta'),
                ) if not params_changed else b''
                st.download_button(
                    L['dl_word'],
                    data=docx_bytes,
                    file_name='memorial_calculo_idf.docx',
                    mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    use_container_width=True,
                    disabled=params_changed,
                )
            except Exception as e:
                st.warning(f'Word: {e}')

# ── Rodapé / créditos ─────────────────────────────────────────────────────────
st.divider()
st.markdown(
    f"<div style='text-align:center; color:#888; font-size:0.85em; padding:0.5rem 0;'>"
    f"{L['footer']}</div>",
    unsafe_allow_html=True,
)
