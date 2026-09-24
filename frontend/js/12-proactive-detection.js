(function (global) {
  "use strict";

  const LG = global.LGMDM || (global.LGMDM = {});

  async function _handleProactiveClick() {
    if (!LG.state?.selectedFile) {
      LG.ui?.showStatus?.(null, "Subí un archivo primero.", "error");
      return;
    }
    LG.ui?.clearResults?.();
    LG.ui?.showStatus?.(null, "Detectando problemas…", "processing");

    const fd = new FormData();
    fd.append("file", LG.state.selectedFile);

    try {
      const res = await LG.api.apiFetch(`${LG.api.apiBase()}/analysis/proactive-detection`, {
        method: "POST",
        body: fd,
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`HTTP ${res.status}: ${text}`);
      }
      const data = await res.json();
      LG.ui?.showStatus?.(null, "Detección completada", "done");
      _renderProactivePanel(data.issues || []);
    } catch (e) {
      console.debug("Error en detección proactiva:", e);
      LG.ui?.showStatus?.(null, "Error: " + e.message, "error");
    }
  }

  function _severityColor(severity) {
    if (severity >= 6) return "#ff4444";
    if (severity >= 3) return "#ffaa00";
    return "#44ff44";
  }

  function _renderProactivePanel(issues) {
    const container = LG.ui?.resultsContainer || document.getElementById("resultsArea");
    if (!container) return;

    const panel = document.createElement("div");
    panel.className = "proactive-panel";
    panel.style.cssText = "padding:16px;border:1px solid var(--ui-border,#333);border-radius:8px;margin:8px 0;background:var(--ui-panel-bg,#1a1a2e);";

    const header = document.createElement("h3");
    header.textContent = `🔬 Detección Proactiva — ${issues.length} problema(s) encontrado(s)`;
    header.style.cssText = "margin:0 0 12px;font-size:1.1em;color:var(--ui-text,#e0e0e0);";
    panel.appendChild(header);

    if (!issues.length) {
      const ok = document.createElement("p");
      ok.textContent = "No se detectaron resonancias ni sibilancia significativas. El track está limpio.";
      ok.style.cssText = "color:#44ff44;font-size:0.95em;";
      panel.appendChild(ok);
      container.appendChild(panel);
      return;
    }

    issues.forEach((issue, i) => {
      const card = document.createElement("div");
      card.style.cssText = "display:flex;align-items:flex-start;gap:10px;padding:10px;margin:6px 0;border-radius:6px;background:rgba(255,255,255,0.03);border-left:3px solid " + _severityColor(issue.severity_db || 0) + ";";

      const info = document.createElement("div");
      info.style.flex = "1";

      const badge = document.createElement("span");
      badge.textContent = issue.type || "issue";
      badge.style.cssText = "display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.75em;font-weight:700;text-transform:uppercase;margin-right:8px;background:" + _severityColor(issue.severity_db || 0) + ";color:#000;";
      info.appendChild(badge);

      const msg = document.createElement("span");
      msg.textContent = issue.message || "";
      msg.style.cssText = "font-size:0.9em;color:var(--ui-text,#e0e0e0);";
      info.appendChild(msg);

      card.appendChild(info);

      const btnGroup = document.createElement("div");
      btnGroup.style.cssText = "display:flex;gap:6px;flex-shrink:0;";

      if (issue.suggested_params) {
        const applyBtn = document.createElement("button");
        applyBtn.type = "button";
        applyBtn.className = "btn btn-primary btn-sm";
        applyBtn.textContent = "Aplicar";
        applyBtn.style.cssText = "padding:4px 10px;font-size:0.8em;";
        applyBtn.addEventListener("click", () => {
          if (typeof applyPresetToUI === "function") {
            applyPresetToUI(issue.suggested_params);
          } else if (LG.params?.build) {
            LG.params.build(issue.suggested_params);
          }
        });
        btnGroup.appendChild(applyBtn);
      }

      if (issue.type === "resonance" && issue.freq_hz) {
        const deltaBtn = document.createElement("button");
        deltaBtn.type = "button";
        deltaBtn.className = "btn btn-secondary btn-sm";
        deltaBtn.textContent = "Delta Solo";
        deltaBtn.style.cssText = "padding:4px 10px;font-size:0.8em;";
        deltaBtn.addEventListener("click", () => _playDeltaSolo(issue));
        btnGroup.appendChild(deltaBtn);
      }

      card.appendChild(btnGroup);
      panel.appendChild(card);
    });

    container.appendChild(panel);
  }

  let _deltaAudio = null;
  function _playDeltaSolo(issue) {
    if (!LG.state?.selectedFile) return;
    const fd = new FormData();
    fd.append("file", LG.state.selectedFile);
    const params = new URLSearchParams();
    if (issue.suggested_params) {
      if (issue.suggested_params.reso_freq) params.set("reso_freq", issue.suggested_params.reso_freq);
      if (issue.suggested_params.reso_q) params.set("reso_q", issue.suggested_params.reso_q);
      if (issue.suggested_params.reso_threshold_db) params.set("reso_threshold_db", issue.suggested_params.reso_threshold_db);
      if (issue.suggested_params.reso_ratio) params.set("reso_ratio", issue.suggested_params.reso_ratio);
    }

    LG.api?.downloadAuthenticated?.(
      `${LG.api.apiBase()}/analysis/delta-solo?${params.toString()}`,
      "delta_solo.wav"
    ).then(blob => {
      const url = URL.createObjectURL(blob);
      if (_deltaAudio) {
        _deltaAudio.pause();
        _deltaAudio.src = "";
      }
      _deltaAudio = new Audio(url);
      _deltaAudio.play().catch(e => console.debug("Delta solo playback error:", e));
    }).catch(e => {
      console.debug("Error descargando delta solo:", e);
      LG.ui?.showStatus?.(null, "Error generando delta solo: " + e.message, "error");
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("btnProactive");
    if (btn) btn.addEventListener("click", _handleProactiveClick);
    const pfBtn = document.getElementById("btnPreflight");
    if (pfBtn) pfBtn.addEventListener("click", _handlePreflightClick);
    const simBtn = document.getElementById("btnSimulator");
    if (simBtn) simBtn.addEventListener("click", _handleSimulatorClick);
  });

  LG.proactiveDetection = { detect: _handleProactiveClick, renderPanel: _renderProactivePanel, preflight: _handlePreflightClick, simulator: _handleSimulatorClick };

  // ═══════════════════════════════════════════════════════════════
  // ── Simulador Predictivo Multiplataforma + Anti-Loudness ──────
  // ═══════════════════════════════════════════════════════════════

  async function _handleSimulatorClick() {
    if (!LG.state?.selectedFile) {
      LG.ui?.showStatus?.(null, "Subí un archivo primero.", "error");
      return;
    }
    LG.ui?.clearResults?.();
    LG.ui?.showStatus?.(null, "Simulando plataformas…", "processing");

    const targetLufs = LG.dom?.byId?.("s-target-lufs")?.value || -14;
    const fd = new FormData();
    fd.append("file", LG.state.selectedFile);

    try {
      const res = await LG.api.apiFetch(
        `${LG.api.apiBase()}/analysis/simulate-platforms?target_lufs=${targetLufs}`,
        { method: "POST", body: fd }
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`HTTP ${res.status}: ${text}`);
      }
      const data = await res.json();
      LG.ui?.showStatus?.(null, "Simulación completada", "done");
      _renderSimulatorPanel(data);
    } catch (e) {
      console.debug("Error en simulador:", e);
      LG.ui?.showStatus?.(null, "Error: " + e.message, "error");
    }
  }

  function _renderSimulatorPanel(data) {
    const container = LG.ui?.resultsContainer || document.getElementById("resultsArea");
    if (!container) return;

    const panel = document.createElement("div");
    panel.style.cssText = "padding:16px;border:1px solid var(--ui-border,#333);border-radius:8px;margin:8px 0;background:var(--ui-panel-bg,#1a1a2e);";

    const header = document.createElement("h3");
    header.textContent = "📡 Simulador Predictivo Multiplataforma";
    header.style.cssText = "margin:0 0 8px;font-size:1.1em;color:var(--ui-text,#e0e0e0);";
    panel.appendChild(header);

    const orig = data.original || {};
    const origInfo = document.createElement("div");
    origInfo.style.cssText = "font-size:0.85em;color:var(--ui-text-dim,#aaa);margin-bottom:12px;";
    origInfo.textContent = `Track original: ${orig.lufs || '?'} LUFS, ${orig.true_peak_db || '?'} dBTP, DR ${orig.dynamic_range_db || '?'}`;
    panel.appendChild(origInfo);

    const table = document.createElement("table");
    table.style.cssText = "width:100%;border-collapse:collapse;font-size:0.85em;";
    table.innerHTML = `<thead><tr style="border-bottom:2px solid var(--ui-border,#333);">
      <th style="text-align:left;padding:6px;color:var(--ui-text,#e0e0e0);">Plataforma</th>
      <th style="text-align:center;padding:6px;">Target</th>
      <th style="text-align:center;padding:6px;">Gain</th>
      <th style="text-align:center;padding:6px;">Pred. LUFS</th>
      <th style="text-align:center;padding:6px;">Pred. TP</th>
      <th style="text-align:center;padding:6px;">Pred. DR</th>
      <th style="text-align:center;padding:6px;">Status</th>
    </tr></thead>`;

    const tbody = document.createElement("tbody");
    (data.platforms || []).forEach((p) => {
      const tr = document.createElement("tr");
      tr.style.cssText = `border-bottom:1px solid rgba(255,255,255,0.05);`;
      const statusColor = p.status === "pass" ? "#44ff44" : p.status === "warn" ? "#ffaa00" : "#ff4444";
      const statusIcon = p.status === "pass" ? "✓" : p.status === "warn" ? "⚠" : "✗";
      tr.innerHTML = `
        <td style="padding:6px;color:var(--ui-text,#e0e0e0);font-weight:600;">${p.platform}</td>
        <td style="text-align:center;padding:6px;">${p.target_lufs} LUFS</td>
        <td style="text-align:center;padding:6px;color:${p.gain_db < 0 ? '#ff4444' : '#44ff44'};">${p.gain_db > 0 ? '+' : ''}${p.gain_db} dB</td>
        <td style="text-align:center;padding:6px;">${p.predicted_lufs}</td>
        <td style="text-align:center;padding:6px;color:${p.predicted_tp > p.true_peak_ceiling ? '#ff4444' : 'inherit'};">${p.predicted_tp} dBTP</td>
        <td style="text-align:center;padding:6px;">${p.predicted_dr} dB</td>
        <td style="text-align:center;padding:6px;color:${statusColor};font-weight:900;">${statusIcon}</td>
      `;
      if (p.warnings && p.warnings.length) {
        const warnRow = document.createElement("tr");
        warnRow.innerHTML = `<td colspan="7" style="padding:4px 6px;font-size:0.75em;color:#ffaa00;padding-left:20px;">${p.warnings.join("; ")}</td>`;
        tbody.appendChild(tr);
        tbody.appendChild(warnRow);
      } else {
        tbody.appendChild(tr);
      }
    });
    table.appendChild(tbody);
    panel.appendChild(table);

    const rec = data.recommendation || {};
    const recBox = document.createElement("div");
    recBox.style.cssText = "margin-top:16px;padding:12px;border-radius:6px;background:rgba(68,255,68,0.05);border:1px solid rgba(68,255,68,0.2);";
    recBox.innerHTML = `
      <div style="font-weight:700;color:#44ff44;margin-bottom:4px;">🎯 Recomendación Anti-Loudness Penalty</div>
      <div style="font-size:0.85em;color:var(--ui-text,#e0e0e0);">${rec.reasoning || ""}</div>
      <div style="font-size:0.8em;color:var(--ui-text-dim,#aaa);margin-top:4px;">
        Penalty total: ${data.total_penalty_db || 0} dB
      </div>
    `;
    if (rec.suggested_params && Object.keys(rec.suggested_params).length) {
      const applyBtn = document.createElement("button");
      applyBtn.type = "button";
      applyBtn.className = "btn btn-primary btn-sm";
      applyBtn.textContent = "Aplicar recomendación";
      applyBtn.style.cssText = "margin-top:8px;";
      applyBtn.addEventListener("click", () => {
        if (typeof applyPresetToUI === "function") applyPresetToUI(rec.suggested_params);
        else if (LG.params?.build) LG.params.build(rec.suggested_params);
      });
      recBox.appendChild(applyBtn);
    }
    panel.appendChild(recBox);

    container.appendChild(panel);
  }

  // ═══════════════════════════════════════════════════════════════
  // ── Pre-Flight Inspector ──────────────────────────────────────
  // ═══════════════════════════════════════════════════════════════

  async function _handlePreflightClick() {
    if (!LG.state?.selectedFile) {
      LG.ui?.showStatus?.(null, "Subí un archivo primero.", "error");
      return;
    }
    LG.ui?.clearResults?.();
    LG.ui?.showStatus?.(null, "Ejecutando Pre-Flight…", "processing");

    const targetLufs = LG.dom?.byId?.("s-target-lufs")?.value || -14;
    const fd = new FormData();
    fd.append("file", LG.state.selectedFile);

    try {
      const res = await LG.api.apiFetch(
        `${LG.api.apiBase()}/analysis/preflight?target_lufs=${targetLufs}`,
        { method: "POST", body: fd }
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`HTTP ${res.status}: ${text}`);
      }
      const data = await res.json();
      LG.ui?.showStatus?.(null, "Pre-Flight completado", "done");
      _renderPreflightPanel(data);
    } catch (e) {
      console.debug("Error en preflight:", e);
      LG.ui?.showStatus?.(null, "Error: " + e.message, "error");
    }
  }

  function _renderPreflightPanel(data) {
    const container = LG.ui?.resultsContainer || document.getElementById("resultsArea");
    if (!container) return;

    const panel = document.createElement("div");
    panel.className = "preflight-panel";
    panel.style.cssText = "padding:16px;border:1px solid var(--ui-border,#333);border-radius:8px;margin:8px 0;background:var(--ui-panel-bg,#1a1a2e);";

    const scoreColor = data.overall_score >= 80 ? "#44ff44" : data.overall_score >= 50 ? "#ffaa00" : "#ff4444";
    const header = document.createElement("div");
    header.style.cssText = "display:flex;align-items:center;gap:12px;margin-bottom:12px;";
    header.innerHTML = `<h3 style="margin:0;font-size:1.1em;color:var(--ui-text,#e0e0e0);">🛫 Pre-Flight Inspector</h3>
      <span style="font-size:1.5em;font-weight:900;color:${scoreColor};">${data.overall_score}/100</span>
      <span style="font-size:0.85em;color:var(--ui-text-dim,#888);">${data.summary || ""}</span>`;
    panel.appendChild(header);

    const checksTitle = document.createElement("h4");
    checksTitle.textContent = "Checklist";
    checksTitle.style.cssText = "margin:12px 0 6px;font-size:0.95em;color:var(--ui-text,#e0e0e0);";
    panel.appendChild(checksTitle);

    (data.checks || []).forEach((check) => {
      const row = document.createElement("div");
      const statusColor = check.status === "pass" ? "#44ff44" : check.status === "warn" ? "#ffaa00" : "#ff4444";
      const statusIcon = check.status === "pass" ? "✓" : check.status === "warn" ? "⚠" : "✗";
      row.style.cssText = `display:flex;align-items:center;gap:8px;padding:6px 10px;margin:3px 0;border-radius:4px;background:rgba(255,255,255,0.02);border-left:3px solid ${statusColor};`;

      row.innerHTML = `<span style="color:${statusColor};font-weight:900;font-size:1.1em;">${statusIcon}</span>
        <span style="font-weight:600;min-width:140px;color:var(--ui-text,#e0e0e0);">${check.name}</span>
        <span style="flex:1;font-size:0.85em;color:var(--ui-text-dim,#aaa);">${check.message}</span>`;

      if (check.suggested_params && Object.keys(check.suggested_params).length) {
        const fixBtn = document.createElement("button");
        fixBtn.type = "button";
        fixBtn.className = "btn btn-primary btn-sm";
        fixBtn.textContent = "Auto-corregir";
        fixBtn.style.cssText = "padding:3px 8px;font-size:0.75em;";
        fixBtn.addEventListener("click", () => {
          if (typeof applyPresetToUI === "function") applyPresetToUI(check.suggested_params);
          else if (LG.params?.build) LG.params.build(check.suggested_params);
        });
        row.appendChild(fixBtn);
      }

      if (check.detail) {
        const detail = document.createElement("div");
        detail.style.cssText = "width:100%;font-size:0.8em;color:#ffaa00;margin-top:2px;padding-left:28px;";
        detail.textContent = check.detail;
        row.appendChild(detail);
      }

      panel.appendChild(row);
    });

    const predTitle = document.createElement("h4");
    predTitle.textContent = "Predicciones";
    predTitle.style.cssText = "margin:16px 0 6px;font-size:0.95em;color:var(--ui-text,#e0e0e0);";
    panel.appendChild(predTitle);

    (data.predictions || []).forEach((pred) => {
      const sevColor = pred.severity === "ok" ? "#44ff44" : pred.severity === "warn" ? "#ffaa00" : "#ff4444";
      const row = document.createElement("div");
      row.style.cssText = `padding:8px 10px;margin:3px 0;border-radius:4px;background:rgba(255,255,255,0.02);border-left:3px solid ${sevColor};`;
      row.innerHTML = `<div style="font-weight:600;color:var(--ui-text,#e0e0e0);">${pred.scenario}</div>
        <div style="font-size:0.85em;color:${sevColor};margin-top:2px;">${pred.prediction}</div>`;
      if (pred.recommendation) {
        const rec = document.createElement("div");
        rec.style.cssText = "font-size:0.8em;color:var(--ui-text-dim,#aaa);margin-top:2px;";
        rec.textContent = "→ " + pred.recommendation;
        row.appendChild(rec);
      }
      if (pred.suggested_params && Object.keys(pred.suggested_params).length) {
        const fixBtn = document.createElement("button");
        fixBtn.type = "button";
        fixBtn.className = "btn btn-primary btn-sm";
        fixBtn.textContent = "Aplicar corrección";
        fixBtn.style.cssText = "padding:3px 8px;font-size:0.75em;margin-top:4px;";
        fixBtn.addEventListener("click", () => {
          if (typeof applyPresetToUI === "function") applyPresetToUI(pred.suggested_params);
          else if (LG.params?.build) LG.params.build(pred.suggested_params);
        });
        row.appendChild(fixBtn);
      }
      panel.appendChild(row);
    });

    container.appendChild(panel);
  }
})(window);
