"""Entry point mono-comando: server FastAPI che serve API + frontend statico
dallo stesso processo, e apre il browser in automatico.

Uso:
    python app.py
"""

import csv
import os
import threading
import time
import webbrowser
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from spd3303c import SPD3303C, SPD3303CError, VOLTAGE_MAX, CURRENT_MAX

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
STATIC_DIR = os.path.join(APP_DIR, "static")
os.makedirs(DATA_DIR, exist_ok=True)

FAST_POLL_PAUSE_S = 0.02  # pausa tra un ciclo di misura e il successivo (oltre al tempo delle query stesse)
SETPOINT_EVERY_N_CYCLES = 3  # i setpoint cambiano solo per comando/pannello: bastano ~1 volta/sec
HISTORY_LEN = 1500
PORT = 8420

# Un solo thread di polling: evita la contesa tra thread concorrenti sulla
# stessa connessione USB, che rendeva più facile sforare il timeout e
# innescare la desincronizzazione USBTMC (vedi SPD3303C.invalidate()).
instrument = SPD3303C(io_delay=0.045)

state_lock = threading.Lock()
state = {
    "connected": False,
    "idn": None,
    "error": None,
    "timestamp": None,
    "track_mode": "unknown",
    "locked": False,
    "meas_seq": 0,      # incrementato a ogni campionamento di tensione/corrente misurate
    "setpoint_seq": 0,  # incrementato a ogni campionamento dei setpoint V/I
    "channels": {
        1: {"v_meas": 0.0, "i_meas": 0.0, "v_set": 0.0, "i_set": 0.0, "mode": "CV", "on": False},
        2: {"v_meas": 0.0, "i_meas": 0.0, "v_set": 0.0, "i_set": 0.0, "mode": "CV", "on": False},
    },
    "logging": False,
}
history = deque(maxlen=HISTORY_LEN)

_log_file = None
_log_writer = None
_logging_flag = threading.Event()


def _open_log_file():
    fname = os.path.join(DATA_DIR, f"log_{datetime.now():%Y%m%d_%H%M%S}.csv")
    f = open(fname, "w", newline="")
    w = csv.writer(f)
    w.writerow(["timestamp", "ch1_v", "ch1_i", "ch1_mode", "ch1_on", "ch2_v", "ch2_i", "ch2_mode", "ch2_on"])
    return fname, f, w


