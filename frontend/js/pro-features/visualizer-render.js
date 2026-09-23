// ============================================================
// pro-features/visualizer-render.js — Goniometer + waterfall drawing
// F3.9 — Extraído de 34-premium-suite.js (split JS-I-3)
// ============================================================
// API pública (expone via window.LGMDM.visualizerRender):
//   - colorForMagnitude(mag) → [r, g, b]
//   - drawGoniometerFrame(canvas, ctx, size, dataL, dataR, pearson = 0)
//   - drawWaterfallFrame(canvas, ctx, rowData, waterfallRow)
//
// Carga: ANTES de 34-premium-suite.js. premium-suite consume estos
// helpers via window.LGMDM.visualizerRender.* en los tabs ABX
// (goniometro) y Waterfall.
//
// Notas técnicas:
//   - _WATERFALL_LUT pre-computada (offscreen canvas 256×1) — un
//     drawImage por pixel en lugar de triple lerp por muestra.
//   - _gonioParticles persiste entre llamadas (efecto glow acumulativo).
//     Si necesitás reset, llamá resetGoniometerState().
// ============================================================

(function (global) {
  "use strict";

  const ns = (global.LGMDM = global.LGMDM || {}).visualizerRender = (global.LGMDM && global.LGMDM.visualizerRender) || {};

  // ── Waterfall LUT (gradient azul → cyan → amarillo → rojo) ──
  const _WATERFALL_LUT = (() => {
    const c = document.createElement('canvas');
    c.width = 256; c.height = 1;
    const g = c.getContext('2d');
    const grd = g.createLinearGradient(0, 0, 256, 0);
    grd.addColorStop(0.00, '#070c24');
    grd.addColorStop(0.20, '#1a3f8a');
    grd.addColorStop(0.50, '#52f2bd');
    grd.addColorStop(0.78, '#ffd84d');
    grd.addColorStop(1.00, '#ff5f72');
    g.fillStyle = grd;
    g.fillRect(0, 0, 256, 1);
    return c;
  })();

  function colorForMagnitude(mag) {
    // Mantenido por compatibilidad con consumidores que esperan [r,g,b].
    // Ahora consulta la LUT pre-computada para evitar el triple lerp.
    const idx = Math.max(0, Math.min(255, Math.round(mag * 255)));
    const px = _WATERFALL_LUT.getContext('2d').getImageData(idx, 0, 1, 1).data;
    return [px[0], px[1], px[2]];
  }

  // ── Goniometro: estado persistente entre frames ──
  let _gonioParticles = [];
  let _haloPulse = 0;

  function resetGoniometerState() {
    _gonioParticles = [];
    _haloPulse = 0;
  }

  function drawGoniometerFrame(canvas, ctx, size, dataL, dataR, pearson = 0) {
    const w = canvas.width;
    const h = canvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const radius = Math.min(w, h) * 0.42;

    // F5.9 — Glow acumulativo: compositing aditivo + fade corto del frame previo
    const prevOp = ctx.globalCompositeOperation;
    ctx.globalCompositeOperation = 'lighter';
    ctx.fillStyle = 'rgba(7, 9, 18, 0.18)';
    ctx.fillRect(0, 0, w, h);

    // crosshair
    ctx.strokeStyle = 'rgba(82, 242, 189, 0.18)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, cy); ctx.lineTo(w, cy);
    ctx.moveTo(cx, 0); ctx.lineTo(cx, h);
    ctx.stroke();

    // círculo de scope
    ctx.strokeStyle = 'rgba(82, 242, 189, 0.28)';
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.stroke();

    // línea mono-safe a 45° (donde L=R cae)
    ctx.strokeStyle = 'rgba(255, 216, 77, 0.32)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(cx - radius * 0.72, cy + radius * 0.72);
    ctx.lineTo(cx + radius * 0.72, cy - radius * 0.72);
    ctx.stroke();
    ctx.setLineDash([]);

    // Plot L (X) vs R (Y). dataL/dataR son byteTimeDomainData [0..255]; 128 = silencio.
    const n = Math.min(dataL.length, dataR.length);
    ctx.strokeStyle = '#52f2bd';
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    let lastLX = 0, lastLY = 0;
    for (let i = 0; i < n; i++) {
      const lx = (dataL[i] / 128) - 1;
      const ly = (dataR[i] / 128) - 1;
      const px = cx + lx * radius;
      const py = cy - ly * radius;   // Y invertido para coordenadas de pantalla
      if (i === 0) ctx.moveTo(px, py);
      else         ctx.lineTo(px, py);
      lastLX = lx; lastLY = ly;
    }
    ctx.stroke();

    // F5.9 — Spawn 2 partículas/frame con vida 800ms desde la última muestra.
    if (Math.abs(lastLX) > 0.02 || Math.abs(lastLY) > 0.02) {
      for (let p = 0; p < 2; p++) {
        const j = (Math.random() - 0.5) * 0.18;
        _gonioParticles.push({
          x: cx + lastLX * radius + j,
          y: cy - lastLY * radius + j,
          vx: lastLX * 28 + (Math.random() - 0.5) * 8,
          vy: -lastLY * 28 + (Math.random() - 0.5) * 8,
          life: 0.8,
          maxLife: 0.8
        });
      }
    }
    // Update + draw particles
    const dt = 1 / 60;
    for (let i = _gonioParticles.length - 1; i >= 0; i--) {
      const pt = _gonioParticles[i];
      pt.x += pt.vx * dt;
      pt.y += pt.vy * dt;
      pt.vx *= 0.96; pt.vy *= 0.96;
      pt.life -= dt;
      if (pt.life <= 0) { _gonioParticles.splice(i, 1); continue; }
      const alpha = Math.max(0, pt.life / pt.maxLife);
      ctx.fillStyle = `rgba(82, 242, 189, ${alpha * 0.85})`;
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 1.4 + alpha * 1.6, 0, Math.PI * 2);
      ctx.fill();
    }
    // Cap de partículas para no acumular miles
    if (_gonioParticles.length > 240) _gonioParticles.splice(0, _gonioParticles.length - 240);

    // F5.9 — Halo pulsante cuando |pearsonCorrelation| > 0.85.
    if (Math.abs(pearson) > 0.85) {
      _haloPulse += 0.08;
      const haloR = (Math.sin(_haloPulse) + 1) * 15; // 0..30 px
      ctx.fillStyle = `rgba(66, 232, 255, ${0.18 * (1 - haloR / 30)})`;
      ctx.beginPath();
      ctx.arc(cx, cy, haloR, 0, Math.PI * 2);
      ctx.fill();
    } else {
      _haloPulse = 0;
    }

    ctx.globalCompositeOperation = prevOp;
  }

  function drawWaterfallFrame(canvas, ctx, rowData, waterfallRow) {
    const w = canvas.width;
    const h = canvas.height;

    // Cascada vertical: copia contenido existente desplazando 1px hacia abajo
    // drawImage(canvas, sx, sy, sw, sh, dx, dy, dw, dh)
    ctx.drawImage(canvas, 0, 0, w, h - 1, 0, 1, w, h - 1);

    // F5.10 — Nueva fila usando la LUT pre-computada (1 drawImage por pixel).
    const bins = waterfallRow.length;
    for (let x = 0; x < w; x++) {
      // Mapeo log-ish: las frecuencias bajas ocupan más espacio horizontal
      const binIdx = Math.min(bins - 1, Math.floor(Math.pow(x / w, 1.5) * (bins - 1)));
      const mag = waterfallRow[binIdx] / 255;
      const srcX = Math.max(0, Math.min(255, Math.round(mag * 255)));
      ctx.drawImage(_WATERFALL_LUT, srcX, 0, 1, 1, x, 0, 1, 1);
    }
  }

  Object.assign(ns, {
    colorForMagnitude,
    drawGoniometerFrame,
    drawWaterfallFrame,
    resetGoniometerState,
  });
})(window);
