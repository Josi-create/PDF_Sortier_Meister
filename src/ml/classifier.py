"""
Lernfähiger Klassifikator für PDF Sortier Meister

Verwendet TF-IDF und Kosinus-Ähnlichkeit um PDFs basierend auf
ihrem Textinhalt einem Zielordner zuzuordnen.

Unterstützt hierarchische Ordnerstrukturen und Jahres-Muster-Erkennung.
"""

import pickle
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.utils.config import get_config
from src.utils.database import get_database, SortingHistory


@dataclass
class Suggestion:
    """Ein Sortiervorschlag."""
    folder_path: Path
    folder_name: str
    confidence: float  # 0.0 - 1.0
    reason: str  # Begründung für den Vorschlag
    relative_path: str = ""  # NEU: Relativer Pfad (z.B. "Steuer 2026/Banken")


class PDFClassifier:
    """
    Klassifikator für PDF-Dokumente.

    Lernt aus Benutzerentscheidungen und schlägt Zielordner vor.
    """

    def __init__(self):
        """Initialisiert den Klassifikator."""
        self.config = get_config()
        self.db = get_database()

        # TF-IDF Vectorizer für Textähnlichkeit
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.tfidf_matrix = None
        self.training_entries: list[SortingHistory] = []

        # Modell-Pfad
        self.model_path = self.config.model_dir / "classifier.pkl"

        # Cache für Ordner-Suche in den Zielordnern
        self._folder_cache: dict[str, Path] = {}
        self._folder_cache_roots: list[Path] = []

        # Modell laden oder neu erstellen
        self._load_or_create_model()

    def _find_folder_by_name(self, folder_name: str) -> Optional[Path]:
        """
        Sucht einen Ordner nach Namen in allen Zielordnern.

        Diese Methode ermöglicht das Matching von gelernten Ordnernamen
        auf einen neuen Zielordner - die Lerninhalte bleiben erhalten.

        Args:
            folder_name: Name des gesuchten Ordners

        Returns:
            Pfad zum gefundenen Ordner oder None
        """
        # Aktuelle Zielordner holen
        target_folders = self.config.get_target_folders()

        if not target_folders:
            return None

        # Cache invalidieren wenn Zielordner sich geändert haben
        if self._folder_cache_roots != target_folders:
            self._folder_cache = {}
            self._folder_cache_roots = target_folders.copy()
            self._build_folder_cache(target_folders)

        return self._folder_cache.get(folder_name.lower())

    def _build_folder_cache(self, root_folders: list[Path]):
        """Baut den Ordner-Cache für schnelle Suche auf."""
        self._folder_cache = {}
        for root_folder in root_folders:
            if not root_folder.exists():
                continue
            try:
                # Root-Ordner selbst auch hinzufügen
                self._folder_cache[root_folder.name.lower()] = root_folder
                # Alle Unterordner
                for folder in root_folder.rglob("*"):
                    if folder.is_dir() and not folder.name.startswith('.'):
                        # Lowercase für case-insensitive Matching
                        self._folder_cache[folder.name.lower()] = folder
            except PermissionError:
                pass

    def _resolve_folder_path(self, learned_folder: str, learned_name: str) -> Optional[Path]:
        """
        Löst einen gelernten Ordnerpfad auf - entweder direkt oder per Namen.

        Args:
            learned_folder: Der gelernte absolute Pfad
            learned_name: Der gelernte Ordnername

        Returns:
            Pfad zum existierenden Ordner oder None
        """
        # 1. Versuche den originalen Pfad
        original_path = Path(learned_folder)
        if original_path.exists():
            return original_path

        # 2. Suche nach Ordnernamen im aktuellen Zielordner
        found_path = self._find_folder_by_name(learned_name)
        if found_path:
            return found_path

        return None

    def _load_or_create_model(self):
        """Lädt ein bestehendes Modell oder erstellt ein neues."""
        if self.model_path.exists():
            try:
                self._load_model()
                print(f"Klassifikator geladen mit {len(self.training_entries)} Einträgen")
            except Exception as e:
                print(f"Fehler beim Laden des Modells: {e}")
                self._create_new_model()
        else:
            self._create_new_model()

    def _create_new_model(self):
        """Erstellt ein neues Modell basierend auf der Datenbank."""
        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            ngram_range=(1, 2),  # Uni- und Bigrams
            min_df=1,
            stop_words=None,  # Deutsche Stopwords werden manuell behandelt
        )

        # Trainiere mit bestehenden Daten
        self._retrain()

    def _load_model(self):
        """Lädt das Modell von der Festplatte."""
        with open(self.model_path, "rb") as f:
            data = pickle.load(f)
            self.vectorizer = data["vectorizer"]
            self.tfidf_matrix = data["tfidf_matrix"]
            self.training_entries = data["training_entries"]

    def _save_model(self):
        """Speichert das Modell auf der Festplatte."""
        data = {
            "vectorizer": self.vectorizer,
            "tfidf_matrix": self.tfidf_matrix,
            "training_entries": self.training_entries,
        }
        with open(self.model_path, "wb") as f:
            pickle.dump(data, f)

    def _retrain(self):
        """Trainiert das Modell mit allen Daten aus der Datenbank."""
        entries = self.db.get_entries_with_text()

        if not entries:
            self.training_entries = []
            self.tfidf_matrix = None
            return

        self.training_entries = entries
        texts = [self._preprocess_text(e.extracted_text) for e in entries]

        if texts and any(texts):
            self.tfidf_matrix = self.vectorizer.fit_transform(texts)
            self._save_model()
        else:
            self.tfidf_matrix = None

    def _preprocess_text(self, text: str) -> str:
        """
        Bereitet Text für die Vektorisierung vor.

        Args:
            text: Der zu verarbeitende Text

        Returns:
            Vorverarbeiteter Text
        """
        if not text:
            return ""

        # Kleinschreibung
        text = text.lower()

        # Deutsche Stopwords entfernen (einfache Liste)
        stopwords = {
            "der", "die", "das", "und", "in", "zu", "den", "von", "ist", "mit",
            "sich", "des", "auf", "für", "nicht", "ein", "eine", "als", "auch",
            "es", "an", "werden", "aus", "er", "hat", "dass", "sie", "nach",
            "wird", "bei", "einer", "um", "am", "sind", "noch", "wie", "einem",
            "über", "so", "zum", "kann", "nur", "ihr", "seine", "ich", "oder",
            "aber", "vor", "zur", "bis", "mehr", "durch", "man", "sehr", "diese",
            "wenn", "war", "haben", "wurde", "alle", "können", "diesem", "dieser",
        }

        words = text.split()
        words = [w for w in words if w not in stopwords and len(w) > 2]

        return " ".join(words)

    def learn(
        self,
        pdf_path: Path,
        target_folder: Path,
        extracted_text: str,
        keywords: list[str] = None,
        detected_date: str = None,
        new_filename: str = None,
        relative_path: str = None,
    ):
        """
        Lernt aus einer Benutzerentscheidung.

        Args:
            pdf_path: Pfad zur sortierten PDF
            target_folder: Gewählter Zielordner
            extracted_text: Extrahierter Text aus der PDF
            keywords: Erkannte Schlüsselwörter
            detected_date: Erkanntes Datum
            new_filename: Neuer Dateiname
            relative_path: Relativer Pfad (z.B. "Steuer 2026/Banken")
        """
        # In Datenbank speichern
        self.db.add_sorting_entry(
            original_filename=pdf_path.name,
            original_path=str(pdf_path),
            target_folder=str(target_folder),
            target_folder_name=target_folder.name,
            extracted_text=extracted_text,
            keywords=keywords,
            detected_date=detected_date,
            new_filename=new_filename,
            confidence=1.0,
            target_relative_path=relative_path,
        )

        # Modell neu trainieren
        self._retrain()

    def suggest(
        self,
        text: str,
        keywords: list[str] = None,
        max_suggestions: int = 5,
    ) -> list[Suggestion]:
        """
        Schlägt Zielordner für eine PDF vor.

        Args:
            text: Extrahierter Text aus der PDF
            keywords: Erkannte Schlüsselwörter
            max_suggestions: Maximale Anzahl Vorschläge

        Returns:
            Liste von Sortiervorschlägen, sortiert nach Konfidenz
        """
        suggestions = []

        # 1. Textbasierte Ähnlichkeit (wenn Trainingsdaten vorhanden)
        if self.tfidf_matrix is not None and text:
            text_suggestions = self._suggest_by_text_similarity(text, max_suggestions)
            suggestions.extend(text_suggestions)

        # 2. Schlüsselwort-basierte Vorschläge
        if keywords:
            keyword_suggestions = self._suggest_by_keywords(keywords, max_suggestions)
            for suggestion in keyword_suggestions:
                # Nur hinzufügen wenn noch nicht vorhanden
                if not any(s.folder_path == suggestion.folder_path for s in suggestions):
                    suggestions.append(suggestion)

        # 3. Häufig verwendete Ordner als Fallback
        if len(suggestions) < max_suggestions:
            frequent_suggestions = self._suggest_by_frequency(
                max_suggestions - len(suggestions)
            )
            for suggestion in frequent_suggestions:
                if not any(s.folder_path == suggestion.folder_path for s in suggestions):
                    suggestions.append(suggestion)

        # Nach Konfidenz sortieren
        suggestions.sort(key=lambda s: s.confidence, reverse=True)

        return suggestions[:max_suggestions]

    def _suggest_by_text_similarity(
        self, text: str, max_suggestions: int
    ) -> list[Suggestion]:
        """Schlägt Ordner basierend auf Textähnlichkeit vor."""
        if self.tfidf_matrix is None or not self.training_entries:
            return []

        # Text vektorisieren
        processed_text = self._preprocess_text(text)
        if not processed_text:
            return []

        try:
            query_vector = self.vectorizer.transform([processed_text])
        except Exception:
            return []

        # Ähnlichkeiten berechnen
        similarities = cosine_similarity(query_vector, self.tfidf_matrix)[0]

        # Beste Übereinstimmungen finden - gruppiert nach Ordnernamen
        # (nicht nach absolutem Pfad, damit Wechsel des Zielordners funktioniert)
        folder_scores: dict[str, tuple[str, list[float]]] = {}  # name -> (learned_path, scores)
        for idx, similarity in enumerate(similarities):
            if similarity > 0.1:  # Mindest-Ähnlichkeit
                entry = self.training_entries[idx]
                folder_name = entry.target_folder_name
                if folder_name not in folder_scores:
                    folder_scores[folder_name] = (entry.target_folder, [])
                folder_scores[folder_name][1].append(similarity)

        # Durchschnittliche Ähnlichkeit pro Ordner
        suggestions = []
        for folder_name, (learned_path, scores) in folder_scores.items():
            avg_score = np.mean(scores)
            max_score = max(scores)
            # Gewichteter Score: 70% max, 30% avg
            combined_score = 0.7 * max_score + 0.3 * avg_score

            # Ordner im aktuellen Zielordner finden (oder Original wenn noch da)
            folder_path = self._resolve_folder_path(learned_path, folder_name)
            if folder_path:
                suggestions.append(Suggestion(
                    folder_path=folder_path,
                    folder_name=folder_path.name,
                    confidence=min(combined_score, 0.95),  # Max 95%
                    reason=f"Ähnlicher Inhalt ({int(combined_score * 100)}%)",
                ))

        suggestions.sort(key=lambda s: s.confidence, reverse=True)
        return suggestions[:max_suggestions]

    def _suggest_by_keywords(
        self, keywords: list[str], max_suggestions: int
    ) -> list[Suggestion]:
        """Schlägt Ordner basierend auf Schlüsselwörtern vor."""
        entries = self.db.search_similar_keywords(keywords)

        if not entries:
            return []

        # Ordner nach Häufigkeit mit passenden Keywords - gruppiert nach Namen
        folder_counts: dict[str, tuple[str, int]] = {}  # name -> (learned_path, count)
        for entry in entries:
            folder_name = entry.target_folder_name
            if folder_name not in folder_counts:
                folder_counts[folder_name] = (entry.target_folder, 0)
            folder_counts[folder_name] = (
                folder_counts[folder_name][0],
                folder_counts[folder_name][1] + 1
            )

        suggestions = []
        total = sum(count for _, count in folder_counts.values())

        for folder_name, (learned_path, count) in folder_counts.items():
            # Ordner im aktuellen Zielordner finden
            folder_path = self._resolve_folder_path(learned_path, folder_name)
            if folder_path:
                confidence = min(count / total * 0.8, 0.8)  # Max 80%
                suggestions.append(Suggestion(
                    folder_path=folder_path,
                    folder_name=folder_path.name,
                    confidence=confidence,
                    reason=f"Ähnliche Schlüsselwörter",
                ))

        suggestions.sort(key=lambda s: s.confidence, reverse=True)
        return suggestions[:max_suggestions]

    def _suggest_by_frequency(self, max_suggestions: int) -> list[Suggestion]:
        """Schlägt häufig verwendete Ordner vor."""
        folders = self.db.get_most_used_folders(max_suggestions * 2)  # Mehr holen für Fallbacks

        suggestions = []
        for folder in folders:
            # Ordner im aktuellen Zielordner finden
            folder_path = self._resolve_folder_path(folder.path, folder.name)
            if folder_path:
                # Niedrige Konfidenz für Frequenz-basierte Vorschläge
                confidence = min(folder.usage_count / 100, 0.3)  # Max 30%
                suggestions.append(Suggestion(
                    folder_path=folder_path,
                    folder_name=folder_path.name,
                    confidence=confidence,
                    reason=f"Häufig verwendet ({folder.usage_count}x)",
                ))
                if len(suggestions) >= max_suggestions:
                    break

        return suggestions

    def get_training_count(self) -> int:
        """Gibt die Anzahl der Trainingseinträge zurück."""
        return self.db.get_entry_count()

    def suggest_with_subfolders(
        self,
        text: str,
        keywords: list[str] = None,
        detected_date: str = None,
        root_folders: list[Path] = None,
        max_suggestions: int = 5,
    ) -> list[Suggestion]:
        """
        Schlägt Zielordner inkl. Unterordner vor.

        Berücksichtigt hierarchische Strukturen und aktualisiert Jahreszahlen.

        Args:
            text: Extrahierter Text aus der PDF
            keywords: Erkannte Schlüsselwörter
            detected_date: Erkanntes Datum (für Jahres-Erkennung)
            root_folders: Liste der Root-Ordner
            max_suggestions: Maximale Anzahl Vorschläge

        Returns:
            Liste von Sortiervorschlägen mit relativen Pfaden
        """
        # Basis-Vorschläge holen
        base_suggestions = self.suggest(text, keywords, max_suggestions * 2)

        # Aktuelles Jahr für Muster-Erkennung
        current_year = datetime.now().year
        detected_year = self._extract_year_from_date(detected_date)

        suggestions = []
        for s in base_suggestions:
            # Relativen Pfad berechnen
            relative_path = self._get_relative_path(s.folder_path, root_folders)

            # Jahres-Muster aktualisieren
            updated_path, updated_relative = self._update_year_pattern(
                s.folder_path,
                relative_path,
                detected_year or current_year
            )

            # Neuen Suggestion mit rel. Pfad erstellen
            updated_suggestion = Suggestion(
                folder_path=updated_path,
                folder_name=updated_path.name,
                confidence=s.confidence,
                reason=s.reason,
                relative_path=updated_relative
            )

            # Duplikate vermeiden
            if not any(
                existing.folder_path == updated_suggestion.folder_path
                for existing in suggestions
            ):
                suggestions.append(updated_suggestion)

        return suggestions[:max_suggestions]

    def _get_relative_path(
        self,
        folder_path: Path,
        root_folders: list[Path] = None
    ) -> str:
        """Berechnet den relativen Pfad eines Ordners."""
        if not root_folders:
            return folder_path.name

        for root in root_folders:
            try:
                relative = folder_path.relative_to(root)
                if str(relative) == '.':
                    return root.name
                return f"{root.name}/{relative}"
            except ValueError:
                continue

        return folder_path.name

    def _extract_year_from_date(self, date_str: str) -> Optional[int]:
        """Extrahiert das Jahr aus einem Datum-String."""
        if not date_str:
            return None

        # Verschiedene Formate unterstützen
        year_match = re.search(r'20\d{2}', date_str)
        if year_match:
            return int(year_match.group())
        return None

    def _update_year_pattern(
        self,
        folder_path: Path,
        relative_path: str,
        target_year: int
    ) -> tuple[Path, str]:
        """
        NICHT automatisch Jahreszahlen aktualisieren!

        Ein Dokument mit Datum 2026 kann trotzdem für "Steuer 2025" sein
        (z.B. Lohnsteuerbescheinigung 2025 kommt im Januar 2026).

        Stattdessen: Originalen Vorschlag behalten. Die Jahres-Variante
        wird separat als Alternative angeboten wenn verfügbar.

        Args:
            folder_path: Absoluter Pfad
            relative_path: Relativer Pfad
            target_year: Zieljahr (aus Dokument-Datum)

        Returns:
            Tuple (Original-Pfad, Original-relativer-Pfad) - NICHT geändert
        """
        # Keine automatische Jahresanpassung mehr!
        # Der Benutzer entscheidet selbst, ob das Dokument für 2025 oder 2026 ist.
        return folder_path, relative_path

    def suggest_subfolder_for_parent(
        self,
        parent_folder: Path,
        text: str,
        keywords: list[str] = None,
        max_suggestions: int = 3,
    ) -> list[Suggestion]:
        """
        Schlägt Unterordner für einen bereits gewählten Parent-Ordner vor.

        Args:
            parent_folder: Der übergeordnete Ordner
            text: Extrahierter Text aus der PDF
            keywords: Erkannte Schlüsselwörter
            max_suggestions: Maximale Anzahl

        Returns:
            Liste von Unterordner-Vorschlägen
        """
        suggestions = []

        # 1. Gelernte Unterordner aus der Datenbank
        learned_subfolders = self.db.get_subfolders_for_parent(str(parent_folder))

        for folder_entry in learned_subfolders[:max_suggestions * 2]:
            # Ordner im aktuellen Zielordner finden
            folder_path = self._resolve_folder_path(folder_entry.path, folder_entry.name)
            if folder_path:
                confidence = min(folder_entry.usage_count / 50, 0.8)
                suggestions.append(Suggestion(
                    folder_path=folder_path,
                    folder_name=folder_path.name,
                    confidence=confidence,
                    reason=f"Gelernt ({folder_entry.usage_count}x verwendet)",
                    relative_path=folder_entry.relative_path or folder_entry.name,
                ))
                if len(suggestions) >= max_suggestions:
                    break

        # 2. Existierende Unterordner als Fallback
        if len(suggestions) < max_suggestions:
            try:
                existing_subfolders = [
                    p for p in parent_folder.iterdir()
                    if p.is_dir() and not p.name.startswith('.')
                ]

                for subfolder in existing_subfolders[:max_suggestions - len(suggestions)]:
                    if not any(s.folder_path == subfolder for s in suggestions):
                        suggestions.append(Suggestion(
                            folder_path=subfolder,
                            folder_name=subfolder.name,
                            confidence=0.2,
                            reason="Existierender Unterordner",
                            relative_path=subfolder.name,
                        ))
            except PermissionError:
                pass

        return suggestions[:max_suggestions]


# Globale Klassifikator-Instanz
_classifier_instance: Optional[PDFClassifier] = None


def get_classifier() -> PDFClassifier:
    """Gibt die globale Klassifikator-Instanz zurück."""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = PDFClassifier()
    return _classifier_instance
