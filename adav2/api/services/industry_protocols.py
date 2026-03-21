PROTOCOLS = {
    "construccion": {
        "kpis": ["CPI", "SPI", "EAC", "Variación de Alcance", "Desperdicio de Insumos"],
        "analysis": """
ANÁLISIS SECTORIAL — CONSTRUCCIÓN:
- Auditoría de Desviaciones: brecha entre presupuesto ajustado y proyección actual por capítulo de obra
- Valor Ganado (EVM): CPI (eficiencia de costo) y SPI (eficiencia de tiempo). Si CPI < 1, el proyecto gasta más de lo planeado
- Simulación de Cierre (EAC): proyectar sobrecosto usando ineficiencia histórica del CPI
- Consumo de Insumos Críticos: cruce teórico vs real de concreto, acero, cemento, agregados. Si desperdicio > 5%, alertar fuga de capital
- Horas Hombre (HH): productividad por cuadrilla, rendimientos por capítulo (m²/HH, m³/HH, ml/HH). Detectar horas extra no planificadas
- Impacto Inflacionario: si avance < 40%, simular impacto de inflación en materiales base sobre presupuesto restante
- Riesgo de Subcontratistas: capítulos con mayor desviación de costo por ineficiencia de terceros
- Scope Creep: trabajos adicionales ejecutados sin orden de cambio que erosionan margen
""",
        "forecasting": "Cálculo de EAC basado en CPI actual. Si CPI=0.85, el presupuesto restante costará 17.6% más.",
        "alerts": "🔴 CPI < 0.85 | 🔴 Desperdicio > 10% | 🟠 SPI < 0.9 | 🟠 Avance < plan > 15%",
    },

    "retail": {
        "kpis": ["Margen Bruto", "DSO", "GMROI", "Churn Rate", "Concentración Top 2"],
        "analysis": """
ANÁLISIS SECTORIAL — RETAIL/MAYOREO:
- Product Mix: Top 5 SKUs por margen bruto y volumen. Productos de baja rotación (días inventario > promedio) con costo de oportunidad
- GMROI: retorno por cada peso invertido en inventario por categoría
- Fuerza de Ventas: cumplimiento de cuota, ticket promedio, margen por vendedor. Si Top 2 > 40% de ventas → riesgo persona clave
- Cartera: aging por estratos (1-30, 31-60, 61-90, +90 días), DSO, provisión por incobrables
- Eficiencia Logística: inventario inmovilizado >90 días, rutas con margen neto negativo tras costos de transporte
- Retención: clientes recurrentes inactivos, pérdida de LTV proyectada
- Complementariedad: correlaciones entre productos para cross-selling
- Estacionalidad: cruce de series para predecir picos de demanda y compras preventivas
""",
        "forecasting": "Proyección de ventas y margen del siguiente trimestre basado en tendencia actual.",
        "alerts": "🔴 Margen negativo | 🔴 Mora > 90 días | 🟠 Concentración > 40% | 🟠 Inventario > 90 días",
    },

    "salud": {
        "kpis": ["Tasa Ocupación", "Glosas/Denegaciones", "Margen por Especialidad", "Merma Farmacia"],
        "analysis": """
ANÁLISIS SECTORIAL — SALUD:
- Eficiencia Operativa: tasa de ocupación de quirófanos, rotación de camas, tiempos muertos entre procedimientos
- Insumos y Farmacia: inventario de alto costo (fármacos/prótesis), mermas, vencimientos próximos (<30 días)
- Ciclo de Ingresos (RCM): glosas por aseguradora, patrones de error en codificación médica
- Rentabilidad por Especialidad: margen neto restando costos directos y prorrateo de fijos
""",
        "forecasting": "Proyección de ingresos por especialidad y riesgo de glosas acumuladas.",
        "alerts": "🔴 Merma farmacia > 5% | 🔴 Glosas > 15% | 🟠 Ocupación < 60%",
    },

    "agricultura": {
        "kpis": ["Rendimiento ton/ha", "Eficiencia de Insumos", "Merma en Transporte", "Precio Commodity"],
        "analysis": """
ANÁLISIS SECTORIAL — AGROINDUSTRIA:
- Varianza de Rendimiento: ton/hectárea real vs proyectado por lote. Eficiencia de conversión de fertilizantes/agua
- Logística Perecederos: cadena de frío, merma en transporte, costo de oportunidad por retrasos en cosecha
- Activos Biológicos: flujo de caja basado en ciclo de maduración y volatilidad del commodity
- Riesgo Climático: simulación de pérdida ante variaciones de temperatura/pluviosidad
""",
        "forecasting": "Proyección de cosecha y precio de venta basado en tendencia del commodity.",
        "alerts": "🔴 Merma > 8% | 🟠 Rendimiento < 80% del proyectado | 🟠 Precio commodity en caída",
    },

    "servicios": {
        "kpis": ["Utilization Rate", "Margen por Proyecto", "Pipeline Value", "Concentración Talento"],
        "analysis": """
ANÁLISIS SECTORIAL — SERVICIOS PROFESIONALES:
- Utilization Rate: horas facturables vs totales por consultor. Scope Creep no facturado
- Rentabilidad por Proyecto: margen neto tras costo por hora cargado (incluyendo prestaciones)
- Riesgo de Talento: % facturación generado por socios clave. Vulnerabilidad ante fuga de capital intelectual
- Pipeline: tasa de conversión de propuestas, backlog vs capacidad instalada
""",
        "forecasting": "Proyección de facturación basado en pipeline y utilization rate actual.",
        "alerts": "🔴 Utilization < 60% | 🟠 Concentración talento > 40% | 🟠 Pipeline < 3 meses",
    },

    "tecnologia": {
        "kpis": ["LTV/CAC", "Churn Rate", "MRR/ARR", "Rule of 40", "Margen Infra Cloud"],
        "analysis": """
ANÁLISIS SECTORIAL — SOFTWARE/SAAS:
- Unit Economics: LTV/CAC ratio y payback period. Si CAC > LTV → modelo insostenible
- Churn Forensics: logo churn vs revenue churn, causa raíz por uso de producto
- Margen de Infraestructura: eficiencia del gasto Cloud (AWS/Azure) vs crecimiento de usuarios
- Rule of 40: crecimiento + margen debe superar 40% para empresa saludable
""",
        "forecasting": "Proyección de MRR/ARR y runway basado en burn rate actual.",
        "alerts": "🔴 LTV/CAC < 3 | 🔴 Churn > 5% mensual | 🟠 Rule of 40 < 30",
    },

    "educacion": {
        "kpis": ["Retención por Cohorte", "LTV Alumno", "Carga Académica", "Mora Pensiones"],
        "analysis": """
ANÁLISIS SECTORIAL — EDUCACIÓN:
- LTV y Retención: deserción por semestre, pérdida de ingresos proyectada hasta graduación
- Carga Académica: ratio alumnos/docente, rentabilidad de programas/facultades, cursos subutilizados
- Becas: impacto de beneficios en margen neto, correlación becas vs retención real
- Mora: aging de pensiones vencidas con segmentación socioeconómica
""",
        "forecasting": "Proyección de deserción y pérdida de ingresos por cohorte.",
        "alerts": "🔴 Deserción > 20% | 🟠 Mora > 60 días | 🟠 Programas con margen negativo",
    },

    "alimentos": {
        "kpis": ["Prime Cost", "Food Cost %", "RevPASH", "Variación Porcionamiento"],
        "analysis": """
ANÁLISIS SECTORIAL — RESTAURANTES/ALIMENTOS:
- Prime Cost: costo alimentos + mano de obra. Umbral máximo: 60%
- Ingeniería de Menú: clasificación de platos en Estrellas vs Baja Rotación por margen y popularidad
- Porcionamiento: comparativa teórica vs real para detectar desperdicio o robo hormiga
- RevPASH: ingreso por asiento disponible por hora para optimizar turnos
""",
        "forecasting": "Proyección de food cost y prime cost basado en tendencia de precios de insumos.",
        "alerts": "🔴 Prime Cost > 65% | 🔴 Variación porcionamiento > 10% | 🟠 Platos con margen < 20%",
    },

    "transporte": {
        "kpis": ["CPK", "Km Vacío %", "Costo Mantenimiento/Unidad", "Siniestralidad"],
        "analysis": """
ANÁLISIS SECTORIAL — LOGÍSTICA/TRANSPORTE:
- CPK: desglose combustible, neumáticos, mantenimiento, peajes por ruta
- Km Vacío: ineficiencia en retornos y costo de capacidad ociosa
- Flota: ranking por costo preventivo vs correctivo, análisis de renovación (Capex)
- Siniestralidad: impacto en primas y tiempos de inactividad
""",
        "forecasting": "Proyección de CPK y necesidad de renovación de flota.",
        "alerts": "🔴 Km vacío > 30% | 🟠 Mantenimiento correctivo > preventivo | 🟠 Siniestralidad en aumento",
    },

    "inmobiliario": {
        "kpis": ["NOI", "Yield", "Vacancia %", "Capex de Valorización"],
        "analysis": """
ANÁLISIS SECTORIAL — INMOBILIARIO:
- NOI y Yield: rentabilidad neta del portafolio tras gastos operativos
- Vacancia: días promedio desocupación por tipo, costo de mantenimiento de activos vacantes
- Capex: ROI de remodelaciones vs incremento en canon o precio de venta
- Contratos: mapa de riesgo por vencimientos masivos en ventanas cortas
""",
        "forecasting": "Proyección de NOI y riesgo de vacancia por vencimiento de contratos.",
        "alerts": "🔴 Vacancia > 15% | 🟠 NOI en declive 3 meses consecutivos | 🟠 Capex sin ROI positivo",
    },

    "financiero": {
        "kpis": ["NPL Ratio", "NIM", "Costo Adquisición/Depósito", "Eficiencia Operativa"],
        "analysis": """
ANÁLISIS SECTORIAL — SERVICIOS FINANCIEROS/FINTECH:
- Calidad de Activos (NPL): cartera vencida, severidad de pérdida, correlación riesgo-aprobación
- NIM: diferencial captación vs colocación, sensibilidad ante cambios de tasa
- Costo vs Depósito: rentabilidad por cliente vs costo de marketing
- Eficiencia: costo por transacción y automatización de back-office
""",
        "forecasting": "Proyección de NPL y sensibilidad del NIM ante cambios de tasa.",
        "alerts": "🔴 NPL > 5% | 🟠 NIM comprimido | 🟠 CAC > valor depósito primer año",
    },

    "consultoria": {
        "kpis": ["Utilization Rate", "Margen por Engagement", "Pipeline", "Burn Rate"],
        "analysis": """
ANÁLISIS SECTORIAL — CONSULTORÍA:
- Utilization Rate: horas facturables vs totales. Detección de scope creep no facturado
- Rentabilidad por Engagement: margen tras costos directos del equipo asignado
- Pipeline: propuestas activas vs capacidad, tasa de conversión
- Riesgo de Concentración: dependencia de clientes o consultores clave
""",
        "forecasting": "Proyección de facturación basado en pipeline y tasa de cierre histórica.",
        "alerts": "🔴 Utilization < 55% | 🟠 Un cliente > 30% facturación | 🟠 Pipeline < 2 meses",
    },

    "restaurante": {
        "kpis": ["Prime Cost", "Food Cost %", "RevPASH", "Ticket Promedio"],
        "analysis": """
ANÁLISIS SECTORIAL — RESTAURANTE:
- Prime Cost: alimentos + mano de obra. Máximo saludable: 60%
- Ingeniería de Menú: platos estrellas vs baja rotación, margen por plato
- Porcionamiento: teórico vs real, detección de desperdicio
- RevPASH: ingreso por asiento por hora, optimización de turnos
""",
        "forecasting": "Proyección de food cost y rentabilidad por turno.",
        "alerts": "🔴 Prime Cost > 65% | 🔴 Desperdicio > 8% | 🟠 Platos sin margen",
    },

    "manufactura": {
        "kpis": ["OEE", "WIP Value", "Costo No-Calidad", "KWh/Unidad"],
        "analysis": """
ANÁLISIS SECTORIAL — MANUFACTURA:
- OEE: desglose Disponibilidad × Desempeño × Calidad. Costo de paradas no programadas
- WIP: capital atrapado en líneas de producción, cuellos de botella
- No-Calidad: impacto financiero de scrap y re-procesos sobre margen bruto
- Eficiencia Energética: KWh por unidad para detectar desgaste de maquinaria
""",
        "forecasting": "Proyección de OEE y costo de mantenimiento preventivo vs correctivo.",
        "alerts": "🔴 OEE < 65% | 🔴 Scrap > 3% | 🟠 Paradas no programadas en aumento",
    },

    "generic": {
        "kpis": ["Margen Bruto", "Crecimiento", "Concentración", "Liquidez"],
        "analysis": """
ANÁLISIS ESTÁNDAR:
- Rentabilidad: margen bruto y neto por línea de negocio
- Concentración: dependencia de clientes, productos o vendedores clave
- Tendencias: crecimiento interperiodo, estacionalidad
- Anomalías: outliers, valores negativos, desviaciones significativas
""",
        "forecasting": "Proyección lineal basada en tendencia del último período.",
        "alerts": "🔴 Margen negativo | 🟠 Concentración > 40% | 🟠 Tendencia decreciente 3 períodos",
    },
}


