import os
import json
import threading

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                QPushButton, QComboBox, QProgressBar, QApplication)
from PySide6.QtGui import QPainter, QColor
from PySide6.QtCore import QSize, QPoint, Qt, QEvent, QRect, QTimer, Signal

from core.theme import T, themed_icon
from core.session_logger import log_action, log_event, log_error
from ui._constants import _ICONS, _PROJECT_DIR
from ui._helpers import _list_audio_devices, _device_max_channels, _pw_find_id_by_name


class DropDownComboBox(QComboBox):
    """ComboBox die das Popup immer unterhalb öffnet."""
    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        pos = self.mapToGlobal(QPoint(0, self.height()))
        popup.move(pos)


class AudioSetupOverlay(QWidget):

    _save_sig  = Signal(bool)
    _rec_sig   = Signal(bool)   # True = aufnahme gestartet
    _wave_done = Signal()       # Wave Test fertig
    _rec_done  = Signal()       # Playback fertig
    _vu_level  = Signal(float)  # VU Meter Level 0.0–1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.hide()
        self._recording = False
        if parent:
            parent.installEventFilter(self)

        # ── Panel ────────────────────────────────────────────────────
        self.panel = QWidget(self)
        self.panel.setFixedSize(700, 400)
        self.panel.setObjectName("audiopanel")
        self.panel.setStyleSheet(f"""
            QWidget#audiopanel {{
                background-color: {T['bg_dark']};
                border: 1px solid {T['border']};
                border-radius: 12px;
            }}
        """)

        root = QVBoxLayout(self.panel)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)

        # ── Title + Save button ─────────────────────────────────────
        title_row = QHBoxLayout()
        self._audio_title = QLabel("Audio Matrix")
        self._audio_title.setStyleSheet(f"color: {T['text']}; font-size: 16px; font-weight: bold; border: none;")
        title_row.addWidget(self._audio_title)
        title_row.addStretch()

        _icon_btn_style = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['border']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['border_hover']}; }}"""

        self.btn_wave = QPushButton()
        self.btn_wave.setFixedSize(40, 40)
        self.btn_wave.setIcon(themed_icon(os.path.join(_ICONS, "sound.svg")))
        self.btn_wave.setIconSize(QSize(22, 22))
        self.btn_wave.setCursor(Qt.PointingHandCursor)
        self.btn_wave.setToolTip("Wave Test")
        self.btn_wave.setStyleSheet(_icon_btn_style)
        title_row.addWidget(self.btn_wave)

        self.btn_rec = QPushButton()
        self.btn_rec.setFixedSize(40, 40)
        self.btn_rec.setIcon(themed_icon(os.path.join(_ICONS, "mic.svg")))
        self.btn_rec.setIconSize(QSize(22, 22))
        self.btn_rec.setCursor(Qt.PointingHandCursor)
        self.btn_rec.setToolTip("Aufnahme Test")
        self._rec_style_idle = _icon_btn_style
        self._rec_style_active = f"""
            QPushButton {{ background-color: rgba(139, 0, 0, 255); border: 2px solid {T['error']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: rgba(160, 0, 0, 255); }}"""
        self.btn_rec.setStyleSheet(self._rec_style_idle)
        title_row.addWidget(self.btn_rec)

        self.btn_save = QPushButton()
        self.btn_save.setFixedSize(40, 40)
        self.btn_save.setIcon(themed_icon(os.path.join(_ICONS, "save.svg")))
        self.btn_save.setIconSize(QSize(22, 22))
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setToolTip("Audio-Matrix speichern")
        self._save_style_default = _icon_btn_style
        self._save_style_ok  = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['accent']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['accent']}; }}"""
        self._save_style_err = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['error']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['error']}; }}"""
        self.btn_save.setStyleSheet(self._save_style_default)
        title_row.addWidget(self.btn_save)
        root.addLayout(title_row)

        # ── 4 Device rows ─────────────────────────────────────────────
        rows_cfg = [
            ("1. PC MIKROFON",      "input"),
            ("2. TRX MIKROFON",     "input"),
            ("3. TRX LAUTSPRECHER", "output"),
            ("4. PC LAUTSPRECHER",  "output"),
        ]

        _combo_style = f"""
            QComboBox {{ background-color: {T['bg_mid']}; color: {T['text_secondary']}; border: 1px solid {T['border']};
                        border-radius: 5px; padding: 4px 8px; font-size: 12px; min-height: 26px; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{ background-color: {T['bg_mid']}; color: {T['text_secondary']};
                        selection-background-color: {T['bg_light']}; border: 1px solid {T['border']}; }}"""

        self.device_combos = []
        self.rate_combos   = []
        self.chan_combos   = []
        self._row_kinds    = []
        self._row_labels   = []

        for label_text, kind in rows_cfg:
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"color: {T['accent']}; font-size: 11px; font-weight: bold; border: none;")
            root.addWidget(lbl)
            self._row_labels.append(lbl)

            row = QHBoxLayout()
            row.setSpacing(8)

            dev_cb = DropDownComboBox()
            devs = _list_audio_devices(kind)
            for item in devs:
                if isinstance(item, tuple):
                    display, internal = item
                    dev_cb.addItem(display, userData=internal)
                else:
                    dev_cb.addItem(item, userData=item)
            dev_cb.setStyleSheet(_combo_style)
            row.addWidget(dev_cb, stretch=1)

            rate_cb = DropDownComboBox()
            rate_cb.addItems(["44100", "48000", "96000", "192000"])
            rate_cb.setFixedWidth(90)
            rate_cb.setStyleSheet(_combo_style)
            row.addWidget(rate_cb)

            chan_cb = DropDownComboBox()
            chan_cb.setFixedWidth(55)
            chan_cb.setStyleSheet(_combo_style)
            row.addWidget(chan_cb)

            root.addLayout(row)
            self.device_combos.append(dev_cb)
            self.rate_combos.append(rate_cb)
            self.chan_combos.append(chan_cb)
            self._row_kinds.append(kind)

            idx = len(self.device_combos) - 1
            dev_cb.currentTextChanged.connect(
                lambda txt, i=idx, k=kind: self._update_channels(i, txt, k)
            )
            self._update_channels(idx, dev_cb.currentText(), kind)

        # ── VU Meter ─────────────────────────────────────────────────
        self.vu_bar = QProgressBar()
        self.vu_bar.setFixedHeight(10)
        self.vu_bar.setRange(0, 100)
        self.vu_bar.setValue(0)
        self.vu_bar.setTextVisible(False)
        root.addWidget(self.vu_bar)

        # ── Signals ───────────────────────────────────────────────────
        self.btn_save.clicked.connect(self.save_to_config)
        self.btn_wave.clicked.connect(self._wave_test)
        self.btn_rec.clicked.connect(self._toggle_rec)
        self._save_sig.connect(self._on_save_result)
        self._wave_done.connect(self._wave_test_reset)
        self._rec_done.connect(self._on_rec_done)
        self._vu_level.connect(self._update_vu)

    def _update_vu(self, level):
        val = int(level * 100)
        self.vu_bar.setValue(val)
        if val < 60:
            color = T['vu_green']
        elif val < 85:
            color = T['vu_yellow']
        else:
            color = T['vu_red']
        self.vu_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {T['bg_dark']}; border: 1px solid {T['border']};
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                border-radius: 3px;
                background-color: {color};
            }}
        """)

    def _on_rec_done(self):
        self.btn_rec.setEnabled(True)
        self.vu_bar.setValue(0)
        self.btn_rec.setStyleSheet(self._icon_btn_ok)
        QTimer.singleShot(2000, lambda: self.btn_rec.setStyleSheet(self._rec_style_idle))

    def _update_channels(self, row_idx: int, device_str: str, kind: str):
        """Populate channel combo based on actual device max channels."""
        cb = self.chan_combos[row_idx]
        current = cb.currentText()
        max_ch = _device_max_channels(device_str, kind)
        cb.blockSignals(True)
        cb.clear()
        cb.addItems([str(i) for i in range(1, max_ch + 1)])
        if current and cb.findText(current) != -1:
            cb.setCurrentText(current)
        cb.blockSignals(False)

    # ── Config ──────────────────────────────────────────────────────

    _ROW_KEYS = ["pc_mic", "trx_mic", "trx_speaker", "pc_speaker"]

    def _rig_config_path(self) -> str:
        parent = self.parent()
        if parent is None:
            return ""
        main_win = parent.window()
        if hasattr(main_win, "radio_setup_overlay"):
            return main_win.radio_setup_overlay._config_path()
        return ""

    def load_from_config(self):
        path = self._rig_config_path()
        if not path or not os.path.exists(path):
            return
        try:
            with open(path) as f:
                full_cfg = json.load(f)
        except Exception:
            return
        cfg = full_cfg.get("audio", {})
        if not cfg:
            return
        for i, key in enumerate(self._ROW_KEYS):
            row = cfg.get(key, {})
            dev  = row.get("device", "")
            rate = str(row.get("rate", "44100"))
            chan = str(row.get("channels", "1"))
            cb = self.device_combos[i]
            matched = False
            if dev:
                for idx in range(cb.count()):
                    if cb.itemData(idx) == dev:
                        cb.setCurrentIndex(idx)
                        matched = True
                        break
                if not matched:
                    import re as _re
                    display = _re.sub(r"^\[.*?\]\s*", "", dev).strip()
                    for idx in range(cb.count()):
                        if cb.itemText(idx) == display:
                            cb.setCurrentIndex(idx)
                            matched = True
                            break
                if not matched and dev:
                    display = _re.sub(r"^\[.*?\]\s*", "", dev).strip()
                    cb.addItem(display, userData=dev)
                    cb.setCurrentIndex(cb.count() - 1)
            self.rate_combos[i].setCurrentText(rate)
            self.chan_combos[i].setCurrentText(chan)

    def save_to_config(self):
        path = self._rig_config_path()
        if not path:
            print("Audio save fehler: kein Rig ausgewählt")
            self._save_sig.emit(False)
            return
        try:
            if os.path.exists(path):
                with open(path) as f:
                    full_cfg = json.load(f)
            else:
                full_cfg = {}

            audio_cfg = {}
            for i, key in enumerate(self._ROW_KEYS):
                audio_cfg[key] = {
                    "device":   self.device_combos[i].currentData() or self.device_combos[i].currentText(),
                    "rate":     int(self.rate_combos[i].currentText()),
                    "channels": int(self.chan_combos[i].currentText()),
                }

            full_cfg["audio"] = audio_cfg
            with open(path, "w") as f:
                json.dump(full_cfg, f, indent=4)

            with open(path) as f:
                check = json.load(f)
            ok = all(
                check["audio"][k]["device"] == audio_cfg[k]["device"] and
                check["audio"][k]["rate"]   == audio_cfg[k]["rate"]
                for k in self._ROW_KEYS
            )
        except Exception as e:
            print(f"Audio save fehler: {e}")
            ok = False
        self._save_sig.emit(ok)

    def _on_save_result(self, ok: bool):
        self.btn_save.setStyleSheet(self._save_style_ok if ok else self._save_style_err)
        QTimer.singleShot(2000, lambda: self.btn_save.setStyleSheet(self._save_style_default))
        if ok:
            main_win = self.parent().window() if self.parent() else None
            if main_win and hasattr(main_win, "_restart_audio"):
                main_win._restart_audio()

    # ── Wave Test ────────────────────────────────────────────────────

    _WAV_PATH = os.path.join(_PROJECT_DIR, "assets", "audio", "VOXScrm_Wilhelm_scream.wav")
    _TEMP_REC = os.path.join(_PROJECT_DIR, "assets", "audio", "temp_rec.wav")

    def _find_sd_device(self, combo_index, need_input=False, need_output=False):
        """Finde den sounddevice Device-Index anhand des Namens im Combo."""
        import sounddevice as sd
        import re
        txt = self.device_combos[combo_index].currentText()
        name = re.sub(r"^\[.*?\]\s*", "", txt).strip()
        name = re.sub(r"\s*\((Eingang|Ausgabe)\)\s*$", "", name).strip().lower()

        for i, d in enumerate(sd.query_devices()):
            if need_input and d["max_input_channels"] < 1:
                continue
            if need_output and d["max_output_channels"] < 1:
                continue
            if name in d["name"].lower():
                return i
        return None

    def _pw_node_name_for(self, combo_index):
        """PipeWire node.name direkt aus Combo-Text lesen."""
        import subprocess, re
        txt = self.device_combos[combo_index].currentData() or self.device_combos[combo_index].currentText()
        m = re.search(r"\[pw:([^\]]+)\]", txt)
        if not m:
            return None
        pw_val = m.group(1)
        if not pw_val.isdigit():
            return pw_val
        try:
            out = subprocess.run(["pw-cli", "info", pw_val],
                capture_output=True, text=True, timeout=2).stdout
            for line in out.splitlines():
                if "node.name" in line and "node.nick" not in line:
                    nm = re.search(r'"(.+?)"', line)
                    if nm:
                        return nm.group(1)
        except Exception:
            pass
        return pw_val

    def _wave_test(self):
        """WAV auf PC LAUTSPRECHER (Zeile 4, Index 3) abspielen."""
        self.btn_wave.setEnabled(False)
        import platform
        pw_target = self._pw_node_name_for(3) if platform.system() == "Linux" else None

        def run():
            try:
                if pw_target:
                    import subprocess
                    subprocess.run(
                        ["pw-play", "--target", pw_target, self._WAV_PATH],
                        timeout=15
                    )
                else:
                    import sounddevice as sd, numpy as np, wave
                    with wave.open(self._WAV_PATH, "rb") as wf:
                        rate = wf.getframerate()
                        frames = wf.readframes(wf.getnframes())
                        dtype = np.int16 if wf.getsampwidth() == 2 else np.uint8
                        data = np.frombuffer(frames, dtype=dtype).astype(np.float32)
                        data /= np.iinfo(dtype).max
                        if wf.getnchannels() > 1:
                            data = data.reshape(-1, wf.getnchannels())
                    sd.play(data, rate)
                    sd.wait()
            except Exception as e:
                print(f"Wave Test Fehler: {e}")
            self._wave_done.emit()
        threading.Thread(target=run, daemon=True).start()

    @property
    def _icon_btn_ok(self):
        return f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['accent']};
                          border-radius: 5px; padding: 5px; }}"""

    def _wave_test_reset(self):
        self.btn_wave.setEnabled(True)
        self.btn_wave.setStyleSheet(self._icon_btn_ok)
        QTimer.singleShot(2000, lambda: self.btn_wave.setStyleSheet(self._rec_style_idle))

    # ── Record ───────────────────────────────────────────────────────

    def _toggle_rec(self):
        """Aufnahme von PC MIKROFON (Zeile 1, Index 0),
        Wiedergabe auf PC LAUTSPRECHER (Zeile 4, Index 3)."""
        import platform

        if not self._recording:
            try:
                if os.path.exists(self._TEMP_REC):
                    os.remove(self._TEMP_REC)
            except Exception:
                pass

            rate = int(self.rate_combos[0].currentText())
            ch = int(self.chan_combos[0].currentText())
            self._recording = True
            self._rec_frames = []
            self._rec_rate = rate
            self._rec_ch = ch
            self.btn_rec.setStyleSheet(self._rec_style_active)

            if platform.system() == "Linux":
                pw_mic = self._pw_node_name_for(0)
                if not pw_mic:
                    print("PC Mikrofon nicht gefunden!")
                    self._recording = False
                    self.btn_rec.setStyleSheet(self._rec_style_idle)
                    return
                import subprocess
                self._rec_process = subprocess.Popen(
                    ["pw-cat", "--record", "--target", pw_mic,
                     "--format", "s16", "--rate", str(rate), "--channels", str(ch), "-"],
                    stdout=subprocess.PIPE)

                def read_audio():
                    import numpy as np
                    chunk_size = 1024 * ch * 2
                    while self._recording and self._rec_process:
                        data = self._rec_process.stdout.read(chunk_size)
                        if not data:
                            break
                        self._rec_frames.append(data)
                        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                        rms = np.sqrt(np.mean(samples ** 2)) / 32768.0
                        self._vu_level.emit(min(1.0, rms * 5.0))

                self._rec_thread = threading.Thread(target=read_audio, daemon=True)
                self._rec_thread.start()
                print(f"Aufnahme: pw-cat --target {pw_mic} | {rate}Hz | {ch}ch")
            else:
                import sounddevice as sd, numpy as np
                mic_idx = self._find_sd_device(0, need_input=True)
                if mic_idx is None:
                    print("PC Mikrofon nicht gefunden!")
                    self._recording = False
                    self.btn_rec.setStyleSheet(self._rec_style_idle)
                    return
                def callback(indata, frames, time_info, status):
                    if self._recording:
                        self._rec_frames.append(indata.copy())
                        rms = float(np.sqrt(np.mean(indata ** 2)))
                        self._vu_level.emit(min(1.0, rms * 5.0))
                self._rec_stream = sd.InputStream(
                    device=mic_idx, samplerate=rate, channels=ch,
                    dtype="float32", blocksize=1024, callback=callback)
                self._rec_stream.start()
        else:
            # ── Stop & Play ───────────────────────────────────────
            self._recording = False
            self.btn_rec.setStyleSheet(self._rec_style_idle)
            self.btn_rec.setEnabled(False)
            self._vu_level.emit(0.0)

            pw_spk = self._pw_node_name_for(3) if platform.system() == "Linux" else None

            if platform.system() == "Linux":
                if hasattr(self, "_rec_process") and self._rec_process:
                    self._rec_process.terminate()
                    try: self._rec_process.wait(timeout=3)
                    except Exception: pass
                    self._rec_process = None
                if hasattr(self, "_rec_thread"):
                    self._rec_thread.join(timeout=2)

                frames_raw = self._rec_frames
                rate = self._rec_rate
                ch = self._rec_ch
                self._rec_frames = []

                def save_and_play():
                    try:
                        if not frames_raw:
                            print("Keine Daten!")
                            self._rec_done.emit()
                            return
                        import wave as wavmod
                        raw = b"".join(frames_raw)
                        with wavmod.open(self._TEMP_REC, "wb") as wf:
                            wf.setnchannels(ch)
                            wf.setsampwidth(2)
                            wf.setframerate(rate)
                            wf.writeframes(raw)
                        if pw_spk:
                            import subprocess
                            subprocess.run(
                                ["pw-play", "--target", pw_spk, self._TEMP_REC],
                                timeout=30)
                        print("Playback fertig")
                    except Exception as e:
                        print(f"Playback Fehler: {e}")
                    self._rec_done.emit()
                threading.Thread(target=save_and_play, daemon=True).start()
            else:
                import sounddevice as sd, numpy as np
                if hasattr(self, "_rec_stream") and self._rec_stream:
                    self._rec_stream.stop()
                    self._rec_stream.close()
                    self._rec_stream = None
                if self._rec_frames:
                    audio = np.concatenate(self._rec_frames, axis=0)
                    rate = self._rec_rate
                    self._rec_frames = []
                    def playback():
                        sd.play(audio, rate)
                        sd.wait()
                        self._rec_done.emit()
                    threading.Thread(target=playback, daemon=True).start()
                else:
                    self._rec_done.emit()

    # ── Overlay mechanics ────────────────────────────────────────────

    def _refresh_styles(self):
        """Styles mit aktuellen Theme-Werten neu setzen."""
        self.panel.setStyleSheet(f"""
            QWidget#audiopanel {{
                background-color: {T['bg_dark']};
                border: 1px solid {T['border']};
                border-radius: 12px;
            }}
        """)
        self._audio_title.setStyleSheet(f"color: {T['text']}; font-size: 16px; font-weight: bold; border: none;")

        _icon_btn_style = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['border']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['border_hover']}; }}"""
        self._rec_style_idle = _icon_btn_style
        self._save_style_default = _icon_btn_style
        self._save_style_ok = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['accent']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['accent']}; }}"""
        self._save_style_err = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['error']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['error']}; }}"""

        self.btn_wave.setStyleSheet(_icon_btn_style)
        self.btn_rec.setStyleSheet(self._rec_style_idle)
        self.btn_save.setStyleSheet(self._save_style_default)
        self.btn_wave.setIcon(themed_icon(os.path.join(_ICONS, "sound.svg")))
        self.btn_rec.setIcon(themed_icon(os.path.join(_ICONS, "mic.svg")))
        self.btn_save.setIcon(themed_icon(os.path.join(_ICONS, "save.svg")))

        _combo_style = f"""
            QComboBox {{ background-color: {T['bg_mid']}; color: {T['text_secondary']}; border: 1px solid {T['border']};
                        border-radius: 5px; padding: 4px 8px; font-size: 12px; min-height: 26px; }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{ background-color: {T['bg_mid']}; color: {T['text_secondary']};
                        selection-background-color: {T['bg_light']}; border: 1px solid {T['border']}; }}"""

        for lbl in self._row_labels:
            lbl.setStyleSheet(f"color: {T['accent']}; font-size: 11px; font-weight: bold; border: none;")
        for cb in self.device_combos + self.rate_combos + self.chan_combos:
            cb.setStyleSheet(_combo_style)

    def show_overlay(self):
        self._refresh_styles()
        parent = self.parent()
        self.setGeometry(parent.rect())
        pw = min(700, int(parent.width() * 0.85))
        ph = min(400, int(parent.height() * 0.85))
        self.panel.setFixedSize(pw, ph)
        self.panel.move((self.width() - pw) // 2, (self.height() - ph) // 2)
        self.load_from_config()
        self.show()
        self.raise_()
        QApplication.instance().installEventFilter(self)

    def hide(self):
        try:
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass
        super().hide()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            global_pos = event.globalPosition().toPoint()
            panel_rect = QRect(self.panel.mapToGlobal(QPoint(0, 0)), self.panel.size())
            if not panel_rect.contains(global_pos):
                widget_at = QApplication.widgetAt(global_pos)
                if widget_at is not None:
                    parent = widget_at
                    while parent is not None:
                        if parent is self.panel:
                            return False
                        parent = parent.parent()
                    top = widget_at.window()
                    if top is not None and top is not self.parent().window():
                        return False
                self.hide()
        elif event.type() == QEvent.Type.Resize and obj is self.parent() and self.isVisible():
            parent = self.parent()
            self.setGeometry(parent.rect())
            pw = min(700, int(parent.width() * 0.85))
            ph = min(400, int(parent.height() * 0.85))
            self.panel.setFixedSize(pw, ph)
            self.panel.move((self.width() - pw) // 2, (self.height() - ph) // 2)
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
