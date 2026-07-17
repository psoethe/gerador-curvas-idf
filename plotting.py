"""
Plotly figure generation for IDF Curve Generator.
"""
import logging
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from calculations import DURATIONS, RETURN_PERIODS, sherman_model
from i18n import t

logger = logging.getLogger("viktor")

# Professional color palette for TR lines
TR_COLORS = px.colors.qualitative.Set1[:len(RETURN_PERIODS)]


def fig_historical_series(series_df, lang: str = 'PT') -> go.Figure:
    """Bar + line chart of the consolidated historical series."""
    fig = go.Figure()

    col_ano = t('col_ano', lang)
    col_precip = t('col_precip', lang)
    mean_val = series_df[col_precip].mean()

    fig.add_trace(go.Bar(
        x=series_df[col_ano],
        y=series_df[col_precip],
        name=t('hist_bar_name', lang),
        marker_color='steelblue',
        opacity=0.75,
    ))

    # Mean line
    fig.add_hline(
        y=mean_val,
        line_dash='dash',
        line_color='firebrick',
        annotation_text=f'{t("hist_mean_label", lang)}: {mean_val:.1f} mm',
        annotation_position='top right',
    )

    fig.update_layout(
        title=t('hist_title', lang),
        xaxis=dict(title=dict(text=t('axis_year', lang))),
        yaxis=dict(title=dict(text=t('axis_precip_mm', lang))),
        template='plotly_white',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    )
    return fig


def fig_gumbel_analysis(gumbel_df, mu: float, sigma: float, n: int, lang: str = 'PT') -> go.Figure:
    """Bar chart of Pt vs TR with statistics annotation."""
    fig = go.Figure()

    # Build bar colors: TR_COLORS may be hex '#rrggbb' or 'rgb(r,g,b)' — handle both
    def _to_rgba(c: str, alpha: float = 0.8) -> str:
        c = c.strip()
        if c.startswith('#') and len(c) == 7:
            r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
            return f'rgba({r},{g},{b},{alpha})'
        if c.startswith('rgb('):
            inner = c[4:-1]
            parts = [p.strip() for p in inner.split(',')]
            return f'rgba({parts[0]},{parts[1]},{parts[2]},{alpha})'
        return c

    col_tr = t('col_tr', lang)
    col_pt = t('col_pt', lang)

    fig.add_trace(go.Bar(
        x=[str(tr) for tr in gumbel_df[col_tr]],
        y=gumbel_df[col_pt],
        name=t('gumbel_bar_name', lang),
        marker_color=[_to_rgba(c) for c in TR_COLORS],
        text=[f'{v:.1f}' for v in gumbel_df[col_pt]],
        textposition='outside',
    ))

    fig.update_layout(
        title=(
            f'{t("gumbel_title", lang)}<br>'
            f'<sup>N={n} {t("report_n_suffix", lang).strip()} | μ={mu:.2f} mm | σ={sigma:.2f} mm</sup>'
        ),
        xaxis=dict(title=dict(text=t('axis_tr', lang))),
        yaxis=dict(title=dict(text=t('axis_precip_mm', lang))),
        template='plotly_white',
        showlegend=False,
    )
    return fig


def fig_pdf_curves(disagg_df, lang: str = 'PT') -> go.Figure:
    fig = go.Figure()

    for i, col in enumerate(disagg_df.columns):
        tr_label = col.replace('TR=', 'TR = ')
        fig.add_trace(go.Scatter(
            x=list(DURATIONS),             # <-- CONVERTER PARA LISTA AQUI
            y=disagg_df[col].tolist(),     # <-- USAR .tolist() AQUI
            mode='lines+markers',
            name=tr_label,
            line=dict(color=TR_COLORS[i % len(TR_COLORS)], width=2),
            marker=dict(size=5),
        ))

    fig.update_layout(
        title=t('pdf_title', lang),
        xaxis=dict(title=dict(text=t('axis_duration_min', lang))),
        yaxis=dict(title=dict(text=t('axis_precip_p', lang))),
        template='plotly_white',
        legend=dict(title=t('legend_tr', lang), orientation='v'),
    )
    return fig


def fig_idf_curves(idf_df, sherman_params: dict, lang: str = 'PT') -> go.Figure:
    fig = go.Figure()
    
    # Manter o array numpy original para os cálculos matemáticos
    t_smooth_arr = np.logspace(np.log10(6), np.log10(1440), 200)
    # Criar uma versão em lista nativa para o gráfico
    t_smooth_list = t_smooth_arr.tolist()

    for i, col in enumerate(idf_df.columns):
        tr_val = int(col.split('=')[1].split(' ')[0])
        color = TR_COLORS[i % len(TR_COLORS)]
        tr_label = col.replace('TR=', 'TR = ')

        # Curvas Calculadas (sólidas)
        fig.add_trace(go.Scatter(
            x=list(DURATIONS),             # <-- CONVERTER PARA LISTA AQUI
            y=idf_df[col].tolist(),        # <-- USAR .tolist() AQUI
            mode='lines+markers',
            name=f'{tr_label} {t("idf_calc_suffix", lang)}',
            line=dict(color=color, width=2, dash='solid'),
            marker=dict(size=5),
            legendgroup=f'TR{tr_val}',
        ))

        # Ajuste de Sherman (tracejadas)
        A = sherman_params['A']
        B = sherman_params['B']
        C = sherman_params['C']
        D = sherman_params['D']
        
        # Usar o array numpy (t_smooth_arr) apenas no cálculo matemático
        i_fitted = sherman_model((t_smooth_arr, np.full_like(t_smooth_arr, tr_val)), A, B, C, D)

        fig.add_trace(go.Scatter(
            x=t_smooth_list,               # <-- USAR A LISTA AQUI
            y=i_fitted.tolist(),           # <-- USAR .tolist() AQUI
            mode='lines',
            name=f'{tr_label} {t("idf_sherman_suffix", lang)}',
            line=dict(color=color, width=1.5, dash='dash'),
            legendgroup=f'TR{tr_val}',
            showlegend=True,
        ))

    fig.update_layout(
        title=(
            f'{t("idf_title", lang)}<br>'
            f'<sup>i = (A·TR^B) / (t+C)^D | '
            f'A={sherman_params["A"]:.2f}, B={sherman_params["B"]:.4f}, '
            f'C={sherman_params["C"]:.2f}, D={sherman_params["D"]:.4f} | '
            f'R²={sherman_params["R²"]:.4f}</sup>'
        ),
        xaxis=dict(
            title=dict(text=t('axis_duration_min', lang)),
            type='log',
        ),
        yaxis=dict(
            title=dict(text=t('axis_intensity', lang)),
            type='log',
        ),
        template='plotly_white',
        legend=dict(title=t('legend_tr', lang), orientation='v', font=dict(size=10)),
    )
    return fig
