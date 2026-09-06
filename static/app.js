const POLL_MS = 400; // il backend campiona misure a ~2.5 volte/sec
const VOLT_SCALE_MAX = 32;
const CURRENT_SCALE_MAX = 3.2;

// Per canale: seq del setpoint al momento dell'ultimo SET inviato da qui.
// Finché state.setpoint_seq non supera questo valore, il campo resta vuoto
// invece di mostrare il vecchio valore.
const pendingSetpoint = {
  1: { v: null, i: null },
  2: { v: null, i: null },
};
let lastSetpointSeq = 0;

const els = {
  connStatus: document.getElementById("conn-status"),
  trackMode: document.getElementById("track-mode"),
  logToggle: document.getElementById("log-toggle"),
  logFile: document.getElementById("log-file"),
  chartV: document.getElementById("chart-v"),
  chartI: document.getElementById("chart-i"),
  ch3Off: document.getElementById("ch3-off"),
  ch3On: document.getElementById("ch3-on"),
};

function fmt(value, decimals) {
  return Number(value).toFixed(decimals).padStart(decimals + 3, "0");
}

// Accetta sia "5.5" che "5,5" (tastiera italiana).
function parseLocaleFloat(str) {
  if (str === "" || str == null) return null;
  const n = parseFloat(String(str).replace(",", "."));
  return Number.isNaN(n) ? null : n;
}

function updateChannel(ch, data, setpointSeq) {
  document.getElementById(`v-${ch}`).textContent = fmt(data.v_meas, 2);
  document.getElementById(`i-${ch}`).textContent = fmt(data.i_meas, 3);
  const limiting = data.on && data.mode === "CC";
  const led = document.getElementById(`led-${ch}`);
  led.classList.remove("on", "off", "limit");
  led.classList.add(!data.on ? "off" : (limiting ? "limit" : "on"));
  led.title = `${data.on ? "ON" : "OFF"} (${data.mode})`;

  document.getElementById(`limit-${ch}`).classList.toggle("show", limiting);

  const ctrl = document.querySelector(`.channel-control[data-ch="${ch}"]`);
  const outBtn = ctrl.querySelector(".toggle-output");
  outBtn.textContent = data.on ? "SPEGNI" : "ACCENDI";
  outBtn.classList.toggle("on", data.on);
  outBtn.classList.toggle("off", !data.on);

  const vInput = ctrl.querySelector(".set-v");
  const iInput = ctrl.querySelector(".set-i");
  const pending = pendingSetpoint[ch];

  // Una volta arrivato un campionamento più recente del comando inviato,
  // il valore mostrato è di nuovo affidabile.
  if (pending.v !== null && setpointSeq > pending.v) pending.v = null;
  if (pending.i !== null && setpointSeq > pending.i) pending.i = null;

  if (document.activeElement !== vInput && pending.v === null) vInput.value = data.v_set.toFixed(2);
  if (document.activeElement !== iInput && pending.i === null) iInput.value = data.i_set.toFixed(3);
}

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (data.connected) {
      els.connStatus.textContent = `Connesso — ${data.idn || ""}`;
      els.connStatus.className = "ok";
    } else {
      els.connStatus.textContent = data.error ? `Non connesso: ${data.error}` : "Non connesso";
      els.connStatus.className = "err";
    }
    els.trackMode.textContent = `Modalità: ${data.track_mode}`;
    lastSetpointSeq = data.setpoint_seq;
    updateChannel(1, data.channels["1"], data.setpoint_seq);
    updateChannel(2, data.channels["2"], data.setpoint_seq);

    els.logToggle.textContent = data.logging ? "Ferma log" : "Avvia log";
    els.logToggle.classList.toggle("active", data.logging);
  } catch (e) {
    els.connStatus.textContent = "Server non raggiungibile";
    els.connStatus.className = "err";
  }
}

async function refreshHistoryAndDraw() {
  try {
    const res = await fetch("/api/history");
    const hist = await res.json();
    drawChart(els.chartV, hist, VOLT_SCALE_MAX, ["ch1_v", "ch2_v"], (v) => v.toFixed(0));
    drawChart(els.chartI, hist, CURRENT_SCALE_MAX, ["ch1_i", "ch2_i"], (v) => v.toFixed(1));
  } catch (e) {
    /* ridisegnerà al prossimo giro */
  }
}

