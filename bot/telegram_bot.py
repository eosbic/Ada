"""
Telegram Bot - flujo multimodal explicito (texto, voz, documentos e imagenes).
"""

import os
import traceback
import httpx
import asyncio
from pathlib import Path
from datetime import datetime
import re

from telegram import Update
from telegram.error import Conflict
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)

API_URL = os.getenv("ADA_API_URL", "http://localhost:8000")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_API")
TIMEOUT_CHAT = 60
TIMEOUT_UPLOAD = 180
AUTO_SAVE_MD = os.getenv("TELEGRAM_AUTO_SAVE_MD", "true").strip().lower() in {"1", "true", "yes", "on"}
AUTO_INGEST_MD = os.getenv("TELEGRAM_AUTO_INGEST_MD", "true").strip().lower() in {"1", "true", "yes", "on"}
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_MD_DIR = "boveda/Adaobsidian/Inbox" if (_REPO_ROOT / "boveda" / "Adaobsidian").exists() else "obsidian-vault/Inbox"
MD_NOTE_DIR = os.getenv("TELEGRAM_MD_DIR", _DEFAULT_MD_DIR)
INGEST_ONLY_MEMORY_CANDIDATES = os.getenv("TELEGRAM_INGEST_ONLY_MEMORY_CANDIDATES", "true").strip().lower() in {"1", "true", "yes", "on"}

_PENDING_LINK = set()
_PENDING_IMAGES = {}  # telegram_id -> {"bytes": bytes, "user_data": dict, "timestamp": float}

IMAGE_MENU_OPTIONS = {
    "1": "Analizar documento / factura / contrato",
    "2": "Interpretar gráfica o métricas",
    "3": "Evaluar como pieza de marketing",
    "4": "Etiquetar persona o equipo",
    "5": "Describir producto",
    "6": "Análisis general",
}

IMAGE_MENU_TEXT = (
    "¿Qué quieres que haga con esta imagen?\n\n"
    "1️⃣ Analizar documento / factura / contrato\n"
    "2️⃣ Interpretar gráfica o métricas\n"
    "3️⃣ Evaluar como pieza de marketing\n"
    "4️⃣ Etiquetar persona o equipo\n"
    "5️⃣ Describir producto\n"
    "6️⃣ Análisis general\n\n"
    "Responde con el número o escribe tu propia instrucción."
)


