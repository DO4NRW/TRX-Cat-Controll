"""
RigLink — WSJT-X UDP-Listener
Empfängt Decode-Daten von WSJT-X via UDP-Port 2237 (QDataStream, big-endian).
Kein externes Paket nötig — parst das Binärprotokoll direkt.

WSJT-X Protokoll-Referenz:
  NetworkMessage.hpp aus dem WSJT-X Quellcode (Hamlib-Projekt)

Verwendung:
  listener = WsjtxListener()
  listener.decoded.connect(slot)   # slot(utc, snr, dt, freq_hz, message, mode)
  listener.start()
  # ...
  listener.stop()
"""

import socket
import struct
import threading
import logging

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

WSJTX_UDP_PORT = 2237
WSJTX_MAGIC    = 0xADBCCBDA
_MSG_STATUS    = 1
_MSG_DECODE    = 2
_MSG_CLEAR     = 3


class WsjtxListener(QObject):
    """
    UDP-Listener für WSJT-X Decode-Pakete.
    Erbt von QObject — Signale werden automatisch als QueuedConnection
    in den Main-Thread geleitet (UDP-Thread emittiert, Main-Thread empfängt).
    """

    # (utc_str, snr, dt_sek, freq_hz, nachricht, modus)
    decoded = Signal(str, int, float, int, str, str)
    # (dial_freq_hz, modus, dx_call, tx_aktiv)
    status  = Signal(int, str, str, bool)
    # Port-Bind-Fehler o.ä.
    error   = Signal(str)

    def __init__(self, port: int = WSJTX_UDP_PORT, parent=None):
        super().__init__(parent)
        self._port    = port
        self._sock    = None
        self._running = False
        self._thread  = None

    # ── Public API ────────────────────────────────────────────────────

    def start(self) -> bool:
        """Bindet UDP-Socket und startet Empfangs-Thread. Gibt False bei Fehler."""
        if self._running:
            return True
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("0.0.0.0", self._port))
            self._sock.settimeout(1.0)
        except OSError as e:
            self.error.emit(f"Port {self._port} nicht verfügbar: {e}")
            log.error("WsjtxListener bind fehlgeschlagen: %s", e)
            return False

        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="wsjtx-udp")
        self._thread.start()
        log.info("WsjtxListener gestartet auf :%d", self._port)
        return True

    def stop(self):
        """Stoppt Listener-Thread und schließt Socket."""
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.info("WsjtxListener gestoppt")

    @property
    def is_running(self) -> bool:
        return self._running

    # ── UDP-Empfangs-Thread ───────────────────────────────────────────

    def _loop(self):
        while self._running:
            try:
                data, _ = self._sock.recvfrom(4096)
                self._dispatch(data)
            except socket.timeout:
                continue
            except OSError:
                break

    def _dispatch(self, data: bytes):
        try:
            if len(data) < 12:
                return
            magic,    off = _u32(data, 0)
            if magic != WSJTX_MAGIC:
                return
            _schema,  off = _u32(data, off)
            msg_type, off = _u32(data, off)
            _id,      off = _qstr(data, off)   # Client-ID überspringen

            if msg_type == _MSG_DECODE:
                self._parse_decode(data, off)
            elif msg_type == _MSG_STATUS:
                self._parse_status(data, off)
        except Exception as e:
            log.debug("WSJT-X Dispatch-Fehler: %s", e)

    def _parse_decode(self, data: bytes, off: int):
        """
        Decode-Paket (type=2) — Reihenfolge gemäß NetworkMessage.hpp:
          new(bool) → time_ms(uint32) → snr(int32) → delta_time(float64)
          → delta_freq(uint32) → mode(QStr) → message(QStr)
          → low_confidence(bool) → off_air(bool)
        """
        _new,     off = _bool(data, off)
        time_ms,  off = _u32(data, off)
        snr,      off = _i32(data, off)
        dt_sec,   off = _f64(data, off)
        freq_hz,  off = _u32(data, off)
        mode,     off = _qstr(data, off)
        message,  off = _qstr(data, off)
        # low_confidence + off_air nicht benötigt

        # ms seit UTC-Mitternacht → HH:MM:SS
        h = (time_ms // 3_600_000) % 24
        m = (time_ms %  3_600_000) // 60_000
        s = (time_ms %     60_000) // 1_000
        utc = f"{h:02d}:{m:02d}:{s:02d}"

        self.decoded.emit(utc, int(snr), float(dt_sec), int(freq_hz), message, mode)

    def _parse_status(self, data: bytes, off: int):
        """
        Status-Paket (type=1) — erste Felder nach Header:
          dial_freq(uint64) → mode(QStr) → dx_call(QStr)
          → report(QStr) → tx_mode(QStr) → tx_enabled(bool) → ...
        """
        dial_freq,  off = _u64(data, off)
        mode,       off = _qstr(data, off)
        dx_call,    off = _qstr(data, off)
        _report,    off = _qstr(data, off)
        _tx_mode,   off = _qstr(data, off)
        tx_enabled, off = _bool(data, off)

        self.status.emit(int(dial_freq), mode, dx_call, tx_enabled)


# ── Binär-Helfer (big-endian, QDataStream-Kompatibel) ────────────────

def _u32(buf: bytes, off: int):
    return struct.unpack_from('>I', buf, off)[0], off + 4

def _i32(buf: bytes, off: int):
    return struct.unpack_from('>i', buf, off)[0], off + 4

def _u64(buf: bytes, off: int):
    return struct.unpack_from('>Q', buf, off)[0], off + 8

def _f64(buf: bytes, off: int):
    return struct.unpack_from('>d', buf, off)[0], off + 8

def _bool(buf: bytes, off: int):
    return bool(buf[off]), off + 1

def _qstr(buf: bytes, off: int):
    """Qt QDataStream-String: uint32 Länge (0xFFFFFFFF = Null-String) + UTF-8 Bytes."""
    length, off = _u32(buf, off)
    if length == 0xFFFFFFFF:
        return "", off
    text = buf[off:off + length].decode("utf-8", errors="replace")
    return text, off + length
