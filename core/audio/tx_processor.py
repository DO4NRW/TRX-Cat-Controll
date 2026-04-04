"""
TX Audio-Prozessor für RigLink (AP-02 Noise Gate, AP-03 Kompressor)
====================================================================
Kombinierte Pipeline für TX-Audio:
    pw-cat --record → EQProcessor → NoiseGate → Compressor → pw-cat --playback

Alle Prozessoren sind zustandsbehaftet und block-weise aufrufbar.
Blockgröße empfohlen: 256–512 Samples @ 48 kHz (~5–10 ms Latenz).

Verwendung:
    pipeline = TxPipeline(sample_rate=48000)
    pipeline.gate.threshold_db = -40.0
    pipeline.comp.threshold_db = -18.0
    out = pipeline.process(block)          # numpy float32/float64

    # Aus Config laden / in Config speichern:
    pipeline.load_config(rig_config['tx_processor'])
    cfg = pipeline.dump_config()
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from core.audio.eq import EQProcessor


# ─────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────────────────────

def _db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)

def _lin_to_db(lin: float) -> float:
    return 20.0 * math.log10(max(lin, 1e-10))

def _rms_db(block: np.ndarray) -> float:
    """RMS-Pegel eines Blocks in dBFS."""
    rms = math.sqrt(float(np.mean(block.astype(np.float64) ** 2)))
    return _lin_to_db(rms)

def _smooth_coeff(time_ms: float, sample_rate: int) -> float:
    """Glättungskoeffizient für Attack/Release (1. Ordnung IIR)."""
    if time_ms <= 0:
        return 0.0
    tau = time_ms / 1000.0
    return math.exp(-1.0 / (tau * sample_rate))


# ─────────────────────────────────────────────────────────────────────────────
# Noise Gate  (AP-02)
# ─────────────────────────────────────────────────────────────────────────────

class NoiseGate:
    """
    Noise Gate — dämpft das Signal wenn der Pegel unter den Threshold fällt.

    Zustand: open (Signal durch) / closed (Signal gedämpft).
    Attack/Hold/Release verhindern abrupte Übergänge.

    Parameter
    ---------
    threshold_db : float   Öffnungs-Schwelle in dBFS (z.B. -40.0)
    ratio        : float   Dämpfungsverhältnis wenn geschlossen (1.0 = hart, 4.0 = sanft)
    attack_ms    : float   Zeit bis Gate vollständig öffnet
    hold_ms      : float   Haltezeit nach Unterschreiten der Schwelle
    release_ms   : float   Zeit bis Gate vollständig schließt
    """

    def __init__(self, sample_rate: int = 48000):
        self._sr            = sample_rate
        self.threshold_db   = -40.0
        self.ratio          = 10.0      # Dämpfung: 10:1 → ~-20 dB unter Schwelle
        self.attack_ms      = 5.0
        self.hold_ms        = 50.0
        self.release_ms     = 100.0
        self.enabled        = True

        # Interner Zustand
        self._gain          = 0.0       # Aktueller Gain (0.0–1.0 linear)
        self._hold_samples  = 0         # Verbleibende Hold-Samples

    def reset(self):
        self._gain         = 0.0
        self._hold_samples = 0

    def set_sample_rate(self, sr: int):
        self._sr = sr

    def process(self, block: np.ndarray) -> np.ndarray:
        """
        Block durch das Noise Gate führen.
        Input/Output: float64-Array (mono).
        Gibt neues Array zurück — kein In-Place.
        """
        if not self.enabled:
            return block

        data = block.astype(np.float64)
        out  = np.empty_like(data)

        # Koeffizienten (pro Block neu, da Parameter änderbar)
        a_attack  = _smooth_coeff(self.attack_ms,   self._sr)
        a_release = _smooth_coeff(self.release_ms,  self._sr)
        thr_lin   = _db_to_lin(self.threshold_db)
        hold_samp = int(self.hold_ms * self._sr / 1000.0)

        gain = self._gain
        hold = self._hold_samples

        # Vectorized envelope: abs(x) geglättet mit Attack
        env = np.abs(data)
        # Einfaches Peak-Follower über den Block
        for i in range(1, len(env)):
            if env[i] >= thr_lin:
                env[i] = a_attack * env[i-1] + (1 - a_attack) * env[i]
            else:
                env[i] = a_release * env[i-1] + (1 - a_release) * env[i]

        # Gain-Kurve: über/unter Schwelle
        min_gain = 1.0 / self.ratio
        gain_curve = np.where(env >= thr_lin, 1.0, min_gain)

        # Gain glätten (Attack/Release per Sample — numpy-Schleife vermeiden
        # durch Kompromiss: Gain wird pro Block auf Zielwert gezogen)
        target_mean = float(np.mean(gain_curve))
        if target_mean > gain:
            coeff = 1.0 - a_attack
        else:
            coeff = 1.0 - a_release
        gain = gain + coeff * (target_mean - gain)

        out = data * gain_curve
        self._gain         = gain
        self._hold_samples = 0
        return out

    @property
    def gain_db(self) -> float:
        """Aktueller Gate-Gain in dB (für Anzeige)."""
        return _lin_to_db(self._gain)

    def load(self, cfg: dict):
        self.threshold_db = float(cfg.get('threshold_db', self.threshold_db))
        self.ratio        = float(cfg.get('ratio',        self.ratio))
        self.attack_ms    = float(cfg.get('attack_ms',    self.attack_ms))
        self.hold_ms      = float(cfg.get('hold_ms',      self.hold_ms))
        self.release_ms   = float(cfg.get('release_ms',   self.release_ms))
        self.enabled      = bool( cfg.get('enabled',      self.enabled))

    def dump(self) -> dict:
        return {
            'threshold_db': self.threshold_db,
            'ratio':        self.ratio,
            'attack_ms':    self.attack_ms,
            'hold_ms':      self.hold_ms,
            'release_ms':   self.release_ms,
            'enabled':      self.enabled,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Kompressor  (AP-03)
# ─────────────────────────────────────────────────────────────────────────────

class Compressor:
    """
    Feed-Forward-Kompressor — gleichmäßiger TX-Sendepegel.

    Architektur: Level Detection → Gain Computer → Smoothing → Makeup Gain.

    Parameter
    ---------
    threshold_db : float   Ab welchem Pegel wird komprimiert (z.B. -18.0)
    ratio        : float   Kompressionsverhältnis (z.B. 4.0 = 4:1)
    knee_db      : float   Soft-Knee-Breite (0.0 = hart, 6.0 = sanft)
    attack_ms    : float   Ansprechzeit
    release_ms   : float   Rückfallzeit
    makeup_db    : float   Makeup-Gain nach Kompression in dB
    rms_ms       : float   RMS-Integrationszeitkonstante (0 = Peak-Detection)
    """

    def __init__(self, sample_rate: int = 48000):
        self._sr           = sample_rate
        self.threshold_db  = -18.0
        self.ratio         = 4.0
        self.knee_db       = 6.0
        self.attack_ms     = 10.0
        self.release_ms    = 100.0
        self.makeup_db     = 0.0
        self.rms_ms        = 10.0
        self.enabled       = True
        self.limit         = True       # True = Limiter bei 0 dBFS aktiv

        # Interner Zustand
        self._env_lin     = 0.0        # Envelope-Detektor (linear)
        self._gain_db     = 0.0        # Geglätteter Gain in dB

    def reset(self):
        self._env_lin  = 0.0
        self._gain_db  = 0.0

    def set_sample_rate(self, sr: int):
        self._sr = sr

    def _gain_computer(self, level_db: float) -> float:
        """
        Berechnet den Gain-Reduction-Wert in dB für einen gegebenen Eingangspegel.
        Implementiert Soft-Knee gemäß AES-Standard.
        """
        thr   = self.threshold_db
        ratio = self.ratio
        knee  = self.knee_db
        knee2 = knee / 2.0

        if knee > 0 and level_db > thr - knee2 and level_db < thr + knee2:
            # Soft-Knee-Bereich
            x = (level_db - thr + knee2) / knee
            gr = (1.0 / ratio - 1.0) * (x ** 2) * knee / 2.0
        elif level_db <= thr - knee2:
            # Unterhalb Schwelle: kein Gain Reduction
            gr = 0.0
        else:
            # Oberhalb Schwelle: volle Kompression
            gr = (level_db - thr) * (1.0 / ratio - 1.0)

        return gr  # negativ = Dämpfung

    def process(self, block: np.ndarray) -> np.ndarray:
        """
        Block komprimieren.
        Input/Output: float64-Array (mono).
        """
        if not self.enabled:
            return block

        data = block.astype(np.float64)
        out  = np.empty_like(data)

        a_rms     = _smooth_coeff(self.rms_ms,     self._sr) if self.rms_ms > 0 else 0.0
        a_attack  = _smooth_coeff(self.attack_ms,  self._sr)
        a_release = _smooth_coeff(self.release_ms, self._sr)
        makeup    = _db_to_lin(self.makeup_db)

        env   = self._env_lin
        g_db  = self._gain_db

        # RMS-Envelope über den gesamten Block (numpy)
        if a_rms > 0:
            sq = data * data
            # Rekursiver IIR via lfilter-Approximation: einmalig über Block
            rms_val = math.sqrt(float(a_rms * self._env_lin +
                                      (1.0 - a_rms) * float(np.mean(sq))))
            env = rms_val
        else:
            peak = float(np.max(np.abs(data)))
            if peak > self._env_lin:
                env = peak
            else:
                env = a_release * self._env_lin + (1.0 - a_release) * peak

        level_db = _lin_to_db(max(env, 1e-10))
        gr_db    = self._gain_computer(level_db)

        # Gain Smoothing (Attack/Release, pro Block)
        if gr_db < g_db:
            coeff = 1.0 - a_attack
        else:
            coeff = 1.0 - a_release
        g_db = g_db + coeff * (gr_db - g_db)

        # Gain auf Block anwenden
        gain_lin = _db_to_lin(g_db) * makeup
        out = data * gain_lin

        if self.limit:
            np.clip(out, -1.0, 1.0, out=out)

        self._env_lin = env
        self._gain_db = g_db
        return out

    @property
    def gain_reduction_db(self) -> float:
        """Aktuelle Gain Reduction in dB (für GR-Meter, immer ≤ 0)."""
        return self._gain_db

    def load(self, cfg: dict):
        self.threshold_db = float(cfg.get('threshold_db', self.threshold_db))
        self.ratio        = float(cfg.get('ratio',        self.ratio))
        self.knee_db      = float(cfg.get('knee_db',      self.knee_db))
        self.attack_ms    = float(cfg.get('attack_ms',    self.attack_ms))
        self.release_ms   = float(cfg.get('release_ms',   self.release_ms))
        self.makeup_db    = float(cfg.get('makeup_db',    self.makeup_db))
        self.rms_ms       = float(cfg.get('rms_ms',       self.rms_ms))
        self.enabled      = bool( cfg.get('enabled',      self.enabled))
        self.limit        = bool( cfg.get('limit',        self.limit))

    def dump(self) -> dict:
        return {
            'threshold_db': self.threshold_db,
            'ratio':        self.ratio,
            'knee_db':      self.knee_db,
            'attack_ms':    self.attack_ms,
            'release_ms':   self.release_ms,
            'makeup_db':    self.makeup_db,
            'rms_ms':       self.rms_ms,
            'enabled':      self.enabled,
            'limit':        self.limit,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Kombinierte TX-Pipeline
# ─────────────────────────────────────────────────────────────────────────────

class TxPipeline:
    """
    Kombinierte TX Audio-Pipeline:  EQ → Noise Gate → Kompressor

    Reihenfolge bewusst gewählt:
    - EQ zuerst: Mic-Klang formen bevor Gate/Comp entscheiden
    - Gate vor Kompressor: Rauschen raus bevor Comp es hochzieht
    - Kompressor am Ende: Gleichmäßiger Pegel für Sender

    Verwendung mit pw-cat:
        pipeline = TxPipeline(sample_rate=48000)
        # In pw-cat-Loop:
        block_in  = np.frombuffer(proc.stdout.read(BLOCK_SIZE * 4), np.float32)
        block_out = pipeline.process(block_in)
        proc2.stdin.write(block_out.astype(np.float32).tobytes())
    """

    # Standard-Blockgröße (256 Samples @ 48 kHz ≈ 5,3 ms)
    DEFAULT_BLOCK = 256

    def __init__(self, sample_rate: int = 48000):
        self._sr        = sample_rate
        self.eq         = EQProcessor(sample_rate)
        self.gate       = NoiseGate(sample_rate)
        self.comp       = Compressor(sample_rate)
        self._bypass    = False

        # Standard-Einstellungen für SSB-TX
        self._apply_defaults()

    def _apply_defaults(self):
        """Sinnvolle Startwerte für SSB-TX."""
        # EQ: Tiefen absenken (Mic-Brummen), leichte Höhenanhebung (Verständlichkeit)
        self.eq.set_gain(31.0,   -6.0)
        self.eq.set_gain(63.0,   -4.0)
        self.eq.set_gain(125.0,  -2.0)
        self.eq.set_gain(8000.0, +2.0)

        # Gate: Raumgeräusche unter -40 dBFS sperren
        self.gate.threshold_db = -40.0
        self.gate.attack_ms    = 5.0
        self.gate.hold_ms      = 60.0
        self.gate.release_ms   = 120.0
        self.gate.ratio        = 10.0

        # Kompressor: Moderates 4:1 Verhältnis, 10 ms Attack
        self.comp.threshold_db = -18.0
        self.comp.ratio        = 4.0
        self.comp.knee_db      = 6.0
        self.comp.attack_ms    = 10.0
        self.comp.release_ms   = 80.0
        self.comp.makeup_db    = 4.0
        self.comp.limit        = True

    # ── Verarbeitung ─────────────────────────────────────────────────────────

    def process(self, block: np.ndarray) -> np.ndarray:
        """
        Block durch die gesamte TX-Pipeline führen.
        Input: float32 oder float64, mono (1D).
        Output: gleicher dtype wie Input.
        """
        if self._bypass:
            return block

        dtype = block.dtype
        data  = block.astype(np.float64)

        # 1. EQ
        data = self.eq.process(data)

        # 2. Noise Gate
        data = self.gate.process(data)

        # 3. Kompressor
        data = self.comp.process(data)

        return data.astype(dtype)

    def process_interleaved(self, raw: bytes,
                             in_dtype=np.float32) -> bytes:
        """
        Convenience-Methode für pw-cat Byte-Streams.
        Liest float32-Bytes, verarbeitet, gibt float32-Bytes zurück.
        """
        block = np.frombuffer(raw, dtype=in_dtype).copy()
        out   = self.process(block)
        return out.astype(in_dtype).tobytes()

    # ── Status ───────────────────────────────────────────────────────────────

    @property
    def bypass(self) -> bool:
        return self._bypass

    @bypass.setter
    def bypass(self, v: bool):
        self._bypass = v

    def reset(self):
        """Alle internen Zustände zurücksetzen (nach PTT-Off sinnvoll)."""
        self.eq._rebuild_all()
        self.gate.reset()
        self.comp.reset()

    def set_sample_rate(self, sr: int):
        """Samplerate aller Stufen aktualisieren."""
        self._sr = sr
        self.eq.set_sample_rate(sr)
        self.gate.set_sample_rate(sr)
        self.comp.set_sample_rate(sr)

    # ── Config-Serialisierung ─────────────────────────────────────────────────

    def load_config(self, cfg: dict):
        """
        Aus Rig-Config laden.
        Erwartet: cfg['tx_processor'] = {'eq': [...], 'gate': {...}, 'comp': {...}}
        """
        if not cfg:
            return
        if 'eq' in cfg:
            gains = cfg['eq']
            if isinstance(gains, list):
                for idx, g in enumerate(gains):
                    self.eq.set_gain_by_index(idx, float(g))
        if 'gate' in cfg:
            self.gate.load(cfg['gate'])
        if 'comp' in cfg:
            self.comp.load(cfg['comp'])
        if 'bypass' in cfg:
            self._bypass = bool(cfg['bypass'])

    def dump_config(self) -> dict:
        """
        Aktuelle Einstellungen als dict (für Rig-Config).
        Speichern: rig_config['tx_processor'] = pipeline.dump_config()
        """
        return {
            'eq':     self.eq.get_gains(),
            'gate':   self.gate.dump(),
            'comp':   self.comp.dump(),
            'bypass': self._bypass,
        }

    # ── Metering ─────────────────────────────────────────────────────────────

    def get_metering(self) -> dict:
        """
        Aktuelle Meter-Werte für GUI.
        Rückgabe: {'gate_db': float, 'gain_reduction_db': float}
        """
        return {
            'gate_db':           self.gate.gain_db,
            'gain_reduction_db': self.comp.gain_reduction_db,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Selbsttest
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import time as _time

    print("TxPipeline Selbsttest")
    print("=" * 40)

    SR   = 48000
    BLOK = 256
    pipe = TxPipeline(sample_rate=SR)

    # --- Noise Gate Test ---
    print("\n[1] Noise Gate")
    # Stilles Signal (Rauschen bei -60 dBFS) → Gate zu
    noise = np.random.randn(BLOK).astype(np.float64) * _db_to_lin(-60)
    pipe.gate.reset()
    out_quiet = pipe.gate.process(noise)
    rms_in  = _rms_db(noise)
    rms_out = _rms_db(out_quiet)
    print(f"  Stilles Signal: {rms_in:.1f} dBFS rein → {rms_out:.1f} dBFS raus")
    assert rms_out < rms_in, "Gate sollte dämpfen"

    # Lautes Signal (-10 dBFS) → Gate auf
    speech = np.random.randn(BLOK).astype(np.float64) * _db_to_lin(-10)
    # Mehrere Blöcke damit Gate Zeit hat zu öffnen
    pipe.gate.reset()
    for _ in range(20):
        out_loud = pipe.gate.process(speech)
    rms_loud = _rms_db(out_loud)
    print(f"  Lautes Signal:  {_rms_db(speech):.1f} dBFS rein → {rms_loud:.1f} dBFS raus (Gate offen)")
    assert rms_loud > -30, "Gate sollte Signal durchlassen"

    # --- Kompressor Test ---
    print("\n[2] Kompressor")
    pipe.comp.reset()
    pipe.comp.threshold_db = -20.0
    pipe.comp.ratio        = 4.0
    pipe.comp.makeup_db    = 0.0

    # Leiseres Signal → kaum GR
    quiet = np.random.randn(BLOK).astype(np.float64) * _db_to_lin(-30)
    for _ in range(10):
        pipe.comp.process(quiet)
    gr_quiet = pipe.comp.gain_reduction_db
    print(f"  Leises Signal (-30 dBFS): GR = {gr_quiet:.2f} dB")

    # Lautes Signal → deutliche GR
    loud = np.random.randn(BLOK).astype(np.float64) * _db_to_lin(-10)
    for _ in range(30):
        pipe.comp.process(loud)
    gr_loud = pipe.comp.gain_reduction_db
    print(f"  Lautes Signal  (-10 dBFS): GR = {gr_loud:.2f} dB")
    assert gr_loud < gr_quiet, "Kompressor sollte mehr GR bei lautem Signal haben"

    # --- Pipeline Durchlauf ---
    print("\n[3] Komplette Pipeline")
    pipe.reset()
    t0 = _time.perf_counter()
    signal = np.random.randn(SR).astype(np.float32) * 0.1  # 1s @ 48 kHz
    n_blocks = len(signal) // BLOK
    for i in range(n_blocks):
        blk = signal[i*BLOK:(i+1)*BLOK]
        pipe.process(blk)
    elapsed = _time.perf_counter() - t0
    ratio = 1.0 / elapsed
    print(f"  {n_blocks} Blöcke à {BLOK} ({SR}Hz): {elapsed*1000:.1f} ms ({ratio:.0f}× Echtzeit)")
    assert ratio > 5, "Pipeline muss mindestens 5× Echtzeit schaffen"

    # --- Config Round-Trip ---
    print("\n[4] Config-Serialisierung")
    cfg = pipe.dump_config()
    assert 'eq' in cfg and 'gate' in cfg and 'comp' in cfg
    pipe2 = TxPipeline(SR)
    pipe2.load_config(cfg)
    cfg2 = pipe2.dump_config()
    assert cfg['gate']['threshold_db'] == cfg2['gate']['threshold_db']
    assert cfg['comp']['ratio']        == cfg2['comp']['ratio']
    print(f"  Gate threshold: {cfg['gate']['threshold_db']} dB ✓")
    print(f"  Comp ratio:     {cfg['comp']['ratio']}:1 ✓")

    # --- Byte-Stream Interface ---
    print("\n[5] Byte-Stream Interface (pw-cat)")
    raw = (np.random.randn(BLOK).astype(np.float32) * 0.1).tobytes()
    result = pipe.process_interleaved(raw)
    assert len(result) == len(raw)
    print(f"  {len(raw)} Bytes rein → {len(result)} Bytes raus ✓")

    print("\nAlle Tests bestanden.")
