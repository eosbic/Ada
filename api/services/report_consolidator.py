"""
Report Consolidator — Consulta, agrega y consolida reportes de multiples periodos.
Punto de entrada: get_consolidated_data(empresa_id, period_text, source_filter).
"""

import re
import json
from datetime import datetime, date, timedelta
from collections import defaultdict
from typing import Optional
from sqlalchemy import text as sql_text
from api.database import sync_engine


# Meses en español
MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def parse_period(text: str) -> tuple[str, str]:
    """
    Recibe texto libre y retorna (start_date, end_date) en YYYY-MM-DD.
    Soporta: meses en español, trimestres, semestres, rangos relativos.
    """
    text = (text or "").lower().strip()
    today = date.today()
    current_year = today.year

    # Extraer año si lo mencionan
    year_match = re.search(r"\b(20\d{2})\b", text)
    year = int(year_match.group(1)) if year_match else current_year

    # "este mes"
    if "este mes" in text:
        start = today.replace(day=1)
        return str(start), str(today)

    # "este año" / "año actual"
    if "este año" in text or "año actual" in text or "año en curso" in text:
        start = date(current_year, 1, 1)
        return str(start), str(today)

    # "anual" / "año XXXX"
    if "anual" in text or re.search(r"a[ñn]o\s+\d{4}", text):
        start = date(year, 1, 1)
        end = date(year, 12, 31) if year < current_year else today
        return str(start), str(end)

    # "ultimo(s) N meses"
    m = re.search(r"[uú]ltimos?\s+(\d+)\s+mes(?:es)?", text)
    if m:
        months = int(m.group(1))
        start = today - timedelta(days=months * 30)
        return str(start), str(today)

    # "ultima(s) N semanas"
    m = re.search(r"[uú]ltimas?\s+(\d+)\s+semanas?", text)
    if m:
        weeks = int(m.group(1))
        start = today - timedelta(weeks=weeks)
        return str(start), str(today)

    # Trimestres: Q1-Q4 o "primer trimestre", etc.
    q_map = {
        "q1": (1, 3), "q2": (4, 6), "q3": (7, 9), "q4": (10, 12),
        "primer trimestre": (1, 3), "segundo trimestre": (4, 6),
        "tercer trimestre": (7, 9), "cuarto trimestre": (10, 12),
        "1er trimestre": (1, 3), "2do trimestre": (4, 6),
        "3er trimestre": (7, 9), "4to trimestre": (10, 12),
    }
    for pattern, (sm, em) in q_map.items():
        if pattern in text:
            start = date(year, sm, 1)
            if em == 12:
                end = date(year, 12, 31)
            else:
                end = date(year, em + 1, 1) - timedelta(days=1)
            if end > today:
                end = today
            return str(start), str(end)

    # Semestres: H1/H2 o "primer semestre"
    h_map = {
        "h1": (1, 6), "h2": (7, 12),
        "primer semestre": (1, 6), "segundo semestre": (7, 12),
        "1er semestre": (1, 6), "2do semestre": (7, 12),
    }
    for pattern, (sm, em) in h_map.items():
        if pattern in text:
            start = date(year, sm, 1)
            if em == 12:
                end = date(year, 12, 31)
            else:
                end = date(year, em + 1, 1) - timedelta(days=1)
            if end > today:
                end = today
            return str(start), str(end)

    # Mes individual en español: "marzo", "marzo 2025"
    for mes_name, mes_num in MESES.items():
        if mes_name in text:
            start = date(year, mes_num, 1)
            if mes_num == 12:
                end = date(year, 12, 31)
            else:
                end = date(year, mes_num + 1, 1) - timedelta(days=1)
            if end > today:
                end = today
            return str(start), str(end)

    # Default: ultimos 12 meses
    start = today - timedelta(days=365)
    return str(start), str(today)


def fetch_reports_for_period(
    empresa_id: str,
    period_start: str,
    period_end: str,
    report_type: str = None,
    source_file_pattern: str = None,
    include_markdown: bool = True,
) -> list[dict]:
    """
    SELECT de ada_reports con TODOS los reportes del periodo.
    Retorna lista de dicts con metadatos y contenido.
    """
    if not empresa_id:
        return []

    try:
        conditions = [
            "empresa_id = :eid",
            "is_archived = FALSE",
            "created_at >= :start::timestamp",
            "created_at <= :end::timestamp + interval '1 day'",
        ]
        params = {
            "eid": empresa_id,
            "start": period_start,
            "end": period_end,
        }

        if report_type:
            conditions.append("report_type = :rtype")
            params["rtype"] = report_type

        if source_file_pattern:
            conditions.append("source_file ILIKE :sfp")
            params["sfp"] = source_file_pattern

        md_col = ", markdown_content" if include_markdown else ""

        query = f"""
            SELECT id, title, source_file, report_type,
                   metrics_summary, alerts, created_at{md_col}
            FROM ada_reports
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at ASC
        """

        with sync_engine.connect() as conn:
            rows = conn.execute(sql_text(query), params).fetchall()

        reports = []
        for row in rows:
            metrics = {}
            if row.metrics_summary:
                try:
                    metrics = json.loads(row.metrics_summary) if isinstance(row.metrics_summary, str) else row.metrics_summary
                except Exception:
                    metrics = {}

            alerts_parsed = []
            if row.alerts:
                try:
                    alerts_parsed = json.loads(row.alerts) if isinstance(row.alerts, str) else row.alerts
                except Exception:
                    alerts_parsed = []

            report = {
                "id": str(row.id),
                "title": row.title,
                "source_file": row.source_file,
                "report_type": row.report_type,
                "metrics_summary": metrics,
                "alerts": alerts_parsed,
                "created_at": str(row.created_at),
                "created_date": row.created_at.strftime("%Y-%m-%d") if row.created_at else "",
                "created_month": row.created_at.strftime("%Y-%m") if row.created_at else "",
            }

            if include_markdown:
                report["markdown_content"] = row.markdown_content or ""

            reports.append(report)

        print(f"CONSOLIDATOR: {len(reports)} reportes encontrados para {period_start} - {period_end}")
        return reports

    except Exception as e:
        print(f"CONSOLIDATOR: Error consultando reportes: {e}")
        import traceback
        traceback.print_exc()
        return []


def consolidate_metrics(reports: list[dict]) -> dict:
    """
    Consolida metrics_summary de N reportes.
    Agrupa por mes, calcula totales, promedios y tendencias.
    """
    if not reports:
        return {
            "total_reports": 0,
            "period": "",
            "months_covered": [],
            "report_files": [],
            "global_totals": {},
            "global_averages": {},
            "by_month": {},
            "trends": {},
            "all_alerts": [],
            "top_metrics": [],
        }

    # Agrupar metricas por mes
    by_month = defaultdict(lambda: defaultdict(list))
    all_metric_values = defaultdict(list)
    all_alerts = []
    report_files = []

    for r in reports:
        month = r.get("created_month", "unknown")
        report_files.append(r.get("source_file", ""))

        for key, value in r.get("metrics_summary", {}).items():
            if isinstance(value, (int, float)):
                by_month[month][key].append(value)
                all_metric_values[key].append(value)

        for alert in r.get("alerts", []):
            if isinstance(alert, dict):
                alert["report_date"] = r.get("created_date", "")
                alert["source_file"] = r.get("source_file", "")
                all_alerts.append(alert)

    months_covered = sorted(by_month.keys())
    report_files = list(dict.fromkeys(report_files))  # dedup preserving order

    # Totales globales
    global_totals = {}
    global_averages = {}
    for key, values in all_metric_values.items():
        global_totals[key] = round(sum(values), 2)
        global_averages[key] = round(sum(values) / len(values), 2)

    # Desglose mensual
    monthly_breakdown = {}
    for month in months_covered:
        month_data = {}
        for key, values in by_month[month].items():
            month_data[key] = {
                "total": round(sum(values), 2),
                "avg": round(sum(values) / len(values), 2),
                "count": len(values),
            }
        monthly_breakdown[month] = month_data

    # Tendencias: comparar primer mes vs ultimo
    trends = {}
    if len(months_covered) >= 2:
        first_month = months_covered[0]
        last_month = months_covered[-1]
        first_data = by_month[first_month]
        last_data = by_month[last_month]

        for key in all_metric_values:
            if key in first_data and key in last_data:
                first_val = sum(first_data[key]) / len(first_data[key])
                last_val = sum(last_data[key]) / len(last_data[key])

                if first_val != 0:
                    change_pct = round(((last_val - first_val) / abs(first_val)) * 100, 2)
                else:
                    change_pct = 0

                if change_pct > 5:
                    direction = "up"
                elif change_pct < -5:
                    direction = "down"
                else:
                    direction = "stable"

                trends[key] = {
                    "first_month": first_month,
                    "last_month": last_month,
                    "first_value": round(first_val, 2),
                    "last_value": round(last_val, 2),
                    "change_pct": change_pct,
                    "direction": direction,
                }

    # Top metricas por magnitud
    top_metrics = sorted(
        global_totals.items(),
        key=lambda x: abs(x[1]),
        reverse=True,
    )[:10]

    period = f"{months_covered[0]} a {months_covered[-1]}" if months_covered else ""

    return {
        "total_reports": len(reports),
        "period": period,
        "months_covered": months_covered,
        "report_files": report_files,
        "global_totals": global_totals,
        "global_averages": global_averages,
        "by_month": monthly_breakdown,
        "trends": trends,
        "all_alerts": all_alerts,
        "top_metrics": top_metrics,
    }


def format_consolidation_for_llm(
    consolidated: dict,
    reports: list[dict],
    max_markdown_chars: int = 20000,
) -> str:
    """Formatea la consolidacion como string para el prompt del LLM."""
    parts = []

    # Resumen general
    parts.append(f"## CONSOLIDACION DE REPORTES")
    parts.append(f"**Periodo:** {consolidated['period']}")
    parts.append(f"**Total reportes:** {consolidated['total_reports']}")
    parts.append(f"**Meses cubiertos:** {', '.join(consolidated['months_covered'])}")

    # Archivos incluidos
    files = consolidated.get("report_files", [])
    if files:
        parts.append(f"\n**Archivos analizados ({len(files)}):**")
        for f in files:
            parts.append(f"  - {f}")

    # Totales globales
    totals = consolidated.get("global_totals", {})
    if totals:
        parts.append(f"\n## TOTALES GLOBALES")
        for key, val in sorted(totals.items(), key=lambda x: abs(x[1]), reverse=True)[:15]:
            parts.append(f"  - **{key}:** {val:,.2f}")

    # Promedios
    avgs = consolidated.get("global_averages", {})
    if avgs:
        parts.append(f"\n## PROMEDIOS GLOBALES")
        for key, val in sorted(avgs.items(), key=lambda x: abs(x[1]), reverse=True)[:10]:
            parts.append(f"  - **{key}:** {val:,.2f}")

    # Desglose mensual
    by_month = consolidated.get("by_month", {})
    if by_month:
        parts.append(f"\n## DESGLOSE MENSUAL")
        for month in sorted(by_month.keys()):
            month_data = by_month[month]
            parts.append(f"\n### {month}")
            for key, stats in sorted(month_data.items(), key=lambda x: abs(x[1].get("total", 0)), reverse=True)[:8]:
                parts.append(f"  - {key}: total={stats['total']:,.2f}, avg={stats['avg']:,.2f} ({stats['count']} reportes)")

    # Tendencias
    trends = consolidated.get("trends", {})
    if trends:
        parts.append(f"\n## TENDENCIAS")
        for key, t in trends.items():
            arrow = "↑" if t["direction"] == "up" else "↓" if t["direction"] == "down" else "→"
            parts.append(
                f"  - **{key}:** {t['first_value']:,.2f} → {t['last_value']:,.2f} "
                f"{arrow} {t['change_pct']:+.1f}% ({t['first_month']} vs {t['last_month']})"
            )

    # Alertas criticas
    alerts = consolidated.get("all_alerts", [])
    critical_alerts = [a for a in alerts if a.get("level") in ("critical", "error")]
    warning_alerts = [a for a in alerts if a.get("level") == "warning"]
    if critical_alerts or warning_alerts:
        parts.append(f"\n## ALERTAS ACUMULADAS")
        for a in critical_alerts[:10]:
            parts.append(f"  🔴 [{a.get('report_date', '')}] {a.get('message', '')}")
        for a in warning_alerts[:10]:
            parts.append(f"  🟠 [{a.get('report_date', '')}] {a.get('message', '')}")

    # Extractos de markdown de cada reporte
    if reports and max_markdown_chars > 0:
        parts.append(f"\n## EXTRACTOS DE REPORTES")
        chars_per_report = max_markdown_chars // max(len(reports), 1)
        chars_per_report = max(chars_per_report, 200)
        for r in reports:
            md = r.get("markdown_content", "")
            if md:
                parts.append(f"\n### [{r.get('created_date', '')}] {r.get('title', '')} ({r.get('source_file', '')})")
                parts.append(md[:chars_per_report])

    result = "\n".join(parts)
    return result


def get_consolidated_data(
    empresa_id: str,
    period_text: str,
    source_filter: Optional[str] = None,
) -> tuple[dict, list[dict], str]:
    """
    Punto de entrada principal.
    Retorna (consolidated, reports, formatted).
    """
    start, end = parse_period(period_text)
    print(f"CONSOLIDATOR: Periodo parseado: {start} → {end} (input: '{period_text}')")

    pattern = f"%{source_filter}%" if source_filter else None
    reports = fetch_reports_for_period(
        empresa_id=empresa_id,
        period_start=start,
        period_end=end,
        source_file_pattern=pattern,
    )

    consolidated = consolidate_metrics(reports)
    formatted = format_consolidation_for_llm(consolidated, reports)

    return consolidated, reports, formatted
