"""Driver SCPI/USBTMC per l'alimentatore Siglent SPD3303C.

Basato sul set di comandi documentato nel Quick Start (sezione "Remote Control").
Nota: il firmware non è pienamente conforme USBTMC — senza read_termination/
write_termination espliciti a '\\n', le query vanno in timeout.
"""

import threading
import time

import pyvisa

VOLTAGE_MAX = 32.0
CURRENT_MAX = 3.2

_TRACK_MODES = {1: "independent", 2: "parallel", 3: "series"}


class SPD3303CError(Exception):
    pass


class SPD3303C:
    def __init__(self, io_delay=0.12, timeout_ms=3000):
        self._lock = threading.RLock()
        self._rm = None
        self._inst = None
        self._io_delay = io_delay
        self._timeout_ms = timeout_ms
        self.connected = False
        self.idn = None

    def connect(self, resource=None):
        with self._lock:
            rm = pyvisa.ResourceManager("@py")
            if resource is None:
                candidates = [r for r in rm.list_resources() if r.startswith("USB")]
                if not candidates:
                    raise SPD3303CError("Nessun dispositivo USBTMC trovato")
                resource = candidates[0]
            inst = rm.open_resource(resource)
            inst.timeout = self._timeout_ms
            inst.read_termination = "\n"
            inst.write_termination = "\n"
            self._rm = rm
            self._inst = inst
            try:
                self.idn = self._query_locked("*IDN?")
            except Exception as e:
                self.invalidate()
                raise SPD3303CError(f"Errore comunicazione durante la connessione: {e}") from e
            self.connected = True

    def _write_locked(self, cmd):
        self._inst.write(cmd)
        time.sleep(self._io_delay)

    def _query_locked(self, cmd):
        self._inst.write(cmd)
        time.sleep(self._io_delay)
        return self._inst.read().strip()

    def _guard(self):
        if not self.connected or self._inst is None:
            raise SPD3303CError("Strumento non connesso")

    def invalidate(self):
        """Chiude la sessione USB corrente e forza una riconnessione pulita.

        Va chiamato ogni volta che una query/scrittura fallisce (es. timeout):
        il firmware non è pienamente conforme USBTMC, quindi una risposta
        rimasta "in coda" dopo un timeout può altrimenti essere letta da una
        query successiva non correlata (visto in pratica: SYSTem:STATus?
        letto al posto di *IDN? dopo un errore).
        """
        with self._lock:
            self.connected = False
            if self._inst is not None:
                try:
                    self._inst.close()
                except Exception:
                    pass
                self._inst = None

    def query(self, cmd):
        with self._lock:
            self._guard()
            try:
                return self._query_locked(cmd)
            except Exception as e:
                self.invalidate()
                raise SPD3303CError(f"Errore comunicazione: {e}") from e

    def write(self, cmd):
        with self._lock:
            self._guard()
            try:
                self._write_locked(cmd)
            except Exception as e:
                self.invalidate()
                raise SPD3303CError(f"Errore comunicazione: {e}") from e

    def _query_and_parse(self, cmd, parse):
        """Query + parsing della risposta, invalidando la sessione se la
        risposta non è nel formato atteso (risposta di un'altra query letta
        per errore dopo un timeout, non solo un timeout esplicito)."""
        raw = self.query(cmd)
        try:
            return parse(raw)
        except ValueError as e:
            self.invalidate()
            raise SPD3303CError(f"Risposta inattesa a '{cmd}': {raw!r}") from e

    # --- letture ---

    def measure_voltage(self, ch):
        return self._query_and_parse(f"MEASure:VOLTage? CH{ch}", float)

    def measure_current(self, ch):
        return self._query_and_parse(f"MEASure:CURRent? CH{ch}", float)

    def get_setpoint_voltage(self, ch):
        return self._query_and_parse(f"CH{ch}:VOLTage?", float)

    def get_setpoint_current(self, ch):
        return self._query_and_parse(f"CH{ch}:CURRent?", float)

    def get_status(self):
        raw = self.query("SYSTem:STATus?")
        try:
            val = int(raw, 16)
        except ValueError as e:
            self.invalidate()
            raise SPD3303CError(f"Risposta inattesa a 'SYSTem:STATus?': {raw!r}") from e
        return {
            "raw": raw,
            "ch1_mode": "CC" if val & 0x01 else "CV",
            "ch2_mode": "CC" if val & 0x02 else "CV",
            "track_mode": _TRACK_MODES.get((val >> 2) & 0x03, "unknown"),
            "ch1_on": bool(val & 0x10),
            "ch2_on": bool(val & 0x20),
        }

    # --- scritture (comandano l'uscita reale) ---

    def set_voltage(self, ch, value):
        if not (0 <= value <= VOLTAGE_MAX):
            raise SPD3303CError(f"Tensione fuori range (0-{VOLTAGE_MAX}V)")
        self.write(f"CH{ch}:VOLTage {value:.3f}")

    def set_current(self, ch, value):
        if not (0 <= value <= CURRENT_MAX):
            raise SPD3303CError(f"Corrente fuori range (0-{CURRENT_MAX}A)")
        self.write(f"CH{ch}:CURRent {value:.3f}")

    def set_output(self, ch, state):
        self.write(f"OUTPut CH{ch},{'ON' if state else 'OFF'}")
