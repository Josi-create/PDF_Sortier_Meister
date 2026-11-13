"""
Globales Aussehen der Checkboxen (alle Plattformen).

Fusion zeichnet Checkbox-Kaestchen auf Retina-Macs praktisch ohne Rahmen
(weisses Quadrat auf hellem Grund) - Nutzer sehen nicht, dass dort etwas
anzuklicken ist. Darum eigene, kontrastreiche Indikatoren. Ein angehaktes
Kaestchen bekommt ein weisses Haekchen: nur blau gefuellt wurde es als
"aus" gelesen.

Das Haekchen-Bild wird beim Start ins Datenverzeichnis geschrieben, statt es
ueber PyInstaller mitzuliefern - so funktioniert es in Dev und Build gleich.

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path
from typing import Optional

from src.gui.farben import css
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

CHECK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
    '<path d="M3.5 8.5 L6.5 11.5 L12.5 4.5" fill="none" stroke="#ffffff" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)

_BASE = (
    "QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px; "
    "border: 1px solid $grau_7a; background-color: $weiss; }"
    "QCheckBox::indicator:hover { border-color: $akzent; }"
    "QCheckBox::indicator:checked { background-color: $akzent; "
    "border-color: $akzent_rand;{bild} }"
    "QCheckBox::indicator:disabled { border-color: $grau_c0; "
    "background-color: $grau_f0; }"
    "QCheckBox::indicator:checked:disabled { background-color: $akzent_blass; "
    "border-color: $akzent_blass; }"
)


def write_check_icon(folder: Path) -> Optional[Path]:
    """Schreibt das Haekchen-SVG nach folder; None, wenn das nicht geht."""
    path = Path(folder) / "checkbox_haekchen.svg"
    try:
        if not path.exists() or path.read_text(encoding="utf-8") != CHECK_SVG:
            path.write_text(CHECK_SVG, encoding="utf-8")
        return path
    except OSError as e:
        logger.warning(f"Haekchen fuer Checkboxen nicht geschrieben: {e}")
        return None


def checkbox_stylesheet(check_icon: Optional[Path]) -> str:
    """Stylesheet fuer alle Checkboxen; ohne Bild bleibt es beim blauen Kaestchen."""
    # Qt-Stylesheets wollen "/" als Trenner, auch unter Windows
    bild = f' image: url("{Path(check_icon).as_posix()}");' if check_icon else ""
    return css(_BASE).replace("{bild}", bild)
