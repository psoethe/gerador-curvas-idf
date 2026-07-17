"""
PDF report generation for IDF Curve Generator.
Produces a professional engineering Memorial de Cálculo / Calculation Report using ReportLab.
Includes: header with logo+app name, footer with page number + report ID,
complete 6-step analysis with ALL tables, equations, parameters, and a Guide annex.
"""
import logging
import io
import datetime
import plotly.io as pio
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Table, TableStyle, Image, HRFlowable, PageBreak, KeepTogether,
    NextPageTemplate,
)
from reportlab.platypus.flowables import Flowable
from reportlab.pdfgen import canvas as rl_canvas
from calculations import DURATIONS, ISOZONA_CONSTANTS, RETURN_PERIODS
from i18n import t

logger = logging.getLogger("viktor")

# ── Brand colours ─────────────────────────────────────────────────────────────
BLUE_DARK  = colors.HexColor('#1a5276')
BLUE_MID   = colors.HexColor('#2980b9')
BLUE_LIGHT = colors.HexColor('#d6eaf8')
TEAL       = colors.HexColor('#0f766e')
TEAL_LIGHT = colors.HexColor('#ccfbf1')
AMBER      = colors.HexColor('#92400e')
AMBER_LIGHT= colors.HexColor('#fef3c7')
WHITE      = colors.white
GREY_LIGHT = colors.HexColor('#f1f5f9')
GREY_MID   = colors.HexColor('#94a3b8')
GREY_DARK  = colors.HexColor('#334155')

PAGE_W, PAGE_H = A4
MARGIN = 2.0 * cm
CONTENT_W = PAGE_W - 2 * MARGIN


# ── Figure → PNG bytes ────────────────────────────────────────────────────────
def _fig_to_png_bytes(fig, width: int = 860, height: int = 420) -> bytes | None:
    """Render a Plotly figure to PNG bytes via kaleido."""
    try:
        return pio.to_image(fig, format='png', width=width, height=height, scale=1.8)
    except Exception as exc:
        logger.warning(f"⚠️ Figura não exportada: {exc}")
        return None


def _png_flowable(png_bytes: bytes | None, max_width: float = CONTENT_W) -> list:
    """Return a list of flowables for an image (or a placeholder paragraph)."""
    if not png_bytes:
        return [Paragraph('<i>[Figura não disponível]</i>', _styles()['Normal'])]
    buf = io.BytesIO(png_bytes)
    img = Image(buf)
    # Scale to fit content width
    scale = min(max_width / img.imageWidth, 1.0)
    img.drawWidth  = img.imageWidth  * scale
    img.drawHeight = img.imageHeight * scale
    return [img]


# ── Styles ────────────────────────────────────────────────────────────────────
def _styles() -> dict:
    """Build and return a dict of named ParagraphStyles."""
    base = getSampleStyleSheet()
    s = {}

    s['Normal'] = ParagraphStyle(
        'IDF_Normal', parent=base['Normal'],
        fontSize=9, leading=13, textColor=GREY_DARK,
    )
    s['Small'] = ParagraphStyle(
        'IDF_Small', parent=base['Normal'],
        fontSize=7.5, leading=11, textColor=GREY_MID,
    )
    s['Title'] = ParagraphStyle(
        'IDF_Title', parent=base['Title'],
        fontSize=20, leading=26, textColor=WHITE,
        alignment=TA_CENTER, fontName='Helvetica-Bold',
    )
    s['Subtitle'] = ParagraphStyle(
        'IDF_Subtitle', parent=base['Normal'],
        fontSize=11, leading=15, textColor=WHITE,
        alignment=TA_CENTER, fontName='Helvetica',
    )
    s['H1'] = ParagraphStyle(
        'IDF_H1', parent=base['Heading1'],
        fontSize=13, leading=18, textColor=WHITE,
        fontName='Helvetica-Bold', spaceAfter=4,
    )
    s['H2'] = ParagraphStyle(
        'IDF_H2', parent=base['Heading2'],
        fontSize=10.5, leading=14, textColor=BLUE_DARK,
        fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=4,
    )
    s['H3'] = ParagraphStyle(
        'IDF_H3', parent=base['Heading3'],
        fontSize=9.5, leading=13, textColor=BLUE_MID,
        fontName='Helvetica-Bold', spaceBefore=6, spaceAfter=3,
    )
    s['Body'] = ParagraphStyle(
        'IDF_Body', parent=base['Normal'],
        fontSize=9, leading=13.5, textColor=GREY_DARK,
        alignment=TA_JUSTIFY, spaceAfter=4,
    )
    s['Mono'] = ParagraphStyle(
        'IDF_Mono', parent=base['Code'],
        fontSize=8.5, leading=12, textColor=BLUE_DARK,
        fontName='Courier', backColor=BLUE_LIGHT,
        borderPad=6, borderRadius=4,
    )
    s['Caption'] = ParagraphStyle(
        'IDF_Caption', parent=base['Normal'],
        fontSize=7.5, leading=10, textColor=GREY_MID,
        alignment=TA_CENTER, spaceAfter=6,
    )
    s['Footer'] = ParagraphStyle(
        'IDF_Footer', parent=base['Normal'],
        fontSize=7, leading=9, textColor=GREY_MID,
        alignment=TA_CENTER,
    )
    s['MetaKey'] = ParagraphStyle(
        'IDF_MetaKey', parent=base['Normal'],
        fontSize=8.5, leading=12, textColor=BLUE_DARK,
        fontName='Helvetica-Bold',
    )
    s['MetaVal'] = ParagraphStyle(
        'IDF_MetaVal', parent=base['Normal'],
        fontSize=8.5, leading=12, textColor=GREY_DARK,
    )
    return s


# ── Coloured section header flowable ─────────────────────────────────────────
class SectionHeader(Flowable):
    """A full-width coloured banner used as a section heading."""

    def __init__(self, text: str, bg_color=BLUE_DARK, text_color=WHITE,
                 height: float = 22, font_size: float = 11):
        super().__init__()
        self.text = text
        self.bg_color = bg_color
        self.text_color = text_color
        self._height = height
        self.font_size = font_size
        self.width = CONTENT_W

    def wrap(self, avail_w, avail_h):
        self.width = avail_w
        return avail_w, self._height + 6

    def draw(self):
        c = self.canv
        # Background rectangle
        c.setFillColor(self.bg_color)
        c.roundRect(0, 0, self.width, self._height, 4, fill=1, stroke=0)
        # Text
        c.setFillColor(self.text_color)
        c.setFont('Helvetica-Bold', self.font_size)
        c.drawString(10, (self._height - self.font_size) / 2 + 1, self.text)