def poll_loop():
    """Unico ciclo di polling: stato + misure a ogni giro, setpoint ogni
    SETPOINT_EVERY_N_CYCLES giri (cambiano solo per comando o pannello)."""
    global _log_file, _log_writer
    cycle = 0
    while True:
        try:
            if not instrument.connected:
                instrument.connect()
            status = instrument.get_status()
            ts = datetime.now().isoformat(timespec="seconds")
            meas = {}
            for ch in (1, 2):
                meas[ch] = {
                    "v_meas": instrument.measure_voltage(ch),
                    "i_meas": instrument.measure_current(ch),
                    "mode": status[f"ch{ch}_mode"],
                    "on": status[f"ch{ch}_on"],
                }

            cycle += 1
            read_setpoints = (cycle % SETPOINT_EVERY_N_CYCLES) == 0
            setpoints = None
            if read_setpoints:
                setpoints = {
                    ch: {
                        "v_set": instrument.get_setpoint_voltage(ch),
                        "i_set": instrument.get_setpoint_current(ch),
                    }
                    for ch in (1, 2)
                }

            with state_lock:
                state["connected"] = True
                state["error"] = None
                state["idn"] = instrument.idn
                state["timestamp"] = ts
                state["track_mode"] = status["track_mode"]
                state["locked"] = status["locked"]
                state["meas_seq"] += 1
                for ch in (1, 2):
                    state["channels"][ch].update(meas[ch])
                if setpoints is not None:
                    state["setpoint_seq"] += 1
                    for ch in (1, 2):
                        state["channels"][ch].update(setpoints[ch])
                state["logging"] = _logging_flag.is_set()
                history.append({
                    "t": ts,
                    "ch1_v": meas[1]["v_meas"], "ch1_i": meas[1]["i_meas"],
                    "ch2_v": meas[2]["v_meas"], "ch2_i": meas[2]["i_meas"],
                })
                if _logging_flag.is_set() and _log_writer:
                    _log_writer.writerow([
                        ts,
                        meas[1]["v_meas"], meas[1]["i_meas"], meas[1]["mode"], meas[1]["on"],
                        meas[2]["v_meas"], meas[2]["i_meas"], meas[2]["mode"], meas[2]["on"],
                    ])
                    _log_file.flush()
        except SPD3303CError as e:
            with state_lock:
                state["connected"] = False
                state["error"] = str(e)
            time.sleep(0.5)  # evita di martellare l'hardware/USB se scollegato
        except Exception as e:
            instrument.invalidate()  # per sicurezza, anche se l'eccezione non viene da SPD3303C
            with state_lock:
                state["connected"] = False
                state["error"] = f"Errore inatteso: {e}"
            time.sleep(0.5)
        time.sleep(FAST_POLL_PAUSE_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=poll_loop, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/api/status")
def api_status():
    with state_lock:
        return dict(state)


@app.get("/api/history")
def api_history():
    with state_lock:
        return list(history)


class SetValue(BaseModel):
    value: float = Field(..., ge=0)


class SetOutput(BaseModel):
    on: bool


def _check_channel(ch: int):
    if ch not in (1, 2):
        raise HTTPException(400, "Canale non valido (usa 1 o 2)")


def _refresh_setpoint(ch: int):
    """Rilegge subito il setpoint dopo un comando, invece di aspettare il ciclo lento."""
    try:
        v_set = instrument.get_setpoint_voltage(ch)
        i_set = instrument.get_setpoint_current(ch)
    except SPD3303CError:
        return
    with state_lock:
        state["setpoint_seq"] += 1
        state["channels"][ch].update({"v_set": v_set, "i_set": i_set})


@app.post("/api/channel/{ch}/voltage")
def set_voltage(ch: int, body: SetValue):
    _check_channel(ch)
    if body.value > VOLTAGE_MAX:
        raise HTTPException(400, f"Tensione fuori range (0-{VOLTAGE_MAX}V)")
    try:
        instrument.set_voltage(ch, body.value)
    except SPD3303CError as e:
        raise HTTPException(503, str(e))
    _refresh_setpoint(ch)
    return {"ok": True}


@app.post("/api/channel/{ch}/current")
def set_current(ch: int, body: SetValue):
    _check_channel(ch)
    if body.value > CURRENT_MAX:
        raise HTTPException(400, f"Corrente fuori range (0-{CURRENT_MAX}A)")
    try:
        instrument.set_current(ch, body.value)
    except SPD3303CError as e:
        raise HTTPException(503, str(e))
    _refresh_setpoint(ch)
    return {"ok": True}


@app.post("/api/channel/{ch}/output")
def set_output(ch: int, body: SetOutput):
    if ch not in (1, 2, 3):
        raise HTTPException(400, "Canale non valido (usa 1, 2 o 3)")
    try:
        instrument.set_output(ch, body.on)
    except SPD3303CError as e:
        raise HTTPException(503, str(e))
    return {"ok": True}


def _refresh_mode_flags():
    """Rilegge subito lock/track mode dopo un comando, come per i setpoint."""
    try:
        status = instrument.get_status()
    except SPD3303CError:
        return
    with state_lock:
        state["track_mode"] = status["track_mode"]
        state["locked"] = status["locked"]


class SetLock(BaseModel):
    locked: bool


class SetTrack(BaseModel):
    mode: int


@app.post("/api/lock")
def set_lock(body: SetLock):
    try:
        instrument.set_lock(body.locked)
    except SPD3303CError as e:
        raise HTTPException(503, str(e))
    _refresh_mode_flags()
    return {"ok": True}


@app.post("/api/track")
def set_track(body: SetTrack):
    if body.mode not in (0, 1, 2):
        raise HTTPException(400, "Modalità non valida (0=independent, 1=series, 2=parallel)")
    try:
        instrument.set_track_mode(body.mode)
    except SPD3303CError as e:
        raise HTTPException(503, str(e))
    _refresh_mode_flags()
    return {"ok": True}


@app.post("/api/logging/{action}")
def logging_control(action: str):
    global _log_file, _log_writer
    if action == "start":
        with state_lock:
            if not _logging_flag.is_set():
                fname, _log_file, _log_writer = _open_log_file()
                _logging_flag.set()
                return {"ok": True, "file": os.path.basename(fname)}
            return {"ok": True, "already": True}
    elif action == "stop":
        with state_lock:
            _logging_flag.clear()
            if _log_file:
                _log_file.close()
                _log_file = None
                _log_writer = None
        return {"ok": True}
    raise HTTPException(400, "Azione non valida (usa start o stop)")


# Catch-all per servire il frontend statico (deve stare per ultimo).
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def main():
    url = f"http://127.0.0.1:{PORT}"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