const SERIES_COLORS = { 0: "#7CFC7C", 1: "#ffb347" };

function drawChart(canvas, hist, scaleMax, keys, labelFmt) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  const marginLeft = 42, marginRight = 8, marginTop = 6, marginBottom = 6;
  const plotW = w - marginLeft - marginRight;
  const plotH = h - marginTop - marginBottom;

  ctx.clearRect(0, 0, w, h);

  // griglia + etichette scala (5 livelli)
  ctx.strokeStyle = "#2a2a2e";
  ctx.fillStyle = "#8a8a8a";
  ctx.font = "10px Menlo, Consolas, monospace";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  const steps = 4;
  for (let i = 0; i <= steps; i++) {
    const frac = i / steps;
    const y = marginTop + plotH * (1 - frac);
    ctx.beginPath();
    ctx.moveTo(marginLeft, y);
    ctx.lineTo(marginLeft + plotW, y);
    ctx.stroke();
    ctx.fillText(labelFmt(scaleMax * frac), marginLeft - 6, y);
  }

  if (hist.length < 2) return;

  keys.forEach((key, idx) => {
    ctx.strokeStyle = SERIES_COLORS[idx];
    ctx.lineWidth = 2;
    ctx.beginPath();
    hist.forEach((pt, i) => {
      const x = marginLeft + (i / (hist.length - 1)) * plotW;
      const clamped = Math.max(0, Math.min(pt[key], scaleMax));
      const y = marginTop + plotH * (1 - clamped / scaleMax);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
}

function wireControls() {
  document.querySelectorAll(".channel-control[data-ch]").forEach((ctrl) => {
    const ch = ctrl.dataset.ch;
    if (ch === "3") return; // CH3 gestito a parte, non ha set-v/set-i

    const vInput = ctrl.querySelector(".set-v");
    const iInput = ctrl.querySelector(".set-i");
    const applyBtn = ctrl.querySelector(".apply");

    const doApply = async () => {
      const v = parseLocaleFloat(vInput.value);
      const i = parseLocaleFloat(iInput.value);
      const pending = pendingSetpoint[ch];
      if (v !== null) {
        pending.v = lastSetpointSeq;
        vInput.value = "";
        await fetch(`/api/channel/${ch}/voltage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value: v }),
        });
      }
      if (i !== null) {
        pending.i = lastSetpointSeq;
        iInput.value = "";
        await fetch(`/api/channel/${ch}/current`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value: i }),
        });
      }
      refreshStatus();
    };

    applyBtn.addEventListener("click", doApply);
    [vInput, iInput].forEach((input) => {
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); doApply(); input.blur(); }
      });
    });

    ctrl.querySelector(".toggle-output").addEventListener("click", async (e) => {
      const turningOn = e.target.classList.contains("off");
      const action = turningOn ? "accendere" : "spegnere";
      if (!confirm(`Confermi di voler ${action} l'uscita CH${ch}?`)) return;
      await fetch(`/api/channel/${ch}/output`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ on: turningOn }),
      });
      refreshStatus();
    });
  });

  const sendCh3 = async (turningOn) => {
    const action = turningOn ? "accendere" : "spegnere";
    if (!confirm(`Confermi di voler ${action} l'uscita CH3?`)) return;
    await fetch(`/api/channel/3/output`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on: turningOn }),
    });
  };
  els.ch3Off.addEventListener("click", () => sendCh3(false));
  els.ch3On.addEventListener("click", () => sendCh3(true));

  els.logToggle.addEventListener("click", async () => {
    const starting = !els.logToggle.classList.contains("active");
    const res = await fetch(`/api/logging/${starting ? "start" : "stop"}`, { method: "POST" });
    const data = await res.json();
    els.logFile.textContent = starting && data.file ? `→ ${data.file}` : "";
    refreshStatus();
  });
}

wireControls();
refreshStatus();
refreshHistoryAndDraw();
setInterval(refreshStatus, POLL_MS);
setInterval(refreshHistoryAndDraw, 800);
