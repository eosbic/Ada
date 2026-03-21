---
tags: [operacion, setup, dev]
---

# Operacion Local

Volver a [[00-Inicio]].

## Arranque

- Guia rapida: [LOCAL_SETUP.md](../LOCAL_SETUP.md)
- Script principal: `../scripts/start_local.ps1`
- Dependencias: `../requirements.txt`

## Comandos frecuentes

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1 -Target api
powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1 -Target bot
powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1 -Target both
```

## Relaciones

- Entender despliegue de componentes: [[10-Arquitectura]]
- Validar rutas y flujos: [[30-Routers-API]]
