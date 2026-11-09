"""Angehakte Checkboxen zeigen ein Haekchen, nicht nur ein blaues Kaestchen."""
from src.gui.checkbox_style import CHECK_SVG, checkbox_stylesheet, write_check_icon


def test_haekchen_wird_geschrieben_und_eingebunden(tmp_path):
    icon = write_check_icon(tmp_path)
    assert icon is not None and icon.read_text(encoding="utf-8") == CHECK_SVG
    css = checkbox_stylesheet(icon)
    checked = css.split("QCheckBox::indicator:checked {")[1].split("}")[0]
    assert f'image: url("{icon.as_posix()}")' in checked
    assert "\\" not in checked  # Qt braucht "/" auch unter Windows


def test_ohne_bild_bleibt_das_blaue_kaestchen(tmp_path):
    css = checkbox_stylesheet(None)
    assert "image:" not in css and "{bild}" not in css
    assert "QCheckBox::indicator:checked { background-color: #0078d7;" in css


def test_nicht_beschreibbarer_ordner_liefert_none(tmp_path):
    assert write_check_icon(tmp_path / "gibt-es-nicht") is None
