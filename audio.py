#!/usr/bin/env python3
"""
RigLink Audio — PCM2901 USB-Soundkarte erkennen und Streaming via ALSA/PipeWire.

Erkennt automatisch ob PCM2901 (oder andere USB-Audio) angeschlossen ist.
Nutzt pw-cat wenn PipeWire verfügbar, sonst arecord/aplay als ALSA-Fallback.
"""

import os
import re
import shutil
import subprocess
import threading
import logging
import time
from typing import Optional

log = logging.getLogger("riglink.audio")


# ── USB-Soundkarte erkennen ──────────────────────────────────────────────────

# Bekannte TRX-Soundkarten (USB Vendor:Product oder ALSA-Name)
KNOWN_CARDS = {
    "PCM2901":  "08bb:29b0",   # TI PCM2901 (typisch für IC-705 USB-Audio)
    "PCM2902":  "08bb:29c0",   # TI PCM2902
    "IC-705":   "0c26:002e",   # Icom IC-705 internes USB-Audio
    "USB Audio": None,          # Generischer Fallback
}


def find_usb_audio_card() -> Optional[dict]:
    """
    Sucht nach USB-Audio-Devices in ALSA.
    Gibt dict zurück: {name, card_num, device, hw_id} oder None.
    """
    try:
        # ALSA Capture-Devices auflisten
        out = subprocess.check_output(
            ["arecord", "-l"], text=True, timeout=3,
            stderr=subprocess.DEVNULL
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        log.warning("arecord nicht verfügbar")
        return None

    # Format: "card 1: CODEC [USB Audio CODEC], device 0: USB Audio [USB Audio]"
    for line in out.splitlines():
        m = re.match(r"card (\d+): (\S+) \[(.+?)\], device (\d+):", line)
        if m:
            card_num = int(m.group(1))
            card_id = m.group(2)
            card_name = m.group(3)
            device_num = int(m.group(4))
            hw_id = f"hw:{card_num},{device_num}"

            log.info("USB-Audio gefunden: %s (%s) → %s", card_name, card_id, hw_id)
            return {
                "name": card_name,
                "card_id": card_id,
                "card_num": card_num,
                "device_num": device_num,
                "hw_capture": hw_id,
                "hw_playback": f"hw:{card_num},0",
            }

    # Auch Playback-Devices prüfen (manche haben nur Output)
    try:
        out = subprocess.check_output(
            ["aplay", "-l"], text=True, timeout=3,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        return None

    for line in out.splitlines():
        m = re.match(r"card (\d+): (\S+) \[(.+?)\], device (\d+):", line)
        if m:
            card_name = m.group(3)
            # Nur USB-Audio, nicht die eingebauten
            if "USB" in card_name or "PCM29" in card_name or "CODEC" in card_name:
                card_num = int(m.group(1))
                return {
                    "name": card_name,
                    "card_id": m.group(2),
                    "card_num": card_num,
                    "device_num": int(m.group(4)),
                    "hw_capture": None,
                    "hw_playback": f"hw:{card_num},{m.group(4)}",
                }
    return None


def find_usb_audio_by_lsusb() -> Optional[str]:
    """Fallback: USB-Audio über lsusb erkennen."""
    try:
        out = subprocess.check_output(["lsusb"], text=True, timeout=3)
    except Exception:
        return None

    for name, vid_pid in KNOWN_CARDS.items():
        if vid_pid and vid_pid in out:
            return name
    # Generisch
    if "Audio" in out or "audio" in out:
        return "USB Audio (generisch)"
    return None


# ── Audio-Backend erkennen ───────────────────────────────────────────────────

def has_pipewire() -> bool:
    """Prüft ob PipeWire läuft."""
    return shutil.which("pw-cat") is not None and _pw_running()


def _pw_running() -> bool:
    try:
        subprocess.check_output(
            ["pw-cli", "info", "0"], text=True, timeout=2,
            stderr=subprocess.DEVNULL
        )
        return True
    except Exception:
        return False


def audio_backend() -> str:
    """Gibt das verfügbare Audio-Backend zurück: 'pipewire', 'alsa' oder 'none'."""
    if has_pipewire():
        return "pipewire"
    if shutil.which("arecord"):
        return "alsa"
    return "none"


# ── Audio-Streaming ──────────────────────────────────────────────────────────

class AudioStreamer:
    """
    Verwaltet RX-Audio (TRX → PC) und TX-Audio (PC → TRX) Streams.
    Nutzt pw-cat oder arecord/aplay je nach Backend.
    """

    def __init__(self):
        self._rx_proc: Optional[subprocess.Popen] = None
        self._tx_proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self.rx_active = False
        self.tx_active = False
        self.card_info: Optional[dict] = None
        self.backend = "none"

    def detect(self) -> dict:
        """Hardware und Backend erkennen. Gibt Status-Dict zurück."""
        self.card_info = find_usb_audio_card()
        self.backend = audio_backend()

        usb_name = None
        if not self.card_info:
            usb_name = find_usb_audio_by_lsusb()

        return {
            "card": self.card_info,
            "usb_detected": usb_name,
            "backend": self.backend,
            "rx_active": self.rx_active,
            "tx_active": self.tx_active,
        }

    def start_rx(self, output_file: str = "/tmp/riglink_rx.wav",
                 sample_rate: int = 48000, channels: int = 1) -> bool:
        """RX-Audio vom TRX aufnehmen (Capture)."""
        with self._lock:
            if self._rx_proc:
                log.warning("RX-Stream läuft bereits")
                return True

            if not self.card_info or not self.card_info.get("hw_capture"):
                log.error("Kein Capture-Device verfügbar")
                return False

            hw = self.card_info["hw_capture"]

            if self.backend == "pipewire":
                cmd = [
                    "pw-cat", "--record",
                    "--target", hw,
                    "--rate", str(sample_rate),
                    "--channels", str(channels),
                    "--format", "s16",
                    output_file,
                ]
            else:
                # ALSA-Fallback
                cmd = [
                    "arecord",
                    "-D", hw,
                    "-f", "S16_LE",
                    "-r", str(sample_rate),
                    "-c", str(channels),
                    "-t", "wav",
                    output_file,
                ]

            try:
                log.info("Starte RX-Stream: %s", " ".join(cmd))
                self._rx_proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
                self.rx_active = True
                return True
            except Exception as e:
                log.error("RX-Stream Start fehlgeschlagen: %s", e)
                return False

    def stop_rx(self):
        """RX-Stream beenden."""
        with self._lock:
            if self._rx_proc:
                self._rx_proc.terminate()
                try:
                    self._rx_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._rx_proc.kill()
                self._rx_proc = None
            self.rx_active = False
            log.info("RX-Stream beendet")

    def start_tx(self, input_file: str,
                 sample_rate: int = 48000, channels: int = 1) -> bool:
        """TX-Audio zum TRX abspielen (Playback)."""
        with self._lock:
            if self._tx_proc:
                log.warning("TX-Stream läuft bereits")
                return True

            if not self.card_info:
                log.error("Keine Soundkarte erkannt")
                return False

            hw = self.card_info.get("hw_playback", f"hw:{self.card_info['card_num']},0")

            if not os.path.exists(input_file):
                log.error("TX-Datei nicht gefunden: %s", input_file)
                return False

            if self.backend == "pipewire":
                cmd = [
                    "pw-cat", "--playback",
                    "--target", hw,
                    "--rate", str(sample_rate),
                    "--channels", str(channels),
                    "--format", "s16",
                    input_file,
                ]
            else:
                cmd = [
                    "aplay",
                    "-D", hw,
                    "-f", "S16_LE",
                    "-r", str(sample_rate),
                    "-c", str(channels),
                    input_file,
                ]

            try:
                log.info("Starte TX-Stream: %s", " ".join(cmd))
                self._tx_proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
                )
                self.tx_active = True
                return True
            except Exception as e:
                log.error("TX-Stream Start fehlgeschlagen: %s", e)
                return False

    def stop_tx(self):
        """TX-Stream beenden."""
        with self._lock:
            if self._tx_proc:
                self._tx_proc.terminate()
                try:
                    self._tx_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._tx_proc.kill()
                self._tx_proc = None
            self.tx_active = False
            log.info("TX-Stream beendet")

    def stop_all(self):
        """Alle Streams beenden."""
        self.stop_rx()
        self.stop_tx()

    def status(self) -> dict:
        """Aktueller Audio-Status für API."""
        # Prozesse prüfen (könnten inzwischen beendet sein)
        if self._rx_proc and self._rx_proc.poll() is not None:
            self._rx_proc = None
            self.rx_active = False
        if self._tx_proc and self._tx_proc.poll() is not None:
            self._tx_proc = None
            self.tx_active = False

        info = self.detect()
        return {
            "backend": self.backend,
            "card_name": self.card_info["name"] if self.card_info else None,
            "card_hw": self.card_info["hw_capture"] if self.card_info else None,
            "rx_active": self.rx_active,
            "tx_active": self.tx_active,
            "available": self.card_info is not None,
        }
