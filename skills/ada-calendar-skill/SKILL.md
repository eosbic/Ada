# Ada Calendar Skill

## Cuándo usar este skill
Cuando el intent es "calendar" y el usuario pregunta sobre agenda,
reuniones, citas, horarios, disponibilidad.

## Acciones disponibles

### Lectura (directa, sin aprobación)
- **Listar eventos**: "¿qué tengo hoy?", "mi agenda de la semana"
- **Buscar eventos**: "¿cuándo es la reunión con Carlos?"
- **Ver disponibilidad**: "¿qué horarios tengo libres?"

### Escritura (requiere aprobación del usuario)
- **Crear evento**: "agenda reunión mañana a las 3pm"
- **Modificar evento**: "mueve la reunión al jueves"
- **Eliminar evento**: "cancela la reunión de las 5"

## Formato de respuesta

### Para listar eventos
```
Tus eventos (N):

📅 **Nombre evento** — fecha hora
   📍 Ubicación (si tiene)
   👥 Asistentes (si tiene)
```

### Para crear eventos
```
✅ Evento creado:

📅 **Nombre**
🕐 Inicio — Fin
📍 Ubicación
👥 Asistentes

🔗 Link al evento
```

### Para disponibilidad
```
Tienes N compromisos en los próximos X días:

🔴 fecha hora — Nombre evento

Los demás horarios están disponibles.
```

## Reglas

1. Timezone SIEMPRE America/Bogota
2. Fechas en formato legible: "Lunes 10 de marzo, 3:00 PM"
3. Si el usuario dice "mañana" o "la próxima semana", calcular fecha real
4. Para crear eventos: SIEMPRE confirmar antes de ejecutar
5. Duración default: 1 hora si no especifica
6. Si no hay eventos: responder positivamente "Agenda libre 🎉"
7. Máximo 10 eventos en lista, si hay más decir "y N más..."

## Manejo de conflictos
- Si hay choque de horario al crear: "⚠️ Ya tienes [evento] a esa hora. ¿Creo de todas formas?"
- Si el usuario pide cancelar y hay varios resultados: "Encontré N eventos. ¿Cuál cancelo?"
