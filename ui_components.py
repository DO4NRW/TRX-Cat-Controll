import customtkinter as ctk
import sounddevice as sd


class UIComponents:
    def __init__(self, parent):
        self.p = parent
        self.btn_states = {tool: False for tool in ["ATT", "NB", "DNR", "DNF", "NOTCH"]}
        self.tool_buttons = {}
        self.mode_buttons = {}
        self.s_meter_scale_labels = []
        self.s_meter_scale_order = ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "+10", "+20", "+40", "+60"]
        self.ram_btn = None

    def _log(self, msg: str):
        # Safe action logger (main.py provides log_action)
        try:
            if hasattr(self.p, "log_action"):
                self.p.log_action(msg)
        except Exception:
            pass

    def _wrap(self, msg: str, fn):
        # Wrap a command callback to log the UI action without changing behavior
        return lambda *a, **k: (self._log(msg), fn(*a, **k))

    def finalize_and_center(self, win):
        win.update_idletasks()
        s_w = win.winfo_screenwidth()
        s_h = win.winfo_screenheight()
        req_w = win.winfo_reqwidth()
        req_h = win.winfo_reqheight()
        pos_x = max(0, (s_w // 2) - (req_w // 2))
        pos_y = max(30, (s_h // 2) - (req_h // 2) - 20)
        win.geometry(f"+{pos_x}+{pos_y}")
        win.resizable(True, True)
        win.lift()
        win.focus_force()

    def build_main_ui(self):
        content = ctk.CTkFrame(self.p, fg_color="transparent")
        content.pack(padx=10, pady=10, fill="both", expand=True)

        # ===== Top bar =====
        top = ctk.CTkFrame(content)
        top.pack(fill="x", pady=(0, 10))

        self.p.conn_btn = ctk.CTkButton(top, text="CONNECT", width=140, command=self._wrap("UI: CONNECT/TOGGLE pressed", self.p.toggle_connection))
        self.p.conn_btn.pack(side="left", padx=(6, 6), pady=6)

        self.p.reload_btn = ctk.CTkButton(
            top,
            text="RELOAD CFG",
            width=140,
            fg_color="#4a4a4a",
            hover_color="#5a5a5a",
            command=self._wrap("UI: RELOAD CFG pressed", getattr(self.p, "reload_config", self.p.load_settings)),
        )
        self.p.reload_btn.pack(side="left", padx=(6, 18), pady=6)

        ctk.CTkButton(top, text="AUDIO MATRIX", width=160, command=self._wrap("UI: Open Audio Matrix", self.open_audio_window)).pack(side="left", padx=6, pady=6)
        ctk.CTkButton(top, text="RADIO SETUP", width=160, command=self._wrap("UI: Open Radio Setup", self.open_radio_window)).pack(side="left", padx=6, pady=6)

        # ===== Frequency =====
        f_g = ctk.CTkFrame(content)
        f_g.pack(pady=(5, 14), fill="x")
        self.p.freq_label = ctk.CTkLabel(f_g, text="---.------ MHz", font=("Roboto", 32, "bold"), text_color="#3b8ed0")
        self.p.freq_label.pack(padx=40, pady=(10, 8))

        # ===== Tuning =====
        tune_fr = ctk.CTkFrame(content)
        tune_fr.pack(fill="x", pady=(0, 8), padx=10)

        ctk.CTkButton(tune_fr, text="◀ STEP", width=110, command=self._wrap("UI: STEP ◀", lambda: self.p.step_frequency(-1))).pack(side="left", padx=6, pady=8)
        ctk.CTkLabel(tune_fr, text="STEP (Hz):", font=("", 12, "bold")).pack(side="left", padx=(12, 6))

        self.p.step_combo = ctk.CTkComboBox(
            tune_fr,
            values=["10", "50", "100", "500", "1000", "2500", "5000", "6250", "8333", "9000", "10000", "12500", "25000", "100000", "1000000"],
            variable=self.p.tune_step,
            width=110,
            command=self.p.set_tune_step,
        )
        self.p.step_combo.pack(side="left", padx=6)

        ctk.CTkButton(tune_fr, text="STEP ▶", width=110, command=self._wrap("UI: STEP ▶", lambda: self.p.step_frequency(1))).pack(side="left", padx=6, pady=8)

        self.p.freq_entry_var = ctk.StringVar(value=self.p._format_freq_for_entry(self.p.last_freq))
        self.p.freq_entry = ctk.CTkEntry(tune_fr, textvariable=self.p.freq_entry_var, width=140, justify="center")
        self.p.freq_entry.pack(side="right", padx=(6, 6), pady=8)
        self.p.freq_entry.bind("<KeyRelease>", self.p.mark_frequency_entry_dirty)
        self.p.freq_entry.bind("<Return>", lambda e: (self._log(f"UI: ENTER in FREQ | entry={self.p.freq_entry_var.get()}"), self.p.submit_frequency_entry()))
        ctk.CTkButton(tune_fr, text="SET", width=70, fg_color="#6a3dad", command=self._wrap(f"UI: SET FREQ pressed | entry={self.p.freq_entry_var.get()}", self.p.submit_frequency_entry)).pack(side="right", padx=(6, 2), pady=8)

        # ===== Mode =====
        mode_fr = ctk.CTkFrame(content)
        mode_fr.pack(fill="x", pady=(0, 12), padx=10)

        ctk.CTkLabel(mode_fr, text="MODE:", font=("", 12, "bold")).pack(side="left", padx=(8, 8))
        self.p.mode_label = ctk.CTkLabel(mode_fr, text=f"MODE: {self.p.rig_mode.get()}", font=("Roboto", 16, "bold"), text_color="#3b8ed0")
        self.p.mode_label.pack(side="right", padx=(8, 8))

        for label in ["LSB", "USB", "FM", "AM", "RTTY"]:
            btn = ctk.CTkButton(
                mode_fr,
                text=label,
                width=82,
                height=34,
                fg_color="#3d3d3d",
                hover_color="#4a4a4a",
                command=self._wrap(f"UI: MODE set {label}", lambda m=label: self.p.set_mode(m)),
            )
            btn.pack(side="left", padx=4, pady=6, expand=True, fill="x")
            self.mode_buttons[label] = btn
        self.update_mode_buttons(self.p.rig_mode.get())

        # ===== TRX tools =====
        tools_fr = ctk.CTkFrame(content)
        tools_fr.pack(fill="x", pady=(6, 6), padx=10)

        for tool in ["ATT", "NB", "DNR", "DNF", "NOTCH"]:
            btn = ctk.CTkButton(
                tools_fr,
                text=tool,
                width=80,
                height=35,
                fg_color="#3d3d3d",
                hover_color="#4a4a4a",
                command=lambda t=tool: self.toggle_tool(t),
            )
            btn.pack(side="left", padx=5, expand=True, fill="x")
            self.tool_buttons[tool] = btn

        self.p.amp_btn = ctk.CTkButton(
            tools_fr,
            text=f"AMP: {self.p.preamp_state.get()}",
            width=110,
            height=35,
            fg_color="#3d3d3d",
            hover_color="#4a4a4a",
            command=self._wrap("UI: AMP cycle pressed", getattr(self.p, "cycle_preamp", lambda: None)),
        )
        self.p.amp_btn.pack(side="left", padx=5)

        # ===== Sliders =====
        sliders = ctk.CTkFrame(content)
        sliders.pack(fill="x", pady=(2, 8), padx=10)

        ctk.CTkLabel(sliders, text="DNR:", font=("", 12, "bold")).pack(side="left", padx=(6, 4))
        self.p.dnr_slider = ctk.CTkSlider(
            sliders,
            from_=1,
            to=15,
            number_of_steps=14,
            command=getattr(self.p, "on_dnr_slider", lambda v: None),
            width=180,
        )
        try:
            self.p.dnr_slider.set(int(self.p.dnr_level.get()))
        except Exception:
            self.p.dnr_slider.set(8)
        self.p.dnr_slider.pack(side="left", padx=(0, 6))
        self.p.dnr_value_label = ctk.CTkLabel(sliders, text=str(self.p.dnr_level.get()), width=26)
        self.p.dnr_value_label.pack(side="left", padx=(0, 14))

        ctk.CTkLabel(sliders, text="NOTCH:", font=("", 12, "bold")).pack(side="left", padx=(0, 4))
        self.p.notch_slider = ctk.CTkSlider(
            sliders,
            from_=10,
            to=3200,
            number_of_steps=319,
            width=180,
            command=self._on_notch_slider,
        )
        try:
            self.p.notch_slider.set(int(float(self.p.manual_notch_freq.get())))
        except Exception:
            self.p.notch_slider.set(100)
        self.p.notch_slider.pack(side="left", padx=(0, 6))
        self.p.notch_value_label = ctk.CTkLabel(sliders, text=f"{int(float(self.p.manual_notch_freq.get())):04d}", width=40)
        self.p.notch_value_label.pack(side="left", padx=(0, 14))

        ctk.CTkLabel(sliders, text="PWR:", font=("", 12, "bold")).pack(side="left", padx=(0, 4))
        self.p.pwr_slider = ctk.CTkSlider(
            sliders,
            from_=5,
            to=100,
            number_of_steps=95,
            width=180,
            command=self._on_pwr_slider,
        )
        try:
            self.p.pwr_slider.set(int(self.p.pwr_level.get()))
        except Exception:
            self.p.pwr_slider.set(50)
        self.p.pwr_slider.pack(side="left", padx=(0, 6))
        self.p.pwr_value_label = ctk.CTkLabel(sliders, text=str(self.p.pwr_level.get()), width=40)
        self.p.pwr_value_label.pack(side="left", padx=(0, 6))

        # ===== S-meter =====
        self.p.s_meter_label = ctk.CTkLabel(content, text="S-METER CAT: ---", font=("", 16, "bold"))
        self.p.s_meter_label.pack(pady=(6, 2))

        scale_fr = ctk.CTkFrame(content, fg_color="transparent")
        scale_fr.pack(fill="x", padx=20, pady=(0, 2))
        for i, label in enumerate(self.s_meter_scale_order):
            scale_fr.grid_columnconfigure(i, weight=1)
            lbl = ctk.CTkLabel(scale_fr, text=label, font=("Roboto", 11, "bold"), text_color="#8f99a8")
            lbl.grid(row=0, column=i, padx=1, sticky="n")
            self.s_meter_scale_labels.append(lbl)
        self.update_s_meter_scale(None)

        self.p.rx_meter = ctk.CTkProgressBar(content, width=600, height=22)
        self.p.rx_meter.pack(pady=(0, 10), fill="x", padx=20)
        self.p.rx_meter.set(0)

        self.p.tx_meter = ctk.CTkProgressBar(content, width=600, height=22, progress_color="#24c13a")
        self.p.tx_meter.pack(pady=(8, 4), fill="x", padx=20)
        self.p.tx_meter.set(0)

        self.p.tx_meter_label = ctk.CTkLabel(content, text="MIC: --- dBFS", font=("", 15, "bold"))
        self.p.tx_meter_label.pack(pady=(0, 2))

        # ===== VOX =====
        vox_fr = ctk.CTkFrame(content)
        vox_fr.pack(fill="x", padx=20, pady=(6, 4))

        self.p.vox_switch = ctk.CTkSwitch(vox_fr, text="VOX EIN/AUS", variable=self.p.vox_enabled, command=self._wrap("UI: VOX toggle", self._on_vox_toggle))
        self.p.vox_switch.pack(side="left", padx=(10, 12), pady=6)

        self.p.mute_switch = ctk.CTkSwitch(vox_fr, text="MUTE", variable=getattr(self.p, "mute_enabled", ctk.BooleanVar(value=False)), command=self._wrap("UI: MUTE toggle", getattr(self.p, "on_mute_toggle", lambda: None)))
        self.p.mute_switch.pack(side="left", padx=(0, 12), pady=6)

        ctk.CTkLabel(vox_fr, text="Schwelle dBFS:", font=("", 12, "bold")).pack(side="left", padx=(0, 6))
        self.p.vox_thr_entry = ctk.CTkEntry(vox_fr, width=70, textvariable=self.p.vox_threshold_dbfs)
        self.p.vox_thr_entry.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(vox_fr, text="Hold ms:", font=("", 12, "bold")).pack(side="left", padx=(0, 6))
        self.p.vox_hold_entry = ctk.CTkEntry(vox_fr, width=70, textvariable=self.p.vox_hang_ms)
        self.p.vox_hold_entry.pack(side="left", padx=(0, 12))

        self.p.vox_save_btn = ctk.CTkButton(vox_fr, text="VOX SPEICHERN", width=140, command=self._wrap("UI: VOX SAVE pressed", self._save_vox))
        self.p.vox_save_btn.pack(side="right", padx=10)

        self.p.vox_status_label = ctk.CTkLabel(content, text="VOX: AUS | THR --- dBFS | HOLD --- ms", font=("", 12, "bold"), text_color="#aaaaaa")
        self.p.vox_status_label.pack(pady=(0, 4))

        self.p.mute_status_label = ctk.CTkLabel(content, text="MUTE: AUS", font=("", 12, "bold"), text_color="#aaaaaa")
        self.p.mute_status_label.pack(pady=(0, 10))

        # ===== PTT =====
        self.p.ptt_btn = ctk.CTkButton(content, text="RX (SPACE)", height=60, font=("", 24, "bold"), fg_color="gray")
        self.p.ptt_btn.pack(pady=18, fill="both", expand=True, padx=60)
        self.p.ptt_btn.bind("<Button-1>", lambda e: (self._log("UI: PTT press (mouse)"), self.p.start_tx()))
        self.p.ptt_btn.bind("<ButtonRelease-1>", lambda e: (self._log("UI: PTT release (mouse)"), self.p.stop_tx()))

    def apply_config_to_ui(self):
        try:
            self.p.dnr_slider.set(int(self.p.dnr_level.get()))
            self.p.dnr_value_label.configure(text=str(self.p.dnr_level.get()))
        except Exception:
            pass
        try:
            self.p.amp_btn.configure(text=f"AMP: {self.p.preamp_state.get()}")
        except Exception:
            pass
        try:
            self.p.notch_slider.set(int(float(self.p.manual_notch_freq.get())))
            self.p.notch_value_label.configure(text=f"{int(float(self.p.manual_notch_freq.get())):04d}")
        except Exception:
            pass
        try:
            self.p.pwr_slider.set(int(self.p.pwr_level.get()))
            self.p.pwr_value_label.configure(text=str(self.p.pwr_level.get()))
        except Exception:
            pass
        try:
            self.update_mode_buttons(self.p.rig_mode.get())
        except Exception:
            pass

    def update_mode_buttons(self, current_mode):
        current = str(current_mode).strip().upper()
        if current in {"RTTY-LSB", "RTTY-USB"}:
            current = "RTTY"
        for label, btn in self.mode_buttons.items():
            active = label == current
            try:
                btn.configure(
                    fg_color="#1f538d" if active else "#3d3d3d",
                    hover_color="#2a6fb3" if active else "#4a4a4a",
                    border_width=1,
                    border_color="#89c2ff" if active else "#4a4a4a",
                )
            except Exception:
                pass

    def update_s_meter_scale(self, active_index):
        for idx, lbl in enumerate(self.s_meter_scale_labels):
            active = active_index is not None and idx == active_index
            try:
                lbl.configure(text_color="#d7ecff" if active else "#8f99a8")
            except Exception:
                pass

    def update_s_meter_scale_by_label(self, label):
        label = str(label).strip().upper()
        active_index = None
        for idx, item in enumerate(self.s_meter_scale_order):
            if item == label:
                active_index = idx
                break
        self.update_s_meter_scale(active_index)

    def set_tool_button_state(self, tool, state):
        tool = str(tool).upper()
        self.btn_states[tool] = bool(state)
        btn = self.tool_buttons.get(tool)
        if btn is not None:
            try:
                btn.configure(fg_color="#1f538d" if state else "#3d3d3d")
            except Exception:
                pass

    def toggle_tool(self, tool):
        if not self.p.is_connected or not self.p.ser_cat:
            return
        tool = str(tool).upper()
        new_state = not self.btn_states.get(tool, False)
        try:
            self._log(f"UI: TOOL toggle {tool} -> {new_state}")
        except Exception:
            pass
        self.set_tool_button_state(tool, new_state)
        try:
            if tool == "ATT":
                self.p.cat.toggle_att(self.p.ser_cat, new_state)
            elif tool == "NB":
                self.p.cat.toggle_nb(self.p.ser_cat, new_state)
            elif tool == "DNR":
                self.p.cat.toggle_dnr(self.p.ser_cat, new_state)
            elif tool == "DNF":
                self.p.cat.toggle_dnf(self.p.ser_cat, new_state)
            elif tool == "NOTCH":
                self.p.cat.toggle_notch(self.p.ser_cat, new_state)
        except Exception as exc:
            print(f"Tool {tool} Fehler: {exc}")

    def open_frequency_window(self):
        win = ctk.CTkToplevel(self.p)
        win.title("Frequenz direkt setzen")
        win.transient(self.p)

        fr = ctk.CTkFrame(win)
        fr.pack(padx=20, pady=20, fill="both", expand=True)

        ctk.CTkLabel(fr, text="Frequenz eingeben", font=("Roboto", 18, "bold")).pack(pady=(5, 10))
        ctk.CTkLabel(fr, text="Beispiele: 145.500000  |  145500  |  7100", text_color="gray70").pack(pady=(0, 10))

        entry_var = ctk.StringVar(value=self.p._format_freq_for_entry(self.p.last_freq))
        entry = ctk.CTkEntry(fr, textvariable=entry_var, width=240, font=("Roboto", 22, "bold"), justify="center")
        entry.pack(pady=8)
        entry.focus_set()
        entry.select_range(0, "end")

        ctk.CTkLabel(fr, text=f"Aktueller Step: {self.p.tune_step.get()} Hz", text_color="#3b8ed0").pack(pady=(4, 10))

        def submit():
            if self.p.set_frequency_from_text(entry_var.get()):
                try:
                    entry.selection_clear()
                except Exception:
                    pass
                try:
                    win.focus_set()
                except Exception:
                    pass
                try:
                    self.p.focus_set()
                except Exception:
                    pass
                win.after(10, win.destroy)

        btn_row = ctk.CTkFrame(fr, fg_color="transparent")
        btn_row.pack(fill="x", pady=(8, 4))
        ctk.CTkButton(btn_row, text="ABBRECHEN", fg_color="#555555", command=win.destroy).pack(side="left", padx=6, expand=True, fill="x")
        ctk.CTkButton(btn_row, text="SETZEN (ENTER)", fg_color="#28a745", command=submit).pack(side="left", padx=6, expand=True, fill="x")

        entry.bind("<Return>", lambda e: submit())
        self.finalize_and_center(win)

    def open_audio_window(self):
        win = ctk.CTkToplevel(self.p)
        win.title("Audio Matrix")
        win.transient(self.p)

        cp = ctk.CTkFrame(win, fg_color="transparent")
        cp.pack(padx=25, pady=25, fill="both", expand=True)

        try:
            devs = [f"[{i}] {d['name']}" for i, d in enumerate(sd.query_devices()) if d.get('hostapi', 0) == 0]
        except Exception:
            devs = []
        if not devs:
            devs = [""]

        def add_row(parent, title, var_dev, var_sr, var_ch):
            fr = ctk.CTkFrame(parent)
            fr.pack(fill="x", pady=5)

            ctk.CTkLabel(
                fr,
                text=title,
                font=("", 11, "bold"),
                text_color="#3b8ed0"
            ).pack(anchor="w", padx=15, pady=(10, 2))

            row = ctk.CTkFrame(fr, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=(2, 10))

            ctk.CTkComboBox(row, values=devs, variable=var_dev, width=475).pack(side="left", padx=(0, 10))
            ctk.CTkComboBox(row, values=["44100", "48000"], variable=var_sr, width=110).pack(side="left", padx=(0, 10))
            ctk.CTkComboBox(row, values=["1", "2"], variable=var_ch, width=80).pack(side="left")

        add_row(cp, "1. PC MIKROFON", self.p.pc_mic, self.p.mic_sr, self.p.mic_ch)
        add_row(cp, "2. TRX MIKROFON", self.p.trx_mic, self.p.tmic_sr, self.p.tmic_ch)
        add_row(cp, "3. TRX LAUTSPRECHER", self.p.trx_spk, self.p.tspk_sr, self.p.tspk_ch)
        add_row(cp, "4. PC LAUTSPRECHER", self.p.pc_spk, self.p.pspk_sr, self.p.pspk_ch)

        def wave_test():
            import os
            file_path = os.path.join(self.p.base_dir, "defaults", "VOXScrm_Wilhelm_scream.wav")
            if not os.path.exists(file_path):
                print(f"Fehler: Datei nicht gefunden unter {file_path}")
                return
            try:
                print(f"Starte Test auf Gerät: {self.p.pc_spk.get()}")
                self.p.audio.play_test_wave(file_path, self.p.pc_spk.get())
            except Exception as e:
                print(f"WAVE TEST Fehler: {e}")

        btn_fr = ctk.CTkFrame(cp)
        btn_fr.pack(fill="x", pady=(12, 8))

        ctk.CTkButton(
            btn_fr,
            text="🔊 WAVE TEST",
            fg_color="#555555",
            hover_color="#6a6a6a",
            command=self._wrap("UI: WAVE TEST pressed", wave_test)
        ).pack(side="left", padx=10, pady=12, expand=True, fill="x")

        self.ram_btn = ctk.CTkButton(
            btn_fr,
            text="⏺ START REC",
            fg_color="#880000",
            hover_color="#b00000",
            command=self._wrap("UI: REC toggle pressed", self.toggle_record)
        )
        self.ram_btn.pack(side="left", padx=10, pady=12, expand=True, fill="x")

        ctk.CTkButton(
            cp,
            text="AUDIO-MATRIX SPEICHERN",
            fg_color="#28a745",
            hover_color="#24963f",
            height=46,
            command=self._wrap("UI: AUDIO-MATRIX SAVE pressed", self.p.save_settings)
        ).pack(pady=(8, 0), fill="x")

        self.finalize_and_center(win)

    def toggle_record(self):
        if not self.p.audio.is_recording:
            self.p.audio.start_ram_record()
            if self.ram_btn:
                self.ram_btn.configure(text="⏹ STOP & PLAY", fg_color="#5cb85c")
        else:
            self.p.audio.stop_and_play_ram()
            if self.ram_btn:
                self.ram_btn.configure(text="⏺ START REC", fg_color="#880000")

    def open_radio_window(self):
        win = ctk.CTkToplevel(self.p)
        win.title("Settings")
        win.transient(self.p)

        main_pad = ctk.CTkFrame(win, fg_color="transparent")
        main_pad.pack(padx=15, pady=15, fill="both", expand=True)

        # Backward-compatible: some main versions may not define these vars/configs
        if not hasattr(self.p, "data_bits"):
            self.p.data_bits = ctk.StringVar(value="Default")
        if not hasattr(self.p, "stop_bits"):
            self.p.stop_bits = ctk.StringVar(value="Default")
        if not hasattr(self.p, "handshake"):
            self.p.handshake = ctk.StringVar(value="Default")
        if not hasattr(self.p, "split_op"):
            self.p.split_op = ctk.StringVar(value="None")

        radio_cfg = getattr(self.p, "radio_cfg", {
            "radiobutton_width": 20,
            "radiobutton_height": 20,
            "border_width_checked": 7,
            "border_width_unchecked": 2,
            "font": ("Roboto", 11),
        })

        # --- Serial ports (Windows) ---
        def _list_serial_ports():
            try:
                from serial.tools import list_ports
                ports = [p.device for p in list_ports.comports()]
                ports = sorted(ports, key=lambda s: (len(s), s))
                return ports
            except Exception:
                return []

        port_values = _list_serial_ports()
        if not port_values:
            # Fallback to something reasonable so the combobox isn't empty
            port_values = ["COM1"]

        # Ensure current selections stay selectable even if not detected right now
        try:
            cur_cat = self.p.cat_port.get()
            if cur_cat and cur_cat not in port_values:
                port_values = [cur_cat] + port_values
        except Exception:
            pass

        try:
            cur_ptt = self.p.ptt_port.get()
            if cur_ptt and cur_ptt not in port_values:
                port_values = [cur_ptt] + port_values
        except Exception:
            pass

        # Rig row
        rig_fr = ctk.CTkFrame(main_pad, fg_color="transparent")
        rig_fr.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(rig_fr, text="Rig:").pack(side="left", padx=(4, 8))
        ctk.CTkComboBox(rig_fr, values=["Yaesu FT-991"], width=700).pack(side="left", fill="x", expand=True)

        # Two columns
        split_fr = ctk.CTkFrame(main_pad, fg_color="transparent")
        split_fr.pack(fill="both", expand=True)

        # LEFT: CAT
        cat_box = ctk.CTkFrame(split_fr, border_width=1)
        cat_box.pack(side="left", padx=(0, 8), pady=5, fill="both", expand=True)
        ctk.CTkLabel(cat_box, text="CAT Control", font=("", 12, "bold")).pack(pady=(8, 10))

        ctk.CTkLabel(cat_box, text="Serial Port:").pack(anchor="w", padx=14)
        cat_port_combo = ctk.CTkComboBox(cat_box, values=port_values, variable=self.p.cat_port, width=160)
        cat_port_combo.pack(padx=14, pady=(0, 8))

        ctk.CTkLabel(cat_box, text="Baud Rate:").pack(anchor="center", pady=(2, 4))
        ctk.CTkComboBox(cat_box, values=["1200","2400","4800","9600","19200","38400","57600","115200"], variable=self.p.baud_rate, width=160).pack(pady=(0, 10))

        def make_group(parent, title, var, options):
            box = ctk.CTkFrame(parent)
            box.pack(fill="x", padx=10, pady=6)
            ctk.CTkLabel(box, text=title, font=("", 11, "bold")).pack(anchor="w", padx=10, pady=(6, 4))
            rows = ctk.CTkFrame(box, fg_color="transparent")
            rows.pack(fill="x", padx=8, pady=(0, 8))
            for i, option in enumerate(options):
                ctk.CTkRadioButton(
                    rows, text=option, variable=var, value=option, **radio_cfg
                ).grid(row=i // 3, column=i % 3, padx=18, pady=6, sticky="w")

        make_group(cat_box, "Data Bits", self.p.data_bits, ["Default", "Seven", "Eight"])
        make_group(cat_box, "Stop Bits", self.p.stop_bits, ["Default", "One", "Two"])
        make_group(cat_box, "Handshake", self.p.handshake, ["Default", "None", "XON/XOFF", "Hardware"])

        # RIGHT: PTT/Mode/Split + tests
        right_box = ctk.CTkFrame(split_fr)
        right_box.pack(side="left", padx=(8, 0), pady=5, fill="both", expand=True)

        ptt_f_cont = ctk.CTkFrame(right_box, border_width=1)
        ptt_f_cont.pack(fill="x", padx=5, pady=(0, 10))
        ctk.CTkLabel(ptt_f_cont, text="PTT Method", font=("", 11, "bold")).pack(anchor="w", padx=10, pady=(8, 6))

        ptt_grid = ctk.CTkFrame(ptt_f_cont, fg_color="transparent")
        ptt_grid.pack(fill="x", padx=8)
        ptt_options = ["VOX", "DTR", "CAT", "RTS"]
        for i, label_txt in enumerate(ptt_options):
            ctk.CTkRadioButton(
                ptt_grid, text=label_txt, variable=self.p.ptt_method_val, value=label_txt, **radio_cfg
            ).grid(row=i // 2, column=i % 2, padx=40, pady=10, sticky="w")

        ctk.CTkLabel(ptt_f_cont, text="Port:").pack(anchor="w", padx=14)
        ptt_port_combo = ctk.CTkComboBox(ptt_f_cont, values=port_values, variable=self.p.ptt_port, width=160)
        ptt_port_combo.pack(padx=14, pady=(0, 6))
        ctk.CTkCheckBox(ptt_f_cont, text="PTT invertieren (+V)", variable=self.p.ptt_invert).pack(anchor="w", padx=14, pady=(0, 10))

        def make_inline_group(parent, title, var, options):
            box = ctk.CTkFrame(parent)
            box.pack(fill="x", padx=5, pady=6)
            ctk.CTkLabel(box, text=title, font=("", 11, "bold")).pack(anchor="w", padx=10, pady=(6, 4))
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=(0, 8))
            for option in options:
                ctk.CTkRadioButton(row, text=option, variable=var, value=option, **radio_cfg).pack(side="left", padx=18)

        make_inline_group(right_box, "Mode", self.p.rig_mode, ["None", "USB", "Data/Pkt"])
        make_inline_group(right_box, "Split Operation", self.p.split_op, ["None", "Rig", "Fake It"])

        def _safe_test_cat():
            try:
                import serial
                with serial.Serial(self.p.cat_port.get(), int(self.p.baud_rate.get()), timeout=0.5) as s:
                    ok = bool(self.p.cat.get_freq(s))
                self.p.btn_tcat.configure(fg_color="#28a745" if ok else "#dc3545")
            except Exception as e:
                print(f"Test CAT Fehler: {e}")
                try:
                    self.p.btn_tcat.configure(fg_color="#dc3545")
                except Exception:
                    pass

        def _safe_test_ptt():
            try:
                import serial
                import time
                with serial.Serial(self.p.ptt_port.get(), 38400, timeout=0.5) as s:
                    safe_level = bool(self.p.ptt_invert.get())
                    try:
                        s.setRTS(safe_level)
                    except Exception:
                        pass
                    try:
                        s.setDTR(safe_level)
                    except Exception:
                        pass
                    time.sleep(0.1)

                    method = str(self.p.ptt_method_val.get()).upper()
                    if method == "RTS":
                        s.setRTS(not safe_level)
                        time.sleep(0.3)
                        s.setRTS(safe_level)
                    elif method == "DTR":
                        s.setDTR(not safe_level)
                        time.sleep(0.3)
                        s.setDTR(safe_level)
                    else:
                        # Fallback: kurzer RTS-Impuls
                        s.setRTS(not safe_level)
                        time.sleep(0.3)
                        s.setRTS(safe_level)

                self.p.btn_tptt.configure(fg_color="#28a745")
            except Exception as e:
                print(f"Test PTT Fehler: {e}")
                try:
                    self.p.btn_tptt.configure(fg_color="#dc3545")
                except Exception:
                    pass

        test_row = ctk.CTkFrame(right_box, fg_color="transparent")
        test_row.pack(fill="x", pady=(8, 0))
        self.p.btn_tcat = ctk.CTkButton(test_row, text="Test CAT", command=self._wrap("UI: Test CAT pressed", _safe_test_cat), width=140)
        self.p.btn_tcat.pack(side="left", padx=10, pady=6, expand=True)
        self.p.btn_tptt = ctk.CTkButton(test_row, text="Test PTT", command=self._wrap("UI: Test PTT pressed", _safe_test_ptt), width=140)
        self.p.btn_tptt.pack(side="left", padx=10, pady=6, expand=True)

        ctk.CTkButton(
            main_pad,
            text="EINSTELLUNGEN SPEICHERN",
            fg_color="#28a745",
            hover_color="#24963f",
            height=46,
            command=self._wrap("UI: SAVE SETTINGS pressed", getattr(self.p, "save_settings", lambda: None))
        ).pack(pady=(14, 0), fill="x")

        self.finalize_and_center(win)


    def _on_notch_slider(self, value):
        """
        NOTCH slider is displayed in Hz (10..3200). Internally we store Hz as string.
        """
        try:
            hz = int(round(float(value)))
        except Exception:
            hz = 1000
        hz = max(10, min(3200, hz))
        self.p.manual_notch_freq.set(str(hz))
        try:
            self.p.notch_value_label.configure(text=f"{hz:04d}")
        except Exception:
            pass
        # Forward to main for debounce + CAT apply
        try:
            if hasattr(self.p, "on_notch_slider"):
                self.p.on_notch_slider(hz)
        except Exception:
            pass

    def _on_pwr_slider(self, value):
        try:
            power = max(5, min(100, int(round(float(value)))))
        except Exception:
            power = 50
        self.p.pwr_level.set(str(power))
        try:
            self.p.pwr_value_label.configure(text=str(power))
        except Exception:
            pass
        if self.p.is_connected and self.p.ser_cat:
            try:
                self.p.cat.set_rf_power(self.p.ser_cat, power)
            except Exception:
                pass

    def _on_vox_toggle(self):
        try:
            self.p.save_settings()
        except Exception:
            pass

    def _save_vox(self):
        try:
            self.p.save_settings()
        except Exception:
            pass