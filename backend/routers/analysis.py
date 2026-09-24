from __future__ import annotations

import os
import uuid

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool

try:
    from ..audio_service import AudioService
    from ..mastering import (
        mix_advice, spectrum_analysis_fft, normalize_to_streaming_target,
        evaluate_streaming_compliance, detect_resonances, detect_sibilance,
        recommend_dynamic_eq, measure_lufs_integrated, PLATFORM_LOUDNESS_TARGETS,
    )
    from ..validation_utils import validate_audio_file
except ImportError:  # pragma: no cover
    from audio_service import AudioService
    from mastering import (
        mix_advice, spectrum_analysis_fft, normalize_to_streaming_target,
        evaluate_streaming_compliance, detect_resonances, detect_sibilance,
        recommend_dynamic_eq, measure_lufs_integrated, PLATFORM_LOUDNESS_TARGETS,
    )
    from validation_utils import validate_audio_file


def _spectrum_from_file(file_path: str, n_fft: int, n_bins: int):
    service = AudioService()
    return service.spectrum_file(file_path, n_fft=n_fft, n_bins=n_bins)


def _analyze_from_file(file_path: str) -> dict:
    try:
        return AudioService().analyze_file(file_path)
    except Exception as e:
        raise RuntimeError(f"Error analizando archivo: {e}") from e


