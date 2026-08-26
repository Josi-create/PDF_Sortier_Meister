"""
Hardware-Erkennung fuer die Ollama-Empfehlung im Einrichtungs-Assistenten.

Ermittelt Grafikkarten (Name, dedizierter Grafikspeicher, integriert oder
dediziert) und den Arbeitsspeicher und leitet daraus ab, ob Ollama lokal
sinnvoll ist und welches Modell zur Grafikkarte passt.

Quellen (Windows):
1. ``nvidia-smi`` - liefert bei NVIDIA-Karten den exakten Speicher.
2. Registry ``HKLM\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-...}``
   (Display-Adapter): ``DriverDesc`` + ``HardwareInformation.qwMemorySize``.
   Deckt AMD/Intel ab und dient als Fallback fuer NVIDIA ohne nvidia-smi.

Integrierte GPUs (Intel UHD/Iris, AMD Radeon Graphics in APUs) melden zwar
einen Speicherwert, teilen sich aber den Arbeitsspeicher - fuer Ollama zaehlt
das nicht als Grafikspeicher.
"""

from __future__ import annotations

import ctypes
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class GpuInfo:
    name: str
    vram_mb: int          # dedizierter Grafikspeicher in MB (0 = keiner/unbekannt)
    dedicated: bool       # False = integrierte Grafik (nutzt den Arbeitsspeicher)
    vendor: str           # "nvidia" | "amd" | "intel" | "other"


@dataclass
class OllamaRecommendation:
    local_ok: bool                 # Ollama lokal empfohlen?
    model: Optional[str]           # empfohlenes lokales Modell (None -> Cloud)
    model_size_gb: float           # Downloadgroesse des Modells
    reason: str                    # Begruendung fuer den Nutzer
    gpu: Optional[GpuInfo]         # die massgebliche Grafikkarte


# (min. Grafikspeicher in MB, Modell, Downloadgroesse in GB)
# Gemma 3 ist mehrsprachig stark (Deutsch) und liefert stabiles JSON.
MODEL_TIERS = [
    (20000, "gemma3:27b", 17.0),
    (10000, "gemma3:12b", 8.1),
    (4000, "gemma3:4b", 3.3),
]
MIN_VRAM_MB = MODEL_TIERS[-1][0]

CLOUD_MODEL = "gpt-oss:120b"

_INTEGRATED_PATTERNS = (
    r"intel\(r\)\s+(uhd|hd|iris)",
    r"intel.*(uhd|iris)\s+graphics",
    r"radeon\(tm\)\s+graphics",
    r"amd radeon graphics",
    r"radeon.*vega.*graphics",
    r"radeon\s+\d{3}m\b",          # Radeon 610M/680M/780M/890M (APUs)
)
_IGNORE_PATTERNS = (
    r"microsoft basic",
    r"remote display",
    r"virtual",
    r"vmware",
    r"virtualbox",
    r"parsec",
    r"displaylink",
    r"citrix",
)


def classify_gpu_name(name: str) -> tuple[str, bool, bool]:
    """
    Ordnet einen Adapternamen ein.

    Returns:
        (vendor, dedicated, ignore)
    """
    low = name.lower()
    if any(re.search(p, low) for p in _IGNORE_PATTERNS):
        return "other", False, True
    if "nvidia" in low or "geforce" in low or "quadro" in low:
        vendor = "nvidia"
    elif "amd" in low or "radeon" in low:
        vendor = "amd"
    elif "intel" in low:
        vendor = "intel"
    else:
        vendor = "other"
    integrated = any(re.search(p, low) for p in _INTEGRATED_PATTERNS)
    return vendor, not integrated, False


def parse_nvidia_smi(output: str) -> list[GpuInfo]:
    """Parst ``nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits``."""
    gpus = []
    for line in output.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2 or not parts[0]:
            continue
        try:
            vram = int(float(parts[1]))
        except ValueError:
            continue
        gpus.append(GpuInfo(name=parts[0], vram_mb=vram, dedicated=True, vendor="nvidia"))
    return gpus


def _nvidia_smi_gpus() -> list[GpuInfo]:
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, **kwargs,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return parse_nvidia_smi(result.stdout)


def _registry_value_to_int(value) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, (bytes, bytearray)) and value:
        return int.from_bytes(value, "little", signed=False)
    return 0


