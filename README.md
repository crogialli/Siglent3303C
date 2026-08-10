# Siglent3303C

Interfaccia per il controllo remoto SCPI dell'alimentatore Siglent SPD3303C via USBTMC.

## Contesto

Lo SPD3303C espone comandi SCPI via USB (classe USBTMC), utilizzabili su macOS/Linux
tramite `pyvisa` + `pyvisa-py` (backend `libusb`), senza bisogno di NI-VISA o del
software Windows-only fornito da Siglent (EasyPower).

Nota di compatibilità: il firmware non è pienamente conforme USBTMC — senza impostare
esplicitamente `read_termination` / `write_termination = '\n'` su pyvisa, le query
vanno in timeout.

## Obiettivo

Interfaccia grafica di base per leggere/impostare tensione e corrente sui canali
CH1/CH2 e monitorare lo stato (CV/CC, ON/OFF), basata sul set di comandi SCPI
documentato nel Quick Start SPD3303C (sezione "Remote Control").
