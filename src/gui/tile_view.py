"""
Kachelgroessen fuer den Scan-Bereich (Issue #117)

Der linke Bereich zeigt PDFs und Unterordner als Kacheln. Wie im
Windows-Explorer laesst sich die Groesse umschalten (Klein / Mittel / Gross).
Das Thumbnail wird weiterhin in 140x160 gerendert und auf Platte gecacht;
kleinere Ansichten skalieren nur dieses Bild herunter. Bei den kompakten
Ansichten zeigt der Mauszeiger ueber einer PDF-Kachel das Original.

GPL-3.0-or-later - Copyright (c) 2026
"""

from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics


@dataclass(frozen=True)
class TileView:
    """Masse einer Kachelgroesse. Alle Werte in Pixeln."""

    id: str
    label: str
    thumb_w: int  # Bildflaeche in der PDF-Kachel
    thumb_h: int
    # True: Bild fuellt die Flaeche in der Breite, unten wird abgeschnitten
    # (Kopf der Seite). False: ganze Seite eingepasst, Rest bleibt frei.
    thumb_crop: bool
    tile_w: int  # Mindestbreite/-hoehe der Kachel (PDF und Ordner gleich)
    tile_h: int
    tile_max_w: int
    tile_max_h: int
    margin: int  # Innenabstand der Kachel
    spacing: int  # Abstand Bild -> Name
    font_px: int  # Schriftgroesse des Dateinamens
    name_lines: int  # Zeilen fuer den Namen; die letzte wird mittig gekuerzt
    name_max_height: int  # Hoehe des Namensfelds
    folder_icon_px: int  # Schriftgroesse des Ordner-Symbols
    hover_preview: bool  # Mauszeiger ueber PDF zeigt das Original-Thumbnail

    @property
    def slot_width(self) -> int:
        """Rasterbreite pro Kachel inkl. Abstand - bestimmt die Spaltenzahl."""
        return self.tile_max_w + 10

    @property
    def text_width(self) -> int:
        """Nutzbare Textbreite in der Kachel (Mindestbreite minus Rand/Rahmen)."""
        return self.tile_w - 2 * self.margin - 2


# Reihenfolge = Reihenfolge in der Auswahl. "gross" entspricht den Massen
# vor Issue #117 (Kachel 160-180 x 230-260, Bild 140x160).
TILE_VIEWS: tuple[TileView, ...] = (
    TileView(
        id="klein", label="Klein",
        # Bild so breit wie der Text, Seite unten abgeschnitten: Bei 56x64
        # blieb um die A4-Seite (45 px breit) zu viel leere Kachel (#117-Feedback)
        thumb_w=82, thumb_h=64, thumb_crop=True,
        tile_w=92, tile_h=104, tile_max_w=102, tile_max_h=126,
        margin=4, spacing=3, font_px=10,
        name_lines=2, name_max_height=30,
        folder_icon_px=22, hover_preview=True,
    ),
    TileView(
        id="mittel", label="Mittel",
        thumb_w=84, thumb_h=96, thumb_crop=False,
        tile_w=104, tile_h=142, tile_max_w=114, tile_max_h=166,
        margin=6, spacing=4, font_px=10,
        name_lines=2, name_max_height=30,
        folder_icon_px=32, hover_preview=True,
    ),
    TileView(
        id="gross", label="Groß",
        thumb_w=140, thumb_h=160, thumb_crop=False,
        tile_w=160, tile_h=230, tile_max_w=180, tile_max_h=260,
        margin=8, spacing=5, font_px=11,
        name_lines=3, name_max_height=55,
        folder_icon_px=48, hover_preview=False,
    ),
)

DEFAULT_TILE_VIEW_ID = "klein"

_BY_ID = {view.id: view for view in TILE_VIEWS}


def tile_view(view_id: Optional[str]) -> TileView:
    """Liefert die Kachelgroesse zu einer Konfigurations-ID; unbekannt -> Standard."""
    return _BY_ID.get(view_id or "", _BY_ID[DEFAULT_TILE_VIEW_ID])


def fit_text_lines(text: str, fm: QFontMetrics, width: int, max_lines: int) -> str:
    """Bricht ``text`` auf hoechstens ``max_lines`` Zeilen der Breite ``width`` um.

    QLabel bricht nur an Leerzeichen um; Dateinamen wie
    ``Stadtwerke_Jahresabrechnung_2023`` liefen deshalb seitlich aus der
    Kachel. Hier wird bevorzugt an Leerzeichen getrennt, zu lange Woerter
    werden zeichenweise geteilt, und die letzte Zeile wird bei Bedarf in der
    Mitte gekuerzt ("Stadtwerke_Jah…ng_2023").
    """
    def fits(s: str) -> bool:
        return fm.horizontalAdvance(s) <= width

    rest = text.strip()
    if max_lines <= 0 or fits(rest):
        return rest
    lines: list[str] = []
    while rest and len(lines) < max_lines - 1:
        if fits(rest):
            break
        cut = len(rest)
        while cut > 1 and not fits(rest[:cut]):
            cut -= 1
        # Lieber am letzten Leerzeichen innerhalb des passenden Stuecks trennen
        space = rest.rfind(" ", 1, cut + 1)
        if space > 0:
            cut = space
        lines.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        lines.append(fm.elidedText(rest, Qt.TextElideMode.ElideMiddle, width))
    return "\n".join(lines)