def get_protocol(industry_type: str) -> dict:
    """Retorna el protocolo de auditoría para la industria."""
    return PROTOCOLS.get(industry_type, PROTOCOLS["generic"])


def build_sector_prompt(industry_type: str) -> str:
    """Construye SOLO la sección sectorial del prompt."""
    protocol = get_protocol(industry_type)
    return f"""
## PROTOCOLO DE AUDITORÍA — {industry_type.upper()}
KPIs CLAVE: {', '.join(protocol['kpis'])}

{protocol['analysis']}

LÓGICA PREDICTIVA: {protocol['forecasting']}

UMBRALES DE ALERTA: {protocol['alerts']}

SOLO ejecuta este análisis si los datos tienen las columnas necesarias.
Si una métrica no se puede calcular con los datos disponibles, OMÍTELA.
"""

#Y el prompt maestro queda así (limpio, sin los 16 protocolos):

ANALYSIS_PROMPT = """Eres un auditor financiero senior. Analiza estos datos empresariales.

## EMPRESA: {company_name} | DOMINIO: {industry_type}

## MÉTRICAS PRE-CALCULADAS (exactas, NO recalcular)
{calculations}

## PERFIL ESTADÍSTICO
{statistical_profile}

## MUESTRA ({sample_count} filas)
{sample}

## ANOMALÍAS DETECTADAS
{anomalies}

## KPIs PRIORITARIOS DEL CEO: {kpis}
## INSTRUCCIÓN: {user_instruction}

PROTOCOLO:

1. VEREDICTO EJECUTIVO (3 líneas máximo)

2. DASHBOARD DE MÉTRICAS CRÍTICAS
   Tabla con los 5-7 KPIs vitales. USA métricas pre-calculadas.

3. ANÁLISIS POR DIMENSIÓN (solo las que existan en los datos)
   - Por producto/SKU | Por vendedor | Por cliente | Por ciudad | Por período

4. {sector_analysis}

5. ALERTAS Y ANOMALÍAS
   🔴 Crítico | 🟠 Alto | 🟡 Medio

6. SIMULACIÓN Y PROYECCIÓN
   Solo si hay datos suficientes.

7. FUGA DE CAPITAL IDENTIFICADA
   Monto monetario estimado de ineficiencias detectadas.

8. PLAN DE ACCIÓN (máximo 5 decisiones)
   Concretas, con responsable y plazo.

REGLAS:
- [Fuente: {file_name}]
- Si no hay datos para una sección, OMÍTELA.
- Nombres exactos: SKUs, clientes, vendedores, capítulos.
- Tono de junta directiva. Sin suavizar malas noticias.
"""