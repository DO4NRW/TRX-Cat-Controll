import time

class CatHandler:
    def __init__(self, parent):
        self.p = parent

    # ---------- low level ----------
    def _query(self, ser, cmd, expect_prefix=None, timeout=0.2):
        if not ser or not getattr(ser, "is_open", False):
            return None
        old_timeout = None
        try:
            old_timeout = getattr(ser, "timeout", None)
            try:
                ser.timeout = timeout
            except Exception:
                pass
            try:
                ser.reset_input_buffer()
            except Exception:
                pass
            ser.write(f"{cmd};".encode())
            ans = ser.read_until(b';').decode(errors='ignore').strip()
            if not ans:
                return None
            if expect_prefix and not ans.startswith(expect_prefix):
                return None
            return ans
        except Exception:
            return None
        finally:
            try:
                if old_timeout is not None:
                    ser.timeout = old_timeout
            except Exception:
                pass

    def send_command(self, ser, cmd):
        if ser and getattr(ser, "is_open", False):
            try:
                ser.write(f"{cmd};".encode())
                return True
            except Exception:
                return False
        return False

    # ---------- basic rig ----------
    def get_freq(self, ser):
        ans = self._query(ser, "FA", expect_prefix="FA", timeout=0.2)
        if ans and len(ans) >= 11:
            return ans[2:11]
        return None

    def set_freq(self, ser, hz):
        try:
            hz = int(hz)
        except Exception:
            return False
        if hz < 30000 or hz > 470000000:
            return False
        cmd = f"FA{hz:09d}"
        if not self.send_command(ser, cmd):
            return False
        time.sleep(0.05)
        back = self.get_freq(ser)
        return True if back is None else (back == f"{hz:09d}")

    def get_mode_code(self, ser):
        ans = self._query(ser, "MD0", expect_prefix="MD0", timeout=0.2)
        if ans and len(ans) >= 4:
            return ans[3].upper()
        return None

    def mode_code_to_label(self, code):
        code = str(code).strip().upper() if code is not None else ""
        mapping = {
            "1": "LSB",
            "2": "USB",
            "4": "FM",
            "5": "AM",
            "6": "RTTY",
            "9": "RTTY",
        }
        return mapping.get(code, f"MODE {code}" if code else "---")

    def mode_label_to_code(self, label):
        lbl = str(label).strip().upper()
        mapping = {"LSB": "1", "USB": "2", "FM": "4", "AM": "5", "RTTY": "9"}
        return mapping.get(lbl)

    def get_mode_label(self, ser):
        return self.mode_code_to_label(self.get_mode_code(ser))

    def set_mode(self, ser, mode_code):
        code = str(mode_code).strip().upper()
        if code not in {"1", "2", "4", "5", "6", "9"}:
            return False
        if not self.send_command(ser, f"MD0{code}"):
            return False
        time.sleep(0.05)
        back = self.get_mode_code(ser)
        return True if back is None else (back == code)

    # ---------- meters ----------
    def get_s_meter_raw(self, ser):
        ans = self._query(ser, "SM0", expect_prefix="SM0", timeout=0.15)
        if ans and len(ans) >= 6:
            try:
                return max(0, min(255, int(ans[3:6])))
            except Exception:
                return None
        return None

    # ---------- PTT ----------
    def set_ptt_hardware(self, ser_ptt, active, method, invert):
        if method == "CAT":
            if self.p.ser_cat and self.p.ser_cat.is_open:
                self.send_command(self.p.ser_cat, "TX1" if active else "TX0")
            return
        if method in ("RTS", "DTR") and ser_ptt and ser_ptt.is_open:
            phys_level = active if not invert else not active
            try:
                if method == "RTS":
                    ser_ptt.setRTS(phys_level)
                else:
                    ser_ptt.setDTR(phys_level)
            except Exception:
                pass

    # ---------- TRX toggles ----------
    def toggle_att(self, ser, state):
        return self.send_command(ser, "RA01" if state else "RA00")

    def toggle_nb(self, ser, state):
        return self.send_command(ser, "NB01" if state else "NB00")

    def toggle_dnr(self, ser, state):
        return self.send_command(ser, "NR01" if state else "NR00")

    # DNF = Auto Notch (FT-991A). Some variants used DFxx; we send BCxx and accept DFxx for read.
    def toggle_dnf(self, ser, state):
        return self.send_command(ser, "BC01" if state else "BC00") or self.send_command(ser, "DF01" if state else "DF00")

    # Manual NOTCH: when enabling, also send current frequency (4 digits).
    def toggle_notch(self, ser, state):
        try:
            freq = int(float(getattr(self.p, "manual_notch_freq", None).get()))
        except Exception:
            freq = 1000
        return self.set_manual_notch_state(ser, state, freq_hz=freq)

    # ---------- state readers ----------
    def _parse_bool_last01(self, ans):
        if not ans:
            return None
        for ch in reversed(str(ans)):
            if ch in ("0", "1"):
                return ch == "1"
        return None

    def _get_bool_state(self, ser, query_cmd, expect_prefix=None, timeout=0.2):
        ans = self._query(ser, query_cmd, expect_prefix=expect_prefix or query_cmd, timeout=timeout)
        return self._parse_bool_last01(ans)

    def get_att_state(self, ser):
        return self._get_bool_state(ser, "RA0", expect_prefix="RA0")

    def get_nb_state(self, ser):
        return self._get_bool_state(ser, "NB0", expect_prefix="NB0")

    def get_dnr_state(self, ser):
        return self._get_bool_state(ser, "NR0", expect_prefix="NR0")

    def get_auto_notch_state(self, ser):
        v = self._get_bool_state(ser, "BC0", expect_prefix="BC0")
        if v is None:
            v = self._get_bool_state(ser, "DF0", expect_prefix="DF0")
        return v

    # ---------- DNR level 1..15 ----------
    def get_dnr_level(self, ser):
        # Some firmwares answer as RL0xx, some as RLxx
        ans = self._query(ser, "RL0", expect_prefix="RL", timeout=0.2)
        if not ans:
            ans = self._query(ser, "RL", expect_prefix="RL", timeout=0.2)
        if ans:
            try:
                digits = "".join(ch for ch in str(ans) if ch.isdigit())
                if len(digits) >= 2:
                    v = int(digits[-2:])
                    return max(1, min(15, v))
            except Exception:
                return None
        return None

    def set_dnr_level(self, ser, level):
        try:
            level = int(round(float(level)))
        except Exception:
            return False
        level = max(1, min(15, level))
        if not (self.send_command(ser, f"RL0{level:02d}") or self.send_command(ser, f"RL{level:02d}")):
            return False
        time.sleep(0.05)
        back = self.get_dnr_level(ser)
        return True if back is None else (back == level)

    # ---------- Preamp / IPO ----------
    def preamp_code_to_label(self, code):
        mapping = {"0": "IPO", "1": "AMP1", "2": "AMP2", 0: "IPO", 1: "AMP1", 2: "AMP2"}
        return mapping.get(code, "IPO")

    def preamp_label_to_code(self, label):
        mapping = {"IPO": "0", "AMP1": "1", "AMP 1": "1", "AMP2": "2", "AMP 2": "2", "0": "0", "1": "1", "2": "2"}
        return mapping.get(str(label).strip().upper() if label is not None else "", "0")

    def get_preamp_mode(self, ser):
        ans = self._query(ser, "PA0", expect_prefix="PA0", timeout=0.2)
        if ans and len(ans) >= 4:
            c = ans[3]
            return c if c in ("0", "1", "2") else None
        return None

    def get_preamp_mode_label(self, ser):
        c = self.get_preamp_mode(ser)
        return self.preamp_code_to_label(c) if c is not None else None

    def set_preamp_mode(self, ser, mode):
        code = self.preamp_label_to_code(mode)
        if not self.send_command(ser, f"PA0{code}"):
            return False
        time.sleep(0.05)
        back = self.get_preamp_mode(ser)
        return True if back is None else (back == code)

    # ---------- Manual NOTCH freq/state (4 digits) ----------
    def _parse_last_digits(self, ans, n):
        if not ans:
            return None
        digits = "".join(ch for ch in str(ans) if ch.isdigit())
        if len(digits) < n:
            return None
        try:
            return int(digits[-n:])
        except Exception:
            return None

    def get_manual_notch_freq(self, ser):
        ans = self._query(ser, "BP0", expect_prefix="BP0", timeout=0.2)
        if not ans:
            return None
        digits = "".join(ch for ch in str(ans)[3:] if ch.isdigit())
        if len(digits) >= 4:
            p2 = digits[0]
            p3 = digits[1:4]
            try:
                val = int(p3)
            except Exception:
                return None
            # P2=1 => frequency in steps of 10 Hz, 001..320
            if p2 == "1":
                return max(10, min(3200, val * 10))
            # P2=0 => ON/OFF answer, no separate frequency available here
            return None
        return None

    def get_manual_notch_state(self, ser):
        ans = self._query(ser, "BP0", expect_prefix="BP0", timeout=0.2)
        if not ans:
            return None
        digits = "".join(ch for ch in str(ans)[3:] if ch.isdigit())
        # Expected payload: P2 + P3P3P3
        if len(digits) >= 4:
            p2 = digits[0]
            p3 = digits[1:4]
            if p2 == "0":
                return p3 == "001"
            if p2 == "1":
                return True
        return self._parse_bool_last01(ans)

    def set_manual_notch_state(self, ser, state, freq_hz=1000):
        try:
            freq_hz = int(round(float(freq_hz)))
        except Exception:
            freq_hz = 1000
        # FT-991A: BP P2=0 => ON/OFF, P3=000 OFF / 001 ON. Frequency is separate with P2=1 and 001-320 = x10 Hz.
        if state:
            ok = self.send_command(ser, "BP00001")
            time.sleep(0.03)
            self.set_manual_notch_freq(ser, freq_hz)
            return ok
        return self.send_command(ser, "BP00000")

    def set_manual_notch_freq(self, ser, freq_hz):
        try:
            freq_hz = int(round(float(freq_hz)))
        except Exception:
            return False
        freq_hz = max(10, min(3200, freq_hz))
        cat_val = max(1, min(320, int(round(freq_hz / 10.0))))
        if not self.send_command(ser, f"BP01{cat_val:03d}"):
            return False
        time.sleep(0.05)
        back = self.get_manual_notch_freq(ser)
        return True if back is None else (abs(back - freq_hz) <= 10)

    # ---------- RF Power ----------
    def get_rf_power(self, ser):
        ans = self._query(ser, "PC", expect_prefix="PC", timeout=0.2)
        if ans and len(ans) >= 5:
            try:
                return max(0, min(100, int(ans[2:5])))
            except Exception:
                return None
        return None

    def set_rf_power(self, ser, power):
        try:
            power = int(round(float(power)))
        except Exception:
            return False
        power = max(0, min(100, power))
        return self.send_command(ser, f"PC{power:03d}")
