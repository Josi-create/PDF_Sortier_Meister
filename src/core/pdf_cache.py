"""
PDF-Analyse-Cache für PDF Sortier Meister

Cached PDF-Analysen für schnellere Interaktion:
- Bereits analysierte PDFs werden nicht erneut analysiert
- Hintergrund-Analyse mit niedriger Priorität
- Pre-Caching für noch nicht analysierte PDFs
- Persistente Speicherung (optional) für schnellen Neustart
"""

from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
import queue
import time
import json
import sqlite3

from PyQt6.QtCore import QThread, pyqtSignal, QObject


@dataclass
class LLMSuggestion:
    """Ein LLM-Namensvorschlag."""
    filename: str
    confidence: float = 0.0
    source: str = "llm"


@dataclass
class PDFAnalysisResult:
    """Ergebnis einer PDF-Analyse."""
    pdf_path: Path
    extracted_text: str = ""
    keywords: list[str] = field(default_factory=list)
    dates: list = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=datetime.now)
    file_modified: float = 0.0  # mtime der Datei bei Analyse
    # LLM-Vorschläge (optional, werden im Hintergrund nachgeladen)
    llm_suggestions: list[LLMSuggestion] = field(default_factory=list)
    llm_fetched: bool = False  # True wenn LLM-Vorschläge abgerufen wurden


class PDFAnalysisWorker(QThread):
    """Worker-Thread für Hintergrund-PDF-Analyse."""

    # Signale
    analysis_complete = pyqtSignal(Path, object)  # (pdf_path, PDFAnalysisResult)
    analysis_error = pyqtSignal(Path, str)  # (pdf_path, error_message)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._running = True
        self._current_pdf: Optional[Path] = None
        self._lock = Lock()

    def add_task(self, pdf_path: Path, priority: int = 5):
        """
        Fügt eine Analyse-Aufgabe zur Queue hinzu.

        Args:
            pdf_path: Pfad zur PDF
            priority: 1 = höchste Priorität (User-Interaktion), 10 = niedrigste (Pre-Cache)
        """
        self._queue.put((priority, time.time(), pdf_path))

    def add_urgent(self, pdf_path: Path):
        """Fügt eine dringende Analyse hinzu (User hat geklickt)."""
        self.add_task(pdf_path, priority=1)

    def add_background(self, pdf_path: Path):
        """Fügt eine Hintergrund-Analyse hinzu."""
        self.add_task(pdf_path, priority=10)

    def get_current_pdf(self) -> Optional[Path]:
        """Gibt die aktuell analysierte PDF zurück."""
        with self._lock:
            return self._current_pdf

    def stop(self):
        """Stoppt den Worker."""
        self._running = False
        # Dummy-Task um Queue zu unblockieren
        self._queue.put((0, 0, None))

    def run(self):
        """Worker-Loop."""
        from src.core.pdf_analyzer import PDFAnalyzer

        while self._running:
            try:
                # Warte auf nächste Aufgabe (mit Timeout für sauberes Beenden)
                try:
                    priority, timestamp, pdf_path = self._queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                if pdf_path is None:
                    continue

                with self._lock:
                    self._current_pdf = pdf_path

                # PDF analysieren
                try:
                    if not pdf_path.exists():
                        continue

                    with PDFAnalyzer(pdf_path) as analyzer:
                        result = PDFAnalysisResult(
                            pdf_path=pdf_path,
                            extracted_text=analyzer.extract_text(),
                            keywords=analyzer.extract_keywords(),
                            dates=analyzer.extract_dates(),
                            file_modified=pdf_path.stat().st_mtime
                        )

                    self.analysis_complete.emit(pdf_path, result)

                except Exception as e:
                    self.analysis_error.emit(pdf_path, str(e))

                finally:
                    with self._lock:
                        self._current_pdf = None

            except Exception:
                pass  # Worker soll nicht abstürzen


