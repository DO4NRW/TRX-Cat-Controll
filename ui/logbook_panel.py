"""
RigLink — Logbuch-Panel (ADIF)
QSO-Liste, Import/Export als .adi-Datei.
"""

import os

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QHeaderView, QFileDialog, QMessageBox, QSizePolicy)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont

from core.theme import T, register_refresh, themed_icon
from core.logbook.adif import ADIFLog, QSO
from ui._constants import _ICONS


# Spalten-Definitionen: (ADIF-Attribut, Anzeige-Label, Breite)
_COLUMNS = [
    ("qso_date", "Datum",   90),
    ("time_on",  "UTC",     60),
    ("call",     "Call",    100),
    ("band",     "Band",    55),
    ("mode",     "Mode",    65),
    ("rst_sent", "RST-S",   55),
    ("rst_rcvd", "RST-R",   55),
    ("name",     "Name",    80),
    ("comment",  "Kommentar", 150),
]


class LogbookOverlay(QWidget):
    """Overlay-Panel für das QSO-Logbuch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self._log = ADIFLog()
        self._build_ui()
        register_refresh(self.refresh_theme)

    # ── UI aufbauen ───────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(f"background-color: {T['bg_dark']};")
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        # Header
        header = QHBoxLayout()
        title = QLabel("Logbuch")
        title.setFont(QFont("Roboto", 16, QFont.Bold))
        title.setStyleSheet(f"color: {T['accent']}; border: none;")
        header.addWidget(title)
        header.addStretch()

        self._lbl_count = QLabel("0 QSOs")
        self._lbl_count.setStyleSheet(f"color: {T['text_muted']}; border: none; font-size: 12px;")
        header.addWidget(self._lbl_count)

        self.btn_import = QPushButton("Import ADIF")
        self.btn_import.setFixedHeight(34)
        self.btn_import.setFocusPolicy(Qt.NoFocus)
        self.btn_import.setStyleSheet(self._btn_style())
        self.btn_import.clicked.connect(self._on_import)
        header.addWidget(self.btn_import)

        self.btn_export = QPushButton("Export ADIF")
        self.btn_export.setFixedHeight(34)
        self.btn_export.setFocusPolicy(Qt.NoFocus)
        self.btn_export.setStyleSheet(self._btn_style())
        self.btn_export.clicked.connect(self._on_export)
        header.addWidget(self.btn_export)

        self.btn_close = QPushButton("Schließen")
        self.btn_close.setFixedHeight(34)
        self.btn_close.setFocusPolicy(Qt.NoFocus)
        self.btn_close.setStyleSheet(self._btn_style())
        self.btn_close.clicked.connect(self.hide)
        header.addWidget(self.btn_close)

        root.addLayout(header)

        # QSO-Tabelle
        self.table = QTableWidget()
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in _COLUMNS])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setFocusPolicy(Qt.NoFocus)

        for col, (_, _, width) in enumerate(_COLUMNS):
            self.table.setColumnWidth(col, width)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._apply_table_style()
        root.addWidget(self.table)

    # ── Import / Export ───────────────────────────────────────────────────────

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "ADIF importieren", "", "ADIF-Dateien (*.adi *.adif);;Alle Dateien (*)"
        )
        if not path:
            return
        loaded = self._log.load(path)
        self._refresh_table()
        QMessageBox.information(self, "Import", f"{loaded} QSOs importiert.")

    def _on_export(self):
        if self._log.count() == 0:
            QMessageBox.warning(self, "Export", "Keine QSOs zum Exportieren.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "ADIF exportieren", "logbook.adi", "ADIF-Dateien (*.adi);;Alle Dateien (*)"
        )
        if not path:
            return
        ok = self._log.save(path)
        if ok:
            QMessageBox.information(self, "Export", f"{self._log.count()} QSOs exportiert.")
        else:
            QMessageBox.critical(self, "Export", "Fehler beim Speichern.")

    # ── Tabelle befüllen ──────────────────────────────────────────────────────

    def _refresh_table(self):
        qsos = self._log.sorted_by_date()
        self.table.setRowCount(len(qsos))
        for row, qso in enumerate(qsos):
            for col, (attr, _, _) in enumerate(_COLUMNS):
                val = getattr(qso, attr, "") or ""
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)
        self._lbl_count.setText(f"{self._log.count()} QSOs")

    # ── Overlay-Verwaltung ────────────────────────────────────────────────────

    def show_overlay(self):
        self.setGeometry(self.parent().rect())
        self.setVisible(True)
        self.raise_()

    # ── Theme ─────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        self.setStyleSheet(f"background-color: {T['bg_dark']};")
        self._apply_table_style()
        for btn in [self.btn_import, self.btn_export, self.btn_close]:
            btn.setStyleSheet(self._btn_style())

    def _btn_style(self):
        return (f"QPushButton {{ background-color: {T['bg_mid']}; color: {T['text']}; "
                f"border: 1px solid {T['border']}; border-radius: 4px; padding: 4px 12px; font-size: 12px; }} "
                f"QPushButton:hover {{ border-color: {T['border_hover']}; background-color: {T['bg_light']}; }}")

    def _apply_table_style(self):
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {T['bg_mid']};
                color: {T['text']};
                border: 1px solid {T['border']};
                border-radius: 4px;
                gridline-color: {T['border']};
                alternate-background-color: {T['bg_dark']};
            }}
            QHeaderView::section {{
                background-color: {T['bg_light']};
                color: {T['text_muted']};
                border: none;
                border-bottom: 1px solid {T['border']};
                padding: 4px;
                font-size: 11px;
                font-weight: bold;
            }}
            QTableWidget::item:selected {{
                background-color: {T['bg_light']};
                color: {T['text']};
            }}
        """)
