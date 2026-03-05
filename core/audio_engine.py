import pygame
import sounddevice as sd
import numpy as np
import re
import os
import soundfile as sf
import time
import threading


class AudioEngine:
    def __init__(self, parent):
        self.p = parent
        if not pygame.mixer.get_init():
            pygame.mixer.init()

        self.recorded_frames = []
        self.is_recording = False
        self.rec_stream = None
        self.playback_thread = None
        self.playback_lock = threading.Lock()

        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.temp_file = os.path.join(script_dir, "temp_rec.wav")

    def get_pygame_device_name(self, full_name):
        """Extrahiert den reinen Namen für Pygame (entfernt [ID])."""
        if not full_name:
            return None
        return re.sub(r'^\[\d+\]\s*', '', full_name).strip()

    def play_test_wave(self, file_path, device_name):
        """DEIN FUNKTIONIERENDER TEIL - FINGER WEG."""
        if not os.path.exists(file_path):
            print("WAV Datei nicht gefunden!")
            return False
        try:
            pygame.mixer.quit()
            py_dev = self.get_pygame_device_name(device_name)
            pygame.mixer.init(devicename=py_dev)
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            return True
        except Exception as e:
            print(f"Pygame Playback Fehler: {e}")
            return False

    def _find_device_index(self, device_name, need_input=False, need_output=False):
        if not device_name:
            raise ValueError("Kein Gerätename gesetzt.")

        clean_search = re.sub(r'^\[\d+\]\s*', '', device_name).strip().lower()
        for i, d in enumerate(sd.query_devices()):
            name = d.get('name', '').lower()
            if clean_search in name:
                if need_input and d.get('max_input_channels', 0) <= 0:
                    continue
                if need_output and d.get('max_output_channels', 0) <= 0:
                    continue
                return i, d
        raise ValueError(f"Gerät nicht gefunden oder unpassend: {device_name}")

    def check_input_device(self):
        """Prüft das Mikrofon vor dem Start."""
        try:
            _, device_info = self._find_device_index(self.p.pc_mic.get(), need_input=True)
            print(f"🔍 Hardware-Check: {device_info['name']}")
            return True
        except Exception as e:
            print(f"❌ Mikrofon-Check fehlgeschlagen: {e}")
            return False

    def _record_callback(self, indata, frames, time_info, status):
        if status:
            print(f"⚠️ Aufnahme-Status: {status}")
        if self.is_recording:
            self.recorded_frames.append(indata.copy())

    def _stop_playback_and_release_file(self):
        """Stoppt laufende Wiedergabe und gibt temp_rec.wav sicher frei."""
        with self.playback_lock:
            try:
                if pygame.mixer.get_init():
                    try:
                        pygame.mixer.music.stop()
                    except Exception:
                        pass

                    # Kleiner Moment, damit SDL/Windows das Handle freigibt
                    time.sleep(0.15)

                    try:
                        pygame.mixer.music.unload()
                    except Exception:
                        pass

                    time.sleep(0.15)

                    try:
                        pygame.mixer.quit()
                    except Exception:
                        pass
            except Exception:
                pass

            # Windows braucht manchmal noch einen kleinen Moment
            for _ in range(10):
                try:
                    if os.path.exists(self.temp_file):
                        os.remove(self.temp_file)
                    break
                except PermissionError:
                    time.sleep(0.2)
                except Exception:
                    break

    def start_ram_record(self):
        """Startet eine EIGENE Mikrofonaufnahme nur für den REC-Button."""
        if self.is_recording:
            print("⚠️ Aufnahme läuft bereits.")
            return

        if not self.check_input_device():
            return

        # Falls noch Wiedergabe vom letzten Test läuft oder die Datei noch existiert:
        self._stop_playback_and_release_file()

        try:
            dev_index, dev_info = self._find_device_index(self.p.pc_mic.get(), need_input=True)
            fs = int(self.p.mic_sr.get())
            ch = int(self.p.mic_ch.get())
            max_in = int(dev_info.get('max_input_channels', 0))

            if ch > max_in:
                print(f"⚠️ Konfigurierter Kanalwert {ch} ist zu hoch, nutze stattdessen {max_in}.")
                ch = max_in

            self.recorded_frames = []
            self.is_recording = True
            self.rec_stream = sd.InputStream(
                device=dev_index,
                samplerate=fs,
                channels=ch,
                dtype='float32',
                blocksize=1024,
                callback=self._record_callback,
            )
            self.rec_stream.start()
            print(f"🔴 Aufnahme läuft: {dev_info['name']} | {fs} Hz | {ch} Ch")
        except Exception as e:
            self.is_recording = False
            self.recorded_frames = []
            self.rec_stream = None
            print(f"❌ Fehler beim Starten der Aufnahme: {e}")

    def add_stream_data(self, data):
        """Bestehender Pfad bleibt erhalten für spätere CONNECT-/TRX-Logik."""
        if self.is_recording:
            self.recorded_frames.append(data.copy())

    def stop_and_play_ram(self):
        """Stoppt NUR den REC-Teststream, schreibt WAV und spielt automatisch ab."""
        was_recording = self.is_recording
        self.is_recording = False

        if self.rec_stream is not None:
            try:
                self.rec_stream.stop()
                self.rec_stream.close()
            except Exception:
                pass
            self.rec_stream = None

        if not was_recording:
            print("⚠️ Es lief keine Aufnahme.")
            return

        if not self.recorded_frames:
            print("❌ Keine Daten empfangen!")
            return

        try:
            # Sicherstellen, dass alte Playback-Handles weg sind
            self._stop_playback_and_release_file()

            full_audio = np.concatenate(self.recorded_frames, axis=0)
            fs = int(self.p.mic_sr.get())
            py_dev = self.get_pygame_device_name(self.p.pc_spk.get())

            sf.write(self.temp_file, full_audio, fs, format='WAV')
            print(f"✅ Datei gespeichert: {os.path.basename(self.temp_file)}")

            time.sleep(0.15)

            pygame.mixer.init(frequency=fs, devicename=py_dev)
            pygame.mixer.music.load(self.temp_file)
            pygame.mixer.music.play()

            self.playback_thread = threading.Thread(target=self._wait_and_delete, daemon=True)
            self.playback_thread.start()
        except Exception as e:
            print(f"❌ Fehler beim Finalisieren/Wiedergeben: {e}")
        finally:
            self.recorded_frames = []

    def _wait_and_delete(self):
        try:
            while pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                time.sleep(0.2)
        except Exception:
            pass
        self._stop_playback_and_release_file()

    def open_stream_with_fallback(self, device_name, direction, callback, channels, samplerate):
        """Öffnet passend zur GUI-Semantik echte Input-/Output-Streams für RX/TX."""
        try:
            ch = int(channels)
            sr = int(samplerate)

            if direction == "input":
                dev_index, dev_info = self._find_device_index(device_name, need_input=True)
                max_in = int(dev_info.get('max_input_channels', 0))
                if max_in <= 0:
                    raise ValueError(f"Gerät hat keinen Eingang: {dev_info['name']}")
                if ch > max_in:
                    print(f"⚠️ {dev_info['name']}: Eingang {ch} Ch nicht möglich, nutze {max_in} Ch")
                    ch = max_in
                print(f"🎙️ INPUT geöffnet: {dev_info['name']} | {sr} Hz | {ch} Ch")
                return sd.InputStream(
                    device=dev_index,
                    samplerate=sr,
                    channels=ch,
                    dtype='float32',
                    blocksize=1024,
                    callback=callback,
                )

            if direction == "output":
                dev_index, dev_info = self._find_device_index(device_name, need_output=True)
                max_out = int(dev_info.get('max_output_channels', 0))
                if max_out <= 0:
                    raise ValueError(f"Gerät hat keinen Ausgang: {dev_info['name']}")
                if ch > max_out:
                    print(f"⚠️ {dev_info['name']}: Ausgang {ch} Ch nicht möglich, nutze {max_out} Ch")
                    ch = max_out
                print(f"🔊 OUTPUT geöffnet: {dev_info['name']} | {sr} Hz | {ch} Ch")
                return sd.OutputStream(
                    device=dev_index,
                    samplerate=sr,
                    channels=ch,
                    dtype='float32',
                    blocksize=1024,
                )

            raise ValueError(f"Unbekannte Richtung: {direction}")
        except Exception as e:
            print(f"❌ Stream-Open Fehler ({direction}) für {device_name}: {e}")
            return None

    def calculate_s_meter(self, data):
        """DEIN FUNKTIONIERENDER TEIL - FINGER WEG."""
        mag = np.sqrt(np.mean(data**2)) * 5.0
        s = max(0, min(9, int(mag * 9)))
        return min(mag, 1.0), s
