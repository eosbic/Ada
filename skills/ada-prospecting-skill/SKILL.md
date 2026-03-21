# Ada Prospecting Skill

## Cuándo usar este skill
Cuando el intent es "prospecting" y el usuario quiere:
- Perfilar un prospecto o cliente antes de una reunión
- Preparar estrategia comercial
- Buscar información de una empresa o contacto
- Hacer seguimiento a oportunidades de venta

## Flujo de perfilamiento

### Paso 1: Recopilar información
Buscar en memoria (Qdrant) todo lo que Ada sabe del prospecto:
- Conversaciones previas
- Emails intercambiados
- Análisis de datos donde aparece
- Notas guardadas

### Paso 2: Generar perfil comercial
Con la información disponible, generar:
1. **Resumen del prospecto** (empresa, sector, tamaño estimado)
2. **Historial de relación** (contactos previos, compras, interacciones)
3. **Estado actual** (activo, inactivo, lead frío/caliente)
4. **Oportunidad estimada** (qué podría comprar/contratar)

### Paso 3: Estrategia de acercamiento
3 recomendaciones concretas y accionables:
- Qué decir en la primera frase
- Qué ofrecer
- Qué evitar

## Formato de respuesta

```
## 📋 Perfil: [Nombre del prospecto/empresa]

**BLUF**: [Conclusión en 1-2 oraciones]

### Datos conocidos
- Empresa: ...
- Sector: ...
- Contacto: ...
- Historial: ...

### Estado de la relación
[Activo/Inactivo/Nuevo] — última interacción: [fecha si hay]

### 💡 Estrategia de acercamiento
1. [Acción concreta 1]
2. [Acción concreta 2]
3. [Acción concreta 3]

### ❓ Preguntas clave para la reunión
1. [Pregunta descubrimiento]
2. [Pregunta dolor/necesidad]
3. [Pregunta siguiente paso]
```

## Reglas

1. NUNCA inventar datos del prospecto — si no hay info, decirlo
2. Si hay datos parciales, trabajar con lo que hay y decir qué falta
3. Enfoque práctico: todo debe ser accionable
4. Adaptar estrategia al contexto colombiano B2B
5. Si el prospecto es un cliente existente, enfocarse en upselling
6. Si es prospecto nuevo, enfocarse en descubrimiento
7. Guardar el perfil en memoria para futuras consultas

## Señales de oportunidad
- 💰 Alta: "Han preguntado precio", "Pidieron cotización", "Segunda reunión"
- 📊 Media: "Mostraron interés", "Respondieron email", "Conexión en evento"
- ❄️ Baja: "Sin respuesta", "Solo explorando", "Primer contacto"

## Contexto colombiano B2B
- Relación personal importa más que en otros mercados
- Primer acercamiento: referencia mutua > llamada fría
- Seguimiento: WhatsApp es más efectivo que email para cerrar
- Horarios: no contactar antes de 8am ni después de 6pm
- Lenguaje: profesional pero cercano, tutear si el otro tutea
