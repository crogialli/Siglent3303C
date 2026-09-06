const POLL_MS = 1000;
const VOLT_SCALE_MAX = 32;

const els = {
  connStatus: document.getElementById("conn-status"),
  trackMode: document.getElementById("track-mode"),
  logToggle: document.getElementById("log-toggle"),
  logFile: document.getElementById("log-file"),
  chart: document.getElementById("chart"),
};

function fmt(value, decimals) {
  return Number(value).toFixed(decimals).padStart(decimals + 3, "0");
}

function updateChannel(ch, data) {
  document.getElementById(`v-${ch}`).textContent = fmt(data.v_meas, 2);
  document.getElementById(`i-${ch}`).textContent = fmt(data.i_meas, 3);
  const led = document.getElementById(`led-${ch}`);
  led.classList.remove("cv", "cc");
  led.classList.add(data.mode === "CC" ? "cc" : "cv");
  led.title = data.mode;

  const ctrl = document.querySelector(`.channel-control[data-ch="${ch}"]`);
  const outBtn = ctrl.querySelector(".toggle-output");
  outBtn.textContent = data.on ? "ON" : "OFF";
  outBtn.classList.toggle("on", data.on);
  outBtn.classList.toggle("off", !data.on);

  const vInput = ctrl.querySelector(".set-v");
  const iInput = ctrl.querySelector(".set-i");
  if (document.activeElement !== vInput) vInput.placeholder = data.v_set.toFixed(2);
  if (document.activeElement !== iInput) iInput.placeholder = data.i_set.toFixed(3);
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
    updateChannel(1, data.channels["1"]);
    updateChannel(2, data.channels["2"]);

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
    drawChart(hist);
  } catch (e) {
    /* ignora, ridisegnerà al prossimo giro */
  }
}

function drawChart(hist) {
  const canvas = els.chart;
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  // griglia
  ctx.strokeStyle = "#2a2a2e";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = (h / 4) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }

  if (hist.length < 2) return;

  const plot = (key, color) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    hist.forEach((pt, idx) => {
      const x = (idx / (hist.length - 1)) * w;
      const y = h - (Math.min(pt[key], VOLT_SCALE_MAX) / VOLT_SCALE_MAX) * h;
      if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  };

  plot("ch1_v", "#7CFC7C");
  plot("ch2_v", "#ffb347");
}

function wireControls() {
  document.querySelectorAll(".channel-control").forEach((ctrl) => {
    const ch = ctrl.dataset.ch;

    ctrl.querySelector(".apply").addEventListener("click", async () => {
      const v = ctrl.querySelector(".set-v").value;
      const i = ctrl.querySelector(".set-i").value;
      if (v !== "") {
        await fetch(`/api/channel/${ch}/voltage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value: parseFloat(v) }),
        });
      }
      if (i !== "") {
        await fetch(`/api/channel/${ch}/current`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value: parseFloat(i) }),
        });
      }
      refreshStatus();
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
setInterval(refreshHistoryAndDraw, 2000);
