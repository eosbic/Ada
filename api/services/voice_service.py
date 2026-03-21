"""
Voice Service — STT (Whisper) + TTS (ElevenLabs).
Referencia: ADA_MIGRACION_V5_SECCIONES_10-15.md §11

STT: OpenAI Whisper API (usa GEMINI_API_KEY no necesita OpenAI key)
TTS: ElevenLabs API
"""

import os
import io
import httpx


ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel (default)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


async def speech_to_text(audio_bytes: bytes, filename: str = "audio.ogg") -> str:
    """Transcribe audio a texto usando Gemini."""
    try:
        from google import genai
        import tempfile

        client = genai.Client(api_key=GEMINI_API_KEY)

        # Guardar audio temporal
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name

        # Subir archivo
        uploaded = client.files.upload(file=temp_path, config={"mime_type": "audio/ogg"})

        if not uploaded:
            raise Exception("No se pudo subir el archivo")

        # Transcribir
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                "Transcribe este audio en español. Responde SOLO con la transcripción exacta, sin explicación ni comillas.",
                uploaded,
            ],
        )

        os.unlink(temp_path)

        transcript = response.text.strip()
        print(f"STT: '{transcript[:100]}'")
        return transcript

    except Exception as e:
        print(f"ERROR STT: {e}")
        import traceback
        traceback.print_exc()
        return "[No se pudo transcribir el audio]"


async def _whisper_fallback(audio_bytes: bytes, filename: str) -> str:
    """Fallback STT con OpenAI Whisper API."""
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        return "[No se pudo transcribir el audio]"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {openai_key}"},
                files={"file": (filename, audio_bytes, "audio/ogg")},
                data={"model": "whisper-1", "language": "es"},
            )
        result = resp.json()
        return result.get("text", "[Error transcribiendo]")
    except Exception as e:
        print(f"ERROR Whisper fallback: {e}")
        return "[No se pudo transcribir el audio]"


async def text_to_speech(text: str) -> bytes | None:
    """Convierte texto a audio usando ElevenLabs."""

    if not ELEVENLABS_API_KEY:
        print("WARNING: ELEVENLABS_API_KEY no configurada")
        return None

    # Limpiar texto para voz (sin markdown, emojis, etc)
    clean_text = _clean_for_speech(text)

    if not clean_text:
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "text": clean_text[:500],  # Limitar para no gastar mucho
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                        "style": 0.3,
                    },
                },
            )

        if resp.status_code == 200:
            print(f"TTS: {len(resp.content)} bytes generados")
            return resp.content
        else:
            print(f"ERROR TTS ElevenLabs: {resp.status_code} {resp.text[:200]}")
            return None

    except Exception as e:
        print(f"ERROR TTS: {e}")
        return None


def _clean_for_speech(text: str) -> str:
    """Limpia texto para que suene natural hablado."""
    import re

    # Quitar markdown
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # **bold**
    text = re.sub(r'\*(.+?)\*', r'\1', text)       # *italic*
    text = re.sub(r'#{1,6}\s', '', text)            # ## headers
    text = re.sub(r'\[Fuente:.*?\]', '', text)      # [Fuente: ...]

    # Quitar emojis comunes
    emojis = ['📊', '⚠️', '💡', '✅', '🔴', '📈', '📉', '📅', '📧', '✉️',
              '🤖', '🏢', '💼', '📦', '📍', '👥', '📋', '💵', '👤', '🎙️',
              '🔍', '💰', '🎉', '❌', '⏳', '⏰', '👋']
    for e in emojis:
        text = text.replace(e, '')

    # Quitar bullets
    text = re.sub(r'^[-•]\s', '', text, flags=re.MULTILINE)

    # Limpiar espacios múltiples
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'  +', ' ', text)

    return text.strip()