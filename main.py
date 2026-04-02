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

    from core.session_logger import start_session, had_crash, has_previous_log
    from main_ui import MainWindow
    from core.status import StatusManager

    # Crash-Check BEVOR neue Session startet
    _prev_crash = had_crash() and has_previous_log()

    # Neue Session starten (setzt clean_exit=False)
    start_session()

    window = MainWindow()
    #StatusManager Start
    stat_mgr = StatusManager()
    text, _ = stat_mgr.get_status_data("READY")
    window.status_label.setText(text.upper())
    window.status_label.setStyleSheet(f"color: {T['text']}; padding-left: 10px; font-family: Consolas;")


    window.show()

    # Crash-Report Dialog (wenn letzte Session abgestürzt ist)
    if _prev_crash:
        from core.reporter import show_crash_dialog
        show_crash_dialog(window)

    # Auto-Update Check im Hintergrund
    from core.updater import UpdateChecker, show_update_dialog
    updater = UpdateChecker()
    updater.update_available.connect(
        lambda local, remote, changelog, url: show_update_dialog(window, local, remote, changelog, url))
    updater.check()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()