class LLMSuggestionWorker(QThread):
    """Worker-Thread für Hintergrund-LLM-Abruf."""

    # Signale
    suggestions_complete = pyqtSignal(Path, list)  # (pdf_path, list[LLMSuggestion])
    suggestions_error = pyqtSignal(Path, str)  # (pdf_path, error_message)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._running = True
        self._current_pdf: Optional[Path] = None
        self._lock = Lock()
        self._hybrid_classifier = None

    def add_task(self, pdf_path: Path, analysis_result: PDFAnalysisResult, priority: int = 5):
        """Fügt eine LLM-Abruf-Aufgabe zur Queue hinzu."""
        self._queue.put((priority, time.time(), pdf_path, analysis_result))

    def stop(self):
        """Stoppt den Worker."""
        self._running = False
        self._queue.put((0, 0, None, None))

    def run(self):
        """Worker-Loop für LLM-Abruf."""
        while self._running:
            try:
                try:
                    priority, timestamp, pdf_path, analysis_result = self._queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                if pdf_path is None:
                    continue

                with self._lock:
                    self._current_pdf = pdf_path

                try:
                    if not pdf_path.exists():
                        continue

                    # Hybrid-Classifier lazy laden
                    if self._hybrid_classifier is None:
                        try:
                            from src.ml.hybrid_classifier import get_hybrid_classifier
                            self._hybrid_classifier = get_hybrid_classifier()
                        except Exception as e:
                            print(f"LLM-Pre-Cache: Konnte Hybrid-Classifier nicht laden: {e}")
                            continue

                    # Prüfen ob LLM überhaupt verfügbar ist
                    if not self._hybrid_classifier.is_llm_available():
                        print(f"LLM-Pre-Cache: LLM nicht verfügbar, überspringe {pdf_path.name}")
                        continue

                    # LLM-Vorschläge abrufen
                    from datetime import datetime as dt
                    file_mtime = pdf_path.stat().st_mtime
                    file_date = dt.fromtimestamp(file_mtime).strftime("%Y-%m-%d")

                    detected_date = None
                    if analysis_result.dates:
                        detected_date = str(analysis_result.dates[0])

                    print(f"LLM-Pre-Cache: Rufe LLM ab für {pdf_path.name}...")
                    suggestions = self._hybrid_classifier.suggest_filename(
                        text=analysis_result.extracted_text or "",
                        current_filename=pdf_path.name,
                        keywords=analysis_result.keywords,
                        detected_date=detected_date,
                        use_llm=True,
                        file_date=file_date,
                    )

                    # Nur LLM-Vorschläge behalten (nicht lokale)
                    llm_suggestions = []
                    for s in suggestions:
                        if s.source == "llm":
                            llm_suggestions.append(LLMSuggestion(
                                filename=s.filename,
                                confidence=s.confidence,
                                source=s.source
                            ))

                    self.suggestions_complete.emit(pdf_path, llm_suggestions)

                except Exception as e:
                    self.suggestions_error.emit(pdf_path, str(e))

                finally:
                    with self._lock:
                        self._current_pdf = None

            except Exception:
                pass  # Worker soll nicht abstürzen


