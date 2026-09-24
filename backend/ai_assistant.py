#ai_assistant.py — Asistente de IA conversacional para mastering (estilo LANDR AI).



from __future__ import annotations

import asyncio
import os
import json
import logging
import re
import threading
from typing import Optional, Dict, Tuple

import httpx

logger = logging.getLogger(__name__)

# Carga opcional de un archivo .env (backend/.env) si python-dotenv está instalado.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Acepta GEMINI_API_KEY o GOOGLE_API_KEY (los mismos nombres que usan los SDKs oficiales).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
AI_MODEL = os.environ.get("AI_ASSISTANT_MODEL", "gemini-2.5-flash")
MAX_HISTORY_MESSAGES = 20  # últimos N mensajes de la conversación que se reenvían

# Se habla directo con la API REST de Gemini (sin SDK oficial): tanto
# google-genai como google-generativeai piden Python >=3.9 y no instalan en
# Windows 7 / Python 3.8. `requests` no tiene ese piso ni dependencias con
# Rust, así que evita también el problema de "cryptography" con Windows 7.
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

_client = None
_client_error: Optional[str] = None
_client_lock = threading.Lock()


def _get_client():
    """Valida (de forma perezosa) que haya una API key configurada y cachea el
    resultado. Ya no instancia ningún SDK: las llamadas van por REST directo,
    ver `_gemini_generate_content`."""
    global _client, _client_error
    with _client_lock:
        if _client is not None:
            return _client
        if _client_error is not None:
            return None
        if not GEMINI_API_KEY:
            _client_error = (
                "Falta configurar la variable de entorno GEMINI_API_KEY en el backend."
            )
            logger.warning(_client_error)
            return None
        _client = True
        return _client


def is_available() -> bool:
    return _get_client() is not None


