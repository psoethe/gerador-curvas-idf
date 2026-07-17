"""
Internationalisation (i18n) strings for the IDF Curve Generator.
Supports Portuguese (PT) and English (EN).
"""

LABELS: dict[str, dict[str, str]] = {
    # ── Parametrization sections ──────────────────────────────────────────────
    'sec_meta_title':       {'PT': 'Metadados (Identificação)',          'EN': 'Metadata (Identification)'},
    'responsavel_label':    {'PT': 'Responsável Técnico',                'EN': 'Technical Responsible'},
    'localizacao_label':    {'PT': 'Localização',                        'EN': 'Location'},
    'estacao_label':        {'PT': 'Número da Estação',                  'EN': 'Station Number'},

    'sec_data_title':       {'PT': 'Entrada de Dados Hidrológicos',      'EN': 'Hydrological Data Input'},
    'ana_file_label':       {'PT': 'Arquivo ANA/HidroWeb (CSV ou TXT)',  'EN': 'ANA/HidroWeb File (CSV or TXT)'},
    'ana_file_desc':        {'PT': 'Importe o arquivo de chuvas máximas diárias anuais exportado do HidroWeb (ANA).',
                             'EN': 'Import the annual maximum daily rainfall file exported from HidroWeb (ANA).'},
    'manual_data_label':    {'PT': 'Dados Manuais (um valor por linha, em mm)',
                             'EN': 'Manual Data (one value per line, in mm)'},
    'manual_data_desc':     {'PT': 'Insira a série histórica de precipitação máxima diária anual, um valor por linha.',
                             'EN': 'Enter the annual maximum daily precipitation historical series, one value per line.'},

    'sec_period_title':     {'PT': 'Filtro de Período da Série Histórica', 'EN': 'Historical Series Period Filter'},
    'year_start_label':     {'PT': 'Ano Inicial',                        'EN': 'Start Year'},
    'year_start_desc':      {'PT': 'Ano inicial para filtrar a série histórica (deixe em branco para usar todo o período).',
                             'EN': 'Start year to filter the historical series (leave blank to use the full period).'},
    'year_end_label':       {'PT': 'Ano Final',                          'EN': 'End Year'},
    'year_end_desc':        {'PT': 'Ano final para filtrar a série histórica (deixe em branco para usar todo o período).',
                             'EN': 'End year to filter the historical series (leave blank to use the full period).'},

    'sec_region_title':     {'PT': 'Parâmetros da Região',               'EN': 'Regional Parameters'},
    'isozona_label':        {'PT': 'Isozona (Método Taborga)',            'EN': 'Isozone (Taborga Method)'},
    'isozona_desc':         {'PT': 'Selecione a isozona correspondente à localização da estação pluviométrica.',
                             'EN': 'Select the isozone corresponding to the rain gauge station location.'},
    'latitude_label':       {'PT': 'Latitude',                           'EN': 'Latitude'},
    'latitude_desc':        {'PT': 'Latitude da estação (opcional, para referência).',
                             'EN': 'Station latitude (optional, for reference).'},
    'longitude_label':      {'PT': 'Longitude',                          'EN': 'Longitude'},
    'longitude_desc':       {'PT': 'Longitude da estação (opcional, para referência).',
                             'EN': 'Station longitude (optional, for reference).'},

    'sec_export_title':     {'PT': 'Exportar',                           'EN': 'Export'},
    'download_btn_label':   {'PT': 'Exportar Memorial de Cálculo (HTML)', 'EN': 'Export Calculation Report (HTML)'},

    # ── View titles ───────────────────────────────────────────────────────────
    'view_historica':       {'PT': 'Série Histórica',                    'EN': 'Historical Series'},
    'view_gumbel':          {'PT': 'Análise de Gumbel',                  'EN': 'Gumbel Analysis'},
    'view_pdf':             {'PT': 'Curvas PDF',                         'EN': 'PDF Curves'},
    'view_idf':             {'PT': 'Curvas IDF',                         'EN': 'IDF Curves'},
    'view_tables':          {'PT': 'Tabelas de Resultados',              'EN': 'Results Tables'},

    # ── Chart titles & axis labels ────────────────────────────────────────────
    'hist_title':           {'PT': 'Série Histórica de Precipitação Máxima Diária Anual',
                             'EN': 'Annual Maximum Daily Precipitation Historical Series'},
    'hist_mean_label':      {'PT': 'Média',                              'EN': 'Mean'},
    'hist_bar_name':        {'PT': 'Precipitação Máxima Anual',          'EN': 'Annual Maximum Precipitation'},
    'axis_year':            {'PT': 'Ano',                                'EN': 'Year'},
    'axis_precip_mm':       {'PT': 'Precipitação Máxima (mm)',           'EN': 'Maximum Precipitation (mm)'},
    'axis_duration_min':    {'PT': 'Duração (min)',                      'EN': 'Duration (min)'},
    'axis_precip_p':        {'PT': 'Precipitação P (mm)',                'EN': 'Precipitation P (mm)'},
    'axis_intensity':       {'PT': 'Intensidade i (mm/h)',               'EN': 'Intensity i (mm/h)'},
    'axis_tr':              {'PT': 'Período de Retorno TR (anos)',        'EN': 'Return Period TR (years)'},
    'legend_tr':            {'PT': 'Período de Retorno',                 'EN': 'Return Period'},

    'gumbel_title':         {'PT': 'Análise de Gumbel — Precipitação de Projeto por Período de Retorno',
                             'EN': 'Gumbel Analysis — Design Precipitation by Return Period'},
    'gumbel_bar_name':      {'PT': 'Precipitação de Projeto (Pt)',       'EN': 'Design Precipitation (Pt)'},

    'pdf_title':            {'PT': 'Curvas PDF — Precipitação Acumulada por Duração',
                             'EN': 'PDF Curves — Accumulated Precipitation by Duration'},

    'idf_title':            {'PT': 'Curvas IDF — Intensidade-Duração-Frequência',
                             'EN': 'IDF Curves — Intensity-Duration-Frequency'},
    'idf_calc_suffix':      {'PT': '(calc.)',                            'EN': '(calc.)'},
    'idf_sherman_suffix':   {'PT': '(Sherman)',                          'EN': '(Sherman)'},

    # ── Table subtitles ───────────────────────────────────────────────────────
    'tbl1_title':           {'PT': 'Tabela 1 — Série Histórica',         'EN': 'Table 1 — Historical Series'},
    'tbl2_title':           {'PT': 'Tabela 2 — Análise de Gumbel',       'EN': 'Table 2 — Gumbel Analysis'},
    'tbl3_title':           {'PT': 'Tabela 3 — Desagregação (mm)',       'EN': 'Table 3 — Disaggregation (mm)'},
    'tbl4_title':           {'PT': 'Tabela 4 — Parâmetros de Sherman',   'EN': 'Table 4 — Sherman Parameters'},

    # ── DataFrame column names ────────────────────────────────────────────────
    'col_ano':              {'PT': 'Ano',                                'EN': 'Year'},
    'col_data':             {'PT': 'Data',                               'EN': 'Date'},
    'col_precip':           {'PT': 'Precipitação Máxima (mm)',           'EN': 'Maximum Precipitation (mm)'},
    'col_tr':               {'PT': 'TR (anos)',                          'EN': 'TR (years)'},
    'col_y':                {'PT': 'Y',                                  'EN': 'Y'},
    'col_kt':               {'PT': 'Kt',                                 'EN': 'Kt'},
    'col_pt':               {'PT': 'Pt (mm)',                            'EN': 'Pt (mm)'},
    'col_duracao':          {'PT': 'Duração (min)',                      'EN': 'Duration (min)'},
    'tr_col_prefix':        {'PT': 'TR=',                                'EN': 'TR='},
    'tr_col_suffix':        {'PT': ' anos',                              'EN': ' yrs'},

    # ── Report strings ────────────────────────────────────────────────────────
    'report_title':         {'PT': 'Memorial de Cálculo — Curvas IDF',  'EN': 'Calculation Report — IDF Curves'},
    'report_s1':            {'PT': '1. Identificação',                   'EN': '1. Identification'},
    'report_responsavel':   {'PT': 'Responsável Técnico',                'EN': 'Technical Responsible'},
    'report_localizacao':   {'PT': 'Localização',                        'EN': 'Location'},
    'report_estacao':       {'PT': 'Número da Estação',                  'EN': 'Station Number'},
    'report_isozona':       {'PT': 'Isozona',                            'EN': 'Isozone'},
    'report_n':             {'PT': 'Tamanho Amostral (N)',               'EN': 'Sample Size (N)'},
    'report_n_suffix':      {'PT': ' anos',                              'EN': ' years'},
    'report_mu':            {'PT': 'Média (μ)',                          'EN': 'Mean (μ)'},
    'report_sigma':         {'PT': 'Desvio Padrão (σ)',                  'EN': 'Standard Deviation (σ)'},
    'report_period_filter': {'PT': 'Período Analisado',                  'EN': 'Analysed Period'},

    'report_s2':            {'PT': '2. Série Histórica',                 'EN': '2. Historical Series'},
    'report_s2_desc':       {'PT': 'Precipitação máxima diária anual extraída da série de dados.',
                             'EN': 'Annual maximum daily precipitation extracted from the data series.'},

    'report_s3':            {'PT': '3. Análise de Gumbel',               'EN': '3. Gumbel Analysis'},
    'report_s3_desc':       {'PT': 'Estimativa da precipitação máxima diária para diferentes períodos de retorno usando a distribuição de Gumbel (Valor Extremo Tipo I).',
                             'EN': 'Estimation of maximum daily precipitation for different return periods using the Gumbel distribution (Extreme Value Type I).'},
    'report_gumbel_note':   {'PT': 'Constantes de Gumbel para N=',       'EN': 'Gumbel constants for N='},

    'report_s4':            {'PT': '4. Desagregação de Chuvas — Método das Isozonas (Taborga)',
                             'EN': '4. Rainfall Disaggregation — Isozone Method (Taborga)'},
    'report_s4_desc':       {'PT': 'Desagregação da precipitação diária para 22 durações sub-diárias (6 min a 1440 min) usando os coeficientes de isozona',
                             'EN': 'Disaggregation of daily precipitation to 22 sub-daily durations (6 min to 1440 min) using isozone coefficients'},

    'report_s5':            {'PT': '5. Curvas IDF',                      'EN': '5. IDF Curves'},
    'report_s5_desc':       {'PT': 'Intensidade de precipitação calculada a partir da precipitação acumulada:',
                             'EN': 'Precipitation intensity calculated from accumulated precipitation:'},

    'report_s6':            {'PT': '6. Equação de Sherman (Montana)',     'EN': '6. Sherman Equation (Montana)'},
    'report_s6_desc':       {'PT': 'Ajuste paramétrico por regressão não-linear (Levenberg-Marquardt):',
                             'EN': 'Parametric fitting by non-linear regression (Levenberg-Marquardt):'},
    'report_s6_params':     {'PT': 'Parâmetros ajustados:',              'EN': 'Fitted parameters:'},

    'report_footer':        {'PT': 'Gerado automaticamente pelo App VIKTOR — Curvas IDF',
                             'EN': 'Automatically generated by VIKTOR App — IDF Curves'},

    # ── Gumbel Memory-of-Calculation (Passo 2) ───────────────────────────────
    'gumbel_mem_title':     {'PT': 'Passo 2 — Análise Probabilística (Gumbel)',
                             'EN': 'Step 2 — Probabilistic Analysis (Gumbel)'},
    'gumbel_mem_card':      {'PT': 'Memória de Cálculo — Método de Gumbel',
                             'EN': 'Calculation Memory — Gumbel Method'},

    # Ordered data table columns
    'gm_col_data':          {'PT': 'Data/Ano',          'EN': 'Date/Year'},
    'gm_col_p':             {'PT': 'P (mm)',             'EN': 'P (mm)'},
    'gm_col_m':             {'PT': 'M',                  'EN': 'M'},
    'gm_col_pdesc':         {'PT': 'P decresc.',         'EN': 'P desc.'},
    'gm_col_ppn':           {'PT': 'P − Pn',             'EN': 'P − Pn'},
    'gm_col_ppn2':          {'PT': '(P−Pn)²',            'EN': '(P−Pn)²'},
    'gm_col_pr':            {'PT': 'Pr (%)',             'EN': 'Pr (%)'},
    'gm_col_tr':            {'PT': 'Tr (anos)',          'EN': 'Tr (yrs)'},
    'gm_col_y':             {'PT': 'Y',                  'EN': 'Y'},
    'gm_col_yyn':           {'PT': 'Y − Yn',             'EN': 'Y − Yn'},
    'gm_col_yyn2':          {'PT': '(Y−Yn)²',            'EN': '(Y−Yn)²'},

    # Auxiliary table A labels
    'gm_aux_n':             {'PT': 'N (nº de dados)',    'EN': 'N (data count)'},
    'gm_aux_n1':            {'PT': 'N − 1',              'EN': 'N − 1'},
    'gm_aux_sumP':          {'PT': 'Σ P (mm)',           'EN': 'Σ P (mm)'},
    'gm_aux_pn':            {'PT': 'Pn — Média (mm)',    'EN': 'Pn — Mean (mm)'},
    'gm_aux_sumPPn2':       {'PT': 'Σ (P−Pn)²',         'EN': 'Σ (P−Pn)²'},
    'gm_aux_sigma':         {'PT': 'σn — Desv. Padrão (mm)', 'EN': 'σn — Std Dev (mm)'},
    'gm_aux_sumY':          {'PT': 'Σ Y',                'EN': 'Σ Y'},
    'gm_aux_yn':            {'PT': 'Yn — Média de Y',   'EN': 'Yn — Mean of Y'},
    'gm_aux_sumYYn2':       {'PT': 'Σ (Y−Yn)²',         'EN': 'Σ (Y−Yn)²'},
    'gm_aux_sn':            {'PT': "σ'n — Fator Amostral", 'EN': "σ'n — Sample Factor"},

    # Ven Te Chow table B
    'gm_chow_title':        {'PT': 'Fórmula de Ven Te Chow',  'EN': 'Ven Te Chow Formula'},
    'gm_chow_tr':           {'PT': 'TR (anos)',               'EN': 'TR (yrs)'},
    'gm_chow_pn':           {'PT': 'Pn (mm)',                 'EN': 'Pn (mm)'},
    'gm_chow_sigma':        {'PT': 'σn (mm)',                 'EN': 'σn (mm)'},
    'gm_chow_kt':           {'PT': 'Kt',                      'EN': 'Kt'},
    'gm_chow_pt':           {'PT': 'Pt (mm)',                 'EN': 'Pt (mm)'},

    # Kt detail table
    'gm_kt_title':          {'PT': 'Fator de Frequência (Kt)',  'EN': 'Frequency Factor (Kt)'},
    'gm_kt_tr':             {'PT': 'ANOS (TR)',                 'EN': 'YEARS (TR)'},
    'gm_kt_y':              {'PT': 'Y',                         'EN': 'Y'},
    'gm_kt_yn':             {'PT': 'Yn',                        'EN': 'Yn'},
    'gm_kt_sn':             {'PT': "σ'n",                       'EN': "σ'n"},
    'gm_kt_kt':             {'PT': 'Kt',                        'EN': 'Kt'},

    # P24h disaggregation table
    'gm_p24_title':         {'PT': 'Altura de Precipitação para Menor de 24h (Desagregação)',
                             'EN': 'Precipitation Height for Less than 24h (Disaggregation)'},
    'gm_p24_tr':            {'PT': 'TR',                        'EN': 'TR'},
    'gm_p24_pn':            {'PT': 'Pn (Média)',                'EN': 'Pn (Mean)'},
    'gm_p24_sigma':         {'PT': 'σn (Desv. Padrão)',         'EN': 'σn (Std Dev)'},
    'gm_p24_kt':            {'PT': 'Kt',                        'EN': 'Kt'},
    'gm_p24_pt':            {'PT': 'Pt (mm)',                   'EN': 'Pt (mm)'},
    'gm_p24_coef':          {'PT': 'Coef. (1,158)',             'EN': 'Coef. (1.158)'},
    'gm_p24_p24':           {'PT': 'P 24h (mm)',                'EN': 'P 24h (mm)'},

    # Right-panel
    'gm_results_title':     {'PT': 'Resultados Estimados',      'EN': 'Estimated Results'},
    'gm_results_tr':        {'PT': 'TR',                        'EN': 'TR'},
    'gm_results_p':         {'PT': 'P máx. diária (mm)',        'EN': 'Max daily P (mm)'},
    'gm_alert1_title':      {'PT': 'Método de Ven Te Chow (Gumbel)',
                             'EN': 'Ven Te Chow Method (Gumbel)'},
    'gm_alert1_body':       {'PT': 'A estimativa foi realizada com base no Método de Ven Te Chow, '
                                   'usando a equação P(TR) = Pn + Kt × σn, onde Kt = (Y − Yn) / σ\'n.',
                             'EN': 'The estimate was performed using the Ven Te Chow Method, '
                                   'with equation P(TR) = Pn + Kt × σn, where Kt = (Y − Yn) / σ\'n.'},
    'gm_alert2_title':      {'PT': 'Tempo de Retorno (TR)',     'EN': 'Return Period (TR)'},
    'gm_alert2_body':       {'PT': 'O Tempo de Retorno representa a probabilidade anual de ocorrência '
                                   'de um evento igual ou superior (P = 1/TR). O risco de falha hidráulica '
                                   'de uma estrutura é diretamente dependente do TR escolhido para projeto.',
                             'EN': 'The Return Period represents the annual probability of occurrence '
                                   'of an equal or greater event (P = 1/TR). The hydraulic failure risk '
                                   'of a structure is directly dependent on the TR chosen for design.'},

    # ── Taborga Isozone Memory-of-Calculation (Passo 3) ─────────────────────
    'tab_page_title':       {'PT': 'Passo 3 — Metodologia de Isozonas (Taborga)',
                             'EN': 'Step 3 — Isozone Methodology (Taborga)'},
    'tab_card_main':        {'PT': 'Memória de Cálculo — Desagregação de Chuvas (Taborga)',
                             'EN': 'Calculation Memory — Rainfall Disaggregation (Taborga)'},

    # Section headings
    'tab_s1_title':         {'PT': '① Dados Base — Herança do Passo Estatístico (Gumbel)',
                             'EN': '① Base Data — Inherited from Statistical Step (Gumbel)'},
    'tab_s2_title':         {'PT': '② Seleção da Isozona',
                             'EN': '② Isozone Selection'},
    'tab_s3_title':         {'PT': '③ Tabela de Relações (Coeficientes Taborga)',
                             'EN': '③ Relations Table (Taborga Coefficients)'},
    'tab_s4_title':         {'PT': '④ Alturas de Precipitação (6 min e 1 h)',
                             'EN': '④ Precipitation Heights (6 min and 1 h)'},
    'tab_s5_title':         {'PT': '⑤ Resumo Gumbel — Limites Temporais de Projeto',
                             'EN': '⑤ Gumbel Summary — Design Time Limits'},
    'tab_s6_title':         {'PT': '⑥ Cálculo das Constantes K₁ e K₂',
                             'EN': '⑥ Calculation of Constants K₁ and K₂'},

    # Table 1 (base data) columns
    'tab_t1_tr':            {'PT': 'TR (Anos)',     'EN': 'TR (Years)'},
    'tab_t1_pt':            {'PT': 'Pt (mm)',       'EN': 'Pt (mm)'},
    'tab_t1_sn':            {'PT': "σ'n",           'EN': "σ'n"},
    'tab_t1_ap':            {'PT': 'Ap (24h) mm',   'EN': 'Ap (24h) mm'},

    # Table 3 (relations) rows
    'tab_t3_rel1h':         {'PT': 'Relação 1h / 24h  (a)',   'EN': '1h / 24h Ratio  (a)'},
    'tab_t3_rel6min':       {'PT': 'Relação 6min / 24h  (b)', 'EN': '6min / 24h Ratio  (b)'},

    # Table 4 (heights) rows
    'tab_t4_h1h':           {'PT': 'Altura 1h  (P₁ₕ = a × Ap)',    'EN': 'Height 1h  (P₁ₕ = a × Ap)'},
    'tab_t4_h6min':         {'PT': 'Altura 6min  (P₆ₘ = b × Ap)',  'EN': 'Height 6min  (P₆ₘ = b × Ap)'},

    # Table 5 (Gumbel summary) rows
    'tab_t5_6min':          {'PT': '6 min',         'EN': '6 min'},
    'tab_t5_1h':            {'PT': '1 hora',         'EN': '1 hour'},
    'tab_t5_24h':           {'PT': '24 horas',       'EN': '24 hours'},

    # Table 6 (K1/K2) headers
    'tab_t6_tr':            {'PT': 'TR (anos)',      'EN': 'TR (yrs)'},
    'tab_t6_p6':            {'PT': 'P₆ₘ (mm)',      'EN': 'P₆ₘ (mm)'},
    'tab_t6_p60':           {'PT': 'P₆₀ₘ (mm)',     'EN': 'P₆₀ₘ (mm)'},
    'tab_t6_p1440':         {'PT': 'P₁₄₄₀ (mm)',    'EN': 'P₁₄₄₀ (mm)'},
    'tab_t6_k1':            {'PT': 'K₁',             'EN': 'K₁'},
    'tab_t6_k2':            {'PT': 'K₂',             'EN': 'K₂'},

    # Right panel
    'tab_rp_title':         {'PT': 'Isozona Selecionada',   'EN': 'Selected Isozone'},
    'tab_rp_zone':          {'PT': 'Zona',                  'EN': 'Zone'},
    'tab_rp_coef_title':    {'PT': 'Constantes da Isozona', 'EN': 'Isozone Constants'},
    'tab_rp_rel1h':         {'PT': 'Relação 1h/24h',        'EN': '1h/24h Ratio'},
    'tab_rp_rel6min':       {'PT': 'Relação 6min/24h',      'EN': '6min/24h Ratio'},
    'tab_rp_tr_range':      {'PT': 'TR 5–50 anos',          'EN': 'TR 5–50 yrs'},
    'tab_rp_tr_100':        {'PT': 'TR 100 anos',           'EN': 'TR 100 yrs'},

    # Alerts
    'tab_alert1_title':     {'PT': 'Herança do Passo Estatístico',
                             'EN': 'Inherited from Statistical Step'},
    'tab_alert1_body':      {'PT': 'Os valores de Pt e σ\'n são provenientes da análise de Gumbel (Passo 2). '
                                   'A coluna Ap = Pt × 1,202 representa a altura de chuva equivalente a 24 horas.',
                             'EN': 'The Pt and σ\'n values come from the Gumbel analysis (Step 2). '
                                   'The Ap = Pt × 1.202 column represents the 24-hour equivalent rainfall height.'},
    'tab_alert2_title':     {'PT': 'Método de Taborga — Isozonas do Brasil',
                             'EN': 'Taborga Method — Brazil Isozones'},
    'tab_alert2_body':      {'PT': 'O método das Isozonas de Taborga divide o Brasil em 8 zonas (A–H) com '
                                   'coeficientes de desagregação específicos. Consulte o mapa para identificar '
                                   'a zona correspondente à localização da sua estação pluviométrica.',
                             'EN': 'Taborga\'s Isozone method divides Brazil into 8 zones (A–H) with specific '
                                   'disaggregation coefficients. Consult the map to identify the zone '
                                   'corresponding to your rain gauge station location.'},
    'tab_alert3_title':     {'PT': 'Interpolação Logarítmica (K₁ e K₂)',
                             'EN': 'Logarithmic Interpolation (K₁ and K₂)'},
    'tab_alert3_body':      {'PT': 'K₁ e K₂ são os coeficientes de interpolação logarítmica para os intervalos '
                                   '6–60 min e 60–1440 min respectivamente. Permitem calcular a precipitação '
                                   'para qualquer duração intermediária.',
                             'EN': 'K₁ and K₂ are the logarithmic interpolation coefficients for the 6–60 min '
                                   'and 60–1440 min intervals respectively. They allow calculating precipitation '
                                   'for any intermediate duration.'},

    # Map card
    'tab_map_title':        {'PT': 'Mapa de Isozonas do Brasil',  'EN': 'Brazil Isozone Map'},
    'tab_map_select':       {'PT': 'Isozona Ativa',               'EN': 'Active Isozone'},
    'tab_const_table':      {'PT': 'Tabela de Constantes — Relação 1h/24h por TR',
                             'EN': 'Constants Table — 1h/24h Ratio by TR'},

    # K1/K2 interval labels
    'tab_k_interval_short': {'PT': 'Intervalo Curto: 6 a 60 min',   'EN': 'Short Interval: 6 to 60 min'},
    'tab_k_interval_long':  {'PT': 'Intervalo Longo: 60 a 1440 min', 'EN': 'Long Interval: 60 to 1440 min'},
    'tab_k_formula_short':  {'PT': 'P(t) = P₆ₘ + K₁ × ln(t/6)',    'EN': 'P(t) = P₆ₘ + K₁ × ln(t/6)'},
    'tab_k_formula_long':   {'PT': 'P(t) = P₆₀ₘ + K₂ × ln(t/60)', 'EN': 'P(t) = P₆₀ₘ + K₂ × ln(t/60)'},

    # ── PDF Curves View (Passo 4) ─────────────────────────────────────────────
    'pdf_view_title':       {'PT': 'Passo 4 — Curvas PDF (Precipitação-Duração-Frequência)',
                             'EN': 'Step 4 — PDF Curves (Precipitation-Duration-Frequency)'},
    'pdf_chart_card':       {'PT': 'Gráfico — Precipitação Acumulada por Duração',
                             'EN': 'Chart — Accumulated Precipitation by Duration'},
    'pdf_table_card':       {'PT': 'Tabela de Precipitação P(t) por Duração e TR',
                             'EN': 'Precipitation P(t) Table by Duration and TR'},
    'pdf_table_dur':        {'PT': 'Duração (min)',  'EN': 'Duration (min)'},
    'pdf_math_title':       {'PT': '📐 Fundamentos Matemáticos — Passo 4',
                             'EN': '📐 Mathematical Foundations — Step 4'},
    'pdf_math_eq_title':    {'PT': 'Equação PDF (Precipitação)',
                             'EN': 'PDF Equation (Precipitation)'},
    'pdf_math_eq':          {'PT': 'P(t) = K₁ · log₁₀(t) − K₂',
                             'EN': 'P(t) = K₁ · log₁₀(t) − K₂'},
    'pdf_math_pt':          {'PT': 'P(t): Precipitação total para a duração t (mm).',
                             'EN': 'P(t): Total precipitation for duration t (mm).'},
    'pdf_math_t':           {'PT': 't: Duração da chuva em minutos.',
                             'EN': 't: Rainfall duration in minutes.'},
    'pdf_math_k1k2':        {'PT': 'K₁, K₂: Parâmetros calculados na desagregação para o intervalo de tempo.',
                             'EN': 'K₁, K₂: Parameters calculated in the disaggregation for the time interval.'},
    'pdf_math_intervals':   {'PT': 'Intervalos de Aplicação',
                             'EN': 'Application Intervals'},
    'pdf_math_short':       {'PT': 'Intervalo Curto (6 a 60 min):',
                             'EN': 'Short Interval (6 to 60 min):'},
    'pdf_math_long':        {'PT': 'Intervalo Longo (60 a 1440 min):',
                             'EN': 'Long Interval (60 to 1440 min):'},
    'pdf_math_short_eq':    {'PT': 'P(t) = P₆ₘ + K₁ × ln(t / 6)',
                             'EN': 'P(t) = P₆ₘ + K₁ × ln(t / 6)'},
    'pdf_math_long_eq':     {'PT': 'P(t) = P₆₀ₘ + K₂ × ln(t / 60)',
                             'EN': 'P(t) = P₆₀ₘ + K₂ × ln(t / 60)'},
    'pdf_math_k1_def':      {'PT': 'K₁ = (P₆₀ − P₆) / ln(60 / 6)',
                             'EN': 'K₁ = (P₆₀ − P₆) / ln(60 / 6)'},
    'pdf_math_k2_def':      {'PT': 'K₂ = (P₁₄₄₀ − P₆₀) / ln(1440 / 60)',
                             'EN': 'K₂ = (P₁₄₄₀ − P₆₀) / ln(1440 / 60)'},
    'pdf_math_note':        {'PT': 'Os coeficientes K₁ e K₂ são calculados no Passo 3 (Taborga) para cada '
                                   'Tempo de Retorno, usando os pontos âncora P₆ₘ, P₆₀ₘ e P₁₄₄₀ obtidos '
                                   'pela desagregação das isozonas.',
                             'EN': 'Coefficients K₁ and K₂ are calculated in Step 3 (Taborga) for each '
                                   'Return Period, using the anchor points P₆ₘ, P₆₀ₘ and P₁₄₄₀ obtained '
                                   'from the isozone disaggregation.'},
    'pdf_k_table_title':    {'PT': 'Coeficientes K₁ e K₂ por TR (do Passo 3)',
                             'EN': 'K₁ and K₂ Coefficients by TR (from Step 3)'},
    'pdf_k_tr':             {'PT': 'TR (anos)',  'EN': 'TR (yrs)'},
    'pdf_k_k1':             {'PT': 'K₁',         'EN': 'K₁'},
    'pdf_k_k2':             {'PT': 'K₂',         'EN': 'K₂'},
    'pdf_k_p6':             {'PT': 'P₆ₘ (mm)',   'EN': 'P₆ₘ (mm)'},
    'pdf_k_p60':            {'PT': 'P₆₀ₘ (mm)',  'EN': 'P₆₀ₘ (mm)'},
    'pdf_k_p1440':          {'PT': 'P₁₄₄₀ (mm)', 'EN': 'P₁₄₄₀ (mm)'},
    'pdf_alert_title':      {'PT': 'Origem dos Dados',  'EN': 'Data Origin'},
    'pdf_alert_body':       {'PT': 'Os valores de precipitação P(t) são calculados a partir da desagregação '
                                   'de Taborga (Passo 3). Cada curva representa um Tempo de Retorno diferente, '
                                   'mostrando como a precipitação acumulada varia com a duração da chuva.',
                             'EN': 'Precipitation values P(t) are calculated from the Taborga disaggregation '
                                   '(Step 3). Each curve represents a different Return Period, showing how '
                                   'accumulated precipitation varies with rainfall duration.'},

    # ── Step selector dropdown ────────────────────────────────────────────────
    'step_selector_label':  {'PT': 'Navegar para o Passo / Navigate to Step',
                             'EN': 'Navigate to Step / Navegar para o Passo'},
    'step_opt_guide':       {'PT': '🗺️ Guia — Como obter dados',
                             'EN': '🗺️ Guide — How to get data'},
    'step_opt_historica':   {'PT': '📊 Passo 1 — Série Histórica',
                             'EN': '📊 Step 1 — Historical Series'},
    'step_opt_gumbel_mem':  {'PT': '📐 Passo 2 — Memória Gumbel',
                             'EN': '📐 Step 2 — Gumbel Memory'},
    'step_opt_taborga':     {'PT': '🗺️ Passo 3 — Isozonas Taborga',
                             'EN': '🗺️ Step 3 — Taborga Isozones'},
    'step_opt_pdf':         {'PT': '🌧️ Passo 4 — Curvas PDF',
                             'EN': '🌧️ Step 4 — PDF Curves'},
    'step_opt_idf':         {'PT': '⚡ Passo 5 — Curvas IDF',
                             'EN': '⚡ Step 5 — IDF Curves'},
    'step_opt_tables':      {'PT': '📋 Passo 6 — Tabelas de Resultados',
                             'EN': '📋 Step 6 — Results Tables'},

    # ── Error / warning messages ──────────────────────────────────────────────
    'err_no_data':          {'PT': 'Nenhum dado de entrada fornecido. Por favor, faça upload de um arquivo ANA ou insira dados manualmente.',
                             'EN': 'No input data provided. Please upload an ANA file or enter data manually.'},
    'err_small_sample':     {'PT': 'Amostra pequena: N={}. Resultados podem ser pouco confiáveis.',
                             'EN': 'Small sample: N={}. Results may be unreliable.'},
    'err_no_period_data':   {'PT': 'Nenhum dado encontrado no período selecionado ({} – {}). Verifique os anos informados.',
                             'EN': 'No data found in the selected period ({} – {}). Please check the years entered.'},
}


def t(key: str, lang: str) -> str:
    """
    Translate a label key to the requested language.
    Falls back to Portuguese if the key or language is not found.
    """
    entry = LABELS.get(key, {})
    return entry.get(lang, entry.get('PT', key))
