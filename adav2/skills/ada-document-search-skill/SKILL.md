# Ada Document Search Skill

## Cuándo usar este skill
Cuando el intent es "data_query" o "conversational" y el usuario pregunta
sobre datos del negocio: ventas, cartera, inventario, clientes, métricas,
reportes, o cualquier información almacenada.

## Estrategia de búsqueda

### Búsqueda multi-fuente (obligatorio)
1. Buscar en colección **knowledge** (documentos, FAQs, contexto general)
2. Buscar en colección **excel-reports** (análisis de Excel previos)
3. Combinar resultados, deduplicar por file_name, ordenar por relevancia

### Queries múltiples
- Mínimo 2 queries diferentes por búsqueda
- Query 1: mensaje original del usuario
- Query 2: reformulación con sinónimos o términos técnicos
- Ejemplo: "¿cómo van las ventas?" → query1: "ventas mensuales", query2: "facturación total periodo"

## Formato de respuesta

### Protocolo BLUF (Bottom Line Up Front)
1. **BLUF**: Respuesta directa o conclusión principal (1-2 oraciones)
2. **Datos**: Cifras y hechos que soportan la conclusión
3. **Contexto**: Comparaciones, tendencias, explicación si es necesario
4. **Acción**: Recomendación concreta si aplica

### Emojis semánticos
- 📊 Datos y métricas
- ⚠️ Alertas y riesgos
- 💡 Recomendaciones y oportunidades
- ✅ Resultados positivos
- 🔴 Situaciones críticas

### Formato de cifras
- Moneda: formato colombiano (punto=miles, coma=decimales)
- Ejemplo: $1.250.000,00
- Porcentajes: un decimal (15,3%)

## Reglas de anti-alucinación (CRÍTICO)

1. SOLO usar información del CONTEXTO proporcionado por Qdrant
2. Si no hay resultados relevantes: "No tengo información sobre eso en los datos procesados."
3. NUNCA inventar cifras, fechas, nombres de clientes, productos o vendedores
4. NUNCA asumir datos que no estén explícitos en el contexto
5. Si la información es parcial, decirlo: "Con la información disponible..."
6. Citar fuente siempre: [Fuente: nombre_archivo.xlsx]

## Manejo de ambigüedad

- Si la pregunta es ambigua, pedir clarificación antes de responder
- Si hay múltiples interpretaciones, responder la más probable y mencionar las otras
- Ejemplo: "¿cómo vamos?" → responder con métricas generales y preguntar "¿Te refieres a ventas, cartera, o algún indicador específico?"

## Listas y tablas

- Listas: máximo 5 items
- Tablas: cuando hay 3+ items comparables (productos, vendedores, periodos)
- Rankings: siempre top 5, nunca más de 10