def _registry_gpus() -> list[GpuInfo]:
    """Display-Adapter aus der Windows-Registry (funktioniert ohne Zusatztools)."""
    if sys.platform != "win32":
        return []
    import winreg

    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    gpus = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return []
    with root:
        index = 0
        while True:
            try:
                sub = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            if not re.fullmatch(r"\d{4}", sub):
                continue
            try:
                with winreg.OpenKey(root, sub) as key:
                    name = winreg.QueryValueEx(key, "DriverDesc")[0]
                    vram_bytes = 0
                    for value_name in ("HardwareInformation.qwMemorySize",
                                       "HardwareInformation.MemorySize"):
                        try:
                            vram_bytes = _registry_value_to_int(
                                winreg.QueryValueEx(key, value_name)[0]
                            )
                            if vram_bytes:
                                break
                        except OSError:
                            continue
            except OSError:
                continue
            vendor, dedicated, ignore = classify_gpu_name(name)
            if ignore:
                continue
            gpus.append(GpuInfo(
                name=name,
                vram_mb=int(vram_bytes // (1024 * 1024)) if dedicated else 0,
                dedicated=dedicated,
                vendor=vendor,
            ))
    return gpus


def detect_gpus() -> list[GpuInfo]:
    """Alle Grafikkarten; NVIDIA-Werte aus nvidia-smi haben Vorrang."""
    gpus = _nvidia_smi_gpus()
    seen = {g.name.lower() for g in gpus}
    for g in _registry_gpus():
        if g.name.lower() in seen:
            continue
        seen.add(g.name.lower())
        gpus.append(g)
    return gpus


def total_ram_mb() -> int:
    """Physischer Arbeitsspeicher in MB (0, wenn nicht ermittelbar)."""
    if sys.platform != "win32":
        return 0

    class _MemStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = _MemStatus()
    status.dwLength = ctypes.sizeof(_MemStatus)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0
    except Exception:
        return 0
    return int(status.ullTotalPhys // (1024 * 1024))


def _gb(mb: int) -> str:
    return f"{mb / 1024:.0f} GB"


def recommend(gpus: list[GpuInfo], ram_mb: int = 0) -> OllamaRecommendation:
    """
    Leitet aus der Hardware eine Ollama-Empfehlung ab.

    Regeln:
    - keine dedizierte Grafikkarte (nur integrierte Grafik oder gar keine):
      lokal nicht empfohlen -> Ollama Cloud
    - dedizierte Karte mit weniger als 4 GB: ebenfalls Cloud
    - Intel Arc: von Ollama unter Windows nicht unterstuetzt -> Cloud
    - sonst: groesstes Gemma-3-Modell, das in den Grafikspeicher passt
    """
    dedicated = [g for g in gpus if g.dedicated]
    best = max(dedicated, key=lambda g: g.vram_mb) if dedicated else None

    if best is None:
        integrated = next((g for g in gpus if not g.dedicated), None)
        if integrated:
            reason = (
                f"Nur integrierte Grafik erkannt ({integrated.name}), die sich den "
                f"Arbeitsspeicher teilt. Ein lokales Modell wuerde auf dem Prozessor "
                f"laufen - pro Dokument dauert das oft eine Minute oder laenger."
            )
        else:
            reason = (
                "Keine Grafikkarte erkannt. Ein lokales Modell wuerde auf dem "
                "Prozessor laufen - pro Dokument dauert das oft eine Minute oder laenger."
            )
        return OllamaRecommendation(False, None, 0.0, reason, integrated)

    if best.vendor == "intel":
        return OllamaRecommendation(
            False, None, 0.0,
            f"{best.name} erkannt - Intel-Grafikkarten werden von Ollama unter "
            f"Windows nicht unterstuetzt, das Modell liefe auf dem Prozessor.",
            best,
        )

    if best.vram_mb < MIN_VRAM_MB:
        vram_text = _gb(best.vram_mb) if best.vram_mb else "unbekannt"
        return OllamaRecommendation(
            False, None, 0.0,
            f"{best.name} erkannt, aber mit {vram_text} Grafikspeicher zu wenig fuer "
            f"ein brauchbares lokales Modell (mindestens {_gb(MIN_VRAM_MB)}).",
            best,
        )

    for min_mb, model, size_gb in MODEL_TIERS:
        if best.vram_mb >= min_mb:
            reason = (
                f"{best.name} mit {_gb(best.vram_mb)} Grafikspeicher erkannt - "
                f"empfohlenes Modell: {model} (Download ca. {size_gb:.0f} GB)."
            )
            if best.vendor == "amd":
                reason += (
                    " Hinweis: Ollama unterstuetzt unter Windows nur neuere "
                    "AMD-Karten (Radeon RX 6000/7000/9000)."
                )
            return OllamaRecommendation(True, model, size_gb, reason, best)

    # unerreichbar (MIN_VRAM_MB entspricht der kleinsten Stufe), Sicherheitsnetz
    return OllamaRecommendation(False, None, 0.0, "Keine Empfehlung moeglich.", best)


def detect_and_recommend() -> OllamaRecommendation:
    """Erkennung + Empfehlung in einem Schritt (dauert < 1 s, nvidia-smi inklusive)."""
    return recommend(detect_gpus(), total_ram_mb())
