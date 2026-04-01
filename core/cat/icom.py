"""
Icom CI-V Protokoll — funktioniert für IC-7300, IC-7610, IC-705, IC-9700, IC-7100.
CI-V nutzt Binärframes: FE FE <to> <from> <cmd> [<sub>] [<data>] FD
"""

import struct
from core.cat import CatBase

# Icom CI-V Adressen (Default, kann in Config überschrieben werden)
RIG_ADDRESSES = {
    "ic7300": 0x94,
    "ic7610": 0x98,
    "ic705":  0xA4,
    "ic9700": 0xA2,
    "ic7100": 0x88,
}

ICOM_MODES = {
    0x00: "LSB", 0x01: "USB", 0x02: "AM", 0x03: "CW",
    0x04: "RTTY", 0x05: "FM", 0x07: "CW-R", 0x08: "RTTY-R",
    0x17: "D-L",  0x18: "D-U",
}
MODE_TO_ICOM = {v: k for k, v in ICOM_MODES.items()}
MODE_TO_ICOM.update({"DATA-L": 0x17, "DATA-U": 0x18})


class IcomCat(CatBase):
    """Icom CI-V Protokoll (IC-7300, IC-705, IC-7610 etc.)."""

    def __init__(self, civ_address=0x94, **kwargs):
        super().__init__(**kwargs)
        self._civ_addr = civ_address
        self._ctrl_addr = 0xE0  # Controller (PC) Adresse

    def _on_connect(self):
        pass  # Icom braucht keine Init-Befehle

    # ── CI-V Frame ────────────────────────────────────────────────────

    def _build_frame(self, cmd, sub=None, data=b""):
        """CI-V Frame bauen: FE FE <to> <from> <cmd> [<sub>] [<data>] FD"""
        frame = bytes([0xFE, 0xFE, self._civ_addr, self._ctrl_addr, cmd])
        if sub is not None:
            frame += bytes([sub])
        frame += data + bytes([0xFD])
        return frame

    def _parse_response(self, raw):
        """CI-V Response parsen. Return (cmd, sub, data) oder None."""
        if not raw or len(raw) < 6:
            return None
        # Suche FE FE
        idx = raw.find(bytes([0xFE, 0xFE]))
        if idx < 0:
            return None
        raw = raw[idx:]
        # Suche FD (Ende)
        end = raw.find(bytes([0xFD]))
        if end < 0:
            return None
        frame = raw[:end + 1]
        if len(frame) < 6:
            return None
        cmd = frame[4]
        data = frame[5:-1]
        return cmd, data

    def _civ_query(self, cmd, sub=None, data=b""):
        """CI-V Befehl senden und Antwort parsen."""
        with self._lock:
            if not self._ser or not self._ser.is_open:
                return None
            try:
                frame = self._build_frame(cmd, sub, data)
                self._ser.reset_input_buffer()
                self._ser.write(frame)
                # Antwort lesen (max 64 bytes, bis FD)
                resp = self._ser.read(64)
                # Echo überspringen (Icom sendet Echo zurück)
                # Suche zweites FE FE (= Antwort vom Rig)
                first = resp.find(bytes([0xFE, 0xFE]))
                if first >= 0:
                    second = resp.find(bytes([0xFE, 0xFE]), first + 2)
                    if second >= 0:
                        resp = resp[second:]
                return self._parse_response(resp)
            except Exception:
                return None

    def _civ_send(self, cmd, sub=None, data=b""):
        """CI-V Befehl senden, keine Antwort erwartet."""
        with self._lock:
            if not self._ser or not self._ser.is_open:
                return
            try:
                frame = self._build_frame(cmd, sub, data)
                self._ser.write(frame)
            except Exception:
                pass

    # ── BCD Konvertierung ─────────────────────────────────────────────

    @staticmethod
    def _bcd_to_int(data):
        """BCD bytes → integer (LSB first, Icom Frequenz-Format)."""
        result = 0
        for i, b in enumerate(data):
            lo = b & 0x0F
            hi = (b >> 4) & 0x0F
            result += (hi * 10 + lo) * (100 ** i)
        return result

    @staticmethod
    def _int_to_bcd(value, length=5):
        """Integer → BCD bytes (LSB first, Icom Frequenz-Format)."""
        data = []
        for _ in range(length):
            lo = value % 10
            value //= 10
            hi = value % 10
            value //= 10
            data.append((hi << 4) | lo)
        return bytes(data)

    # ── Frequency ─────────────────────────────────────────────────────

    def get_frequency(self) -> int | None:
        result = self._civ_query(0x03)  # Read frequency
        if result:
            cmd, data = result
            if cmd == 0x03 and len(data) == 5:
                return self._bcd_to_int(data)
        return None

    def set_frequency(self, hz: int):
        hz = max(30_000, min(470_000_000, int(hz)))
        data = self._int_to_bcd(hz, 5)
        self._civ_send(0x05, data=data)  # Set frequency

    # ── Mode ──────────────────────────────────────────────────────────

    def get_mode(self) -> str | None:
        result = self._civ_query(0x04)  # Read mode
        if result:
            cmd, data = result
            if cmd == 0x04 and len(data) >= 1:
                return ICOM_MODES.get(data[0], f"MODE_{data[0]:02X}")
        return None

    def set_mode(self, mode: str):
        code = MODE_TO_ICOM.get(mode.upper())
        if code is not None:
            self._civ_send(0x06, data=bytes([code, 0x01]))  # Mode + Filter

    # ── S-Meter ───────────────────────────────────────────────────────

    def get_smeter(self) -> int | None:
        result = self._civ_query(0x15, sub=0x02)  # Read S-meter
        if result:
            cmd, data = result
            if len(data) >= 3 and data[0] == 0x02:
                # BCD Format: 2 bytes → 0000-0255
                return self._bcd_to_int(data[1:3])
        return None

    # ── PTT ───────────────────────────────────────────────────────────

    def ptt_on(self):
        self._civ_send(0x1C, sub=0x00, data=bytes([0x01]))

    def ptt_off(self):
        self._civ_send(0x1C, sub=0x00, data=bytes([0x00]))

    # ── RF Power ──────────────────────────────────────────────────────

    def get_power(self) -> int | None:
        result = self._civ_query(0x14, sub=0x0A)
        if result:
            cmd, data = result
            if len(data) >= 3 and data[0] == 0x0A:
                raw = self._bcd_to_int(data[1:3])
                return min(100, int(raw / 255 * 100))
        return None

    def set_power(self, pct: int):
        pct = max(0, min(100, int(pct)))
        raw = int(pct / 100 * 255)
        data = self._int_to_bcd(raw, 2)
        self._civ_send(0x14, sub=0x0A, data=data)

    # ── Preamp / ATT ──────────────────────────────────────────────────

    def get_preamp(self) -> str | None:
        result = self._civ_query(0x16, sub=0x02)
        if result:
            cmd, data = result
            if len(data) >= 2 and data[0] == 0x02:
                return {0x00: "OFF", 0x01: "AMP1", 0x02: "AMP2"}.get(data[1], "OFF")
        return None

    def set_preamp(self, mode: str):
        codes = {"OFF": 0x00, "IPO": 0x00, "AMP1": 0x01, "AMP2": 0x02}
        code = codes.get(mode.upper(), 0x00)
        self._civ_send(0x16, sub=0x02, data=bytes([code]))

    def get_att(self) -> bool | None:
        result = self._civ_query(0x11)
        if result:
            cmd, data = result
            if cmd == 0x11 and len(data) >= 1:
                return data[0] != 0x00
        return None

    def set_att(self, on: bool):
        self._civ_send(0x11, data=bytes([0x20 if on else 0x00]))

    # ── DSP ───────────────────────────────────────────────────────────

    def set_nb(self, on: bool):
        self._civ_send(0x16, sub=0x22, data=bytes([0x01 if on else 0x00]))

    def set_dnr(self, on: bool):
        self._civ_send(0x16, sub=0x40, data=bytes([0x01 if on else 0x00]))

    def set_dnf(self, on: bool):
        self._civ_send(0x16, sub=0x32, data=bytes([0x01 if on else 0x00]))
