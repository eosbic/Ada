"""
Chart Generator — Genera graficos PNG con matplotlib para incrustar en PDFs.
Estilo oscuro profesional. PNGs temporales en /tmp/.
"""

import uuid
import os
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker


CHART_DIR = Path("/tmp/ada_charts")
CHART_DIR.mkdir(parents=True, exist_ok=True)

# Paleta profesional
COLORS_BAR = ["#00e5ff", "#7c3aed", "#00ff9d", "#ff6b35", "#ffd60a", "#ff3d5a", "#378ADD", "#1D9E75", "#D4537E", "#BA7517"]
COLORS_PIE = ["#00e5ff", "#7c3aed", "#00ff9d", "#ff6b35", "#ffd60a", "#ff3d5a", "#378ADD", "#1D9E75", "#D4537E", "#BA7517"]

DARK_BG = "#0c1220"
DARK_CARD = "#101828"
DARK_TEXT = "#e0f4ff"
DARK_GRID = "#1a2840"

LIGHT_BG = "#ffffff"
LIGHT_CARD = "#f8f8f6"
LIGHT_TEXT = "#1a1a1a"
LIGHT_TEXT2 = "#555555"
LIGHT_GRID = "#e0e0dc"
COLORS_LIGHT = ["#2563eb", "#7c3aed", "#059669", "#d97706", "#dc2626", "#0891b2", "#4f46e5", "#15803d", "#b91c1c", "#9333ea"]


def _apply_dark_style():
    """Aplica estilo oscuro profesional."""
    plt.rcParams.update({
        "figure.facecolor": DARK_BG,
        "axes.facecolor": DARK_CARD,
        "axes.edgecolor": DARK_GRID,
        "axes.labelcolor": DARK_TEXT,
        "text.color": DARK_TEXT,
        "xtick.color": "#7eafc9",
        "ytick.color": "#7eafc9",
        "grid.color": DARK_GRID,
        "grid.alpha": 0.4,
        "font.family": "sans-serif",
        "font.size": 10,
    })


def _apply_light_style():
    """Aplica estilo claro profesional para PDFs corporativos."""
    plt.rcParams.update({
        "figure.facecolor": LIGHT_BG,
        "axes.facecolor": LIGHT_CARD,
        "axes.edgecolor": LIGHT_GRID,
        "axes.labelcolor": LIGHT_TEXT,
        "text.color": LIGHT_TEXT,
        "xtick.color": LIGHT_TEXT2,
        "ytick.color": LIGHT_TEXT2,
        "grid.color": LIGHT_GRID,
        "grid.alpha": 0.5,
        "font.family": "sans-serif",
        "font.size": 10,
    })


