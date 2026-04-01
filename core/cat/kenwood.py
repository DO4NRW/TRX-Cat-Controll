"""
Kenwood CAT Protokoll — funktioniert für TS-890S, TS-2000, TS-590SG, TS-480.
Auch Elecraft K3/KX2/KX3 nutzen das Kenwood-Protokoll.
Befehle: CMD[params]; (ähnlich Yaesu, aber andere Codes)
"""

from core.cat import CatBase

KENWOOD_MODES = {
    "1": "LSB", "2": "USB", "3": "CW", "4": "FM",
    "5": "CW-R", "6": "RTTY", "7": "CW-R",
    "9": "RTTY-R",
}
MODE_TO_KENWOOD = {
    "LSB": "1", "USB": "2", "CW": "3", "FM": "4",
    "CW-R": "5", "RTTY": "6", "RTTY-R": "9",
    "D-L": "6", "D-U": "2", "DATA-L": "6", "DATA-U": "2",
}


class KenwoodCat(CatBase):
    """Kenwood/Elecraft CAT Protokoll (TS-890S, K3, KX2 etc.)."""

    def _on_connect(self):
        self._raw_send("AI0;")

    # ── Frequency ─────────────────────────────────────────────────────

    def get_frequency(self) -> int | None:
        resp = self._query("FA;")
        if resp and resp.startswith("FA"):
            try:
                return int(resp[2:])
            except ValueError:
                pass
        return None

    def set_frequency(self, hz: int):
        hz = max(30_000, min(470_000_000, int(hz)))
        self._send(f"FA{hz:011d};")

    # ── Mode ──────────────────────────────────────────────────────────

    def get_mode(self) -> str | None:
        resp = self._query("MD;")
        if resp and resp.startswith("MD") and len(resp) >= 3:
            return KENWOOD_MODES.get(resp[2], f"MODE_{resp[2]}")
        return None

    def set_mode(self, mode: str):
        code = MODE_TO_KENWOOD.get(mode.upper())
        if code:
            self._send(f"MD{code};")

    # ── S-Meter ───────────────────────────────────────────────────────

    def get_smeter(self) -> int | None:
        resp = self._query("SM0;")
        if resp and resp.startswith("SM"):
            try:
                return int(resp[2:].lstrip("0") or "0")
            except ValueError:
                pass
        return None

    # ── PTT ───────────────────────────────────────────────────────────

    def ptt_on(self):
        self._send("TX;")

    def ptt_off(self):
        self._send("RX;")

    # ── RF Power ──────────────────────────────────────────────────────

    def get_power(self) -> int | None:
        resp = self._query("PC;")
        if resp and resp.startswith("PC"):
            try:
                return int(resp[2:])
            except ValueError:
                pass
        return None

    def set_power(self, pct: int):
        pct = max(0, min(100, int(pct)))
        self._send(f"PC{pct:03d};")

    # ── Preamp / ATT ──────────────────────────────────────────────────

    def get_preamp(self) -> str | None:
        resp = self._query("PA;")
        if resp and resp.startswith("PA") and len(resp) >= 3:
            return {"0": "OFF", "1": "AMP1"}.get(resp[2], "OFF")
        return None

    def set_preamp(self, mode: str):
        codes = {"OFF": "0", "IPO": "0", "AMP1": "1"}
        code = codes.get(mode.upper(), "0")
        self._send(f"PA{code};")

    def get_att(self) -> bool | None:
        resp = self._query("RA;")
        if resp and resp.startswith("RA") and len(resp) >= 4:
            return resp[2:4] != "00"
        return None

    def set_att(self, on: bool):
        self._send("RA01;" if on else "RA00;")

    # ── DSP ───────────────────────────────────────────────────────────

    def set_nb(self, on: bool):
        self._send("NB1;" if on else "NB0;")

    def set_dnr(self, on: bool):
        self._send("NR1;" if on else "NR0;")

    def set_dnf(self, on: bool):
        self._send("NT1;" if on else "NT0;")
