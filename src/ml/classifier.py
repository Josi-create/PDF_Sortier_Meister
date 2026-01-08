"""
Lernfähiger Klassifikator für PDF Sortier Meister

Verwendet TF-IDF und Kosinus-Ähnlichkeit um PDFs basierend auf
ihrem Textinhalt einem Zielordner zuzuordnen.
"""

import pickle
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

        # Modell laden oder neu erstellen
        self._load_or_create_model()

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

        # Beste Übereinstimmungen finden
        folder_scores: dict[str, list[float]] = {}
        for idx, similarity in enumerate(similarities):
            if similarity > 0.1:  # Mindest-Ähnlichkeit
                entry = self.training_entries[idx]
                folder = entry.target_folder
                if folder not in folder_scores:
                    folder_scores[folder] = []
                folder_scores[folder].append(similarity)

        # Durchschnittliche Ähnlichkeit pro Ordner
        suggestions = []
        for folder, scores in folder_scores.items():
            avg_score = np.mean(scores)
            max_score = max(scores)
            # Gewichteter Score: 70% max, 30% avg
            combined_score = 0.7 * max_score + 0.3 * avg_score

            folder_path = Path(folder)
            if folder_path.exists():
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

        # Ordner nach Häufigkeit mit passenden Keywords
        folder_counts: dict[str, int] = {}
        for entry in entries:
            folder = entry.target_folder
            folder_counts[folder] = folder_counts.get(folder, 0) + 1

        suggestions = []
        total = sum(folder_counts.values())

        for folder, count in folder_counts.items():
            folder_path = Path(folder)
            if folder_path.exists():
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
        folders = self.db.get_most_used_folders(max_suggestions)

        suggestions = []
        for folder in folders:
            folder_path = Path(folder.path)
            if folder_path.exists():
                # Niedrige Konfidenz für Frequenz-basierte Vorschläge
                confidence = min(folder.usage_count / 100, 0.3)  # Max 30%
                suggestions.append(Suggestion(
                    folder_path=folder_path,
                    folder_name=folder.name,
                    confidence=confidence,
                    reason=f"Häufig verwendet ({folder.usage_count}x)",
                ))

        return suggestions

    def get_training_count(self) -> int:
        """Gibt die Anzahl der Trainingseinträge zurück."""
        return self.db.get_entry_count()


# Globale Klassifikator-Instanz
_classifier_instance: Optional[PDFClassifier] = None


def get_classifier() -> PDFClassifier:
    """Gibt die globale Klassifikator-Instanz zurück."""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = PDFClassifier()
    return _classifier_instance