def generate_bar_chart(
    labels: list[str],
    values: list[float],
    title: str = "Grafico",
    horizontal: bool = False,
    figsize: tuple = (8, 4.5),
    light_mode: bool = False,
) -> Optional[str]:
    """Genera grafico de barras PNG. Retorna path al archivo o None."""
    if not labels or not values or len(labels) != len(values):
        return None

    if light_mode:
        _apply_light_style()
        text_color = LIGHT_TEXT
        palette = COLORS_LIGHT
    else:
        _apply_dark_style()
        text_color = DARK_TEXT
        palette = COLORS_BAR

    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    colors = [palette[i % len(palette)] for i in range(len(labels))]

    if horizontal:
        y_pos = range(len(labels))
        bars = ax.barh(y_pos, values, color=colors, height=0.6, edgecolor="none")
        ax.set_yticks(y_pos)
        ax.set_yticklabels([l[:30] for l in labels], fontsize=8)
        ax.invert_yaxis()
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
        ax.set_xlabel("")
        for bar, val in zip(bars, values):
            ax.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
                    f"{val:,.0f}", va="center", fontsize=7, color=text_color)
    else:
        x_pos = range(len(labels))
        bars = ax.bar(x_pos, values, color=colors, width=0.65, edgecolor="none")
        ax.set_xticks(x_pos)
        ax.set_xticklabels([l[:20] for l in labels], fontsize=8, rotation=25, ha="right")
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
        ax.set_ylabel("")
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.01,
                    f"{val:,.0f}", ha="center", fontsize=7, color=text_color)

    ax.set_title(title, fontsize=12, fontweight="bold", color=text_color, pad=12)
    ax.grid(axis="y" if not horizontal else "x", linestyle="--", alpha=0.2 if not light_mode else 0.4)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()

    filename = f"chart_{uuid.uuid4().hex[:10]}.png"
    filepath = str(CHART_DIR / filename)
    fig.savefig(filepath, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    return filepath


def generate_pie_chart(
    labels: list[str],
    values: list[float],
    title: str = "Distribucion",
    figsize: tuple = (6, 5),
    light_mode: bool = False,
) -> Optional[str]:
    """Genera grafico de torta PNG. Retorna path al archivo o None."""
    if not labels or not values or len(labels) != len(values):
        return None

    if light_mode:
        _apply_light_style()
        text_color = LIGHT_TEXT
        edge_color = LIGHT_BG
        palette = COLORS_LIGHT
    else:
        _apply_dark_style()
        text_color = DARK_TEXT
        edge_color = DARK_BG
        palette = COLORS_PIE

    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    colors = [palette[i % len(palette)] for i in range(len(labels))]

    total = sum(values)
    if total == 0:
        plt.close(fig)
        return None

    wedges, texts, autotexts = ax.pie(
        values,
        labels=None,
        colors=colors,
        autopct=lambda p: f"{p:.1f}%" if p > 5 else "",
        startangle=90,
        pctdistance=0.75,
        wedgeprops={"edgecolor": edge_color, "linewidth": 2},
    )

    for t in autotexts:
        t.set_fontsize(8)
        t.set_color(text_color)

    legend_labels = [f"{l[:25]} ({v:,.0f})" for l, v in zip(labels, values)]
    ax.legend(wedges, legend_labels, loc="center left", bbox_to_anchor=(1, 0.5),
              fontsize=8, frameon=False, labelcolor=text_color)

    ax.set_title(title, fontsize=12, fontweight="bold", color=text_color, pad=12)
    fig.tight_layout()

    filename = f"pie_{uuid.uuid4().hex[:10]}.png"
    filepath = str(CHART_DIR / filename)
    fig.savefig(filepath, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    return filepath


def generate_doughnut_chart(
    labels: list[str],
    values: list[float],
    title: str = "Indicadores",
    figsize: tuple = (7, 4.5),
    light_mode: bool = False,
) -> Optional[str]:
    """Genera grafico de dona PNG para porcentajes. Retorna path o None."""
    if not labels or not values or len(labels) != len(values):
        return None

    if light_mode:
        _apply_light_style()
        text_color = LIGHT_TEXT
        edge_color = LIGHT_BG
        palette = COLORS_LIGHT
    else:
        _apply_dark_style()
        text_color = DARK_TEXT
        edge_color = DARK_BG
        palette = COLORS_BAR

    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    colors = [palette[i % len(palette)] for i in range(len(labels))]

    total = sum(abs(v) for v in values)
    if total == 0:
        plt.close(fig)
        return None

    wedges, texts, autotexts = ax.pie(
        [abs(v) for v in values],
        labels=None,
        colors=colors,
        autopct=lambda p: f"{p:.1f}%" if p > 4 else "",
        startangle=90,
        pctdistance=0.78,
        wedgeprops={"edgecolor": edge_color, "linewidth": 2, "width": 0.45},
    )
    for t in autotexts:
        t.set_fontsize(8)
        t.set_color(text_color)

    legend_labels = [f"{l[:28]} ({v:,.1f}%)" for l, v in zip(labels, values)]
    ax.legend(wedges, legend_labels, loc="center left", bbox_to_anchor=(1, 0.5),
              fontsize=8, frameon=False, labelcolor=text_color)

    ax.set_title(title, fontsize=12, fontweight="bold", color=text_color, pad=12)
    fig.tight_layout()

    filename = f"donut_{uuid.uuid4().hex[:10]}.png"
    filepath = str(CHART_DIR / filename)
    fig.savefig(filepath, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return filepath


def generate_charts_from_metrics(metrics: dict, markdown: str = "", light_mode: bool = False) -> list[str]:
    """Genera todos los graficos posibles desde metrics_summary. Retorna lista de paths PNG."""
    from api.services.visual_report_service import _extract_chart_data

    charts = _extract_chart_data(metrics, markdown)
    paths = []

    for chart in charts:
        labels = chart.get("labels", [])
        values = chart.get("values", [])
        title = chart.get("title", "Grafico")
        chart_type = chart.get("type", "bar")

        if len(labels) < 2:
            continue

        if chart_type == "doughnut":
            path = generate_doughnut_chart(labels, values, title, light_mode=light_mode)
        elif chart_type == "horizontalBar":
            path = generate_bar_chart(labels, values, title, horizontal=True, light_mode=light_mode)
        else:
            path = generate_bar_chart(labels, values, title, horizontal=False, light_mode=light_mode)

        if path:
            paths.append(path)

    return paths


def cleanup_charts(paths: list[str]) -> None:
    """Elimina archivos de graficos temporales."""
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass
