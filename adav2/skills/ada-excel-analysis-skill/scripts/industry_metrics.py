"""Métricas específicas por industria.
Cargado por el skill cuando industry_type está definido."""

INDUSTRY_METRICS = {
    "retail": {
        "metricas": [
            "margen_bruto_pct", "margen_neto_pct",
            "rotacion_inventario_dias", "clasificacion_abc",
            "cartera_vencida_total", "dias_mora_promedio",
            "top_10_clientes_por_venta", "top_10_productos_por_margen",
            "productos_margen_negativo", "ranking_vendedores",
            "ranking_sucursales", "variacion_mes_a_mes",
            "concentracion_clientes_pct",
        ],
        "alertas": {
            "margen_negativo": "Producto con margen < 0",
            "cartera_vencida_alta": "Cartera vencida > 15% de ventas",
            "concentracion_alta": "Top 5 clientes > 60% de ventas",
            "stock_congelado": "Producto sin movimiento > 90 días",
        }
    },
    "servicios": {
        "metricas": [
            "sla_cumplimiento_pct", "tickets_abiertos",
            "tickets_resueltos", "tiempo_resolucion_promedio",
            "nps_score", "churn_rate", "revenue_por_cliente",
            "costo_servicio_por_ticket", "backlog_horas",
        ],
        "alertas": {
            "sla_incumplido": "SLA < 95%",
            "backlog_alto": "Backlog > 200 horas",
            "churn_alto": "Churn > 5% mensual",
        }
    }
}


def get_metrics_for_industry(industry_type: str) -> dict:
    return INDUSTRY_METRICS.get(industry_type, {"metricas": [], "alertas": {}})