def _slugify(text: str, max_len: int = 48) -> str:
    value = (text or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    if not value:
        return "mensaje"
    return value[:max_len]


def _build_markdown_note(telegram_id: str, message: str) -> tuple[str, bytes]:
    now = datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    snippet = _slugify(message)
    file_name = f"tg_{telegram_id}_{stamp}_{snippet}.md"
    markdown = (
        "---\n"
        "tags: [telegram, captura, segundo-cerebro]\n"
        f"telegram_id: \"{telegram_id}\"\n"
        f"created_at: \"{now.isoformat(timespec='seconds')}\"\n"
        "source: telegram\n"
        "---\n\n"
        "# Mensaje Telegram\n\n"
        f"{message.strip()}\n\n"
        "## Enlaces\n\n"
        "- [[00-Inicio]]\n"
    )
    return file_name, markdown.encode("utf-8")


def _is_memory_candidate(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text or len(text) < 8:
        return False

    query_markers = [
        "?",
        "busca ",
        "busca en ",
        "dime ",
        "responde ",
        "puedes ",
        "cual ",
        "como ",
        "que ",
        "no inventes",
    ]
    if any(m in text for m in query_markers):
        return False

    fact_markers = [
        "me llamo ",
        "soy ",
        "mi ",
        "recuerda que ",
        "mi color favorito",
        "mi codigo ",
        "obs_",
    ]
    return any(m in text for m in fact_markers)


def _save_markdown_locally(file_name: str, file_bytes: bytes) -> str:
    note_dir = Path(MD_NOTE_DIR)
    if not note_dir.is_absolute():
        note_dir = _REPO_ROOT / note_dir
    note_dir.mkdir(parents=True, exist_ok=True)
    out_path = note_dir / file_name
    out_path.write_bytes(file_bytes)
    return str(out_path)


async def _ingest_markdown_note(file_name: str, file_bytes: bytes, empresa_id: str) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_UPLOAD) as client:
            resp = await client.post(
                f"{API_URL}/files/upload",
                files={"file": (file_name, file_bytes, "text/markdown")},
                data={
                    "empresa_id": empresa_id,
                    "instruction": "Ingesta automatica de nota de conversacion de Telegram.",
                    "industry_type": "generic",
                },
            )
        data = resp.json()
        if resp.status_code >= 300:
            return False, f"HTTP {resp.status_code}: {data}"
        if isinstance(data, dict) and data.get("error"):
            return False, str(data.get("error"))
        return True, "ok"
    except Exception as e:
        return False, str(e)


def _wants_audio_reply(message: str) -> bool:
    m = (message or "").lower()
    return any(k in m for k in ["responde en audio", "en audio", "#audio", "/audio"])


def _split_text(text: str, max_len: int = 3900) -> list[str]:
    content = (text or "").strip()
    if not content:
        return [""]
    chunks = []
    while len(content) > max_len:
        cut = content.rfind("\n", 0, max_len)
        if cut < max_len * 0.6:
            cut = max_len
        chunks.append(content[:cut].strip())
        content = content[cut:].strip()
    if content:
        chunks.append(content)
    return chunks


def _sanitize_text(text: str) -> str:
    value = (text or "").replace("\x00", "")
    cleaned_chars = []
    for ch in value:
        code = ord(ch)
        if ch in {"\n", "\r", "\t"} or code >= 32:
            cleaned_chars.append(ch)
    return "".join(cleaned_chars)


def _fix_markdown_for_telegram(text: str) -> str:
    """Arregla Markdown para que Telegram lo acepte."""
    result = text

    # 1. Proteger URLs
    urls = re.findall(r'https?://[^\s\)]+', result)
    url_placeholders = {}
    for i, url in enumerate(urls):
        placeholder = f"__URL_PLACEHOLDER_{i}__"
        url_placeholders[placeholder] = url
        result = result.replace(url, placeholder)

    # 2. Proteger emails
    emails = re.findall(r'[\w.-]+@[\w.-]+\.\w+', result)
    email_placeholders = {}
    for i, email in enumerate(emails):
        placeholder = f"__EMAIL_PLACEHOLDER_{i}__"
        email_placeholders[placeholder] = email
        result = result.replace(email, placeholder)

    # 3. Verificar que ** estén balanceados
    count_bold = result.count("**")
    if count_bold % 2 != 0:
        last_pos = result.rfind("**")
        result = result[:last_pos] + result[last_pos+2:]

    # 4. Reemplazar * sueltos (no **) con • para evitar cursiva rota
    result = re.sub(r'(?<!\*)\*(?!\*)', '•', result)

    # 5. Restaurar URLs y emails
    for placeholder, url in url_placeholders.items():
        result = result.replace(placeholder, url)
    for placeholder, email in email_placeholders.items():
        result = result.replace(placeholder, email)

    # 6. Bullets markdown → bullet unicode
    result = re.sub(r'^(\s*)-\s+', r'\1• ', result, flags=re.MULTILINE)

    # 7. Agregar doble salto de línea antes de líneas que empiezan con emoji
    import unicodedata
    _section_prefixes = (
        "📊", "💰", "📈", "📉", "🏆", "💡", "📅", "👥", "📝", "✉️",
        "📋", "✅", "⚠️", "🔴", "📬", "🎯", "🤖", "🏢", "💼", "📦",
        "📍", "🌐", "🎨", "📧", "💬", "📱", "🖼️", "⛔", "🟢", "🟡",
        "EN RESUMEN", "ADEMÁS", "ALERTAS", "RECOMENDACION",
    )
    lines = result.split("\n")
    spaced = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and i > 0:
            first_char = stripped[0] if stripped else ""
            is_emoji = first_char and unicodedata.category(first_char) == "So"
            starts_with_emoji = is_emoji or any(stripped.startswith(e) for e in _section_prefixes)
            if starts_with_emoji and spaced and spaced[-1].strip() != "":
                spaced.append("")
        spaced.append(line)
    result = "\n".join(spaced)

    return result


async def _send_markdown_safe(message_obj, text: str):
    """Envía mensaje con Markdown. Si falla, envía sin formato."""
    try:
        await message_obj.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        print(f"TELEGRAM BOT: Markdown parse failed ({e}), sending plain text")
        clean = text.replace("**", "").replace("__", "").replace("```", "").replace("`", "")
        try:
            await message_obj.reply_text(clean)
        except Exception as e2:
            print(f"TELEGRAM BOT: Even plain text failed: {e2}")
            await message_obj.reply_text("Error mostrando la respuesta. Intenta de nuevo.")


async def _safe_send_text(update: Update, processing_msg, text: str):
    sanitized = _sanitize_text(text)
    formatted = _fix_markdown_for_telegram(sanitized)
    chunks = _split_text(formatted, max_len=3900)
    first = chunks[0] if chunks else "Sin contenido."

    print(f"TELEGRAM BOT: sending {len(chunks)} chunk(s) with Markdown")
    await _send_markdown_safe(update.message, first)

    for extra in chunks[1:]:
        await _send_markdown_safe(update.message, extra)

    try:
        if processing_msg:
            await processing_msg.delete()
    except Exception:
        pass


async def on_bot_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    err = context.error
    if isinstance(err, Conflict):
        print(
            "ERROR: Conflicto de Telegram (409). "
            "Hay otra instancia del bot usando este mismo token. "
            "Deteniendo esta instancia."
        )
        await context.application.stop()
        return

    print(f"ERROR Telegram no manejado: {err}")
    traceback.print_exception(type(err), err, err.__traceback__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = str(update.effective_user.id)
    linked = await _check_linked(telegram_id)
    if linked:
        await update.message.reply_text("Hola de nuevo. Escribeme lo que necesites.")
    else:
        _PENDING_LINK.add(telegram_id)
        await update.message.reply_text(
            "Hola. Soy Ada.\n\n"
            "Para empezar necesito saber quien eres.\n"
            "Escribe tu email registrado:"
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = str(update.effective_user.id)
    message = update.message.text or ""
    print(f"TELEGRAM BOT: msg from {telegram_id} -> {message[:80]}")

    if telegram_id in _PENDING_LINK:
        await _handle_link_email(update, telegram_id, message.strip())
        return

    # Verificar si hay imagen pendiente esperando instrucción
    import time
    if telegram_id in _PENDING_IMAGES:
        pending = _PENDING_IMAGES[telegram_id]
        elapsed = time.time() - pending["timestamp"]
        if elapsed < 300:  # 5 minutos
            # Si estamos esperando info de persona (segundo nivel de opción 4)
            if pending.get("awaiting_person_info"):
                instruction = f"Etiquetar persona: {message.strip()}. Incluye nombre, cargo, área en el knowledge graph y en los metadatos del reporte."
                del _PENDING_IMAGES[telegram_id]
                await _send_file_to_upload(update, pending["user_data"], "telegram_photo.jpg", pending["bytes"], instruction)
                return
            # Primer nivel: selección del menú
            choice = message.strip()
            if choice == "4":
                # Opción 4: pedir nombre y cargo antes de procesar
                pending["awaiting_person_info"] = True
                pending["timestamp"] = time.time()
                await update.message.reply_text("¿Cuál es el nombre completo de esta persona y su cargo o área?\n(Ej: Carlos Satizabal, Director de Educación)")
                return
            instruction = IMAGE_MENU_OPTIONS.get(choice, choice)
            del _PENDING_IMAGES[telegram_id]
            await _send_file_to_upload(update, pending["user_data"], "telegram_photo.jpg", pending["bytes"], instruction)
            return
        else:
            del _PENDING_IMAGES[telegram_id]

    user_data = await _get_user_data(telegram_id)
    if not user_data:
        _PENDING_LINK.add(telegram_id)
        await update.message.reply_text("No te tengo registrado. Escribe tu email para vincularte:")
        return

    processing_msg = await update.message.reply_text("Procesando...")

    try:
        note_file_name = ""
        note_bytes = b""

        if AUTO_SAVE_MD or AUTO_INGEST_MD:
            note_file_name, note_bytes = _build_markdown_note(telegram_id, message)

        if AUTO_SAVE_MD and note_file_name and note_bytes:
            note_path = _save_markdown_locally(note_file_name, note_bytes)
            print(f"TELEGRAM BOT: note saved -> {note_path}")

        token = user_data.get("access_token", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        async with httpx.AsyncClient(timeout=TIMEOUT_CHAT) as client:
            resp = await client.post(
                f"{API_URL}/chat/chat",
                json={
                    "message": message,
                    "empresa_id": user_data["empresa_id"],
                    "user_id": user_data["user_id"],
                    "source": "telegram",
                },
                headers=headers,
            )

        data = resp.json()
        response_text = data.get("response", "No pude procesar tu mensaje.")
        output_mode = data.get("output_mode", "")
        await _safe_send_text(update, processing_msg, response_text)

        attachments = data.get("attachments")
        if not isinstance(attachments, list):
            attachments = []

        single_attachment = data.get("attachment") or {}
        if isinstance(single_attachment, dict) and single_attachment:
            duplicated = any(
                (a.get("type") == single_attachment.get("type") and a.get("file_path") == single_attachment.get("file_path"))
                for a in attachments if isinstance(a, dict)
            )
            if not duplicated:
                attachments.append(single_attachment)

        for attachment in attachments[:4]:
            if not isinstance(attachment, dict):
                continue
            file_path = attachment.get("file_path")
            file_name = attachment.get("file_name") or "archivo"
            artifact_type = attachment.get("type")

            if not file_path or not os.path.exists(file_path):
                continue

            if artifact_type == "pdf":
                with open(file_path, "rb") as pdf_file:
                    await update.message.reply_document(
                        document=pdf_file,
                        filename=file_name,
                        caption="PDF generado automaticamente.",
                    )
            elif artifact_type in {"chart", "image"}:
                with open(file_path, "rb") as img_file:
                    await update.message.reply_photo(
                        photo=img_file,
                        caption="Grafico generado automaticamente.",
                    )

        # salida multimodal centralizada
        wants_voice = (output_mode == "voice") or _wants_audio_reply(message)
        if wants_voice:
            from api.services.voice_service import text_to_speech

            audio_response = await text_to_speech(response_text)
            if audio_response:
                await update.message.reply_voice(voice=audio_response)

        should_ingest = AUTO_INGEST_MD
        if should_ingest and INGEST_ONLY_MEMORY_CANDIDATES:
            should_ingest = _is_memory_candidate(message)

        # Ingesta posterior a la respuesta para no contaminar la busqueda del mismo turno.
        if should_ingest and note_file_name and note_bytes:
            ok, detail = await _ingest_markdown_note(
                file_name=note_file_name,
                file_bytes=note_bytes,
                empresa_id=user_data["empresa_id"],
            )
            if ok:
                print(f"TELEGRAM BOT: note ingested -> {note_file_name}")
            else:
                print(f"TELEGRAM BOT: note ingest warning -> {detail}")
        elif AUTO_INGEST_MD and note_file_name:
            print(f"TELEGRAM BOT: note not ingested (query/non-memory) -> {note_file_name}")

    except httpx.TimeoutException:
        await _safe_send_text(update, processing_msg, "La respuesta tomo demasiado tiempo. Intenta de nuevo.")
    except Exception as e:
        print(f"ERROR Telegram text: {e}")
        traceback.print_exc()
        await _safe_send_text(update, processing_msg, "Error procesando tu mensaje.")


async def _handle_link_email(update: Update, telegram_id: str, email: str):
    if "@" not in email or "." not in email:
        await update.message.reply_text("Email no valido. Intenta de nuevo:")
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{API_URL}/auth/link-telegram",
                json={"email": email, "telegram_id": telegram_id},
            )

        data = resp.json()
        if resp.status_code == 200:
            _PENDING_LINK.discard(telegram_id)
            await update.message.reply_text(
                f"Listo, {data.get('nombre', '')}. Tu Telegram ya esta vinculado."
            )
        elif resp.status_code == 404:
            await update.message.reply_text(
                f"No encontre '{email}' registrado.\n"
                "Pidele a tu administrador que te registre o escribe otro email:"
            )
        else:
            await update.message.reply_text(f"Error: {data.get('detail', 'desconocido')}")

    except Exception as e:
        print(f"ERROR link email: {e}")
        await update.message.reply_text("Error de conexion. Intenta de nuevo.")


async def _send_file_to_upload(update: Update, user_data: dict, file_name: str, file_bytes: bytes, instruction: str = ""):
    processing_msg = await update.message.reply_text(f"Analizando {file_name}...")

    try:
        token = user_data.get("access_token", "")
        async with httpx.AsyncClient(timeout=TIMEOUT_UPLOAD) as client:
            resp = await client.post(
                f"{API_URL}/files/upload",
                files={"file": (file_name, file_bytes)},
                data={
                    "empresa_id": user_data["empresa_id"],
                    "instruction": instruction or "Analisis general",
                    "industry_type": "generic",
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        data = resp.json()
        if "error" in data:
            await processing_msg.edit_text(f"Error: {data['error']}")
            return

        response_text = data.get("response", "Analisis completado.")
        report_id = data.get("report_id")

        if report_id:
            visual_link = f"\n\n📊 Ver reporte visual: https://backend-ada.duckdns.org/api/v1/reports/{report_id}/visual"
            max_len = 4000 - len(visual_link)
            response_text = response_text[:max_len] + visual_link
        else:
            response_text = response_text[:4000]

        await processing_msg.edit_text(response_text)

        alerts = data.get("alerts", [])
        if alerts:
            alert_text = "\n".join([a.get("message", "") for a in alerts[:5]])
            if alert_text.strip():
                await update.message.reply_text(f"Alertas:\n\n{alert_text[:4000]}")

    except httpx.TimeoutException:
        await processing_msg.edit_text("El analisis tomo demasiado tiempo.")
    except Exception as e:
        print(f"ERROR upload flow: {e}")
        traceback.print_exc()
        await processing_msg.edit_text("Error analizando archivo.")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = str(update.effective_user.id)
    user_data = await _get_user_data(telegram_id)
    if not user_data:
        await update.message.reply_text("Primero vinculate con /start")
        return

    doc = update.message.document
    if not doc:
        return

    file_name = doc.file_name or "archivo"
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

    allowed = {"xlsx", "xls", "csv", "pdf", "txt", "md", "markdown", "doc", "docx", "png", "jpg", "jpeg", "webp", "bmp"}
    if ext not in allowed:
        await update.message.reply_text(f"Formato no soportado: .{ext}")
        return

    if doc.file_size and doc.file_size > 25 * 1024 * 1024:
        await update.message.reply_text("Tamano maximo 25MB.")
        return

    file = await doc.get_file()
    file_bytes = bytes(await file.download_as_bytearray())
    instruction = update.message.caption or ""
    await _send_file_to_upload(update, user_data, file_name, file_bytes, instruction)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import time

    telegram_id = str(update.effective_user.id)
    user_data = await _get_user_data(telegram_id)
    if not user_data:
        await update.message.reply_text("Primero vinculate con /start")
        return

    if not update.message.photo:
        return

    photo = update.message.photo[-1]
    f = await photo.get_file()
    img_bytes = bytes(await f.download_as_bytearray())
    instruction = (update.message.caption or "").strip()

    if instruction:
        # Con caption: procesar directamente
        await _send_file_to_upload(update, user_data, "telegram_photo.jpg", img_bytes, instruction)
    else:
        # Sin caption: guardar imagen y mostrar menú
        _PENDING_IMAGES[telegram_id] = {
            "bytes": img_bytes,
            "user_data": user_data,
            "timestamp": time.time(),
        }
        await update.message.reply_text(IMAGE_MENU_TEXT)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = str(update.effective_user.id)
    user_data = await _get_user_data(telegram_id)
    if not user_data:
        await update.message.reply_text("Primero vinculate con /start")
        return

    processing_msg = await update.message.reply_text("Escuchando...")

    try:
        voice = update.message.voice or update.message.audio
        file = await voice.get_file()
        audio_bytes = bytes(await file.download_as_bytearray())

        await processing_msg.edit_text("Transcribiendo...")
        from api.services.voice_service import speech_to_text, text_to_speech

        transcript = await speech_to_text(audio_bytes)
        if not transcript or transcript.startswith("["):
            await processing_msg.edit_text("No pude entender el audio. Intenta de nuevo.")
            return

        await processing_msg.edit_text("Procesando...")

        token = user_data.get("access_token", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        async with httpx.AsyncClient(timeout=TIMEOUT_CHAT) as client:
            resp = await client.post(
                f"{API_URL}/chat/chat",
                json={
                    "message": transcript,
                    "empresa_id": user_data["empresa_id"],
                    "user_id": user_data["user_id"],
                    "source": "telegram_voice",
                },
                headers=headers,
            )

        data = resp.json()
        response_text = data.get("response", "No pude procesar tu mensaje.")
        output_mode = data.get("output_mode", "voice")
        await _safe_send_text(update, processing_msg, response_text)

        if output_mode == "voice":
            audio_response = await text_to_speech(response_text)
            if audio_response:
                await update.message.reply_voice(voice=audio_response)

    except httpx.TimeoutException:
        await _safe_send_text(update, processing_msg, "La respuesta tomo demasiado tiempo.")
    except Exception as e:
        print(f"ERROR Telegram voice: {e}")
        traceback.print_exc()
        await _safe_send_text(update, processing_msg, "Error procesando audio.")


async def _check_linked(telegram_id: str):
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            resp = await c.get(f"{API_URL}/auth/telegram/{telegram_id}")
        return resp.status_code == 200
    except Exception:
        return False


async def _get_user_data(telegram_id: str):
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            resp = await c.get(f"{API_URL}/auth/telegram/{telegram_id}")
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


async def _validate_api_target(max_attempts: int = 20, wait_seconds: float = 1.0) -> bool:
    """
    Verifica que el bot este apuntando al backend Ada correcto.
    Evita contestar con una API de otro proyecto por error de puerto/env.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                health = await client.get(f"{API_URL}/health")
                if health.status_code != 200:
                    raise RuntimeError(f"health={health.status_code}")

                openapi = await client.get(f"{API_URL}/openapi.json")
                if openapi.status_code != 200:
                    raise RuntimeError(f"openapi={openapi.status_code}")

                data = openapi.json()
                title = str(data.get("info", {}).get("title", ""))
                if "Ada V5.0" not in title:
                    print(
                        "ERROR: El bot apunta a una API distinta. "
                        f"API_URL={API_URL}, title='{title}'"
                    )
                    return False

            return True
        except Exception as e:
            if attempt == max_attempts:
                print(f"ERROR validando API_URL {API_URL}: {e}")
                return False
            await asyncio.sleep(wait_seconds)


def main():
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_API no configurado")
        return

    print(f"TELEGRAM BOT: Iniciando... API_URL={API_URL}")
    if not asyncio.run(_validate_api_target()):
        print("TELEGRAM BOT: cancelado por API_URL invalida.")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_error_handler(on_bot_error)

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    print("TELEGRAM BOT: Escuchando...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
