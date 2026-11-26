"""Trennlinien rasten beim Loslassen ein (Issue #341).

* ``reihen_hoehe``: Hoehe der Vorschlagsliste (Trennlinie ueber dem Ordnerbaum) auf ganze
  Reihen von Vorschlagskacheln, oder knapp unter die letzte Reihe.
* ``spalten_breite``: nutzbare Breite der linken Spalte auf eine ganze Zahl von Kachelspalten.
* ``LoslassMelder``: ruft eine Funktion auf, wenn der Griff einer Trennlinie losgelassen wird.
"""

from typing import Callable

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer


def reihen_hoehe(gezogen: int, bedarf: int, zeile: int, abstand: int, hoechstens: int) -> int:
    """Eingerastete Hoehe der Vorschlagsliste.

    Ab ``bedarf`` (alle Reihen sichtbar) wird es genau ``bedarf``, kein leerer Streifen darunter;
    darueber die naechste ganze Reihe (``k * zeile + (k - 1) * abstand``), keine halbe Reihe.
    ``hoechstens`` begrenzt nach unten (dem Ordnerbaum bleibt sein Mindestplatz).
    """
    if gezogen >= bedarf and bedarf <= hoechstens:
        return bedarf
    schritt = zeile + abstand
    k = max(1, round((gezogen + abstand) / schritt))
    k = min(k, max(1, (min(bedarf, hoechstens) + abstand) // schritt))
    return k * schritt - abstand


def spalten_breite(frei: int, kachel: int, abstand: int, unten: int, oben: int) -> int:
    """Nutzbare Breite fuer die naechstgelegene ganze Zahl von Kachelspalten.

    ``n`` Spalten brauchen ``n * kachel + (n - 1) * abstand``. Gewaehlt wird die zu ``frei``
    naechste solche Breite im Bereich ``unten..oben`` (Mindestbreiten der Spalten); passt
    keine hinein, bleibt ``frei``.
    """
    schritt = kachel + abstand
    if schritt <= 0:
        return frei
    kandidaten = [n * schritt - abstand for n in range(1, max(oben, 0) // schritt + 2)]
    passend = [b for b in kandidaten if unten <= b <= oben]
    if not passend:
        return frei
    return min(passend, key=lambda b: (abs(b - frei), b))


class LoslassMelder(QObject):
    """Meldet das Loslassen des Griffs einer Trennlinie (nach dem Ereignis, nicht waehrenddessen)."""

    def __init__(self, griff, beim_loslassen: Callable[[], None]):
        super().__init__(griff)
        self._beim_loslassen = beim_loslassen
        griff.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt-API)
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            QTimer.singleShot(0, self._beim_loslassen)
        return False
