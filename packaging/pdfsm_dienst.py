"""Einstieg der gebauten Dienstprogramme ``pdfsm-dienst`` und ``pdfsm-dienstw`` (PyInstaller).

``freeze_support()`` muss vor allem anderen laufen: Die Arbeitsprozesse des
Indexlaufs (``ProcessPoolExecutor``, Startmethode spawn) starten dasselbe
Programm noch einmal und werden hier abgefangen.
"""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from src.search.dienst import main

    sys.exit(main())
