"""
Image Protocols — Prompts especializados por tipo de imagen.
Cada tipo tiene un protocolo de análisis diferente.
"""

IMAGE_PROTOCOLS = {
    "documento_fisico": """
Extrae y estructura TODA la información visible:
- Tipo de documento (factura, contrato, recibo, acta, etc.)
- Partes involucradas (emisor, receptor, firmantes)
- Fechas clave (emisión, vencimiento, vigencia)
- Montos, totales, impuestos, descuentos
- Números de referencia, códigos, IDs
- Condiciones o cláusulas relevantes
- Alertas: inconsistencias, fechas vencidas, campos ilegibles
Formato: tabla estructurada + alertas al final.
""",
    "grafica_metricas": """
Interpreta la gráfica con foco ejecutivo:
- Qué métrica(s) muestra y en qué período
- Valor actual vs tendencia (subiendo/bajando/estable)
- Punto más alto y más bajo visible
- Comparación vs objetivo si aparece
- Anomalías o cambios bruscos
- Recomendación accionable basada en la tendencia
KPIs del sector a priorizar: {kpis_sector}
""",
    "pieza_marketing": """
Evalúa esta pieza de marketing:
- Tipo (post, banner, flyer, story, ad, email, etc.)
- Canal aparente (Instagram, LinkedIn, impreso, etc.)
- Mensaje principal y CTA
- Audiencia target inferida
- Elementos de marca (colores, logo, tipografía)
- Fortalezas de la pieza
- 3 sugerencias concretas de mejora
- Copy alternativo sugerido para el CTA
""",
    "persona_equipo": """
Analiza esta imagen de persona(s):
- Descripción del contexto (corporativo, evento, campo, etc.)
- Número de personas y roles aparentes
- Elementos de marca o empresa visibles
- Etiquetas sugeridas para knowledge graph
- Contexto empresarial inferido
- Metadata para almacenamiento: nombre (si se indicó), área, evento
""",
    "producto": """
Analiza este producto:
- Nombre o tipo de producto inferido
- Características visibles (tamaño, color, materiales, estado)
- Calidad aparente y presentación
- Posicionamiento de mercado sugerido (premium, masivo, etc.)
- Oportunidades de mejora en presentación
- Sugerencia de copy para venta
""",
    "captura_pantalla": """
Extrae toda la información de esta captura:
- Plataforma o aplicación identificada
- Datos y métricas visibles (exactos)
- Alertas o errores visibles
- Contexto de la captura
- Acción sugerida basada en lo que muestra
""",
    "general": """
Análisis BLUF completo:
- Qué muestra la imagen
- Información clave extraíble
- Contexto empresarial inferido
- Acciones sugeridas
""",
}

# Mapeo de instrucciones del usuario a tipos de imagen
INSTRUCTION_TYPE_MAP = {
    "documento": "documento_fisico",
    "factura": "documento_fisico",
    "contrato": "documento_fisico",
    "recibo": "documento_fisico",
    "acta": "documento_fisico",
    "grafica": "grafica_metricas",
    "gráfica": "grafica_metricas",
    "metrica": "grafica_metricas",
    "métrica": "grafica_metricas",
    "chart": "grafica_metricas",
    "dashboard": "grafica_metricas",
    "marketing": "pieza_marketing",
    "banner": "pieza_marketing",
    "flyer": "pieza_marketing",
    "post": "pieza_marketing",
    "publicidad": "pieza_marketing",
    "persona": "persona_equipo",
    "equipo": "persona_equipo",
    "team": "persona_equipo",
    "producto": "producto",
    "product": "producto",
    "captura": "captura_pantalla",
    "screenshot": "captura_pantalla",
    "pantalla": "captura_pantalla",
}


def infer_type_from_instruction(instruction: str) -> str:
    """Infiere el tipo de imagen desde la instrucción del usuario."""
    if not instruction:
        return ""
    lower = instruction.lower()
    for keyword, img_type in INSTRUCTION_TYPE_MAP.items():
        if keyword in lower:
            return img_type
    return ""


def build_image_prompt(
    image_type: str,
    industry_type: str,
    custom_prompt: str,
    user_instruction: str,
    file_name: str,
    kpis_sector: str = "",
) -> str:
    """Construye el prompt completo para análisis de imagen."""
    protocol = IMAGE_PROTOCOLS.get(image_type, IMAGE_PROTOCOLS["general"])
    protocol = protocol.format(kpis_sector=kpis_sector or "N/A")

    prompt = (
        "Eres analista senior de documentos visuales. "
        "Entrega respuesta en formato BLUF, luego evidencia visual, luego acciones. "
        "No inventes datos que no aparezcan en la imagen.\n\n"
        f"TIPO DE IMAGEN DETECTADO: {image_type}\n\n"
        f"PROTOCOLO DE ANÁLISIS:\n{protocol}\n\n"
        f"Instrucción del usuario: {user_instruction}\n"
        f"Archivo: {file_name}"
    )

    if custom_prompt:
        prompt += f"\n\nINSTRUCCIONES PERSONALIZADAS DE LA EMPRESA:\n{custom_prompt}"

    return prompt
