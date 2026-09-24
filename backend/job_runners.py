"""Workers de background para procesamiento de audio.

Este módulo contiene la lógica de ejecución de jobs que no debería vivir en
el punto de entrada HTTP. Las dependencias se inyectan mediante
``create_job_runners`` para mantenerlo testeable y evitar imports circulares.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Callable

import librosa
import soundfile as sf


logger = logging.getLogger(__name__)


def create_job_runners(
    *,
    jobs,
    cleanup_old: Callable[[], None],
    process_audio,
    process_audio_with_reference,
    normalize_by_lufs,
    separate_stems,
    separate_vocals_hq,
    analyze_stems_full,
    measure_lufs_integrated,
    stems_dir: str,
):
    """Construye los workers con las dependencias concretas de la aplicación."""

    def make_progress_cb(job_id: str):
        def _cb(pct: int, stage: str):
            if not jobs.exists(job_id):
                return
            jobs.update_job(job_id, progress=pct, stage=stage)
        return _cb

    def run_mastering_job(job_id: str, input_path: str, params: dict):
        jobs.update_job(job_id, status="processing", started_at=time.time(), progress=0, stage="Iniciando procesamiento")
        jobs.set_stage(job_id, "analyzing", progress=10)
        jobs.append_log(job_id, "Preparando análisis del archivo", stage="analyzing")
        jobs.snapshot_params(job_id, params)
        try:
            cleanup_old()
            jobs.append_log(job_id, "Procesando mastering con la cadena de audio", stage="rendering")
            jobs.set_stage(job_id, "rendering", progress=25)
            result = process_audio(input_path, progress_cb=make_progress_cb(job_id), **params)
            jobs.set_stage(job_id, "generating_preview", progress=85)
            jobs.append_log(job_id, "Render finalizado; preparando exportes y preview", stage="generating_preview")
            output_path = result.get("output_path")
            output_format = str(params.get("output_format", "wav")).lower()
            if output_path and os.path.exists(output_path):
                jobs.add_export(
                    job_id,
                    "master_final",
                    output_path,
                    version_name="master_final",
                    format=output_format,
                    bit_depth=params.get("output_bit_depth", 24),
                    target_lufs=params.get("target_lufs"),
                    platform_target=params.get("platform_target"),
                )
            jobs.update_job(job_id, status="done", result=result, finished_at=time.time(), progress=100, stage="Completado")
            jobs.append_log(job_id, f"Master finalizado correctamente: {output_path or 'sin ruta'}", stage="preview_ready")
            logger.info("Job %s done: %s", job_id, result.get("output_path"))
        except (ValueError, RuntimeError) as e:
            jobs.mark_failed(job_id, str(e), stage="failed", progress=0)
            jobs.append_log(job_id, f"Error en el job: {e}", stage="failed", level="error")
            logger.error("Job %s failed (value/runtime error): %s", job_id, e, exc_info=True)
        except OSError as e:
            jobs.mark_failed(job_id, str(e), stage="failed", progress=0)
            jobs.append_log(job_id, f"Error de sistema: {e}", stage="failed", level="error")
            logger.error("Job %s failed (OS error): %s", job_id, e, exc_info=True)
        except Exception as e:
            # Red de seguridad: TypeError, KeyError, AttributeError y cualquier
            # otro error no catalogado deben marcar el job como failed en
            # vez de dejarlo colgado en "processing" para siempre (antes un
            # TypeError inesperado en process_audio(**params) no era atrapado
            # aqui y el job quedaba en estado limbo).
            jobs.mark_failed(job_id, str(e), stage="failed", progress=0)
            jobs.append_log(job_id, f"Error inesperado: {e}", stage="failed", level="error")
            logger.error("Job %s failed (unexpected %s): %s", job_id, type(e).__name__, e, exc_info=True)
        finally:
            if os.path.exists(input_path):
                os.remove(input_path)

    def run_reference_job(job_id: str, input_path: str, reference_path: str, params: dict):
        jobs.update_job(job_id, status="processing", started_at=time.time(), progress=0, stage="Iniciando procesamiento")
        jobs.set_stage(job_id, "analyzing", progress=10)
        jobs.snapshot_params(job_id, params)
        try:
            cleanup_old()
            jobs.append_log(job_id, "Procesando mastering con referencia", stage="rendering")
            jobs.set_stage(job_id, "rendering", progress=25)
            result = process_audio_with_reference(input_path, reference_path, progress_cb=make_progress_cb(job_id), **params)
            output_path = result.get("output_path")
            if output_path and os.path.exists(output_path):
                jobs.add_export(
                    job_id,
                    "reference_master",
                    output_path,
                    version_name="reference_master",
                    format=str(params.get("output_format", "wav")).lower(),
                )
            jobs.update_job(job_id, status="done", result=result, finished_at=time.time(), progress=100, stage="Completado")
            logger.info("Job %s (reference match) done: %s", job_id, result.get("output_path"))
        except (ValueError, RuntimeError) as e:
            jobs.mark_failed(job_id, str(e), stage="failed", progress=0)
            jobs.append_log(job_id, f"Error en el job (reference): {e}", stage="failed", level="error")
            logger.error("Job %s (reference match) failed: %s", job_id, e, exc_info=True)
        except OSError as e:
            jobs.mark_failed(job_id, str(e), stage="failed", progress=0)
            jobs.append_log(job_id, f"Error de sistema (reference): {e}", stage="failed", level="error")
            logger.error("Job %s (reference match) failed (OS error): %s", job_id, e, exc_info=True)
        except Exception as e:
            jobs.mark_failed(job_id, str(e), stage="failed", progress=0)
            jobs.append_log(job_id, f"Error inesperado (reference): {e}", stage="failed", level="error")
            logger.error("Job %s (reference match) failed (unexpected %s): %s", job_id, type(e).__name__, e, exc_info=True)
        finally:
            if os.path.exists(input_path):
                os.remove(input_path)
            if os.path.exists(reference_path):
                os.remove(reference_path)

    def run_normalize_job(job_id: str, input_path: str, params: dict):
        jobs.update_job(job_id, status="processing", started_at=time.time(), progress=0, stage="Iniciando normalización")
        jobs.set_stage(job_id, "analyzing", progress=10)
        jobs.snapshot_params(job_id, params)
        try:
            cleanup_old()
            jobs.append_log(job_id, "Normalizando por LUFS", stage="rendering")
            jobs.set_stage(job_id, "rendering", progress=25)
            result = normalize_by_lufs(input_path, progress_cb=make_progress_cb(job_id), **params)
            output_path = result.get("output_path")
            if output_path and os.path.exists(output_path):
                jobs.add_export(
                    job_id,
                    "lufs_normalized",
                    output_path,
                    version_name="lufs_normalized",
                    format=str(params.get("output_format", "wav")).lower(),
                )
            jobs.update_job(job_id, status="done", result=result, finished_at=time.time(), progress=100, stage="Completado")
            logger.info("Job %s (lufs normalize) done: %s", job_id, result.get("output_path"))
        except (ValueError, RuntimeError) as e:
            jobs.mark_failed(job_id, str(e), stage="failed", progress=0)
            jobs.append_log(job_id, f"Error en el job (normalize): {e}", stage="failed", level="error")
            logger.error("Job %s (lufs normalize) failed: %s", job_id, e, exc_info=True)
        except OSError as e:
            jobs.mark_failed(job_id, str(e), stage="failed", progress=0)
            jobs.append_log(job_id, f"Error de sistema (normalize): {e}", stage="failed", level="error")
            logger.error("Job %s (lufs normalize) failed (OS error): %s", job_id, e, exc_info=True)
        except Exception as e:
            jobs.mark_failed(job_id, str(e), stage="failed", progress=0)
            jobs.append_log(job_id, f"Error inesperado (normalize): {e}", stage="failed", level="error")
            logger.error("Job %s (lufs normalize) failed (unexpected %s): %s", job_id, type(e).__name__, e, exc_info=True)
        finally:
            if os.path.exists(input_path):
                os.remove(input_path)

    def run_stems_job(job_id: str, input_path: str, mode: str = "demucs_4stem"):
        jobs.update_job(job_id, status="processing", started_at=time.time(), progress=0, stage="Iniciando separación")
        try:
            cleanup_old()
            audio, sr = librosa.load(input_path, sr=None, mono=False)
            if audio.ndim == 1:
                audio = audio[None, :]

            if mode == "vocals_hq":
                stems = separate_vocals_hq(audio, sr, progress_cb=make_progress_cb(job_id))
            else:
                stems = separate_stems(audio, sr, progress_cb=make_progress_cb(job_id))

            jobs.update_job(job_id, stage="Analizando stems", progress=96)
            # SERIE: análisis de stems sin subproceso. Antes corría dentro de un
            # ThreadPoolExecutor(max_workers=1) solo para tener timeout; como
            # ahora todo el procesamiento de audio es estrictamente secuencial,
            # se llama directo. Si analyze_stems_full se cuelga, el caller
            # (job_store) verá el job sin progreso y podrá cancelarlo.
            analysis = analyze_stems_full(stems, sr, measure_lufs_integrated)

            stem_dir = os.path.join(stems_dir, job_id)
            os.makedirs(stem_dir, exist_ok=True)
            stem_paths = {}
            for name, stem_audio in stems.items():
                out_path = os.path.join(stem_dir, f"{name}.wav")
                data_to_write = stem_audio.T if stem_audio.ndim == 2 else stem_audio
                sf.write(out_path, data_to_write, sr, subtype="PCM_24")
                stem_paths[name] = out_path

            jobs.update_job(
                job_id,
                status="done",
                finished_at=time.time(),
                progress=100,
                stage="Completado",
                stem_analysis=analysis,
                stem_paths=stem_paths,
                available_stems=list(stem_paths.keys()),
            )
            logger.info("Job %s (stems) done: %s", job_id, list(stem_paths.keys()))
        except (ValueError, RuntimeError) as e:
            jobs.update_job(job_id, status="error", error=str(e))
            logger.error("Job %s (stems) failed: %s", job_id, e, exc_info=True)
        except OSError as e:
            jobs.update_job(job_id, status="error", error=str(e))
            logger.error("Job %s (stems) failed (OS error): %s", job_id, e, exc_info=True)
        finally:
            if os.path.exists(input_path):
                os.remove(input_path)

    def run_one_click_stem_master_job(job_id: str, input_path: str, mode: str = "demucs_4stem"):
        """1-Click: separar stems → analizar → AI decide mix → mix → master → resultado."""
        import asyncio
        import numpy as np
        from stem_analysis import analyze_stems_full
        from ai_assistant import decide_mix
        from mixer import mix_and_master, StemParams, MixParams
        from mastering import PLATFORM_LOUDNESS_TARGETS

        jobs.update_job(job_id, status="processing", started_at=time.time(), progress=0,
                        stage="Separando stems")
        try:
            cleanup_old()
            audio, sr = librosa.load(input_path, sr=None, mono=False)
            if audio.ndim == 1:
                audio = audio[None, :]

            if mode == "vocals_hq":
                stems = separate_vocals_hq(audio, sr, progress_cb=make_progress_cb(job_id))
            else:
                stems = separate_stems(audio, sr, progress_cb=make_progress_cb(job_id))

            jobs.update_job(job_id, stage="Analizando stems", progress=60)
            analysis = analyze_stems_full(stems, sr, measure_lufs_integrated)

            jobs.update_job(job_id, stage="IA decidiendo mix", progress=70)
            stems_for_ai = {}
            for name, stem_audio in stems.items():
                stem_analysis = analysis.get("stems", {}).get(name, {})
                stems_for_ai[name] = stem_analysis

            try:
                loop = asyncio.new_event_loop()
                try:
                    mix_decision = loop.run_until_complete(decide_mix(stems_for_ai))
                finally:
                    loop.close()
            except RuntimeError as e:
                jobs.update_job(job_id, stage="IA no disponible - usando defaults", progress=75)
                logger.warning("1-click: IA no disponible (%s), usando params default.", e)
                mix_decision = {name: {"gain_db": 0, "pan": 0, "hp_cutoff_hz": 20,
                                       "lp_cutoff_hz": 20000, "comp_enabled": False,
                                       "stereo_width_amount": 1.0, "sidechain_trigger_name": None,
                                       "reasoning": "IA no disponible"}
                                for name in stems}

            jobs.update_job(job_id, stage="Mezclando y masterizando", progress=80)

            stem_params = {}
            for name in stems:
                p = mix_decision.get(name, {})
                stem_params[name] = StemParams(
                    name=name,
                    gain_db=p.get("gain_db", 0.0),
                    pan=p.get("pan", 0.0),
                    hp_cutoff_hz=p.get("hp_cutoff_hz", 20.0),
                    lp_cutoff_hz=p.get("lp_cutoff_hz", 20000.0),
                    eq_low_gain_db=p.get("eq_low_gain_db", 0.0),
                    eq_lomid_gain_db=p.get("eq_lomid_gain_db", 0.0),
                    eq_himid_gain_db=p.get("eq_himid_gain_db", 0.0),
                    eq_high_gain_db=p.get("eq_high_gain_db", 0.0),
                    comp_enabled=p.get("comp_enabled", False),
                    comp_threshold=p.get("comp_threshold", 0.5),
                    comp_ratio=p.get("comp_ratio", 4.0),
                    comp_attack_ms=p.get("comp_attack_ms", 10.0),
                    comp_release_ms=p.get("comp_release_ms", 100.0),
                    comp_makeup_db=p.get("comp_makeup_db", 0.0),
                    transient_attack=p.get("transient_attack", 0.0),
                    transient_sustain=p.get("transient_sustain", 0.0),
                    stereo_width_amount=p.get("stereo_width_amount", 1.0),
                    sidechain_trigger_name=p.get("sidechain_trigger_name"),
                    sidechain_threshold=p.get("sidechain_threshold", 0.5),
                    sidechain_ratio=p.get("sidechain_ratio", 4.0),
                    sidechain_attack_ms=p.get("sidechain_attack_ms", 10.0),
                    sidechain_release_ms=p.get("sidechain_release_ms", 100.0),
                )

            mix_params = MixParams(master_gain_db=-2.0, normalize_before_master=True)
            result = mix_and_master(stems, sr, stem_params, mix_params,
                                      progress_cb=make_progress_cb(job_id))

            stem_dir = os.path.join(stems_dir, job_id)
            os.makedirs(stem_dir, exist_ok=True)
            stem_paths = {}
            for name, stem_audio in stems.items():
                out_path = os.path.join(stem_dir, f"{name}.wav")
                data_to_write = stem_audio.T if stem_audio.ndim == 2 else stem_audio
                sf.write(out_path, data_to_write, sr, subtype="PCM_24")
                stem_paths[name] = out_path

            jobs.update_job(
                job_id,
                status="done",
                finished_at=time.time(),
                progress=100,
                stage="Completado",
                type="one_click_stem_master",
                result=result,
                stem_analysis=analysis,
                stem_paths=stem_paths,
                available_stems=list(stem_paths.keys()),
                mix_decision=mix_decision,
                mix_result=result,
            )
            logger.info("Job %s (1-click stem master) done", job_id)

        except (ValueError, RuntimeError) as e:
            jobs.update_job(job_id, status="error", error=str(e))
            logger.error("Job %s (1-click) failed: %s", job_id, e, exc_info=True)
        except Exception as e:
            jobs.update_job(job_id, status="error", error=str(e))
            logger.error("Job %s (1-click) failed: %s", job_id, e, exc_info=True)
        finally:
            if os.path.exists(input_path):
                os.remove(input_path)

    return run_mastering_job, run_reference_job, run_normalize_job, run_stems_job, run_one_click_stem_master_job
