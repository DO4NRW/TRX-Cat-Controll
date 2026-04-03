"""Kompatibilitäts-Layer — alle Klassen leben jetzt in ui/.
Dieser Re-Export stellt sicher, dass 'from main_ui import X' weiterhin funktioniert."""

from ui import (
    MainWindow, MenuIconProxyStyle,
    RadioSetupOverlay, AudioSetupOverlay, DropDownComboBox,
    ThemeEditorOverlay, ToggleButton, ToggleGroup,
    _scan_rigs, _scan_rigs_map, _list_serial_ports,
    _pw_find_id_by_name, _list_audio_devices, _device_max_channels,
    _ICONS, _RIG_DIR, _THEME_PATH, _THEME_FIELDS,
)

if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
