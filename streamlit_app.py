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
    SHERMAN_OPTIMIZER_BOUNDS,
    SHERMAN_TYPICAL_RANGES,
)
from plotting import (
    fig_historical_series,
    fig_gumbel_analysis,
    fig_pdf_curves,
    fig_idf_curves,
    fig_hydrograph_scs,
    fig_hyetograph_blocks,
)
from report import generate_pdf_report
from report_word import generate_word_report
from i18n import t
import project
import basin
import discharge



# ── Configuração da página ────────────────────────────────────────────────────
st.set_page_config(
    page_title="SII-HiDRO — Sistema Integrado de Hidrologia",
    page_icon="💧",
    layout="wide",
)

ISOZONAS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']


# ── Marca Dinâmica SII-HiDRO ──────────────────────────────────────────────────
def render_brand_html(active_module: str = 'idf', font_size: str = '2.0rem') -> str:
    """
    Renderiza a marca dinâmica SII-HiDRO com o 'i' em minúsculo estilizado
    na cor de ação primária (#2563eb).
    Módulo Projeto → SII-HiDRO
    Módulo IDF     → SII-HiDRO-IDF
    Módulo Bacia   → SII-HiDRO-Bacia
    Módulo Vazão   → SII-HiDRO-Vazão
    """
    suffix_map = {
        'projeto': '',
        'idf': '-IDF',
        'bacia': '-Bacia',
        'vazao': '-Vazão',
    }
    suffix = suffix_map.get(str(active_module).lower(), f"-{str(active_module).capitalize()}")
    return (
        f"<div style='display:inline-flex; align-items:center; gap:8px; line-height:1.2; margin-bottom:4px;'>"
        f"<span style='font-size:{font_size}; font-weight:800; letter-spacing:-0.5px; color:#0f172a;'>"
        f"SII-H<span style='color:#2563eb;'>i</span>DRO{suffix}"
        f"</span>"
        f"</div>"
    )


def brand_text(active_module: str = 'idf') -> str:
    """Retorna o texto sem formatação HTML da marca dinâmica."""
    suffix_map = {
        'projeto': '',
        'idf': '-IDF',
        'bacia': '-Bacia',
        'vazao': '-Vazão',
    }
    suffix = suffix_map.get(str(active_module).lower(), f"-{str(active_module).capitalize()}")
    return f"SII-HiDRO{suffix}"


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
        'title': 'SII-HiDRO-IDF',
        'subtitle': 'Sistema Integrado de Hidrologia · Módulo de Curvas Intensidade-Duração-Frequência (IDF)',
        'footer': 'Desenvolvido por <a href="https://pedrosoethe.vercel.app/engenheiro/soethe-ii" target="_blank">Soethe Infrastructure Intelligence</a> · SII-HiDRO v3.0',
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
        'title': 'SII-HiDRO-IDF',
        'subtitle': 'Integrated Hydrology System · Intensity-Duration-Frequency (IDF) Curves Module',
        'footer': 'Developed by <a href="https://pedrosoethe.vercel.app/engenheiro/soethe-ii" target="_blank">Soethe Infrastructure Intelligence</a> · SII-HiDRO v3.0',
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


# ── Estado da sessão (SII-HiDRO v3.0) ─────────────────────────────────────────
def init_state():
    # ── Estado de dois eixos ──────────────────────────────────────────────────
    st.session_state.setdefault('active_module', 'idf')       # 'projeto' | 'idf' | 'bacia' | 'vazao'
    st.session_state.setdefault('step', 0)                    # índice da etapa dentro do módulo ativo
    st.session_state.setdefault('project_dirty', False)        # booleano de modificação não gravada
    st.session_state.setdefault('bacia_confirmada', False)     # confirmação visual da bacia hidrográfica
    st.session_state.setdefault('lang', 'PT')

    # ── Campos estruturantes do projeto (únicos e globais) ────────────────────
    st.session_state.setdefault('responsavel', 'Pedro Luis Soethe Cursino')
    st.session_state.setdefault('nome_obra', 'Rodovia BR-163 km 812')
    st.session_state.setdefault('dispositivo', 'bueiro_grota')
    st.session_state.setdefault('tr_projeto', 25)
    st.session_state.setdefault('caminho_arquivo', None)

    # ── Variáveis do módulo IDF ───────────────────────────────────────────────
    st.session_state.setdefault('current_step', 1)            # Compatibilidade de stepper
    st.session_state.setdefault('ana_stations', [])           # [{codigo, nome, latitude, longitude, ...}]
    st.session_state.setdefault('ana_series_text', '')        # texto manual ou baixado
    st.session_state.setdefault('loaded_df', None)            # DataFrame unificado da série histórica
    st.session_state.setdefault('results', None)
    st.session_state.setdefault('calc_hash', None)            # Hash dos parâmetros no momento do cálculo
    st.session_state.setdefault('report_ctx', {})
    st.session_state.setdefault('proj_lat', -7.0375)
    st.session_state.setdefault('proj_lon', -55.4186)
    st.session_state.setdefault('proj_loc', 'Novo Progresso, PA')
    st.session_state.setdefault('estacao_input', '')
    st.session_state.setdefault('search_radius_km', 35)
    st.session_state.setdefault('selection_mode', 'single')   # 'single' ou 'idw'
    st.session_state.setdefault('idw_meta', None)
    st.session_state.setdefault('station_info', None)
    st.session_state.setdefault('idw_p', 2.0)                 # Expoente de distância IDW
    st.session_state.setdefault('last_clicked_coords', None)
    st.session_state.setdefault('uf_sel', 'PA')
    st.session_state.setdefault('download_info', None)
    st.session_state.setdefault('data_source_method', 'api')  # 'api', 'csv', 'manual'
    st.session_state.setdefault('api_source', 'hist')         # 'hist' ou 'tele'
    st.session_state.setdefault('isozona_escolhida', 'F')
    st.session_state.setdefault('isozona_origem', 'Automática (detectada no mapa)')
    st.session_state.setdefault('limiar_cobertura_pct', 90.0)
    st.session_state.setdefault('excluir_incompletos', True)
    st.session_state.setdefault('modo_ajuste_sherman', 'log')
    st.session_state.setdefault('year_start', None)
    st.session_state.setdefault('year_end', None)


init_state()


def mark_dirty():
    """Marca o projeto com modificações pendentes de gravação (project_dirty = True)."""
    st.session_state.project_dirty = True


def module_status(mod: str) -> str:
    """
    Retorna o status do módulo: 'locked' | 'todo' | 'done'.
    Regras estritas da especificação:
    - idf: 'todo' assim que existe coordenada; 'done' quando results existe e physical_consistency['is_valid'] é True.
    - bacia: 'todo' assim que existe coordenada; 'done' quando bacia_confirmada is True (confirmação visual).
    - vazao: 'locked' enquanto idf ou bacia não estiverem done. Se ambos done: 'todo' (ou 'done' se q_projeto_m3s calculado).
    - projeto: 'done' se salvo ou 'todo'.
    """
    m = str(mod).lower()
    if m == 'projeto':
        return 'done' if st.session_state.get('caminho_arquivo') else 'todo'

    lat = st.session_state.get('proj_lat')
    lon = st.session_state.get('proj_lon')
    tem_coords = (lat is not None and lon is not None and (lat != 0.0 or lon != 0.0))

    # Avaliação do status de IDF
    idf_done = False
    res = st.session_state.get('results')
    if res and isinstance(res, dict):
        pc = res.get('physical_consistency', {})
        if pc.get('is_valid') is True:
            idf_done = True

    if m == 'idf':
        if idf_done:
            return 'done'
        return 'todo' if tem_coords else 'locked'

    # Avaliação do status de Bacia
    bacia_confirmada = bool(st.session_state.get('bacia_confirmada', False))
    if m == 'bacia':
        if bacia_confirmada:
            return 'done'
        return 'todo' if tem_coords else 'locked'

    # Avaliação do status de Vazão
    if m == 'vazao':
        if not (idf_done and bacia_confirmada):
            return 'locked'
        if st.session_state.get('q_projeto_m3s') is not None:
            return 'done'
        return 'todo'

    return 'todo'


