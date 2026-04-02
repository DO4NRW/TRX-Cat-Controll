"""
Importiert Icom Rig-Definitionen aus wfview .rig Files.
Erzeugt/updatet die features-Section in unseren config.json Files.

Usage: python tools/import_wfview_rigs.py
"""
import os, re, json

WFVIEW_RIGS = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           "source", "wfview", "rigs")
OUR_RIGS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rig", "icom")

# CI-V Adressen pro Modell
CIV_ADDRESSES = {
    "ic705": 0xA4, "ic7300": 0x94, "ic7300mk2": 0x94,
    "ic7610": 0x98, "ic9700": 0xA2, "ic7100": 0x88,
    "ic7600": 0x7A, "ic9100": 0x7C, "ic785x": 0x8E,
    "ic7760": 0x6E, "ic905": 0xAC,
}

def parse_rig_file(path):
    """Parsed ein wfview .rig File und extrahiert Features."""
    with open(path) as f:
        content = f.read()

    features = {
        "modes": [],
        "digi_modes": [],
        "dsp": [],
        "agc": [],
        "preamp": [],
        "power": {},
        "pbt": False,
        "scope": False,
    }

    # Modes aus Commands extrahieren
    mode_types = set()
    for m in re.finditer(r'Commands\\\d+\\Type=(.+)', content):
        t = m.group(1).strip()
        mode_types.add(t)

    # DSP Features
    dsp_map = {
        "Attenuator": "ATT", "Attenuator Status": "ATT",
        "Noise Blanker": "NB", "NB Level": "NB",
        "Noise Reduction": "NR", "NR Level": "NR",
        "Auto Notch": "NOTCH", "Manual Notch": "NOTCH",
        "Compressor": "COMP", "Compressor Status": "COMP", "Compressor Level": "COMP",
        "Audio Peak Filter": "APF",
    }
    for wf_name, our_name in dsp_map.items():
        if wf_name in mode_types and our_name not in features["dsp"]:
            features["dsp"].append(our_name)

    # AGC
    if "AGC" in mode_types or "AGC Time Constant" in mode_types:
        features["agc"] = ["SLOW", "MID", "FAST"]

    # Preamp
    if "Preamp" in mode_types:
        features["preamp"] = ["OFF", "AMP1", "AMP2"]

    # PBT
    if "PBT Inner" in mode_types:
        features["pbt"] = True

    # Power
    power_match = re.search(r'Bands\\1\\Power=(\d+)', content)
    max_watts = int(power_match.group(1)) if power_match else 100
    features["power"] = {"min": 0, "max": 255, "max_watts": max_watts}

    # Scope
    if "Scope Wave" in " ".join(mode_types) or "scope" in content.lower():
        features["scope"] = True

    # Standard Modes für Icom
    features["modes"] = ["LSB", "USB", "CW", "CW-R", "FM", "AM", "RTTY", "RTTY-R"]
    features["digi_modes"] = ["DATA"]

    return features


def main():
    if not os.path.isdir(WFVIEW_RIGS):
        print(f"wfview rigs nicht gefunden: {WFVIEW_RIGS}")
        return

    for rig_file in sorted(os.listdir(WFVIEW_RIGS)):
        if not rig_file.startswith("IC-") or not rig_file.endswith(".rig"):
            continue

        model = rig_file.replace(".rig", "").replace("IC-", "ic").lower().replace(" ", "")
        our_dir = os.path.join(OUR_RIGS, model)
        our_config = os.path.join(our_dir, "config.json")

        if not os.path.exists(our_dir):
            continue  # Wir haben dieses Rig nicht

        features = parse_rig_file(os.path.join(WFVIEW_RIGS, rig_file))

        # Config laden und features updaten
        cfg = {}
        if os.path.exists(our_config):
            with open(our_config) as f:
                cfg = json.load(f)

        cfg["features"] = features

        with open(our_config, "w") as f:
            json.dump(cfg, f, indent=4)

        print(f"  {rig_file:20s} → {our_config}")
        print(f"    DSP: {features['dsp']}")
        print(f"    Power: {features['power']['max_watts']}W")
        print(f"    PBT: {features['pbt']}  Scope: {features['scope']}")


if __name__ == "__main__":
    main()
