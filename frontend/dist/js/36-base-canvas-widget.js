// ============================================================
// 36-base-canvas-widget.js — Mixin para widgets canvas Pro
// ============================================================
// Extraído del audit 2026-09-18: 6+ widgets Pro duplicaban el
// mismo boilerplate (_rafId, _lastFrame, _frameInterval, _running,
// _destroyed, init/destroy/teardown). Este mixin centraliza:
//
//   class MyWidget extends BaseCanvasWidget { ... }
//   const w = new MyWidget();
//   w.init(canvas, { onTick(t) { ... }, fps: 60 });
//   w.destroy();   // limpia rAF + listeners + ResizeObserver
//
// API:
//   - start() / stop()        control de rAF
//   - resize()                manual resize
//   - destroy()               cleanup completo
// ============================================================
// Dependent widgets — extienden globalThis.BaseCanvasWidget y DEBEN
// cargarse DESPUÉS de este script (ver index.html, sección pro-features):
//   saturation-widget.js, ms-imager-widget.js, loudness-war-widget.js,
//   loudness-penalty-widget.js, phase-rotation-widget.js
// ============================================================

(function (global) {
  "use strict";

  class BaseCanvasWidget {
    // Truly-private fields (P2 modernization: campos #). Solo se acceden
    // dentro de esta clase. Subclasses usan _dpr / _ro (protegidos por
    // convención — son API que necesitan para overrides de resize).
    #rafId = 0;
    #lastFrame = 0;
    #frameInterval = 1000 / 60;
    #running = false;
    #destroyed = false;
    #canvas = null;
    #ctx = null;
    #cssWidth = 0;
    #cssHeight = 0;
    #onTick = null;
    #cleanupResize = null;

    constructor() {
      // Protected (subclasses acceden para resize/cleanup custom)
      this._ro = null;
      this._dpr = 1;
    }

    // Subclasses (saturation, phase-rotation, ms-imager…) leen this.canvas /
    // this.ctx en onResize/onInit. Los getters exponen los #privados del base.
    get canvas() { return this.#canvas; }
    get ctx() { return this.#ctx; }

    _size(canvas) {
      const rect = canvas.getBoundingClientRect();
      this.#cssWidth = Math.max(rect.width, 320);
      this.#cssHeight = Math.max(rect.height, 180);
      this._dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(this.#cssWidth * this._dpr);
      canvas.height = Math.floor(this.#cssHeight * this._dpr);
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.setTransform(this._dpr, 0, 0, this._dpr, 0, 0);
      return ctx;
    }

    _bindResize(canvas) {
      if (typeof ResizeObserver === "undefined" || !canvas) return;
      let raf = 0;
      const apply = () => {
        raf = 0;
        if (this.#destroyed) return;
        this.#ctx = this._size(canvas);
        if (typeof this.onResize === "function") this.onResize(this.#cssWidth, this.#cssHeight, this._dpr);
      };
      this._ro = new ResizeObserver(() => {
        if (!raf) raf = requestAnimationFrame(apply);
      });
      this._ro.observe(canvas);
      this.#cleanupResize = () => {
        if (raf) cancelAnimationFrame(raf);
      };
    }

    _tick(now) {
      if (this.#destroyed || !this.#running) return;
      if (now - this.#lastFrame < this.#frameInterval) {
        this.#rafId = requestAnimationFrame((t) => this._tick(t));
        return;
      }
      this.#lastFrame = now;
      try {
        if (typeof this.onTick === "function") this.onTick(now);
      } catch (e) {
        console.error(`[BaseCanvasWidget] onTick error in ${this.constructor.name}:`, e);
      }
      this.#rafId = requestAnimationFrame((t) => this._tick(t));
    }

    init(canvas, options = {}) {
      if (!canvas) throw new Error("[BaseCanvasWidget] canvas required");
      this.#canvas = canvas;
      this.#ctx = this._size(canvas);
      this.#onTick = options.onTick || null;
      if (typeof this.onResize === "function") this.onResize(this.#cssWidth, this.#cssHeight, this._dpr);
      this._bindResize(canvas);
      if (typeof this.onInit === "function") this.onInit(options);
      this.#running = true;
      this.#rafId = requestAnimationFrame((t) => this._tick(t));
    }

    start() {
      if (this.#destroyed || this.#running) return;
      this.#running = true;
      this.#rafId = requestAnimationFrame((t) => this._tick(t));
    }

    stop() {
      this.#running = false;
      if (this.#rafId) {
        cancelAnimationFrame(this.#rafId);
        this.#rafId = 0;
      }
    }

    resize() {
      if (!this.#canvas) return;
      this.#ctx = this._size(this.#canvas);
      if (typeof this.onResize === "function") this.onResize(this.#cssWidth, this.#cssHeight, this._dpr);
    }

    destroy() {
      this.#destroyed = true;
      this.#running = false;
      if (this.#rafId) cancelAnimationFrame(this.#rafId);
      this.#rafId = 0;
      if (this._ro) { try { this._ro.disconnect(); } catch (_) {} this._ro = null; }
      if (typeof this.#cleanupResize === "function") { this.#cleanupResize(); this.#cleanupResize = null; }
      if (typeof this.onDestroy === "function") this.onDestroy();
      this.#canvas = null;
      this.#ctx = null;
    }

    teardown() { this.destroy(); }
  }

  global.BaseCanvasWidget = BaseCanvasWidget;
})(window);
