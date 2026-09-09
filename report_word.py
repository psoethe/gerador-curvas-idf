"""
Word (.docx) report generator for IDF Curve Calculator.
Produces a professional Memorial de Cálculo / Calculation Report
using python-docx, mirroring the structure of the PDF report.
"""
import io
import logging
import datetime

from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from i18n import t
from calculations import (
    DURATIONS, SHERMAN_TYPICAL_RANGES,
    gerar_png_mapa_local, gerar_png_mapa_isozonas,
)

logger = logging.getLogger("viktor")

# ── Brand colours ─────────────────────────────────────────────────────────────
_BLUE_DARK  = RGBColor(0x1a, 0x52, 0x76)
_BLUE_MID   = RGBColor(0x29, 0x80, 0xb9)
_BLUE_LIGHT = RGBColor(0xd6, 0xea, 0xf8)
_WHITE      = RGBColor(0xff, 0xff, 0xff)
_GREY_DARK  = RGBColor(0x33, 0x41, 0x55)
_GREEN      = RGBColor(0x16, 0xa3, 0x4a)


# ── XML helpers ───────────────────────────────────────────────────────────────

def _set_cell_bg(cell, hex_color: str):
    """Set table cell background colour via XML shading."""
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  hex_color.lstrip('#'))
    tcPr.append(shd)


# ── Formatting helpers ────────────────────────────────────────────────────────

def _section_header(doc: Document, text: str) -> None:
    """Blue-bar section header."""
    p   = doc.add_paragraph()
    run = p.add_run(f'  {text}')
    run.bold = True
    run.font.size  = Pt(11)
    run.font.color.rgb = _WHITE
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  '1a5276')
    pPr.append(shd)
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after  = Pt(4)


def _para(doc: Document, text: str, bold: bool = False, italic: bool = False,
          size: int = 10, color: RGBColor = None,
          align=WD_ALIGN_PARAGRAPH.LEFT):
    """Add a styled paragraph."""
    p   = doc.add_paragraph()
    run = p.add_run(text)
    run.bold   = bold
    run.italic = italic
    run.font.size = Pt(size)
    if color:
        run.font.color.rgb = color
    p.alignment = align
    p.paragraph_format.space_after = Pt(3)
    return p


def _add_df_table(doc: Document, df,
                  header_hex: str = '1a5276',
                  alt_hex: str    = 'd6eaf8') -> None:
    """Render a pandas DataFrame as a styled Word table."""
    rows, cols = df.shape
    tbl = doc.add_table(rows=rows + 1, cols=cols)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.style = 'Table Grid'

    # Header
    for j, col_name in enumerate(df.columns):
        cell = tbl.rows[0].cells[j]
        cell.text = str(col_name)
        r = cell.paragraphs[0].runs[0]
        r.bold = True
        r.font.size = Pt(9)
        r.font.color.rgb = _WHITE
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_cell_bg(cell, header_hex)

    # Data rows
    for i, (_, row_data) in enumerate(df.iterrows()):
        bg = alt_hex if i % 2 == 0 else 'ffffff'
        for j, val in enumerate(row_data):
            cell = tbl.rows[i + 1].cells[j]
            cell.text = str(val)
            r = cell.paragraphs[0].runs[0]
            r.font.size = Pt(9)
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_cell_bg(cell, bg)

    doc.add_paragraph()


