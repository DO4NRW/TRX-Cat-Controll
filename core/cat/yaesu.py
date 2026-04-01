"""
Yaesu CAT Protokoll — funktioniert für FT-991A, FT-891, FT-710, FT-DX101D,
FT-DX10, FT-950, FT-2000, FT-450, FT-857, FT-818 und ähnliche.
Alle nutzen das gleiche Befehlsformat: CMD[params];
"""

from core.cat import CatBase

MODE_TO_CODE = {
    "LSB": "1", "USB": "2", "CW": "3", "FM": "4", "AM": "5",
    "RTTY-L": "6", "CW-R": "7", "DATA-L": "8", "RTTY-U": "9",
    "DATA-FM": "A", "FM-N": "B", "DATA-U": "C",
    "D-L": "8", "D-U": "C", "RTTY": "6",
}
CODE_TO_MODE = {
    "1": "LSB", "2": "USB", "3": "CW", "4": "FM", "5": "AM",
    "6": "RTTY", "7": "CW-R", "8": "D-L", "9": "RTTY-U",
    "A": "DATA-FM", "B": "FM-N", "C": "D-U",
}


class YaesuCat(CatBase):
    """Yaesu CAT Protokoll (FT-991A, FT-891, FT-710, FTDX-101D etc.)."""

    def _on_connect(self):
        self._raw_send("AI0;")

    # ── Frequency ─────────────────────────────────────────────────────

    def get_frequency(self) -> int | None:
        resp = self._query("FA;")
        if resp and resp.startswith("FA") and len(resp) >= 10:
            try:
                return int(resp[2:])
            except ValueError:
                pass
        return None

    def set_frequency(self, hz: int):
        hz = max(30_000, min(470_000_000, int(hz)))
        self._send(f"FA{hz:09d};")

    # ── Mode ──────────────────────────────────────────────────────────

    def get_mode(self) -> str | None:
        resp = self._query("MD0;")
        if resp and resp.startswith("MD0") and len(resp) == 4:
            return CODE_TO_MODE.get(resp[3], f"MODE_{resp[3]}")
        return None

    def set_mode(self, mode: str):
        code = MODE_TO_CODE.get(mode.upper())
        if code:
            self._send(f"MD0{code};")

    # ── S-Meter ───────────────────────────────────────────────────────

    def get_smeter(self) -> int | None:
        resp = self._query("SM0;")
        if resp and resp.startswith("SM0") and len(resp) == 6:
            try:
                return int(resp[3:])
            except ValueError:
                pass
        return None

    # ── PTT ───────────────────────────────────────────────────────────

    def ptt_on(self):
        self._send("TX1;")

    def ptt_off(self):
        self._send("TX0;")

    # ── RF Power ──────────────────────────────────────────────────────

    def get_power(self) -> int | None:
        resp = self._query("PC;")
        if resp and resp.startswith("PC") and len(resp) == 5:
            try:
                return int(resp[2:])
            except ValueError:
                pass
        return None

    def set_power(self, pct: int):
        pct = max(5, min(100, int(pct)))
        self._send(f"PC{pct:03d};")

    # ── Preamp / ATT ──────────────────────────────────────────────────

    def get_preamp(self) -> str | None:
        resp = self._query("PA0;")
        if resp and resp.startswith("PA0") and len(resp) == 4:
            return {"0": "IPO", "1": "AMP1", "2": "AMP2"}.get(resp[3])
        return None

    def set_preamp(self, mode: str):
        codes = {"IPO": "0", "AMP1": "1", "AMP2": "2"}
        code = codes.get(mode.upper(), "0")
        self._send(f"PA0{code};")

    def get_att(self) -> bool | None:
        resp = self._query("RA0;")
        if resp and resp.startswith("RA0") and len(resp) == 5:
            return resp[3:5] == "01"
        return None

    def set_att(self, on: bool):
        self._send("RA01;" if on else "RA00;")

    # ── DSP ───────────────────────────────────────────────────────────

    def set_nb(self, on: bool):
        self._send("NB01;" if on else "NB00;")

    def set_dnr(self, on: bool):
        self._send("NR01;" if on else "NR00;")

    def set_dnr_level(self, level: int):
        level = max(1, min(15, int(level)))
        self._send(f"RL0{level:02d};")

    def get_dnr_level(self) -> int | None:
        resp = self._query("RL0;")
        if resp and resp.startswith("RL0"):
            try:
                return int(resp[3:])
            except ValueError:
                pass
        return None

    def set_dnf(self, on: bool):
        self._send("BC01;" if on else "BC00;")
