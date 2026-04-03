import os
import json
import copy

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                QPushButton, QComboBox, QScrollArea, QLineEdit,
                                QColorDialog, QMenu, QMessageBox, QApplication)
from PySide6.QtGui import QPainter, QColor, QIcon, QTransform
from PySide6.QtCore import QSize, QPoint, Qt, QEvent, QRect, QTimer

from core.theme import (T, load_theme, save_theme, apply_theme, hex_to_rgba, rgba_to_hex,
                         rgba_parts, with_alpha, PRESETS, PRESET_NAMES, register_refresh,
                         unregister_refresh, detect_preset, get_last_theme, themed_icon,
                         load_user_themes, save_user_theme, delete_user_theme, is_builtin_preset)
from core.session_logger import log_action
from ui._constants import _ICONS, _THEME_PATH, _THEME_FIELDS, _SMETER_STYLES
from ui.audio_setup import DropDownComboBox


class ThemeEditorOverlay(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.hide()
        if parent:
            parent.installEventFilter(self)

        self.btn_delete = QPushButton()
        self.btn_delete.setFixedSize(0, 0)
        self.btn_delete.setVisible(False)
        self._user_edited_name = False
        self._name_block_signal = False
        self._selected_key = None

        self.panel = QWidget(self)
        self.panel.setFixedSize(400, 520)
        self.panel.setObjectName("themepanel")
        self._apply_panel_style()

        root = QVBoxLayout(self.panel)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(6)

        # ── Title Row ─────────────────────────────────────────────────
        self._title_lbl = QLabel("Theme Editor")
        self._title_lbl.setStyleSheet(f"color: {T['text']}; font-size: 16px; font-weight: bold; border: none;")
        root.addWidget(self._title_lbl)

        self.combo_preset = DropDownComboBox()
        self.combo_preset.hide()
        self._preset_lbl = QLabel("")

        # ── Tab-Leiste (Akten-Ordner Laschen) ─────────────────────
        from PySide6.QtWidgets import QStackedWidget
        tab_row = QHBoxLayout()
        tab_row.setSpacing(0)
        self._tab_buttons = []
        self._tab_names = ["Farben", "S-Meter", "Digi-Modes"]
        self._current_tab = 0

        for i, name in enumerate(self._tab_names):
            btn = QPushButton(name)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda checked, idx=i: self._switch_tab(idx))
            tab_row.addWidget(btn)
            self._tab_buttons.append(btn)
        tab_row.addStretch()
        root.addLayout(tab_row)
        self._apply_tab_styles()

        self._tab_stack = QStackedWidget()
        self._tab_stack.setStyleSheet("background: transparent;")

        # ── TAB 0: Farben ─────────────────────────────────────────
        self._tab_colors = QWidget()
        tab_colors_layout = QVBoxLayout(self._tab_colors)
        tab_colors_layout.setContentsMargins(0, 4, 0, 0)
        tab_colors_layout.setSpacing(4)

        # ── Farbliste mit Punkten + Edit-Button pro Zeile ─────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 6px; background: transparent; }
            QScrollBar::handle:vertical { background: rgba(128,128,128,60); border-radius: 3px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        """)
        scroll_widget = QWidget()
        color_list = QVBoxLayout(scroll_widget)
        color_list.setContentsMargins(4, 4, 4, 4)
        color_list.setSpacing(1)

        self._color_buttons = {}
        self._color_rows = {}
        self._color_dots = {}
        self._theme_data = {}

        for key, label in _THEME_FIELDS:
            row_widget = QWidget()
            row_widget.setFixedHeight(34)
            row_widget.setCursor(Qt.PointingHandCursor)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(6, 0, 6, 0)
            row_layout.setSpacing(6)

            dot = QLabel("")
            dot.setFixedSize(20, 20)
            dot.setStyleSheet(f"background: {T['accent']}; border: 2px solid {T['border']}; border-radius: 10px;")
            row_layout.addWidget(dot)
            self._color_dots[key] = dot

            lbl = QPushButton(label)
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.setStyleSheet(f"""
                QPushButton {{ background: transparent; border: none;
                    color: {T['text_secondary']}; font-size: 11px; text-align: left; padding: 0; }}
                QPushButton:hover {{ color: {T['text']}; }}
            """)
            lbl.clicked.connect(lambda checked, k=key: self._select_color(k))
            row_layout.addWidget(lbl, stretch=1)

            btn_edit = QPushButton()
            btn_edit.setFixedSize(34, 34)
            btn_edit.setCursor(Qt.PointingHandCursor)
            btn_edit.setIcon(themed_icon(os.path.join(_ICONS, "build.svg")))
            btn_edit.setIconSize(QSize(24, 24))
            btn_edit.setStyleSheet(f"""
                QPushButton {{ background: transparent; border: none; }}
                QPushButton:hover {{ background: {T['bg_light']}; border-radius: 3px; }}
            """)
            btn_edit.clicked.connect(lambda checked, k=key: self._edit_color(k))
            row_layout.addWidget(btn_edit)

            color_list.addWidget(row_widget)
            self._color_rows[key] = (row_widget, lbl, btn_edit)

        color_list.addStretch()
        scroll.setWidget(scroll_widget)
        tab_colors_layout.addWidget(scroll, stretch=1)
        self._tab_stack.addWidget(self._tab_colors)

        # ── TAB 1: S-Meter (Style-Liste mit Highlight) ────────────
        self._tab_smeter = QWidget()
        tab_smeter_layout = QVBoxLayout(self._tab_smeter)
        tab_smeter_layout.setContentsMargins(0, 4, 0, 0)
        tab_smeter_layout.setSpacing(2)

        # Dummy combo für Kompatibilität (versteckt)
        self.combo_smeter_style = DropDownComboBox()
        for key, label in _SMETER_STYLES:
            self.combo_smeter_style.addItem(label, userData=key)
        self.combo_smeter_style.hide()
        self.combo_smeter_style.currentIndexChanged.connect(self._on_smeter_style_changed)

        self._smeter_style_rows = {}
        self._selected_smeter = T.get("smeter_style", "segment")

        smeter_scroll = QScrollArea()
        smeter_scroll.setWidgetResizable(True)
        smeter_scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 6px; background: transparent; }
            QScrollBar::handle:vertical { background: rgba(128,128,128,60); border-radius: 3px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        """)
        smeter_list_widget = QWidget()
        smeter_list = QVBoxLayout(smeter_list_widget)
        smeter_list.setContentsMargins(4, 4, 4, 4)
        smeter_list.setSpacing(2)

        for key, label in _SMETER_STYLES:
            row = QWidget()
            row.setFixedHeight(36)
            row.setCursor(Qt.PointingHandCursor)
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(8, 0, 8, 0)
            row_l.setSpacing(8)

            # Punkt (Akzentfarbe wenn aktiv, grau wenn nicht)
            dot = QLabel("")
            dot.setFixedSize(14, 14)
            row_l.addWidget(dot)

            lbl = QPushButton(label)
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.clicked.connect(lambda checked, k=key: self._select_smeter_style(k))
            row_l.addWidget(lbl, stretch=1)

            smeter_list.addWidget(row)
            self._smeter_style_rows[key] = (row, dot, lbl)

        smeter_list.addStretch()
        smeter_scroll.setWidget(smeter_list_widget)
        tab_smeter_layout.addWidget(smeter_scroll, stretch=1)
        self._update_smeter_list_styles()
        self._tab_stack.addWidget(self._tab_smeter)

        # ── TAB 2: Digi-Modes ─────────────────────────────────────
        from ui.theme_digi import DigiColorWidget
        self._tab_digi = DigiColorWidget(self._theme_data)
        self._tab_stack.addWidget(self._tab_digi)

        root.addWidget(self._tab_stack, stretch=1)

        # Dummy-Attribute für Kompatibilität
        self._color_preview = QLabel("")
        self._color_name_lbl = QLabel("")
        self._rgba_inputs = {"R": QLineEdit(), "G": QLineEdit(), "B": QLineEdit(), "A": QLineEdit()}
        self._hex_input = QLineEdit()

        # ── Save Row ─────────────────────────────────────────────────
        hint_lbl = QLabel("Name ändern = neues Theme")
        hint_lbl.setStyleSheet(f"color: {T['text_muted']}; font-size: 9px; border: none;")
        root.addWidget(hint_lbl)

        save_row = QHBoxLayout()
        save_row.setSpacing(6)

        self.input_theme_name = QLineEdit()
        self.input_theme_name.setPlaceholderText("Theme-Name...")
        self.input_theme_name.setMinimumHeight(32)
        self.input_theme_name.setStyleSheet(f"""
            QLineEdit {{ background-color: {T['bg_mid']}; color: {T['text']};
                border: 1px solid {T['border']}; border-radius: 5px;
                padding: 4px 10px; font-size: 12px; }}
            QLineEdit:focus {{ border-color: {T['accent']}; }}
        """)
        self.input_theme_name.setFocusPolicy(Qt.ClickFocus)
        self.input_theme_name.textEdited.connect(self._on_name_edited)
        save_row.addWidget(self.input_theme_name, stretch=1)

        self._preset_menu = QMenu(self)
        btn_presets = QPushButton()
        btn_presets.setFixedSize(32, 32)
        btn_presets.setCursor(Qt.PointingHandCursor)
        self._update_arrow_icon(btn_presets)
        btn_presets.setStyleSheet(f"""
            QPushButton {{ background: {T['bg_mid']};
                border: 1px solid {T['border']}; border-radius: 5px; }}
            QPushButton:hover {{ border-color: {T['accent']}; }}
        """)
        self._btn_presets = btn_presets
        btn_presets.clicked.connect(lambda: self._show_preset_menu(btn_presets))
        save_row.addWidget(btn_presets)

        self.combo_preset = QComboBox()
        self.combo_preset.hide()

        self.btn_delete = QPushButton()
        self.btn_delete.setFixedSize(32, 32)
        self.btn_delete.setText("X")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setToolTip("User-Theme löschen")
        self._delete_style = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['error']};
                          border-radius: 5px; padding: 5px; color: {T['error']};
                          font-weight: bold; font-size: 12px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; }}"""
        self.btn_delete.setStyleSheet(self._delete_style)
        self.btn_delete.clicked.connect(self._delete_theme)
        save_row.addWidget(self.btn_delete)
        self._hide_delete_btn()

        btn_save = QPushButton()
        btn_save.setFixedSize(40, 40)
        btn_save.setIcon(themed_icon(os.path.join(_ICONS, "save.svg")))
        btn_save.setIconSize(QSize(22, 22))
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setToolTip("Theme speichern & anwenden")
        self._save_default = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['border']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['border_hover']}; }}"""
        self._save_ok = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['accent']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['accent']}; }}"""
        btn_save.setStyleSheet(self._save_default)
        btn_save.clicked.connect(self._save_theme)
        self._btn_save = btn_save
        save_row.addWidget(btn_save)

        root.addLayout(save_row)
        self._init_done = True

    def _switch_tab(self, idx):
        """Tab wechseln — Speichern-Dialog nur wenn Änderungen vorhanden."""
        if idx == self._current_tab:
            return
        # Prüfe ob sich was geändert hat seit dem letzten Snapshot
        if self._has_unsaved_changes():
            from PySide6.QtWidgets import QMessageBox
            msg = QMessageBox(self)
            msg.setWindowTitle("Speichern?")
            msg.setText("Änderungen speichern bevor Sie wechseln?")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            msg.button(QMessageBox.Yes).setText("Ja, speichern")
            msg.button(QMessageBox.No).setText("Verwerfen")
            msg.button(QMessageBox.Cancel).setText("Abbrechen")
            result = msg.exec()
            if result == QMessageBox.Cancel:
                return
            if result == QMessageBox.Yes:
                self._save_theme()
            else:
                # Verwerfen — Snapshot wiederherstellen
                self._theme_data.clear()
                self._theme_data.update(copy.deepcopy(self._theme_snapshot))
        self._current_tab = idx
        self._tab_stack.setCurrentIndex(idx)
        self._apply_tab_styles()
        self._take_snapshot()
        if idx == 1:
            self._selected_smeter = self._theme_data.get("smeter_style", "segment")
            self._update_smeter_list_styles()
        elif idx == 2:
            self._tab_digi.set_theme_data(self._theme_data)
        # Snapshot NACH Tab-Init (Defaults können theme_data erweitern)
        self._take_snapshot()

    def _take_snapshot(self):
        """Aktuellen Theme-Stand im RAM speichern für Änderungs-Erkennung."""
        self._theme_snapshot = copy.deepcopy(self._theme_data)

    def _has_unsaved_changes(self):
        """Prüft ob theme_data sich seit dem Snapshot geändert hat."""
        if not hasattr(self, '_theme_snapshot') or not self._theme_snapshot:
            return False
        return self._theme_data != self._theme_snapshot

    def _apply_tab_styles(self):
        """Tab-Buttons stylen — aktiver Tab hervorgehoben."""
        for i, btn in enumerate(self._tab_buttons):
            if i == self._current_tab:
                btn.setStyleSheet(f"""
                    QPushButton {{ background: {T['bg_mid']}; color: {T['text']};
                        border: 1px solid {T['border']}; border-bottom: none;
                        border-radius: 6px 6px 0 0; padding: 4px 12px;
                        font-size: 11px; font-weight: bold; }}""")
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{ background: transparent; color: {T['text_muted']};
                        border: none; border-bottom: 1px solid {T['border']};
                        border-radius: 0; padding: 4px 12px; font-size: 11px; }}
                    QPushButton:hover {{ color: {T['text']}; }}""")

    def _select_smeter_style(self, key):
        """S-Meter Style in der Liste auswählen."""
        self._selected_smeter = key
        self._theme_data["smeter_style"] = key
        self._update_smeter_list_styles()
        # Live-Preview
        T["smeter_style"] = key
        main_win = self.parent().window() if self.parent() else None
        if main_win and hasattr(main_win, "refresh_theme"):
            main_win.refresh_theme()
        from core.theme import _refresh_callbacks
        for cb in _refresh_callbacks[:]:
            try:
                cb()
            except Exception:
                pass

    def _update_smeter_list_styles(self):
        """S-Meter Style-Liste visuell aktualisieren."""
        for key, (row, dot, lbl) in self._smeter_style_rows.items():
            is_active = (key == self._selected_smeter)
            if is_active:
                dot.setStyleSheet(f"background: {T['accent']}; border: 2px solid {T['accent']}; border-radius: 7px;")
                lbl.setStyleSheet(f"""
                    QPushButton {{ background: transparent; border: none;
                        color: {T['text']}; font-size: 12px; font-weight: bold; text-align: left; padding: 0; }}""")
                row.setStyleSheet(f"background: {T['bg_light']}; border: 1px solid {T['accent']}; border-radius: 4px;")
            else:
                dot.setStyleSheet(f"background: {T['bg_light']}; border: 2px solid {T['border']}; border-radius: 7px;")
                lbl.setStyleSheet(f"""
                    QPushButton {{ background: transparent; border: none;
                        color: {T['text_secondary']}; font-size: 12px; text-align: left; padding: 0; }}
                    QPushButton:hover {{ color: {T['text']}; }}""")
                row.setStyleSheet("background: transparent; border: none; border-radius: 4px;")

    def _on_smeter_style_changed(self, index):
        """S-Meter Style in theme_data setzen → Live-Preview."""
        style_key = self.combo_smeter_style.itemData(index)
        if style_key:
            self._theme_data["smeter_style"] = style_key
            # Live-Preview: sofort anwenden
            T["smeter_style"] = style_key
            main_win = self.parent().window() if self.parent() else None
            if main_win and hasattr(main_win, "refresh_theme"):
                main_win.refresh_theme()
            from core.theme import _refresh_callbacks
            for cb in _refresh_callbacks[:]:
                try:
                    cb()
                except Exception:
                    pass

    def _hide_delete_btn(self):
        self.btn_delete.setFixedSize(0, 0)
        self.btn_delete.setVisible(False)

    def _show_delete_btn(self):
        self.btn_delete.setFixedSize(40, 40)
        self.btn_delete.setVisible(True)

    def _on_name_edited(self):
        if not self._name_block_signal:
            self._user_edited_name = True

    def _set_name_silent(self, text):
        self._name_block_signal = True
        self.input_theme_name.setText(text)
        self._name_block_signal = False

    def _clear_name_silent(self):
        self._name_block_signal = True
        self.input_theme_name.clear()
        self._name_block_signal = False

    def _apply_panel_style(self):
        self.panel.setStyleSheet(f"""
            QWidget#themepanel {{
                background-color: {T['bg_dark']};
                border: 1px solid {T['border']};
                border-radius: 12px;
            }}
        """)

    def _load_theme(self):
        try:
            with open(_THEME_PATH) as f:
                raw = json.load(f)
            self._theme_data = {k: v for k, v in raw.items() if not k.startswith("_")}
        except Exception:
            self._theme_data = {}

        for key in self._color_rows:
            self._update_color_row(key, selected=(key == self._selected_key))

        # S-Meter Style Dropdown synchronisieren
        if hasattr(self, 'combo_smeter_style'):
            current = self._theme_data.get("smeter_style", "segment")
            self.combo_smeter_style.blockSignals(True)
            for i in range(self.combo_smeter_style.count()):
                if self.combo_smeter_style.itemData(i) == current:
                    self.combo_smeter_style.setCurrentIndex(i)
                    break
            self.combo_smeter_style.blockSignals(False)

    def _update_arrow_icon(self, btn):
        icon = themed_icon(os.path.join(_ICONS, "arrow.svg"))
        pixmap = icon.pixmap(QSize(18, 18))
        rotated = pixmap.transformed(QTransform().rotate(270))
        btn.setIcon(QIcon(rotated))
        btn.setIconSize(QSize(18, 18))

    def _update_edit_icons(self):
        for key in self._color_rows:
            row_data = self._color_rows[key]
            if len(row_data) >= 3:
                btn_edit = row_data[2]
                btn_edit.setIcon(themed_icon(os.path.join(_ICONS, "build.svg")))
                btn_edit.setStyleSheet(f"""
                    QPushButton {{ background: transparent; border: none; }}
                    QPushButton:hover {{ background: {T['bg_light']}; border-radius: 3px; }}
                """)

    def _show_preset_menu(self, btn):
        self._preset_menu.clear()
        self._preset_menu.setStyleSheet(f"""
            QMenu {{ background: {T['bg_mid']}; color: {T['text']}; border: 1px solid {T['border']};
                border-radius: 6px; padding: 4px; }}
            QMenu::item {{ padding: 6px 16px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {T['bg_light']}; }}
        """)
        for key, name in PRESET_NAMES.items():
            action = self._preset_menu.addAction(name)
            action.setData(f"builtin:{key}")
            action.triggered.connect(lambda checked, k=key: self._load_preset(k))
        user_themes = load_user_themes()
        if user_themes:
            self._preset_menu.addSeparator()
            for name in sorted(user_themes.keys()):
                action = self._preset_menu.addAction(f"  {name}")
                action.triggered.connect(lambda checked, n=name: self._load_user_theme(n))

        menu_height = self._preset_menu.sizeHint().height()
        pos = btn.mapToGlobal(QPoint(0, -menu_height))
        self._preset_menu.exec(pos)

    def _load_preset(self, key):
        if key in PRESETS:
            self._theme_data = copy.deepcopy(PRESETS[key])
            self.input_theme_name.setText(PRESET_NAMES.get(key, key))
            self._user_edited_name = False
            for k in self._color_rows:
                self._update_color_row(k)
            self._hide_delete_btn()

    def _load_user_theme(self, name):
        user_themes = load_user_themes()
        if name in user_themes:
            self._theme_data = copy.deepcopy(user_themes[name])
            self.input_theme_name.setText(name)
            self._user_edited_name = True
            for k in self._color_rows:
                self._update_color_row(k)
            self._show_delete_btn()

    def _select_color(self, key):
        """Farbe in der Liste highlighten."""
        self._selected_key = key
        color_str = self._theme_data.get(key, "rgba(0, 0, 0, 255)")
        r, g, b, a = rgba_parts(color_str)

        self._color_preview.setStyleSheet(
            f"background: rgba({r},{g},{b},{a}); border-radius: 14px; border: 1px solid {T['border']};")
        self._color_name_lbl.setText(dict(_THEME_FIELDS).get(key, key))
        self._rgba_inputs["R"].setText(str(r))
        self._rgba_inputs["G"].setText(str(g))
        self._rgba_inputs["B"].setText(str(b))
        self._rgba_inputs["A"].setText(str(a))
        self._hex_input.setText(f"#{r:02x}{g:02x}{b:02x}")

        for k in self._color_rows:
            self._update_color_row(k, selected=(k == key))

    def _edit_color(self, key):
        """Edit-Button geklickt → Farbrad Popup öffnen."""
        self._selected_key = key
        color_str = self._theme_data.get(key, "rgba(0, 0, 0, 255)")
        r, g, b, a = rgba_parts(color_str)

        dlg = QColorDialog(QColor(r, g, b, a))
        dlg.setWindowTitle(dict(_THEME_FIELDS).get(key, key))
        dlg.setOption(QColorDialog.ShowAlphaChannel, True)

        if dlg.exec() == QColorDialog.Accepted:
            c = dlg.selectedColor()
            rgba_str = f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})"
            self._theme_data[key] = rgba_str
            self._update_color_row(key)

    def _update_color_row(self, key, selected=False):
        if key not in self._color_rows or key not in self._color_dots:
            return
        row_data = self._color_rows[key]
        widget = row_data[0]
        lbl = row_data[1]
        dot = self._color_dots[key]
        color_str = self._theme_data.get(key, "rgba(128,128,128,255)")
        r, g, b, a = rgba_parts(color_str)
        dot.setFixedSize(14, 14)
        dot.setText("")
        dot.setFixedSize(20, 20)
        dot.setStyleSheet(f"background: rgba({r},{g},{b},{a}); border: 2px solid {T['border']}; border-radius: 10px;")
        if selected:
            lbl.setStyleSheet(f"""QPushButton {{ background: transparent; border: none;
                color: {T['text']}; font-size: 11px; font-weight: bold; text-align: left; padding: 0; }}""")
            widget.setStyleSheet(f"background: {T['bg_light']}; border: 1px solid {T['accent']}; border-radius: 4px;")
        else:
            lbl.setStyleSheet(f"""QPushButton {{ background: transparent; border: none;
                color: {T['text_secondary']}; font-size: 11px; text-align: left; padding: 0; }}
                QPushButton:hover {{ color: {T['text']}; }}""")
            widget.setStyleSheet("background: transparent; border: none; border-radius: 4px;")

    def _apply_selected_color(self, r, g, b, a):
        if not self._selected_key:
            return
        rgba_str = f"rgba({r}, {g}, {b}, {a})"
        self._theme_data[self._selected_key] = rgba_str
        self._color_preview.setStyleSheet(
            f"background-color: rgba({r},{g},{b},{a}); border-radius: 8px; border: 1px solid {T['border']};")
        self._update_color_row(self._selected_key, selected=True)

    def _on_rgba_edited(self):
        try:
            r = max(0, min(255, int(self._rgba_inputs["R"].text())))
            g = max(0, min(255, int(self._rgba_inputs["G"].text())))
            b = max(0, min(255, int(self._rgba_inputs["B"].text())))
            a = max(0, min(255, int(self._rgba_inputs["A"].text())))
            self._hex_input.setText(f"#{r:02x}{g:02x}{b:02x}")
            self._apply_selected_color(r, g, b, a)
        except ValueError:
            pass

    def _on_hex_edited(self):
        hex_str = self._hex_input.text().strip().lstrip("#")
        if len(hex_str) == 6:
            try:
                r = int(hex_str[0:2], 16)
                g = int(hex_str[2:4], 16)
                b = int(hex_str[4:6], 16)
                a = int(self._rgba_inputs["A"].text() or "255")
                self._rgba_inputs["R"].setText(str(r))
                self._rgba_inputs["G"].setText(str(g))
                self._rgba_inputs["B"].setText(str(b))
                self._apply_selected_color(r, g, b, a)
            except ValueError:
                pass

    def _open_color_dialog(self):
        if not self._selected_key:
            return
        color_str = self._theme_data.get(self._selected_key, "rgba(0, 0, 0, 255)")
        r, g, b, a = rgba_parts(color_str)

        dlg = QColorDialog(QColor(r, g, b, a))
        dlg.setWindowTitle(f"Farbe: {dict(_THEME_FIELDS).get(self._selected_key, self._selected_key)}")
        dlg.setOption(QColorDialog.ShowAlphaChannel, True)

        dlg.currentColorChanged.connect(lambda c: self._apply_selected_color(
            c.red(), c.green(), c.blue(), c.alpha()))

        if dlg.exec() == QColorDialog.Accepted:
            color = dlg.selectedColor()
            self._rgba_inputs["R"].setText(str(color.red()))
            self._rgba_inputs["G"].setText(str(color.green()))
            self._rgba_inputs["B"].setText(str(color.blue()))
            self._rgba_inputs["A"].setText(str(color.alpha()))
            self._hex_input.setText(f"#{color.red():02x}{color.green():02x}{color.blue():02x}")
            self._apply_selected_color(color.red(), color.green(), color.blue(), color.alpha())
        else:
            self._apply_selected_color(r, g, b, a)
            self._rgba_inputs["R"].setText(str(r))
            self._rgba_inputs["G"].setText(str(g))
            self._rgba_inputs["B"].setText(str(b))
            self._rgba_inputs["A"].setText(str(a))
            self._hex_input.setText(f"#{r:02x}{g:02x}{b:02x}")

    def _pick_color(self, key):
        self._select_color(key)
        self._open_color_dialog()

    def _rebuild_preset_combo(self):
        self.combo_preset.blockSignals(True)
        self.combo_preset.clear()
        self.combo_preset.addItem("— Benutzerdefiniert —", None)
        for key, name in PRESET_NAMES.items():
            self.combo_preset.addItem(f"  {name}", f"builtin:{key}")
        user_themes = load_user_themes()
        if user_themes:
            for name in sorted(user_themes.keys()):
                self.combo_preset.addItem(f"  {name}", f"user:{name}")
        self.combo_preset.blockSignals(False)

    def _on_preset_selected(self, index):
        if index <= 0:
            self._hide_delete_btn()
            self._clear_name_silent()
            self.input_theme_name.setReadOnly(False)
            self.input_theme_name.setPlaceholderText("Theme-Name eingeben...")
            self._user_edited_name = False
            return

        data_key = self.combo_preset.itemData(index)
        if not data_key:
            return

        if data_key.startswith("builtin:"):
            preset_key = data_key.replace("builtin:", "")
            if preset_key in PRESETS:
                self._theme_data = copy.deepcopy(PRESETS[preset_key])
                self._clear_name_silent()
                self.input_theme_name.setReadOnly(True)
                self.input_theme_name.setPlaceholderText("Preset (read-only)")
                self._user_edited_name = False
                self._hide_delete_btn()
        elif data_key.startswith("user:"):
            theme_name = data_key.replace("user:", "")
            user_themes = load_user_themes()
            if theme_name in user_themes:
                self._theme_data = copy.deepcopy(user_themes[theme_name])
                self._set_name_silent(theme_name)
                self.input_theme_name.setReadOnly(False)
                self.input_theme_name.setPlaceholderText("Theme-Name eingeben...")
                self._user_edited_name = True
                self._show_delete_btn()

        for key in self._color_rows:
            self._update_color_row(key, selected=(key == self._selected_key))

        # Live-Preview
        T.clear()
        T.update(self._theme_data)
        main_win = self.parent().window() if self.parent() else None
        if main_win and hasattr(main_win, "refresh_theme"):
            main_win.refresh_theme()
        from core.theme import _refresh_callbacks
        for cb in _refresh_callbacks[:]:
            try:
                cb()
            except Exception:
                pass

    def _detect_current_preset(self):
        self.combo_preset.blockSignals(True)
        self._hide_delete_btn()

        current = detect_preset()
        if current:
            for i in range(self.combo_preset.count()):
                if self.combo_preset.itemData(i) == f"builtin:{current}":
                    self.combo_preset.setCurrentIndex(i)
                    self._clear_name_silent()
                    self._user_edited_name = False
                    self.combo_preset.blockSignals(False)
                    return

        user_themes = load_user_themes()
        for name, theme_data in user_themes.items():
            if all(T.get(k) == v for k, v in theme_data.items()):
                for i in range(self.combo_preset.count()):
                    if self.combo_preset.itemData(i) == f"user:{name}":
                        self.combo_preset.setCurrentIndex(i)
                        self._set_name_silent(name)
                        self._user_edited_name = True
                        self._show_delete_btn()
                        self.combo_preset.blockSignals(False)
                        return

        self.combo_preset.setCurrentIndex(0)
        self._clear_name_silent()
        self._user_edited_name = False
        self.combo_preset.blockSignals(False)

    def _save_theme(self):
        try:
            theme_name = self.input_theme_name.text().strip()

            is_user_theme = (theme_name
                             and not is_builtin_preset(theme_name)
                             and self._user_edited_name)
            if is_user_theme:
                save_user_theme(theme_name, self._theme_data)

            T.clear()
            T.update(self._theme_data)

            save_theme()

            main_win = self.parent().window() if self.parent() else None
            if main_win and hasattr(main_win, "refresh_theme"):
                main_win.refresh_theme()

            from core.theme import _refresh_callbacks
            for cb in _refresh_callbacks[:]:
                try:
                    cb()
                except Exception:
                    pass

            self._refresh_own_styles()
            self._rebuild_preset_combo()
            self._detect_current_preset()
            self._take_snapshot()

            # Grüner Border NACH refresh (sonst wird er sofort überschrieben)
            self._btn_save.setStyleSheet(self._save_ok)
            QTimer.singleShot(2000, lambda: self._btn_save.setStyleSheet(self._save_default))

        except Exception as e:
            print(f"Theme save Fehler: {e}")

    def _delete_theme(self):
        theme_name = self.input_theme_name.text().strip()
        if not theme_name or is_builtin_preset(theme_name):
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Theme löschen")
        msg.setText(f'Theme "{theme_name}" wirklich löschen?')
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        msg.button(QMessageBox.Yes).setText("Ja, löschen")
        msg.button(QMessageBox.No).setText("Nein")

        if msg.exec() == QMessageBox.Yes:
            delete_user_theme(theme_name)
            self._clear_name_silent()
            self._user_edited_name = False
            self._hide_delete_btn()
            self._rebuild_preset_combo()
            self.combo_preset.setCurrentIndex(0)

    def _refresh_own_styles(self):
        """Theme Editor Panel + Labels mit neuen Farben aktualisieren."""
        self._apply_panel_style()
        if not getattr(self, '_init_done', False):
            return
        self._title_lbl.setStyleSheet(f"color: {T['text']}; font-size: 16px; font-weight: bold; border: none;")
        self._preset_lbl.setStyleSheet(f"color: {T['text_secondary']}; font-size: 12px; border: none;")
        self._color_name_lbl.setStyleSheet(f"color: {T['text']}; font-size: 14px; font-weight: bold; border: none;")
        for key in self._color_rows:
            self._update_color_row(key, selected=(key == self._selected_key))
        self._update_edit_icons()
        if hasattr(self, '_btn_presets'):
            self._update_arrow_icon(self._btn_presets)
            self._btn_presets.setStyleSheet(f"""
                QPushButton {{ background: {T['bg_mid']};
                    border: 1px solid {T['border']}; border-radius: 5px; }}
                QPushButton:hover {{ border-color: {T['accent']}; }}
            """)
        self.input_theme_name.setStyleSheet(f"""
            QLineEdit {{ background-color: {T['bg_mid']}; color: {T['text_secondary']};
                        border: 1px solid {T['border']}; border-radius: 5px;
                        padding: 4px 8px; font-size: 12px; }}
        """)
        # Tabs
        if hasattr(self, '_tab_buttons'):
            self._apply_tab_styles()
        if hasattr(self, '_smeter_style_rows'):
            self._update_smeter_list_styles()
        if hasattr(self, '_tab_digi'):
            self._tab_digi.refresh_theme()
        # S-Meter Style Dropdown
        if hasattr(self, '_smeter_lbl'):
            self._smeter_lbl.setStyleSheet(f"color: {T['text_secondary']}; font-size: 11px; border: none;")
        if hasattr(self, 'combo_smeter_style'):
            self.combo_smeter_style.setStyleSheet(f"""
                QComboBox {{ background-color: {T['bg_mid']}; color: {T['text_secondary']};
                    border: 1px solid {T['border']}; border-radius: 5px;
                    padding: 4px 8px; font-size: 11px; min-height: 24px; }}
                QComboBox::drop-down {{ border: none; width: 20px; }}
                QComboBox QAbstractItemView {{ background-color: {T['bg_mid']}; color: {T['text_secondary']};
                    selection-background-color: {T['bg_light']}; border: 1px solid {T['border']}; }}""")
        self._delete_style = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['error']};
                          border-radius: 5px; padding: 5px; color: {T['error']};
                          font-weight: bold; font-size: 14px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; }}"""
        self.btn_delete.setStyleSheet(self._delete_style)
        self._save_default = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['border']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['border_hover']}; }}"""
        self._save_ok = f"""
            QPushButton {{ background-color: {T['bg_mid']}; border: 2px solid {T['accent']};
                          border-radius: 5px; padding: 5px; }}
            QPushButton:hover {{ background-color: {T['bg_light']}; border-color: {T['accent']}; }}"""
        self._btn_save.setStyleSheet(self._save_default)
        self._btn_save.setIcon(themed_icon(os.path.join(_ICONS, "save.svg")))
        self.combo_preset.setStyleSheet(f"""
            QComboBox {{
                background-color: {T['bg_mid']};
                color: {T['text_secondary']};
                border: 1px solid {T['border']};
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 12px;
                min-height: 28px;
            }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{
                background-color: {T['bg_mid']};
                color: {T['text_secondary']};
                selection-background-color: {T['bg_light']};
                border: 1px solid {T['border']};
            }}
        """)

    def show_overlay(self):
        if not getattr(self, '_init_done', False):
            print("ThemeEditor: show_overlay abgebrochen — Init nicht fertig!")
            return
        parent = self.parent()
        self.setGeometry(parent.rect())
        pw = min(500, int(parent.width() * 0.6))
        ph = min(580, int(parent.height() * 0.9))
        self.panel.setFixedSize(pw, ph)
        self.panel.move((self.width() - pw) // 2, (self.height() - ph) // 2)
        self._refresh_own_styles()
        self._load_theme()
        self._take_snapshot()
        self._rebuild_preset_combo()
        self._detect_current_preset()
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
            pw = min(500, int(parent.width() * 0.6))
            ph = min(580, int(parent.height() * 0.9))
            self.panel.setFixedSize(pw, ph)
            self.panel.move((self.width() - pw) // 2, (self.height() - ph) // 2)
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