# ── DataFrame → ReportLab Table ───────────────────────────────────────────────
def _df_to_rl_table(
    df: pd.DataFrame,
    col_widths: list | None = None,
    include_index: bool = False,
    header_bg=BLUE_DARK,
    alt_bg=BLUE_LIGHT,
    font_size: float = 7.5,
) -> Table:
    """Convert a pandas DataFrame to a styled ReportLab Table."""
    st = _styles()

    # Build header row
    header = []
    if include_index and df.index.name:
        header.append(Paragraph(f'<b>{df.index.name}</b>', st['Small']))
    for col in df.columns:
        header.append(Paragraph(f'<b>{col}</b>', st['Small']))

    # Build data rows
    data = [header]
    for i, (idx, row) in enumerate(df.iterrows()):
        r = []
        if include_index:
            r.append(Paragraph(str(idx), st['Small']))
        for val in row:
            if isinstance(val, float):
                r.append(Paragraph(f'{val:.3f}', st['Small']))
            else:
                r.append(Paragraph(str(val), st['Small']))
        data.append(r)

    n_cols = len(data[0])
    if col_widths is None:
        col_widths = [CONTENT_W / n_cols] * n_cols

    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ('BACKGROUND',  (0, 0), (-1, 0),  header_bg),
        ('TEXTCOLOR',   (0, 0), (-1, 0),  WHITE),
        ('FONTNAME',    (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',    (0, 0), (-1, -1), font_size),
        ('ALIGN',       (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',      (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, alt_bg]),
        ('GRID',        (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
        ('TOPPADDING',  (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',(0, 0), (-1, -1), 4),
    ]
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ── Header / Footer canvas callback ──────────────────────────────────────────
def _make_header_footer(report_id: str, app_name: str, responsavel: str,
                        localizacao: str, total_pages_placeholder: str = '??'):
    """Return an onPage callback that draws header and footer on every page."""

    def on_page(canv: rl_canvas.Canvas, doc):
        page_num = canv.getPageNumber()
        w, h = A4

        # ── HEADER ────────────────────────────────────────────────────────────
        header_h = 1.4 * cm
        # Blue bar
        canv.setFillColor(BLUE_DARK)
        canv.rect(0, h - header_h, w, header_h, fill=1, stroke=0)

        # App name (left)
        canv.setFillColor(WHITE)
        canv.setFont('Helvetica-Bold', 9)
        canv.drawString(MARGIN, h - header_h + 0.45 * cm, f'⚡ {app_name}')

        # Report ID (centre)
        canv.setFont('Helvetica', 7.5)
        canv.drawCentredString(w / 2, h - header_h + 0.45 * cm, report_id)

        # Location (right)
        canv.setFont('Helvetica', 7.5)
        canv.drawRightString(w - MARGIN, h - header_h + 0.45 * cm, localizacao[:40])

        # Thin accent line below header
        canv.setStrokeColor(BLUE_MID)
        canv.setLineWidth(1.5)
        canv.line(0, h - header_h - 1, w, h - header_h - 1)

        # ── FOOTER ────────────────────────────────────────────────────────────
        footer_y = 0.7 * cm
        canv.setStrokeColor(GREY_MID)
        canv.setLineWidth(0.5)
        canv.line(MARGIN, footer_y + 0.35 * cm, w - MARGIN, footer_y + 0.35 * cm)

        canv.setFillColor(GREY_MID)
        canv.setFont('Helvetica', 7)
        # Left: responsible
        canv.drawString(MARGIN, footer_y, responsavel[:50])
        # Centre: report ID
        canv.drawCentredString(w / 2, footer_y, report_id)
        # Right: page number
        canv.drawRightString(w - MARGIN, footer_y, f'Página {page_num}')

    return on_page


# ── Coloured info box ─────────────────────────────────────────────────────────
def _info_box(text: str, bg=BLUE_LIGHT, border=BLUE_MID, st_dict: dict = None) -> Table:
    """Return a lightly coloured info/note box as a Table flowable."""
    if st_dict is None:
        st_dict = _styles()
    data = [[Paragraph(text, st_dict['Body'])]]
    tbl = Table(data, colWidths=[CONTENT_W])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), bg),
        ('BOX',           (0, 0), (-1, -1), 0.8, border),
        ('TOPPADDING',    (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('ROUNDEDCORNERS', [4]),
    ]))
    return tbl


# ── Two-column mini-table helper ──────────────────────────────────────────────
def _kv_table(rows: list[tuple], st_dict: dict, key_w: float = 5.5 * cm) -> Table:
    """Build a two-column key-value table."""
    data = [
        [Paragraph(f'<b>{k}</b>', st_dict['MetaKey']),
         Paragraph(str(v), st_dict['MetaVal'])]
        for k, v in rows
    ]
    tbl = Table(data, colWidths=[key_w, CONTENT_W - key_w])
    tbl.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [GREY_LIGHT, WHITE]),
        ('GRID',           (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
        ('TOPPADDING',     (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 4),
        ('LEFTPADDING',    (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 8),
        ('BACKGROUND',     (0, 0), (0, -1), BLUE_LIGHT),
    ]))
    return tbl


# ── Main PDF generator ────────────────────────────────────────────────────────
def generate_pdf_report(
    results: dict,
    responsavel: str,
    localizacao: str,
    estacao: str,
    fig_historica,
    fig_gumbel,
    fig_pdf,
    fig_idf,
    lang: str = 'PT',
) -> bytes:
    """
    Generate a complete PDF Memorial de Cálculo / Calculation Report.
    Includes ALL tables, equations, parameters, figures for all 6 steps.
    Returns raw PDF bytes.
    """
    logger.info(f"📄 Gerando relatório PDF completo (lang={lang})...")

    # ── Unpack results ────────────────────────────────────────────────────────
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

    # Compute Taborga memory for full tables
    from calculations import compute_taborga_memory
    tab_mem    = compute_taborga_memory(gumbel_mem, isozona, lang)

    col_ano = t('col_ano', lang)
    y0 = year_start or int(series_df[col_ano].min())
    y1 = year_end   or int(series_df[col_ano].max())
    period_str = f'{y0} – {y1}'

    is_pt = lang == 'PT'
    now   = datetime.datetime.now()
    report_id = f'IDF-{estacao or "XXX"}-{now.strftime("%Y%m%d-%H%M")}'
    app_name  = 'IDF Curve Calculator'

    # ── Render figures to PNG ─────────────────────────────────────────────────
    logger.info("🖼️ Renderizando figuras para PNG...")
    png_hist   = _fig_to_png_bytes(fig_historica, width=860, height=380)
    png_gumbel = _fig_to_png_bytes(fig_gumbel,    width=860, height=380)
    png_pdf    = _fig_to_png_bytes(fig_pdf,        width=860, height=440)
    png_idf    = _fig_to_png_bytes(fig_idf,        width=860, height=440)
    logger.info(f"🖼️ Figuras: hist={bool(png_hist)}, gumbel={bool(png_gumbel)}, pdf={bool(png_pdf)}, idf={bool(png_idf)}")

    # ── Build PDF in memory ───────────────────────────────────────────────────
    buf = io.BytesIO()
    st  = _styles()

    on_page = _make_header_footer(report_id, app_name, responsavel, localizacao)
    frame = Frame(
        MARGIN, 1.6 * cm,
        CONTENT_W, PAGE_H - 1.6 * cm - 1.8 * cm,
        leftPadding=0, rightPadding=0,
        topPadding=4, bottomPadding=4,
        id='main',
    )
    page_tmpl = PageTemplate(id='main', frames=[frame], onPage=on_page)
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=1.8 * cm, bottomMargin=1.6 * cm,
        title=t('report_title', lang),
        author=responsavel,
    )
    doc.addPageTemplates([page_tmpl])

    story = []

    # ══════════════════════════════════════════════════════════════════════════
    # COVER PAGE
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Spacer(1, 2.5 * cm))
    cover_data = [[Paragraph(f'IDF Curve Calculator', st['Title'])]]
    cover_tbl = Table(cover_data, colWidths=[CONTENT_W])
    cover_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), BLUE_DARK),
        ('TOPPADDING',    (0, 0), (-1, -1), 22),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 22),
        ('ROUNDEDCORNERS', [8]),
    ]))
    story.append(cover_tbl)
    story.append(Spacer(1, 0.5 * cm))
    subtitle_text = 'Memorial de Cálculo — Curvas IDF' if is_pt else 'Calculation Report — IDF Curves'
    story.append(Paragraph(subtitle_text, ParagraphStyle(
        'CoverSub', parent=st['H2'],
        fontSize=14, alignment=TA_CENTER, textColor=BLUE_DARK,
    )))
    story.append(Spacer(1, 1.2 * cm))

    meta_rows = [
        (t('report_responsavel', lang),   responsavel or '—'),
        (t('report_localizacao', lang),   localizacao or '—'),
        (t('report_estacao', lang),       estacao or '—'),
        (t('report_isozona', lang),       isozona),
        (t('report_period_filter', lang), period_str),
        (t('report_n', lang),             f'{n}{t("report_n_suffix", lang)}'),
        (t('report_mu', lang),            f'{mu:.3f} mm'),
        (t('report_sigma', lang),         f'{sigma:.3f} mm'),
        ('Yn',                            f'{gumbel_mem["stats"]["yn"]:.4f}'),
        ('Sn',                            f'{gumbel_mem["stats"]["sn"]:.4f}'),
        ('ID Relatório / Report ID',      report_id),
        ('Data / Date',                   now.strftime('%d/%m/%Y %H:%M')),
    ]
    story.append(_kv_table(meta_rows, st))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # TABLE OF CONTENTS (simple text list)
    # ══════════════════════════════════════════════════════════════════════════
    story.append(SectionHeader(
        'Sumário / Table of Contents' if is_pt else 'Table of Contents',
        bg_color=GREY_DARK, height=20, font_size=10,
    ))
    story.append(Spacer(1, 0.3 * cm))
    toc_items = [
        ('Passo 1' if is_pt else 'Step 1', t('report_s2', lang)),
        ('Passo 2' if is_pt else 'Step 2', t('report_s3', lang)),
        ('Passo 3' if is_pt else 'Step 3', 'Memória de Cálculo Gumbel' if is_pt else 'Gumbel Calculation Memory'),
        ('Passo 4' if is_pt else 'Step 4', f'{t("report_s4", lang)} — Isozona {isozona}'),
        ('Passo 5' if is_pt else 'Step 5', 'Curvas PDF — Precipitação-Duração-Frequência' if is_pt else 'PDF Curves — Precipitation-Duration-Frequency'),
        ('Passo 6' if is_pt else 'Step 6', t('report_s5', lang)),
        ('Passo 7' if is_pt else 'Step 7', t('report_s6', lang)),
        ('Anexo' if is_pt else 'Annex', 'Guia de Uso do Aplicativo' if is_pt else 'Application User Guide'),
    ]
    for step_label, step_name in toc_items:
        story.append(Paragraph(
            f'<b>{step_label}</b> — {step_name}',
            ParagraphStyle('TOC', parent=st['Body'], spaceBefore=4, spaceAfter=4,
                           leftIndent=10, borderPad=0),
        ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # PASSO 1 — Série Histórica / Historical Series
    # ══════════════════════════════════════════════════════════════════════════
    story.append(SectionHeader(
        f'{"Passo 1" if is_pt else "Step 1"} — {t("report_s2", lang)}',
        bg_color=BLUE_DARK,
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(t('report_s2_desc', lang), st['Body']))
    story.append(Spacer(1, 0.2 * cm))

    # Key stats for this step
    story.append(_kv_table([
        ('N (amostras / samples)', str(n)),
        ('Período / Period', period_str),
        ('μ (média / mean)', f'{mu:.3f} mm'),
        ('σ (desvio padrão / std dev)', f'{sigma:.3f} mm'),
        ('Mín / Min', f'{series_df[t("col_precip", lang)].min():.1f} mm'),
        ('Máx / Max', f'{series_df[t("col_precip", lang)].max():.1f} mm'),
    ], st, key_w=6 * cm))
    story.append(Spacer(1, 0.3 * cm))

    story.extend(_png_flowable(png_hist))
    story.append(Paragraph(
        'Figura 1 — Série histórica de precipitação máxima diária anual' if is_pt
        else 'Figure 1 — Annual maximum daily precipitation historical series',
        st['Caption'],
    ))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph(t('tbl1_title', lang), st['H3']))
    story.append(_df_to_rl_table(series_df.reset_index(drop=True)))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # PASSO 2 — Análise de Gumbel / Gumbel Analysis
    # ══════════════════════════════════════════════════════════════════════════
    story.append(SectionHeader(
        f'{"Passo 2" if is_pt else "Step 2"} — {t("report_s3", lang)}',
        bg_color=BLUE_MID,
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(t('report_s3_desc', lang), st['Body']))
    story.append(Spacer(1, 0.2 * cm))

    # ── Equations block — Passo 2 (visual math format) ───────────────────────
    story.append(SectionHeader('Equações / Equations', bg_color=GREY_DARK, height=18, font_size=9))
    story.append(Spacer(1, 0.2 * cm))

    eq_math_style = ParagraphStyle(
        'EqMath2', parent=st['Normal'],
        fontName='Helvetica', fontSize=10.5,
        textColor=BLUE_DARK, alignment=TA_CENTER,
    )
    eq_lhs2 = ParagraphStyle(
        'EqLhs2', parent=st['Normal'],
        fontName='Helvetica-Bold', fontSize=10.5,
        textColor=BLUE_DARK, alignment=TA_RIGHT,
    )
    eq_note2 = ParagraphStyle(
        'EqNote2', parent=st['Normal'],
        fontName='Helvetica-Oblique', fontSize=8,
        textColor=GREY_MID, alignment=TA_LEFT,
    )

    def _simple_eq_row(lhs_text, rhs_text, note_text=''):
        """Single-line equation rendered as a styled table row."""
        cells = [
            Paragraph(lhs_text, eq_lhs2),
            Paragraph(rhs_text, eq_math_style),
        ]
        col_ws = [4.5 * cm, CONTENT_W - 4.5 * cm]
        if note_text:
            cells = [
                Paragraph(lhs_text, eq_lhs2),
                Paragraph(rhs_text, eq_math_style),
                Paragraph(note_text, eq_note2),
            ]
            col_ws = [4.5 * cm, 7 * cm, CONTENT_W - 4.5 * cm - 7 * cm]
        tbl = Table([cells], colWidths=col_ws)
        tbl.setStyle(TableStyle([
            ('ALIGN',         (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
            ('BACKGROUND',    (0, 0), (-1, -1), GREY_LIGHT),
            ('BOX',           (0, 0), (-1, -1), 0.5, GREY_MID),
        ]))
        return tbl

    # ── Eq 1: Y(TR) — reduced variate (fraction form) ─────────────────────────
    _frac_inner_y = Table(
        [[Paragraph('−ln(−ln(1 − 1/TR))', eq_math_style)]],
        colWidths=[8 * cm],
    )
    _frac_inner_y.setStyle(TableStyle([
        ('ALIGN',  (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(_simple_eq_row(
        'Y(TR)  =',
        '−ln(−ln(1 − 1/TR))',
        'variável reduzida de Gumbel / Gumbel reduced variate',
    ))
    story.append(Spacer(1, 0.12 * cm))

    # ── Eq 2: Kt ──────────────────────────────────────────────────────────────
    _frac_kt = Table(
        [[Paragraph('Y − Yn', eq_math_style)],
         [Paragraph('Sn', eq_math_style)]],
        colWidths=[5 * cm],
    )
    _frac_kt.setStyle(TableStyle([
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW',     (0, 0), (0, 0),   0.8, GREY_DARK),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    _kt_outer = Table(
        [[Paragraph('Kt  =', eq_lhs2), _frac_kt,
          Paragraph('fator de frequência / frequency factor', eq_note2)]],
        colWidths=[4.5 * cm, 5.5 * cm, CONTENT_W - 10 * cm],
    )
    _kt_outer.setStyle(TableStyle([
        ('ALIGN',         (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('BACKGROUND',    (0, 0), (-1, -1), GREY_LIGHT),
        ('BOX',           (0, 0), (-1, -1), 0.5, GREY_MID),
    ]))
    story.append(_kt_outer)
    story.append(Spacer(1, 0.12 * cm))

    # ── Eq 3: Pt ──────────────────────────────────────────────────────────────
    story.append(_simple_eq_row(
        'Pt  =',
        'μ  +  σ · Kt',
        'precipitação de projeto / design precipitation [mm]',
    ))
    story.append(Spacer(1, 0.12 * cm))

    # ── Eq 4: P24h ────────────────────────────────────────────────────────────
    story.append(_simple_eq_row(
        'P24h  =',
        'Pt  ×  1,158',
        'fator de correção chuva pontual / point rainfall correction factor',
    ))
    story.append(Spacer(1, 0.25 * cm))

    # Parameters
    mem_stats = gumbel_mem['stats']
    story.append(_kv_table([
        ('N', str(mem_stats['n'])),
        ('μ = Pn (média / mean)', f'{mem_stats["pn"]:.3f} mm'),
        ('σn (desvio padrão / std dev)', f'{mem_stats["sigma"]:.3f} mm'),
        ('Yn (reduzida média / reduced mean)', f'{mem_stats["yn"]:.4f}'),
        ('Sn (reduzida desvio / reduced std)', f'{mem_stats["sn"]:.4f}'),
        ('ΣP', f'{mem_stats["sum_p"]:.2f} mm'),
        ('Σ(P−Pn)²', f'{mem_stats["sum_ppn2"]:.2f}'),
    ], st, key_w=7 * cm))
    story.append(Spacer(1, 0.3 * cm))

    story.extend(_png_flowable(png_gumbel))
    story.append(Paragraph(
        'Figura 2 — Precipitação de projeto Pt por período de retorno TR' if is_pt
        else 'Figure 2 — Design precipitation Pt by return period TR',
        st['Caption'],
    ))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph(t('tbl2_title', lang), st['H3']))
    story.append(_df_to_rl_table(gumbel_df))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # PASSO 3 — Memória de Cálculo Gumbel (tabela ordenada completa)
    # ══════════════════════════════════════════════════════════════════════════
    story.append(SectionHeader(
        f'{"Passo 3" if is_pt else "Step 3"} — {"Memória de Cálculo Gumbel" if is_pt else "Gumbel Calculation Memory"}',
        bg_color=GREY_DARK,
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        'Tabela ordenada (decrescente) com todos os parâmetros do método de Ven Te Chow.'
        if is_pt else
        'Ordered table (descending) with all parameters of the Ven Te Chow method.',
        st['Body'],
    ))
    story.append(Spacer(1, 0.2 * cm))

    # Stats summary row
    stats_hdr = [
        Paragraph('<b>N</b>', st['Small']),
        Paragraph('<b>Pn (mm)</b>', st['Small']),
        Paragraph('<b>σn (mm)</b>', st['Small']),
        Paragraph('<b>ΣP</b>', st['Small']),
        Paragraph('<b>Σ(P−Pn)²</b>', st['Small']),
        Paragraph('<b>Yn</b>', st['Small']),
        Paragraph('<b>Sn</b>', st['Small']),
        Paragraph('<b>ΣY</b>', st['Small']),
        Paragraph('<b>Σ(Y−Yn)²</b>', st['Small']),
    ]
    stats_vals = [
        Paragraph(str(mem_stats['n']), st['Small']),
        Paragraph(f'{mem_stats["pn"]:.2f}', st['Small']),
        Paragraph(f'{mem_stats["sigma"]:.2f}', st['Small']),
        Paragraph(f'{mem_stats["sum_p"]:.2f}', st['Small']),
        Paragraph(f'{mem_stats["sum_ppn2"]:.2f}', st['Small']),
        Paragraph(f'{mem_stats["yn"]:.4f}', st['Small']),
        Paragraph(f'{mem_stats["sn"]:.4f}', st['Small']),
        Paragraph(f'{mem_stats["sum_y"]:.4f}', st['Small']),
        Paragraph(f'{mem_stats["sum_yyn2"]:.4f}', st['Small']),
    ]
    n_stat_cols = len(stats_hdr)
    stats_tbl = Table([stats_hdr, stats_vals], colWidths=[CONTENT_W / n_stat_cols] * n_stat_cols)
    stats_tbl.setStyle(TableStyle([
        ('BACKGROUND',   (0, 0), (-1, 0), BLUE_DARK),
        ('TEXTCOLOR',    (0, 0), (-1, 0), WHITE),
        ('BACKGROUND',   (0, 1), (-1, 1), BLUE_LIGHT),
        ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
        ('GRID',         (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
        ('FONTSIZE',     (0, 0), (-1, -1), 7.5),
        ('TOPPADDING',   (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
    ]))
    story.append(stats_tbl)
    story.append(Spacer(1, 0.4 * cm))

    # Full ordered table
    story.append(Paragraph(
        'Tabela Ordenada — Método de Ven Te Chow' if is_pt else 'Ordered Table — Ven Te Chow Method',
        st['H3'],
    ))
    mem_rows = gumbel_mem['rows']
    ordered_df = pd.DataFrame([{
        'Data' if is_pt else 'Date': r['date'],
        'P orig (mm)': r['p_orig'],
        'm': r['m'],
        'P desc (mm)': r['p_desc'],
        'P−Pn': r['ppn'],
        '(P−Pn)²': r['ppn2'],
        'Pr (%)': r['pr'],
        'TR emp': r['tr_emp'],
        'Y': r['y'],
        'Y−Yn': r['yyn'],
        '(Y−Yn)²': r['yyn2'],
    } for r in mem_rows])
    # Use smaller font for this wide table
    story.append(_df_to_rl_table(ordered_df, font_size=6.5))
    story.append(Spacer(1, 0.4 * cm))

    # Ven Te Chow results per TR
    story.append(Paragraph(
        'Ven Te Chow — Resultados por TR' if is_pt else 'Ven Te Chow — Results by TR',
        st['H3'],
    ))
    chow_df = pd.DataFrame(gumbel_mem['chow_rows'])
    chow_df.columns = ['TR', 'Yt', 'Pn (mm)', 'σn (mm)', 'Kt', 'Pt (mm)', 'P24h (mm)']
    story.append(_df_to_rl_table(chow_df))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # PASSO 4 — Isozonas Taborga / Taborga Isozone Disaggregation
    # ══════════════════════════════════════════════════════════════════════════
    story.append(SectionHeader(
        f'{"Passo 4" if is_pt else "Step 4"} — {t("report_s4", lang)} — Isozona {isozona}',
        bg_color=TEAL,
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        f'Desagregação da precipitação diária para sub-diária usando o método das Isozonas de Taborga. '
        f'Isozona selecionada: <b>{isozona}</b>. Fator de correção: Ap = Pt × 1,202.'
        if is_pt else
        f'Disaggregation of daily precipitation to sub-daily using the Taborga Isozone method. '
        f'Selected isozone: <b>{isozona}</b>. Correction factor: Ap = Pt × 1.202.',
        st['Body'],
    ))
    story.append(Spacer(1, 0.2 * cm))

    # Equations — Passo 4 (visual math format)
    story.append(SectionHeader('Equações / Equations', bg_color=GREY_DARK, height=18, font_size=9))
    story.append(Spacer(1, 0.15 * cm))

    # Reuse the same helper styles defined in Passo 2 scope — redefine locally
    _eq_s = ParagraphStyle('EqS4', parent=st['Normal'],
                           fontName='Helvetica', fontSize=10.5,
                           textColor=BLUE_DARK, alignment=TA_CENTER)
    _lhs_s = ParagraphStyle('LhsS4', parent=st['Normal'],
                            fontName='Helvetica-Bold', fontSize=10.5,
                            textColor=BLUE_DARK, alignment=TA_RIGHT)
    _note_s = ParagraphStyle('NoteS4', parent=st['Normal'],
                             fontName='Helvetica-Oblique', fontSize=8,
                             textColor=GREY_MID, alignment=TA_LEFT)

    def _eq_row4(lhs, rhs, note=''):
        cells = [Paragraph(lhs, _lhs_s), Paragraph(rhs, _eq_s)]
        cws   = [4.5 * cm, 8 * cm]
        if note:
            cells.append(Paragraph(note, _note_s))
            cws.append(CONTENT_W - 12.5 * cm)
        t4 = Table([cells], colWidths=cws)
        t4.setStyle(TableStyle([
            ('ALIGN',  (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
            ('BACKGROUND',    (0, 0), (-1, -1), GREY_LIGHT),
            ('BOX',           (0, 0), (-1, -1), 0.5, GREY_MID),
        ]))
        return t4

    def _frac_row4(lhs, num, den, note=''):
        """Fraction-style equation row for Passo 4."""
        frac = Table([[Paragraph(num, _eq_s)], [Paragraph(den, _eq_s)]],
                     colWidths=[7 * cm])
        frac.setStyle(TableStyle([
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('LINEBELOW',     (0, 0), (0, 0),   0.8, GREY_DARK),
            ('TOPPADDING',    (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        cells = [Paragraph(lhs, _lhs_s), frac]
        cws   = [4.5 * cm, 7.5 * cm]
        if note:
            cells.append(Paragraph(note, _note_s))
            cws.append(CONTENT_W - 12 * cm)
        outer = Table([cells], colWidths=cws)
        outer.setStyle(TableStyle([
            ('ALIGN',  (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
            ('BACKGROUND',    (0, 0), (-1, -1), GREY_LIGHT),
            ('BOX',           (0, 0), (-1, -1), 0.5, GREY_MID),
        ]))
        return outer

    # Eq 1: Ap
    story.append(_eq_row4(
        'Ap  =', 'Pt  ×  1,202',
        'altura de precipitacao de 24h / 24h precipitation height [mm]',
    ))
    story.append(Spacer(1, 0.1 * cm))

    # Eq 2: P(6min)
    story.append(_frac_row4(
        'P(6min)  =',
        'Ap  ×  rel6min',
        '100',
        'precipitacao em 6 minutos / 6-minute precipitation [mm]',
    ))
    story.append(Spacer(1, 0.1 * cm))

    # Eq 3: P(60min)
    story.append(_frac_row4(
        'P(60min)  =',
        'Ap  ×  rel1h',
        '100',
        'precipitacao em 60 minutos / 60-minute precipitation [mm]',
    ))
    story.append(Spacer(1, 0.1 * cm))

    # Eq 4: P(t) short interval — fraction with ln
    story.append(_eq_row4(
        'P(t)  =',
        'P6  +  K1 · ln(t / 6)',
        '6 min <= t <= 60 min',
    ))
    story.append(Spacer(1, 0.1 * cm))

    # Eq 5: P(t) long interval
    story.append(_eq_row4(
        'P(t)  =',
        'P60  +  K2 · ln(t / 60)',
        '60 min < t <= 1440 min',
    ))
    story.append(Spacer(1, 0.1 * cm))

    # Eq 6: K1 — fraction form
    story.append(_frac_row4(
        'K1  =',
        'P(60min)  −  P(6min)',
        'ln(60 / 6)',
        'coeficiente de interpolacao logaritmica / log interpolation coefficient',
    ))
    story.append(Spacer(1, 0.1 * cm))

    # Eq 7: K2 — fraction form
    story.append(_frac_row4(
        'K2  =',
        'P(1440min)  −  P(60min)',
        'ln(1440 / 60)',
        'coeficiente de interpolacao logaritmica / log interpolation coefficient',
    ))
    story.append(Spacer(1, 0.2 * cm))

    # ── Sub-table 4a: Isozone constants for ALL zones ─────────────────────────
    story.append(Paragraph(
        'Tabela de Constantes das Isozonas (rel1h %)' if is_pt else 'Isozone Constants Table (rel1h %)',
        st['H3'],
    ))
    all_zones = list(ISOZONA_CONSTANTS.keys())
    all_trs   = sorted({tr for z in all_zones for tr in ISOZONA_CONSTANTS[z]['rel1h'].keys()})
    iz_hdr = [Paragraph('<b>TR</b>', st['Small'])] + [
        Paragraph(f'<b>{z}</b>', st['Small']) for z in all_zones
    ]
    iz_rows_data = [iz_hdr]
    for tr_c in all_trs:
        row = [Paragraph(str(tr_c), st['Small'])]
        for z in all_zones:
            val = ISOZONA_CONSTANTS[z]['rel1h'].get(tr_c, '—')
            cell_style = st['Small']
            row.append(Paragraph(
                f'<b>{val}</b>' if z == isozona else str(val),
                cell_style,
            ))
        iz_rows_data.append(row)
    n_iz_cols = len(iz_hdr)
    iz_col_w = CONTENT_W / n_iz_cols
    iz_tbl = Table(iz_rows_data, colWidths=[iz_col_w] * n_iz_cols, repeatRows=1)
    iz_style = [
        ('BACKGROUND',  (0, 0), (-1, 0), TEAL),
        ('TEXTCOLOR',   (0, 0), (-1, 0), WHITE),
        ('ALIGN',       (0, 0), (-1, -1), 'CENTER'),
        ('GRID',        (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
        ('FONTSIZE',    (0, 0), (-1, -1), 7.5),
        ('TOPPADDING',  (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, TEAL_LIGHT]),
    ]
    # Highlight active isozone column
    active_col_idx = all_zones.index(isozona) + 1
    iz_style.append(('BACKGROUND', (active_col_idx, 0), (active_col_idx, -1), TEAL))
    iz_style.append(('TEXTCOLOR',  (active_col_idx, 1), (active_col_idx, -1), TEAL))
    iz_style.append(('FONTNAME',   (active_col_idx, 1), (active_col_idx, -1), 'Helvetica-Bold'))
    iz_tbl.setStyle(TableStyle(iz_style))
    story.append(iz_tbl)
    story.append(Spacer(1, 0.3 * cm))

    # rel6min constants
    story.append(Paragraph(
        'Constantes rel6min por Isozona' if is_pt else 'rel6min Constants by Isozone',
        st['H3'],
    ))
    rel6_hdr = [Paragraph('<b>Isozona</b>', st['Small']),
                Paragraph('<b>rel6min TR 5–50 (%)</b>', st['Small']),
                Paragraph('<b>rel6min TR 100 (%)</b>', st['Small'])]
    rel6_rows = [rel6_hdr]
    for z in all_zones:
        rel6_rows.append([
            Paragraph(f'<b>{z}</b>' if z == isozona else z, st['Small']),
            Paragraph(str(ISOZONA_CONSTANTS[z]['rel6min']['05/50']), st['Small']),
            Paragraph(str(ISOZONA_CONSTANTS[z]['rel6min']['100']), st['Small']),
        ])
    rel6_tbl = Table(rel6_rows, colWidths=[CONTENT_W / 3] * 3, repeatRows=1)
    rel6_tbl.setStyle(TableStyle([
        ('BACKGROUND',  (0, 0), (-1, 0), TEAL),
        ('TEXTCOLOR',   (0, 0), (-1, 0), WHITE),
        ('ALIGN',       (0, 0), (-1, -1), 'CENTER'),
        ('GRID',        (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
        ('FONTSIZE',    (0, 0), (-1, -1), 8),
        ('TOPPADDING',  (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, TEAL_LIGHT]),
    ]))
    story.append(rel6_tbl)
    story.append(Spacer(1, 0.3 * cm))

    # ── Sub-table 4b: Base data (Pt, Ap per TR) ───────────────────────────────
    story.append(Paragraph(
        'Tabela 4a — Dados Base: Pt, σ\'n, Ap por TR' if is_pt else 'Table 4a — Base Data: Pt, σ\'n, Ap by TR',
        st['H3'],
    ))
    base_df = pd.DataFrame(tab_mem['base_rows'])
    base_df.columns = ['TR', 'Pt (mm)', "σ'n", 'Ap = Pt×1.202 (mm)']
    story.append(_df_to_rl_table(base_df, header_bg=TEAL))
    story.append(Spacer(1, 0.3 * cm))

    # ── Sub-table 4c: Relations (rel1h, rel6min per TR) ───────────────────────
    story.append(Paragraph(
        'Tabela 4b — Relações Taborga: rel1h (a) e rel6min (b) por TR' if is_pt
        else 'Table 4b — Taborga Ratios: rel1h (a) and rel6min (b) by TR',
        st['H3'],
    ))
    rel_df = pd.DataFrame(tab_mem['rel_rows'])
    rel_df.columns = ['TR', 'rel1h (a)', 'rel6min (b)']
    story.append(_df_to_rl_table(rel_df, header_bg=TEAL))
    story.append(Spacer(1, 0.3 * cm))

    # ── Sub-table 4d: Heights (P1h, P6min per TR) ────────────────────────────
    story.append(Paragraph(
        'Tabela 4c — Alturas de Precipitação: P(60min) e P(6min) por TR' if is_pt
        else 'Table 4c — Precipitation Heights: P(60min) and P(6min) by TR',
        st['H3'],
    ))
    height_df = pd.DataFrame(tab_mem['height_rows'])
    height_df.columns = ['TR', 'P(60min) mm', 'P(6min) mm']
    story.append(_df_to_rl_table(height_df, header_bg=TEAL))
    story.append(Spacer(1, 0.3 * cm))

    # ── Sub-table 4e: Summary (P6min, P1h, P24h per TR) ──────────────────────
    story.append(Paragraph(
        'Tabela 4d — Resumo Gumbel: P(6min), P(1h), P(24h) por TR' if is_pt
        else 'Table 4d — Gumbel Summary: P(6min), P(1h), P(24h) by TR',
        st['H3'],
    ))
    summary_df = pd.DataFrame(tab_mem['summary_rows'])
    summary_df.columns = ['TR', 'P(6min) mm', 'P(60min) mm', 'P(1440min) mm']
    story.append(_df_to_rl_table(summary_df, header_bg=TEAL))
    story.append(Spacer(1, 0.3 * cm))

    # ── Sub-table 4f: K1/K2 coefficients ─────────────────────────────────────
    story.append(Paragraph(
        'Tabela 4e — Coeficientes K1 e K2 de Interpolacao Logaritmica por TR' if is_pt
        else 'Table 4e — Logarithmic Interpolation Coefficients K1 and K2 by TR',
        st['H3'],
    ))
    k_df = pd.DataFrame(tab_mem['k_rows'])
    k_df.columns = ['TR', 'P(6min) mm', 'P(60min) mm', 'P(1440min) mm', 'K1', 'K2']
    story.append(_df_to_rl_table(k_df, header_bg=TEAL))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # PASSO 5 — Curvas PDF / PDF Curves
    # ══════════════════════════════════════════════════════════════════════════
    story.append(SectionHeader(
        f'{"Passo 5" if is_pt else "Step 5"} — '
        f'{"Curvas PDF — Precipitação-Duração-Frequência" if is_pt else "PDF Curves — Precipitation-Duration-Frequency"}',
        bg_color=colors.HexColor('#0369a1'),
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        'Precipitação acumulada P(t) por duração e período de retorno, calculada via '
        'desagregação de Taborga. Todas as 8 TRs (2, 5, 10, 15, 20, 25, 50 e 100 anos).'
        if is_pt else
        'Accumulated precipitation P(t) by duration and return period, calculated via '
        'Taborga disaggregation. All 8 TRs (2, 5, 10, 15, 20, 25, 50 and 100 years).',
        st['Body'],
    ))
    story.append(Spacer(1, 0.2 * cm))

    # Equations — Passo 5 (visual math format)
    story.append(SectionHeader('Equações / Equations', bg_color=GREY_DARK, height=18, font_size=9))
    story.append(Spacer(1, 0.15 * cm))

    _eq_s5 = ParagraphStyle('EqS5', parent=st['Normal'],
                            fontName='Helvetica', fontSize=10.5,
                            textColor=BLUE_DARK, alignment=TA_CENTER)
    _lhs_s5 = ParagraphStyle('LhsS5', parent=st['Normal'],
                             fontName='Helvetica-Bold', fontSize=10.5,
                             textColor=BLUE_DARK, alignment=TA_RIGHT)
    _note_s5 = ParagraphStyle('NoteS5', parent=st['Normal'],
                              fontName='Helvetica-Oblique', fontSize=8,
                              textColor=GREY_MID, alignment=TA_LEFT)

    def _eq_row5(lhs, rhs, note=''):
        cells = [Paragraph(lhs, _lhs_s5), Paragraph(rhs, _eq_s5)]
        cws   = [4.5 * cm, 8 * cm]
        if note:
            cells.append(Paragraph(note, _note_s5))
            cws.append(CONTENT_W - 12.5 * cm)
        t5 = Table([cells], colWidths=cws)
        t5.setStyle(TableStyle([
            ('ALIGN',  (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
            ('BACKGROUND',    (0, 0), (-1, -1), GREY_LIGHT),
            ('BOX',           (0, 0), (-1, -1), 0.5, GREY_MID),
        ]))
        return t5

    def _frac_row5(lhs, num, den, note=''):
        frac = Table([[Paragraph(num, _eq_s5)], [Paragraph(den, _eq_s5)]],
                     colWidths=[7 * cm])
        frac.setStyle(TableStyle([
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('LINEBELOW',     (0, 0), (0, 0),   0.8, GREY_DARK),
            ('TOPPADDING',    (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        cells = [Paragraph(lhs, _lhs_s5), frac]
        cws   = [4.5 * cm, 7.5 * cm]
        if note:
            cells.append(Paragraph(note, _note_s5))
            cws.append(CONTENT_W - 12 * cm)
        outer = Table([cells], colWidths=cws)
        outer.setStyle(TableStyle([
            ('ALIGN',  (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
            ('BACKGROUND',    (0, 0), (-1, -1), GREY_LIGHT),
            ('BOX',           (0, 0), (-1, -1), 0.5, GREY_MID),
        ]))
        return outer

    # Eq 1: P(t) short
    story.append(_eq_row5(
        'P(t)  =',
        'P6  +  K1 · ln(t / 6)',
        '6 min <= t <= 60 min',
    ))
    story.append(Spacer(1, 0.1 * cm))

    # Eq 2: P(t) long
    story.append(_eq_row5(
        'P(t)  =',
        'P60  +  K2 · ln(t / 60)',
        '60 min < t <= 1440 min',
    ))
    story.append(Spacer(1, 0.1 * cm))

    # Eq 3: i(t) — fraction form
    story.append(_frac_row5(
        'i(t)  =',
        'P(t)',
        't / 60',
        'intensidade de precipitacao / rainfall intensity [mm/h]',
    ))
    story.append(Spacer(1, 0.25 * cm))

    # Figure
    story.extend(_png_flowable(png_pdf))
    story.append(Paragraph(
        'Figura 3 — Curvas PDF: Precipitação acumulada P(t) por duração e TR' if is_pt
        else 'Figure 3 — PDF Curves: Accumulated precipitation P(t) by duration and TR',
        st['Caption'],
    ))
    story.append(Spacer(1, 0.4 * cm))

    # Full P(t) disaggregation matrix
    story.append(Paragraph(
        'Tabela 5a — Matriz de Desagregação P(t) [mm] — todas as durações × TRs' if is_pt
        else 'Table 5a — Disaggregation Matrix P(t) [mm] — all durations × TRs',
        st['H3'],
    ))
    disagg_display = disagg_df.copy()
    disagg_display.index.name = t('col_duracao', lang)
    story.append(_df_to_rl_table(
        disagg_display.reset_index(),
        include_index=False,
        header_bg=colors.HexColor('#0369a1'),
        font_size=7.0,
    ))
    story.append(Spacer(1, 0.3 * cm))

    # K1/K2 table in this section too
    story.append(Paragraph(
        'Tabela 5b — Coeficientes K1 e K2 por TR' if is_pt else 'Table 5b — K1 and K2 Coefficients by TR',
        st['H3'],
    ))
    story.append(_df_to_rl_table(k_df, header_bg=colors.HexColor('#0369a1')))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # PASSO 6 — Curvas IDF / IDF Curves
    # ══════════════════════════════════════════════════════════════════════════
    story.append(SectionHeader(
        f'{"Passo 6" if is_pt else "Step 6"} — {t("report_s5", lang)}',
        bg_color=colors.HexColor('#3730a3'),
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(t('report_s5_desc', lang), st['Body']))
    story.append(Spacer(1, 0.2 * cm))

    # IDF conversion equation — visual fraction form
    _eq_s6 = ParagraphStyle('EqS6', parent=st['Normal'],
                            fontName='Helvetica', fontSize=11,
                            textColor=BLUE_DARK, alignment=TA_CENTER)
    _lhs_s6 = ParagraphStyle('LhsS6', parent=st['Normal'],
                             fontName='Helvetica-Bold', fontSize=11,
                             textColor=BLUE_DARK, alignment=TA_RIGHT)
    _note_s6 = ParagraphStyle('NoteS6', parent=st['Normal'],
                              fontName='Helvetica-Oblique', fontSize=8.5,
                              textColor=GREY_MID, alignment=TA_LEFT)
    _frac6 = Table(
        [[Paragraph('P(t, TR)', _eq_s6)],
         [Paragraph('t / 60', _eq_s6)]],
        colWidths=[6 * cm],
    )
    _frac6.setStyle(TableStyle([
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW',     (0, 0), (0, 0),   0.8, GREY_DARK),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    _idf_eq = Table(
        [[Paragraph('i(t, TR)  =', _lhs_s6),
          _frac6,
          Paragraph('intensidade de precipitacao / rainfall intensity [mm/h]', _note_s6)]],
        colWidths=[4.5 * cm, 6.5 * cm, CONTENT_W - 11 * cm],
    )
    _idf_eq.setStyle(TableStyle([
        ('ALIGN',  (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('BACKGROUND',    (0, 0), (-1, -1), GREY_LIGHT),
        ('BOX',           (0, 0), (-1, -1), 0.5, GREY_MID),
    ]))
    story.append(_idf_eq)
    story.append(Spacer(1, 0.3 * cm))

    story.extend(_png_flowable(png_idf))
    story.append(Paragraph(
        'Figura 4 — Curvas IDF: Intensidade (mm/h) por duração e TR' if is_pt
        else 'Figure 4 — IDF Curves: Intensity (mm/h) by duration and TR',
        st['Caption'],
    ))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph(
        'Tabela 6a — Intensidades IDF (mm/h) — todas as durações × TRs' if is_pt
        else 'Table 6a — IDF Intensities (mm/h) — all durations × TRs',
        st['H3'],
    ))
    idf_display = idf_df.copy()
    idf_display.index.name = t('col_duracao', lang)
    story.append(_df_to_rl_table(
        idf_display.reset_index(),
        include_index=False,
        header_bg=colors.HexColor('#3730a3'),
        font_size=7.0,
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # PASSO 7 — Equação de Sherman / Sherman Equation
    # ══════════════════════════════════════════════════════════════════════════
    story.append(SectionHeader(
        f'{"Passo 7" if is_pt else "Step 7"} — {t("report_s6", lang)}',
        bg_color=colors.HexColor('#0c4a6e'),
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(t('report_s6_desc', lang), st['Body']))
    story.append(Spacer(1, 0.2 * cm))

    # Equations
    story.append(SectionHeader('Equações / Equations', bg_color=GREY_DARK, height=18, font_size=9))
    story.append(Spacer(1, 0.2 * cm))

    # ── Helper: build a visual fraction table ─────────────────────────────────
    def _eq_fraction(numerator_para, denominator_para, lhs_para, rhs_label_para=None):
        """
        Renders:   lhs = ──────────────  [rhs_label]
                         denominator
        as a ReportLab Table so it looks like a real fraction.
        """
        frac_inner = Table(
            [[numerator_para], [denominator_para]],
            colWidths=[9 * cm],
        )
        frac_inner.setStyle(TableStyle([
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('LINEBELOW',     (0, 0), (0, 0),   1.2, BLUE_DARK),   # fraction bar
            ('TOPPADDING',    (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ]))

        cells = [lhs_para, frac_inner]
        col_ws = [3.5 * cm, 9.5 * cm]
        if rhs_label_para:
            cells.append(rhs_label_para)
            col_ws.append(CONTENT_W - 3.5 * cm - 9.5 * cm)

        outer = Table([cells], colWidths=col_ws)
        outer.setStyle(TableStyle([
            ('ALIGN',         (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING',   (0, 0), (-1, -1), 12),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 12),
            ('BACKGROUND',    (0, 0), (-1, -1), BLUE_LIGHT),
            ('BOX',           (0, 0), (-1, -1), 1.0, BLUE_MID),
            ('ROUNDEDCORNERS', [6]),
        ]))
        return outer

    # Equation paragraph styles — larger, bolder, matching the reference image
    eq_style = ParagraphStyle(
        'EqBody', parent=st['Normal'],
        fontName='Helvetica-Bold', fontSize=13,
        textColor=BLUE_DARK, alignment=TA_CENTER,
    )
    eq_lhs_style = ParagraphStyle(
        'EqLhs', parent=st['Normal'],
        fontName='Helvetica-Bold', fontSize=13,
        textColor=BLUE_DARK, alignment=TA_RIGHT,
    )
    eq_label_style = ParagraphStyle(
        'EqLabel', parent=st['Normal'],
        fontName='Helvetica-Oblique', fontSize=8,
        textColor=GREY_MID, alignment=TA_LEFT,
    )

    # ── Generic form ──────────────────────────────────────────────────────────
    story.append(Paragraph(
        '<b>Forma Geral / General Form</b>' if is_pt else '<b>General Form</b>',
        st['H3'],
    ))
    story.append(Spacer(1, 0.15 * cm))
    story.append(_eq_fraction(
        numerator_para   = Paragraph('A &middot; TR <super>B</super>', eq_style),
        denominator_para = Paragraph('(t + C) <super>D</super>', eq_style),
        lhs_para         = Paragraph('<i>i</i> =', eq_lhs_style),
        rhs_label_para   = Paragraph('Equação de Montana', eq_label_style),
    ))
    story.append(Spacer(1, 0.4 * cm))

    # ── Fitted form with actual values ────────────────────────────────────────
    A_v = sherman['A'];  B_v = sherman['B']
    C_v = sherman['C'];  D_v = sherman['D']
    r2_v  = sherman['R²']
    rmse_v = sherman['RMSE']
    nse_v  = sherman['NSE']

    # Format sign of C so it reads "(t + 3.12)" or "(t − 1.05)"
    c_sign = '+' if C_v >= 0 else '−'
    c_abs  = abs(C_v)
    r2_pct = f'{r2_v * 100:.2f}%'

    story.append(Paragraph(
        '<b>Equação Ajustada / Fitted Equation</b>' if is_pt else '<b>Fitted Equation</b>',
        st['H3'],
    ))
    story.append(Spacer(1, 0.15 * cm))
    story.append(_eq_fraction(
        numerator_para   = Paragraph(
            f'{A_v:.4f} &middot; TR <super>{B_v:.4f}</super>', eq_style),
        denominator_para = Paragraph(
            f'(t {c_sign} {c_abs:.4f}) <super>{D_v:.4f}</super>', eq_style),
        lhs_para         = Paragraph('<i>i</i> =', eq_lhs_style),
    ))
    story.append(Spacer(1, 0.3 * cm))

    # ── Parameter grid (2×2) — matching the reference image ──────────────────
    param_label_style = ParagraphStyle(
        'ParamLbl', parent=st['Normal'],
        fontName='Helvetica', fontSize=7,
        textColor=GREY_MID, alignment=TA_LEFT,
        spaceAfter=1,
    )
    param_value_style = ParagraphStyle(
        'ParamVal', parent=st['Normal'],
        fontName='Helvetica-Bold', fontSize=11,
        textColor=BLUE_DARK, alignment=TA_LEFT,
    )

    def _param_cell(label, value_str):
        """Build a single parameter cell with label above value."""
        cell_data = [[
            Paragraph(label, param_label_style),
        ], [
            Paragraph(f'<b>{value_str}</b>', param_value_style),
        ]]
        cell_tbl = Table(cell_data, colWidths=[(CONTENT_W - 1.2 * cm) / 2])
        cell_tbl.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), colors.white),
            ('BOX',           (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING',    (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING',   (0, 0), (-1, -1), 10),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
            ('ROUNDEDCORNERS', [4]),
        ]))
        return cell_tbl

    lbl_a = 'A (CONSTANTE)' if is_pt else 'A (CONSTANT)'
    lbl_b = 'B (EXPOENTE TR)' if is_pt else 'B (TR EXPONENT)'
    lbl_c = 'C (AJUSTE TEMPO)' if is_pt else 'C (TIME ADJUST)'
    lbl_d = 'D (EXPOENTE TEMPO)' if is_pt else 'D (TIME EXPONENT)'

    param_grid = Table(
        [
            [_param_cell(lbl_a, f'{A_v:.4f}'), _param_cell(lbl_b, f'{B_v:.4f}')],
            [_param_cell(lbl_c, f'{c_abs:.4f}'), _param_cell(lbl_d, f'{D_v:.4f}')],
        ],
        colWidths=[(CONTENT_W - 0.6 * cm) / 2, (CONTENT_W - 0.6 * cm) / 2],
        rowHeights=[1.4 * cm, 1.4 * cm],
    )
    param_grid.setStyle(TableStyle([
        ('ALIGN',         (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
    ]))
    story.append(param_grid)
    story.append(Spacer(1, 0.4 * cm))

    # ── Statistical Validation block — R² as large green percentage ──────────
    story.append(SectionHeader(
        'Validacao Estatistica' if is_pt else 'Statistical Validation',
        bg_color=GREY_DARK, height=18, font_size=9,
    ))
    story.append(Spacer(1, 0.2 * cm))

    # R² row: label on left, big green percentage on right
    r2_label_style = ParagraphStyle(
        'R2Lbl', parent=st['Normal'],
        fontName='Helvetica-Bold', fontSize=10,
        textColor=GREY_DARK, alignment=TA_LEFT,
    )
    r2_sub_style = ParagraphStyle(
        'R2Sub', parent=st['Normal'],
        fontName='Helvetica', fontSize=8,
        textColor=GREY_MID, alignment=TA_LEFT,
    )
    r2_value_style = ParagraphStyle(
        'R2Val', parent=st['Normal'],
        fontName='Helvetica-Bold', fontSize=20,
        textColor=colors.HexColor('#16a34a'),   # green — matching reference
        alignment=TA_RIGHT,
    )
    r2_sub_text = (
        'Mede a aderencia do modelo aos dados.' if is_pt
        else 'Measures model fit to data.'
    )
    r2_lbl_cell = Table(
        [[Paragraph(f'<b>Coeficiente de Determinacao (R²)</b>', r2_label_style)],
         [Paragraph(r2_sub_text, r2_sub_style)]],
        colWidths=[CONTENT_W * 0.65],
    )
    r2_lbl_cell.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
    ]))
    r2_row_tbl = Table(
        [[r2_lbl_cell, Paragraph(r2_pct, r2_value_style)]],
        colWidths=[CONTENT_W * 0.65, CONTENT_W * 0.35],
    )
    r2_row_tbl.setStyle(TableStyle([
        ('ALIGN',         (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN',         (1, 0), (1, 0),   'RIGHT'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('BACKGROUND',    (0, 0), (-1, -1), colors.white),
        ('BOX',           (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('LINEBELOW',     (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
    ]))
    story.append(r2_row_tbl)
    story.append(Spacer(1, 0.15 * cm))

    # RMSE + NSE side-by-side metric cells
    metric_label_style = ParagraphStyle(
        'MetLbl', parent=st['Normal'],
        fontName='Helvetica', fontSize=7,
        textColor=GREY_MID, alignment=TA_CENTER,
        spaceAfter=2,
    )
    metric_value_style = ParagraphStyle(
        'MetVal', parent=st['Normal'],
        fontName='Helvetica-Bold', fontSize=11,
        textColor=BLUE_DARK, alignment=TA_CENTER,
    )

    def _metric_cell(label, value_str, col_w):
        tbl = Table(
            [[Paragraph(label, metric_label_style)],
             [Paragraph(f'<b>{value_str}</b>', metric_value_style)]],
            colWidths=[col_w],
        )
        tbl.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
            ('BOX',           (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING',    (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('ROUNDEDCORNERS', [4]),
        ]))
        return tbl

    half_w = (CONTENT_W - 0.6 * cm) / 2
    metrics_row = Table(
        [[_metric_cell('RMSE (mm/h)', f'{rmse_v:.4f}', half_w),
          _metric_cell('NSE', f'{nse_v:.4f}', half_w)]],
        colWidths=[half_w + 0.3 * cm, half_w + 0.3 * cm],
    )
    metrics_row.setStyle(TableStyle([
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
    ]))
    story.append(metrics_row)
    story.append(Spacer(1, 0.4 * cm))

    # ── Legend ────────────────────────────────────────────────────────────────
    legend_rows = [
        ('i', 'Intensidade de precipitacao (mm/h)' if is_pt else 'Rainfall intensity (mm/h)'),
        ('t', 'Duracao (min)' if is_pt else 'Duration (min)'),
        ('TR', 'Periodo de retorno (anos)' if is_pt else 'Return period (years)'),
        ('A, B', 'Parametros de escala' if is_pt else 'Scale parameters'),
        ('C, D', 'Parametros de forma' if is_pt else 'Shape parameters'),
    ]
    leg_data = [[
        Paragraph(f'<b>{sym}</b>', ParagraphStyle('LS', parent=st['Normal'],
                  fontName='Helvetica-Bold', fontSize=9, textColor=BLUE_DARK)),
        Paragraph(desc, ParagraphStyle('LD', parent=st['Normal'],
                  fontName='Helvetica', fontSize=9, textColor=GREY_DARK)),
    ] for sym, desc in legend_rows]
    leg_tbl = Table(leg_data, colWidths=[1.8 * cm, CONTENT_W - 1.8 * cm])
    leg_tbl.setStyle(TableStyle([
        ('ALIGN',         (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING',   (0, 0), (0, -1),  8),
        ('LEFTPADDING',   (1, 0), (1, -1),  4),
        ('LINEBELOW',     (0, 0), (-1, -2), 0.3, GREY_MID),
    ]))
    story.append(leg_tbl)
    story.append(Spacer(1, 0.3 * cm))

    # Parameters table
    story.append(Paragraph(
        'Tabela 7a — Parametros de Sherman Ajustados' if is_pt else 'Table 7a — Fitted Sherman Parameters',
        st['H3'],
    ))
    sherman_df = pd.DataFrame([{
        'A': f'{sherman["A"]:.4f}',
        'B': f'{sherman["B"]:.4f}',
        'C': f'{sherman["C"]:.4f}',
        'D': f'{sherman["D"]:.4f}',
        'R²': f'{r2_pct}',
        'RMSE (mm/h)': f'{rmse_v:.4f}',
        'NSE': f'{nse_v:.4f}',
    }])
    story.append(_df_to_rl_table(sherman_df, header_bg=colors.HexColor('#0c4a6e')))
    story.append(Spacer(1, 0.3 * cm))

    # Quality metrics info box
    story.append(_info_box(
        f'<b>{"Qualidade do Ajuste" if is_pt else "Fit Quality"}</b>: '
        f'R² = {r2_pct} | RMSE = {rmse_v:.4f} mm/h | NSE = {nse_v:.4f}. '
        + ('R² proximo de 1 indica excelente ajuste. NSE > 0.9 e considerado muito bom.'
           if is_pt else
           'R² close to 1 indicates excellent fit. NSE > 0.9 is considered very good.'),
        bg=BLUE_LIGHT, border=BLUE_MID, st_dict=st,
    ))
    story.append(Spacer(1, 0.3 * cm))

    # Sherman fitted values vs calculated — comparison table
    story.append(Paragraph(
        'Tabela 7b — Comparação: Intensidades Calculadas vs Ajuste Sherman (TR=10, 25, 100 anos)' if is_pt
        else 'Table 7b — Comparison: Calculated vs Sherman Fit Intensities (TR=10, 25, 100 years)',
        st['H3'],
    ))
    import numpy as np
    from calculations import sherman_model
    compare_trs = [10, 25, 100]
    compare_rows = []
    for dur in DURATIONS:
        row = {'Duração (min)' if is_pt else 'Duration (min)': dur}
        for tr_c in compare_trs:
            col_name = f'TR={tr_c} calc'
            col_name_fit = f'TR={tr_c} fit'
            # Get calculated value from idf_df
            tr_col = [c for c in idf_df.columns if str(tr_c) in c]
            if tr_col:
                row[col_name] = f'{idf_df[tr_col[0]].loc[dur]:.2f}'
            else:
                row[col_name] = '—'
            # Sherman fitted value
            i_fit = sherman_model((dur, tr_c), sherman['A'], sherman['B'], sherman['C'], sherman['D'])
            row[col_name_fit] = f'{i_fit:.2f}'
        compare_rows.append(row)
    compare_df = pd.DataFrame(compare_rows)
    story.append(_df_to_rl_table(compare_df, header_bg=colors.HexColor('#0c4a6e'), font_size=7.5))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # ANNEX — Guia de Uso / User Guide
    # ══════════════════════════════════════════════════════════════════════════
    story.append(SectionHeader(
        'Anexo — Guia de Uso do Aplicativo' if is_pt else 'Annex — Application User Guide',
        bg_color=colors.HexColor('#1e3a5f'),
        height=26, font_size=12,
    ))
    story.append(Spacer(1, 0.4 * cm))

    guide_steps = [
        ('1', '📂 ' + ('Entrada de Dados' if is_pt else 'Data Input'),
         ('Faça upload do arquivo CSV exportado do HidroWeb (ANA) ou insira os dados manualmente '
          'na seção "Entrada de Dados Hidrológicos". O arquivo deve conter a série histórica de '
          'precipitação máxima diária anual. Um arquivo de exemplo pode ser baixado diretamente '
          'na seção de dados.'
          if is_pt else
          'Upload the CSV file exported from HidroWeb (ANA) or enter data manually in the '
          '"Hydrological Data Input" section. The file must contain the annual maximum daily '
          'precipitation historical series. An example file can be downloaded directly in the data section.')),
        ('2', '🗺️ ' + ('Isozona Taborga' if is_pt else 'Taborga Isozone'),
         ('Selecione a isozona correspondente à localização da estação pluviométrica no campo '
          '"Isozona Taborga" na seção "Parâmetros da Região". Consulte o mapa de isozonas '
          'disponível na aba "Isozonas Taborga" para identificar a zona correta. '
          'O recálculo é automático ao alterar a isozona.'
          if is_pt else
          'Select the isozone corresponding to the rain gauge station location in the '
          '"Taborga Isozone" field under "Regional Parameters". Consult the isozone map '
          'in the "Taborga Isozones" tab to identify the correct zone. '
          'Recalculation is automatic when changing the isozone.')),
        ('3', '📊 ' + ('Série Histórica' if is_pt else 'Historical Series'),
         ('A aba "Série Histórica" exibe o gráfico de barras da precipitação máxima diária '
          'anual com a linha de média. Use o filtro de período para restringir a análise a '
          'um intervalo específico de anos.'
          if is_pt else
          'The "Historical Series" tab displays the bar chart of annual maximum daily '
          'precipitation with the mean line. Use the period filter to restrict the analysis '
          'to a specific year range.')),
        ('4', '📐 ' + ('Memória Gumbel' if is_pt else 'Gumbel Memory'),
         ('A aba "Memória Gumbel" apresenta o memorial completo do método de Ven Te Chow, '
          'incluindo a tabela ordenada com todos os parâmetros (m, P, Pr, TR, Y, Kt), '
          'estatísticas amostrais (N, Pn, σn, Yn, Sn) e os resultados de Pt e P24h por TR.'
          if is_pt else
          'The "Gumbel Memory" tab presents the complete Ven Te Chow method memory, '
          'including the ordered table with all parameters (m, P, Pr, TR, Y, Kt), '
          'sample statistics (N, Pn, σn, Yn, Sn) and Pt and P24h results by TR.')),
        ('5', '🗺️ ' + ('Isozonas Taborga' if is_pt else 'Taborga Isozones'),
         ('A aba "Isozonas Taborga" exibe o memorial completo da desagregacao: mapa de isozonas, '
          'tabela de constantes de todas as zonas, dados base (Pt, Ap), relacoes (rel1h, rel6min), '
          'alturas (P1h, P6min), resumo Gumbel e coeficientes K1/K2.'
          if is_pt else
          'The "Taborga Isozones" tab displays the complete disaggregation memory: isozone map, '
          'constants table for all zones, base data (Pt, Ap), ratios (rel1h, rel6min), '
          'heights (P1h, P6min), Gumbel summary and K1/K2 coefficients.')),
        ('6', '🌧️ ' + ('Curvas PDF' if is_pt else 'PDF Curves'),
         ('A aba "Curvas PDF" exibe a precipitação acumulada P(t) por duração e período de '
          'retorno, calculada via desagregação de Taborga. O gráfico mostra todas as TRs '
          '(2, 5, 10, 15, 20, 25, 50 e 100 anos) e a tabela completa da matriz P(t).'
          if is_pt else
          'The "PDF Curves" tab displays accumulated precipitation P(t) by duration and '
          'return period, calculated via Taborga disaggregation. The chart shows all TRs '
          '(2, 5, 10, 15, 20, 25, 50 and 100 years) and the complete P(t) matrix table.')),
        ('7', '⚡ ' + ('Curvas IDF' if is_pt else 'IDF Curves'),
         ('A aba "Curvas IDF" exibe as curvas de intensidade-duração-frequência em escala '
          'log-log, com as curvas calculadas (sólidas) e o ajuste de Sherman (tracejadas). '
          'Os parâmetros A, B, C, D da equação de Montana são exibidos no título.'
          if is_pt else
          'The "IDF Curves" tab displays intensity-duration-frequency curves on a log-log '
          'scale, with calculated curves (solid) and Sherman fit (dashed). The Montana '
          'equation parameters A, B, C, D are shown in the title.')),
        ('8', '📋 ' + ('Tabelas de Resultados' if is_pt else 'Results Tables'),
         ('A aba "Tabelas de Resultados" consolida todas as tabelas: série histórica, '
          'análise de Gumbel, matriz de desagregação P(t) e parâmetros de Sherman.'
          if is_pt else
          'The "Results Tables" tab consolidates all tables: historical series, '
          'Gumbel analysis, P(t) disaggregation matrix and Sherman parameters.')),
        ('9', '📄 ' + ('Exportar PDF' if is_pt else 'Export PDF'),
         ('Clique em "Exportar Memorial de Cálculo (PDF)" na seção "Exportar" para baixar '
          'este relatório completo em PDF, contendo todos os passos, figuras, tabelas e '
          'este guia como anexo.'
          if is_pt else
          'Click "Export Calculation Report (PDF)" in the "Export" section to download '
          'this complete PDF report, containing all steps, figures, tables and '
          'this guide as an annex.')),
    ]

    for step_num, step_title, step_body in guide_steps:
        step_hdr_data = [[
            Paragraph(f'<b>{step_num}</b>', ParagraphStyle(
                f'StepNum{step_num}', parent=st['Normal'],
                fontSize=11, textColor=WHITE, alignment=TA_CENTER,
            )),
            Paragraph(step_title, ParagraphStyle(
                f'StepTitle{step_num}', parent=st['Normal'],
                fontSize=10, textColor=WHITE, fontName='Helvetica-Bold',
            )),
        ]]
        step_hdr = Table(step_hdr_data, colWidths=[0.8 * cm, CONTENT_W - 0.8 * cm])
        step_hdr.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), BLUE_MID),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        body_data = [[Paragraph(step_body, st['Body'])]]
        body_tbl = Table(body_data, colWidths=[CONTENT_W])
        body_tbl.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), GREY_LIGHT),
            ('TOPPADDING',    (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING',   (0, 0), (-1, -1), 10),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
            ('BOX',           (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ]))
        story.append(KeepTogether([step_hdr, body_tbl, Spacer(1, 0.25 * cm)]))

    # ── Build PDF ─────────────────────────────────────────────────────────────
    doc.build(story)
    pdf_bytes = buf.getvalue()
    logger.info(f"✅ Relatório PDF completo gerado: {len(pdf_bytes):,} bytes")
    return pdf_bytes