def create_analysis_router(*, upload_dir: str, read_and_validate, logger, current_user_dependency, audio_service: AudioService | None = None) -> APIRouter:
    router = APIRouter(tags=["Análisis"])

    @router.post("/analysis")
    async def analyze_complete(
        file: UploadFile = File(...),
        n_fft: int = Query(4096, ge=256, le=16384),
        n_bins: int = Query(64, ge=8, le=256),
        current_user: dict = Depends(current_user_dependency),
    ):
        logger.info("🔍 %s análisis server-side: %s", current_user["email"], file.filename)
        validate_audio_file(file.filename)
        data = await read_and_validate(file)
        tmp = os.path.join(upload_dir, f"analysis_{uuid.uuid4().hex}")
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            if audio_service:
                result = await run_in_threadpool(audio_service.analyze_with_spectrum, tmp, n_fft, n_bins)
            else:
                result = await run_in_threadpool(AudioService().analyze_with_spectrum, tmp, n_fft, n_bins)
            logger.info("✓ Análisis completo server-side: %s", file.filename)
            return result
        except Exception as exc:
            logger.error("❌ Error análisis server-side %s: %s", file.filename, exc, exc_info=True)
            raise HTTPException(500, "Error análisis server-side: operación no completada") from exc
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    @router.post("/analyze")
    async def analyze_legacy(file: UploadFile = File(...), current_user: dict = Depends(current_user_dependency)):
        validate_audio_file(file.filename)
        data = await read_and_validate(file)
        tmp = os.path.join(upload_dir, f"analyze_{uuid.uuid4().hex}")
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            return await run_in_threadpool(audio_service.analyze_file if audio_service else _analyze_from_file, tmp)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    @router.post("/mix-advice")
    async def get_mix_advice(file: UploadFile = File(...), current_user: dict = Depends(current_user_dependency)):
        validate_audio_file(file.filename)
        data = await read_and_validate(file)
        tmp = os.path.join(upload_dir, f"advice_{uuid.uuid4().hex}")
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            analysis = await run_in_threadpool(audio_service.analyze_file if audio_service else _analyze_from_file, tmp)
            return {"analysis": analysis, **mix_advice(analysis)}
        except Exception as exc:
            logger.exception("Error en mix-advice: %s", exc)
            raise HTTPException(500, "Error en mix-advice: operación no completada") from exc
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    @router.post("/spectrum")
    async def spectrum(
        file: UploadFile = File(...),
        n_fft: int = Query(4096, ge=256, le=16384),
        n_bins: int = Query(64, ge=8, le=256),
        current_user: dict = Depends(current_user_dependency),
    ):
        validate_audio_file(file.filename)
        data = await read_and_validate(file)
        tmp = os.path.join(upload_dir, f"spectrum_{uuid.uuid4().hex}")
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            if audio_service:
                return await run_in_threadpool(audio_service.spectrum_file, tmp, n_fft, n_bins)
            return await run_in_threadpool(_spectrum_from_file, tmp, n_fft, n_bins)
        except Exception as exc:
            logger.exception("Error en spectrum: %s", exc)
            raise HTTPException(500, "Error en spectrum: operación no completada") from exc
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    @router.post("/normalize-streaming-target")
    async def normalize_streaming_endpoint(
        file: UploadFile = File(...),
        platform: str = Query("spotify"),
        ceiling_dbtp: float = Query(-1.0),
        current_user: dict = Depends(current_user_dependency),
    ):
        logger.info("🎯 %s normalización a streaming target (%s): %s", current_user.get("email"), platform, file.filename)
        validate_audio_file(file.filename)
        data = await read_and_validate(file)
        tmp = os.path.join(upload_dir, f"norm_{uuid.uuid4().hex}")
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)

            def _process():
                import soundfile as sf
                from mastering import measure_lra
                audio, sr = sf.read(tmp, always_2d=True)
                audio_ch = audio.T
                norm_audio, info = normalize_to_streaming_target(
                    audio_ch, sr, platform=platform, ceiling_dbtp=ceiling_dbtp, return_info=True
                )
                if not info or norm_audio is None:
                    return {"status": "error", "detail": "normalize_to_streaming_target returned no info"}
                # Mide DR real desde el audio normalizado (peak_db - rms_db en LUFS-weighted)
                # y LRA real vía pyloudnorm. Si la medición falla, cae a defaults y
                # marca "partial" para que el frontend sepa que la compliance no es exacta.
                peak_db = float(info.get("output_true_peak_dbtp", -1.0))
                rms_db = 20.0 * float(np.log10(max(np.sqrt(np.mean(norm_audio.astype(np.float64) ** 2)), 1e-9)))
                dynamic_range_db = max(0.0, round(peak_db - rms_db, 2))
                lra_val = measure_lra(norm_audio, sr)
                compliance = evaluate_streaming_compliance(
                    integrated_lufs=info["output_lufs"],
                    true_peak_dbtp=info["output_true_peak_dbtp"],
                    dynamic_range_db=dynamic_range_db,
                    lra=lra_val,
                )
                info["platform_compliance"] = compliance
                info["dynamic_range_db"] = dynamic_range_db
                info["loudness_range_lu"] = lra_val
                input_lufs = float(info.get("input_lufs", -100.0))
                # success sólo si el pipeline midió DR y LRA reales con valores > 0
                measured_ok = dynamic_range_db > 0.0 and lra_val > 0.0
                info["status"] = "success" if (input_lufs > -70.0 and measured_ok) else "partial"
                return info

            return await run_in_threadpool(_process)
        except Exception as exc:
            logger.error("❌ Error en normalización a streaming target: %s", exc, exc_info=True)
            raise HTTPException(500, "Error en normalización a streaming target: operación no completada") from exc
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    @router.post("/analysis/proactive-detection")
    async def proactive_detection(
        file: UploadFile = File(...),
        current_user: dict = Depends(current_user_dependency),
    ):
        """Detecta proactivamente resonancias, sibilancia y problemas espectrales."""
        validate_audio_file(file.filename)
        data = await read_and_validate(file)
        tmp = os.path.join(upload_dir, f"proactive_{uuid.uuid4().hex}")
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)

            def _detect():
                import librosa
                audio, sr = librosa.load(tmp, sr=None, mono=False)
                if audio.ndim == 1:
                    audio = audio[np.newaxis, :]
                mono = audio.mean(axis=0) if audio.ndim > 1 else audio

                resonances = detect_resonances(mono, sr, max_resonances=8)
                sibilance = detect_sibilance(mono, sr)
                dyneq_suggestions = recommend_dynamic_eq(mono, sr)

                issues = []
                for r in resonances:
                    issues.append({
                        "type": "resonance",
                        "freq_hz": round(r.get("freq_hz", 0), 1),
                        "severity_db": round(r.get("excess_db", 0), 1),
                        "suggested_cut_db": round(r.get("suggested_cut_db", 0), 1),
                        "suggested_q": round(r.get("suggested_q", 1.0), 2),
                        "message": f"Resonancia a {r.get('freq_hz', 0):.0f} Hz (+{r.get('excess_db', 0):.1f} dB sobre baseline)",
                        "suggested_params": {
                            "reso_bypass": False,
                            "reso_freq": round(r.get("freq_hz", 0), 1),
                            "reso_q": round(r.get("suggested_q", 1.0), 2),
                            "reso_threshold_db": -20.0,
                            "reso_ratio": 3.0,
                        },
                    })

                if sibilance.get("is_sibilant"):
                    issues.append({
                        "type": "sibilance",
                        "freq_hz": sibilance.get("band_hz", [4000, 9000]),
                        "severity_db": round(sibilance.get("severity_db", 0), 1),
                        "suggested_reduction_db": round(sibilance.get("suggested_reduction_db", 0), 1),
                        "message": f"Sibilancia detectada ({sibilance.get('severity_db', 0):.1f} dB de exceso en {sibilance.get('band_hz', [0,0])[0]}-{sibilance.get('band_hz', [0,0])[1]} Hz)",
                        "suggested_params": {
                            "dyneq_bypass": False,
                            "dyneq_freq": 6000.0,
                            "dyneq_q": 3.0,
                            "dyneq_threshold_db": -18.0,
                            "dyneq_ratio": 2.5,
                        },
                    })

                if dyneq_suggestions:
                    for ds in dyneq_suggestions:
                        if ds.get("freq_hz"):
                            issues.append({
                                "type": "dynamic_eq",
                                "freq_hz": round(ds.get("freq_hz", 0), 1),
                                "message": f"Dynamic EQ sugerido a {ds.get('freq_hz', 0):.0f} Hz",
                                "suggested_params": ds,
                            })

                return {"issues": issues, "total": len(issues)}

            return await run_in_threadpool(_detect)
        except Exception as exc:
            logger.error("Error en proactive-detection: %s", exc, exc_info=True)
            raise HTTPException(500, "Error en detección proactiva") from exc
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    @router.post("/analysis/delta-solo")
    async def delta_solo(
        file: UploadFile = File(...),
        reso_freq: float = Query(0, ge=0, le=20000),
        reso_q: float = Query(1.0, ge=0.1, le=12),
        reso_threshold_db: float = Query(-20, ge=-60, le=0),
        reso_ratio: float = Query(3.0, ge=1, le=20),
        current_user: dict = Depends(current_user_dependency),
    ):
        """Genera audio 'delta' (original - procesado) para escuchar qué se remueve."""
        validate_audio_file(file.filename)
        data = await read_and_validate(file)
        tmp = os.path.join(upload_dir, f"delta_{uuid.uuid4().hex}")
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)

            def _generate_delta():
                import librosa, soundfile as sf, io
                audio, sr = librosa.load(tmp, sr=None, mono=False)
                if audio.ndim == 1:
                    audio = audio[np.newaxis, :]

                from mastering import apply_mastering_chain
                processed = apply_mastering_chain(
                    audio, sr,
                    reso_bypass=False,
                    reso_freq=reso_freq,
                    reso_q=reso_q,
                    reso_threshold_db=reso_threshold_db,
                    reso_ratio=reso_ratio,
                    reso_attack_ms=5.0,
                    reso_release_ms=50.0,
                    reso_max_reduction_db=12.0,
                    oversample_mode="fast",
                )

                min_len = min(audio.shape[-1], processed.shape[-1])
                delta = audio[..., :min_len] - processed[..., :min_len]

                buf = io.BytesIO()
                sf.write(buf, delta.T, sr, format="WAV", subtype="FLOAT")
                buf.seek(0)
                return buf.read()

            audio_bytes = await run_in_threadpool(_generate_delta)
            from fastapi import Response
            return Response(content=audio_bytes, media_type="audio/wav",
                           headers={"Content-Disposition": "attachment; filename=delta_solo.wav"})
        except Exception as exc:
            logger.error("Error en delta-solo: %s", exc, exc_info=True)
            raise HTTPException(500, "Error generando delta solo") from exc
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    @router.post("/analysis/preflight")
    async def preflight_inspector(
        file: UploadFile = File(...),
        target_lufs: float = Query(-14, ge=-40, le=0),
        current_user: dict = Depends(current_user_dependency),
    ):
        """Inspector Pre-Flight: checklist + predicciones de problemas de mezcla."""
        validate_audio_file(file.filename)
        data = await read_and_validate(file)
        tmp = os.path.join(upload_dir, f"preflight_{uuid.uuid4().hex}")
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)

            def _preflight():
                import librosa
                audio, sr = librosa.load(tmp, sr=None, mono=False)
                if audio.ndim == 1:
                    audio = audio[np.newaxis, :]
                from mastering import analyze_audio
                analysis = analyze_audio(audio, sr)

                lufs = analysis.get("lufs", -14)
                peak_db = analysis.get("peak_db", 0)
                true_peak_db = analysis.get("true_peak_db", 0)
                dr_db = analysis.get("dynamic_range_db", 0)
                lra = analysis.get("lra", 0)
                stereo_corr = analysis.get("stereo_correlation", 1)
                mono_compat = analysis.get("mono_compatibility_db", 0)
                dc_offset = analysis.get("dc_offset", 0)
                clipping_ratio = analysis.get("clipping_ratio", 0)
                silence_ratio = analysis.get("silence_ratio", 0)
                spectral_flatness = analysis.get("spectral_flatness", 0.5)
                spectral_centroid = analysis.get("spectral_centroid_hz", 2000)
                transient_density = analysis.get("transient_density", 0)
                plr = analysis.get("plr_db", 0)

                checks = []

                def _check(name, status, message, detail=None, suggested_params=None):
                    checks.append({
                        "name": name, "status": status,
                        "message": message, "detail": detail or "",
                        "suggested_params": suggested_params or {},
                    })

                _check("DC Offset", "pass" if abs(dc_offset) < 0.01 else "warn" if abs(dc_offset) < 0.05 else "fail",
                       f"DC offset: {dc_offset:.4f}" + (" (OK)" if abs(dc_offset) < 0.01 else " (corregir)"),
                       "DC offset > 0.05 puede causar clicks y pérdida de headroom" if abs(dc_offset) >= 0.01 else None,
                       {"input_gain_db": 0} if abs(dc_offset) >= 0.05 else None)

                _check("Clipping", "pass" if clipping_ratio < 0.001 else "warn" if clipping_ratio < 0.01 else "fail",
                       f"Clipping ratio: {clipping_ratio:.4%}",
                       f"{clipping_ratio*100:.2f}% de samples están en o cerca de 0 dBFS" if clipping_ratio >= 0.001 else None,
                       {"limiter_ceiling": 0.95, "clipper_bypass": False} if clipping_ratio >= 0.001 else None)

                _check("True Peak Headroom", "pass" if true_peak_db < -0.5 else "warn" if true_peak_db < -0.1 else "fail",
                       f"True peak: {true_peak_db:.2f} dBTP",
                       f"Solo {abs(true_peak_db):.2f} dB de margen. Riesgo de clipping en codecs con oversampling." if true_peak_db >= -0.5 else None,
                       {"limiter_ceiling": 0.89} if true_peak_db >= -0.5 else None)

                _check("Stereo Correlation", "pass" if stereo_corr > 0.5 else "warn" if stereo_corr > 0.1 else "fail",
                       f"Correlación estéreo: {stereo_corr:.2f}",
                       "Correlación baja → posible problema de fase. Sumar a mono puede causar cancelaciones." if stereo_corr < 0.5 else None,
                       {"stereo_width_amount": 1.0, "stereo_bypass": False} if stereo_corr < 0.5 else None)

                _check("Mono Compatibility", "pass" if mono_compat < 0.5 else "warn" if mono_compat < 1.5 else "fail",
                       f"Pérdida mono: {mono_compat:.1f} dB",
                       f"Sumar a mono causa {mono_compat:.1f} dB de pérdida. Revisar contenido Side/L-R." if mono_compat >= 1.5 else None,
                       {"mid_gain_db": 1.0, "side_gain_db": -1.0} if mono_compat >= 1.5 else None)

                _check("Dynamic Range", "pass" if dr_db > 8 else "warn" if dr_db > 4 else "fail",
                       f"Rango dinámico: {dr_db:.1f} dB",
                       "DR bajo → track sobre-comprimido o ya masterizado." if dr_db <= 4 else None,
                       {"comp_bypass": True} if dr_db <= 4 else None)

                _check("Loudness Level", "pass" if -18 <= lufs <= -10 else "warn" if -24 <= lufs <= -6 else "fail",
                       f"LUFS integrado: {lufs:.1f} LUFS",
                       ("Track muy bajo (-" + str(abs(lufs)) + " LUFS). Necesita gain significativo." if lufs < -18 else
                        "Track muy alto (" + str(lufs) + " LUFS). Ya al límite de loudness war." if lufs > -6 else None),
                       {"target_lufs": target_lufs} if abs(lufs - target_lufs) > 2 else None)

                _check("Silence Ratio", "pass" if silence_ratio < 0.1 else "warn",
                       f"Silencio: {silence_ratio:.1%} del track",
                       "Mucho silencio al inicio/final. Considerar trim." if silence_ratio >= 0.1 else None)

                _check("Spectral Flatness", "pass" if 0.1 <= spectral_flatness <= 0.8 else "warn",
                       f"Flatness: {spectral_flatness:.3f}",
                       ("Flatness muy bajo → track muy tonal (posibles resonancias)." if spectral_flatness < 0.1 else
                        "Flatness muy alto → track muy ruidoso." if spectral_flatness > 0.8 else None),
                       {"reso_bypass": False} if spectral_flatness < 0.1 else None)

                _check("Transient Density", "pass", f"Densidad de transientes: {transient_density:.1f}/s")

                _check("PLR (Peak-to-Loudness)", "pass" if plr > 7 else "warn" if plr > 4 else "fail",
                       f"PLR: {plr:.1f} dB",
                       "PLR bajo → poco headroom dinámico. Master sonará aplastado." if plr <= 4 else None)

                predictions = []

                gain_to_target = target_lufs - lufs
                predicted_tp = true_peak_db + gain_to_target
                if predicted_tp > 0:
                    predictions.append({
                        "scenario": f"Si normalizás a {target_lufs} LUFS",
                        "prediction": f"True peak llegará a {predicted_tp:.1f} dBTP → CLIPPING",
                        "severity": "critical",
                        "recommendation": f"Bajar limiter_ceiling a {-1 - (predicted_tp - 0):.1f} dBFS antes de normalizar",
                        "suggested_params": {"limiter_ceiling": max(0.89, 10 ** ((-1 - max(0, predicted_tp)) / 20))},
                    })
                else:
                    predictions.append({
                        "scenario": f"Si normalizás a {target_lufs} LUFS",
                        "prediction": f"True peak llegará a {predicted_tp:.1f} dBTP → OK",
                        "severity": "ok",
                    })

                if lufs < -20:
                    predicted_gain = target_lufs - lufs
                    predicted_dr = max(2, dr_db - predicted_gain * 0.3)
                    predictions.append({
                        "scenario": f"Subir {predicted_gain:.1f} dB a {target_lufs} LUFS",
                        "prediction": f"DR bajará de {dr_db:.1f} a ~{predicted_dr:.1f} dB",
                        "severity": "warn" if predicted_dr < 5 else "ok",
                    })

                platform_data = analysis.get("platform_compliance", {})
                for plat, info in platform_data.items():
                    status = info.get("status", "pass")
                    if status != "pass":
                        predictions.append({
                            "scenario": f"Compliance {plat}",
                            "prediction": f"{'Clipping' if status == 'fail' else 'Warning'}: gain {info.get('gain_adjustment_db', 0):.1f} dB, TP proyectado {info.get('projected_true_peak_dbtp', 0):.1f}",
                            "severity": "critical" if status == "fail" else "warn",
                            "recommendation": f"Ajustar target_lufs a {info.get('target_lufs', -14)} LUFS para {plat}",
                        })

                pass_count = sum(1 for c in checks if c["status"] == "pass")
                warn_count = sum(1 for c in checks if c["status"] == "warn")
                fail_count = sum(1 for c in checks if c["status"] == "fail")
                overall_score = round(pass_count / max(len(checks), 1) * 100)

                return {
                    "checks": checks,
                    "predictions": predictions,
                    "overall_score": overall_score,
                    "summary": f"{pass_count} OK, {warn_count} warnings, {fail_count} fallos",
                    "analysis": {
                        "lufs": lufs, "peak_db": peak_db, "true_peak_db": true_peak_db,
                        "dynamic_range_db": dr_db, "lra": lra, "stereo_correlation": stereo_corr,
                        "mono_compatibility_db": mono_compat, "plr_db": plr,
                    },
                }

            return await run_in_threadpool(_preflight)
        except Exception as exc:
            logger.error("Error en preflight: %s", exc, exc_info=True)
            raise HTTPException(500, "Error en pre-flight inspector") from exc
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    @router.post("/analysis/simulate-platforms")
    async def simulate_platforms(
        file: UploadFile = File(...),
        target_lufs: float = Query(-14, ge=-30, le=-4),
        current_user: dict = Depends(current_user_dependency),
    ):
        """Simulador Predictivo Multiplataforma + Anti-Loudness Penalty."""
        validate_audio_file(file.filename)
        data = await read_and_validate(file)
        tmp = os.path.join(upload_dir, f"simplat_{uuid.uuid4().hex}")
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)

            def _simulate():
                import librosa, numpy as np
                audio, sr = librosa.load(tmp, sr=None, mono=False)
                if audio.ndim == 1:
                    audio = audio[np.newaxis, :]

                orig_lufs = float(measure_lufs_integrated(audio, sr))
                peak = float(np.max(np.abs(audio)))
                orig_peak_db = 20.0 * float(np.log10(max(peak, 1e-6)))
                orig_dr = max(0, orig_peak_db - float(measure_lufs_integrated(audio, sr)))

                from mastering import true_peak_dbfs
                orig_tp_db = float(true_peak_dbfs(audio, sr))

                platforms_result = []
                total_penalty = 0

                for plat_name, plat_target in PLATFORM_LOUDNESS_TARGETS.items():
                    plat_lufs = float(plat_target["lufs"])
                    plat_ceiling = float(plat_target["true_peak_db"])
                    gain_db = plat_lufs - orig_lufs

                    predicted_tp = orig_tp_db + gain_db
                    predicted_lufs = orig_lufs + gain_db

                    status = "pass"
                    warnings = []
                    if predicted_tp > plat_ceiling:
                        status = "fail"
                        warnings.append(f"True peak {predicted_tp:.1f} dBTP excede techo {plat_ceiling:.1f}")
                    elif predicted_tp > plat_ceiling - 0.5:
                        status = "warn"
                        warnings.append(f"True peak {predicted_tp:.1f} dBTP cerca del techo {plat_ceiling:.1f}")

                    if abs(gain_db) > 6:
                        if gain_db < 0:
                            warnings.append(f"Atenuación significativa: {gain_db:.1f} dB (track más fuerte que target)")
                        else:
                            warnings.append(f"Boost significativo: +{gain_db:.1f} dB (track más bajo que target)")

                    predicted_dr = max(1, orig_dr - max(0, gain_db * 0.15))
                    if predicted_dr < 4:
                        status = "warn" if status == "pass" else status
                        warnings.append(f"DR predicho bajo: {predicted_dr:.1f} dB")

                    platforms_result.append({
                        "platform": plat_name,
                        "target_lufs": plat_lufs,
                        "true_peak_ceiling": plat_ceiling,
                        "gain_db": round(gain_db, 2),
                        "predicted_lufs": round(predicted_lufs, 1),
                        "predicted_tp": round(predicted_tp, 1),
                        "predicted_dr": round(predicted_dr, 1),
                        "status": status,
                        "warnings": warnings,
                    })

                    if gain_db < -3:
                        total_penalty += abs(gain_db) * 0.5

                penalties = {p["platform"]: p["gain_db"] for p in platforms_result if p["gain_db"] < 0}
                if penalties:
                    optimal_platform = min(penalties, key=penalties.get)
                    optimal_lufs = PLATFORM_LOUDNESS_TARGETS[optimal_platform]["lufs"]
                else:
                    optimal_lufs = -14
                    optimal_platform = "spotify"

                recommendation = {
                    "optimal_target_lufs": optimal_lufs,
                    "optimal_platform": optimal_platform,
                    "reasoning": f"Target óptimo: {optimal_lufs} LUFS ({optimal_platform}). "
                                 f"Minimiza atenuación de plataforma (penalty total: {total_penalty:.1f} dB).",
                    "suggested_params": {
                        "target_lufs": optimal_lufs,
                        "limiter_ceiling": 10 ** (PLATFORM_LOUDNESS_TARGETS[optimal_platform]["true_peak_db"] / 20),
                        "platform_target": optimal_platform,
                    },
                }

                return {
                    "platforms": platforms_result,
                    "original": {
                        "lufs": round(orig_lufs, 1),
                        "peak_db": round(orig_peak_db, 1),
                        "true_peak_db": round(orig_tp_db, 1),
                        "dynamic_range_db": round(orig_dr, 1),
                    },
                    "target_lufs": target_lufs,
                    "total_penalty_db": round(total_penalty, 1),
                    "recommendation": recommendation,
                }

            return await run_in_threadpool(_simulate)
        except Exception as exc:
            logger.error("Error en simulate-platforms: %s", exc, exc_info=True)
            raise HTTPException(500, "Error en simulador multiplataforma") from exc
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    return router
