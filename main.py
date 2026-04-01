import sys
from PySide6.QtWidgets import QApplication
from core.theme import load_theme, save_theme, get_last_theme, PRESETS, T

def main():
    app = QApplication(sys.argv)

    # Letztes Theme wiederherstellen BEVOR main_ui importiert wird
    # (weil main_ui beim Import Widgets baut die T lesen)
    last = get_last_theme()
    if last != "custom" and last in PRESETS:
        T.clear()
        T.update(PRESETS[last])
        save_theme()  # theme.json synchron halten

    from main_ui import MainWindow
    from core.status import StatusManager

    window = MainWindow()
    #StatusManager Start
    stat_mgr = StatusManager()
    text, color = stat_mgr.get_status_data("READY")
    window.status_label.setText(text.upper())
    window.status_label.setStyleSheet(window.status_label.styleSheet() + f"color:{color}; padding-left: 10px; font-family: Consolas;")


    window.show()

    # Auto-Update Check im Hintergrund
    from core.updater import UpdateChecker, show_update_dialog
    updater = UpdateChecker()
    updater.update_available.connect(
        lambda local, remote, changelog, url: show_update_dialog(window, local, remote, changelog, url))
    updater.check()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()