async def _gemini_generate_content(system_prompt: str, contents: list,
                                    max_output_tokens: int = 2048,
                                    thinking_budget: Optional[int] = None,
                                    temperature: Optional[float] = None,
                                    max_retries: int = 3) -> Optional[str]:
    """Llama directo al endpoint REST generateContent de Gemini (sin SDK) y \
    devuelve el texto crudo de la respuesta. `contents` ya viene armado en el \
    formato de la API: [{"role": "user"|"model", "parts": [{"text": ...}]}, ...]. \
    Siempre se pide responseMimeType=application/json, así que el texto devuelto \
    debería ser JSON parseable (ver `_extract_json_object`). Devuelve None si la \
    llamada falla, no hay candidatos (p.ej. bloqueo de safety) o hay error de red.\
    
    Con reintentos automáticos para transient errors (timeout, 5xx, connection issues)."""
    url = f"{GEMINI_API_BASE}/models/{AI_MODEL}:generateContent"
    generation_config = {
        "responseMimeType": "application/json",
        "maxOutputTokens": max_output_tokens,
    }
    if thinking_budget is not None:
        generation_config["thinkingConfig"] = {"thinkingBudget": thinking_budget}
    if temperature is not None:
        generation_config["temperature"] = temperature
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": generation_config,
    }

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45.0)) as client:
                resp = await client.post(url, params={"key": GEMINI_API_KEY}, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as e:
            last_error = e
            if attempt < max_retries:
                wait_time = 2 ** (attempt - 1)  # exponential backoff: 1s, 2s, 4s
                logger.warning(f"Timeout en Gemini (intento {attempt}/{max_retries}). Esperando {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue
            else:
                logger.error(f"Timeout en Gemini después de {max_retries} intentos: {e}")
                return None
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code >= 500:
                if attempt < max_retries:
                    wait_time = 2 ** (attempt - 1)
                    logger.warning(f"Error 5xx en Gemini (intento {attempt}/{max_retries}): {e.response.status_code}. Esperando {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
            logger.error(f"Error llamando a la API REST de Gemini: {e}")
            return None
        except Exception as e:
            logger.error(f"Error inesperado en Gemini: {e}")
            return None

        # Si llegamos acá sin exception, procesamos la respuesta
        break

    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback")
        logger.warning(f"Gemini no devolvió candidatos (posible bloqueo de safety). promptFeedback={feedback}")
        return None
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if "text" in p)
    finish_reason = candidates[0].get("finishReason")
    if not text:
        logger.warning(f"Gemini devolvió una respuesta sin texto (finishReason={finish_reason}).")
        return None
    if finish_reason == "MAX_TOKENS":
        # La respuesta se cortó antes de terminar (típico cuando thinking_budget
        # dinámico/alto se come la mayor parte de maxOutputTokens, que en la API
        # de Gemini es un presupuesto COMPARTIDO entre tokens de pensamiento y
        # texto de salida). El texto parcial casi siempre es JSON inválido —
        # se loguea acá para que quede claro en el log en vez de solo verse
        # como "JSON ilegible" río abajo, sin pista de la causa real.
        logger.warning(
            f"Gemini cortó la respuesta por MAX_TOKENS (maxOutputTokens insuficiente "
            f"para thinking + salida). Texto parcial: {len(text)} chars."
        )
    return text




def get_unavailable_reason() -> str:
    return _client_error or "El asistente de IA no está disponible."


def _fmt(v, unit: str = "", nd: int = 2) -> str:
    if v is None:
        return "sin datos"
    try:
        return f"{round(float(v), nd)}{unit}"
    except (TypeError, ValueError):
        return str(v)


def build_audio_context(analysis: Optional[dict], preset: Optional[str] = None,
                         platform: Optional[str] = None) -> str:
    """Convierte el dict de analyze_audio()/mix_advice() en texto legible para el modelo."""
    if not analysis:
        return "El usuario todavía no subió ningún audio ni corrió un análisis en esta sesión."

    lines = ["Datos técnicos del análisis del track actual del usuario (decenas de métricas ya calculadas):"]

    lines.append("· Loudness / nivel:")
    lines.append(f"    - LUFS integrado: {_fmt(analysis.get('lufs'), ' LUFS')}")
    lines.append(f"    - Pico (sample): {_fmt(analysis.get('peak_db'), ' dBFS')}")
    lines.append(f"    - True peak (inter-sample, 4x oversample): {_fmt(analysis.get('true_peak_db'), ' dBTP')}")
    lines.append(f"    - RMS: {_fmt(analysis.get('rms_db'), ' dBFS')}")
    lines.append(f"    - PLR (true peak - LUFS): {_fmt(analysis.get('plr_db'), ' dB')}")
    st = analysis.get("loudness_short_term") or {}
    if st:
        lines.append(f"    - Loudness de corto plazo (ventanas 3s): máx {_fmt(st.get('max'), ' LUFS')}, "
                      f"mín {_fmt(st.get('min'), ' LUFS')}, p95 {_fmt(st.get('p95'), ' LUFS')}")
    lines.append(f"    - LRA (rango de loudness): {_fmt(analysis.get('lra'), ' LU')}")

    lines.append("· Dinámica:")
    lines.append(f"    - Rango dinámico global (crest factor): {_fmt(analysis.get('dynamic_range_db'), ' dB')}")
    band_dyn = analysis.get("band_dynamics_db") or {}
    if band_dyn:
        lines.append(f"    - Crest factor por banda: graves {_fmt(band_dyn.get('low'), ' dB')}, "
                      f"medios {_fmt(band_dyn.get('mid'), ' dB')}, agudos {_fmt(band_dyn.get('high'), ' dB')}")

    lines.append("· Higiene de señal:")
    lines.append(f"    - DC offset: {_fmt(analysis.get('dc_offset'), '', 5)}")
    lines.append(f"    - Clipping real: {_fmt((analysis.get('clipping_ratio') or 0) * 100, '% de las muestras', 3)}")
    lines.append(f"    - Silencio (<-60dB): {_fmt((analysis.get('silence_ratio') or 0) * 100, '% del track', 2)}")

    lines.append("· Estéreo:")
    lines.append(f"    - Correlación L/R global: {_fmt(analysis.get('stereo_correlation'), '', 3)}")
    band_st = analysis.get("band_stereo_correlation") or {}
    if band_st:
        lines.append(f"    - Correlación L/R por banda: graves {_fmt(band_st.get('low'), '', 3)}, "
                      f"medios {_fmt(band_st.get('mid'), '', 3)}, agudos {_fmt(band_st.get('high'), '', 3)}")
    lines.append(f"    - Compatibilidad mono (pérdida al sumar L+R): {_fmt(analysis.get('mono_compatibility_db'), ' dB')}")

    lines.append("· Timbre / forma espectral:")
    lines.append(f"    - Centroid espectral: {_fmt(analysis.get('spectral_centroid_hz'), ' Hz', 0)}")
    lines.append(f"    - Rolloff (85% energía): {_fmt(analysis.get('spectral_rolloff_hz'), ' Hz', 0)}")
    lines.append(f"    - Flatness espectral (0=tonal, 1=ruidoso): {_fmt(analysis.get('spectral_flatness'), '', 4)}")
    lines.append(f"    - Zero-crossing rate: {_fmt(analysis.get('zero_crossing_rate'), '', 4)}")

    lines.append("· Ritmo:")
    lines.append(f"    - Densidad de transientes: {_fmt(analysis.get('transient_density'), ' onsets/seg', 2)}")

    spectrum = analysis.get("spectrum") or {}
    if spectrum:
        band_names = {
            "sub_bass": "Sub-bajos (20-80Hz)", "bass": "Bajos (80-250Hz)",
            "low_mid": "Medios-bajos (250-500Hz)", "mid": "Medios (500-2kHz)",
            "upper_mid": "Medios-altos (2-4kHz)", "presence": "Presencia (4-8kHz)",
            "air": "Aire (8-20kHz)",
        }
        lines.append("· Balance espectral (energía relativa en dB por banda):")
        for key, label in band_names.items():
            if key in spectrum:
                lines.append(f"    · {label}: {_fmt(spectrum[key], ' dB')}")

    advice = analysis.get("mix_advice")
    if isinstance(advice, dict):
        issues = advice.get("issues") or []
        tips = advice.get("tips") or []
        score = advice.get("score")
        if score is not None:
            lines.append(f"- Score de calidad del motor de reglas interno: {score}/100")
        if issues:
            lines.append("- Problemas detectados automáticamente:")
            for i in issues:
                lines.append(f"    · {i}")
        if tips:
            lines.append("- Sugerencias automáticas del motor de reglas:")
            for t in tips:
                lines.append(f"    · {t}")

    if preset:
        lines.append(f"- Preset de mastering seleccionado por el usuario: {preset}")
    if platform:
        lines.append(f"- Plataforma/target de loudness elegido: {platform}")

    return "\n".join(lines)


def build_current_params_context(current_params: Optional[dict]) -> str:
    """Convierte los parámetros actuales de la cadena de mastering en texto legible para el modelo."""
    if not current_params or not isinstance(current_params, dict):
        return ""

    groups = {
        "Entrada / Nivel": [
            ("input_gain_db", "Gain de entrada", "dB"),
            ("target_peak", "Pico objetivo", "dBFS"),
            ("use_lufs_normalize", "Normalizar por LUFS", None),
            ("target_lufs", "LUFS objetivo", "LUFS"),
            ("adaptive_loudness_weighting", "Loudness adaptativo (ISO 226)", None),
            ("loudness_sensitivity_amount", "Sensibilidad loudness", None),
            ("platform_target", "Plataforma target", None),
        ],
        "Compresor principal": [
            ("comp_threshold_db", "Threshold", "dB"),
            ("comp_ratio", "Ratio", ":1"),
            ("comp_attack_ms", "Attack", "ms"),
            ("comp_release_ms", "Release", "ms"),
            ("comp_makeup_db", "Makeup", "dB"),
            ("comp_pdr", "PDR activo", None),
            ("comp_pdr_hold_ms", "PDR hold", "ms"),
            ("comp_stereo_link", "Stereo link", None),
            ("comp_bypass", "Bypass", None),
        ],
        "Compresor paralelo": [
            ("parallel_bypass", "Bypass", None),
            ("parallel_mix", "Mix", None),
            ("parallel_threshold_db", "Threshold", "dB"),
            ("parallel_ratio", "Ratio", ":1"),
            ("parallel_attack_ms", "Attack", "ms"),
            ("parallel_release_ms", "Release", "ms"),
        ],
        "Compresor Glue": [
            ("glue_bypass", "Bypass", None),
            ("glue_threshold_db", "Threshold", "dB"),
            ("glue_ratio", "Ratio", ":1"),
            ("glue_attack_ms", "Attack", "ms"),
            ("glue_release_ms", "Release", "ms"),
            ("glue_makeup_db", "Makeup", "dB"),
            ("glue_pdr", "PDR activo", None),
        ],
        "Filtros / EQ de borde": [
            ("hp_cutoff", "High-pass", "Hz"),
            ("lp_bypass", "Low-pass bypass", None),
            ("lp_cutoff", "Low-pass", "Hz"),
            ("high_shelf_gain_db", "High shelf gain", "dB"),
            ("high_shelf_freq_hz", "High shelf freq", "Hz"),
            ("low_shelf_gain_db", "Low shelf gain", "dB"),
            ("low_shelf_freq_hz", "Low shelf freq", "Hz"),
        ],
        "EQ paramétrica (6 bandas)": [
            ("eq1_freq", "EQ1 freq", "Hz"), ("eq1_gain", "EQ1 gain", "dB"), ("eq1_q", "EQ1 Q", None),
            ("eq2_freq", "EQ2 freq", "Hz"), ("eq2_gain", "EQ2 gain", "dB"), ("eq2_q", "EQ2 Q", None),
            ("eq3_freq", "EQ3 freq", "Hz"), ("eq3_gain", "EQ3 gain", "dB"), ("eq3_q", "EQ3 Q", None),
            ("eq4_freq", "EQ4 freq", "Hz"), ("eq4_gain", "EQ4 gain", "dB"), ("eq4_q", "EQ4 Q", None),
            ("eq5_freq", "EQ5 freq", "Hz"), ("eq5_gain", "EQ5 gain", "dB"), ("eq5_q", "EQ5 Q", None),
            ("eq6_freq", "EQ6 freq", "Hz"), ("eq6_gain", "EQ6 gain", "dB"), ("eq6_q", "EQ6 Q", None),
            ("eq_mode", "Modo EQ", None),
        ],
        "Multibanda": [
            ("mb_bypass", "Bypass", None),
            ("mb_low_crossover", "Crossover bajo", "Hz"),
            ("mb_high_crossover", "Crossover alto", "Hz"),
            ("mb_low_threshold_db", "Low threshold", "dB"),
            ("mb_low_ratio", "Low ratio", ":1"),
            ("mb_low_attack_ms", "Low attack", "ms"),
            ("mb_low_release_ms", "Low release", "ms"),
            ("mb_low_makeup_db", "Low makeup", "dB"),
            ("mb_mid_threshold_db", "Mid threshold", "dB"),
            ("mb_mid_ratio", "Mid ratio", ":1"),
            ("mb_mid_attack_ms", "Mid attack", "ms"),
            ("mb_mid_release_ms", "Mid release", "ms"),
            ("mb_mid_makeup_db", "Mid makeup", "dB"),
            ("mb_high_threshold_db", "High threshold", "dB"),
            ("mb_high_ratio", "High ratio", ":1"),
            ("mb_high_attack_ms", "High attack", "ms"),
            ("mb_high_release_ms", "High release", "ms"),
            ("mb_high_makeup_db", "High makeup", "dB"),
        ],
        "Estéreo / M-S": [
            ("stereo_bypass", "Stereo bypass", None),
            ("stereo_width_amount", "Stereo width", None),
            ("use_stereo_enhancer", "Enhancer activo", None),
            ("haas_delay_ms", "Haas delay", "ms"),
            ("enhancer_bass_mono_freq", "Bass mono freq", "Hz"),
            ("mid_gain_db", "Mid gain", "dB"),
            ("side_gain_db", "Side gain", "dB"),
        ],
        "M-S Compresión": [
            ("ms_comp_bypass", "Bypass", None),
            ("ms_comp_mid_threshold_db", "Mid threshold", "dB"),
            ("ms_comp_mid_ratio", "Mid ratio", ":1"),
            ("ms_comp_mid_attack_ms", "Mid attack", "ms"),
            ("ms_comp_mid_release_ms", "Mid release", "ms"),
            ("ms_comp_mid_makeup_db", "Mid makeup", "dB"),
            ("ms_comp_side_threshold_db", "Side threshold", "dB"),
            ("ms_comp_side_ratio", "Side ratio", ":1"),
            ("ms_comp_side_attack_ms", "Side attack", "ms"),
            ("ms_comp_side_release_ms", "Side release", "ms"),
            ("ms_comp_side_makeup_db", "Side makeup", "dB"),
        ],
        "Dynamic EQ / Resonancias": [
            ("dyneq_bypass", "Dyn EQ bypass", None),
            ("dyneq_freq", "Dyn EQ freq", "Hz"),
            ("dyneq_q", "Dyn EQ Q", None),
            ("dyneq_threshold_db", "Dyn EQ threshold", "dB"),
            ("dyneq_ratio", "Dyn EQ ratio", ":1"),
            ("reso_bypass", "Reso bypass", None),
            ("reso_freq", "Reso freq", "Hz"),
            ("reso_q", "Reso Q", None),
            ("reso_threshold_db", "Reso threshold", "dB"),
            ("reso_ratio", "Reso ratio", ":1"),
        ],
        "Saturación / Transientes": [
            ("saturation_drive", "Sat drive", None),
            ("saturation_mode", "Sat mode", None),
            ("saturation_mix", "Sat mix", None),
            ("transient_attack", "Transient attack", None),
            ("transient_sustain", "Transient sustain", None),
        ],
        "Clipper / Limiter / Salida": [
            ("clipper_bypass", "Clipper bypass", None),
            ("clipper_mode", "Clipper mode", None),
            ("clipper_ceiling", "Clipper ceiling", "dB"),
            ("clipper_drive_db", "Clipper drive", "dB"),
            ("limiter_ceiling", "Limiter ceiling", "dBFS"),
            ("limiter_release_ms", "Limiter release", "ms"),
            ("output_format", "Formato salida", None),
            ("output_bit_depth", "Bit depth", None),
            ("dither_mode", "Dither", None),
        ],
        "Reverb / Tonal Balance / Mono": [
            ("reverb_size", "Reverb size", None),
            ("reverb_wet", "Reverb wet", None),
            ("tonal_balance_bypass", "Tonal balance bypass", None),
            ("tonal_balance_amount", "Tonal balance amount", None),
            ("low_end_mono_freq", "Mono freq", "Hz"),
            ("low_end_mono_amount", "Mono amount", None),
        ],
        "Multibanda Stereo Width": [
            ("mb_stereo_bypass", "MB Stereo bypass", None),
            ("mb_stereo_low_width", "MB low width", None),
            ("mb_stereo_mid_width", "MB mid width", None),
            ("mb_stereo_high_width", "MB high width", None),
            ("mb_stereo_low_crossover", "MB Stereo low xover", "Hz"),
            ("mb_stereo_high_crossover", "MB Stereo high xover", "Hz"),
        ],
        "Noise Reduction": [
            ("nr_bypass", "NR bypass", None),
            ("nr_strength", "NR strength", None),
        ],
        "Oversample": [
            ("oversample_mode", "Oversample mode", None),
        ],
        "Preview": [
            ("preview_start_sec", "Inicio del preview", "s"),
        ],
    }

    lines = ["PARÁMETROS ACTUALES DE LA CADENA DE MASTERING (lo que el usuario tiene seteado ahora mismo):"]

    for group_name, params in groups.items():
        group_lines = []
        for key, label, unit in params:
            val = current_params.get(key)
            if val is None or val == "":
                continue
            if isinstance(val, bool):
                group_lines.append(f"    - {label}: {'activado' if val else 'desactivado'}")
            elif unit:
                group_lines.append(f"    - {label}: {val} {unit}")
            else:
                group_lines.append(f"    - {label}: {val}")
        if group_lines:
            lines.append(f"  [{group_name}]")
            lines.extend(group_lines)

    if len(lines) <= 1:
        return ""

    lines.append("")
    lines.append("Estos son los valores de referencia del usuario. Cuando propongas cambios, hacelo")
    lines.append("RELATIVO a estos parámetros actuales — no valores genéricos. Por ejemplo, si el")
    lines.append("usuario dice 'más brillo' y high_shelf_gain_db ya está en 2, proponé 3 o 4, no 0.")

    return "\n".join(lines)


SYSTEM_PROMPT_TEMPLATE = """Sos el Asistente de IA de MASTER, un estudio de mastering de audio online \
(similar en espíritu al asistente de IA de LANDR). Hablás en español rioplatense, con tono \
cercano, profesional y directo, como un ingeniero de mastering con experiencia que está \
mirando la sesión del usuario en tiempo real.

Tenés acceso al análisis técnico real del track que subió el usuario (ver más abajo). \
Usalo SIEMPRE que sea relevante para dar respuestas específicas y accionables, citando los \
números concretos (LUFS, dB, balance espectral, etc.) en vez de consejos genéricos.

Además de responder en texto, PODÉS proponer un cambio concreto y aplicable a la cadena de \
mastering (igual que el asistente de LANDR, que no solo aconseja sino que ajusta el master). \
Para eso completá los campos numéricos/booleanos de parámetros que quieras cambiar; dejá en \
null (sin completar) todos los que no correspondan.

Cuándo SÍ proponer parámetros:
- El usuario pide explícitamente un cambio o efecto ("más brillo", "que suene más fuerte", \
"bajale la compresión", "quiero más pegada en el bajo", "subilo a -9 LUFS para Spotify", etc.).
- Vos mismo detectás en el análisis un problema puntual y accionable y el usuario te pidió consejo \
sobre eso (no lo hagas de prepo en preguntas puramente teóricas).

Cuándo NO proponer parámetros (dejar todo en null):
- Preguntas generales de teoría, flujo de trabajo, o que no dependen del track.
- No hay análisis disponible todavía.
- El usuario está charlando, agradeciendo, o pidiendo una aclaración sin pedir un ajuste.

REGLA CRÍTICA — Basá tus propuestas en el análisis real del track:
- NUNCA inventes valores genéricos. Cada parámetro que propongas debe estar justificado por \
un dato concreto del análisis (LUFS, crest factor, balance espectral, stereo correlation, etc.).
- Si no hay análisis disponible, NO propongas parámetros — pedile al usuario que analice el track primero.
- Si el análisis muestra que algo está bien, no lo cambies. Solo proponé cambios donde el análisis \
indique un problema real (ej: spectral_flatness bajo → resonancia; lufs < -20 → necesita loudness; \
stereo_correlation < 0.3 → problema de fase; true_peak > -0.3 → riesgo de clipping).
- CITA el número del análisis que justifica cada cambio en tu respuesta.

Reglas para las propuestas:
- Cambiá SOLO los parámetros relevantes al pedido puntual (normalmente 1 a 6 campos), NUNCA \
completes todos los campos del esquema como si fuera un mastering completo desde cero.
- Los campos de umbral y techo (comp_threshold_db, mb_low/mid/high_threshold_db, target_peak_db, \
limiter_ceiling_db) están SIEMPRE en dB relativos a 0dBFS (0 = techo digital, valores negativos \
hacia abajo), igual que cualquier otro parámetro en dB de esta lista. No hay ningún parámetro \
en escala lineal 0-1 en este esquema — todo lo que es amplitud/nivel se expresa en dB.
- Los valores deben estar dentro de los rangos válidos (ver más abajo) y ser coherentes con el \
análisis real del track, no genéricos.
- Los cambios que propongas deben ser RELATIVOS a los parámetros actuales del usuario (ver la \
sección "PARÁMETROS ACTUALES" más abajo). No los reemplaces desde cero — ajustá lo que ya tiene.
- Si proponés parámetros, completá también "suggestion_summary" con una frase muy corta (5-9 \
palabras) que resuma el cambio, ej: "Más aire arriba de 8kHz" o "Bajar 2dB el makeup del compresor".
- En "reply" explicá en 1-3 oraciones qué le vas a cambiar y por qué, en tono conversacional \
(el usuario va a ver un botón aparte para aplicar los valores, no hace falta que listes cada \
número ahí).

Lineamientos generales:
- Sé conciso: respuestas cortas (2-6 oraciones o una lista breve), esto es un chat, no un ensayo.
- Si el usuario pregunta algo que no depende del análisis (teoría, flujo de trabajo, qué preset \
usar, cómo usar la herramienta), respondé igual con tu conocimiento de mastering/mezcla.
- Si no hay análisis disponible todavía, decilo y sugerí analizar o subir un audio primero, pero \
igual podés responder preguntas generales de mastering.
- No inventes datos del track que no estén en el contexto: si falta algo, decí que no lo tenés.
- No sos un modelo genérico: sos parte de esta app de mastering, mantené el foco en audio, \
mezcla, mastering y el uso de la herramienta.

Rangos válidos de los parámetros de la cadena (para cuando propongas cambios):
{ranges_block}

{current_params_block}

{audio_context}
"""


async def chat(user_message: str, history: Optional[list] = None,
               analysis: Optional[dict] = None, preset: Optional[str] = None,
               platform: Optional[str] = None,
               current_params: Optional[dict] = None) -> dict:
    """Envía un mensaje al asistente de IA y devuelve un dict:
    {"reply": str, "suggested_params": dict, "suggestion_summary": Optional[str]}

    `suggested_params` viene vacío ({}) cuando el modelo no propuso ningún ajuste \
    aplicable (p.ej. preguntas teóricas) — el frontend solo debe mostrar el botón \
    de "Aplicar cambios" cuando ese dict tiene contenido.

    `history` es una lista de dicts [{"role": "user"|"assistant", "content": str}, ...]
    con los turnos previos de esta conversación (ya sin el mensaje actual).
    """
    client = _get_client()
    if client is None:
        return {
            "reply": f"La IA no está disponible en este momento ({get_unavailable_reason()}). "
                     "No se pueden sugerir parámetros sin el modelo de IA. "
                     "Verificá la configuración de la API key e intentá de nuevo.",
            "suggested_params": {},
            "suggestion_summary": None,
            "suggestion_explanation": None,
        }

    if not user_message or not user_message.strip():
        raise ValueError("El mensaje está vacío.")

    ranges_block = _param_ranges_text()
    float_field_names = [k for k in PARAM_RANGES if k not in DB_EXPOSED_FIELDS]
    float_field_names += [_db_field_name(k) for k in DB_EXPOSED_FIELDS]
    enum_fields_hint = "\n".join(
        f'- "{field}": string o null, uno de {", ".join(repr(v) for v in values)}.'
        for field, values in STRING_ENUM_FIELDS.items()
    )
    json_fields_hint = (
        "Devolvé SOLO un objeto JSON plano (sin markdown, sin texto extra) con estas claves:\n"
        '- "reply": string, obligatorio, tu respuesta conversacional.\n'
        '- "suggestion_summary": string o null.\n'
        '- "reasoning": string o null. Si proponés parámetros, explicá brevemente por qué y cuál es el fundamento técnico.\n'
        f"- Como número (float) o null si no lo tocás: {', '.join(float_field_names)}.\n"
        f"- Como booleano (true/false) o null si no lo tocás: {', '.join(BOOL_PARAM_FIELDS)}.\n"
        f"{enum_fields_hint}"
    )
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        ranges_block=ranges_block,
        current_params_block=build_current_params_context(current_params),
        audio_context=build_audio_context(analysis, preset, platform),
    ) + "\n\n" + json_fields_hint

    # Gemini usa roles "user" y "model" (en vez de "assistant").
    contents = []
    for turn in (history or [])[-MAX_HISTORY_MESSAGES:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": content}]})
    contents.append({"role": "user", "parts": [{"text": user_message.strip()}]})

    # Llamada liviana (respuesta conversacional + a lo sumo algunos parámetros
    # puntuales, no los ~90 interdependientes de auto-master): thinking
    # explícitamente apagado. Sin esto, gemini-2.5-flash usa thinking dinámico
    # por defecto (igual que el bug de auto-master, ver ahí), y acá el margen
    # es todavía menor (2048 tokens) — más chances de que el JSON se corte a
    # mitad de generación.
    raw = await _gemini_generate_content(system_prompt, contents, max_output_tokens=2048, thinking_budget=0)
    data = _extract_json_object(raw) if raw else None
    if data is None and raw is not None:
        logger.warning("Respuesta de chat de Gemini no fue JSON parseable.")

    if not data:
        return {
            "reply": "No se pudo obtener una respuesta válida del modelo de IA. "
                     "No se inventan parámetros sin una respuesta concreta. "
                     "Probá reformular tu mensaje o intentá de nuevo.",
            "suggested_params": {},
            "suggestion_summary": None,
            "suggestion_explanation": None,
        }

    reply_text = str(data.get("reply") or "").strip() or (
        "No obtuve respuesta del modelo. Probá reformular la pregunta."
    )

    suggested: dict = {}
    for key, (lo, hi) in PARAM_RANGES.items():
        if key in DB_EXPOSED_FIELDS:
            continue
        v = data.get(key)
        if v is None:
            continue
        try:
            clamped = _clamp(float(v), lo, hi)
        except (TypeError, ValueError):
            continue
        if clamped is not None:
            suggested[key] = round(clamped, 3)
    for key in DB_EXPOSED_FIELDS:
        linear_val = _resolve_db_exposed_param(key, data, default_linear=None)
        if linear_val is not None:
            suggested[key] = round(linear_val, 4)
    for key in BOOL_PARAM_FIELDS:
        v = data.get(key)
        if v is not None:
            suggested[key] = bool(v)
    for field, valid_values in STRING_ENUM_FIELDS.items():
        v = data.get(field)
        if v in valid_values:
            suggested[field] = v

    return {
        "reply": reply_text,
        "suggested_params": suggested,
        "suggestion_summary": (str(data.get("suggestion_summary") or "").strip() or None),
        "suggestion_explanation": (str(data.get("reasoning") or "").strip() or None),
    }


# ═══════════════════════════════════════════════════════════════════════════
# ── Prompt-to-Master: NL → cadena completa de DSP params ───────────────────
# ═══════════════════════════════════════════════════════════════════════════

PROMPT_MASTER_SYSTEM = """Sos el motor de Prompt-to-Master de MASTER, un estudio de mastering de audio online. \
El usuario te describe en lenguaje natural cómo quiere que suene su master y vos devolvés la cadena \
completa de parámetros DSP para lograrlo.

REGLA CRÍTICA — Basá TODA la cadena en el análisis técnico real del track:
- Cada parámetro que propongas debe estar justificado por un dato concreto del análisis \
(LUFS, crest factor, balance espectral, stereo correlation, dynamic range, resonancias, etc.).
- NUNCA uses valores genéricos o presets fijos. Ajustá cada parámetro al track específico.
- Si no hay análisis disponible, NO propongas parámetros — devolvé un error indicando que \
se necesita analizar el track primero.
- CITA los números del análisis que justifican tus decisiones en el campo "reasoning".

También tenés los PARÁMETROS ACTUALES del usuario como referencia. Usalos como punto de partida:
no empieces desde cero, ajustá lo que ya tiene seteado según el pedido del usuario.

Instrucciones del usuario:
"{user_message}"

Devolvé SOLO un objeto JSON plano con:
- "reply": string — explicación corta (2-4 oraciones) de qué vas a hacer y por qué, citando el análisis.
- "reasoning": string — justificación técnica detallada de cada decisión, citando números del análisis.
- "suggestion_summary": string — frase corta (5-9 palabras) que resume el master.
- Todos los parámetros numéricos de la cadena (como float): {float_field_names}
- Booleanos (true/false): {bool_field_names}
- Enums: {enum_fields_hint}

Rangos válidos:
{ranges_block}

{current_params_block}

{audio_context}
"""


async def prompt_master(user_message: str,
                        analysis: Optional[dict] = None,
                        current_params: Optional[dict] = None,
                        preset: Optional[str] = None,
                        platform: Optional[str] = None) -> dict:
    """Convierte una instrucción en lenguaje natural a la cadena completa de mastering.

    A diferencia de chat() (que propone 1-6 tweaks), esto devuelve TODOS los ~90 parámetros.
    """
    if not analysis:
        return {
            "reply": "No hay análisis disponible. Analizá el track primero antes de pedir un master completo.",
            "params": {},
            "reasoning": None,
            "suggestion_summary": None,
        }

    client = _get_client()
    if client is None:
        return {
            "reply": f"La IA no está disponible ({get_unavailable_reason()}). No se puede generar el master sin el modelo.",
            "params": {},
            "reasoning": None,
            "suggestion_summary": None,
        }

    if not user_message or not user_message.strip():
        user_message = "Masterizá este track según el análisis, optimizando loudness, dinámica y balance espectral para la plataforma elegida."

    ranges_block = _param_ranges_text()
    float_field_names = [k for k in PARAM_RANGES if k not in DB_EXPOSED_FIELDS]
    float_field_names += [_db_field_name(k) for k in DB_EXPOSED_FIELDS]
    enum_fields_hint = "\n".join(
        f'- "{field}": uno de {", ".join(repr(v) for v in values)}.'
        for field, values in STRING_ENUM_FIELDS.items()
    )

    system_prompt = PROMPT_MASTER_SYSTEM.format(
        user_message=user_message.strip(),
        float_field_names=", ".join(float_field_names),
        bool_field_names=", ".join(BOOL_PARAM_FIELDS),
        enum_fields_hint=enum_fields_hint,
        ranges_block=ranges_block,
        current_params_block=build_current_params_context(current_params),
        audio_context=build_audio_context(analysis, preset, platform),
    )

    contents = [{"role": "user", "parts": [{"text": user_message.strip()}]}]

    raw = await _gemini_generate_content(
        system_prompt, contents, max_output_tokens=8192,
        thinking_budget=-1, temperature=0.3,
    )
    data = _extract_json_object(raw) if raw else None
    if data is None and raw is not None:
        logger.warning("Prompt-to-Master: respuesta no fue JSON parseable.")

    if not data:
        return {
            "reply": "No se pudo obtener una respuesta válida del modelo. Intentá de nuevo.",
            "params": {},
            "reasoning": None,
            "suggestion_summary": None,
        }

    params: dict = {}
    for key, (lo, hi) in PARAM_RANGES.items():
        if key in DB_EXPOSED_FIELDS:
            continue
        v = data.get(key)
        if v is None:
            continue
        try:
            clamped = _clamp(float(v), lo, hi)
        except (TypeError, ValueError):
            continue
        if clamped is not None:
            params[key] = round(clamped, 3)
    for key in DB_EXPOSED_FIELDS:
        linear_val = _resolve_db_exposed_param(key, data, default_linear=None)
        if linear_val is not None:
            params[key] = round(linear_val, 4)
    for key in BOOL_PARAM_FIELDS:
        v = data.get(key)
        if v is not None:
            params[key] = bool(v)
    for field, valid_values in STRING_ENUM_FIELDS.items():
        v = data.get(field)
        if v in valid_values:
            params[field] = v

    return {
        "reply": str(data.get("reply") or "").strip(),
        "params": params,
        "reasoning": str(data.get("reasoning") or "").strip() or None,
        "suggestion_summary": str(data.get("suggestion_summary") or "").strip() or None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ── Auto-Mastering: la IA toma las decisiones (estilo LANDR AI) ─────────────
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# ── Auto-Mastering: la IA genera los parámetros de la cadena a mano ─────────
# (ya NO elige entre presets fijos: calcula cada valor en base al análisis)
# ═══════════════════════════════════════════════════════════════════════════

# Rango válido [min, max] para cada parámetro numérico de la cadena de mastering.
# Debe reflejar los mismos límites que valida /master en app.py (Query ge/le),
# para que la IA nunca proponga un valor que el motor de audio vaya a rechazar.
PARAM_RANGES: Dict[str, Tuple[float, float]] = {
    "input_gain_db": (-24.0, 24.0),
    "target_peak": (0.1, 1.0),
    "target_lufs": (-40.0, 0.0),
    "hp_cutoff": (20.0, 500.0),
    "lp_cutoff": (1000.0, 22000.0),
    "high_shelf_gain_db": (-12.0, 12.0),
    "high_shelf_freq_hz": (1000.0, 20000.0),
    "low_shelf_gain_db": (-12.0, 12.0),
    "low_shelf_freq_hz": (20.0, 2000.0),
    "eq1_freq": (20.0, 20000.0), "eq1_gain": (-12.0, 12.0), "eq1_q": (0.1, 10.0),
    "eq2_freq": (20.0, 20000.0), "eq2_gain": (-12.0, 12.0), "eq2_q": (0.1, 10.0),
    "eq3_freq": (20.0, 20000.0), "eq3_gain": (-12.0, 12.0), "eq3_q": (0.1, 10.0),
    "eq4_freq": (20.0, 20000.0), "eq4_gain": (-12.0, 12.0), "eq4_q": (0.1, 10.0),
    "eq5_freq": (20.0, 20000.0), "eq5_gain": (-12.0, 12.0), "eq5_q": (0.1, 10.0),
    "eq6_freq": (20.0, 20000.0), "eq6_gain": (-12.0, 12.0), "eq6_q": (0.1, 10.0),
    "comp_threshold": (0.0, 1.0), "comp_ratio": (1.0, 20.0),
    "comp_attack_ms": (0.1, 200.0), "comp_release_ms": (10.0, 1000.0), "comp_makeup_db": (-12.0, 24.0),
    "transient_attack": (-1.0, 1.0), "transient_sustain": (-1.0, 1.0),
    "mb_low_crossover": (20.0, 2000.0), "mb_high_crossover": (500.0, 20000.0),
    "mb_low_threshold": (0.0, 1.0), "mb_low_ratio": (1.0, 20.0), "mb_low_attack_ms": (0.1, 200.0), "mb_low_release_ms": (10.0, 1000.0), "mb_low_makeup_db": (-12.0, 24.0),
    "mb_mid_threshold": (0.0, 1.0), "mb_mid_ratio": (1.0, 20.0), "mb_mid_attack_ms": (0.1, 200.0), "mb_mid_release_ms": (10.0, 1000.0), "mb_mid_makeup_db": (-12.0, 24.0),
    "mb_high_threshold": (0.0, 1.0), "mb_high_ratio": (1.0, 20.0), "mb_high_attack_ms": (0.1, 200.0), "mb_high_release_ms": (10.0, 1000.0), "mb_high_makeup_db": (-12.0, 24.0),
    "mb_stereo_low_width": (0.0, 3.0), "mb_stereo_mid_width": (0.0, 3.0), "mb_stereo_high_width": (0.0, 3.0),
    "mb_stereo_low_crossover": (20.0, 2000.0), "mb_stereo_high_crossover": (200.0, 20000.0),
    "saturation_drive": (0.0, 1.0), "saturation_mix": (0.0, 1.0),
    "mid_gain_db": (-12.0, 12.0), "side_gain_db": (-18.0, 18.0), "stereo_width_amount": (0.0, 3.0),
    "enhancer_bass_mono_freq": (40.0, 500.0), "haas_delay_ms": (0.0, 30.0),
    "reverb_size": (0.05, 2.0), "reverb_wet": (0.0, 1.0),
    "low_end_mono_freq": (40.0, 300.0), "low_end_mono_amount": (0.0, 1.0),
    "glue_threshold_db": (-24.0, 0.0), "glue_ratio": (1.0, 10.0), "glue_attack_ms": (0.1, 200.0),
    "glue_release_ms": (10.0, 1000.0), "glue_makeup_db": (-12.0, 12.0),
    "clipper_ceiling": (0.1, 1.0), "clipper_drive_db": (0.0, 24.0),
    "dyneq_freq": (200.0, 16000.0), "dyneq_q": (0.5, 12.0), "dyneq_threshold_db": (-60.0, 0.0),
    "dyneq_ratio": (1.0, 20.0), "dyneq_attack_ms": (0.1, 100.0), "dyneq_release_ms": (5.0, 1000.0),
    "dyneq_max_reduction_db": (0.0, 30.0),
    "ms_mid_freq": (20.0, 2000.0), "ms_mid_gain": (-12.0, 12.0), "ms_mid_q": (0.1, 10.0),
    "ms_side_freq": (1000.0, 20000.0), "ms_side_gain": (-12.0, 12.0), "ms_side_q": (0.1, 10.0),
    "ms_comp_mid_threshold_db": (-60.0, 0.0), "ms_comp_mid_ratio": (1.0, 20.0),
    "ms_comp_mid_attack_ms": (0.1, 200.0), "ms_comp_mid_release_ms": (5.0, 2000.0),
    "ms_comp_mid_makeup_db": (0.0, 24.0),
    "ms_comp_side_threshold_db": (-60.0, 0.0), "ms_comp_side_ratio": (1.0, 20.0),
    "ms_comp_side_attack_ms": (0.1, 200.0), "ms_comp_side_release_ms": (5.0, 2000.0),
    "ms_comp_side_makeup_db": (0.0, 24.0),
    "reso_freq": (200.0, 16000.0), "reso_q": (0.5, 12.0), "reso_threshold_db": (-60.0, 0.0),
    "reso_ratio": (1.0, 20.0), "reso_attack_ms": (0.1, 100.0), "reso_release_ms": (5.0, 1000.0),
    "reso_max_reduction_db": (0.0, 30.0),
    "nr_strength": (0.0, 1.0), "nr_noise_sample_sec": (0.1, 5.0),
    "limiter_ceiling": (0.5, 1.0), "limiter_release_ms": (1.0, 500.0),
}
BOOL_PARAM_FIELDS = [
    "use_lufs_normalize", "mb_bypass", "use_stereo_enhancer",
    "lp_bypass", "comp_stereo_link", "mb_stereo_bypass", "glue_bypass",
    "dyneq_bypass", "ms_eq_bypass", "ms_comp_bypass", "reso_bypass", "clipper_bypass", "nr_bypass",
]
SATURATION_MODES = ("tape", "tube")
EQ_MODES = ("iir", "linear_phase")
CLIPPER_MODES = ("soft", "hard")
# Campos de texto libre (no numéricos/booleanos) con un set fijo de valores
# válidos — mismo patrón de validación para los tres, evita que un nuevo
# campo de este tipo repita a mano la lista de opciones en 3 lugares
# distintos (y se desincronice, como pasaba antes con "clipper" apareciendo
# como opción de saturation_mode en el prompt pero no en SATURATION_MODES).
STRING_ENUM_FIELDS: Dict[str, tuple] = {
    "saturation_mode": SATURATION_MODES,
    "eq_mode": EQ_MODES,
    "clipper_mode": CLIPPER_MODES,
}

# Campos de umbral/techo del motor que son ratios lineales de amplitud (0-1,
# relativos a 0dBFS) — nomenclatura técnica interna del DSP. Se los exponemos a
# la IA (y al chat) directamente en dB, que es la escala en la que cualquiera
# razona naturalmente sobre audio, en vez de forzarla a pensar en ratios 0-1.
# El código convierte a la escala lineal real del motor antes de aplicar nada;
# la IA nunca ve ni produce el número lineal.
DB_EXPOSED_FIELDS: Dict[str, Tuple[float, float]] = {
    "target_peak": (-20.0, 0.0),
    "comp_threshold": (-40.0, 0.0),
    "mb_low_threshold": (-40.0, 0.0),
    "mb_mid_threshold": (-40.0, 0.0),
    "mb_high_threshold": (-40.0, 0.0),
    "limiter_ceiling": (-6.0, 0.0),
}


def _db_field_name(key: str) -> str:
    """Nombre del campo tal como lo ve la IA: 'comp_threshold' -> 'comp_threshold_db'."""
    return f"{key}_db"


def _db_to_linear(db_value: float) -> float:
    return 10 ** (db_value / 20.0)


def _linear_to_db(linear_value: float) -> float:
    import math
    return round(20 * math.log10(max(float(linear_value), 1e-6)), 2)
    
import math
def linear_to_db(linear: float) -> float:
    return 20 * math.log10(max(linear, 1e-6))    


# Aclaraciones de escala/unidad para el resto de parámetros que no son dB reales
# (los de DB_EXPOSED_FIELDS ya no necesitan nota: se exponen directamente en dB).
PARAM_NOTES: Dict[str, str] = {
    "saturation_drive": "0–1, cantidad de saturación (no dB). Típico 0.05–0.3.",
    "saturation_mix": "0–1, mezcla dry/wet (no dB). Típico 0.1–0.4.",
    "reverb_wet": "0–1, mezcla dry/wet (no dB). Típico 0–0.1, es mastering, no mezcla.",
    "reverb_size": "0.05–2, tamaño relativo de la reverb (no dB, no segundos).",
    "transient_attack": "-1 a 1, unitless. Negativo = atenúa transitorios, positivo = realza.",
    "transient_sustain": "-1 a 1, unitless. Negativo = atenúa sustain, positivo = realza.",
    "stereo_width_amount": "multiplicador de ancho estéreo, 1.0 = ancho original (no dB, no %).",
    "comp_ratio": "ratio de compresión X:1 (ej. 2.5 = 2.5:1), no dB.",
    "mb_low_ratio": "ratio de compresión X:1, no dB.",
    "mb_mid_ratio": "ratio de compresión X:1, no dB.",
    "mb_high_ratio": "ratio de compresión X:1, no dB.",
    "mb_stereo_low_width": "multiplicador de ancho estéreo SOLO en graves, análogo a stereo_width_amount pero por banda (no dB).",
    "mb_stereo_mid_width": "multiplicador de ancho estéreo SOLO en medios (no dB).",
    "mb_stereo_high_width": "multiplicador de ancho estéreo SOLO en agudos (no dB).",
    "low_end_mono_amount": "0–1, cuánto se monofoniza por debajo de low_end_mono_freq (0=nada, 1=mono total). No dB.",
    "glue_ratio": "ratio de compresión X:1 del glue compressor (bus), no dB.",
    "dyneq_ratio": "ratio de compresión X:1 de la EQ dinámica (de-esser), no dB.",
    "reso_ratio": "ratio de compresión X:1 de la EQ dinámica de resonancias, no dB.",
    "nr_strength": "0–1, intensidad de la reducción de ruido (0=nada, 1=máximo). No dB.",
    "nr_noise_sample_sec": "segundos iniciales del track usados para estimar el perfil de ruido (no dB).",
}


def _param_ranges_text() -> str:
    """Arma el bloque de rangos válidos para el prompt. Los campos de umbral/techo \
    (DB_EXPOSED_FIELDS) se listan ya convertidos a dB, con su nombre '_db' — la IA \
    nunca ve el ratio lineal interno del motor."""
    lines = []
    for key, (lo, hi) in PARAM_RANGES.items():
        if key in DB_EXPOSED_FIELDS:
            continue  # se listan más abajo, en dB
        note = PARAM_NOTES.get(key)
        if note:
            lines.append(f"- {key}: [{lo}, {hi}] — {note}")
        elif key.endswith("_db"):
            lines.append(f"- {key}: [{lo}, {hi}] dB")
        elif key.endswith("_ms"):
            lines.append(f"- {key}: [{lo}, {hi}] ms")
        elif key.endswith(("freq", "crossover", "cutoff")) or key.endswith("_hz"):
            lines.append(f"- {key}: [{lo}, {hi}] Hz")
        else:
            lines.append(f"- {key}: [{lo}, {hi}]")
    for key, (db_lo, db_hi) in DB_EXPOSED_FIELDS.items():
        lines.append(f"- {_db_field_name(key)}: [{db_lo}, {db_hi}] dB, relativo a 0dBFS "
                      f"(el motor lo convierte solo a ratio interno, no calcules vos la conversión)")
    return "\n".join(lines)


def _resolve_db_exposed_param(key: str, data: dict, default_linear: Optional[float] = None):
    """Lee el campo '{key}_db' de la respuesta de la IA, lo clampea en dB y lo \
    convierte a la escala lineal real del motor (PARAM_RANGES[key]). Si no vino \
    en la respuesta, devuelve `default_linear` (ya en escala lineal) sin tocar."""
    db_lo, db_hi = DB_EXPOSED_FIELDS[key]
    lo, hi = PARAM_RANGES[key]
    raw = data.get(_db_field_name(key))
    if raw is None:
        return default_linear
    try:
        db_val = _clamp(float(raw), db_lo, db_hi)
    except (TypeError, ValueError):
        return default_linear
    if db_val is None:
        return default_linear
    linear_val = _clamp(_db_to_linear(db_val), lo, hi)
    return linear_val if linear_val is not None else default_linear



# ── ANÁLISIS PERCEPTUAL (Los "oídos" de Laia) ──────────────────────────────

class PerceptualProfile:
    """Describe cómo suena la mezcla en términos humanos"""
    def __init__(self):
        self.clarity = "unknown"
        self.dynamic_feel = "unknown"
        self.tonal_balance = "unknown"
        self.stereo_coherence = "unknown"
        self.instrumental_definition = "unknown"
        self.presence_feel = "unknown"
        self.fatigue_risk = 0.0
        self.mix_cohesion = "unknown"
        self.frequency_balance = "unknown"
        self.headroom_feel = "unknown"
    
    def to_dict(self):
        return {
            "clarity": self.clarity,
            "dynamic_feel": self.dynamic_feel,
            "tonal_balance": self.tonal_balance,
            "stereo_coherence": self.stereo_coherence,
            "instrumental_definition": self.instrumental_definition,
            "presence_feel": self.presence_feel,
            "fatigue_risk": round(self.fatigue_risk, 2),
            "mix_cohesion": self.mix_cohesion,
            "frequency_balance": self.frequency_balance,
            "headroom_feel": self.headroom_feel,
        }


def _analyze_perceptual_profile(analysis: dict) -> PerceptualProfile:
    """Convierte métricas técnicas en descripción perceptual"""
    profile = PerceptualProfile()
    centroid = analysis.get("spectral_centroid", 3000)
    flatness = analysis.get("spectral_flatness", 0.5)
    plr = analysis.get("plr_db", 8)
    lra = analysis.get("lra_lu", 4)
    correlation_global = analysis.get("correlation_global", 0.8)
    mono_compatibility = analysis.get("mono_compatibility_db", -3)
    lufs = analysis.get("loudness_integrated", -14)
    true_peak = analysis.get("true_peak_db", -3)
    clipping_ratio = analysis.get("clipping_ratio", 0.0)
    band_energies = analysis.get("band_energies_db", {})
    air_energy = band_energies.get("air", -20)
    presence_band = band_energies.get("presence", -20)
    subs_energy = band_energies.get("subs", -20)
    
    if air_energy < -30 and centroid < 2000:
        profile.clarity = "muddy"
    elif flatness < 0.3 or centroid > 6000:
        profile.clarity = "harsh"
    else:
        profile.clarity = "balanced"
    
    if plr > 14 and lra > 7:
        profile.dynamic_feel = "loose"
    elif plr < 6 and lra < 3:
        profile.dynamic_feel = "tight"
    else:
        profile.dynamic_feel = "balanced"
    
    if centroid < 2000:
        profile.tonal_balance = "dark"
    elif centroid > 5000:
        profile.tonal_balance = "bright"
    else:
        profile.tonal_balance = "balanced"
    
    if correlation_global > 0.9:
        profile.stereo_coherence = "mono"
    elif mono_compatibility < -6:
        profile.stereo_coherence = "phase_issues"
    elif correlation_global < 0.5:
        profile.stereo_coherence = "separated"
    else:
        profile.stereo_coherence = "coherent"
    
    if flatness > 0.7 and presence_band < 5:
        profile.instrumental_definition = "clear"
    elif flatness < 0.3:
        profile.instrumental_definition = "blended"
    elif presence_band > 8:
        profile.instrumental_definition = "overly_defined"
    else:
        profile.instrumental_definition = "clear"
    
    if centroid > 5500 and presence_band > 6:
        profile.presence_feel = "in_your_face"
    elif centroid < 2500 or (lufs < -18 and air_energy < -25):
        profile.presence_feel = "distant"
    else:
        profile.presence_feel = "present"
    
    fatigue = 0.0
    if centroid > 6000: fatigue += 0.3
    if plr < 4: fatigue += 0.2
    if presence_band > 10: fatigue += 0.25
    if lufs > -6: fatigue += 0.15
    profile.fatigue_risk = min(1.0, fatigue)
    
    if plr < 3:
        profile.mix_cohesion = "over_compressed"
    elif correlation_global < 0.6:
        profile.mix_cohesion = "disconnected"
    else:
        profile.mix_cohesion = "glued"
    
    if subs_energy > 5 and band_energies.get("mids", -20) < -5:
        profile.frequency_balance = "bass_heavy"
    elif air_energy > 5 and subs_energy < -10:
        profile.frequency_balance = "treble_heavy"
    else:
        profile.frequency_balance = "balanced"
    
    if true_peak > -0.5 or clipping_ratio > 0.1:
        profile.headroom_feel = "cramped"
    elif true_peak < -6 or lufs < -18:
        profile.headroom_feel = "empty"
    else:
        profile.headroom_feel = "comfortable"
    
    return profile


def _get_genre_from_perceptual(profile: PerceptualProfile, analysis: dict) -> tuple:
    """Detecta género: (genre, confidence)"""
    genre_scores = {}
    lufs = analysis.get("loudness_integrated", -14)
    plr = analysis.get("plr_db", 8)
    lra = analysis.get("lra_lu", 4)
    transient_density = analysis.get("transient_density", 0.5)
    centroid = analysis.get("spectral_centroid", 3000)
    
    if lufs > -7 and profile.frequency_balance == "bass_heavy" and plr < 8:
        genre_scores["trap"] = 0.85
    if lufs < -13 and plr > 12 and lra > 6 and profile.dynamic_feel == "loose":
        genre_scores["balada"] = 0.80
    if -10 < lufs < -8 and 8 < plr < 14 and transient_density > 0.6:
        genre_scores["rock"] = 0.75
    if plr > 16 and centroid < 3000 and profile.clarity == "clear":
        genre_scores["podcast"] = 0.80
    if plr > 12 and profile.presence_feel == "distant" and profile.tonal_balance == "dark":
        genre_scores["ambient"] = 0.75
    if -10 < lufs < -7 and 6 < plr < 12 and profile.presence_feel == "present":
        genre_scores["pop"] = 0.70
    if lufs > -6 and plr < 6 and profile.frequency_balance == "bass_heavy":
        genre_scores["edm"] = 0.75
    
    return max(genre_scores.items(), key=lambda x: x[1]) if genre_scores else ("mixed", 0.3)


def _get_perceptual_diagnosis(profile: PerceptualProfile) -> str:
    """Diagnóstico en lenguaje natural"""
    parts = []
    if profile.mix_cohesion == "glued":
        parts.append("Mezcla bien pegada")
    elif profile.mix_cohesion == "over_compressed":
        parts.append("Mezcla muy comprimida")
    else:
        parts.append("Mezcla con elementos desconectados")
    
    if profile.dynamic_feel == "tight":
        parts.append(", dinámica limitada")
    elif profile.dynamic_feel == "loose":
        parts.append(", dinámica muy abierta")
    
    if profile.tonal_balance == "dark":
        parts.append(", tonalidad oscura")
    elif profile.tonal_balance == "bright":
        parts.append(", tonalidad brillante")
    
    if profile.fatigue_risk > 0.7:
        parts.append(f". FATIGA: {int(profile.fatigue_risk*100)}%")
    elif profile.fatigue_risk > 0.4:
        parts.append(f" ({int(profile.fatigue_risk*100)}% fatiga)")
    
    return "".join(parts).rstrip(",") if parts else "Mezcla promedio"


# Valores neutros de partida: no representan ningún género en particular, son
# sólo el punto de referencia que se usa si la IA no está disponible y hay
# que recurrir a la heurística de respaldo (ver _fallback_custom_params).
_NEUTRAL_PARAMS: dict = {
    "input_gain_db": 0.0, "target_peak": 0.95, "use_lufs_normalize": False, "target_lufs": -12.0,
    "hp_cutoff": 35.0, "lp_bypass": True, "lp_cutoff": 18000.0,
    "high_shelf_gain_db": 1.5, "high_shelf_freq_hz": 8000.0,
    "eq1_freq": 100.0, "eq1_gain": 0.0, "eq1_q": 1.0,
    "eq2_freq": 400.0, "eq2_gain": 0.0, "eq2_q": 1.1,
    "eq3_freq": 2500.0, "eq3_gain": 0.0, "eq3_q": 1.0,
    "eq4_freq": 9000.0, "eq4_gain": 0.5, "eq4_q": 0.9,
    "eq5_freq": 200.0, "eq5_gain": 0.0, "eq5_q": 1.0,
    "eq6_freq": 1000.0, "eq6_gain": 0.0, "eq6_q": 1.0,
    "comp_threshold": 0.55, "comp_ratio": 2.2, "comp_attack_ms": 12.0, "comp_release_ms": 120.0, "comp_makeup_db": 1.0,
    "comp_stereo_link": True,
    "transient_attack": 0.0, "transient_sustain": 0.0,
    "mb_bypass": False,
    "mb_low_crossover": 150.0, "mb_high_crossover": 4000.0,
    "mb_low_threshold": 0.60, "mb_low_ratio": 2.0, "mb_low_attack_ms": 20.0, "mb_low_release_ms": 150.0, "mb_low_makeup_db": 0.3,
    "mb_mid_threshold": 0.62, "mb_mid_ratio": 1.8, "mb_mid_attack_ms": 15.0, "mb_mid_release_ms": 120.0, "mb_mid_makeup_db": 0.3,
    "mb_high_threshold": 0.65, "mb_high_ratio": 1.6, "mb_high_attack_ms": 8.0, "mb_high_release_ms": 90.0, "mb_high_makeup_db": 0.2,
    # Multibanda-estéreo, glue, clipper, de-esser y EQ de resonancias arrancan
    # BYPASSEADOS por default: son correcciones/refinamientos puntuales, no
    # algo que todo track necesite — si la IA no tiene motivo para tocarlos
    # (o falla y cae a la heurística), lo correcto es dejarlos apagados en
    # vez de aplicar valores inventados sin que el análisis lo justifique.
    "mb_stereo_bypass": True,
    "mb_stereo_low_width": 0.9, "mb_stereo_mid_width": 1.0, "mb_stereo_high_width": 1.0,
    "mb_stereo_low_crossover": 150.0, "mb_stereo_high_crossover": 4000.0,
    "saturation_drive": 0.1, "saturation_mode": "tape", "saturation_mix": 0.2,
    "mid_gain_db": 0.0, "side_gain_db": 0.0, "stereo_width_amount": 1.05,
    "use_stereo_enhancer": False, "enhancer_bass_mono_freq": 120.0, "haas_delay_ms": 0.0,
    "reverb_size": 0.2, "reverb_wet": 0.02,
    "low_end_mono_freq": 120.0, "low_end_mono_amount": 0.0,
    "glue_bypass": True,
    "glue_threshold_db": -4.0, "glue_ratio": 2.0, "glue_attack_ms": 30.0, "glue_release_ms": 120.0, "glue_makeup_db": 0.0,
    "clipper_bypass": True, "clipper_mode": "soft", "clipper_ceiling": 0.98, "clipper_drive_db": 0.0,
    "dyneq_bypass": True,
    "dyneq_freq": 3000.0, "dyneq_q": 2.5, "dyneq_threshold_db": -18.0,
    "dyneq_ratio": 3.0, "dyneq_attack_ms": 3.0, "dyneq_release_ms": 80.0, "dyneq_max_reduction_db": 12.0,
    "ms_eq_bypass": True,
    "ms_mid_freq": 250.0, "ms_mid_gain": 0.0, "ms_mid_q": 1.0,
    "ms_side_freq": 8000.0, "ms_side_gain": 0.0, "ms_side_q": 1.0,
    "ms_comp_bypass": True,
    "ms_comp_mid_threshold_db": -18.0, "ms_comp_mid_ratio": 2.0,
    "ms_comp_mid_attack_ms": 15.0, "ms_comp_mid_release_ms": 120.0, "ms_comp_mid_makeup_db": 0.0,
    "ms_comp_side_threshold_db": -18.0, "ms_comp_side_ratio": 2.0,
    "ms_comp_side_attack_ms": 15.0, "ms_comp_side_release_ms": 120.0, "ms_comp_side_makeup_db": 0.0,
    "reso_bypass": True,
    "reso_freq": 1200.0, "reso_q": 3.0, "reso_threshold_db": -18.0,
    "reso_ratio": 3.0, "reso_attack_ms": 5.0, "reso_release_ms": 100.0, "reso_max_reduction_db": 8.0,
    "nr_bypass": True, "nr_strength": 0.5, "nr_noise_sample_sec": 0.5,
    "eq_mode": "iir",
    "limiter_ceiling": 0.96, "limiter_release_ms": 55.0,
}

AUTO_MASTER_SYSTEM_PROMPT = """Sos Laia, la ingeniera de mastering de IA integrada en la app MASTER. \
Tu trabajo es decidir de forma 100% autónoma CADA parámetro de la cadena de mastering para el \
track del usuario, con el mismo criterio, cuidado y "consciencia" que aplicaría una ingeniera de \
mastering de estudio de primer nivel escuchando y midiendo el track antes de tocar un solo knob. \
El usuario no va a tocar nada manualmente: confía por completo en tu criterio profesional. \
Trabajás en cinco fases, en este orden, y tu reasoning final debe reflejar ese razonamiento:

FASE 1 — ANÁLISIS: ya tenés decenas de métricas reales del track (ver más abajo): loudness \
integrado y de corto plazo, true peak, PLR, LRA, dinámica global y por banda (graves/medios/agudos), \
balance espectral de 7 bandas + centroid/rolloff/flatness, correlación estéreo global y por banda, \
compatibilidad mono, DC offset, clipping, silencio y densidad de transientes. Leelas todas \
antes de decidir nada: son tu diagnóstico, no un formulario a ignorar.

FASE 2 — DECISIÓN INTELIGENTE: a partir de ese diagnóstico, identificá los 2-4 problemas o \
características más importantes de ESTE track puntual (p.ej. "muy comprimido y con exceso de \
graves", o "dinámico pero apagado en agudos", o "buena dinámica, sólo necesita loudness") y \
definí una estrategia de mastering coherente con eso: qué tan agresiva debe ser la compresión, \
si conviene EQ correctiva o de color, cuánto loudness final tiene sentido para el carácter del \
track (no todo tiene que llegar a -6 LUFS), y si el estéreo/saturación necesitan ajuste. \
Dos tracks distintos con métricas distintas DEBEN terminar con parámetros distintos — nunca \
apliques siempre la misma combinación "por defecto".

FASE 3 — CONSTRUCCIÓN DE LA CADENA DSP: traducí la estrategia de la Fase 2 a valores concretos \
de cada etapa de la cadena (en este orden de señal: input gain → high-pass/low-pass → EQ correctiva \
(6 bandas paramétricas, eq1..eq6) + de-esser (dyneq_*) + EQ dinámica de resonancias (reso_*) → EQ \
M/S (ms_*) → compresor de banda ancha → tonal shelf/EQ de color → multibanda (mb_*) → transient \
shaper → saturación → estéreo (mid/side, ancho, multibanda mb_stereo_*, enhancer/haas) → sub-bass \
mono (low_end_mono_*) → glue compressor (glue_*) → clipper → limiter). Guía de criterio (no son \
reglas rígidas, usalas con sentido común de ingeniería, cruzando SIEMPRE con los números reales \
del análisis):
- Dinámica: si dynamic_range_db o el crest factor por banda ya son bajos (muy comprimido), usá \
compresión y limiter más suaves para no sobre-comprimir; si son altos, podés compensar con más \
ratio/threshold más bajo. LRA muy chico también es señal de sobre-compresión previa.
- Balance espectral: corregí excesos o faltantes de energía en sub-bajos/bajos/medios/presencia/aire \
con hp_cutoff, high_shelf_gain_db/freq_hz y las 6 bandas de EQ paramétrico (eqN_freq/gain/q). El \
centroid y rolloff espectral te dicen si el track suena "oscuro" o "brillante" en términos objetivos. \
Usá eq_mode="linear_phase" SOLO si necesitás una corrección quirúrgica (corte angosto, alto Q) donde \
la fase importa; para EQ de color amplio, iir es más liviano y suena igual de bien.
- De-esser y resonancias (dyneq_*, reso_*): son EQ dinámica, no estática — solo actúan cuando la \
señal supera el threshold en esa frecuencia puntual. Activalos (bypass=false) SOLO si el análisis \
sugiere sibilancia o resonancias problemáticas puntuales (picos angostos y consistentes en el \
balance espectral, spectral_flatness muy baja en una zona acotada); no los uses como reemplazo de \
la EQ estática de banda ancha.
- EQ M/S (ms_*): correctivo fino de mid vs. side, independiente del ancho estéreo general. Útil \
p.ej. para bajar graves del side (mantenerlos centrados) sin tocar los graves del mid. Dejalo \
bypasseado salvo que el análisis de correlación por banda lo justifique.
- Estéreo: si mono_compatibility_db es muy negativo o la correlación por banda en graves es baja, \
NO ensanches más el estéreo (dejá stereo_width_amount y mb_stereo_*_width cerca de 1.0), activá \
low_end_mono_amount (mono forzado por debajo de low_end_mono_freq) y considerá enhancer_bass_mono_freq \
más alto para mantener los graves centrados. Los parámetros multibanda (mb_*, mb_stereo_*) y mid/side \
son correcciones finas; no los actives agresivamente salvo que el análisis lo justifique.
- Glue compressor (glue_*): compresión de bus muy suave (ratio bajo, threshold alto) para "pegar" el \
mix antes del limiter — no es un segundo compresor de banda ancha agresivo. Útil en mixes con \
elementos que suenan desconectados entre sí; conservador con el resto.
- Clipper: recorte previo al limiter para quitar picos puntuales sin que el limiter tenga que \
trabajar tanto (menos pumping). Usalo con drive bajo (unos pocos dB) si true_peak_db/clipping_ratio \
ya muestran el track muy caliente y el limiter solo no alcanza sin sonar forzado; clipper_mode="hard" \
es más agresivo/audible que "soft".
- True peak / clipping: si true_peak_db o clipping_ratio ya muestran problemas, usá limiter_ceiling_db \
más conservador (≤ -0.5 dB aprox.) y no agregues makeup gain innecesario.
- Densidad de transientes: material muy percusivo (transient_density alta, trap/metal) tolera \
attack del compresor más lento y más transient shaping; material sostenido (baladas, ambient) pide \
attack más rápido y compresión más suave para no aplastar el groove.
- Loudness objetivo y ceiling del limiter: dependen de la plataforma elegida (si elegís una) y de \
cuánto necesita "calentarse" el track según su LUFS actual y su PLR (un PLR alto = mucho margen \
para subir loudness sin destruir la dinámica; un PLR bajo = ya está caliente, sé conservador).
- Reducción de ruido (nr_*): SOLO si hay ruido de fondo real evidente en el análisis (silence_ratio \
alto con piso de ruido notable, o el usuario lo menciona); no es parte del mastering normal.
- Sé conservador con saturación, reverb y haas: son color, no arreglos — nunca la solución a un \
problema técnico real.

FASE 4 — OPTIMIZACIÓN: después de tu decisión, el sistema renderiza un preview real con estos \
parámetros y vuelve a medir LUFS logrado. Si no coincide con el objetivo, se hace una corrección \
automática de gain-staging (makeup del compresor / input gain) sin tocar tu diseño tonal ni \
dinámico.

FASE 5 — VERIFICACIÓN: con esos parámetros ya corregidos, se vuelve a renderizar y esta vez se \
mide TODO de nuevo (true peak, clipping real, rango dinámico, compatibilidad mono) — no solo el \
LUFS. Si el true peak se escapó del ceiling del limiter, si hay clipping real, si el rango \
dinámico colapsó de forma no intencional respecto al track original, o si el estéreo quedó mal \
fasado en mono, se hace una corrección puntual y acotada (bajar el ceiling, bajar el makeup, \
relajar el ratio del compresor, o reducir el ancho estéreo, según corresponda) — sin tocar tu \
criterio de EQ ni la estrategia general de la Fase 2.

No necesitás simular ninguna de las dos fases vos: por eso es más importante que definas bien \
EQ, dinámica y estéreo con buen criterio de ingeniería que perseguir un LUFS exacto de memoria \
o forzar el sistema con valores extremos "por las dudas" — la verificación de la Fase 5 va a \
atrapar excesos objetivos igual, pero no puede arreglar una mala decisión tonal.

Rangos válidos (el motor de audio rechaza cualquier valor fuera de estos límites, así que \
mantenete siempre dentro de ellos):
{ranges_block}

saturation_mode sólo puede ser "tape" o "tube". Los campos use_lufs_normalize, mb_bypass y \
use_stereo_enhancer son booleanos (true/false).

Respondé ÚNICAMENTE con un objeto JSON, sin texto adicional, sin markdown, con TODOS los campos \
numéricos/booleanos de la cadena (los mismos que se listan en los rangos de arriba, más \
saturation_mode), y además:
{{
  "platform": "<una de las plataformas listadas abajo, EXACTAMENTE como está escrita, o null>",
  "reasoning": "<4-6 oraciones en español rioplatense explicando el diagnóstico (Fase 1-2) y las \
decisiones más importantes de la cadena (Fase 3) que tomaste, citando los números concretos del \
análisis (LUFS, true peak, dinámica por banda, balance espectral, estéreo, etc.) y por qué \
elegiste esos valores puntuales de compresor/EQ/limiter>"
}}

Plataformas / targets de loudness disponibles: {platforms_block}

{audio_context}
"""


def _clamp(value, lo, hi):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, value))


def _resolve_target_lufs(result: dict) -> Optional[float]:
    """Determina el LUFS objetivo de la Fase 4 (Optimización): el de la plataforma \
    elegida si hay una, si no el target_lufs que la propia IA/heurística calculó."""
    from mastering import PLATFORM_LOUDNESS_TARGETS

    platform = result.get("platform")
    if platform and platform in PLATFORM_LOUDNESS_TARGETS:
        return float(PLATFORM_LOUDNESS_TARGETS[platform]["lufs"])
    target = result.get("target_lufs")
    try:
        return float(target)
    except (TypeError, ValueError):
        return None


def _optimize_and_verify_mix(result: dict, audio, sr, pre_analysis: Optional[dict] = None,
                              max_iters: int = 3, tolerance_db: float = 0.4) -> list:
    """FASE 4+5 fusionadas — Optimización y verificación real: renderiza UN preview \
    (~25s, del medio del track) con los parámetros que decidió la IA (o la heurística \
    de respaldo) y, sobre ESE MISMO render, chequea todo lo que antes vivía en dos \
    fases separadas con renders duplicados:
      1) LUFS logrado vs. objetivo (gain-staging) → corrige el makeup gain del \
         compresor de banda ancha.
      2) True peak que se escapa del ceiling del limiter → baja el ceiling.
      3) Clipping real (recorte duro) → baja el makeup gain.
      4) Colapso de rango dinámico NO intencional — comparado contra el track \
         ORIGINAL (pre_analysis), no contra un piso fijo: un track que ya venía muy \
         comprimido puede terminar con DR bajo a propósito, eso no es un error → \
         relaja el ratio del compresor.
      5) Compatibilidad mono muy degradada tras el procesamiento estéreo → reduce \
         el ancho estéreo.

    MEJORA (perf): esto reemplaza a las dos funciones separadas que había antes \
    (_optimize_gain_staging + _verify_and_correct_mix), cada una con su propio \
    recorte de preview y hasta 4+2=6 renders totales por decisión de Laia. Acá se \
    recorta el preview UNA sola vez y cada iteración renderiza una sola vez — hasta \
    max_iters renders en vez de 6, revisando las 5 cosas sobre el mismo render en \
    vez de una fase completa por separado para cada una.

    No toca EQ, dinámica multibanda ni estéreo más allá de lo puntual de arriba — es \
    el control de calidad determinístico que una ingeniera real haría de oído después \
    de escuchar el primer render, no una segunda decisión completa de la IA (eso \
    requeriría otra llamada al modelo, fuera de esta fase por costo/latencia).

    Se salta silenciosamente si no hay audio disponible, igual que antes."""
    if audio is None or sr is None:
        return []

    from mastering import apply_mastering_chain, _crop_preview, analyze_audio

    target_lufs = _resolve_target_lufs(result)
    chain_keys = set(PARAM_RANGES.keys()) | set(BOOL_PARAM_FIELDS) | set(STRING_ENUM_FIELDS.keys())
    try:
        preview = _crop_preview(audio, sr, 25.0)
    except Exception as e:
        logger.warning(f"Optimización/verificación (Fases 4+5) abortada, no se pudo recortar preview: {e}")
        return []
    if preview.shape[-1] < sr * 2:
        return []  # track demasiado corto para un preview útil

    pre_dr = (pre_analysis or {}).get("dynamic_range_db")
    notes = []
    for i in range(max_iters):
        chain_params = {k: v for k, v in result.items() if k in chain_keys}
        try:
            rendered, meters = apply_mastering_chain(preview, sr, oversample_mode="fast", **chain_params)
        except Exception as e:
            logger.warning(f"Optimización/verificación (Fases 4+5) abortada, no se pudo renderizar preview: {e}")
            break

        fixes = []

        # 1) LUFS logrado vs. objetivo (gain-staging) — mismo chequeo que antes
        #    hacía _optimize_gain_staging en su propio loop.
        if target_lufs is not None:
            achieved_lufs = meters.get("post_limiter", {}).get("lufs")
            if achieved_lufs is not None:
                delta = target_lufs - achieved_lufs
                if abs(delta) > tolerance_db:
                    old_makeup = float(result.get("comp_makeup_db", 0.0))
                    new_makeup = _clamp(old_makeup + delta, *PARAM_RANGES["comp_makeup_db"])
                    if new_makeup is not None and abs(new_makeup - old_makeup) > 0.05:
                        result["comp_makeup_db"] = round(new_makeup, 3)
                        fixes.append(
                            f"LUFS {achieved_lufs:.1f} vs. objetivo {target_lufs:.1f} → "
                            f"makeup gain corregido en {delta:+.1f}dB"
                        )

        # Para el resto de los chequeos hace falta el análisis completo del
        # render (true peak, clipping, dinámica, mono) — se calcula UNA vez
        # sobre el mismo `rendered` de arriba, no un render aparte.
        try:
            post = analyze_audio(rendered, sr)
        except Exception as e:
            logger.warning(f"Verificación (Fase 5) abortada, no se pudo analizar el preview renderizado: {e}")
            post = {}

        # 2) True peak escapado del ceiling del limiter.
        ceiling_lin = float(result.get("limiter_ceiling", 0.98))
        ceiling_db = _linear_to_db(ceiling_lin)
        tp = post.get("true_peak_db")
        if tp is not None and tp > ceiling_db + 0.1:
            overshoot = tp - ceiling_db
            new_ceiling_db = ceiling_db - overshoot
            new_ceiling_lin = _clamp(_db_to_linear(new_ceiling_db), *PARAM_RANGES["limiter_ceiling"])
            if new_ceiling_lin is not None and abs(new_ceiling_lin - ceiling_lin) > 0.002:
                result["limiter_ceiling"] = round(new_ceiling_lin, 4)
                fixes.append(
                    f"true peak {tp:.2f}dBTP superaba el ceiling del limiter ({ceiling_db:.2f}dB) "
                    f"por {overshoot:.2f}dB → ceiling bajado a {new_ceiling_db:.2f}dB"
                )

        # 3) Clipping real (recorte duro).
        clip = post.get("clipping_ratio") or 0.0
        if clip > 0.001:
            old_makeup2 = float(result.get("comp_makeup_db", 0.0))
            new_makeup2 = _clamp(old_makeup2 - 1.0, *PARAM_RANGES["comp_makeup_db"])
            if new_makeup2 is not None and abs(new_makeup2 - old_makeup2) > 0.05:
                result["comp_makeup_db"] = round(new_makeup2, 3)
                fixes.append(
                    f"clipping real detectado ({clip * 100:.3f}% de las muestras) → "
                    f"se bajó el makeup gain del compresor en 1dB más"
                )

        # 4) Colapso de rango dinámico no intencional (vs. el track original).
        post_dr = post.get("dynamic_range_db")
        if post_dr is not None and pre_dr is not None and pre_dr > 6.0 and post_dr < 3.0:
            old_ratio = float(result.get("comp_ratio", 2.0))
            new_ratio = _clamp(old_ratio * 0.75, *PARAM_RANGES["comp_ratio"])
            if new_ratio is not None and abs(new_ratio - old_ratio) > 0.05:
                result["comp_ratio"] = round(new_ratio, 3)
                fixes.append(
                    f"rango dinámico colapsado a {post_dr:.1f}dB (el original tenía "
                    f"{pre_dr:.1f}dB, no venía tan comprimido) → se relajó el ratio del "
                    f"compresor de {old_ratio:.2f}:1 a {new_ratio:.2f}:1"
                )

        # 5) Compatibilidad mono degradada por el procesamiento estéreo.
        mono_compat = post.get("mono_compatibility_db")
        if mono_compat is not None and mono_compat < -6.0:
            old_width = float(result.get("stereo_width_amount", 1.0))
            new_width = _clamp(old_width * 0.85, *PARAM_RANGES["stereo_width_amount"])
            if new_width is not None and abs(new_width - old_width) > 0.02:
                result["stereo_width_amount"] = round(new_width, 3)
                fixes.append(
                    f"compatibilidad mono degradada a {mono_compat:.1f}dB tras el procesamiento "
                    f"→ se redujo el ancho estéreo de {old_width:.2f} a {new_width:.2f}"
                )

        if not fixes:
            notes.append(
                f"Optimización/verificación: preview #{i + 1} dentro de lo esperado en todas "
                f"las métricas (LUFS, true peak, clipping, dinámica, compatibilidad mono) "
                f"— sin correcciones adicionales."
            )
            break
        notes.append(f"Iteración #{i + 1}: " + "; ".join(fixes) + ".")

    return notes


def _apply_optimization(result: dict, audio, sr, pre_analysis: Optional[dict] = None) -> dict:
    """Corre la optimización + verificación fusionada (Fases 4+5: gain-staging, true \
    peak, clipping, dinámica y mono, todo sobre los mismos renders) y, si hubo \
    correcciones, las suma al reasoning que ya trae `result`.

    `pre_analysis` es el análisis del track ORIGINAL (antes de cualquier \
    procesamiento) — lo necesita el chequeo de rango dinámico para juzgar si un DR \
    bajo es un problema nuevo o si el track ya venía así."""
    try:
        notes = _optimize_and_verify_mix(result, audio, sr, pre_analysis)
    except Exception as e:
        logger.warning(f"Optimización/verificación (Fases 4+5) falló, se devuelve la decisión sin ajustar: {e}")
        notes = []
    if notes:
        base = (result.get("reasoning") or "").rstrip()
        if base and not base.endswith((".", "!", "?")):
            base += "."
        result["reasoning"] = (base + " " + " ".join(notes)).strip()
    return result


async def decide_mastering(analysis: Optional[dict], platform_options: list,
                            audio=None, sr: Optional[int] = None) -> dict:
    """Le pide al modelo que calcule, a mano, todos los parámetros de la cadena \
    de mastering (compresor, EQ de 4 bandas, multibanda, estéreo, limiter, etc.) \
    en base al análisis del track — NO elige entre presets predefinidos.

    `platform_options` es una lista de claves de plataforma válidas. Si se pasan \
    `audio`/`sr` (el mismo array ya cargado que se usó para `analyze_audio`), se \
    corre además la Fase 4 (Optimización): un preview real se renderiza con los \
    parámetros decididos y, si el LUFS logrado no coincide con el objetivo, se \
    corrige el makeup gain e itera hasta converger.

    Devuelve siempre un dict con todos los parámetros validados y clampeados \
    a rango, más 'platform' y 'reasoning', aunque la IA falle o no esté \
    disponible (usa una heurística de respaldo que también calcula los \
    valores a partir del análisis, no de un preset).
    """
    if not analysis:
        raise ValueError(
            "Se necesita analizar el track antes de poder decidir el mastering automático."
        )

    client = _get_client()
    if client is None:
        raise RuntimeError(
            f"La IA no está disponible ({get_unavailable_reason()}). "
            "No se puede realizar auto-mastering sin el modelo de IA. "
            "No se usan heurísticas ni parámetros preestablecidos."
        )

    float_field_names = [k for k in PARAM_RANGES if k not in DB_EXPOSED_FIELDS]
    float_field_names += [_db_field_name(k) for k in DB_EXPOSED_FIELDS]
    enum_fields_hint = "\n".join(
        f'- "{field}": string, obligatorio, uno de {", ".join(repr(v) for v in values)}.'
        for field, values in STRING_ENUM_FIELDS.items()
    )
    json_fields_hint = (
        "Devolvé SOLO un objeto JSON plano (sin markdown, sin texto extra) con estas claves:\n"
        f"- Como número (float), obligatorio en todos: {', '.join(float_field_names)}.\n"
        f"- Como booleano (true/false), obligatorio en todos: {', '.join(BOOL_PARAM_FIELDS)}.\n"
        f"{enum_fields_hint}\n"
        f'- "platform": string, una de estas opciones o null: {", ".join(platform_options) if platform_options else "(ninguna)"}.\n'
        '- "reasoning": string, tu razonamiento (Fases 1-3) en 3-6 oraciones.'
    )

    ranges_block = _param_ranges_text()
    platforms_block = ", ".join(platform_options) if platform_options else "(ninguna)"
    system_prompt = AUTO_MASTER_SYSTEM_PROMPT.format(
        ranges_block=ranges_block,
        platforms_block=platforms_block,
        audio_context=build_audio_context(analysis),
    ) + "\n\n" + json_fields_hint

    data = None
    try:
        contents = [{"role": "user", "parts": [
            {"text": "Calculá los parámetros de mastering para este track y devolvé solo el JSON."}
        ]}]
        # PRECISIÓN: esta es la llamada que calcula ~90 parámetros numéricos
        # interdependientes de toda la cadena — la tarea más compleja de todo
        # el asistente. Antes corría con thinking_budget=0 (pensamiento
        # apagado a propósito) y sin temperature (default de gemini-2.5-flash
        # = 1.0 en escala 0-2, bastante alta). Ambas cosas priorizaban
        # velocidad/costo por sobre precisión en la única llamada donde más
        # importa lo contrario:
        # - thinking_budget=-1 (dinámico): el modelo decide cuánto "pensar"
        #   según la complejidad real del track, en vez de responder de un
        #   tirón sin razonar la interdependencia entre etapas.
        # - temperature=0.3: mucha menos variabilidad corrida a corrida para
        #   una tarea que es esencialmente cálculo técnico, no creatividad.
        #   El campo "reasoning" (texto) sigue leyéndose natural con este
        #   valor; no hace falta temperature alta para que no suene robótico.
        # BUGFIX: maxOutputTokens en la API de Gemini es un presupuesto
        # COMPARTIDO entre los tokens de "pensamiento" (invisibles) y el
        # texto de salida real. Con thinking_budget=-1 (dinámico, sin techo)
        # el modelo podía gastar la mayor parte de los 4096 tokens pensando
        # y dejar el JSON de salida cortado a mitad de generación (JSON
        # inválido, "el asistente no anda" aunque el request nunca fallaba
        # — silenciosamente caía al heurístico de respaldo). Subido a 8192
        # para dejar margen real tanto al pensamiento dinámico como al JSON
        # completo (~90 campos + reasoning).
        raw = await _gemini_generate_content(
            system_prompt, contents, max_output_tokens=8192,
            thinking_budget=-1, temperature=0.3,
        )
        data = _extract_json_object(raw) if raw else None
        if data is None and raw is not None:
            logger.error(f"JSON de auto-mastering ilegible. Raw: {raw[:400]!r}")
    except Exception as e:
        logger.error(f"No se pudo obtener/parsear la decisión de mastering de la IA: {e}")

    if not data:
        raise RuntimeError(
            "La IA no devolvió una respuesta válida para auto-mastering. "
            "No se usan heurísticas ni parámetros preestablecidos. "
            "Intentá de nuevo."
        )

    result = {}
    for key, (lo, hi) in PARAM_RANGES.items():
        if key in DB_EXPOSED_FIELDS:
            continue
        try:
            clamped = _clamp(float(data.get(key, _NEUTRAL_PARAMS.get(key))), lo, hi)
        except (TypeError, ValueError):
            clamped = None
        result[key] = clamped if clamped is not None else _NEUTRAL_PARAMS.get(key)
        result[key] = round(result[key], 3)

    for key in DB_EXPOSED_FIELDS:
        linear_val = _resolve_db_exposed_param(key, data, default_linear=_NEUTRAL_PARAMS.get(key))
        result[key] = round(linear_val if linear_val is not None else _NEUTRAL_PARAMS.get(key), 4)

    for key in BOOL_PARAM_FIELDS:
        result[key] = bool(data.get(key, _NEUTRAL_PARAMS.get(key, False)))

    for field, valid_values in STRING_ENUM_FIELDS.items():
        v = data.get(field)
        result[field] = v if v in valid_values else _NEUTRAL_PARAMS.get(field, valid_values[0])

    platform = data.get("platform")
    result["platform"] = platform if platform in (platform_options or []) else None

    result["reasoning"] = str(data.get("reasoning") or "").strip() or (
        "El asistente calculó estos parámetros según el análisis técnico del track."
    )

    return _apply_optimization(result, audio, sr, pre_analysis=analysis)


def _extract_json_object(raw: str) -> Optional[dict]:
    """Intenta rescatar un dict JSON de una respuesta de texto imperfecta:
    quita fences de markdown, recorta al primer '{'...último '}', y prueba
    arreglos comunes (comas colgantes, comillas simples) antes de rendirse.
    """
    import json
    import re

    if not raw:
        return None
    text = raw.strip()
    # Sacar fences tipo ```json ... ``` o ``` ... ```
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    candidates = [text]
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            pass
        # Arreglo básico: comas colgantes antes de } o ]
        fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            return json.loads(fixed)
        except Exception:
            continue
    return None



# ── IA para mix multistem ──────────────────────────────────────────────────────

MIX_SYSTEM_PROMPT = """Sos un ingeniero de mezcla profesional con 20 años de experiencia.
Recibís el análisis acústico de varios stems (pistas individuales de una canción) y tenés que
sugerir los parámetros óptimos de mezcla para cada uno.

Tu tarea es analizar las características de cada stem (LUFS, peak, LRA, espectro, correlación,
tipo de stem) y calcular parámetros que logren una mezcla equilibrada, coherente y profesional.

REGLAS ESTRICTAS:
- Devolvé SOLO un objeto JSON válido, sin markdown, sin texto extra.
- El objeto tiene una clave por stem (el nombre exacto del stem como te lo pasan).
- Cada stem tiene EXACTAMENTE estos campos:

  gain_db: float [-24, +12] — ganancia principal. Ajustá para equilibrar niveles.
  pan: float [-1.0, +1.0] — paneo. 0=centro, -1=izquierda, +1=derecha.
  hp_cutoff_hz: float [20, 500] — high-pass. Sacá rumble innecesario según el tipo de stem.
  lp_cutoff_hz: float [2000, 20000] — low-pass. Usá 20000 si no necesitás corte.
  eq_low_gain_db: float [-12, +12] — EQ graves (100 Hz por defecto).
  eq_lomid_gain_db: float [-12, +12] — EQ low-mid (500 Hz por defecto).
  eq_himid_gain_db: float [-12, +12] — EQ high-mid (3000 Hz por defecto).
  eq_high_gain_db: float [-12, +12] — EQ agudos (10000 Hz por defecto).
  comp_enabled: bool — activar compresor.
  comp_threshold: float [0.01, 1.0] — threshold lineal (0.5 = -6dBFS aprox).
  comp_ratio: float [1.0, 20.0] — ratio de compresión.
  comp_attack_ms: float [0.1, 100.0] — attack.
  comp_release_ms: float [10, 500] — release.
  comp_makeup_db: float [0, 24] — makeup gain post-compresor.
  transient_attack: float [-1.0, +1.0] — ajuste de transientes (+1=más punch, -1=menos).
  transient_sustain: float [-1.0, +1.0] — ajuste de sustain.
  stereo_width_amount: float [0.0, 2.0] — ancho estéreo (1.0=original, 0=mono, 2=extra wide).
  sidechain_trigger_name: string o null — nombre del stem que hace ducking sobre éste (null=desactivado).
  reasoning: string — explicación breve de tus decisiones para ESTE stem (1-2 oraciones).

GUÍAS POR TIPO DE STEM:
- kick: hp 20Hz, comp agresiva (ratio 4-6), transient_attack alto, poco EQ high.
- snare: hp 80Hz, comp media, transient_attack medio, presencia en 3-5kHz.
- bass: hp 30Hz, comp agresiva, sidechain del kick si hay kick.
- vocals: hp 80-120Hz, comp suave (ratio 2-3), de-essing implícito bajando 6-8kHz si hay sibilancia.
- guitar: hp 80Hz, comp media, pan levemente off-center.
- synth/pad: lp según contexto, stereo_width alto, comp suave.
- drums/perc: hp según tipo, comp media.
- fx/atm: lp agresivo, stereo_width alto, comp suave o desactivada.

Analizá los datos de cada stem y tomá decisiones que suenen musicalmente coherentes entre sí.
Si hay un kick y un bass, considerá sidechain del bass triggerado por el kick.
Equilibrá los LUFS/peaks entre stems para que ninguno domine injustamente.
"""


async def decide_mix(stems_analysis: dict) -> dict:
    """Analiza los stems y sugiere parámetros de mezcla para cada uno.

    stems_analysis: { stem_name: { analysis_dict } }
    Devuelve: { stem_name: { param: value, ..., reasoning: str } }
    """
    if not stems_analysis:
        raise ValueError("Se necesita al menos un stem analizado.")

    # Construir el resumen de análisis para el prompt
    stems_summary = []
    for name, analysis in stems_analysis.items():
        stem_type = analysis.get("stem_type", "other")
        lufs = analysis.get("lufs", "N/A")
        peak = analysis.get("peak_db", "N/A")
        lra = analysis.get("lra", "N/A")
        corr = analysis.get("stereo_correlation", "N/A")
        spectrum = analysis.get("spectrum", {})
        channels = analysis.get("channels", 2)
        sr = analysis.get("sample_rate", 44100)
        duration = analysis.get("duration_sec", 0)

        spec_str = ", ".join(
            f"{k}: {v:.1f}dB" for k, v in spectrum.items()
        ) if spectrum else "N/A"

        stems_summary.append(
            f"Stem: \"{name}\" (tipo: {stem_type}, {channels}ch, {sr}Hz, {duration:.1f}s)\n"
            f"  LUFS: {lufs}, Peak: {peak} dBFS, LRA: {lra} LU\n"
            f"  Correlación estéreo: {corr}\n"
            f"  Espectro: {spec_str}"
        )

    user_prompt = (
        f"Tenés {len(stems_analysis)} stem(s) para mezclar:\n\n"
        + "\n\n".join(stems_summary)
        + "\n\nCalculá los parámetros de mezcla óptimos para cada stem y devolvé el JSON."
    )

    client = _get_client()

    if client is None:
        raise RuntimeError(
            f"La IA no está disponible ({get_unavailable_reason()}). "
            "No se pueden sugerir parámetros de mezcla sin el modelo de IA. "
            "No se usan heurísticas ni parámetros preestablecidos."
        )

    try:
        result = await _gemini_generate_content(
            system_prompt=MIX_SYSTEM_PROMPT,
            contents=[{"role": "user", "parts": [{"text": user_prompt}]}],
            max_output_tokens=4096,
        )
        raw = result.get("text", "")
        parsed = _extract_json_object(raw)
        if not parsed:
            raise ValueError("La IA no devolvió JSON válido.")
        return _validate_mix_params(parsed, stems_analysis)
    except Exception as e:
        logger.error(f"decide_mix error: {e}")
        raise RuntimeError(
            f"La IA no pudo sugerir parámetros de mezcla: {e}. "
            "No se usan heurísticas ni parámetros preestablecidos."
        )


def _validate_mix_params(params: dict, stems_analysis: dict) -> dict:
    """Clampea y valida los parámetros sugeridos por la IA para cada stem."""

    float_ranges = {
        "gain_db": (-24.0, 12.0),
        "pan": (-1.0, 1.0),
        "hp_cutoff_hz": (20.0, 500.0),
        "lp_cutoff_hz": (2000.0, 20000.0),
        "eq_low_gain_db": (-12.0, 12.0),
        "eq_lomid_gain_db": (-12.0, 12.0),
        "eq_himid_gain_db": (-12.0, 12.0),
        "eq_high_gain_db": (-12.0, 12.0),
        "comp_threshold": (0.01, 1.0),
        "comp_ratio": (1.0, 20.0),
        "comp_attack_ms": (0.1, 100.0),
        "comp_release_ms": (10.0, 500.0),
        "comp_makeup_db": (0.0, 24.0),
        "transient_attack": (-1.0, 1.0),
        "transient_sustain": (-1.0, 1.0),
        "stereo_width_amount": (0.0, 2.0),
        "sidechain_threshold": (0.01, 1.0),
        "sidechain_ratio": (1.0, 20.0),
    }

    stem_names = set(stems_analysis.keys())
    validated = {}

    for stem_name in stems_analysis:
        stem_params = params.get(stem_name, {})
        clean = {}

        for field, (lo, hi) in float_ranges.items():
            val = stem_params.get(field)
            if val is not None:
                try:
                    clean[field] = float(max(lo, min(hi, float(val))))
                except (TypeError, ValueError):
                    pass

        clean["comp_enabled"] = bool(stem_params.get("comp_enabled", False))

        # sidechain_trigger_name — debe ser un stem existente o null
        sc = stem_params.get("sidechain_trigger_name")
        clean["sidechain_trigger_name"] = sc if sc in stem_names and sc != stem_name else None

        clean["reasoning"] = str(stem_params.get("reasoning", ""))

        validated[stem_name] = clean

    return validated
