import json
import os
import time

import customtkinter as ctk
import numpy as np
import serial

from core.audio_engine import AudioEngine
from core.cat_handler import CatHandler
from core.logging_setup import setup_session_logs
from ui_components import UIComponents


class DO4NRWTRXPro(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_file = os.path.join(self.base_dir, "defaults", "trx_config.json")

        # Session logs (reset on every start)
        self.actions_logger, self.errors_logger, self.actions_log_path, self.error_log_path = setup_session_logs()

        self.init_vars()
        self.load_settings()

        self.audio = AudioEngine(self)
        self.cat = CatHandler(self)
        self.ui = UIComponents(self)

        self.title("DO4NRW-TRX-Control Pro v14.6 freq")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.ui.build_main_ui()
        self.ui.finalize_and_center(self)

        # Frequency entry edit guards
        self.freq_entry_editing = False
        self.freq_entry_dirty = False

        self.bind("<KeyPress-space>", self.start_tx)
        self.bind("<KeyRelease-space>", self.stop_tx)

        self._refresh_idle_ui()
        self._sync_frequency_widgets()
        self.update_loop()


    # ----------------------------
    # Init / Config
    # ----------------------------
    def init_vars(self):
        # CAT / Serial
        self.cat_port = ctk.StringVar(value="COM9")
        self.baud_rate = ctk.StringVar(value="38400")

        # PTT
        self.ptt_method_val = ctk.StringVar(value="RTS")  # RTS/DTR/CAT
        self.ptt_port = ctk.StringVar(value="COM10")
        self.ptt_invert = ctk.BooleanVar(value=False)

        # Rig state
        self.rig_mode = ctk.StringVar(value="USB")
        self.tune_step = ctk.StringVar(value="1000")
        self.last_freq = 145_500_000

        # Audio routing
        self.pc_mic = ctk.StringVar(value="")
        self.mic_sr = ctk.StringVar(value="44100")
        self.mic_ch = ctk.StringVar(value="1")

        self.trx_mic = ctk.StringVar(value="")
        self.tmic_sr = ctk.StringVar(value="44100")
        self.tmic_ch = ctk.StringVar(value="2")

        self.trx_spk = ctk.StringVar(value="")
        self.tspk_sr = ctk.StringVar(value="44100")
        self.tspk_ch = ctk.StringVar(value="2")

        self.pc_spk = ctk.StringVar(value="")
        self.pspk_sr = ctk.StringVar(value="44100")
        self.pspk_ch = ctk.StringVar(value="2")

        # VOX
        self.vox_enabled = ctk.BooleanVar(value=False)
        self.vox_threshold_dbfs = ctk.StringVar(value="-25")
        self.vox_hang_ms = ctk.StringVar(value="700")

        # MUTE (RX audio to PC)
        self.mute_enabled = ctk.BooleanVar(value=False)

        # DSP / misc
        self.dnr_level = ctk.StringVar(value="1")
        self.manual_notch_freq = ctk.StringVar(value="0100")  # Hz (4-stellig Anzeige)
        self.preamp_state = ctk.StringVar(value="IPO")
        self.pwr_level = ctk.StringVar(value="50")

        # S-meter tables
        self.s_meter_tables = {"IPO": [], "AMP1": [], "AMP2": []}

        # S-meter bar scaling (optional overrides per AMP/IPO)
        self.s_meter_bar_max = {"IPO": 255, "AMP1": 255, "AMP2": 255}

        self.s_meter_bar_min = {"IPO": 0, "AMP1": 0, "AMP2": 0}

        # Runtime
        self.is_connected = False
        self.disconnecting = False
        self.ptt_active = False
        self._manual_tx = False

        self.ser_cat = None
        self.ser_ptt = None

        self.st_tx_in = None
        self.st_tx_out = None
        self.st_rx_in = None
        self.st_rx_out = None

        self._ui_job = None
        self._freq_entry_dirty = False
        self._dnr_set_job = None
        self._notch_set_job = None
        self._pwr_set_job = None
        self._mode_poll_counter = 0

        # meters
        self.cat_s_raw = 0
        self.cat_s_smooth = 0.0

        self.tx_rms_db = -60.0
        self.tx_peak_db = -60.0
        self.tx_target_db = -60.0
        self.tx_meter_db = -60.0
        self.tx_peak_hold_db = -60.0
        self.tx_peak_hold_ts = time.time()
        self.tx_clipped = False

        # VOX runtime
        self._vox_force_rx_until = 0.0
        self._vox_last_above = 0.0

    def load_settings(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            else:
                cfg = {}
        except Exception as e:
            print(f"Config load error: {e}")
            cfg = {}

        def g(key, default=None):
            return cfg.get(key, default)

        self.cat_port.set(g("cat_port", self.cat_port.get()))
        self.baud_rate.set(g("baud_rate", self.baud_rate.get()))
        self.ptt_port.set(g("ptt_port", self.ptt_port.get()))
        self.ptt_invert.set(bool(g("ptt_invert", self.ptt_invert.get())))

        self.pc_mic.set(g("pc_mic", self.pc_mic.get()))
        self.trx_mic.set(g("trx_mic", self.trx_mic.get()))
        self.trx_spk.set(g("trx_spk", self.trx_spk.get()))
        self.pc_spk.set(g("pc_spk", self.pc_spk.get()))

        self.mic_sr.set(g("mic_sr", self.mic_sr.get()))
        self.tmic_sr.set(g("tmic_sr", self.tmic_sr.get()))
        self.tspk_sr.set(g("tspk_sr", self.tspk_sr.get()))
        self.pspk_sr.set(g("pspk_sr", self.pspk_sr.get()))

        self.mic_ch.set(g("mic_ch", self.mic_ch.get()))
        self.tmic_ch.set(g("tmic_ch", self.tmic_ch.get()))
        self.tspk_ch.set(g("tspk_ch", self.tspk_ch.get()))
        self.pspk_ch.set(g("pspk_ch", self.pspk_ch.get()))

        self.rig_mode.set(g("rig_mode", self.rig_mode.get()))
        self.tune_step.set(g("tune_step", self.tune_step.get()))

        self.vox_enabled.set(bool(g("vox_enabled", self.vox_enabled.get())))
        self.vox_threshold_dbfs.set(str(g("vox_threshold_dbfs", self.vox_threshold_dbfs.get())))
        self.vox_hang_ms.set(str(g("vox_hang_ms", self.vox_hang_ms.get())))


        self.mute_enabled.set(bool(g("mute_enabled", self.mute_enabled.get())))

        self.dnr_level.set(str(g("dnr_level", self.dnr_level.get())))
        self.manual_notch_freq.set(str(g("manual_notch_freq", self.manual_notch_freq.get())))
        self.preamp_state.set(str(g("amp_mode", g("preamp_state", self.preamp_state.get()))))
        self.pwr_level.set(str(g("pwr_level", self.pwr_level.get())))

        tables = g("s_meter_tables", None)
        if isinstance(tables, dict):
            self.s_meter_tables = tables

        bar_max = g("s_meter_bar_max", None)
        if isinstance(bar_max, dict):
            # keep defaults for missing keys
            for k in ("IPO", "AMP1", "AMP2"):
                if k in bar_max:
                    try:
                        self.s_meter_bar_max[k] = int(bar_max[k])
                    except Exception:
                        pass

        print("Konfiguration erfolgreich geladen.")

    def save_settings(self):
        cfg = {
            "cat_port": self.cat_port.get(),
            "baud_rate": self.baud_rate.get(),
            "ptt_port": self.ptt_port.get(),
            "ptt_invert": bool(self.ptt_invert.get()),
            "pc_mic": self.pc_mic.get(),
            "trx_mic": self.trx_mic.get(),
            "trx_spk": self.trx_spk.get(),
            "pc_spk": self.pc_spk.get(),
            "mic_sr": self.mic_sr.get(),
            "tmic_sr": self.tmic_sr.get(),
            "tspk_sr": self.tspk_sr.get(),
            "pspk_sr": self.pspk_sr.get(),
            "mic_ch": self.mic_ch.get(),
            "tmic_ch": self.tmic_ch.get(),
            "tspk_ch": self.tspk_ch.get(),
            "pspk_ch": self.pspk_ch.get(),
            "ptt_method": self.ptt_method_val.get(),
            "rig_mode": self.rig_mode.get(),
            "tune_step": self.tune_step.get(),
            "vox_enabled": bool(self.vox_enabled.get()),
            "vox_threshold_dbfs": self.vox_threshold_dbfs.get(),
            "vox_hang_ms": self.vox_hang_ms.get(),
            "mute_enabled": bool(self.mute_enabled.get()),
            "dnr_level": self.dnr_level.get(),
            "manual_notch_freq": self.manual_notch_freq.get(),
            "amp_mode": self.preamp_state.get(),
            "pwr_level": self.pwr_level.get(),
            "s_meter_tables": self.s_meter_tables,
            "s_meter_bar_max": self.s_meter_bar_max,
            "s_meter_bar_min": self.s_meter_bar_min,
        }
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
            print("✅ Settings gespeichert.")
        except Exception as e:
            print(f"❌ Settings speichern fehlgeschlagen: {e}")

    def reload_config(self):
        self.load_settings()
        try:
            self.ui.apply_config_to_ui()
        except Exception:
            pass
        if self.is_connected and self.ser_cat and self.ser_cat.is_open:
            self.sync_state_from_rig()


    def on_mute_toggle(self):
        """Toggle mute for RX audio to PC speakers."""
        try:
            enabled = bool(self.mute_enabled.get())
        except Exception:
            enabled = False
        try:
            if hasattr(self, "mute_status_label"):
                self.mute_status_label.configure(
                    text=f"MUTE: {'EIN' if enabled else 'AUS'}",
                    text_color="#7bd88f" if enabled else "#aaaaaa",
                )
        except Exception:
            pass
        # Persist immediately so Reload/Restart keeps it
        try:
            self.save_settings()
        except Exception:
            pass


    # ----------------------------
    # Session logging helpers
    # ----------------------------
    def log_action(self, msg: str):
        try:
            self.actions_logger.info(msg)
        except Exception:
            pass

    def log_error(self, msg: str):
        try:
            self.errors_logger.error(msg)
        except Exception:
            pass
    # ----------------------------
    # UI helpers
    # ----------------------------
    def _format_freq_label(self, hz):
        try:
            hz = int(hz)
        except Exception:
            return "---.------ MHz"
        return f"{hz / 1_000_000.0:0.6f} MHz"

    def _format_freq_for_entry(self, hz):
        try:
            hz = int(hz)
        except Exception:
            hz = 0
        return f"{hz / 1_000_000.0:0.6f}"

    def _get_tune_step_hz(self):
        try:
            return max(1, int(str(self.tune_step.get()).strip()))
        except Exception:
            return 1000

    def set_tune_step(self, value):
        try:
            self.tune_step.set(str(max(1, int(str(value).strip()))))
        except Exception:
            self.tune_step.set("1000")

    # ----------------------------
    # Rig control
    # ----------------------------
    def step_frequency(self, direction):
        if not self.is_connected or self.disconnecting:
            return False
        step = self._get_tune_step_hz()
        new_freq = max(30_000, min(470_000_000, int(self.last_freq) + (step * int(direction))))
        return self.set_frequency_hz(new_freq)

    def _parse_frequency_input(self, text):
        s = str(text).strip().replace(" ", "").replace(",", ".")
        s = s.replace("MHz", "").replace("mhz", "").replace("Hz", "").replace("hz", "")
        if not s:
            raise ValueError("Leere Eingabe")
        if "." in s:
            hz = int(round(float(s) * 1_000_000))
        else:
            digits = "".join(ch for ch in s if ch.isdigit())
            if not digits:
                raise ValueError("Keine Ziffern gefunden")
            hz = int(digits) * 1000 if len(digits) <= 6 else int(digits)
        if not (30_000 <= hz <= 470_000_000):
            raise ValueError("Frequenz außerhalb Bereich")
        return hz

    def set_frequency_from_text(self, text):
        try:
            hz = self._parse_frequency_input(text)
        except Exception as e:
            print(f"❌ Frequenz ungültig: {e}")
            return False
        return self.set_frequency_hz(hz)

    def mark_frequency_entry_dirty(self, event=None):
        self._freq_entry_dirty = True

    def submit_frequency_entry(self):
        try:
            txt = self.freq_entry_var.get()
        except Exception:
            return False

        ok = self.set_frequency_from_text(txt)
        if ok:
            self._freq_entry_dirty = False
            try:
                self.freq_entry_var.set(self._format_freq_for_entry(self.last_freq))
            except Exception:
                pass

            # Fokus wirklich aus dem Eingabefeld rausnehmen
            try:
                if hasattr(self, "freq_entry") and self.freq_entry is not None:
                    try:
                        self.freq_entry.selection_clear()
                    except Exception:
                        pass
                    try:
                        self.freq_entry.icursor("end")
                    except Exception:
                        pass

                # Fokus bewusst auf einen anderen Widget-Owner setzen
                if hasattr(self, "conn_btn") and self.conn_btn is not None:
                    self.conn_btn.focus_set()
                elif hasattr(self, "ptt_btn") and self.ptt_btn is not None:
                    self.ptt_btn.focus_set()
                else:
                    self.focus_set()

                try:
                    self.freq_entry_editing = False
                    self.freq_entry_dirty = False
                except Exception:
                    pass
            except Exception:
                pass

        return ok

    def _sync_frequency_widgets(self):
        try:
            self.freq_label.configure(text=self._format_freq_label(self.last_freq))
        except Exception:
            pass
        try:
            if hasattr(self, "freq_entry_var") and self.freq_entry_var is not None:
                # NICHT während der Benutzer tippt zurücksynchronisieren
                focus_widget = None
                try:
                    focus_widget = self.focus_get()
                except Exception:
                    pass
                if (not getattr(self, "_freq_entry_dirty", False)) and focus_widget is not getattr(self, "freq_entry", None):
                    self.freq_entry_var.set(self._format_freq_for_entry(self.last_freq))
        except Exception:
            pass

    def set_frequency_hz(self, hz):
        if not self.is_connected or self.disconnecting or not self.ser_cat:
            return False
        try:
            hz = int(hz)
        except Exception:
            return False
        ok = self.cat.set_freq(self.ser_cat, hz)
        if ok:
            self.last_freq = hz
            self._sync_frequency_widgets()
        return ok

    def set_mode(self, mode_label):
        if not self.is_connected or self.disconnecting or not self.ser_cat:
            return False
        code = self.cat.mode_label_to_code(mode_label)
        if not code:
            return False
        ok = self.cat.set_mode(self.ser_cat, code)
        if ok:
            self.rig_mode.set(mode_label)
            try:
                self.mode_label.configure(text=f"MODE: {mode_label}")
                self.ui.update_mode_buttons(mode_label)
            except Exception:
                pass
        return ok

    def cycle_preamp(self):
        order = ["IPO", "AMP1", "AMP2"]
        cur = str(self.preamp_state.get()).strip().upper()
        try:
            idx = order.index(cur)
        except ValueError:
            idx = 0
        new = order[(idx + 1) % 3]
        if self.is_connected and self.ser_cat and self.ser_cat.is_open:
            if not self.cat.set_preamp_mode(self.ser_cat, new):
                return False
        self.preamp_state.set(new)
        try:
            self.amp_btn.configure(text=f"AMP: {new}")
        except Exception:
            pass
        return True

    # DNR slider: auto apply after 2s idle
    def on_dnr_slider(self, value):
        try:
            level = int(round(float(value)))
        except Exception:
            level = 1
        level = max(1, min(15, level))
        self.dnr_level.set(str(level))
        try:
            self.dnr_value_label.configure(text=str(level))
        except Exception:
            pass
        if self._dnr_set_job is not None:
            try:
                self.after_cancel(self._dnr_set_job)
            except Exception:
                pass
        self._dnr_set_job = self.after(180, self.apply_dnr_level)

    def apply_dnr_level(self):
        self._dnr_set_job = None
        if self.is_connected and self.ser_cat and self.ser_cat.is_open:
            try:
                if not self.ui.btn_states.get("DNR"):
                    self.ui.set_tool_button_state("DNR", True)
                    self.cat.toggle_dnr(self.ser_cat, True)
                self.cat.set_dnr_level(self.ser_cat, int(self.dnr_level.get()))
            except Exception:
                pass

    # NOTCH freq (Hz) auto apply after 250ms idle
    def on_notch_slider(self, value):
        try:
            hz = int(round(float(value)))
        except Exception:
            hz = 1000
        hz = max(10, min(3200, hz))
        self.manual_notch_freq.set(str(hz))
        try:
            self.notch_value_label.configure(text=f"{hz:04d}")
        except Exception:
            pass
        if self._notch_set_job is not None:
            try:
                self.after_cancel(self._notch_set_job)
            except Exception:
                pass
        self._notch_set_job = self.after(120, self.apply_notch_freq)

    def apply_notch_freq(self):
        self._notch_set_job = None
        if self.is_connected and self.ser_cat and self.ser_cat.is_open:
            try:
                hz = int(self.manual_notch_freq.get())
            except Exception:
                hz = 1000
            try:
                # Notch bei Bedarf am TRX wirklich einschalten
                if not self.ui.btn_states.get("NOTCH"):
                    self.cat.toggle_notch(self.ser_cat, True)
                    self.ui.set_tool_button_state("NOTCH", True)
                self.cat.set_manual_notch_freq(self.ser_cat, hz)
            except Exception:
                pass

    def on_power_slider(self, value):
        try:
            p = int(round(float(value)))
        except Exception:
            p = 50
        p = max(0, min(100, p))
        self.pwr_level.set(str(p))
        try:
            self.pwr_value_label.configure(text=str(p))
        except Exception:
            pass
        if self._pwr_set_job is not None:
            try:
                self.after_cancel(self._pwr_set_job)
            except Exception:
                pass
        self._pwr_set_job = self.after(250, self.apply_power)

    def apply_power(self):
        self._pwr_set_job = None
        if self.is_connected and self.ser_cat and self.ser_cat.is_open:
            try:
                self.cat.set_rf_power(self.ser_cat, int(self.pwr_level.get()))
            except Exception:
                pass

    # ----------------------------
    # Connect / Disconnect
    # ----------------------------
    def toggle_connection(self):
        if self.is_connected:
            self.close_all()
            return

        try:
            self.disconnecting = False

            self.ser_cat = serial.Serial(self.cat_port.get(), int(self.baud_rate.get()), timeout=0.1)

            if self.ptt_method_val.get() in ("RTS", "DTR"):
                self.ser_ptt = serial.Serial(self.ptt_port.get(), 38400, timeout=0.1)
                self._set_ptt_idle_lines()

            self.cat.set_ptt_hardware(self.ser_ptt, False, self.ptt_method_val.get(), bool(self.ptt_invert.get()))
            self.ptt_active = False
            self._manual_tx = False

            # Audio streams
            self.st_rx_in = self.audio.open_stream_with_fallback(self.trx_mic.get(), "input", self.rx_input_cb, self.tmic_ch.get(), self.tmic_sr.get())
            self.st_rx_out = self.audio.open_stream_with_fallback(self.pc_spk.get(), "output", None, self.pspk_ch.get(), self.pspk_sr.get())
            self.st_tx_in = self.audio.open_stream_with_fallback(self.pc_mic.get(), "input", self.tx_input_cb, self.mic_ch.get(), self.mic_sr.get())
            self.st_tx_out = self.audio.open_stream_with_fallback(self.trx_spk.get(), "output", None, self.tspk_ch.get(), self.tspk_sr.get())

            required = [self.st_rx_in, self.st_rx_out, self.st_tx_in, self.st_tx_out]
            if any(s is None for s in required):
                raise RuntimeError("Mindestens ein Audio-Stream konnte nicht geöffnet werden.")
            for s in required:
                s.start()

            self.is_connected = True
            try:
                self.conn_btn.configure(text="DISCONNECT", fg_color="#28a745")
            except Exception:
                pass

            self.sync_state_from_rig()
            print("✅ CONNECT aktiv.")
        except Exception as e:
            print(f"Connect Fehler: {e}")
            self.close_all()

    def _set_ptt_idle_lines(self):
        if self.ser_ptt and self.ser_ptt.is_open:
            safe_level = bool(self.ptt_invert.get())
            try:
                self.ser_ptt.setRTS(safe_level)
            except Exception:
                pass
            try:
                self.ser_ptt.setDTR(safe_level)
            except Exception:
                pass

    def close_all(self):
        self.disconnecting = True
        self.is_connected = False
        self.ptt_active = False

        try:
            self.cat.set_ptt_hardware(self.ser_ptt, False, self.ptt_method_val.get(), bool(self.ptt_invert.get()))
        except Exception:
            pass

        # stop streams
        for s in [self.st_tx_in, self.st_tx_out, self.st_rx_in, self.st_rx_out]:
            if s is None:
                continue
            try:
                s.stop()
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass

        self.st_tx_in = self.st_tx_out = self.st_rx_in = self.st_rx_out = None

        if self.ser_ptt:
            try:
                self.ser_ptt.close()
            except Exception:
                pass
            self.ser_ptt = None

        if self.ser_cat:
            try:
                self.ser_cat.close()
            except Exception:
                pass
            self.ser_cat = None

        self._refresh_idle_ui()
        self.disconnecting = False
        print("✅ DISCONNECT fertig.")

    # ----------------------------
    # Sync from rig
    # ----------------------------
    def sync_state_from_rig(self):
        if not (self.ser_cat and self.ser_cat.is_open):
            return

        try:
            freq = self.cat.get_freq(self.ser_cat)
            if freq:
                self.last_freq = int(freq)
                self._sync_frequency_widgets()
        except Exception:
            pass

        try:
            mode = self.cat.get_mode_label(self.ser_cat)
            if mode:
                self.rig_mode.set(mode)
                self.mode_label.configure(text=f"MODE: {mode}")
                self.ui.update_mode_buttons(mode)
        except Exception:
            pass

        try:
            p = self.cat.get_preamp_mode_label(self.ser_cat)
            if p:
                self.preamp_state.set(p)
                self.amp_btn.configure(text=f"AMP: {p}")
        except Exception:
            pass

        self.sync_tool_states_from_rig()
        self.sync_levels_from_rig()

    def sync_tool_states_from_rig(self):
        if not (self.ser_cat and self.ser_cat.is_open):
            return
        mapping = {
            "ATT": self.cat.get_att_state,
            "NB": self.cat.get_nb_state,
            "DNR": self.cat.get_dnr_state,
            "DNF": self.cat.get_auto_notch_state,
            "NOTCH": self.cat.get_manual_notch_state,
        }
        for name, fn in mapping.items():
            try:
                st = fn(self.ser_cat)
            except Exception:
                st = None
            if st is None:
                continue
            self.ui.set_tool_button_state(name, bool(st))

    def sync_levels_from_rig(self):
        if not (self.ser_cat and self.ser_cat.is_open):
            return
        try:
            d = self.cat.get_dnr_level(self.ser_cat)
            if d is not None:
                self.dnr_level.set(str(d))
                self.dnr_slider.set(int(d))
                self.dnr_value_label.configure(text=str(d))
        except Exception:
            pass
        try:
            notch_on = self.ui.btn_states.get("NOTCH", False)
            n = self.cat.get_manual_notch_freq(self.ser_cat) if notch_on else None
            if n is not None:
                self.manual_notch_freq.set(str(n))
                # nicht während der Benutzer aktiv schiebt hart zurücksetzen
                if self._notch_set_job is None:
                    self.notch_slider.set(int(n))
                self.notch_value_label.configure(text=f"{int(n):04d}")
        except Exception:
            pass
        try:
            p = self.cat.get_rf_power(self.ser_cat)
            if p is not None:
                self.pwr_level.set(str(p))
                self.pwr_slider.set(int(p))
                self.pwr_value_label.configure(text=str(p))
        except Exception:
            pass

    # ----------------------------
    # Audio callbacks
    # ----------------------------
    def _dbfs(self, v):
        return 20.0 * np.log10(max(float(v), 1e-7))

    def tx_input_cb(self, indata, frames, time_info, status):
        if self.disconnecting:
            return
        try:
            mono = indata[:, [0]] if indata.shape[1] > 1 else indata
            rms = float(np.sqrt(np.mean(np.square(mono), dtype=np.float64)))
            peak = float(np.max(np.abs(mono)))
            self.tx_rms_db = self._dbfs(rms)
            self.tx_peak_db = self._dbfs(peak)
            self.tx_target_db = max(self.tx_rms_db, self.tx_peak_db - 3.0)
            self.tx_clipped = peak >= 0.98

            if self.ptt_active and self.st_tx_out is not None:
                out = np.column_stack((mono, mono)) if self.st_tx_out.channels == 2 else mono
                try:
                    self.st_tx_out.write(out)
                except Exception:
                    pass

            if self.audio.is_recording:
                try:
                    self.audio.add_stream_data(indata.copy())
                except Exception:
                    pass
        except Exception:
            pass

    def rx_input_cb(self, indata, frames, time_info, status):
        if self.disconnecting:
            return
        try:
            if (not self.ptt_active) and self.st_rx_out is not None:
                # MUTE: suppress RX audio to PC speakers
                try:
                    if bool(self.mute_enabled.get()):
                        return
                except Exception:
                    pass
                mono = indata[:, [0]] if indata.shape[1] > 1 else indata
                out = np.column_stack((mono, mono)) if self.st_rx_out.channels == 2 else mono
                try:
                    self.st_rx_out.write(out)
                except Exception:
                    pass
        except Exception:
            pass

    # ----------------------------
    # TX / VOX
    # ----------------------------
    def start_tx(self, e=None, manual=True):
        if not self.is_connected or self.disconnecting or self.ptt_active:
            return
        if manual:
            self._vox_force_rx_until = time.time() + 0.25

        self.ptt_active = True
        self._manual_tx = bool(manual)
        try:
            self.cat.set_ptt_hardware(self.ser_ptt, True, self.ptt_method_val.get(), bool(self.ptt_invert.get()))
        except Exception:
            pass
        try:
            self.ptt_btn.configure(fg_color="#d32f2f", text="TX (SPACE)")
        except Exception:
            pass

    def stop_tx(self, e=None):
        if not self.is_connected or self.disconnecting or not self.ptt_active:
            return
        self.ptt_active = False
        try:
            self.cat.set_ptt_hardware(self.ser_ptt, False, self.ptt_method_val.get(), bool(self.ptt_invert.get()))
        except Exception:
            pass
        try:
            self.ptt_btn.configure(fg_color="gray", text="RX (SPACE)")
        except Exception:
            pass
        self._manual_tx = False

    def _vox_tick(self):
        if not bool(self.vox_enabled.get()):
            return
        if self._manual_tx:
            return
        now = time.time()
        if now < self._vox_force_rx_until:
            return

        try:
            thr = float(self.vox_threshold_dbfs.get())
        except Exception:
            thr = -25.0
        try:
            hang = max(50, int(float(self.vox_hang_ms.get())))
        except Exception:
            hang = 700

        above = self.tx_peak_db >= thr
        if above:
            self._vox_last_above = now
            if not self.ptt_active:
                self.start_tx(manual=False)
        else:
            if self.ptt_active and (now - self._vox_last_above) * 1000.0 > hang:
                self.stop_tx()

    # ----------------------------
    # UI update loop
    # ----------------------------
    def _raw_to_s_text(self, raw):
        raw = max(0, min(255, int(round(float(raw)))))
        state = str(self.preamp_state.get()).strip().upper()
        table = (self.s_meter_tables or {}).get(state) or (self.s_meter_tables or {}).get("IPO") or []
        if not table:
            return "S0" if raw < 15 else "S9"
        try:
            table = sorted(table, key=lambda x: int(x.get("max_raw", 0)))
        except Exception:
            pass
        for row in table:
            try:
                if raw <= int(row.get("max_raw", 0)):
                    return str(row.get("label", "S0"))
            except Exception:
                continue
        return str(table[-1].get("label", "S9"))

    def _meter_fraction_from_raw(self, raw):
        """
        Map CAT-Rohwert auf Balkenposition anhand der in der Config hinterlegten
        S-Meter-Tabelle pro IPO/AMP-Profil. Dadurch laufen Text, Skala und Balken
        auf derselben Kennlinie.
        """
        raw = max(0.0, min(255.0, float(raw)))

        # UI-Skala: S0..S9,+10,+20,+40,+60 => 14 Positionen, letzter Index = 13
        max_scale_index = 13.0

        try:
            state = str(self.preamp_state.get()).strip().upper()
        except Exception:
            state = "IPO"

        table = (self.s_meter_tables or {}).get(state) or (self.s_meter_tables or {}).get("IPO") or []

        # Config-basierte Kennlinie bevorzugen
        if table:
            try:
                table = sorted(
                    [row for row in table if isinstance(row, dict)],
                    key=lambda x: int(x.get("max_raw", 0))
                )
            except Exception:
                table = [row for row in table if isinstance(row, dict)]

            prev_raw = 0.0
            prev_idx = 0.0  # S0

            for row in table:
                try:
                    row_raw = float(int(row.get("max_raw", 0)))
                except Exception:
                    continue

                label = str(row.get("label", "S0"))
                row_idx = self._s_label_to_scale_index(label)
                if row_idx is None:
                    row_idx = prev_idx
                else:
                    row_idx = float(row_idx)

                if raw <= row_raw:
                    # Zwischen zwei bekannten Punkten weich interpolieren
                    if row_raw <= prev_raw:
                        return max(0.0, min(row_idx / max_scale_index, 1.0))
                    frac = (raw - prev_raw) / (row_raw - prev_raw)
                    pos = prev_idx + frac * (row_idx - prev_idx)
                    return max(0.0, min(pos / max_scale_index, 1.0))

                prev_raw = row_raw
                prev_idx = row_idx

            # Oberhalb des letzten Tabellenpunkts: am letzten konfigurierten Marker stehen bleiben
            return max(0.0, min(prev_idx / max_scale_index, 1.0))

        # Fallback, falls noch keine Config-Tabelle vorhanden ist
        if raw <= 150.0:
            s_val = 1.0 + (raw - 30.0) / 15.0
            s_val = max(0.0, min(9.0, s_val))
            return max(0.0, min(s_val / 9.0, 1.0))
        return 1.0


    def _s_label_to_scale_index(self, label):
        m = {"S0": 0, "S1": 1, "S2": 2, "S3": 3, "S4": 4, "S5": 5, "S6": 6, "S7": 7, "S8": 8, "S9": 9, "+10": 10, "+20": 11, "+40": 12, "+60": 13}
        lab = str(label).replace("S9+", "+").replace("dB", "").strip().upper()
        return m.get(lab)

    def _update_ui_from_state(self):
        # S-meter smoothing (zackiger)
        raw = float(self.cat_s_raw)
        alpha = 0.85
        self.cat_s_smooth = ((1.0 - alpha) * self.cat_s_smooth) + (alpha * raw)
        bar_max = 255.0
        try:
            state = str(self.preamp_state.get()).strip().upper()
            # prefer explicit config override; otherwise derive from last table entry
            bar_max = float((self.s_meter_bar_max or {}).get(state, 255) or 255)
            if bar_max <= 0:
                bar_max = 255.0
        except Exception:
            bar_max = 255.0
        try:
            if (self.s_meter_bar_max or {}).get(state, 255) in (None, 0, 255):
                table = (self.s_meter_tables or {}).get(state) or []
                if table:
                    mm = max(int(r.get("max_raw", 0)) for r in table if isinstance(r, dict))
                    if mm > 0:
                        bar_max = float(mm)
        except Exception:
            pass
        bar_min = 0.0
        try:
            bar_min = float((self.s_meter_bar_min or {}).get(state, 0) or 0)
        except Exception:
            bar_min = 0.0
        if bar_max <= bar_min:
            bar_min = 0.0
            bar_max = max(bar_max, 255.0)
        meter_norm = self._meter_fraction_from_raw(self.cat_s_smooth)
        s_text = self._raw_to_s_text(self.cat_s_smooth)

        try:
            self.rx_meter.set(meter_norm)
            self.s_meter_label.configure(text=f"S-METER CAT: {int(self.cat_s_smooth):03d} ({s_text} | {self.preamp_state.get()})")
            self.ui.update_s_meter_scale(self._s_label_to_scale_index(s_text))
        except Exception:
            pass

        # MIC meter
        target = float(self.tx_target_db)
        attack = 0.55
        release = 0.12
        coeff = attack if target > self.tx_meter_db else release
        self.tx_meter_db = self.tx_meter_db + ((target - self.tx_meter_db) * coeff)

        now = time.time()
        if self.tx_peak_db >= self.tx_peak_hold_db or (now - self.tx_peak_hold_ts) > 1.0:
            self.tx_peak_hold_db = self.tx_peak_db
            self.tx_peak_hold_ts = now
        else:
            self.tx_peak_hold_db = max(self.tx_peak_hold_db - 0.8, self.tx_peak_db)

        db_for_bar = max(-60.0, min(0.0, self.tx_meter_db))
        progress = (db_for_bar + 60.0) / 60.0

        try:
            self.tx_meter.set(progress)
            self.tx_meter_label.configure(text=f"MIC: {self.tx_rms_db:.1f} dBFS | Peak {self.tx_peak_hold_db:.1f} dBFS")
        except Exception:
            pass

        # VOX status line
        try:
            thr = float(self.vox_threshold_dbfs.get())
        except Exception:
            thr = -25.0
        try:
            hold = int(float(self.vox_hang_ms.get()))
        except Exception:
            hold = 700

        try:
            if not bool(self.vox_enabled.get()):
                self.vox_status_label.configure(text=f"VOX: AUS | THR {thr:.1f} dBFS | HOLD {hold} ms", text_color="#aaaaaa")
            else:
                self.vox_status_label.configure(text=f"VOX: EIN | THR {thr:.1f} dBFS | HOLD {hold} ms", text_color="#7bd88f")
        except Exception:
            pass

    def update_loop(self):
        # periodic polling
        if self.is_connected and self.ser_cat and self.ser_cat.is_open and not self.disconnecting:
            try:
                raw = self.cat.get_s_meter_raw(self.ser_cat)
                if raw is not None:
                    self.cat_s_raw = raw
            except Exception:
                pass
            self._mode_poll_counter += 1
            if self._mode_poll_counter >= 8:
                self._mode_poll_counter = 0
                try:
                    self.sync_state_from_rig()
                except Exception:
                    pass

        self._update_ui_from_state()

        try:
            self._vox_tick()
        except Exception:
            pass

        self.after(120, self.update_loop)

    # ----------------------------
    # Misc
    # ----------------------------
    def _refresh_idle_ui(self):
        try:
            self.rx_meter.set(0)
            self.tx_meter.set(0)
            self.tx_meter_label.configure(text="MIC: --- dBFS")
            self.s_meter_label.configure(text="S-METER CAT: ---")
            self.ui.update_s_meter_scale(None)
            self.ptt_btn.configure(fg_color="gray", text="RX (SPACE)")
            self.conn_btn.configure(text="CONNECT", fg_color="#1f538d")
            self.amp_btn.configure(text=f"AMP: {self.preamp_state.get()}")
        except Exception:
            pass

    def on_closing(self):
        try:
            self.close_all()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    app = DO4NRWTRXPro()
    app.mainloop()