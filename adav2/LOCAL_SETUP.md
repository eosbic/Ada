# Ejecucion Local

## Estado actual

- Entorno virtual creado en `venv/`.
- Dependencias instaladas desde `requirements.txt`.
- API validada localmente con `GET /health` -> `{"status":"ok","database":"connected"}`.
- Script de arranque creado: `scripts/start_local.ps1`.

## 1) Activar entorno virtual (opcional)

```powershell
.\venv\Scripts\Activate.ps1
```

## 2) Arrancar API local

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1 -Target api
```

API en:

- `http://127.0.0.1:8000`
- Health check: `http://127.0.0.1:8000/health`

## 3) Arrancar solo bot de Telegram

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1 -Target bot
```

## 4) Arrancar API + bot juntos

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1 -Target both
```

## 5) Cambiar host/puerto

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1 -Target api -BindHost 0.0.0.0 -Port 8001
```

## Notas

- El script carga variables de entorno desde `.env`.
- Si Telegram muestra `Conflict: terminated by other getUpdates request`, ya hay otro bot activo con el mismo token. Debe quedar solo una instancia.
- Este proyecto usa servicios externos (DB, Qdrant, Google APIs, Telegram). Si alguno no responde, algunos endpoints de negocio pueden fallar aunque la API levante.
