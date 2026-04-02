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
    0x04: "RTTY", 0x05: "FM", 0x06: "WFM", 0x07: "CW-R",
    0x08: "RTTY-R",
}
MODE_TO_ICOM = {v: k for k, v in ICOM_MODES.items()}


class IcomCat(CatBase):
    """Icom CI-V Protokoll (IC-7300, IC-705, IC-7610 etc.)."""

    def __init__(self, civ_address=0x94, **kwargs):
        super().__init__(**kwargs)
        self._civ_addr = civ_address
        self._ctrl_addr = 0xE0  # Controller (PC) Adresse
        self._scope_buffer = []  # Gepufferte Scope-Frames
        self._scope_spectrum = [0] * 475
        self._scope_last_div = 0
        self._scope_div_max = 11
        self._scope_latest = None
        self._scope_span_hz = 0
        self._scope_center_hz = 0
        self._poll_dbg_count = 0
        import threading
        self._scope_lock = threading.Lock()

    def _on_connect(self):
        pass

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

    def _read_all_frames(self):
        """Alle CI-V Frames aus dem Serial-Buffer lesen und nach Typ sortieren."""
        if not self._ser or not self._ser.is_open:
            return []
        import time
        time.sleep(0.03)
        buf = b""
        while self._ser.in_waiting > 0:
            buf += self._ser.read(self._ser.in_waiting)
            time.sleep(0.005)
        if not buf:
            buf = self._ser.read(128)

        frames = []
        while True:
            start = buf.find(bytes([0xFE, 0xFE]))
            if start < 0:
                break
            end = buf.find(bytes([0xFD]), start)
            if end < 0:
                break
            frames.append(buf[start:end + 1])
            buf = buf[end + 1:]
        return frames

    def _civ_query(self, cmd, sub=None, data=b""):
        """CI-V Befehl senden und Antwort parsen. Scope-Frames werden gepuffert."""
        with self._lock:
            if not self._ser or not self._ser.is_open:
                return None
            try:
                frame = self._build_frame(cmd, sub, data)
                self._ser.reset_input_buffer()
                self._ser.write(frame)

                frames = self._read_all_frames()

                result = None
                for f in frames:
                    if len(f) < 5:
                        continue
                    # Scope-Daten (0x27 0x00) separat puffern (thread-safe)
                    if len(f) >= 6 and f[2] == self._ctrl_addr and f[4] == 0x27 and f[5] == 0x00:
                        with self._scope_lock:
                            self._scope_buffer.append(f)
                        continue
                    # ACK/NAK
                    if f[2] == self._ctrl_addr and f[4] in (0xFB, 0xFA):
                        result = self._parse_response(f)
                        continue
                    # Antwort muss zum gesendeten Command + Sub passen
                    if f[2] == self._ctrl_addr and f[4] == cmd and result is None:
                        # Sub-Command auch prüfen wenn vorhanden
                        if sub is not None and len(f) >= 6 and f[5] != sub:
                            continue  # Falscher Sub-Command
                        result = self._parse_response(f)

                return result
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

    @staticmethod
    def _int_to_bcd_msb(value, length=2):
        """Integer → BCD bytes (MSB first, für Level/Gain/Power)."""
        data = []
        for _ in range(length):
            lo = value % 10
            value //= 10
            hi = value % 10
            value //= 10
            data.append((hi << 4) | lo)
        return bytes(reversed(data))

    @staticmethod
    def _bcd_to_int_msb(data):
        """BCD bytes → integer (MSB first, für Level/Gain/Power)."""
        result = 0
        for b in data:
            hi = (b >> 4) & 0x0F
            lo = b & 0x0F
            result = result * 100 + hi * 10 + lo
        return result

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
                base_mode = ICOM_MODES.get(data[0], f"MODE_{data[0]:02X}")
                # DATA-Flag prüfen (0x1A 0x06)
                data_result = self._civ_query(0x1A, sub=0x06)
                if data_result:
                    _, d = data_result
                    if len(d) >= 2 and d[1] > 0:
                        # DATA aktiv → D-L oder D-U
                        if base_mode == "LSB":
                            return "D-L"
                        elif base_mode == "USB":
                            return "D-U"
                return base_mode
        return None

    def set_mode(self, mode: str):
        upper = mode.upper()
        # DATA-Modes: Basis-Mode setzen + DATA-Flag
        if upper in ("D-L", "DATA-L"):
            self._civ_send(0x06, data=bytes([0x00, 0x01]))  # LSB
            import time; time.sleep(0.05)
            self._civ_send(0x1A, sub=0x06, data=bytes([0x01]))  # DATA ON
        elif upper in ("D-U", "DATA-U"):
            self._civ_send(0x06, data=bytes([0x01, 0x01]))  # USB
            import time; time.sleep(0.05)
            self._civ_send(0x1A, sub=0x06, data=bytes([0x01]))  # DATA ON
        else:
            code = MODE_TO_ICOM.get(upper)
            if code is not None:
                self._civ_send(0x06, data=bytes([code, 0x01]))
                import time; time.sleep(0.05)
                self._civ_send(0x1A, sub=0x06, data=bytes([0x00]))  # DATA OFF

    # ── S-Meter ───────────────────────────────────────────────────────

    def get_smeter(self) -> int | None:
        result = self._civ_query(0x15, sub=0x02)  # Read S-meter
        if result:
            cmd, data = result
            if len(data) >= 3 and data[0] == 0x02:
                # Icom S-Meter: 2 BCD bytes, 0000-0241 (MSB first)
                # z.B. [0x01, 0x20] = 0120 = 120
                hi = (data[1] >> 4) * 10 + (data[1] & 0x0F)
                lo = (data[2] >> 4) * 10 + (data[2] & 0x0F)
                raw = hi * 100 + lo
                # Icom Standard: 0=S0, 120=S9, 241=S9+60dB
                # Raw direkt zurückgeben (0-241), Display regelt den Rest
                return min(255, raw)
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
                raw = self._bcd_to_int_msb(data[1:3])
                return min(100, round(raw / 255 * 100))
        return None

    def set_power(self, pct: int):
        pct = max(0, min(100, int(pct)))
        raw = round(pct / 100 * 255)
        data = self._int_to_bcd_msb(raw, 2)
        self._civ_query(0x14, sub=0x0A, data=data)

    def get_power_raw(self) -> int | None:
        """Power als Rohwert 0-255 lesen (kein Prozent-Umrechnen)."""
        result = self._civ_query(0x14, sub=0x0A)
        if result:
            cmd, data = result
            if len(data) >= 3 and data[0] == 0x0A:
                return self._bcd_to_int_msb(data[1:3])
        return None

    def set_power_raw(self, raw: int):
        """Power als Rohwert 0-255 setzen (kein Prozent-Umrechnen)."""
        raw = max(0, min(255, int(raw)))
        data = self._int_to_bcd_msb(raw, 2)
        self._civ_query(0x14, sub=0x0A, data=data)

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
        # IC-705: 0x00=OFF, 0x20=20dB
        self._civ_send(0x11, data=bytes([0x20 if on else 0x00]))

    # ── DSP ───────────────────────────────────────────────────────────

    def set_nb(self, on: bool):
        # IC-705/IC-7300: NB via 0x16 0x22
        self._civ_send(0x16, sub=0x22, data=bytes([0x01 if on else 0x00]))
        # Alternativ für ältere Modelle: Retry mit 0x16 0x20
        if not on:
            return
        import time; time.sleep(0.05)
        # Prüfen ob es geklappt hat
        result = self._civ_query(0x16, sub=0x22)
        if result is None:
            # Fallback für andere Modelle
            self._civ_send(0x16, sub=0x20, data=bytes([0x01 if on else 0x00]))

    def set_dnr(self, on: bool):
        self._civ_send(0x16, sub=0x40, data=bytes([0x01 if on else 0x00]))

    def set_dnf(self, on: bool):
        """Auto Notch (0x16 0x41). APF wäre 0x16 0x32."""
        self._civ_send(0x16, sub=0x41, data=bytes([0x01 if on else 0x00]))

    # ── AGC ───────────────────────────────────────────────────────────

    _AGC_MAP = {0x00: "OFF", 0x01: "SLOW", 0x02: "MID", 0x03: "FAST"}
    _AGC_REV = {"OFF": 0x00, "SLOW": 0x01, "MID": 0x02, "FAST": 0x03}

    def get_agc(self) -> str | None:
        result = self._civ_query(0x16, sub=0x12)
        if result:
            cmd, data = result
            if len(data) >= 2 and data[0] == 0x12:
                return self._AGC_MAP.get(data[1], "SLOW")
        return None

    def set_agc(self, mode: str):
        val = self._AGC_REV.get(mode.upper(), 0x01)
        self._civ_query(0x16, sub=0x12, data=bytes([val]))

    # ── Compressor ────────────────────────────────────────────────────

    def get_comp(self) -> bool | None:
        result = self._civ_query(0x16, sub=0x44)
        if result:
            cmd, data = result
            if len(data) >= 2 and data[0] == 0x44:
                return data[1] == 0x01
        return None

    def set_comp(self, on: bool):
        self._civ_query(0x16, sub=0x44, data=bytes([0x01 if on else 0x00]))

    # ── Split / VFO ───────────────────────────────────────────────────

    def get_split(self) -> bool | None:
        result = self._civ_query(0x0F)
        if result:
            cmd, data = result
            if len(data) >= 1:
                return data[0] == 0x01
        return None

    def set_split(self, on: bool):
        self._civ_query(0x0F, data=bytes([0x01 if on else 0x00]))

    def set_vfo(self, vfo: str):
        val = 0x00 if vfo.upper() == "A" else 0x01
        self._civ_query(0x07, data=bytes([val]))

    def swap_vfo(self):
        self._civ_query(0x07, data=bytes([0xB0]))

    # ── RIT ───────────────────────────────────────────────────────────

    def set_rit(self, on: bool):
        self._civ_query(0x21, sub=0x01, data=bytes([0x01 if on else 0x00]))

    def set_xit(self, on: bool):
        self._civ_query(0x21, sub=0x02, data=bytes([0x01 if on else 0x00]))

    # ── Notch Frequency ────────────────────────────────────────────────

    def set_notch_freq(self, hz: int):
        """Manual Notch Position setzen (IC-705: 0x14 0x0D, 0-255 BCD MSB)."""
        raw = min(255, max(0, round(hz / 3200 * 255)))
        data = self._int_to_bcd_msb(raw, 2)
        # Manual Notch einschalten + Position setzen (send statt query wegen Scope-Interferenz)
        self._civ_send(0x16, sub=0x48, data=bytes([0x01]))
        self._civ_send(0x14, sub=0x0D, data=data)

    # ── Scope / Waterfall ─────────────────────────────────────────────

    def scope_enable(self, on=True):
        """Scope ein/ausschalten und Wave Data Output aktivieren."""
        self._civ_send(0x27, sub=0x10, data=bytes([0x01 if on else 0x00]))
        if on:
            import time; time.sleep(0.05)
            self._civ_send(0x27, sub=0x11, data=bytes([0x01]))  # Wave output ON

    def _start_scope_thread(self):
        """Scope-Lese-Thread starten."""
        if self._scope_thread and self._scope_thread.is_alive():
            return
        import threading
        self._scope_running = True
        self._scope_thread = threading.Thread(target=self._scope_loop, daemon=True)
        self._scope_thread.start()

    def _stop_scope_thread(self):
        self._scope_running = False

    def _flush_scope_from_serial(self):
        """Lese wartende Daten vom Serial-Port — non-blocking wenn Query läuft."""
        if not self._lock.acquire(blocking=False):
            return  # Query läuft gerade, nicht blockieren
        try:
            if not self._ser or not self._ser.is_open or self._ser.in_waiting == 0:
                return
            import time
            buf = b""
            while self._ser.in_waiting > 0:
                buf += self._ser.read(self._ser.in_waiting)
                time.sleep(0.003)
            while True:
                start = buf.find(bytes([0xFE, 0xFE]))
                if start < 0:
                    break
                end = buf.find(bytes([0xFD]), start)
                if end < 0:
                    break
                f = buf[start:end + 1]
                buf = buf[end + 1:]
                if len(f) >= 6 and f[2] == self._ctrl_addr and f[4] == 0x27 and f[5] == 0x00:
                    self._scope_buffer.append(f)
        except Exception:
            pass
        finally:
            self._lock.release()

    @staticmethod
    def _bcd_byte(b):
        """Ein BCD-Byte → Dezimalzahl (0x11 → 11, nicht 17)."""
        return (b & 0x0F) + ((b >> 4) & 0x0F) * 10

    def _scope_loop(self):
        """Hintergrund-Thread: liest kontinuierlich Scope-Daten vom Serial-Port."""
        import time
        spectrum = [0] * 475
        last_div = 0
        while self._scope_running and self.connected:
            try:
                self._flush_scope_from_serial()

                with self._scope_lock:
                    frames = self._scope_buffer[:]
                    self._scope_buffer.clear()

                if not frames:
                    time.sleep(0.01)
                    continue

                for frame in frames:
                    if len(frame) < 10:
                        continue

                    # BCD-codierte Division-Nummern (wie wfview)
                    div_order = self._bcd_byte(frame[7])
                    div_max = self._bcd_byte(frame[8])

                    if div_order == 1:
                        # Neuer Sweep — altes Spektrum abliefern
                        if last_div > 1:
                            with self._scope_lock:
                                self._scope_latest = spectrum[:]
                        spectrum = [0] * 475
                        last_div = 1
                        continue

                    if div_order <= last_div and last_div > 1:
                        # Neuer Sweep ohne Div 1 Header
                        with self._scope_lock:
                            self._scope_latest = spectrum[:]
                        spectrum = [0] * 475

                    last_div = div_order

                    # Waveform ab Byte 9 (nach 00, div, max Header)
                    # Div 2+: 3 Bytes Mini-Header + Waveform
                    wave_data = frame[9:-1]
                    if not wave_data:
                        continue

                    # wfview Style: Division 1 hat Header, 2+ haben nur Waveform
                    # Offset = (div-2) * Punkte pro Division
                    points_per_div = len(wave_data)
                    offset = (div_order - 2) * 50  # 50 Bytes pro Division

                    for i, val in enumerate(wave_data):
                        idx = offset + i
                        if 0 <= idx < 475:
                            spectrum[idx] = min(160, val)

                    if div_order >= div_max:
                        with self._scope_lock:
                            self._scope_latest = spectrum[:]
                        spectrum = [0] * 475
                        last_div = 0

            except Exception:
                time.sleep(0.03)

    def scope_read(self):
        """Scope-Daten live verarbeiten. Jede Division sofort ins Spektrum."""
        frames = self._scope_buffer[:]
        self._scope_buffer.clear()

        if not frames:
            return None

        changed = False
        for frame in frames:
            if len(frame) < 10:
                continue

            div_order = self._bcd_byte(frame[7])
            div_max = self._bcd_byte(frame[8])

            if div_order == 1:
                if len(frame) >= 18:
                    self._scope_center_hz = self._bcd_to_int(frame[10:15])
                    self._scope_span_hz = self._bcd_to_int(frame[15:18])
                continue

            wave_data = frame[9:-1]
            if not wave_data:
                continue

            if div_order < 2 or div_order > 11:
                continue
            offset = (div_order - 2) * 50
            for i, val in enumerate(wave_data):
                idx = offset + i
                if 0 <= idx < 475:
                    self._scope_spectrum[idx] = min(160, val)
            changed = True

        return self._scope_spectrum[:] if changed else None