class PDFCache(QObject):
    """
    Zentraler Cache für PDF-Analysen.

    Features:
    - Cached Analyse-Ergebnisse
    - Automatische Invalidierung bei Dateiänderung
    - Hintergrund-Worker für Analyse
    - Pre-Caching Unterstützung
    - Persistente Speicherung (SQLite) für schnellen Neustart
    """

    # Signale
    pdf_analyzed = pyqtSignal(Path)  # PDF wurde analysiert (aus Cache oder neu)
    llm_suggestions_ready = pyqtSignal(Path)  # LLM-Vorschläge wurden abgerufen
    cache_ready = pyqtSignal()  # Alle PDFs im Pre-Cache analysiert

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        super().__init__()
        self._cache: dict[Path, PDFAnalysisResult] = {}
        self._lock = Lock()
        self._worker: Optional[PDFAnalysisWorker] = None
        self._llm_worker: Optional[LLMSuggestionWorker] = None
        self._pending_callbacks: dict[Path, list[Callable]] = {}
        self._persist_cache = True  # Standardmäßig persistenten Cache nutzen
        self._db_path: Optional[Path] = None
        self._llm_precache_enabled = True  # LLM-Pre-Caching aktivieren (Default)
        self._initialized = True

        # Persistenten Cache initialisieren
        self._init_persistent_cache()

        # LLM-Pre-Cache Einstellung aus Config laden
        self._load_llm_precache_setting()

    def _init_persistent_cache(self):
        """Initialisiert die SQLite-Datenbank für persistenten Cache."""
        try:
            from src.utils.config import get_config
            config = get_config()

            # Cache-Pfad aus Config oder Standard
            data_dir = config.database_path.parent
            self._db_path = data_dir / "pdf_cache.db"

            # Persistenz-Einstellung aus Config
            self._persist_cache = config.get("persist_pdf_cache", True)

            if not self._persist_cache:
                return

            # Datenbank erstellen/öffnen
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()

            # Tabelle erstellen
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pdf_cache (
                    pdf_path TEXT PRIMARY KEY,
                    extracted_text TEXT,
                    keywords TEXT,
                    dates TEXT,
                    analyzed_at TEXT,
                    file_modified REAL,
                    llm_suggestions TEXT,
                    llm_fetched INTEGER DEFAULT 0
                )
            """)

            # Spalten hinzufügen falls sie noch nicht existieren (Migration)
            try:
                cursor.execute("ALTER TABLE pdf_cache ADD COLUMN llm_suggestions TEXT")
            except sqlite3.OperationalError:
                pass  # Spalte existiert bereits
            try:
                cursor.execute("ALTER TABLE pdf_cache ADD COLUMN llm_fetched INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # Spalte existiert bereits

            conn.commit()
            conn.close()

            # Cache aus Datenbank laden
            self._load_from_db()

        except Exception as e:
            print(f"Cache-Initialisierung fehlgeschlagen: {e}")
            self._persist_cache = False

    def _load_from_db(self):
        """Lädt den Cache aus der SQLite-Datenbank."""
        if not self._persist_cache or not self._db_path:
            return

        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM pdf_cache")
            rows = cursor.fetchall()

            loaded_count = 0
            llm_count = 0
            for row in rows:
                pdf_path = Path(row[0])

                # Prüfe ob Datei noch existiert
                if not pdf_path.exists():
                    continue

                # Prüfe ob Datei geändert wurde
                current_mtime = pdf_path.stat().st_mtime
                cached_mtime = row[5]

                if current_mtime != cached_mtime:
                    # Datei geändert, Cache-Eintrag ungültig
                    continue

                # Keywords und Dates aus JSON parsen
                keywords = json.loads(row[2]) if row[2] else []
                dates_str = json.loads(row[3]) if row[3] else []

                # Dates zurück konvertieren (vereinfacht - nur Strings)
                dates = dates_str

                # LLM-Vorschläge laden (falls vorhanden)
                llm_suggestions = []
                llm_fetched = False
                if len(row) > 6 and row[6]:
                    try:
                        llm_data = json.loads(row[6])
                        for s in llm_data:
                            llm_suggestions.append(LLMSuggestion(
                                filename=s.get("filename", ""),
                                confidence=s.get("confidence", 0.0),
                                source=s.get("source", "llm")
                            ))
                        llm_fetched = bool(len(row) > 7 and row[7])
                        if llm_suggestions:
                            llm_count += 1
                    except Exception:
                        pass

                result = PDFAnalysisResult(
                    pdf_path=pdf_path,
                    extracted_text=row[1] or "",
                    keywords=keywords,
                    dates=dates,
                    analyzed_at=datetime.fromisoformat(row[4]) if row[4] else datetime.now(),
                    file_modified=cached_mtime,
                    llm_suggestions=llm_suggestions,
                    llm_fetched=llm_fetched
                )

                with self._lock:
                    self._cache[pdf_path] = result
                loaded_count += 1

            conn.close()
            print(f"PDF-Cache: {loaded_count} Einträge geladen ({llm_count} mit LLM-Vorschlägen)")

        except Exception as e:
            print(f"Cache-Laden fehlgeschlagen: {e}")

    def _save_to_db(self, result: PDFAnalysisResult):
        """Speichert einen Eintrag in die SQLite-Datenbank."""
        if not self._persist_cache or not self._db_path:
            return

        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()

            # Dates als JSON-Strings speichern
            dates_json = json.dumps([str(d) for d in result.dates])
            keywords_json = json.dumps(result.keywords)

            # LLM-Vorschläge als JSON speichern
            llm_json = json.dumps([
                {"filename": s.filename, "confidence": s.confidence, "source": s.source}
                for s in result.llm_suggestions
            ]) if result.llm_suggestions else None

            cursor.execute("""
                INSERT OR REPLACE INTO pdf_cache
                (pdf_path, extracted_text, keywords, dates, analyzed_at, file_modified, llm_suggestions, llm_fetched)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(result.pdf_path),
                result.extracted_text,
                keywords_json,
                dates_json,
                result.analyzed_at.isoformat(),
                result.file_modified,
                llm_json,
                1 if result.llm_fetched else 0
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"Cache-Speichern fehlgeschlagen: {e}")

    def set_persist_cache(self, enabled: bool):
        """Aktiviert/deaktiviert die persistente Cache-Speicherung."""
        self._persist_cache = enabled

        # Config aktualisieren
        try:
            from src.utils.config import get_config
            config = get_config()
            config.set("persist_pdf_cache", enabled)
        except Exception:
            pass

    def clear_persistent_cache(self):
        """Löscht die persistente Cache-Datenbank."""
        if self._db_path and self._db_path.exists():
            try:
                conn = sqlite3.connect(str(self._db_path))
                cursor = conn.cursor()
                cursor.execute("DELETE FROM pdf_cache")
                conn.commit()
                conn.close()
                print("Persistenter PDF-Cache gelöscht")
            except Exception as e:
                print(f"Cache-Löschen fehlgeschlagen: {e}")

    def start_worker(self):
        """Startet den Hintergrund-Worker."""
        if self._worker is None or not self._worker.isRunning():
            self._worker = PDFAnalysisWorker()
            self._worker.analysis_complete.connect(self._on_analysis_complete)
            self._worker.analysis_error.connect(self._on_analysis_error)
            self._worker.start()

    def start_llm_worker(self):
        """Startet den LLM-Hintergrund-Worker."""
        if self._llm_worker is None or not self._llm_worker.isRunning():
            self._llm_worker = LLMSuggestionWorker()
            self._llm_worker.suggestions_complete.connect(self._on_llm_suggestions_complete)
            self._llm_worker.suggestions_error.connect(self._on_llm_suggestions_error)
            self._llm_worker.start()

    def stop_worker(self):
        """Stoppt den Hintergrund-Worker."""
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
            self._worker = None

    def stop_llm_worker(self):
        """Stoppt den LLM-Hintergrund-Worker."""
        if self._llm_worker and self._llm_worker.isRunning():
            self._llm_worker.stop()
            self._llm_worker.wait(2000)
            self._llm_worker = None

    def get(self, pdf_path: Path) -> Optional[PDFAnalysisResult]:
        """
        Holt ein gecachtes Analyse-Ergebnis.

        Args:
            pdf_path: Pfad zur PDF

        Returns:
            PDFAnalysisResult oder None wenn nicht im Cache
        """
        pdf_path = Path(pdf_path)
        with self._lock:
            result = self._cache.get(pdf_path)

            # Prüfe ob Cache noch gültig (Datei nicht geändert)
            if result and pdf_path.exists():
                current_mtime = pdf_path.stat().st_mtime
                if current_mtime != result.file_modified:
                    # Datei wurde geändert, Cache ungültig
                    del self._cache[pdf_path]
                    return None

            return result

    def is_cached(self, pdf_path: Path) -> bool:
        """Prüft ob eine PDF im Cache ist."""
        return self.get(pdf_path) is not None

    def is_analyzing(self, pdf_path: Path) -> bool:
        """Prüft ob eine PDF gerade analysiert wird."""
        if self._worker:
            return self._worker.get_current_pdf() == pdf_path
        return False

    def request_analysis(
        self,
        pdf_path: Path,
        callback: Callable[[PDFAnalysisResult], None] = None,
        urgent: bool = False
    ) -> Optional[PDFAnalysisResult]:
        """
        Fordert eine Analyse an.

        Wenn im Cache: Gibt sofort Ergebnis zurück
        Wenn nicht: Startet Hintergrund-Analyse, ruft Callback wenn fertig

        Args:
            pdf_path: Pfad zur PDF
            callback: Wird aufgerufen wenn Analyse fertig (optional)
            urgent: True = höchste Priorität (User-Interaktion)

        Returns:
            PDFAnalysisResult wenn im Cache, sonst None
        """
        pdf_path = Path(pdf_path)

        # Prüfe Cache
        cached = self.get(pdf_path)
        if cached:
            if callback:
                callback(cached)
            return cached

        # Callback registrieren
        if callback:
            with self._lock:
                if pdf_path not in self._pending_callbacks:
                    self._pending_callbacks[pdf_path] = []
                self._pending_callbacks[pdf_path].append(callback)

        # Worker starten falls nötig
        self.start_worker()

        # Analyse anfordern
        if urgent:
            self._worker.add_urgent(pdf_path)
        else:
            self._worker.add_background(pdf_path)

        return None

    def pre_cache(self, pdf_paths: list[Path]):
        """
        Startet Pre-Caching für eine Liste von PDFs.

        Args:
            pdf_paths: Liste von PDF-Pfaden
        """
        self.start_worker()

        llm_queue_count = 0
        for pdf_path in pdf_paths:
            pdf_path = Path(pdf_path)
            cached = self.get(pdf_path)

            if not cached:
                # Noch nicht analysiert - zur Analyse-Queue
                self._worker.add_background(pdf_path)
            elif self._llm_precache_enabled and not cached.llm_fetched:
                # Bereits analysiert, aber LLM noch nicht abgerufen
                self._request_llm_suggestions(pdf_path, cached)
                llm_queue_count += 1

        if llm_queue_count > 0:
            print(f"LLM-Pre-Cache: {llm_queue_count} bereits analysierte PDFs zur LLM-Queue hinzugefügt")

    def _on_analysis_complete(self, pdf_path: Path, result: PDFAnalysisResult):
        """Wird aufgerufen wenn eine Analyse abgeschlossen ist."""
        # In Memory-Cache speichern
        with self._lock:
            self._cache[pdf_path] = result

            # Callbacks aufrufen
            callbacks = self._pending_callbacks.pop(pdf_path, [])

        # In persistenten Cache speichern
        self._save_to_db(result)

        for callback in callbacks:
            try:
                callback(result)
            except Exception:
                pass

        # Signal emittieren
        self.pdf_analyzed.emit(pdf_path)

        # LLM-Pre-Caching auslösen (falls aktiviert und noch nicht abgerufen)
        if self._llm_precache_enabled and not result.llm_fetched:
            self._request_llm_suggestions(pdf_path, result)

    def _request_llm_suggestions(self, pdf_path: Path, analysis_result: PDFAnalysisResult):
        """Fordert LLM-Vorschläge im Hintergrund an."""
        print(f"LLM-Pre-Cache: Starte Abruf für {pdf_path.name}...")
        self.start_llm_worker()
        self._llm_worker.add_task(pdf_path, analysis_result, priority=10)

    def _on_llm_suggestions_complete(self, pdf_path: Path, suggestions: list):
        """Wird aufgerufen wenn LLM-Vorschläge abgerufen wurden."""
        print(f"LLM-Pre-Cache: {len(suggestions)} Vorschläge für {pdf_path.name} erhalten")
        with self._lock:
            if pdf_path in self._cache:
                self._cache[pdf_path].llm_suggestions = suggestions
                self._cache[pdf_path].llm_fetched = True

                # Aktualisiert in persistentem Cache speichern
                self._save_to_db(self._cache[pdf_path])

        # Signal emittieren
        self.llm_suggestions_ready.emit(pdf_path)

    def _on_llm_suggestions_error(self, pdf_path: Path, error: str):
        """Wird aufgerufen wenn LLM-Abruf fehlschlägt."""
        print(f"LLM-Pre-Cache FEHLER für {pdf_path.name}: {error}")

    def _on_analysis_error(self, pdf_path: Path, error: str):
        """Wird aufgerufen wenn eine Analyse fehlschlägt."""
        with self._lock:
            # Callbacks mit leerem Ergebnis aufrufen
            callbacks = self._pending_callbacks.pop(pdf_path, [])

        # Leeres Ergebnis für Fehlerfall
        empty_result = PDFAnalysisResult(pdf_path=pdf_path)

        for callback in callbacks:
            try:
                callback(empty_result)
            except Exception:
                pass

    def clear(self):
        """Leert den gesamten Cache."""
        with self._lock:
            self._cache.clear()

    def clear_for_pdf(self, pdf_path: Path):
        """Entfernt einen Eintrag aus dem Cache."""
        pdf_path = Path(pdf_path)
        with self._lock:
            self._cache.pop(pdf_path, None)

    def migrate_cache_entry(self, old_path: Path, new_path: Path):
        """
        Migriert einen Cache-Eintrag von einem Pfad zu einem neuen.

        Wird verwendet wenn eine PDF umbenannt oder verschoben wird,
        um den LLM-Cache (llm_fetched) zu erhalten.

        Args:
            old_path: Alter Pfad
            new_path: Neuer Pfad
        """
        old_path = Path(old_path)
        new_path = Path(new_path)

        with self._lock:
            if old_path not in self._cache:
                return

            # Eintrag kopieren und Pfad aktualisieren
            old_entry = self._cache.pop(old_path)
            old_entry.pdf_path = new_path

            # mtime aktualisieren (falls Datei existiert)
            if new_path.exists():
                old_entry.file_modified = new_path.stat().st_mtime

            self._cache[new_path] = old_entry
            print(f"Cache migriert: {old_path.name} -> {new_path.name} (LLM: {old_entry.llm_fetched})")

        # Alten DB-Eintrag löschen und neuen speichern
        if self._persist_cache and self._db_path:
            try:
                conn = sqlite3.connect(str(self._db_path))
                cursor = conn.cursor()
                cursor.execute("DELETE FROM pdf_cache WHERE pdf_path = ?", (str(old_path),))
                conn.commit()
                conn.close()
            except Exception:
                pass

            # Neuen Eintrag speichern
            self._save_to_db(old_entry)

    def get_stats(self) -> dict:
        """Gibt Cache-Statistiken zurück."""
        with self._lock:
            llm_count = sum(1 for r in self._cache.values() if r.llm_fetched)
            return {
                "cached_count": len(self._cache),
                "pending_count": len(self._pending_callbacks),
                "llm_cached_count": llm_count,
            }

    def get_llm_suggestions(self, pdf_path: Path) -> list[LLMSuggestion]:
        """
        Gibt gecachte LLM-Vorschläge für eine PDF zurück.

        Args:
            pdf_path: Pfad zur PDF

        Returns:
            Liste von LLMSuggestion oder leere Liste wenn nicht gecacht
        """
        pdf_path = Path(pdf_path)
        with self._lock:
            result = self._cache.get(pdf_path)
            if result and result.llm_fetched:
                return result.llm_suggestions
        return []

    def has_llm_suggestions(self, pdf_path: Path) -> bool:
        """Prüft ob LLM-Vorschläge für eine PDF gecacht sind."""
        pdf_path = Path(pdf_path)
        with self._lock:
            result = self._cache.get(pdf_path)
            return result is not None and result.llm_fetched and len(result.llm_suggestions) > 0

    def set_llm_precache_enabled(self, enabled: bool):
        """Aktiviert/deaktiviert LLM-Pre-Caching."""
        self._llm_precache_enabled = enabled
        print(f"LLM-Pre-Cache: {'aktiviert' if enabled else 'deaktiviert'}")

    def _load_llm_precache_setting(self):
        """Lädt die LLM-Pre-Cache Einstellung aus der Config."""
        try:
            from src.utils.config import get_config
            config = get_config()
            self._llm_precache_enabled = config.get("llm_precache_enabled", True)
            print(f"LLM-Pre-Cache: {'aktiviert' if self._llm_precache_enabled else 'deaktiviert'} (aus Config)")
        except Exception:
            pass  # Bei Fehler bleibt Default (True)


# Singleton-Instanz
_pdf_cache: Optional[PDFCache] = None


def get_pdf_cache() -> PDFCache:
    """Gibt die Singleton-Instanz des PDF-Cache zurück."""
    global _pdf_cache
    if _pdf_cache is None:
        _pdf_cache = PDFCache()
    return _pdf_cache
