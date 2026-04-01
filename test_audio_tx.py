"""Test: PTT + 1kHz Testton über TRX senden."""
import serial
import subprocess
import numpy as np
import time
import sys

PORT = "/dev/ttyUSB0"
BAUD = 38400
PTT_PORT = "/dev/ttyUSB1"
TRX_SPK = "alsa_output.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo"
DURATION = 5  # Sekunden

print("=== TX Audio Test ===")
print(f"PTT via RTS auf {PTT_PORT}")
print(f"Audio: 1kHz Testton → {TRX_SPK}")
print(f"Dauer: {DURATION}s")
print()

# 1kHz Testton generieren (s16, 44100Hz, mono)
sr = 44100
t = np.arange(int(sr * DURATION)) / sr
tone = (np.sin(2 * np.pi * 1000 * t) * 16000).astype(np.int16)
tone_bytes = tone.tobytes()

# PTT Port öffnen
ptt_ser = serial.Serial(PTT_PORT, 38400, timeout=0.5, rtscts=False, dsrdtr=False)
ptt_ser.setRTS(False)
ptt_ser.setDTR(False)
time.sleep(0.1)

print("PTT ON (RTS)...")
ptt_ser.setRTS(True)
time.sleep(0.3)

print("Sende 1kHz Testton...")
proc = subprocess.Popen(
    ["pw-cat", "--playback", "--target", TRX_SPK,
     "--format", "s16", "--rate", "44100", "--channels", "1", "-"],
    stdin=subprocess.PIPE
)
proc.stdin.write(tone_bytes)
proc.stdin.close()
proc.wait(timeout=DURATION + 2)

print("PTT OFF...")
ptt_ser.setRTS(False)
time.sleep(0.1)
ptt_ser.close()

print("Fertig! Hast du den Ton am anderen TRX gehört?")