def render_context_bar(lang: str):
    """
    Barra de contexto fixa logo abaixo da barra superior, visível em todos os módulos.
    Exibe os campos estruturantes do projeto único:
    proj_lat, proj_lon, proj_loc, isozona_escolhida, isozona_origem, responsavel,
    nome_obra, dispositivo, tr_projeto, caminho_arquivo.
    """
    lat = st.session_state.get('proj_lat', 0.0)
    lon = st.session_state.get('proj_lon', 0.0)
    loc = st.session_state.get('proj_loc', '—')
    iso = st.session_state.get('isozona_escolhida', '—')
    iso_orig = st.session_state.get('isozona_origem', '')
    resp = st.session_state.get('responsavel', '—')
    obra = st.session_state.get('nome_obra', '—')
    disp = st.session_state.get('dispositivo', '—')
    tr = st.session_state.get('tr_projeto', 25)
    arq = st.session_state.get('caminho_arquivo')
    dirty = st.session_state.get('project_dirty', False)

    arq_nome = Path(arq).name if arq else ('* Projeto não salvo' if dirty else 'Novo Projeto')
    dirty_badge = " <span style='color:#d97706; font-weight:bold;' title='Modificações não salvas'>*</span>" if dirty else ""

    lbl_loc = t('proj_ctx_loc', lang)
    lbl_iso = t('proj_ctx_isozone', lang)
    lbl_resp = t('proj_ctx_author', lang)
    lbl_obra = t('proj_ctx_work', lang)
    lbl_disp = t('proj_ctx_device', lang)
    lbl_tr = t('proj_ctx_tr', lang)
    lbl_arq = t('proj_ctx_file', lang)

    html = f"""
    <div style="background-color:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:6px 12px; margin-top:-4px; margin-bottom:12px; font-size:0.83rem; color:#334155; display:flex; flex-wrap:wrap; gap:16px; align-items:center;">
        <div>📍 <b>{lbl_loc}:</b> {loc} <span style="color:#64748b; font-size:0.75rem;">({lat:.4f}°, {lon:.4f}°)</span></div>
        <div>🌧️ <b>{lbl_iso}:</b> <span style="background-color:#e0f2fe; color:#0369a1; padding:1px 6px; border-radius:4px; font-weight:700;">{iso}</span> <span style="color:#64748b; font-size:0.75rem;">({iso_orig})</span></div>
        <div>👤 <b>{lbl_resp}:</b> {resp}</div>
        <div>🏗️ <b>{lbl_obra}:</b> {obra} &middot; <i>{disp}</i></div>
        <div>⏱️ <b>{lbl_tr}:</b> {tr} anos</div>
        <div>📁 <b>{lbl_arq}:</b> <code style="color:#0f766e; background:#f0fdfa; padding:1px 4px; border-radius:3px;">{arq_nome}</code>{dirty_badge}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


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


# ── CSS de Layout Moderno e Regra das 4 Cores ─────────────────────────────────
st.markdown("""
<style>
/* Remoção de cabeçalhos vazios e layout compacto sem sidebar */
header[data-testid="stHeader"] {
    background: transparent !important;
}
div.block-container {
    padding-top: 1.2rem !important;
    padding-bottom: 2rem !important;
}
/* Destaque âmbar estrito (#d97706) para o botão Salvar com alterações pendentes */
div[data-testid="stButton"] button:has(p:contains("*")) {
    background-color: #d97706 !important;
    border-color: #b45309 !important;
    color: #ffffff !important;
}
</style>
""", unsafe_allow_html=True)


# ── Barra Superior (Horizontal Completa) ──────────────────────────────────────
lang = st.session_state.get('lang', 'PT')
L = UI[lang]
responsavel = st.session_state.get('responsavel', 'Pedro Luis Soethe Cursino')
localizacao = st.session_state.get('proj_loc', 'Novo Progresso, PA')
estacao = st.session_state.get('estacao_input', '')

c_brand, c_tabs, c_actions = st.columns([2.6, 5.0, 2.4], vertical_alignment="center")

with c_brand:
    st.markdown(render_brand_html(st.session_state.active_module, font_size='1.55rem'), unsafe_allow_html=True)

with c_tabs:
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    modules_nav = [
        ('projeto', '📁', t('mod_projeto', lang)),
        ('idf',     '🌧️', t('mod_idf', lang)),
        ('bacia',   '🏞️', t('mod_bacia', lang)),
        ('vazao',   '🌊', t('mod_vazao', lang)),
    ]
    for m_idx, (mod_id, icon, mod_name) in enumerate(modules_nav):
        status = module_status(mod_id)
        status_dot = "🟢" if status == 'done' else ("⚪" if status == 'todo' else "🔒")
        label = f"{icon} {mod_name} {status_dot}"
        is_active = (st.session_state.active_module == mod_id)
        btn_type = "primary" if is_active else "secondary"
        is_locked = (status == 'locked')
        tooltip = t('tooltip_locked_vazao', lang) if is_locked else f"Módulo {mod_name} ({t('status_' + status, lang)})"

        with [col_m1, col_m2, col_m3, col_m4][m_idx]:
            if st.button(
                label,
                key=f"top_tab_{mod_id}",
                disabled=is_locked,
                help=tooltip,
                use_container_width=True,
                type=btn_type,
            ):
                if not is_locked and st.session_state.active_module != mod_id:
                    st.session_state.active_module = mod_id
                    st.session_state.step = 0
                    st.rerun()

with c_actions:
    c_abrir, c_salvar, c_pop = st.columns([1.0, 1.2, 0.8])
    with c_abrir:
        if st.button(f"📂 {t('btn_open', lang)}", key="top_action_open", use_container_width=True):
            st.session_state.active_module = 'projeto'
            st.session_state.step = 0
            st.rerun()

    with c_salvar:
        is_dirty = st.session_state.get('project_dirty', False)
        save_label = f"💾 {t('btn_save', lang)} *" if is_dirty else f"💾 {t('btn_save', lang)}"
        save_type = "primary" if is_dirty else "secondary"
        if st.button(save_label, key="top_action_save", use_container_width=True, type=save_type,
                     help="Modificações pendentes não salvas! Clique para salvar." if is_dirty else "Salvar projeto (.siih)"):
            st.session_state.active_module = 'projeto'
            st.session_state.step = 1
            st.rerun()

    with c_pop:
        with st.popover("⚙️", use_container_width=True, help="Identificação do Responsável e Configurações"):
            st.markdown(f"#### ⚙️ {t('popover_title', lang)}")
            novo_resp = st.text_input(L['resp'], value=st.session_state.get('responsavel', 'Pedro Luis Soethe Cursino'))
            if novo_resp != st.session_state.get('responsavel'):
                st.session_state.responsavel = novo_resp
                st.session_state.project_dirty = True

            novo_obra = st.text_input("Nome da Obra", value=st.session_state.get('nome_obra', 'Rodovia BR-163 km 812'))
            if novo_obra != st.session_state.get('nome_obra'):
                st.session_state.nome_obra = novo_obra
                st.session_state.project_dirty = True

            novo_disp = st.text_input("Dispositivo", value=st.session_state.get('dispositivo', 'bueiro_grota'))
            if novo_disp != st.session_state.get('dispositivo'):
                st.session_state.dispositivo = novo_disp
                st.session_state.project_dirty = True

            novo_tr = st.number_input("TR de Projeto (anos)", min_value=2, max_value=500, value=int(st.session_state.get('tr_projeto', 25)))
            if novo_tr != st.session_state.get('tr_projeto'):
                st.session_state.tr_projeto = int(novo_tr)
                st.session_state.project_dirty = True

            st.divider()
            lang_opts = ['PT 🇧🇷', 'EN 🇺🇸']
            curr_l_idx = 0 if st.session_state.get('lang', 'PT') == 'PT' else 1
            sel_l_lbl = st.radio('🌐 Idioma / Language', lang_opts, index=curr_l_idx, horizontal=True)
            sel_l = sel_l_lbl.split()[0]
            if sel_l != st.session_state.get('lang', 'PT'):
                st.session_state.lang = sel_l
                st.rerun()

            st.caption(f"**Versão:** `SII-HiDRO v3.0`")
            if st.button("🔄 " + t('btn_reset_analysis', lang), use_container_width=True):
                st.session_state.results = None
                st.session_state.calc_hash = None
                st.session_state.loaded_df = None
                st.session_state.ana_series_text = ''
                st.session_state.download_info = None
                st.session_state.year_start = None
                st.session_state.year_end = None
                st.session_state.step = 0
                st.session_state.current_step = 1
                st.session_state.project_dirty = False
                st.rerun()

# ── Barra de Contexto Fixa do Projeto ─────────────────────────────────────────
render_context_bar(lang)

# ── Trilho de Etapas do Módulo Ativo ──────────────────────────────────────────
MODULE_STEPS = {
    'projeto': [('📂', 'stepper_proj_open'), ('💾', 'stepper_proj_save')],
    'idf':     [('📍', 'stepper_step1'), ('🌧️', 'stepper_step2'), ('🔍', 'stepper_step3'), ('📊', 'stepper_step4')],
    'bacia':   [('📐', 'stepper_basin_delineation'), ('🌾', 'stepper_basin_inputs')],
    'vazao':   [('⏱️', 'stepper_flow_tc'), ('🌊', 'stepper_flow_design')],
}

active_mod = st.session_state.active_module
steps = MODULE_STEPS.get(active_mod, MODULE_STEPS['idf'])
if st.session_state.step >= len(steps):
    st.session_state.step = 0

step_cols = st.columns(len(steps))
for s_idx, (icon, label_key) in enumerate(steps):
    with step_cols[s_idx]:
        is_active = (st.session_state.step == s_idx)
        btn_type = "primary" if is_active else "secondary"
        step_lbl = f"{icon} {t(label_key, lang)}"
        if st.button(step_lbl, key=f"step_btn_{active_mod}_{s_idx}", use_container_width=True, type=btn_type):
            st.session_state.step = s_idx
            if active_mod == 'idf':
                st.session_state.current_step = s_idx + 1
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
# DISPATCH DOS MÓDULOS (PROJETO, IDF, BACIA, VAZÃO)
# ══════════════════════════════════════════════════════════════════════════════
if active_mod == 'idf':
    curr_s = st.session_state.step + 1
    st.session_state.current_step = curr_s

    # ──────────────────────────────────────────────────────────────────────────
    # ETAPA 1: 📍 Localização do Projeto e Isozona
    # ──────────────────────────────────────────────────────────────────────────
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
                    if iso_det == 'FALLBACK':
                        st.session_state.isozona_escolhida = 'B'
                        st.session_state.isozona_origem = "Não detectada no mapa (adotado padrão B — favor selecionar)"
                        st.success(f"📍 {addr_f} (UF: **{nova_uf}** | Isozona padrão: **B**)")
                    else:
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
            if iso_det == 'FALLBACK':
                st.session_state.isozona_escolhida = 'B'
                st.session_state.isozona_origem = "Não detectada no mapa (adotado padrão B — favor selecionar)"
            else:
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

            # Contorno da bacia se já delineada
            b_res_idf = st.session_state.get('bacia_results')
            if b_res_idf and 'geometria' in b_res_idf:
                geom_idf = b_res_idf['geometria']
                morf_idf = b_res_idf.get('morfometria', {})
                if 'geojson_wgs84' in geom_idf:
                    try:
                        from shapely.geometry import shape as shp_shape
                        poly_wgs = shp_shape(geom_idf['geojson_wgs84'])
                        if poly_wgs.geom_type == 'Polygon':
                            pts = [[p[1], p[0]] for p in poly_wgs.exterior.coords]
                            folium.Polygon(
                                locations=pts,
                                color='#2563eb',
                                weight=2.5,
                                fill=True,
                                fill_color='#3b82f6',
                                fill_opacity=0.25,
                                tooltip=f"Bacia Hidrográfica Delimitada: {morf_idf.get('area_km2', 0):.2f} km²",
                            ).add_to(m)
                    except Exception:
                        pass

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
                if iso_det == 'FALLBACK':
                    st.session_state.isozona_escolhida = 'B'
                    st.session_state.isozona_origem = "Não detectada no mapa (adotado padrão B — favor selecionar)"
                else:
                    st.session_state.isozona_escolhida = iso_det
                    st.session_state.isozona_origem = f"Automática ({iso_det})"
                st.rerun()

        with col_isozona:
            st.markdown(f"**🗺️ {t('isozona_label', lang)}**")
            img_pin = desenhar_pin_mapa_isozonas(st.session_state.proj_lat, st.session_state.proj_lon)
            if img_pin is not None:
                st.image(img_pin, caption="Mapa Oficial de Isozonas de Chuvas Intensas do Brasil (Taborga, 1974)", use_container_width=True)

            iso_det = detectar_isozona_coordenadas(st.session_state.proj_lat, st.session_state.proj_lon)
            if iso_det == 'FALLBACK':
                st.warning("⚠️ Não foi possível identificar com segurança a Isozona no mapa nas coordenadas informadas (pixel de fronteira, grade ou fora dos limites). Adotou-se **Isozona B** como padrão — confirme ou selecione a Isozona correta abaixo.")
                idx_padrao = ISOZONAS.index(st.session_state.isozona_escolhida) if st.session_state.isozona_escolhida in ISOZONAS else 1
                iso_sel = st.selectbox(f"{t('isozona_label', lang)} (A a H)", ISOZONAS, index=idx_padrao)
                if iso_sel != 'B' or (st.session_state.isozona_origem and st.session_state.isozona_origem.startswith("Manual")):
                    st.caption(f"✏️ **{t('isozona_manual_badge', lang).format(iso_sel)}**")
                    st.session_state.isozona_origem = f"Manual ({iso_sel}) - Selecionada pelo projetista"
                else:
                    st.caption("⚠️ Padrão Isozona B adotado (não detectada no mapa)")
                    st.session_state.isozona_origem = "Não detectada no mapa (adotado padrão B — favor selecionar)"
                st.session_state.isozona_escolhida = iso_sel
            else:
                idx_padrao = ISOZONAS.index(st.session_state.isozona_escolhida) if st.session_state.isozona_escolhida in ISOZONAS else ISOZONAS.index(iso_det)
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
            st.session_state.step = 1
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
                st.session_state.step = 0
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
                                st.session_state.station_info = {
                                    'codigo': cod_sel,
                                    'nome': est_obj['nome'],
                                    'latitude': est_obj.get('latitude'),
                                    'longitude': est_obj.get('longitude'),
                                    'distancia_km': est_obj.get('distancia_km', 0.0),
                                }
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
                        # Checagem de co-localização / arranjo degenerado no preview
                        colocadas_preview = False
                        if len(estacoes_sel) >= 3 and n_eff_preview < 2.0:
                            colocadas_preview = True
                        elif len(estacoes_sel) >= 2:
                            relevantes = [e['codigo'] for e in estacoes_sel if pesos_preview.get(e['codigo'], 0) >= 2.0]
                            dists_rel = [dists_map[c] for c in relevantes]
                            for i in range(len(dists_rel)):
                                for j in range(i + 1, len(dists_rel)):
                                    if abs(dists_rel[i] - dists_rel[j]) < 2.0 and min(dists_rel[i], dists_rel[j]) < 3.0:
                                        colocadas_preview = True
                                        break
                                if colocadas_preview:
                                    break

                        if colocadas_preview:
                            st.info(t('idw_colocated_alert', lang).format(n_eff_preview))

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
                                                'latitude': e.get('latitude'),
                                                'longitude': e.get('longitude'),
                                            }
                                            for e in estacoes_sel if e['codigo'] in series_dict
                                        ],
                                        'coords': (st.session_state.proj_lat, st.session_state.proj_lon),
                                        'p': idw_p,
                                        'n_eff': n_eff_val,
                                    }
                                    st.session_state.station_info = None
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
                st.session_state.step = 2
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
                st.session_state.step = 1
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
            n_pos = diag_prev.get('n_apos_descarte', diag_prev.get('n', len(df_temp)))
            n_raw = diag_prev.get('n_bruto', len(df_temp))
            pct_d = diag_prev.get('pct_descarte', 0.0)
            desc_info = f" ({pct_d:.0f}% descartados)" if (n_raw > n_pos and pct_d > 0) else ""
            q1.metric("Anos na Série", f"{n_pos} de {n_raw}{desc_info}")
            cv = diag_prev.get('cv', 0.0)
            cv_status = "✅ Normal (0.15 - 0.30)" if (0.15 <= cv <= 0.30) else "⚠️ Fora do intervalo usual"
            q2.metric("Coef. Variação (CV)", f"{cv:.2f}", cv_status)
            mk = diag_prev.get('mann_kendall', {})
            mk_trend = mk.get('tendencia_significativa', mk.get('trend', False))
            mk_status = "⚠️ Tendência detectada" if mk_trend else "✅ Estacionária"
            q3.metric("Mann-Kendall (τ)", f"{mk.get('tau', 0.0):.3f}", mk_status)

            desc_list = diag_prev.get('anos_descartados', [])
            if desc_list:
                with st.expander(f"📋 {t('diag_discarded_years', lang)} ({len(desc_list)} anos)", expanded=False):
                    df_desc = pd.DataFrame([{
                        'Ano': item.get('ano', '—'),
                        'Precipitação (mm)': item.get('precipitacao', item.get('valor', 0.0)),
                        'Dias Válidos': item.get('dias_validos', '—'),
                        'Motivo': item.get('motivo', '—'),
                    } for item in desc_list])
                    st.dataframe(df_desc, use_container_width=True, hide_index=True)

            outs = diag_prev.get('outliers', [])
            if outs:
                for o in outs:
                    st.warning(f"⚠️ {t('diag_outlier_found', lang).format(o.get('ano', '—'), o.get('valor', 0.0), o.get('teste', '—'))}")

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
                        idw_p=float(st.session_state.get('idw_p', 2.0)),
                    )
                    st.session_state.calc_hash = h
                    st.session_state.report_ctx = {
                        'responsavel': responsavel,
                        'localizacao': localizacao,
                        'estacao': estacao or st.session_state.estacao_input or '—',
                        'lang': lang,
                        'coords': (float(st.session_state.proj_lat), float(st.session_state.proj_lon)),
                        'idw_meta': st.session_state.idw_meta,
                        'station_info': st.session_state.get('station_info'),
                        'search_radius_km': float(st.session_state.get('search_radius_km', 35)),
                    }
                    st.session_state.current_step = 4
                    st.session_state.step = 3
                    st.session_state.project_dirty = True
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
                st.session_state.step = 2
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
                idw_p=float(st.session_state.get('idw_p', 2.0)),
            )
            params_changed = (st.session_state.calc_hash is not None and current_hash != st.session_state.calc_hash)

            if params_changed:
                st.warning(f"⚠️ **{t('hash_warning_title', lang)}**\n\n{t('hash_warning_desc', lang)}")
                if st.button(f"⚡ {t('btn_run_analysis', lang)} (Recalcular com parâmetros atuais)", type='primary', use_container_width=True):
                    st.session_state.current_step = 3
                    st.session_state.step = 2
                    st.rerun()

            cons = results.get('physical_consistency', {})
            is_cons_ok = bool(cons.get('is_valid', False) or cons.get('status') == 'OK')
            if is_cons_ok:
                st.success(t('phys_cons_ok', lang))
            else:
                st.error(f"🚨 **{t('phys_cons_title', lang)} — Violações de Consistência Detectadas**")
                with st.container(border=True):
                    for v in cons.get('violacoes_tempo', []):
                        msg = v.get('msg', str(v)) if isinstance(v, dict) else str(v)
                        st.markdown(f"- {msg}")
                    for v in cons.get('violacoes_freq', []):
                        msg = v.get('msg', str(v)) if isinstance(v, dict) else str(v)
                        st.markdown(f"- {msg}")
                    for v in cons.get('violacoes_param', []):
                        msg = v.get('msg', str(v)) if isinstance(v, dict) else str(v)
                        st.markdown(f"- {msg}")

            sherman = results['sherman_params']
            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric(L['n_years'], results['n_samples'])
            m2.metric('μ (Gumbel)', f"{results['mu']:.2f} mm")
            m3.metric('σ (Gumbel)', f"{results['sigma']:.2f} mm")
            m4.metric('R² (Sherman)', f"{sherman['R²']:.4f}")
            m5.metric('RMSE', f"{sherman['RMSE']:.2f} mm/h")
            m6.metric('Erro Médio Celular', f"{sherman.get('erro_medio_celula', 0.0):.2f}%")

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
                            mk_sig = mk_info.get('tendencia_significativa', mk_info.get('trend', False))
                            st.markdown(f"- **{t('diag_mk_title', lang)}:** τ=`{tau_val:.4f}`, p-valor=`{pval:.4f}` — {t('diag_mk_trend', lang).format(tau_val, pval) if mk_sig else t('diag_mk_no_trend', lang).format(tau_val, pval)}")

                    desc_anos = results.get('anos_descartados', [])
                    if desc_anos:
                        st.markdown(f"**{t('diag_discarded_years', lang)}:**")
                        df_desc_r = pd.DataFrame([{
                            'Ano': a.get('ano', '—'),
                            'Precipitação (mm)': a.get('precipitacao', a.get('valor', 0.0)),
                            'Dias Válidos': a.get('dias_validos', '—'),
                            'Motivo': a.get('motivo', '—'),
                        } for a in desc_anos])
                        st.dataframe(df_desc_r, use_container_width=True, hide_index=True)

            with t2:
                st.plotly_chart(fg, use_container_width=True)
                st.dataframe(results['gumbel_df'], use_container_width=True, hide_index=True)
                csv_g = results['gumbel_df'].to_csv(index=False).encode('utf-8')
                st.download_button(f"📥 {t('btn_dl_csv', lang)} (Gumbel)", data=csv_g, file_name="gumbel_analise.csv", mime="text/csv")

                st.plotly_chart(fp, use_container_width=True)
                df_disagg_disp = results['disagg_df'].reset_index()
                st.dataframe(df_disagg_disp, height=320, use_container_width=True, hide_index=True)
                csv_d = df_disagg_disp.to_csv(index=False).encode('utf-8')
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
                df_idf_disp = results['idf_df'].reset_index()
                st.dataframe(df_idf_disp, height=320, use_container_width=True, hide_index=True)
                csv_i = df_idf_disp.to_csv(index=False).encode('utf-8')
                st.download_button(f"📥 {t('btn_dl_csv', lang)} (Curvas IDF)", data=csv_i, file_name="curvas_idf.csv", mime="text/csv")

                A, B, C, D = sherman['A'], sherman['B'], sherman['C'], sherman['D']
                st.markdown(f"### {L['sherman_eq']}")
                st.latex(r"i = \frac{%.4f \cdot TR^{%.4f}}{(t + %.4f)^{%.4f}}" % (A, B, C, D))

                df_sherman_params = pd.DataFrame([
                    {
                        'Parâmetro': p,
                        'Valor Ajustado': f"{sherman[p]:.4f}",
                        'Erro Padrão': f"{sherman.get('se_' + p, 0.0):.4f}",
                        'IC 95% Inferior': f"{sherman.get('ci_' + p, (0, 0))[0]:.4f}" if p in ('B', 'D') else f"{sherman.get('ci_' + p, (0, 0))[0]:.2f}",
                        'IC 95% Superior': f"{sherman.get('ci_' + p, (0, 0))[1]:.4f}" if p in ('B', 'D') else f"{sherman.get('ci_' + p, (0, 0))[1]:.2f}",
                        'Faixa Típica (Literatura)': f"{SHERMAN_TYPICAL_RANGES[p][0]:g} a {SHERMAN_TYPICAL_RANGES[p][1]:g}",
                    }
                    for p in ('A', 'B', 'C', 'D')
                ])
                st.dataframe(df_sherman_params, use_container_width=True, hide_index=True)

                g1, g2, g3, g4 = st.columns(4)
                g1.metric('R² (Determinação)', f"{sherman['R²']:.4f}")
                g2.metric('RMSE', f"{sherman['RMSE']:.2f} mm/h")
                g3.metric(t('max_cell_error', lang), f"{sherman.get('erro_max_celula', 0.0):.2f}%")
                g4.metric(t('mean_cell_error', lang), f"{sherman.get('erro_medio_celula', 0.0):.2f}%")

                for p_name, b_val in sherman.get('bounds_touched', []):
                    st.warning(t('bound_touch_alert', lang).format(p_name, sherman[p_name], b_val))

            st.divider()
            st.subheader(L['downloads'])
            if params_changed:
                st.error(f"🚫 {t('export_blocked_msg', lang)}")

            ctx = st.session_state.report_ctx
            d1, d2 = st.columns(2)

            is_consolidado = bool(st.session_state.get('bacia_results') and st.session_state.get('vazao_results'))
            rep_app_name = 'SII-HiDRO' if is_consolidado else brand_text('idf')
            pdf_fn = 'memorial_calculo_siihidro.pdf' if is_consolidado else 'memorial_calculo_idf.pdf'
            docx_fn = 'memorial_calculo_siihidro.docx' if is_consolidado else 'memorial_calculo_idf.docx'

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
                        station_info=ctx.get('station_info'),
                        search_radius_km=float(ctx.get('search_radius_km', 35)),
                        app_name=rep_app_name,
                        bacia_results=st.session_state.get('bacia_results'),
                        vazao_results=st.session_state.get('vazao_results'),
                    ) if not params_changed else b''
                    st.download_button(
                        L['dl_pdf'],
                        data=pdf_bytes,
                        file_name=pdf_fn,
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
                        station_info=ctx.get('station_info'),
                        search_radius_km=float(ctx.get('search_radius_km', 35)),
                        app_name=rep_app_name,
                        bacia_results=st.session_state.get('bacia_results'),
                        vazao_results=st.session_state.get('vazao_results'),
                    ) if not params_changed else b''
                    st.download_button(
                        L['dl_word'],
                        data=docx_bytes,
                        file_name=docx_fn,
                        mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        use_container_width=True,
                        disabled=params_changed,
                    )
                except Exception as e:
                    st.warning(f'Word: {e}')

# ══════════════════════════════════════════════════════════════════════════════
# DISPATCH DO MÓDULO PROJETO (ABRIR OU CRIAR · SALVAR)
# ══════════════════════════════════════════════════════════════════════════════
elif active_mod == 'projeto':
    curr_step_proj = st.session_state.get('step', 0)
    if curr_step_proj == 0:
        st.subheader(f"📂 {t('stepper_proj_open', lang)}")
        st.caption("Crie um novo projeto hidrológico ou abra um projeto existente (.siih)." if lang == 'PT' else "Create a new hydrological project or open an existing (.siih) project.")

        c_novo, c_abrir_card = st.columns(2)
        with c_novo:
            with st.container(border=True):
                st.markdown("### ✨ " + ("Novo Projeto" if lang == 'PT' else "New Project"))
                st.write(
                    "Inicia um projeto hidrológico em branco, mantendo o padrão de coordenadas e parâmetros configurados."
                    if lang == 'PT' else
                    "Starts a blank hydrological project, maintaining default configured coordinates and parameters."
                )
                if st.button("➕ " + ("Iniciar Novo Projeto" if lang == 'PT' else "Start New Project"), type="primary", use_container_width=True):
                    st.session_state.caminho_arquivo = None
                    st.session_state.results = None
                    st.session_state.calc_hash = None
                    st.session_state.loaded_df = None
                    st.session_state.ana_series_text = ''
                    st.session_state.download_info = None
                    st.session_state.bacia_confirmada = False
                    st.session_state.project_dirty = False
                    st.session_state.active_module = 'idf'
                    st.session_state.step = 0
                    st.session_state.current_step = 1
                    st.rerun()

        with c_abrir_card:
            with st.container(border=True):
                st.markdown("### 📂 " + ("Abrir Arquivo de Projeto (.siih)" if lang == 'PT' else "Open Project File (.siih)"))
                st.write(
                    "Abra um projeto salvo para auditar, revisar ou continuar análises hidrológicas."
                    if lang == 'PT' else
                    "Open a saved project to audit, review or continue hydrological analyses."
                )
                uploaded_siih = st.file_uploader(
                    "Carregar arquivo .siih" if lang == 'PT' else "Upload .siih file",
                    type=["siih", "json"],
                    help="Arquivo de projeto SII-HiDRO (.siih) em conformidade com o esquema siih/1" if lang == 'PT' else "SII-HiDRO project file (.siih) conforming to siih/1 schema",
                    key="proj_file_uploader",
                )
                if uploaded_siih is not None:
                    try:
                        proj_loaded = project.abrir_projeto(uploaded_siih.getvalue(), recalcular=True)
                        audit = proj_loaded["status_auditoria"]

                        st.divider()
                        st.markdown("#### 🛡️ " + ("Auditoria de Integridade e Revalidação (.siih)" if lang == 'PT' else "Integrity & Revalidation Audit (.siih)"))

                        # 1. Integridade do Hash
                        if audit.get("hash_adulterado"):
                            st.error(
                                "🚨 " + ("Hash SHA-256 Adulterado! Os dados pluviométricos ou parâmetros divergem do snapshot original. Arquivo possivelmente corrompido ou editado manualmente."
                                         if lang == 'PT' else
                                         "Tampered SHA-256 Hash! Rainfall data or parameters diverge from original snapshot. File possibly corrupted or manually edited.")
                            )
                        else:
                            st.success(
                                "🟢 " + ("Integridade SHA-256 Verificada: Os dados de entrada conferem rigorosamente com a assinatura criptográfica."
                                         if lang == 'PT' else
                                         "SHA-256 Integrity Verified: Input data strictly matches cryptographic signature.")
                            )

                        # 2. Versão do App e Changelog
                        aceite_versao = True
                        if audit.get("versao_anterior"):
                            st.warning(
                                "⚠️ " + (f"Projeto criado na versão **{audit['app_version']}** (versão atual do app: **{project.CURRENT_APP_VERSION}**)."
                                         if lang == 'PT' else
                                         f"Project created in version **{audit['app_version']}** (current app version: **{project.CURRENT_APP_VERSION}**).")
                            )
                            with st.expander("📜 " + ("Ver Mudanças Metodológicas entre Versões (CHANGELOG_BEHAVIOR.md)" if lang == 'PT' else "View Methodological Changes between Versions (CHANGELOG_BEHAVIOR.md)"), expanded=False):
                                st.markdown(audit.get("changelog_behavior", ""))
                            aceite_versao = st.checkbox(
                                "Declaro ciência das mudanças de formulação e comportamento técnico entre as versões."
                                if lang == 'PT' else
                                "I acknowledge the methodological changes and technical behavior between versions.",
                                key="aceite_versao_anterior",
                                value=False,
                            )

                        # 3. Divergência de Isozona
                        iso_escolhida = audit.get("isozona_gravada")
                        if audit.get("isozona_divergente"):
                            loc_dict = proj_loaded['dados'].get('local', {})
                            st.warning(
                                "⚠️ " + (f"Divergência de Isozona Geográfica: As coordenadas ({loc_dict.get('lat', 0):.4f}°, {loc_dict.get('lon', 0):.4f}°) "
                                         f"correspondem à Isozona **{audit['isozona_detectada']}** no mapa oficial, mas o projeto foi gravado com a Isozona **{audit['isozona_gravada']}**."
                                         if lang == 'PT' else
                                         f"Geographical Isozone Divergence: Coordinates ({loc_dict.get('lat', 0):.4f}°, {loc_dict.get('lon', 0):.4f}°) "
                                         f"correspond to Isozone **{audit['isozona_detectada']}** on the official map, but project was saved with Isozone **{audit['isozona_gravada']}**.")
                            )
                            iso_opts = [
                                f"{audit['isozona_gravada']} (" + ("Manter gravada no arquivo" if lang == 'PT' else "Keep saved in file") + ")",
                                f"{audit['isozona_detectada']} (" + ("Adotar detectada nas coordenadas" if lang == 'PT' else "Adopt detected at coordinates") + ")"
                            ]
                            iso_sel_radio = st.radio(
                                "Escolha qual Isozona adotar para os cálculos:" if lang == 'PT' else "Choose which Isozone to adopt for calculations:",
                                iso_opts,
                                index=0,
                                key="radio_iso_abertura",
                            )
                            iso_escolhida = iso_sel_radio.split()[0]

                        # 4. Divergência de Resultados (> 0,5%)
                        if audit.get("divergencia_critica"):
                            st.warning(
                                "⚠️ " + ("Divergência nos Resultados Recalculados a Quente (> 0,5% em relação ao snapshot gravado):"
                                         if lang == 'PT' else
                                         "Divergence in Hot Recalculated Results (> 0.5% compared to saved snapshot):")
                            )
                            df_div = pd.DataFrame([
                                {
                                    'Métrica / Parâmetro': k,
                                    'Snapshot Gravado': f"{v['snapshot']:.4f}",
                                    'Recalculado a Quente': f"{v['recalculado']:.4f}",
                                    'Divergência (%)': f"{v['diff_pct']:.2f}%",
                                }
                                for k, v in audit.get("divergencias_metricas", {}).items()
                            ])
                            st.dataframe(df_div, use_container_width=True, hide_index=True)
                        elif proj_loaded.get("recalculado"):
                            st.success(
                                "✅ " + ("Recálculo Hidrológico Concluído: Resultados a quente idênticos ao snapshot do arquivo."
                                         if lang == 'PT' else
                                         "Hydrological Recalculation Succeeded: Hot results match file snapshot.")
                            )

                        # Botão para efetivar o carregamento no session_state
                        pode_abrir = True
                        if audit.get("versao_anterior") and not aceite_versao:
                            pode_abrir = False
                            st.caption("⚠️ " + ("Marque a confirmação de ciência da versão anterior acima para habilitar o carregamento."
                                                if lang == 'PT' else
                                                "Check the version acknowledgment above to enable loading."))

                        if st.button("📥 " + ("Carregar Projeto no SII-HiDRO" if lang == 'PT' else "Load Project into SII-HiDRO"), type="primary", use_container_width=True, disabled=not pode_abrir):
                            project.carregar_projeto_no_session_state(proj_loaded, isozona_escolhida=iso_escolhida)
                            st.success("✅ " + ("Projeto restaurado com sucesso! Redirecionando para o Módulo IDF..."
                                               if lang == 'PT' else
                                               "Project successfully restored! Redirecting to IDF Module..."))
                            st.rerun()

                    except Exception as e:
                        st.error(f"❌ Erro ao abrir arquivo .siih: {e}")

        st.divider()
        st.markdown("### 📋 " + ("Informações Estruturantes do Projeto Ativo" if lang == 'PT' else "Active Project Structural Information"))
        with st.container(border=True):
            col_i1, col_i2 = st.columns(2)
            with col_i1:
                st.markdown(f"**{t('proj_ctx_author', lang)}:** {st.session_state.get('responsavel', '—')}")
                st.markdown(f"**{t('proj_ctx_work', lang)}:** {st.session_state.get('nome_obra', '—')}")
                st.markdown(f"**{t('proj_ctx_device', lang)}:** {st.session_state.get('dispositivo', '—')}")
                st.markdown(f"**{t('proj_ctx_tr', lang)}:** {st.session_state.get('tr_projeto', 25)} " + ("anos" if lang == 'PT' else "years"))
            with col_i2:
                st.markdown(f"**{t('proj_ctx_loc', lang)}:** {st.session_state.get('proj_loc', '—')}")
                st.markdown(f"**Coordenadas:** `{st.session_state.get('proj_lat', 0.0):.4f}°`, `{st.session_state.get('proj_lon', 0.0):.4f}°`")
                st.markdown(f"**{t('proj_ctx_isozone', lang)}:** {st.session_state.get('isozona_escolhida', '—')} (*{st.session_state.get('isozona_origem', '')}*)")
                dirty_status = ("⚠️ Alterações pendentes de gravação" if st.session_state.get('project_dirty') else "✅ Sem alterações pendentes") if lang == 'PT' else ("⚠️ Unsaved pending changes" if st.session_state.get('project_dirty') else "✅ No pending changes")
                st.markdown(f"**Status:** {dirty_status}")

    elif curr_step_proj == 1:
        st.subheader(f"💾 {t('stepper_proj_save', lang)}")
        st.caption("Grave o projeto hidrológico no formato auditável e versionado .siih." if lang == 'PT' else "Save hydrological project in auditable and versioned .siih format.")

        st.markdown(f"### 📜 {t('contract_tbl_title', lang)}")
        st.markdown(
            "> **" + ("Regra de Ouro da Auditoria SII-HiDRO:" if lang == 'PT' else "SII-HiDRO Audit Golden Rule:") + "** "
            "*" + ("Guarde entrada, recalcule saída." if lang == 'PT' else "Save input, recalculate output.") + "* " +
            ("Séries brutas, decisões, justificativas e o polígono da bacia são entrada e ficam gravados. "
             "Gumbel, Sherman, matriz IDF e vazão são saída, nascem de novo a cada abertura, e o snapshot gravado "
             "serve estritamente para detecção de divergências de versão."
             if lang == 'PT' else
             "Raw series, decisions, rationales and the basin polygon are input and remain stored. "
             "Gumbel, Sherman, IDF matrix and discharge are output, recalculated on each open, and the stored snapshot "
             "serves strictly for version divergence detection.")
        )

        df_contrato = pd.DataFrame([
            {
                t('col_contract_comp', lang): "Metadados & Identificação" if lang == 'PT' else "Metadata & Identification",
                t('col_contract_type', lang): "Entrada" if lang == 'PT' else "Input",
                t('col_contract_saved', lang): "Sim (Responsável, Obra, Dispositivo, TR)" if lang == 'PT' else "Yes (Author, Work, Device, TR)",
                t('col_contract_open', lang): "Restaurado no session_state" if lang == 'PT' else "Restored into session_state",
            },
            {
                t('col_contract_comp', lang): "Localização & Isozona" if lang == 'PT' else "Location & Isozone",
                t('col_contract_type', lang): "Entrada" if lang == 'PT' else "Input",
                t('col_contract_saved', lang): "Sim (Lat, Lon WGS84, Isozona, Origem, Justificativa)" if lang == 'PT' else "Yes (Lat, Lon WGS84, Isozone, Source, Rationale)",
                t('col_contract_open', lang): "Restaurado e revalidado geograficamente" if lang == 'PT' else "Restored and geographically revalidated",
            },
            {
                t('col_contract_comp', lang): "Séries Pluviométricas Brutas" if lang == 'PT' else "Raw Rainfall Series",
                t('col_contract_type', lang): "Entrada" if lang == 'PT' else "Input",
                t('col_contract_saved', lang): "Sim (Anos, Chuvas, Dias Válidos por estação/IDW)" if lang == 'PT' else "Yes (Years, Rainfall, Valid Days per station/IDW)",
                t('col_contract_open', lang): "Restaurado (auditável sem internet)" if lang == 'PT' else "Restored (auditable without internet)",
            },
            {
                t('col_contract_comp', lang): "Decisões e Filtros do Projetista" if lang == 'PT' else "Designer Decisions & Filters",
                t('col_contract_type', lang): "Entrada" if lang == 'PT' else "Input",
                t('col_contract_saved', lang): "Sim (Filtros, Limiares, Anos Reincluídos)" if lang == 'PT' else "Yes (Filters, Thresholds, Reincluded Years)",
                t('col_contract_open', lang): "Restaurado para aplicação no pipeline" if lang == 'PT' else "Restored for execution in pipeline",
            },
            {
                t('col_contract_comp', lang): "Polígono & MDE da Bacia" if lang == 'PT' else "Basin Polygon & DEM",
                t('col_contract_type', lang): "Entrada" if lang == 'PT' else "Input",
                t('col_contract_saved', lang): "Sim (GeoJSON WGS84, Exutório, Metadados MDE)" if lang == 'PT' else "Yes (GeoJSON WGS84, Outlet, DEM Metadata)",
                t('col_contract_open', lang): "Restaurado (reprojeção SIRGAS 2000 UTM)" if lang == 'PT' else "Restored (SIRGAS 2000 UTM reprojection)",
            },
            {
                t('col_contract_comp', lang): "Ajustes Gumbel, Sherman & Curvas IDF" if lang == 'PT' else "Gumbel, Sherman Fits & IDF Curves",
                t('col_contract_type', lang): "Saída" if lang == 'PT' else "Output",
                t('col_contract_saved', lang): "Apenas snapshot de comparação (μ, σ, A, B, C, D, hash)" if lang == 'PT' else "Comparison snapshot only (μ, σ, A, B, C, D, hash)",
                t('col_contract_open', lang): "RECALCULADO A QUENTE (alerta se > 0,5%)" if lang == 'PT' else "HOT RECALCULATED (alert if > 0.5%)",
            },
            {
                t('col_contract_comp', lang): "Tempos de Concentração & Vazão" if lang == 'PT' else "Times of Concentration & Discharge",
                t('col_contract_type', lang): "Saída" if lang == 'PT' else "Output",
                t('col_contract_saved', lang): "Apenas snapshot de comparação (tc e Q de projeto)" if lang == 'PT' else "Comparison snapshot only (tc and design Q)",
                t('col_contract_open', lang): "RECALCULADO A QUENTE com as curvas IDF" if lang == 'PT' else "HOT RECALCULATED with IDF curves",
            },
        ])
        st.dataframe(df_contrato, use_container_width=True, hide_index=True)

        st.divider()
        with st.container(border=True):
            st.markdown("### 💾 " + ("Gravar Arquivo de Projeto (.siih)" if lang == 'PT' else "Save Project File (.siih)"))
            caminho_atual = st.session_state.get('caminho_arquivo')
            if caminho_atual:
                st.markdown(f"**{t('proj_ctx_file', lang)}:** `{caminho_atual}`")
            else:
                st.markdown(f"**{t('proj_ctx_file', lang)}:** *" + ("Novo Projeto (ainda não salvo em disco)" if lang == 'PT' else "New Project (not saved to disk yet)") + "*")

            if st.session_state.get('project_dirty', False):
                st.warning("⚠️ " + ("Há alterações pendentes no projeto que ainda não foram salvas." if lang == 'PT' else "There are pending unsaved changes in the project."))
            else:
                st.success("✅ " + ("Todas as alterações do projeto estão salvas." if lang == 'PT' else "All project changes are saved."))

            try:
                siih_bytes = project.salvar_projeto(filepath=None, state=st.session_state)
                obra_slug = st.session_state.get('nome_obra', 'hidro').replace(' ', '_').replace('/', '-').lower()
                nome_sugestao = f"projeto_{obra_slug}.siih"
                tamanho_kb = len(siih_bytes) / 1024
                comp_tag = " (Gzip Comprimido)" if siih_bytes.startswith(b'\x1f\x8b') else " (JSON UTF-8)"

                c_save_btn, c_save_info = st.columns([1.5, 2.5])
                with c_save_btn:
                    if st.download_button(
                        label=f"💾 {t('btn_save', lang)} (.siih)",
                        data=siih_bytes,
                        file_name=nome_sugestao,
                        mime="application/octet-stream",
                        type="primary" if st.session_state.get('project_dirty') else "secondary",
                        use_container_width=True,
                    ):
                        st.session_state.project_dirty = False
                        st.session_state.caminho_arquivo = nome_sugestao
                        st.success("✅ " + ("Projeto baixado e salvo com sucesso!" if lang == 'PT' else "Project downloaded and saved successfully!"))
                        st.rerun()

                with c_save_info:
                    st.caption(f"**Arquivo:** `{nome_sugestao}` ({tamanho_kb:.1f} KB){comp_tag} · Esquema: `siih/1`")
            except Exception as e:
                st.error(f"Erro ao gerar arquivo do projeto: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# DISPATCH DO MÓDULO BACIA (DELINEAÇÃO · INSUMOS E PARÂMETROS)
# ══════════════════════════════════════════════════════════════════════════════
elif active_mod == 'bacia':
    curr_step_bacia = st.session_state.get('step', 0)
    p_lat = st.session_state.get('proj_lat')
    p_lon = st.session_state.get('proj_lon')
    p_loc = st.session_state.get('proj_loc', '—')

    if p_lat is None or p_lon is None or (p_lat == 0.0 and p_lon == 0.0):
        st.error("🔒 **Coordenadas do projeto não definidas.** Por favor, localize o projeto no Módulo IDF ou no cabeçalho.")
    else:
        b_res = st.session_state.get('bacia_results')

        # ──────────────────────────────────────────────────────────────────────
        # ETAPA 0: 📐 Delineação & Divisor Topográfico
        # ──────────────────────────────────────────────────────────────────────
        if curr_step_bacia == 0:
            st.subheader(f"📐 {t('stepper_basin_delineation', lang)}")
            st.caption(
                "Delineie o divisor de águas a partir do MDE e inspecione o polígono sobre a imagem de satélite. "
                "A confirmação visual explícita é obrigatória para habilitar o Módulo Vazão."
                if lang == 'PT' else
                "Delineate watershed divide from DEM and inspect polygon over satellite imagery. "
                "Explicit visual confirmation is mandatory to unlock Flow Module."
            )

            col_cfg, col_diag = st.columns([1.0, 1.0])

            with col_cfg:
                with st.container(border=True):
                    st.markdown(f"##### ⚙️ {t('basin_exutory_title', lang)}")
                    st.markdown(
                        f"- 📍 **Local:** {p_loc}\n"
                        f"- 🌐 **Exutório:** `{p_lat:.4f}°, {p_lon:.4f}°` (WGS84)\n"
                        f"- ℹ️ *{t('basin_single_coord_note', lang)}*"
                    )

                    fonte_opts = [
                        "FABDEM 30m (Recomendado)",
                        "Copernicus GLO-30",
                        "MERIT Hydro",
                        "Upload GeoTIFF próprio",
                    ]
                    fonte_sel = st.selectbox(t('basin_mde_source', lang), fonte_opts, index=0)

                    up_mde = None
                    if "Upload" in fonte_sel:
                        up_mde = st.file_uploader("Selecione o arquivo GeoTIFF do MDE (.tif)", type=['tif', 'tiff'])

                    raio_snap = st.number_input(
                        t('basin_snap_radius', lang),
                        min_value=30.0,
                        max_value=300.0,
                        value=150.0,
                        step=10.0,
                        help="Distância máxima de tolerância para deslocar o exutório até o talvegue de maior acumulação."
                    )

                    btn_delinear = st.button(
                        f"🚀 {t('basin_btn_delineate', lang)}",
                        type="primary",
                        use_container_width=True,
                    )

            with col_diag:
                with st.container(border=True):
                    st.markdown("##### 🛡️ Diagnóstico e Validação do Divisor")
                    if b_res:
                        snap_d = b_res.get('snap_dist_m', 0.0)
                        conf_ana = b_res.get('conferencia_ana', {})
                        morf = b_res.get('morfometria', {})

                        # Snap badge
                        if snap_d <= 50.0:
                            st.success(f"✅ **Snap do Exutório:** {snap_d:.1f} m (Alinhamento excelente ao talvegue)")
                        elif snap_d <= 150.0:
                            st.warning(f"⚠️ **Snap do Exutório:** {snap_d:.1f} m (Dentro do limite de tolerância de 150 m)")
                        else:
                            st.error(f"❌ **Snap Excedido:** {snap_d:.1f} m (> 150 m). Reposicione o exutório.")

                        # ANA BHO badge
                        ana_diff = conf_ana.get('divergencia_pct', 0.0)
                        ana_area = conf_ana.get('area_ana_km2', 0.0)
                        if conf_ana.get('alerta'):
                            st.warning(f"⚠️ **Conferência ANA BHO:** Divergência de {ana_diff:.1f}% ({morf.get('area_km2', 0):.2f} km² vs ANA {ana_area:.2f} km²)")
                        else:
                            st.success(f"✅ **Conferência ANA BHO:** Aderência de {100.0 - ana_diff:.1f}% ({morf.get('area_km2', 0):.2f} km² vs ANA {ana_area:.2f} km²)")

                        # Geodetic vs UTM validation badge
                        geod_diff = morf.get('diff_area_pct', 0.0)
                        st.info(f"🌐 **Validação Geodésica:** Diferença UTM vs Geodésica de {geod_diff:.4f}% (< 1% rigor)")

                        st.divider()
                        st.markdown("###### 👁️ Confirmação Obrigatória do Projetista")
                        st.caption(t('basin_confirm_warning', lang))

                        is_conf = bool(st.session_state.get('bacia_confirmada', False))
                        if not is_conf:
                            if st.button(f"✅ {t('basin_confirm_btn', lang)}", type="primary", use_container_width=True):
                                st.session_state.bacia_confirmada = True
                                st.session_state.project_dirty = True
                                st.rerun()
                        else:
                            st.success(f"🟢 **{t('basin_confirmed_badge', lang)}**")
                            if st.button(f"🔄 {t('basin_undo_confirm', lang)}", use_container_width=True):
                                st.session_state.bacia_confirmada = False
                                st.session_state.project_dirty = True
                                st.rerun()
                    else:
                        st.info("ℹ️ Clique no botão **Delinear Bacia Hidrográfica** para carregar o MDE e processar a bacia.")

            if btn_delinear:
                with st.spinner("Adquirindo MDE, calculando fluxos D8 e delineando divisor..."):
                    try:
                        mde_tag = 'USER_UPLOAD' if "Upload" in fonte_sel else fonte_sel.split()[0]
                        res = basin.delinear_bacia(
                            lon=p_lon,
                            lat=p_lat,
                            mde_source=mde_tag,
                            snap_radius_m=float(raio_snap),
                            uploaded_file=up_mde,
                            usar_cache=False
                        )
                        st.session_state.bacia_results = res
                        st.session_state.bacia_confirmada = False
                        st.session_state.project_dirty = True
                        st.rerun()
                    except basin.SnapExceededError as err:
                        st.error(f"❌ {err}")
                    except Exception as ex:
                        st.error(f"Erro ao processar delineação da bacia: {ex}")
                        import traceback
                        st.code(traceback.format_exc())

            if b_res:
                morf = b_res.get('morfometria', {})
                st.success(
                    f"🎉 **Bacia Hidrográfica Delimitada com Sucesso!** "
                    f"Área: **{morf.get('area_km2', 0):.2f} km²** | "
                    f"Talvegue: **{morf.get('comprimento_talvegue_km', 0):.2f} km** | "
                    f"Desnível: **{morf.get('desnivel_m', 0):.1f} m**"
                )

                # Destaque com 4 KPIs logo após a delimitação
                mb1, mb2, mb3, mb4 = st.columns(4)
                mb1.metric("Área da Bacia", f"{morf.get('area_km2', 0):.2f} km²")
                mb2.metric("Talvegue Principal", f"{morf.get('comprimento_talvegue_km', 0):.2f} km")
                mb3.metric("Desnível Total (ΔH)", f"{morf.get('desnivel_m', 0):.1f} m")
                mb4.metric("Declividade S10-85", f"{morf.get('declividade_s10_85_m_m', 0)*100:.2f}%")

            # Mapa com Leaflet / Folium
            st.markdown("##### 🗺️ Inspeção Visual da Bacia e Talvegue sobre Satélite")

            map_center_lat, map_center_lon = p_lat, p_lon
            basin_bounds = None
            if b_res and 'geojson_wgs84' in b_res.get('geometria', {}):
                try:
                    from shapely.geometry import shape as shp_shape
                    poly_wgs = shp_shape(b_res['geometria']['geojson_wgs84'])
                    minx, miny, maxx, maxy = poly_wgs.bounds
                    map_center_lat = (miny + maxy) / 2.0
                    map_center_lon = (minx + maxx) / 2.0
                    basin_bounds = [[float(miny), float(minx)], [float(maxy), float(maxx)]]
                except Exception:
                    pass

            m_basin = folium.Map(
                location=[map_center_lat, map_center_lon],
                zoom_start=12 if basin_bounds else 13,
                tiles=None,
                control_scale=True,
            )
            # Imagem de satélite e OSM padrão
            folium.TileLayer('OpenStreetMap', name='🗺️ Mapa (OSM)').add_to(m_basin)
            folium.TileLayer(
                tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                attr='Esri World Imagery',
                name='🛰️ Satélite (Esri)',
            ).add_to(m_basin)
            folium.TileLayer(
                tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
                attr='Esri World Topo',
                name='⛰️ Relevo (Topo)',
            ).add_to(m_basin)
            folium.LayerControl(position='topright').add_to(m_basin)

            # Exutório do projeto
            folium.Marker(
                [p_lat, p_lon],
                popup=f"<b>📍 Exutório do Projeto</b><br>{p_loc}<br>{p_lat:.4f}°, {p_lon:.4f}°",
                tooltip="📍 Exutório do Projeto",
                icon=folium.Icon(color='red', icon='record'),
            ).add_to(m_basin)

            if b_res:
                geom = b_res.get('geometria', {})
                morf = b_res.get('morfometria', {})

                # Exutório Snapped
                s_lat = b_res.get('outlet_snapped_lat', p_lat)
                s_lon = b_res.get('outlet_snapped_lon', p_lon)
                folium.Marker(
                    [s_lat, s_lon],
                    popup=f"<b>🎯 Exutório no Talvegue (Snap: {b_res.get('snap_dist_m'):.1f} m)</b>",
                    tooltip="🎯 Exutório Snapped",
                    icon=folium.Icon(color='blue', icon='flag'),
                ).add_to(m_basin)

                # Polígono da Bacia (usando folium.Polygon nativo para renderização vetorial garantida)
                if 'geojson_wgs84' in geom:
                    try:
                        from shapely.geometry import shape as shp_shape
                        poly_wgs = shp_shape(geom['geojson_wgs84'])
                        if poly_wgs.geom_type == 'Polygon':
                            ext_pts = [[p[1], p[0]] for p in poly_wgs.exterior.coords]
                            folium.Polygon(
                                locations=ext_pts,
                                color='#2563eb',
                                weight=3,
                                fill=True,
                                fill_color='#3b82f6',
                                fill_opacity=0.35,
                                tooltip=f"Bacia Hidrográfica: {morf.get('area_km2', 0):.2f} km²",
                                popup=f"<b>Bacia Hidrográfica</b><br>Área: {morf.get('area_km2', 0):.2f} km²<br>Talvegue: {morf.get('comprimento_talvegue_km', 0):.2f} km",
                            ).add_to(m_basin)
                        elif poly_wgs.geom_type == 'MultiPolygon':
                            for part in poly_wgs.geoms:
                                ext_pts = [[p[1], p[0]] for p in part.exterior.coords]
                                folium.Polygon(
                                    locations=ext_pts,
                                    color='#2563eb',
                                    weight=3,
                                    fill=True,
                                    fill_color='#3b82f6',
                                    fill_opacity=0.35,
                                    tooltip=f"Bacia Hidrográfica: {morf.get('area_km2', 0):.2f} km²",
                                ).add_to(m_basin)
                    except Exception:
                        pass

                # Talvegue Principal (usando folium.PolyLine nativo)
                if 'thalweg_geojson_wgs84' in geom:
                    try:
                        from shapely.geometry import shape as shp_shape
                        thal_wgs = shp_shape(geom['thalweg_geojson_wgs84'])
                        if thal_wgs.geom_type == 'LineString':
                            t_pts = [[p[1], p[0]] for p in thal_wgs.coords]
                            folium.PolyLine(
                                locations=t_pts,
                                color='#d97706',
                                weight=4,
                                tooltip=f"Talvegue Principal: {morf.get('comprimento_talvegue_km', 0):.2f} km",
                                popup=f"<b>Talvegue Principal</b><br>Extensão: {morf.get('comprimento_talvegue_km', 0):.2f} km<br>Desnível: {morf.get('desnivel_m', 0):.1f} m",
                            ).add_to(m_basin)
                        elif thal_wgs.geom_type == 'MultiLineString':
                            for line in thal_wgs.geoms:
                                t_pts = [[p[1], p[0]] for p in line.coords]
                                folium.PolyLine(
                                    locations=t_pts,
                                    color='#d97706',
                                    weight=4,
                                    tooltip=f"Talvegue: {morf.get('comprimento_talvegue_km', 0):.2f} km",
                                ).add_to(m_basin)
                    except Exception:
                        pass

                if basin_bounds:
                    m_basin.fit_bounds(basin_bounds)

            # Chave dinâmica para forçar remontagem limpa do iframe no Leaflet quando a bacia for calculada
            map_key = f"basin_folium_map_{'calc_' + str(b_res.get('hash', ''))[:8] if b_res else 'init'}"
            st_folium(m_basin, height=520, use_container_width=True, key=map_key, returned_objects=[])

            if b_res:
                st.divider()
                c_nav_l, c_nav_r = st.columns([1, 1])
                with c_nav_r:
                    if st.button("Avançar para Morfometria & Insumos 🌾 ➔", type="primary", use_container_width=True, key="btn_next_morpho"):
                        st.session_state.step = 1
                        st.rerun()

        # ──────────────────────────────────────────────────────────────────────
        # ETAPA 1: 🌾 Morfometria & Insumos Hidrológicos
        # ──────────────────────────────────────────────────────────────────────
        elif curr_step_bacia == 1:
            st.subheader(f"🌾 {t('stepper_basin_inputs', lang)}")
            if not b_res:
                st.warning("⚠️ Bacia hidrográfica ainda não delineada. Retorne à etapa anterior.")
                if st.button("⬅️ Ir para Delineação", use_container_width=True):
                    st.session_state.step = 0
                    st.rerun()
            else:
                morf = b_res['morfometria']
                uso = b_res['uso_solo']

                # KPI Cards em 4 colunas
                k1, k2, k3, k4 = st.columns(4)
                with k1:
                    st.metric("Área de Drenagem", f"{morf['area_km2']:.2f} km²")
                with k2:
                    st.metric("Talvegue Principal", f"{morf['comprimento_talvegue_km']:.2f} km")
                with k3:
                    st.metric("Desnível Total (ΔH)", f"{morf['desnivel_m']:.1f} m")
                with k4:
                    st.metric("Declividade S10-85", f"{morf['declividade_s10_85_m_m']*100:.2f}%", f"{morf['declividade_s10_85_m_m']:.4f} m/m")

                st.markdown(f"#### 📊 {t('basin_morpho_title', lang)}")

                tabela_morf = pd.DataFrame([
                    {"Parâmetro": "Área de Drenagem (A)", "Valor": f"{morf['area_km2']:.3f}", "Unidade": "km²", "Método / Referência": "SIRGAS 2000 UTM"},
                    {"Parâmetro": "Área Geodésica Independente", "Valor": f"{morf['area_geod_km2']:.3f}", "Unidade": "km²", "Método / Referência": "Elipsoide GRS80 (Erro: {:.3f}%)".format(morf['diff_area_pct'])},
                    {"Parâmetro": "Perímetro da Bacia (P)", "Valor": f"{morf['perimetro_km']:.3f}", "Unidade": "km", "Método / Referência": "Divisor Topográfico"},
                    {"Parâmetro": "Comprimento Axial (Lax)", "Valor": f"{morf['comprimento_axial_km']:.3f}", "Unidade": "km", "Método / Referência": "Distância Máxima do Exutório ao Divisor"},
                    {"Parâmetro": "Comprimento do Talvegue (L)", "Valor": f"{morf['comprimento_talvegue_km']:.3f}", "Unidade": "km", "Método / Referência": "Canal Principal (Maior Acumulação)"},
                    {"Parâmetro": "Cota do Exutório", "Valor": f"{morf['cota_exutorio_m']:.1f}", "Unidade": "m", "Método / Referência": "MDE"},
                    {"Parâmetro": "Cota do Ponto Mais Remoto", "Valor": f"{morf['cota_remota_m']:.1f}", "Unidade": "m", "Método / Referência": "Nascente do Talvegue"},
                    {"Parâmetro": "Desnível Total (ΔH)", "Valor": f"{morf['desnivel_m']:.1f}", "Unidade": "m", "Método / Referência": "Cota Remota - Cota Exutório"},
                    {"Parâmetro": "Declividade em Linha Reta", "Valor": f"{morf['declividade_reta_m_m']:.5f} ({morf['declividade_reta_m_m']*100:.2f}%)", "Unidade": "m/m (%)", "Método / Referência": "ΔH / L"},
                    {"Parâmetro": "Declividade Taylor-Schwarz (S10-85)", "Valor": f"{morf['declividade_s10_85_m_m']:.5f} ({morf['declividade_s10_85_m_m']*100:.2f}%)", "Unidade": "m/m (%)", "Método / Referência": "Perfil 10% a 85% do Talvegue"},
                    {"Parâmetro": "Declividade Equivalente", "Valor": f"{morf['declividade_equivalente_m_m']:.5f} ({morf['declividade_equivalente_m_m']*100:.2f}%)", "Unidade": "m/m (%)", "Método / Referência": "Trechos Ponderados Taylor-Schwarz"},
                    {"Parâmetro": "Declividade Média da Bacia", "Valor": f"{morf['declividade_media_bacia_pct']:.2f}", "Unidade": "%", "Método / Referência": "Média das Células da Bacia"},
                    {"Parâmetro": "Coeficiente de Compacidade (Kc)", "Valor": f"{morf['coeficiente_compacidade']:.3f}", "Unidade": "adimensional", "Método / Referência": "Gravelius (Kc = 0.28 * P / √A)"},
                    {"Parâmetro": "Fator de Forma (Kf)", "Valor": f"{morf['fator_forma']:.3f}", "Unidade": "adimensional", "Método / Referência": "Horton (Kf = A / Lax²)"},
                    {"Parâmetro": "Densidade de Drenagem", "Valor": f"{morf['densidade_drenagem_km_km2']:.2f}", "Unidade": "km/km²", "Método / Referência": "Canais / Área"},
                    {"Parâmetro": "Ordem de Strahler", "Valor": f"{morf['ordem_strahler']}", "Unidade": "ordem", "Método / Referência": "Hierarquia Fluvial D8"},
                ])
                st.dataframe(tabela_morf, hide_index=True, use_container_width=True)

                st.divider()
                st.markdown(f"#### 🌾 {t('basin_soil_title', lang)}")

                c_soil_l, c_soil_r = st.columns([1, 1])
                with c_soil_l:
                    soil_grp_sel = st.selectbox(
                        "Grupo Hidrológico do Solo (SoilGrids)",
                        ['B (Solos moderadamente profundos/permeáveis - Padrão)', 'A (Alta infiltração/arenosos)', 'C (Baixa infiltração/argilosos)', 'D (Impermeáveis/muito argilosos)'],
                        index=0,
                        help="Grupo hidrológico do solo segundo a classificação do SCS / SoilGrids."
                    )
                    grupo_letra = soil_grp_sel.split()[0]
                    if grupo_letra != uso.get('grupo_solo', 'B'):
                        # Recomputa classes de solo
                        poly_utm_geom = shape(b_res['geometria']['geojson_utm'])
                        b_res['uso_solo'] = basin.granular_uso_solo(poly_utm_geom, soil_group=grupo_letra)
                        st.session_state.bacia_results = b_res
                        st.session_state.project_dirty = True
                        st.rerun()

                classes_df = pd.DataFrame(uso['classes'])
                classes_df.rename(columns={
                    'classe': 'Classe de Uso (MapBiomas)',
                    'area_km2': 'Área (km²)',
                    'pct': 'Proporção (%)',
                    'c': 'Coeficiente C',
                    'cn': 'Curve Number (CN)'
                }, inplace=True)
                st.dataframe(classes_df, hide_index=True, use_container_width=True)

                c_kpi_c, c_kpi_cn = st.columns(2)
                with c_kpi_c:
                    st.metric("Coeficiente de Runoff C Ponderado", f"{uso['c_ponderado']:.3f}")
                with c_kpi_cn:
                    st.metric("Curve Number CN SCS Ponderado", f"{uso['cn_ponderado']:.1f}")

                # Expander de Sobrescrita Manual
                with st.expander(f"⚙️ {t('basin_override_title', lang)}"):
                    st.caption("Permite ao projetista sobrescrever os valores ponderados de C e CN com justificativa técnica obrigatória registrada no projeto e memorial.")
                    tem_sobr = bool(uso.get('sobrescrita'))
                    ativar_sobr = st.checkbox("Ativar sobrescrita manual de C e CN", value=tem_sobr)
                    if ativar_sobr:
                        val_c_atual = uso['sobrescrita'].get('c', uso['c_ponderado']) if tem_sobr else uso['c_ponderado']
                        val_cn_atual = uso['sobrescrita'].get('cn', uso['cn_ponderado']) if tem_sobr else uso['cn_ponderado']
                        motivo_atual = uso['sobrescrita'].get('motivo', '') if tem_sobr else ''

                        col_s1, col_s2 = st.columns(2)
                        novo_c = col_s1.number_input("C Adotado Manualmente", min_value=0.05, max_value=0.99, value=float(val_c_atual), step=0.01)
                        novo_cn = col_s2.number_input("CN Adotado Manualmente", min_value=30.0, max_value=99.0, value=float(val_cn_atual), step=1.0)
                        novo_motivo = st.text_area(t('basin_override_reason', lang), value=motivo_atual, placeholder="Ex.: Ajuste do CN para condição de saturação AMC III devido à alta umidade da bacia.")

                        if st.button("Salvar Sobrescrita Manual", type="primary"):
                            uso['sobrescrita'] = {
                                'c': round(novo_c, 3),
                                'cn': round(novo_cn, 1),
                                'motivo': novo_motivo.strip()
                            }
                            st.session_state.bacia_results = b_res
                            st.session_state.project_dirty = True
                            st.success("✅ Sobrescrita manual registrada com sucesso no projeto!")
                            st.rerun()
                    else:
                        if tem_sobr:
                            uso['sobrescrita'] = None
                            st.session_state.bacia_results = b_res
                            st.session_state.project_dirty = True
                            st.rerun()

                st.divider()
                c_btn_voltar, c_btn_avancar = st.columns([1, 1])
                with c_btn_voltar:
                    if st.button("⬅️ Voltar para Delineação", use_container_width=True):
                        st.session_state.step = 0
                        st.rerun()
                with c_btn_avancar:
                    is_conf = bool(st.session_state.get('bacia_confirmada', False))
                    btn_vazao_help = "Avançar para o cálculo das vazões de projeto" if is_conf else "Módulo Vazão bloqueado: confirme a delimitação da bacia na etapa 1 antes de prosseguir."
                    if st.button(
                        "Avançar para Módulo Vazão 🌊 ➔",
                        type="primary" if is_conf else "secondary",
                        disabled=not is_conf,
                        help=btn_vazao_help,
                        use_container_width=True
                    ):
                        st.session_state.active_module = 'vazao'
                        st.session_state.step = 0
                        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# DISPATCH DO MÓDULO VAZÃO (TEMPO DE CONCENTRAÇÃO · VAZÃO DE PROJETO)
# ══════════════════════════════════════════════════════════════════════════════
elif active_mod == 'vazao':
    status_v = module_status('vazao')
    curr_step_vazao = st.session_state.get('step', 0)

    if status_v == 'locked':
        st.error(f"🔒 **{t('mod_vazao', lang)} {t('status_locked', lang)}**")
        motivos = []
        if module_status('idf') != 'done':
            motivos.append("- **Módulo IDF pendente:** As curvas IDF precisam estar calculadas e com consistência física válida.")
        if not st.session_state.get('bacia_confirmada', False):
            motivos.append("- **Módulo Bacia pendente:** A bacia hidrográfica precisa ser delineada e confirmada visualmente pelo projetista.")
        st.markdown("\n".join(motivos))
    else:
        # Extração e preparação dos insumos de IDF e Bacia
        results_idf = st.session_state.get('results', {}) or {}
        sherman_params = results_idf.get('sherman_params', {}) or {}
        bacia_res = st.session_state.get('bacia_results', {}) or {}
        params_b = bacia_res.get('parametros', {}) or {}
        uso_b = bacia_res.get('uso_solo', {}) or {}

        area_km2 = float(params_b.get('area_km2', 1.0))
        talvegue_km = float(params_b.get('talvegue_km', params_b.get('comprimento_talvegue_km', 1.0)))
        desnivel_m = float(params_b.get('desnivel_m', 10.0))
        declividade_m_m = float(params_b.get('declividade_talvegue_m_m', (desnivel_m / (talvegue_km * 1000.0)) if talvegue_km > 0 else 0.01))
        declividade_media_pct = float(params_b.get('declividade_media_pct', params_b.get('declividade_bacia_pct', 3.0)))

        # Insumos C e CN com verificação de sobrescrita manual
        sobr = uso_b.get('sobrescrita')
        if sobr and isinstance(sobr, dict):
            c_adotado = float(sobr.get('c', uso_b.get('c_ponderado', 0.35)))
            cn_adotado = float(sobr.get('cn', uso_b.get('cn_ponderado', 70.0)))
        else:
            c_adotado = float(uso_b.get('c_ponderado', 0.35))
            cn_adotado = float(uso_b.get('cn_ponderado', 70.0))

        tr_projeto = float(st.session_state.get('proj_tr', 25))

        # Cálculo das 6 fórmulas de tempo de concentração
        tc_data = discharge.calcular_tempos_concentracao(
            area_km2=area_km2,
            comprimento_talvegue_km=talvegue_km,
            desnivel_m=desnivel_m,
            declividade_m_m=declividade_m_m,
            declividade_media_pct=declividade_media_pct,
            cn=cn_adotado
        )

        # ── Etapa 0: Tempo de Concentração ─────────────────────────────────────
        if curr_step_vazao == 0:
            st.subheader(f"⏱️ {t('flow_tc_title', lang)}")
            st.caption(t('flow_tc_desc', lang))

            # Métricas de dispersão
            stats = tc_data['estatisticas']
            c_kpi1, c_kpi2, c_kpi3, c_kpi4, c_kpi5 = st.columns(5)
            c_kpi1.metric("Mínimo", f"{stats['minimo_min']:.1f} min")
            c_kpi2.metric("Média", f"{stats['medio_min']:.1f} min")
            c_kpi3.metric("Mediana", f"{stats['mediana_min']:.1f} min")
            c_kpi4.metric("Máximo", f"{stats['maximo_min']:.1f} min")
            c_kpi5.metric("Dispersão", f"{stats['dispersao_pct']:.1f}%", help="Dispersão relativa: (Máximo - Mínimo) / Média")

            st.markdown("##### 📋 Tabela Comparativa de Fórmulas e Domínios de Validade")
            tc_rows = []
            for f in tc_data['formulas']:
                status_icon = "✅ No domínio" if f['no_dominio'] else "⚠️ Fora do domínio"
                tc_rows.append({
                    'Fórmula / Método': f['nome'],
                    'tc (min)': f['tc_min'],
                    'tc (horas)': f['tc_h'],
                    'Domínio de Calibração': f['dominio'],
                    'Validade': status_icon,
                    'Observação / Restrição': f['aviso'] if f['aviso'] else 'Em conformidade com as características da bacia',
                })
            df_tc = pd.DataFrame(tc_rows)
            st.dataframe(df_tc, hide_index=False, use_container_width=True)

            # Adoção explícita pelo projetista
            st.divider()
            st.markdown("##### ✍️ Adoção do Tempo de Concentração de Projeto")
            st.info(
                "ℹ️ **Regra de Projeto:** A dispersão entre as estimativas empíricas é uma informação técnica indispensável. "
                "Nenhum valor único é imposto silenciosamente pelo sistema. A escolha do valor final deve ser explicitada e "
                "justificada tecnicamente pelo responsável técnico."
            )

            # Opções de fórmula
            opcoes_formulas = [f['id'] for f in tc_data['formulas']] + ['manual']
            nomes_opcoes = {
                f['id']: f"{f['nome']} ({f['tc_min']} min — {'No domínio' if f['no_dominio'] else 'Fora do domínio'})"
                for f in tc_data['formulas']
            }
            nomes_opcoes['manual'] = "Valor Arbitrado / Sobrescrita Direta"

            # Fórmula default recomendada (preferência por no_dominio)
            formula_padrao = 'scs_lag'
            if area_km2 >= 5.0 and any(f['id'] == 'giandotti' and f['no_dominio'] for f in tc_data['formulas']):
                formula_padrao = 'giandotti'
            elif area_km2 <= 4.0 and any(f['id'] == 'kirpich' and f['no_dominio'] for f in tc_data['formulas']):
                formula_padrao = 'kirpich'

            f_atual = st.session_state.get('formula_tc_adotada') or formula_padrao
            if f_atual not in opcoes_formulas:
                f_atual = formula_padrao

            idx_padrao = opcoes_formulas.index(f_atual)
            formula_escolhida = st.selectbox(
                t('flow_select_formula', lang),
                options=opcoes_formulas,
                index=idx_padrao,
                format_func=lambda fid: nomes_opcoes.get(fid, fid)
            )

            # Valor sugerido conforme fórmula
            if formula_escolhida != 'manual':
                item_f = next((f for f in tc_data['formulas'] if f['id'] == formula_escolhida), None)
                val_sugerido = float(item_f['tc_min']) if item_f else float(stats['mediana_min'])
                fora_dom = not item_f['no_dominio'] if item_f else False
            else:
                val_sugerido = float(st.session_state.get('tc_adotado_min') or stats['mediana_min'])
                fora_dom = False

            col_tc_val, col_tc_warn = st.columns([1, 2])
            tc_final = col_tc_val.number_input(
                t('flow_adopted_tc', lang),
                min_value=5.0,
                max_value=1440.0,
                value=float(st.session_state.get('tc_adotado_min') or val_sugerido),
                step=1.0,
                help="Tempo de concentração adotado para a leitura da intensidade de precipitação."
            )

            if fora_dom:
                col_tc_warn.warning(
                    f"⚠️ **Atenção:** A fórmula `{nomes_opcoes.get(formula_escolhida, formula_escolhida)}` está fora do seu "
                    f"domínio físico de calibração para esta bacia hidrográfica. Justifique no campo abaixo o embasamento da escolha."
                )
            else:
                col_tc_warn.success(f"✅ Fórmula em conformidade com o domínio físico de calibração da bacia.")

            justif_atual = st.session_state.get('justificativa_tc', '')
            justif_tc = st.text_area(
                t('flow_adoption_reason', lang),
                value=justif_atual,
                placeholder="Ex.: Adotada a fórmula SCS Lag por representar bacias com uso do solo homogêneo e tempo de retardo calibrado para o CN do projeto."
            )

            st.divider()
            c_btn_voltar, c_btn_avancar = st.columns([1, 1])
            with c_btn_voltar:
                if st.button("⬅️ Voltar para Módulo Bacia", use_container_width=True):
                    st.session_state.active_module = 'bacia'
                    st.session_state.step = 1
                    st.rerun()

            with c_btn_avancar:
                if st.button("Salvar Adoção e Avançar para Vazão de Projeto 🌊 ➔", type="primary", use_container_width=True):
                    st.session_state.tc_adotado_min = round(float(tc_final), 1)
                    st.session_state.formula_tc_adotada = formula_escolhida
                    st.session_state.justificativa_tc = justif_tc.strip()
                    st.session_state.tc_fora_dominio = fora_dom
                    st.session_state.tc_data = tc_data
                    st.session_state.project_dirty = True
                    st.session_state.step = 1
                    st.rerun()

        # ── Etapa 1: Vazão de Projeto ──────────────────────────────────────────
        else:
            st.subheader(f"🌊 {t('flow_design_title', lang)}")

            # Garante que tc adotado existe
            tc_adotado_val = float(st.session_state.get('tc_adotado_min') or tc_data['estatisticas']['mediana_min'])
            formula_adotada_val = st.session_state.get('formula_tc_adotada', 'scs_lag')

            # Leitura da intensidade de chuva pela equação IDF ajustada
            i_chuva = discharge.calcular_intensidade_sherman(sherman_params, tc_adotado_val, tr_projeto)

            # Faixa contextual superior
            with st.container(border=True):
                c_ctx1, c_ctx2, c_ctx3, c_ctx4 = st.columns(4)
                c_ctx1.markdown(f"**Área da Bacia:**<br>`{area_km2:.3f} km²` ({area_km2 * 100:.1f} ha)", unsafe_allow_html=True)
                c_ctx2.markdown(f"**tc Adotado:**<br>`{tc_adotado_val:.1f} min` ({formula_adotada_val})", unsafe_allow_html=True)
                c_ctx3.markdown(f"**Período de Retorno (TR):**<br>`{tr_projeto:.0f} anos`", unsafe_allow_html=True)
                c_ctx4.markdown(f"**Intensidade IDF (i):**<br>`{i_chuva:.2f} mm/h`", unsafe_allow_html=True)

            st.markdown("##### ⚖️ Decisão do Método Hidrológico (DNIT IPR-724)")

            # Verificação estrita do limiar normativo do DNIT IPR-724 (1,00 km² / 100 ha)
            limiar_ipr = discharge.LIMIAR_AREA_RACIONAL_IPR724_KM2
            racional_bloqueado = (area_km2 > limiar_ipr)

            if racional_bloqueado:
                # O botão/opção permanece visível e riscado, conforme requisito pedagógico estrito
                st.markdown(
                    f"<div style='background-color:#fffbeb; border:1.5px solid #d97706; border-radius:8px; padding:14px; margin-bottom:16px;'>"
                    f"<div style='display:flex; align-items:center; gap:10px; margin-bottom:6px;'>"
                    f"<span style='text-decoration:line-through; font-weight:700; color:#92400e; font-size:1.15em;'>{t('flow_method_racional', lang)}</span>"
                    f"<span style='background-color:#fee2e2; color:#991b1b; padding:2px 8px; border-radius:4px; font-weight:700; font-size:0.80em;'>🔒 BLOQUEADO</span>"
                    f"</div>"
                    f"<p style='color:#78350f; margin:0; font-size:0.92em; line-height:1.45;'>"
                    f"<b>Justificativa Normativa (DNIT IPR-724, item 3.2.1):</b> A área da bacia (<b>{area_km2:.3f} km² / {area_km2 * 100:.1f} ha</b>) "
                    f"excede o limite de <b>{limiar_ipr:.2f} km² (100 ha)</b>. Os efeitos de amortecimento na calha principal e a variabilidade "
                    f"espacial da precipitação invalidam a hipótese de chuva uniforme em regime permanente do Método Racional. "
                    f"O dimensionamento hidrológico é conduzido obrigatoriamente pelo <b>Hidrograma Unitário SCS (NRCS)</b>."
                    f"</p></div>",
                    unsafe_allow_html=True
                )
                metodo_selecionado = 'scs'
            else:
                st.success(
                    f"✅ **Área da Bacia Elegível ({area_km2:.3f} km² ≤ {limiar_ipr:.2f} km²):** "
                    f"Tanto o Método Racional quanto o Hidrograma Unitário SCS são métodos aplicáveis."
                )
                metodo_selecionado = st.radio(
                    "Selecione o método de cálculo:",
                    options=['racional', 'scs'],
                    format_func=lambda m: "Método Racional (Recomendado pelo DNIT IPR-724 para microbacias)" if m == 'racional' else "Hidrograma Unitário Sintético SCS (NRCS)"
                )

            # Execução do cálculo de vazão integrado
            res_vazao = discharge.calcular_vazao_projeto(
                area_km2=area_km2,
                c_runoff=c_adotado,
                cn=cn_adotado,
                tc_adotado_min=tc_adotado_val,
                formula_tc_adotada=formula_adotada_val,
                sherman_params=sherman_params,
                tr_anos=tr_projeto,
                metodo_preferido=metodo_selecionado
            )
            res_vazao['tc_data'] = tc_data

            # Salva o resultado no session_state para auditoria, persistência e destravamento
            st.session_state.vazao_results = res_vazao
            st.session_state.q_projeto_m3s = res_vazao['q_projeto_m3s']
            st.session_state.metodo_adotado = res_vazao['metodo_adotado']

            st.divider()
            st.markdown(f"### 📊 {t('flow_results_title', lang)}")

            # Exibição conforme o método adotado
            if res_vazao['metodo_adotado'] == 'racional':
                q_p = res_vazao['q_projeto_m3s']
                c_res1, c_res2, c_res3, c_res4 = st.columns(4)
                c_res1.metric("Vazão de Projeto Q", f"{q_p:.2f} m³/s")
                c_res2.metric("Coeficiente de Runoff C", f"{c_adotado:.3f}")
                c_res3.metric("Intensidade da Chuva i", f"{i_chuva:.2f} mm/h")
                c_res4.metric("Área de Contribuição A", f"{area_km2:.3f} km²")

                st.markdown(
                    f"<div style='background-color:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:12px; margin-top:8px;'>"
                    f"<b>Equação do Método Racional:</b><br>"
                    f"$$Q = \\frac{{C \\cdot i \\cdot A}}{{3,6}} = \\frac{{{c_adotado:.3f} \\cdot {i_chuva:.2f} \\cdot {area_km2:.3f}}}{{3,6}} = {q_p:.2f}\\text{{ m}}^3/\\text{{s}}$$"
                    f"</div>",
                    unsafe_allow_html=True
                )
            else:
                # Hidrograma Unitário SCS
                scs_res = res_vazao['scs']
                q_pico_val = scs_res['q_pico_m3s']
                tp_val_h = scs_res['tempo_pico_h']
                vol_val = scs_res['volume_total_m3']
                pe_val = scs_res['lamina_efetiva_mm']
                ptot_val = scs_res['lamina_total_mm']

                c_kpi_v1, c_kpi_v2, c_kpi_v3, c_kpi_v4 = st.columns(4)
                c_kpi_v1.metric("Vazão de Pico Qp", f"{q_pico_val:.2f} m³/s")
                c_kpi_v2.metric("Tempo ao Pico tp", f"{tp_val_h:.2f} h", help=f"{scs_res['tempo_pico_min']:.0f} minutos")
                c_kpi_v3.metric("Volume Escoado", f"{vol_val:,.0f} m³")
                c_kpi_v4.metric("Chuva Efetiva (Pe)", f"{pe_val:.1f} mm", help=f"Chuva Total P = {ptot_val:.1f} mm")

                # Gráficos interativos Plotly
                df_hidro = scs_res['df_hidrograma']
                col_g1, col_g2 = st.columns(2)
                with col_g1:
                    fig_h = fig_hydrograph_scs(df_hidro, q_pico_val, tp_val_h, lang=lang)
                    st.plotly_chart(fig_h, use_container_width=True)
                with col_g2:
                    fig_b = fig_hyetograph_blocks(df_hidro, lang=lang)
                    st.plotly_chart(fig_b, use_container_width=True)

                with st.expander("🔍 Detalhes Técnicos e Parâmetros Intermediários SCS"):
                    c_det1, c_det2 = st.columns(2)
                    with c_det1:
                        st.markdown(f"- **Fator de Abatimento Espacial (ARF):** `{scs_res['coef_abatimento_espacial']:.3f}`")
                        st.markdown(f"- **Tempo de Pico Unitário (tp):** `{scs_res['tempo_pico_unitario_tp_min']:.1f} min`")
                        st.markdown(f"- **Tempo de Base do HU (tb):** `{scs_res['tempo_base_tb_min']:.1f} min`")
                    with c_det2:
                        st.markdown(f"- **Vazão de Pico Unitária (qu):** `{scs_res['vazao_pico_unitaria_qu_m3s_mm']:.3f} m³/s/mm`")
                        st.markdown(f"- **Curve Number (CN):** `{cn_adotado:.1f}`")
                        st.markdown(f"- **Coeficiente C Equivalente:** `{c_adotado:.3f}`")

                st.markdown("##### 📋 Tabela da Convolução do Hidrograma")
                st.dataframe(df_hidro, hide_index=False, use_container_width=True)

                csv_hidro = df_hidro.to_csv(index=False).encode('utf-8')
                st.download_button(
                    "📥 Baixar Hidrograma em CSV",
                    data=csv_hidro,
                    file_name=f"hidrograma_scs_tr{int(tr_projeto)}.csv",
                    mime="text/csv"
                )

            # Barra de ações final
            st.divider()
            c_nav1, c_nav2 = st.columns(2)
            with c_nav1:
                if st.button("⬅️ Voltar para Tempo de Concentração", use_container_width=True):
                    st.session_state.step = 0
                    st.rerun()
            with c_nav2:
                if st.button("💾 Salvar Projeto e Exportar (.siih)", type="primary", use_container_width=True):
                    st.session_state.active_module = 'projeto'
                    st.session_state.step = 1
                    st.session_state.project_dirty = True
                    st.rerun()


# ── Rodapé / créditos ─────────────────────────────────────────────────────────
st.divider()
st.markdown(
    f"<div style='text-align:center; color:#888; font-size:0.85em; padding:0.5rem 0;'>"
    f"{L['footer']}</div>",
    unsafe_allow_html=True,
)