def _add_figure(doc: Document, png_bytes: bytes, caption: str,
                width_cm: float = 15.0) -> None:
    """Embed a PNG figure with a centred caption."""
    if not png_bytes:
        return
    buf = io.BytesIO(png_bytes)
    doc.add_picture(buf, width=Cm(width_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap = doc.add_paragraph(caption)
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.runs[0].italic = True
    cap.runs[0].font.size = Pt(9)
    cap.runs[0].font.color.rgb = _GREY_DARK
    doc.add_paragraph()


def _sherman_block(doc: Document, sherman: dict, lang: str) -> None:
    """
    Render the Sherman equation block:
      i = A · TR^B / (t ± C)^D
    with parameter grid and R² / RMSE / NSE.
    """
    import pandas as pd
    is_pt = lang == 'PT'
    A = sherman['A'];  B = sherman['B']
    C = sherman['C'];  D = sherman['D']
    r2   = sherman['R²']
    rmse = sherman['RMSE']
    nse  = sherman['NSE']
    c_sign = '+' if C >= 0 else '-'
    c_abs  = abs(C)

    # Equation line with superscripts
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after  = Pt(6)

    def _r(text, bold=True, size=13, color=_BLUE_DARK, sup=False):
        run = p.add_run(text)
        run.bold = bold
        run.font.size = Pt(size)
        run.font.color.rgb = color
        if sup:
            run.font.superscript = True
        return run

    _r('i  =  ')
    _r(f'{A:.4f}')
    _r(' \u00b7 TR')          # · TR
    _r(f'{B:.4f}', sup=True, size=9)
    _r('  /  (t ')
    _r(f'{c_sign} {c_abs:.4f}')
    _r(')')
    _r(f'{D:.4f}', sup=True, size=9)

    # Parameter grid (1 row labels + 1 row values, 4 columns)
    lbl_a = 'A (CONSTANTE)'      if is_pt else 'A (CONSTANT)'
    lbl_b = 'B (EXPOENTE TR)'    if is_pt else 'B (TR EXPONENT)'
    lbl_c = 'C (AJUSTE TEMPO)'   if is_pt else 'C (TIME ADJUST)'
    lbl_d = 'D (EXPOENTE TEMPO)' if is_pt else 'D (TIME EXPONENT)'

    tbl = doc.add_table(rows=2, cols=4)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.style = 'Table Grid'
    params_data = [(lbl_a, f'{A:.4f}'), (lbl_b, f'{B:.4f}'),
                   (lbl_c, f'{c_abs:.4f}'), (lbl_d, f'{D:.4f}')]
    for ci, (lbl, val) in enumerate(params_data):
        lc = tbl.rows[0].cells[ci]
        lc.text = lbl
        lc.paragraphs[0].runs[0].bold = True
        lc.paragraphs[0].runs[0].font.size = Pt(8)
        lc.paragraphs[0].runs[0].font.color.rgb = _WHITE
        lc.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_cell_bg(lc, '1e3a5f')
        vc = tbl.rows[1].cells[ci]
        vc.text = val
        vc.paragraphs[0].runs[0].bold = True
        vc.paragraphs[0].runs[0].font.size = Pt(11)
        vc.paragraphs[0].runs[0].font.color.rgb = _BLUE_DARK
        vc.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_cell_bg(vc, 'd6eaf8')
    doc.add_paragraph()

    # Validation metrics
    lbl_valid = 'Validacao Estatistica' if is_pt else 'Statistical Validation'
    _section_header(doc, f'📈 {lbl_valid}')

    r2_pct = f'{r2 * 100:.2f}%'
    lbl_r2 = 'Coeficiente de Determinacao (R2)' if is_pt else 'Coefficient of Determination (R2)'
    p_r2 = doc.add_paragraph()
    p_r2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2_run = p_r2.add_run(f'{lbl_r2}:  {r2_pct}')
    r2_run.bold = True
    r2_run.font.size = Pt(14)
    r2_run.font.color.rgb = _GREEN

    tbl2 = doc.add_table(rows=2, cols=2)
    tbl2.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl2.style = 'Table Grid'
    lbl_err_med = 'Erro Médio Celular' if is_pt else 'Mean Cell Error'
    val_err_med = f"{sherman.get('erro_medio_celula', 0.0):.2f}%"
    for ci, (lbl, val) in enumerate([('RMSE (mm/h)', f'{rmse:.4f}'), (lbl_err_med, val_err_med)]):
        hc = tbl2.rows[0].cells[ci]
        hc.text = lbl
        hc.paragraphs[0].runs[0].bold = True
        hc.paragraphs[0].runs[0].font.size = Pt(9)
        hc.paragraphs[0].runs[0].font.color.rgb = _WHITE
        hc.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_cell_bg(hc, '1a5276')
        vc = tbl2.rows[1].cells[ci]
        vc.text = val
        vc.paragraphs[0].runs[0].bold = True
        vc.paragraphs[0].runs[0].font.size = Pt(11)
        vc.paragraphs[0].runs[0].font.color.rgb = _BLUE_DARK
        vc.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_cell_bg(vc, 'eaf4fb')
    doc.add_paragraph()

    # Detailed Sherman Parameters Table in Word
    p_tbl = doc.add_paragraph()
    p_tbl.add_run(
        'Parâmetros Detalhados da Equação de Sherman (com Intervalos de Confiança)' if is_pt
        else 'Detailed Sherman Equation Parameters (with Confidence Intervals)'
    ).bold = True
    p_tbl.runs[0].font.size = Pt(10)
    p_tbl.runs[0].font.color.rgb = _BLUE_DARK

    ci_a = f"[{sherman.get('ci_A', (0,0))[0]:.1f}, {sherman.get('ci_A', (0,0))[1]:.1f}]" if 'ci_A' in sherman else '—'
    ci_b = f"[{sherman.get('ci_B', (0,0))[0]:.4f}, {sherman.get('ci_B', (0,0))[1]:.4f}]" if 'ci_B' in sherman else '—'
    ci_c = f"[{sherman.get('ci_C', (0,0))[0]:.2f}, {sherman.get('ci_C', (0,0))[1]:.2f}]" if 'ci_C' in sherman else '—'
    ci_d = f"[{sherman.get('ci_D', (0,0))[0]:.4f}, {sherman.get('ci_D', (0,0))[1]:.4f}]" if 'ci_D' in sherman else '—'

    rng_a = f"{SHERMAN_TYPICAL_RANGES['A'][0]:g} a {SHERMAN_TYPICAL_RANGES['A'][1]:g}"
    rng_b = f"{SHERMAN_TYPICAL_RANGES['B'][0]:g} a {SHERMAN_TYPICAL_RANGES['B'][1]:g}"
    rng_c = f"{SHERMAN_TYPICAL_RANGES['C'][0]:g} a {SHERMAN_TYPICAL_RANGES['C'][1]:g}"
    rng_d = f"{SHERMAN_TYPICAL_RANGES['D'][0]:g} a {SHERMAN_TYPICAL_RANGES['D'][1]:g}"

    rows_detail = [
        ('A (constante / constant)', f'{A:.4f}', f"{sherman.get('se_A', 0.0):.4f}", ci_a, rng_a),
        ('B (expoente TR / exponent)', f'{B:.4f}', f"{sherman.get('se_B', 0.0):.4f}", ci_b, rng_b),
        ('C (ajuste tempo / time adj)', f'{c_abs:.4f}', f"{sherman.get('se_C', 0.0):.4f}", ci_c, rng_c),
        ('D (expoente tempo / exponent)', f'{D:.4f}', f"{sherman.get('se_D', 0.0):.4f}", ci_d, rng_d),
    ]
    hdrs_detail = ['Parâmetro', 'Valor', 'Erro Padrão', 'IC 95%', 'Faixa Plausível'] if is_pt else ['Parameter', 'Value', 'Std Error', '95% CI', 'Plausible Range']

    dtbl = doc.add_table(rows=len(rows_detail) + 1, cols=5)
    dtbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    dtbl.style = 'Table Grid'
    for ci, h in enumerate(hdrs_detail):
        c = dtbl.rows[0].cells[ci]
        c.text = h
        c.paragraphs[0].runs[0].bold = True
        c.paragraphs[0].runs[0].font.size = Pt(8.5)
        c.paragraphs[0].runs[0].font.color.rgb = _WHITE
        c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_cell_bg(c, '3730a3')

    for ri, rvals in enumerate(rows_detail):
        row = dtbl.rows[ri + 1]
        bg = 'e0e7ff' if ri % 2 == 0 else 'ffffff'
        for ci, val in enumerate(rvals):
            cell = row.cells[ci]
            cell.text = str(val)
            cell.paragraphs[0].runs[0].font.size = Pt(8.5)
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_cell_bg(cell, bg)

    if 'erro_max_celula' in sherman:
        doc.add_paragraph()
        p_err = doc.add_paragraph()
        err_text = (
            f"Erro Máximo por Célula: {sherman['erro_max_celula']:.2f}%  |  "
            f"Erro Médio por Célula: {sherman['erro_medio_celula']:.2f}%  |  "
            f"Ajuste: {sherman.get('modo_ajuste', 'log')}"
        ) if is_pt else (
            f"Max Cell Error: {sherman['erro_max_celula']:.2f}%  |  "
            f"Mean Cell Error: {sherman['erro_medio_celula']:.2f}%  |  "
            f"Fit Mode: {sherman.get('modo_ajuste', 'log')}"
        )
        p_err.add_run(err_text).italic = True
        p_err.runs[0].font.size = Pt(8.5)
        p_err.runs[0].font.color.rgb = _GREY_DARK
    doc.add_paragraph()


# ── Main public function ──────────────────────────────────────────────────────

def generate_word_report(
    results: dict,
    responsavel: str,
    localizacao: str,
    estacao: str,
    fig_historica,
    fig_gumbel,
    fig_pdf,
    fig_idf,
    lang: str = 'PT',
    coords: tuple[float, float] | None = None,
    idw_meta: dict | None = None,
    station_info: dict | None = None,
    search_radius_km: float = 35.0,
    app_name: str = 'SII-HiDRO-IDF',
    bacia_results: dict | None = None,
    vazao_results: dict | None = None,
) -> bytes:
    """
    Generate a complete Word (.docx) Memorial de Calculo / Calculation Report.
    Returns raw .docx bytes.
    """
    import pandas as pd
    logger.info(f"📝 Gerando relatorio Word completo (lang={lang})...")

    # Unpack
    series_df  = results['series_df']
    gumbel_df  = results['gumbel_df']
    disagg_df  = results['disagg_df']
    idf_df     = results['idf_df']
    sherman    = results['sherman_params']
    mu         = results['mu']
    sigma      = results['sigma']
    n          = results['n_samples']
    isozona    = results['isozona']
    gumbel_mem = results['gumbel_memory']
    year_start = results.get('year_start')
    year_end   = results.get('year_end')

    from calculations import compute_taborga_memory, DURATIONS
    tab_mem = compute_taborga_memory(gumbel_mem, isozona, lang)

    col_ano = t('col_ano', lang)
    y0 = year_start or int(series_df[col_ano].min())
    y1 = year_end   or int(series_df[col_ano].max())
    period_str = f'{y0} - {y1}'

    is_pt = lang == 'PT'
    now   = datetime.datetime.now()
    report_id = f'IDF-{estacao or "XXX"}-{now.strftime("%Y%m%d-%H%M")}'

    # Render figures to PNG
    logger.info("🖼️ Renderizando figuras para PNG (Word)...")
    try:
        import plotly.io as pio
        png_hist   = pio.to_image(fig_historica, format='png', width=860, height=380, scale=1.5)
        png_gumbel = pio.to_image(fig_gumbel,    format='png', width=860, height=380, scale=1.5)
        png_pdf    = pio.to_image(fig_pdf,        format='png', width=860, height=440, scale=1.5)
        png_idf    = pio.to_image(fig_idf,        format='png', width=860, height=440, scale=1.5)
        logger.info("🖼️ Figuras Word: todas renderizadas")
    except Exception as exc:
        logger.warning(f"⚠️ Falha ao renderizar figuras para Word: {exc}")
        png_hist = png_gumbel = png_pdf = png_idf = None

    # Create document
    doc = Document()
    for sec in doc.sections:
        sec.top_margin    = Cm(2.0)
        sec.bottom_margin = Cm(2.0)
        sec.left_margin   = Cm(2.5)
        sec.right_margin  = Cm(2.5)

    # ── COVER ─────────────────────────────────────────────────────────────────
    doc.add_paragraph()
    tp = doc.add_paragraph()
    tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = tp.add_run(f'⚡ {app_name}')
    tr.bold = True
    tr.font.size = Pt(24)
    tr.font.color.rgb = _BLUE_DARK

    sub_text = 'Memorial de Calculo - Curvas IDF' if is_pt else 'Calculation Report - IDF Curves'
    sp = doc.add_paragraph(sub_text)
    sp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sp.runs[0].font.size = Pt(14)
    sp.runs[0].font.color.rgb = _BLUE_MID
    doc.add_paragraph()

    meta_rows = [
        (t('report_responsavel', lang), responsavel or '-'),
        (t('report_localizacao', lang),  localizacao or '-'),
    ]
    if coords and len(coords) == 2 and coords[0] != 0.0:
        meta_rows.append(('Coordenadas', f'Lat: {coords[0]:.4f}°, Lon: {coords[1]:.4f}°'))
    iso_txt = str(isozona)
    if results.get('isozona_origem'):
        iso_txt += f" ({results.get('isozona_origem')})"
    meta_rows.extend([
        (t('report_estacao', lang),      estacao or '-'),
        (t('report_period', lang),       period_str),
        (t('report_isozona', lang),      iso_txt),
        (t('report_n', lang),            f'N = {n} {t("report_n_suffix", lang)}'),
        ('Versão do Sistema / System Ver.', 'SII-HiDRO v3.0'),
        (t('report_date', lang),         now.strftime('%d/%m/%Y %H:%M:%S')),
        ('ID', report_id),
    ])
    mt = doc.add_table(rows=len(meta_rows), cols=2)
    mt.alignment = WD_TABLE_ALIGNMENT.CENTER
    mt.style = 'Table Grid'
    for i, (k, v) in enumerate(meta_rows):
        bg = 'eaf4fb' if i % 2 == 0 else 'ffffff'
        kc = mt.rows[i].cells[0]
        vc = mt.rows[i].cells[1]
        kc.text = k
        vc.text = str(v)
        kc.paragraphs[0].runs[0].bold = True
        kc.paragraphs[0].runs[0].font.size = Pt(10)
        kc.paragraphs[0].runs[0].font.color.rgb = _BLUE_DARK
        vc.paragraphs[0].runs[0].font.size = Pt(10)
        _set_cell_bg(kc, 'd6eaf8')
        _set_cell_bg(vc, bg)

    doc.add_page_break()

    # ── PASSO 1 — Serie Historica ─────────────────────────────────────────────
    _section_header(doc, ('Passo 1 - Serie Historica de Precipitacao'
                          if is_pt else 'Step 1 - Historical Precipitation Series'))
    _para(doc, f'Estacao: {estacao or "-"}  |  Periodo: {period_str}  |  N = {n}')
    _para(doc, f'mu = {mu:.3f} mm  |  sigma = {sigma:.3f} mm', bold=True, color=_BLUE_DARK)

    # Tabela IDW no Word
    if idw_meta and idw_meta.get('stations'):
        doc.add_paragraph()
        p_idw = doc.add_paragraph()
        p_idw.add_run(
            'Interpolação Espacial IDW (Inverse Distance Weighting)' if is_pt
            else 'Spatial Interpolation IDW (Inverse Distance Weighting)'
        ).bold = True
        p_idw.runs[0].font.size = Pt(11)
        p_idw.runs[0].font.color.rgb = _BLUE_DARK

        idw_tbl = doc.add_table(rows=len(idw_meta['stations']) + 1, cols=6)
        idw_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        idw_tbl.style = 'Table Grid'
        hdr_texts = ['Código', 'Estação', 'Operadora', 'Alt. (m)', 'Dist. (km)', 'Peso (%)'] if is_pt else ['Code', 'Station', 'Operator', 'Alt. (m)', 'Dist. (km)', 'Weight (%)']
        for ci, h in enumerate(hdr_texts):
            c = idw_tbl.rows[0].cells[ci]
            c.text = h
            c.paragraphs[0].runs[0].bold = True
            c.paragraphs[0].runs[0].font.size = Pt(9)
            c.paragraphs[0].runs[0].font.color.rgb = _WHITE
            c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_cell_bg(c, '1a5276')

        for ri, s_info in enumerate(idw_meta['stations']):
            row = idw_tbl.rows[ri + 1]
            bg = 'eaf4fb' if ri % 2 == 0 else 'ffffff'
            alt_txt = f"{s_info.get('altitude', 0.0):.0f}" if s_info.get('altitude') is not None else '—'
            vals = [
                str(s_info.get('codigo', '—')),
                str(s_info.get('nome', '—')),
                str(s_info.get('operadora', '—')),
                alt_txt,
                f"{s_info.get('distancia_km', 0.0):.2f}",
                f"{s_info.get('peso_pct', 0.0):.1f}%",
            ]
            for ci, val in enumerate(vals):
                cell = row.cells[ci]
                cell.text = val
                cell.paragraphs[0].runs[0].font.size = Pt(9)
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
                _set_cell_bg(cell, bg)

    # Anos Descartados no Word
    anos_desc = results.get('anos_descartados', [])
    if anos_desc:
        doc.add_paragraph()
        p_desc = doc.add_paragraph()
        p_desc.add_run(
            'Anos Descartados da Análise (Rastreabilidade)' if is_pt
            else 'Years Excluded from Analysis (Traceability)'
        ).bold = True
        p_desc.runs[0].font.size = Pt(11)
        p_desc.runs[0].font.color.rgb = RGBColor(0xb9, 0x1c, 0x1c)

        desc_tbl = doc.add_table(rows=len(anos_desc) + 1, cols=4)
        desc_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        desc_tbl.style = 'Table Grid'
        desc_hdrs = ['Ano', 'Chuva (mm)', 'Dias Válidos', 'Motivo da Exclusão'] if is_pt else ['Year', 'Rainfall (mm)', 'Valid Days', 'Reason for Exclusion']
        for ci, h in enumerate(desc_hdrs):
            c = desc_tbl.rows[0].cells[ci]
            c.text = h
            c.paragraphs[0].runs[0].bold = True
            c.paragraphs[0].runs[0].font.size = Pt(9)
            c.paragraphs[0].runs[0].font.color.rgb = _WHITE
            c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_cell_bg(c, 'b91c1c')

        for ri, item in enumerate(anos_desc):
            row = desc_tbl.rows[ri + 1]
            bg = 'fee2e2' if ri % 2 == 0 else 'ffffff'
            vals = [
                str(item.get('ano', '—')),
                f"{item.get('valor', 0.0):.1f}",
                str(item.get('dias_validos', '—')),
                str(item.get('motivo', '—')),
            ]
            for ci, val in enumerate(vals):
                cell = row.cells[ci]
                cell.text = val
                cell.paragraphs[0].runs[0].font.size = Pt(9)
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
                _set_cell_bg(cell, bg)

    doc.add_paragraph()
    df_hist_word = series_df.copy()
    col_p = t('col_precip', lang)
    if col_p not in df_hist_word.columns and 'Precipitacao' in df_hist_word.columns:
        df_hist_word[col_p] = df_hist_word['Precipitacao']
    col_a = t('col_ano', lang)
    if col_a not in df_hist_word.columns and 'Ano' in df_hist_word.columns:
        df_hist_word[col_a] = df_hist_word['Ano']
    colunas_word = [c for c in [col_a, t('col_data', lang), t('col_origem', lang), col_p] if c in df_hist_word.columns]
    if len(colunas_word) >= 2:
        df_hist_word = df_hist_word[colunas_word]

    _add_df_table(doc, df_hist_word)
    if idw_meta and idw_meta.get('stations'):
        p_nota = doc.add_paragraph()
        p_nota.add_run(
            'Nota: Os valores de precipitação acima representam a máxima diária ponderada espacialmente via IDW, '
            'não correspondendo a um mesmo dia de evento registrado em calendário único.' if is_pt
            else 'Note: Precipitation values represent IDW spatially weighted daily maxima, not a single calendar event date.'
        ).italic = True
        p_nota.runs[0].font.size = Pt(8.5)
        p_nota.runs[0].font.color.rgb = _GREY_DARK

    # Mapa de Localização da Obra e Estações Pluviométricas
    png_mapa_local = gerar_png_mapa_local(
        coords=coords,
        localizacao=localizacao,
        idw_meta=idw_meta,
        station_info=station_info,
        search_radius_km=search_radius_km,
        lang=lang,
    )
    if png_mapa_local:
        cap_loc = (
            f"Figura 1 - Mapa de Localizacao da Obra ({localizacao or 'Projeto'}) e Estacoes Pluviometricas (Raio: {search_radius_km:.0f} km)"
            if is_pt else
            f"Figure 1 - Project Location Map ({localizacao or 'Project'}) and Rain Gauge Stations ({search_radius_km:.0f} km radius)"
        )
        _add_figure(doc, png_mapa_local, cap_loc, width_cm=15.0)

    _add_figure(doc, png_hist, 'Figura 2 - Serie Historica de Precipitacao Maxima Diaria Anual' if is_pt else 'Figure 2 - Annual Maximum Daily Precipitation Historical Series')
    doc.add_page_break()

    # ── PASSO 2 — Analise de Gumbel ───────────────────────────────────────────
    _section_header(doc, ('Passo 2 - Analise de Gumbel'
                          if is_pt else 'Step 2 - Gumbel Analysis'))
    _para(doc, f'N = {n}  |  Yn = {gumbel_mem["stats"]["yn"]:.4f}  |  Sn = {gumbel_mem["stats"]["sn"]:.4f}', bold=True)
    _para(doc, f'mu = {mu:.3f} mm  |  sigma = {sigma:.3f} mm')
    doc.add_paragraph()
    _add_df_table(doc, gumbel_df)
    _add_figure(doc, png_gumbel, 'Figura 3 - Analise de Gumbel' if is_pt else 'Figure 3 - Gumbel Analysis')
    doc.add_page_break()

    # ── PASSO 3 — Desagregacao de Taborga ────────────────────────────────────
    _section_header(doc, ('Passo 3 - Desagregacao de Taborga'
                          if is_pt else 'Step 3 - Taborga Disaggregation'))
    _para(doc, f'Isozona: {isozona}', bold=True, color=_BLUE_DARK)
    doc.add_paragraph()

    # Mapa Oficial de Isozonas com Pin do Projeto
    png_mapa_isozona = gerar_png_mapa_isozonas(coords)
    if png_mapa_isozona:
        cap_iso = (
            f"Figura - Mapa Oficial de Isozonas de Chuvas Intensas do Brasil (Taborga, 1974) — Posicao da Obra (Isozona {isozona})"
            if is_pt else
            f"Figure - Official Isozone Map of Heavy Rainfall in Brazil (Taborga, 1974) — Project Location (Isozone {isozona})"
        )
        _add_figure(doc, png_mapa_isozona, cap_iso, width_cm=11.5)

    k_rows = tab_mem['k_rows']
    if k_rows:
        k_df = pd.DataFrame(k_rows)
        k_df.columns = [
            t('pdf_k_tr', lang), t('pdf_k_p6', lang), t('pdf_k_p60', lang),
            t('pdf_k_p1440', lang), t('pdf_k_k1', lang), t('pdf_k_k2', lang),
        ]
        _add_df_table(doc, k_df)
    doc.add_page_break()

    # ── PASSO 4 — Curvas PDF ──────────────────────────────────────────────────
    _section_header(doc, ('Passo 4 - Curvas PDF - Precipitacao-Duracao-Frequencia'
                          if is_pt else 'Step 4 - PDF Curves - Precipitation-Duration-Frequency'))
    _para(doc, ('Precipitacao acumulada P(t) por duracao e periodo de retorno.'
                if is_pt else 'Accumulated precipitation P(t) by duration and return period.'))
    doc.add_paragraph()
    pdf_disp = disagg_df.copy()
    pdf_disp.index = DURATIONS
    pdf_disp.index.name = t('pdf_table_dur', lang)
    pdf_disp = pdf_disp.reset_index()
    pdf_disp.columns = [t('pdf_table_dur', lang)] + [
        f'TR={c.split("=")[1].split(" ")[0]}' for c in disagg_df.columns
    ]
    for c in pdf_disp.columns[1:]:
        pdf_disp[c] = pdf_disp[c].round(3)
    _add_df_table(doc, pdf_disp)
    _add_figure(doc, png_pdf, 'Figura 3 - Curvas PDF - Precipitacao Acumulada por Duracao')
    doc.add_page_break()

    # ── PASSO 5 — Curvas IDF ──────────────────────────────────────────────────
    _section_header(doc, ('Passo 5 - Curvas IDF - Intensidade-Duracao-Frequencia'
                          if is_pt else 'Step 5 - IDF Curves - Intensity-Duration-Frequency'))
    _para(doc, ('Intensidade i(t,TR) = P(t,TR) / (t/60) em mm/h.'
                if is_pt else 'Intensity i(t,TR) = P(t,TR) / (t/60) in mm/h.'))
    doc.add_paragraph()
    idf_disp = idf_df.copy()
    idf_disp.index = DURATIONS
    idf_disp.index.name = t('pdf_table_dur', lang)
    idf_disp = idf_disp.reset_index()
    idf_disp.columns = [t('pdf_table_dur', lang)] + [
        f'TR={c.split("=")[1].split(" ")[0]}' for c in idf_df.columns
    ]
    for c in idf_disp.columns[1:]:
        idf_disp[c] = idf_disp[c].round(3)
    _add_df_table(doc, idf_disp)
    _add_figure(doc, png_idf, 'Figura 4 - Curvas IDF - Intensidade-Duracao-Frequencia')
    doc.add_page_break()

    # ── PASSO 6 — Parametros de Sherman ──────────────────────────────────────
    _section_header(doc, ('Passo 6 - Parametros de Sherman'
                          if is_pt else 'Step 6 - Sherman Parameters'))
    _para(doc, ('Ajuste da equacao de Sherman (Montana) aos dados IDF por minimos quadrados nao-lineares.'
                if is_pt else 'Fitting the Sherman (Montana) equation to IDF data via nonlinear least squares.'))
    doc.add_paragraph()
    _sherman_block(doc, sherman, lang)

    # ── MÓDULO BACIA HIDROGRÁFICA (SII-HiDRO-Bacia) ──────────────────────────
    if bacia_results and isinstance(bacia_results, dict):
        p_bac = bacia_results.get('parametros', {}) or {}
        u_bac = bacia_results.get('uso_solo', {}) or {}
        c_bac = bacia_results.get('conferencia', {}) or {}

        doc.add_page_break()
        _section_header(doc, ('Módulo Bacia - Morfometria e Insumos Hidrológicos'
                              if is_pt else 'Basin Module - Morphometry & Hydrological Inputs'))
        _para(doc, ('Caracterizacao morfometrica obtida por delineacao digital baseada em FABDEM (30m) e D8 em SIRGAS 2000 UTM.'
                    if is_pt else 'Morphometric characterization obtained via digital delineation using FABDEM (30m) and D8.'))
        doc.add_paragraph()

        bacia_rows = [
            ('Área de Drenagem / Drainage Area', f"{p_bac.get('area_km2', 0.0):.3f} km² ({p_bac.get('area_km2', 0.0)*100:.1f} ha)"),
            ('Perímetro / Perimeter', f"{p_bac.get('perimetro_km', 0.0):.2f} km"),
            ('Comprimento do Talvegue / Main Stream Length', f"{p_bac.get('talvegue_km', p_bac.get('comprimento_talvegue_km', 0.0)):.3f} km"),
            ('Comprimento Axial / Axial Length', f"{p_bac.get('comprimento_axial_km', 0.0):.3f} km"),
            ('Desnível do Talvegue / Elevation Difference (ΔH)', f"{p_bac.get('desnivel_m', 0.0):.1f} m"),
            ('Cota do Exutório / Outlet Elevation', f"{p_bac.get('cota_exutorio_m', 0.0):.1f} m"),
            ('Cota do Ponto Remoto / Remote Point Elevation', f"{p_bac.get('cota_remota_m', 0.0):.1f} m"),
            ('Declividade Média do Talvegue / Stream Slope (S)', f"{p_bac.get('declividade_talvegue_m_m', 0.0)*100:.2f}%"),
            ('Declividade S10-85 / S10-85 Slope', f"{p_bac.get('declividade_s10_85_pct', 0.0):.2f}%"),
            ('Declividade Equivalente / Equivalent Slope', f"{p_bac.get('declividade_equivalente_pct', 0.0):.2f}%"),
            ('Declividade Média da Bacia / Mean Basin Slope', f"{p_bac.get('declividade_bacia_pct', p_bac.get('declividade_media_pct', 0.0)):.1f}%"),
            ('Coeficiente de Compacidade / Compactness (Kc)', f"{p_bac.get('coeficiente_compacidade_kc', 0.0):.3f}"),
            ('Fator de Forma / Shape Factor (Kf)', f"{p_bac.get('fator_forma_kf', 0.0):.3f}"),
            ('Densidade de Drenagem / Drainage Density', f"{p_bac.get('densidade_drenagem_km_km2', 0.0):.2f} km/km²"),
            ('Ordem de Strahler / Strahler Stream Order', str(p_bac.get('ordem_strahler', '—'))),
            ('Uso do Solo Predominante / Land Use', str(u_bac.get('fonte', 'MapBiomas'))),
            ('Grupo Hidrológico / Soil Group', str(u_bac.get('grupo_hidrologico_soilgrids', '—'))),
            ('Curve Number Ponderado (CN)', f"{u_bac.get('cn_ponderado', 0.0):.1f}"),
            ('Coeficiente C Ponderado (Runoff)', f"{u_bac.get('c_ponderado', 0.0):.3f}"),
        ]
        if u_bac.get('sobrescrita'):
            sobr = u_bac['sobrescrita']
            bacia_rows.append(('Sobrescrita Manual Adotada', f"C={sobr.get('c')}, CN={sobr.get('cn')} (Motivo: {sobr.get('motivo')})"))
        if c_bac:
            bacia_rows.append(('Conferência ANA BHO', f"Área ANA: {c_bac.get('area_km2', 0.0):.2f} km² (Divergência: {c_bac.get('divergencia_pct', 0.0):.1f}%)"))
        bacia_rows.append(('Validação Visual do Divisor', 'Confirmado pelo Responsável Técnico' if bacia_results.get('confirmada_por_usuario') else 'Pendente'))

        df_bacia_doc = pd.DataFrame(bacia_rows, columns=['Parâmetro / Parameter', 'Valor / Value'])
        _add_df_table(doc, df_bacia_doc)

    # ── MÓDULO VAZÃO DE PROJETO (SII-HiDRO-Vazão) ─────────────────────────────
    if vazao_results and isinstance(vazao_results, dict):
        doc.add_page_break()
        _section_header(doc, ('Módulo Vazão - Tempo de Concentração e Vazão de Projeto'
                              if is_pt else 'Discharge Module - Time of Concentration & Design Flow'))
        _para(doc, ('Determinação da vazão de cheia de projeto conforme o critério normativo de área do DNIT IPR-724.'
                    if is_pt else 'Determination of peak design flow according to DNIT IPR-724 normative area criteria.'))
        doc.add_paragraph()

        # Tabela comparativa de tc
        tc_info = vazao_results.get('tc_data', {})
        if tc_info and 'formulas' in tc_info:
            _para(doc, '1. Estimativa Multi-Fórmula do Tempo de Concentração (tc)', bold=True)
            tc_doc_rows = []
            for f in tc_info['formulas']:
                tc_doc_rows.append({
                    'Fórmula': f['nome'],
                    'tc (min)': f"{f['tc_min']:.1f}",
                    'tc (h)': f"{f['tc_h']:.2f}",
                    'Domínio de Calibração': f['dominio'],
                    'Validade': 'No domínio' if f['no_dominio'] else 'Fora do domínio',
                })
            df_tc_doc = pd.DataFrame(tc_doc_rows)
            _add_df_table(doc, df_tc_doc)
            doc.add_paragraph()

        _para(doc, '2. Decisão Normativa e Resultados Hidrológicos', bold=True)
        vazao_rows = [
            ('tc Adotado / Adopted tc', f"{vazao_results.get('tc_adotado_min', 0.0):.1f} min ({vazao_results.get('formula_tc_adotada', '—')})"),
            ('Período de Retorno / Design TR', f"{vazao_results.get('tr_anos', 25):.0f} anos / years"),
            ('Intensidade de Chuva IDF (i)', f"{vazao_results.get('intensidade_chuva_mm_h', 0.0):.2f} mm/h"),
            ('Método Hidrológico Adotado', str(vazao_results.get('nome_metodo_adotado', '—'))),
            ('Limiar Normativo DNIT IPR-724', f"{vazao_results.get('limiar_ipr724_km2', 1.0):.2f} km² (100 ha)"),
            ('Status do Método Racional', 'BLOQUEADO (Área > 100 ha, DNIT IPR-724)' if vazao_results.get('bloqueio_racional') else 'Elegível'),
            ('Vazão de Projeto Q', f"{vazao_results.get('q_projeto_m3s', 0.0):.2f} m³/s"),
        ]
        if vazao_results.get('metodo_adotado') == 'scs' and 'scs' in vazao_results:
            scs_d = vazao_results['scs']
            vazao_rows.extend([
                ('Tempo ao Pico (tp)', f"{scs_d.get('tempo_pico_h', 0.0):.2f} h ({scs_d.get('tempo_pico_min', 0.0):.0f} min)"),
                ('Volume Total Escoado', f"{scs_d.get('volume_total_m3', 0.0):,.0f} m³"),
                ('Chuva Total', f"{scs_d.get('lamina_total_mm', 0.0):.1f} mm"),
                ('Chuva Efetiva Pe', f"{scs_d.get('lamina_efetiva_mm', 0.0):.1f} mm"),
                ('Fator de Abatimento Espacial (ARF)', f"{scs_d.get('coef_abatimento_espacial', 1.0):.3f}"),
            ])
        df_vazao_doc = pd.DataFrame(vazao_rows, columns=['Parâmetro / Parameter', 'Valor / Value'])
        _add_df_table(doc, df_vazao_doc)

    # ── FOOTER ────────────────────────────────────────────────────────────────
    doc.add_page_break()
    _para(doc,
          (f'Relatorio gerado automaticamente pelo {app_name} em {now.strftime("%d/%m/%Y %H:%M")}.'
           if is_pt else
           f'Report automatically generated by {app_name} on {now.strftime("%d/%m/%Y %H:%M")}.'),
          italic=True, size=9, color=_GREY_DARK, align=WD_ALIGN_PARAGRAPH.CENTER)
    _para(doc, f'ID: {report_id}', size=9, color=_GREY_DARK, align=WD_ALIGN_PARAGRAPH.CENTER)

    # Serialise
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    word_bytes = buf.read()
    logger.info(f"✅ Relatorio Word gerado: {len(word_bytes):,} bytes")
    return word_bytes
