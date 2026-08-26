"""Tests fuer die Hardware-Erkennung und die Ollama-Empfehlung."""

import pytest

from src.utils import hardware
from src.utils.hardware import GpuInfo, classify_gpu_name, parse_nvidia_smi, recommend


def _gpu(name, vram_mb, dedicated=True, vendor="nvidia"):
    return GpuInfo(name=name, vram_mb=vram_mb, dedicated=dedicated, vendor=vendor)


@pytest.mark.parametrize("name,vendor,dedicated,ignore", [
    ("NVIDIA GeForce RTX 3060", "nvidia", True, False),
    ("Intel(R) UHD Graphics 770", "intel", False, False),
    ("Intel(R) Iris(R) Xe Graphics", "intel", False, False),
    ("Intel(R) Arc(TM) A770 Graphics", "intel", True, False),
    ("AMD Radeon(TM) Graphics", "amd", False, False),
    ("AMD Radeon 780M", "amd", False, False),
    ("AMD Radeon RX 7800 XT", "amd", True, False),
    ("Microsoft Basic Display Adapter", "other", False, True),
    ("VMware SVGA 3D", "other", False, True),
])
def test_classify_gpu_name(name, vendor, dedicated, ignore):
    assert classify_gpu_name(name) == (vendor, dedicated, ignore)


def test_parse_nvidia_smi():
    out = "NVIDIA GeForce RTX 4090, 24564\nNVIDIA T400, 2048\n\n"
    gpus = parse_nvidia_smi(out)
    assert [(g.name, g.vram_mb) for g in gpus] == [
        ("NVIDIA GeForce RTX 4090", 24564), ("NVIDIA T400", 2048)
    ]
    assert all(g.dedicated and g.vendor == "nvidia" for g in gpus)


def test_no_gpu_recommends_cloud():
    rec = recommend([], ram_mb=32000)
    assert rec.local_ok is False
    assert rec.model is None
    assert "Keine Grafikkarte" in rec.reason


def test_integrated_only_recommends_cloud_even_with_much_ram():
    rec = recommend([_gpu("Intel(R) UHD Graphics 770", 0, dedicated=False, vendor="intel")], ram_mb=65536)
    assert rec.local_ok is False
    assert "integrierte Grafik" in rec.reason
    assert rec.gpu.name.startswith("Intel")


def test_small_vram_recommends_cloud():
    rec = recommend([_gpu("NVIDIA GeForce GTX 1050", 2048)])
    assert rec.local_ok is False
    assert "2 GB" in rec.reason


def test_intel_arc_recommends_cloud():
    rec = recommend([_gpu("Intel(R) Arc(TM) A770 Graphics", 16384, vendor="intel")])
    assert rec.local_ok is False
    assert "Intel" in rec.reason


@pytest.mark.parametrize("vram_mb,model", [
    (4096, "gemma3:4b"),
    (8192, "gemma3:4b"),
    (12288, "gemma3:12b"),
    (16384, "gemma3:12b"),
    (24564, "gemma3:27b"),
])
def test_model_tier_by_vram(vram_mb, model):
    rec = recommend([_gpu("NVIDIA GeForce RTX", vram_mb)])
    assert rec.local_ok is True
    assert rec.model == model
    assert rec.model_size_gb > 0
    assert model in rec.reason


def test_best_dedicated_gpu_wins_over_integrated():
    gpus = [
        _gpu("Intel(R) UHD Graphics 630", 0, dedicated=False, vendor="intel"),
        _gpu("NVIDIA GeForce RTX 3080", 10240),
    ]
    rec = recommend(gpus)
    assert rec.local_ok is True
    assert rec.gpu.name == "NVIDIA GeForce RTX 3080"
    assert rec.model == "gemma3:12b"


def test_amd_gets_support_hint():
    rec = recommend([_gpu("AMD Radeon RX 7800 XT", 16384, vendor="amd")])
    assert rec.local_ok is True
    assert "AMD" in rec.reason


def test_detect_gpus_merges_sources(monkeypatch):
    monkeypatch.setattr(hardware, "_nvidia_smi_gpus",
                        lambda: [_gpu("NVIDIA GeForce RTX 3060", 12288)])
    monkeypatch.setattr(hardware, "_registry_gpus", lambda: [
        _gpu("NVIDIA GeForce RTX 3060", 12000),           # Duplikat -> ignoriert
        _gpu("Intel(R) UHD Graphics 770", 0, False, "intel"),
    ])
    gpus = hardware.detect_gpus()
    assert [g.name for g in gpus] == ["NVIDIA GeForce RTX 3060", "Intel(R) UHD Graphics 770"]
    assert gpus[0].vram_mb == 12288  # nvidia-smi hat Vorrang


def test_registry_value_conversion():
    assert hardware._registry_value_to_int(12 * 1024 ** 3) == 12 * 1024 ** 3
    assert hardware._registry_value_to_int((8 * 1024 ** 3).to_bytes(8, "little")) == 8 * 1024 ** 3
    assert hardware._registry_value_to_int(b"") == 0
    assert hardware._registry_value_to_int("x") == 0
