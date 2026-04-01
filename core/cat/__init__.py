"""
Globaler CAT-Handler — dispatcht nach Protokoll (Yaesu, Icom, Kenwood, Elecraft).
Einheitliche API für alle Rigs.
"""

import serial
import threading
import logging

log = logging.getLogger(__name__)


class CatBase:
    """Basis-Klasse für alle CAT-Protokolle. Einheitliche API."""

    def __init__(self, port="/dev/ttyUSB0", baud=38400, data_bits=8,
                 stop_bits=1, parity="N", timeout=0.5, handshake=None):
        self._port = port
        self._baud = baud
        self._data_bits = data_bits
        self._stop_bits = stop_bits
        self._parity = parity
        self._timeout = timeout
        self._handshake = handshake
        self._ser: serial.Serial | None = None
        self._lock = threading.Lock()
        self.connected = False

    # ── Connection ────────────────────────────────────────────────────

    def connect(self) -> bool:
        parity_map = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}
        stop_map = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}
        with self._lock:
            try:
                self._ser = serial.Serial(
                    port=self._port,
                    baudrate=self._baud,
                    bytesize=self._data_bits or serial.EIGHTBITS,
                    parity=parity_map.get(self._parity or "N", serial.PARITY_NONE),
                    stopbits=stop_map.get(self._stop_bits or 1, serial.STOPBITS_ONE),
                    timeout=self._timeout,
                    rtscts=self._handshake == "RTS/CTS",
                    xonxoff=self._handshake == "XON/XOFF",
                    dsrdtr=False,
                )
                self._on_connect()
                self.connected = True
                log.info("CAT connected on %s @ %d", self._port, self._baud)
                return True
            except Exception as e:
                log.error("CAT connect failed: %s", e)
                self._ser = None
                self.connected = False
                return False

    def _on_connect(self):
        """Override für protokoll-spezifische Init-Befehle nach Connect."""
        pass

    def disconnect(self):
        self.connected = False
        try:
            if self._ser and self._ser.is_open:
                self._ser.close()
        except Exception:
            pass
        self._ser = None
        log.info("CAT disconnected")

    # ── Low-level ─────────────────────────────────────────────────────

    def _raw_send(self, cmd: bytes | str):
        if isinstance(cmd, str):
            cmd = cmd.encode()
        self._ser.reset_input_buffer()
        self._ser.write(cmd)

    def _query(self, cmd: str, terminator=b";") -> str | None:
        with self._lock:
            if not self._ser or not self._ser.is_open:
                return None
            try:
                self._raw_send(cmd)
                response = self._ser.read_until(terminator).decode(errors="ignore").strip()
                return response.rstrip(terminator.decode())
            except Exception as e:
                log.error("CAT query '%s' failed: %s", cmd, e)
                return None

    def _send(self, cmd: str):
        with self._lock:
            if not self._ser or not self._ser.is_open:
                return
            try:
                self._raw_send(cmd)
            except Exception as e:
                log.error("CAT send '%s' failed: %s", cmd, e)

    # ── Einheitliche API (Override in Subklassen) ─────────────────────

    def get_frequency(self) -> int | None:
        return None

    def set_frequency(self, hz: int):
        pass

    def step_frequency(self, step_hz: int):
        freq = self.get_frequency()
        if freq is not None:
            self.set_frequency(freq + step_hz)

    def get_mode(self) -> str | None:
        return None

    def set_mode(self, mode: str):
        pass

    def get_smeter(self) -> int | None:
        return None

    def ptt_on(self):
        pass

    def ptt_off(self):
        pass

    def get_power(self) -> int | None:
        return None

    def set_power(self, pct: int):
        pass

    def get_preamp(self) -> str | None:
        return None

    def set_preamp(self, mode: str):
        pass

    def get_att(self) -> bool | None:
        return None

    def set_att(self, on: bool):
        pass

    def set_nb(self, on: bool):
        pass

    def set_dnr(self, on: bool):
        pass

    def set_dnr_level(self, level: int):
        pass

    def get_dnr_level(self) -> int | None:
        return None

    def set_dnf(self, on: bool):
        pass

    def get_info(self) -> dict:
        return {
            "frequency": self.get_frequency(),
            "mode": self.get_mode(),
            "smeter": self.get_smeter(),
            "preamp": self.get_preamp(),
            "att": self.get_att(),
        }


# ── Factory ───────────────────────────────────────────────────────────

def create_cat_handler(protocol: str, **kwargs) -> CatBase:
    """Erstelle CAT-Handler nach Protokoll-Name."""
    protocol = protocol.lower()
    if protocol == "yaesu":
        from core.cat.yaesu import YaesuCat
        return YaesuCat(**kwargs)
    elif protocol == "icom":
        from core.cat.icom import IcomCat
        return IcomCat(**kwargs)
    elif protocol == "kenwood":
        from core.cat.kenwood import KenwoodCat
        return KenwoodCat(**kwargs)
    elif protocol == "elecraft":
        from core.cat.kenwood import KenwoodCat  # Elecraft nutzt Kenwood-Protokoll
        return KenwoodCat(**kwargs)
    else:
        raise ValueError(f"Unbekanntes CAT-Protokoll: {protocol}")
