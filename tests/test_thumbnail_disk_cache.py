"""Issue #28: Thumbnails werden als PNG auf Platte gecacht."""
import fitz


def _pdf(path):
    d = fitz.open(); p = d.new_page(); p.insert_text((72, 72), "Hallo"); d.save(str(path)); d.close()


def test_thumbnail_written_to_and_read_from_disk(tmp_path, monkeypatch, qtbot):
    from src.utils import config as cfg_mod
    from src.core import pdf_analyzer as pa
    from tests.conftest import patch_singletons

    cfg = cfg_mod.Config(config_path=tmp_path / "config.json")
    patch_singletons(monkeypatch, {"get_config": lambda: cfg})
    pa._thumbnail_cache._cache.clear()

    pdf = tmp_path / "a.pdf"; _pdf(pdf)
    disk = pa._thumbnail_disk_path(pdf, 150, 200)
    assert disk is not None and disk.parent == tmp_path / "thumbnails"
    assert not disk.exists()

    pix1 = pa.get_thumbnail(pdf, 150, 200)
    assert disk.exists() and not pix1.isNull()

    # RAM-Cache leeren -> naechster Aufruf muss von Platte kommen, nicht rendern
    pa._thumbnail_cache._cache.clear()
    monkeypatch.setattr(pa.PDFAnalyzer, "generate_thumbnail",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("rendered!")))
    pix2 = pa.get_thumbnail(pdf, 150, 200)
    assert pix2.size() == pix1.size()


def test_cache_key_changes_when_pdf_changes(tmp_path, monkeypatch):
    import os, time
    from src.utils import config as cfg_mod
    from src.core import pdf_analyzer as pa
    from tests.conftest import patch_singletons

    cfg = cfg_mod.Config(config_path=tmp_path / "config.json")
    patch_singletons(monkeypatch, {"get_config": lambda: cfg})
    pdf = tmp_path / "b.pdf"; _pdf(pdf)
    k1 = pa._thumbnail_disk_path(pdf, 150, 200)
    os.utime(pdf, (time.time() + 100, time.time() + 100))
    k2 = pa._thumbnail_disk_path(pdf, 150, 200)
    assert k1 != k2
