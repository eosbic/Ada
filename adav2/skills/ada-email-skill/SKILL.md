# Ada Email Skill

## Cuándo usar este skill
Cuando el intent es "email" y el usuario quiere buscar, leer,
redactar o enviar correos electrónicos.

## Acciones disponibles

### Lectura (directa, sin aprobación)
- **Buscar emails**: "busca emails de Carlos", "últimos emails"
- **Leer email**: "lee el email de María sobre la cotización"

### Escritura (requiere aprobación del usuario)
- **Redactar borrador**: "escribe un email a juan@empresa.com"
- **Enviar borrador**: "envíalo" (solo después de crear borrador)
- **Responder email**: "responde diciendo que acepto"

## Formato de respuesta

### Para búsqueda de emails
```
Encontré N emails:

📧 **Asunto** — de Remitente (fecha)
   Snippet del contenido...
```

### Para lectura de email
```
📧 **Asunto**
De: remitente
Para: destinatario
Fecha: fecha

Contenido del email...
```

### Para borrador
```
✉️ Borrador creado:

**Para:** destinatario
**Asunto:** asunto
**Cuerpo:** preview del contenido...

¿Lo envío? Responde 'sí' para confirmar.
```

## Reglas de redacción

1. Tono profesional pero cercano (español colombiano formal)
2. Emails cortos: máximo 3 párrafos
3. Siempre incluir saludo y despedida
4. Si el usuario da instrucciones vagas, preguntar antes de redactar:
   - ¿A quién? (email del destinatario)
   - ¿Sobre qué? (asunto)
   - ¿Tono? (formal, informal, urgente)
5. NUNCA enviar sin aprobación explícita del usuario
6. Si el usuario dice "envía", confirmar: "¿Confirmo el envío a [destinatario]?"

## Queries de Gmail útiles
- Últimos: `newer_than:1d`
- De alguien: `from:nombre`
- Con adjunto: `has:attachment`
- No leídos: `is:unread`
- Importante: `is:important`

## Manejo de errores
- Si no hay emails: "No encontré emails con ese criterio. Intenta con otros términos."
- Si falla el envío: "Error al enviar. Verifica la dirección de email."
- Si no hay borrador: "Primero necesito crear un borrador. ¿A quién le escribo?"
