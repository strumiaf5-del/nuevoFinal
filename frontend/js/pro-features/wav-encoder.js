// ============================================================
// pro-features/wav-encoder.js — WAV PCM encoder + ISP counter
// F3.7 — Extraído de 34-premium-suite.js (split monolito)
// ============================================================
// API pública (expone via window.LGMDM.codec):
//   - audioBufferToWavBlob(audioBuffer, bitDepth = 16) → Blob
//   - countInterSamplePeaks(audioBuffer, penaltyDb) → number
//   - rmsDbfs(audioBuffer) → number (dBFS)
//
// Carga: ANTES de 34-premium-suite.js. El codec rendering en
// premium-suite consume estos helpers via window.LGMDM.codec.*.
// ============================================================

(function (global) {
  "use strict";

  const ns = (global.LGMDM = global.LGMDM || {}).codec = (global.LGMDM && global.LGMDM.codec) || {};

  function writeString(view, offset, str) {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  }

  function audioBufferToWavBlob(audioBuffer, bitDepth = 16) {
    const numCh = audioBuffer.numberOfChannels;
    const sampleRate = audioBuffer.sampleRate;
    const numFrames = audioBuffer.length;
    const bytesPerSample = bitDepth / 8;
    const blockAlign = numCh * bytesPerSample;
    const dataBytes = numFrames * blockAlign;
    const headerBytes = 44;
    const buffer = new ArrayBuffer(headerBytes + dataBytes);
    const view = new DataView(buffer);

    // RIFF header
    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + dataBytes, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);             // PCM chunk size
    view.setUint16(20, 1, true);              // PCM format
    view.setUint16(22, numCh, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * blockAlign, true);  // byte rate
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bitDepth, true);
    writeString(view, 36, 'data');
    view.setUint32(40, dataBytes, true);

    // Interleaved PCM samples
    const channels = [];
    for (let c = 0; c < numCh; c++) channels.push(audioBuffer.getChannelData(c));
    let offset = headerBytes;
    const maxAmp = bitDepth === 16 ? 0x7fff : 0x7fffff;
    for (let i = 0; i < numFrames; i++) {
      for (let c = 0; c < numCh; c++) {
        const s = Math.max(-1, Math.min(1, channels[c][i]));
        // Asimétrico (signed PCM) — el driver rechaza [-1] exacto en 16-bit
        const val = Math.round(s < 0 ? s * maxAmp : s * (maxAmp - 1));
        if (bitDepth === 16) {
          view.setInt16(offset, val, true);
          offset += 2;
        } else {
          view.setInt32(offset, val, true);
          offset += 4;
        }
      }
    }
    return new Blob([view], { type: 'audio/wav' });
  }

  // Cuenta "inter-sample peaks" > 0 dBFS (penalty artificial por códec).
  // Para un WAV renderizado por OfflineAudioContext, los samples quedan en
  // [-1..1]; los que están exactamente en +1 ya son clipping. Sumamos el
  // penalty configurable del códec para reflejar los inter-sample peaks
  // que el códec real podría producir tras el re-encoding.
  function countInterSamplePeaks(audioBuffer, penaltyDb) {
    let count = 0;
    const channels = audioBuffer.numberOfChannels;
    for (let c = 0; c < channels; c++) {
      const data = audioBuffer.getChannelData(c);
      for (let i = 0; i < data.length; i++) {
        if (data[i] >= 1.0) count++;
      }
    }
    // Aplicamos un factor empírico: penalty 1dB ⇒ ~0.5% más de picos ISP
    // sobre el total de samples (heurística, no medición real).
    const total = audioBuffer.length * channels;
    const extra = Math.round(total * 0.005 * Math.max(0, penaltyDb));
    return count + extra;
  }

  // RMS en dBFS sobre todo el buffer (para mostrar LUFS estimado en UI).
  function rmsDbfs(audioBuffer) {
    let sumSq = 0;
    let n = 0;
    const ch = audioBuffer.numberOfChannels;
    for (let c = 0; c < ch; c++) {
      const data = audioBuffer.getChannelData(c);
      for (let i = 0; i < data.length; i++) {
        const v = data[i];
        sumSq += v * v;
        n++;
      }
    }
    if (n === 0) return -Infinity;
    const rms = Math.sqrt(sumSq / n);
    return 20 * Math.log10(Math.max(rms, 1e-9));
  }

  Object.assign(ns, { audioBufferToWavBlob, countInterSamplePeaks, rmsDbfs });
})(window);
