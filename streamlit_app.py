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

from calculations import (
    run_full_analysis,
    parse_station_code,
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


# ── Textos da interface (PT / EN) ─────────────────────────────────────────────
UI = {
    'PT': {
        'title': '🌧️ Gerador de Curvas IDF',
        'subtitle': 'Intensidade – Duração – Frequência · Método de Gumbel + Taborga + Sherman',
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
    },
    'EN': {
        'title': '🌧️ IDF Curve Generator',
        'subtitle': 'Intensity – Duration – Frequency · Gumbel + Taborga + Sherman method',
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
    },
}


# ── Estado da sessão ──────────────────────────────────────────────────────────
def init_state():
    st.session_state.setdefault('ana_stations', [])   # [{codigo, nome}]
    st.session_state.setdefault('ana_series_text', '')  # série baixada, formato manual
    st.session_state.setdefault('results', None)
    st.session_state.setdefault('report_ctx', {})


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
    localizacao = st.text_input(L['loc'], value='Taubaté - SP')
    estacao = st.text_input(L['est'], value='')

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
    st.sidebar.caption(L['api_hint'])
    uf = st.sidebar.selectbox(L['api_uf'], sorted(AnaHidroWebService.UFS_BRASIL))

    if st.sidebar.button(L['api_buscar'], use_container_width=True):
        try:
            with st.spinner(L['api_buscar']):
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
                    df = cliente_ana().obter_serie_chuva(
                        estacao, int(api_y0), int(api_y1), progresso=_prog)
                st.session_state.ana_series_text = '\n'.join(
                    df['Precipitacao'].astype(str).tolist())
                aviso.empty()
                barra.empty()
                st.sidebar.success(L['fetch_ok'].format(n=len(df)))
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
    latitude = c0.number_input(L['lat'], value=0.0, format='%.4f')
    longitude = c1.number_input(L['lon'], value=0.0, format='%.4f')

# ── Botão principal ───────────────────────────────────────────────────────────
run = st.sidebar.button(L['run'], type='primary', use_container_width=True)


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
            'responsavel': responsavel, 'localizacao': localizacao,
            'estacao': estacao or '—', 'lang': lang,
        }
    except UserError as e:
        st.error(str(e))
        st.session_state.results = None
    except Exception as e:
        st.error(f'Erro na análise: {e}')
        st.session_state.results = None


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
                fh, fg, fp, fi, lang=lang)
            st.download_button(L['dl_pdf'], data=pdf_bytes,
                               file_name='memorial_calculo_idf.pdf',
                               mime='application/pdf', use_container_width=True)
        except Exception as e:
            st.warning(f'PDF: {e}')

    with d2:
        try:
            docx_bytes = generate_word_report(
                results, ctx['responsavel'], ctx['localizacao'], ctx['estacao'],
                fh, fg, fp, fi, lang=lang)
            st.download_button(
                L['dl_word'], data=docx_bytes,
                file_name='memorial_calculo_idf.docx',
                mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                use_container_width=True)
        except Exception as e:
            st.warning(f'Word: {e}')
