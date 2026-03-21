# Ada Excel Analysis Skill

## Cuándo usar este skill
Cuando el usuario sube un archivo Excel (.xlsx, .xls) o CSV y pide análisis.
Intent: "excel_analysis" o has_file=true con file_type=excel.

## Pipeline de 3 capas (Smart Data Pipeline)

### Capa 1: Cálculos exactos (Python, sin LLM)
- Métricas deterministas: totales, promedios, variaciones, rankings
- Si `industry_type` está definido, cargar métricas de industria adicionales
- ESTOS DATOS SON EXACTOS. NUNCA recalcularlos con el LLM.

### Capa 2: Perfil estadístico
- Por cada columna numérica: mean, median, std, p25, p75
- Detectar anomalías con IQR (1.5×)
- Identificar outliers altos y bajos

### Capa 3: Sampling inteligente
- Head(15) + Tail(10) + Random(25) + Outliers(≤10) = ~60-100 filas
- Enviar SOLO el sample al LLM, nunca todo el archivo
- El LLM trabaja con las métricas pre-calculadas + sample

## Formato de respuesta

### Estructura obligatoria
1. **BLUF**: Hallazgo más importante primero (1-2 oraciones impactantes)
2. **Métricas clave**: Tabla con los números principales
3. **Análisis**: Interpretación de patrones y tendencias
4. **Alertas**: ⚠️ Riesgos detectados
5. **Recomendaciones**: 💡 Máximo 5, accionables y concretas

### Emojis semánticos
- 📊 Datos y métricas
- ⚠️ Riesgos y alertas
- 💡 Oportunidades y recomendaciones
- ✅ Indicadores positivos
- 🔴 Indicadores críticos
- 📈 Tendencias al alza
- 📉 Tendencias a la baja

## Reglas

1. **BLUF**: hallazgo más importante primero, siempre
2. **NUNCA recalcular** lo que ya calculó Python (las métricas de Capa 1 son exactas)
3. **Máximo 5 recomendaciones** accionables y específicas
4. **Señalar riesgos** con ⚠️ y oportunidades con 💡
5. **Si datos incompletos** o sospechosos, decirlo explícitamente
6. **Citar fuente**: [Fuente: nombre_archivo.xlsx]
7. **Formato colombiano** para cifras: punto=miles, coma=decimales
8. **No asumir** datos que no estén en las métricas calculadas

## Manejo de errores

- Archivo vacío: "El archivo no contiene datos procesables."
- Columnas no reconocidas: "No pude identificar las columnas de [ventas/costos/etc]. ¿Podrías indicarme cuáles son?"
- Datos insuficientes: "Los datos son insuficientes para un análisis confiable (menos de 10 registros)."
