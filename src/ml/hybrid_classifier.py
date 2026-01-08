"""
Hybrid-Klassifikator für PDF Sortier Meister

Kombiniert lokale TF-IDF Klassifikation mit optionaler LLM-Unterstützung
für bessere Sortier- und Benennungsvorschläge.

MIT License - Copyright (c) 2026
"""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from src.ml.classifier import PDFClassifier, Suggestion, get_classifier
from src.ml.llm_provider import LLMProvider, LLMConfig, LLMResponse, LLMProviderType
from src.ml.claude_provider import ClaudeProvider
from src.ml.openai_provider import OpenAIProvider
from src.utils.config import get_config


@dataclass
class HybridSuggestion:
    """Ein Sortiervorschlag aus dem Hybrid-System."""
    folder_path: Path
    folder_name: str
    confidence: float  # 0.0 - 1.0
    reason: str
    source: str  # "local", "llm", "hybrid"


@dataclass
class HybridFilename:
    """Ein Dateinamenvorschlag aus dem Hybrid-System."""
    filename: str
    reason: str
    confidence: float  # 0.0 - 1.0
    source: str  # "local", "llm"


class HybridClassifier:
    """
    Hybrid-Klassifikator der lokale ML-Modelle mit LLM kombiniert.

    Strategie:
    1. Immer zuerst lokale TF-IDF Klassifikation
    2. LLM optional für:
       - Niedrige lokale Konfidenz (< threshold)
       - Explizite Benutzeranfrage
       - Komplexe Dokumente
    3. Kombinierte Konfidenzberechnung
    """

    # Konfidenz-Schwellenwerte
    LOCAL_CONFIDENCE_THRESHOLD = 0.6  # Ab hier kein LLM nötig
    LLM_WEIGHT = 0.4  # Gewichtung des LLM bei Kombination
    LOCAL_WEIGHT = 0.6  # Gewichtung des lokalen Klassifikators

    def __init__(self):
        """Initialisiert den Hybrid-Klassifikator."""
        self.config = get_config()
        self.local_classifier = get_classifier()
        self.llm_provider: Optional[LLMProvider] = None
        self.llm_enabled = False
        self.total_tokens_used = 0

        # LLM-Provider initialisieren falls konfiguriert
        self._init_llm_provider()

    def _init_llm_provider(self):
        """Initialisiert den LLM-Provider basierend auf Konfiguration."""
        llm_config = self.config.get("llm", {})
        provider_type = llm_config.get("provider", "none")
        api_key = llm_config.get("api_key", "")
        model = llm_config.get("model", "")

        if not api_key or provider_type == "none":
            self.llm_enabled = False
            return

        config = LLMConfig(
            api_key=api_key,
            model=model,
            max_tokens=llm_config.get("max_tokens", 500),
            temperature=llm_config.get("temperature", 0.3),
        )

        try:
            if provider_type == "claude":
                self.llm_provider = ClaudeProvider(config)
            elif provider_type == "openai":
                self.llm_provider = OpenAIProvider(config)

            self.llm_enabled = (
                self.llm_provider is not None
                and self.llm_provider.is_available()
            )
        except Exception as e:
            print(f"Fehler bei LLM-Initialisierung: {e}")
            self.llm_enabled = False

    def set_llm_provider(
        self,
        provider_type: LLMProviderType,
        api_key: str,
        model: str = "",
    ):
        """
        Setzt den LLM-Provider zur Laufzeit.

        Args:
            provider_type: Art des Providers (claude, openai, none)
            api_key: API-Key
            model: Modellname (optional)
        """
        if provider_type == LLMProviderType.NONE or not api_key:
            self.llm_provider = None
            self.llm_enabled = False
            return

        config = LLMConfig(
            api_key=api_key,
            model=model or ("haiku" if provider_type == LLMProviderType.CLAUDE else "gpt-4o-mini"),
        )

        try:
            if provider_type == LLMProviderType.CLAUDE:
                self.llm_provider = ClaudeProvider(config)
            elif provider_type == LLMProviderType.OPENAI:
                self.llm_provider = OpenAIProvider(config)

            self.llm_enabled = (
                self.llm_provider is not None
                and self.llm_provider.is_available()
            )
        except Exception as e:
            print(f"Fehler bei LLM-Konfiguration: {e}")
            self.llm_enabled = False

    def suggest_folders(
        self,
        text: str,
        keywords: list[str] = None,
        available_folders: list[Path] = None,
        use_llm: bool = None,
        max_suggestions: int = 5,
    ) -> list[HybridSuggestion]:
        """
        Schlägt Zielordner für ein Dokument vor.

        Args:
            text: Extrahierter Text aus dem Dokument
            keywords: Erkannte Schlüsselwörter
            available_folders: Liste der verfügbaren Zielordner
            use_llm: LLM verwenden? None = automatisch entscheiden
            max_suggestions: Maximale Anzahl Vorschläge

        Returns:
            Liste von Sortiervorschlägen
        """
        suggestions = []

        # 1. Lokale Klassifikation
        local_suggestions = self.local_classifier.suggest(
            text, keywords, max_suggestions
        )

        # Lokale Vorschläge in HybridSuggestion konvertieren
        for s in local_suggestions:
            suggestions.append(HybridSuggestion(
                folder_path=s.folder_path,
                folder_name=s.folder_name,
                confidence=s.confidence,
                reason=s.reason,
                source="local",
            ))

        # 2. LLM verwenden wenn:
        #    - Explizit angefordert, ODER
        #    - Automatisch & (keine Vorschläge ODER niedrige Konfidenz)
        should_use_llm = False
        if use_llm is True:
            should_use_llm = True
        elif use_llm is None and self.llm_enabled:
            # Automatische Entscheidung
            if not suggestions:
                should_use_llm = True
            elif suggestions[0].confidence < self.LOCAL_CONFIDENCE_THRESHOLD:
                should_use_llm = True

        if should_use_llm and self.llm_enabled and available_folders:
            llm_suggestion = self._get_llm_folder_suggestion(
                text, keywords, available_folders
            )
            if llm_suggestion:
                suggestions = self._merge_suggestions(
                    suggestions, llm_suggestion, available_folders
                )

        # Nach Konfidenz sortieren
        suggestions.sort(key=lambda s: s.confidence, reverse=True)
        return suggestions[:max_suggestions]

    def _get_llm_folder_suggestion(
        self,
        text: str,
        keywords: list[str],
        available_folders: list[Path],
    ) -> Optional[HybridSuggestion]:
        """Holt einen Ordnervorschlag vom LLM."""
        if not self.llm_provider:
            return None

        folder_names = [f.name for f in available_folders]
        response = self.llm_provider.classify_document(
            text=text,
            available_folders=folder_names,
            keywords=keywords,
        )

        self.total_tokens_used += response.tokens_used

        if not response.success or not response.folder_suggestion:
            return None

        # Ordner-Pfad finden
        folder_path = None
        for f in available_folders:
            if f.name == response.folder_suggestion:
                folder_path = f
                break

        if not folder_path:
            return None

        return HybridSuggestion(
            folder_path=folder_path,
            folder_name=response.folder_suggestion,
            confidence=response.confidence,
            reason=response.folder_reason or "LLM-Empfehlung",
            source="llm",
        )

    def _merge_suggestions(
        self,
        local: list[HybridSuggestion],
        llm: HybridSuggestion,
        available_folders: list[Path],
    ) -> list[HybridSuggestion]:
        """
        Kombiniert lokale und LLM-Vorschläge.

        Args:
            local: Lokale Vorschläge
            llm: LLM-Vorschlag
            available_folders: Verfügbare Ordner

        Returns:
            Kombinierte Liste
        """
        # Prüfen ob LLM-Vorschlag schon in lokalen ist
        matching_local = None
        for s in local:
            if s.folder_path == llm.folder_path:
                matching_local = s
                break

        if matching_local:
            # Kombinierte Konfidenz berechnen
            combined_confidence = (
                self.LOCAL_WEIGHT * matching_local.confidence
                + self.LLM_WEIGHT * llm.confidence
            )
            matching_local.confidence = min(combined_confidence, 0.98)
            matching_local.reason = f"{matching_local.reason} + LLM bestätigt"
            matching_local.source = "hybrid"
        else:
            # LLM-Vorschlag hinzufügen
            local.append(llm)

        return local

    def suggest_filename(
        self,
        text: str,
        current_filename: str,
        keywords: list[str] = None,
        detected_date: str = None,
        target_folder: str = None,
        use_llm: bool = None,
    ) -> list[HybridFilename]:
        """
        Schlägt Dateinamen für ein Dokument vor.

        Args:
            text: Extrahierter Text aus dem Dokument
            current_filename: Aktueller Dateiname
            keywords: Erkannte Schlüsselwörter
            detected_date: Erkanntes Datum
            target_folder: Zielordner
            use_llm: LLM verwenden?

        Returns:
            Liste von Dateinamenvorschlägen
        """
        suggestions = []

        # 1. Lokale regelbasierte Vorschläge (aus rename_dialog.py Logik)
        local_names = self._generate_local_filename_suggestions(
            current_filename, keywords, detected_date
        )
        for name, reason, confidence in local_names:
            suggestions.append(HybridFilename(
                filename=name,
                reason=reason,
                confidence=confidence,
                source="local",
            ))

        # 2. LLM-Vorschlag wenn gewünscht
        if (use_llm or use_llm is None) and self.llm_enabled:
            llm_suggestion = self._get_llm_filename_suggestion(
                text, current_filename, keywords, detected_date, target_folder
            )
            if llm_suggestion:
                # LLM-Vorschlag an erster Stelle wenn Konfidenz hoch
                if llm_suggestion.confidence > 0.7:
                    suggestions.insert(0, llm_suggestion)
                else:
                    suggestions.append(llm_suggestion)

        return suggestions

    def _generate_local_filename_suggestions(
        self,
        current_filename: str,
        keywords: list[str],
        detected_date: str,
    ) -> list[tuple[str, str, float]]:
        """
        Generiert lokale Dateinamenvorschläge.

        Returns:
            Liste von (filename, reason, confidence) Tupeln
        """
        suggestions = []
        base_name = current_filename.replace(".pdf", "").replace(".PDF", "")

        # Datum-basierter Name
        if detected_date:
            date_name = f"{detected_date}_{base_name}.pdf"
            suggestions.append((
                date_name,
                f"Mit erkanntem Datum ({detected_date})",
                0.7,
            ))

        # Schlüsselwort-basierter Name
        if keywords:
            # Kategorie aus erstem Keyword
            category = keywords[0] if keywords else ""
            if detected_date:
                keyword_name = f"{detected_date}_{category}.pdf"
                suggestions.append((
                    keyword_name,
                    f"Datum + Kategorie ({category})",
                    0.75,
                ))
            else:
                keyword_name = f"{category}_{base_name}.pdf"
                suggestions.append((
                    keyword_name,
                    f"Mit Kategorie ({category})",
                    0.6,
                ))

        return suggestions

    def _get_llm_filename_suggestion(
        self,
        text: str,
        current_filename: str,
        keywords: list[str],
        detected_date: str,
        target_folder: str,
    ) -> Optional[HybridFilename]:
        """Holt einen Dateinamenvorschlag vom LLM."""
        if not self.llm_provider:
            return None

        response = self.llm_provider.suggest_filename(
            text=text,
            current_filename=current_filename,
            keywords=keywords,
            detected_date=detected_date,
            target_folder=target_folder,
        )

        self.total_tokens_used += response.tokens_used

        if not response.success or not response.filename_suggestion:
            return None

        return HybridFilename(
            filename=response.filename_suggestion,
            reason=response.filename_reason or "LLM-Vorschlag",
            confidence=response.confidence,
            source="llm",
        )

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

        Delegiert an den lokalen Klassifikator.
        """
        self.local_classifier.learn(
            pdf_path=pdf_path,
            target_folder=target_folder,
            extracted_text=extracted_text,
            keywords=keywords,
            detected_date=detected_date,
            new_filename=new_filename,
        )

    def get_training_count(self) -> int:
        """Gibt die Anzahl der Trainingseinträge zurück."""
        return self.local_classifier.get_training_count()

    def get_tokens_used(self) -> int:
        """Gibt die Gesamtzahl der verwendeten Tokens zurück."""
        return self.total_tokens_used

    def is_llm_available(self) -> bool:
        """Prüft ob ein LLM-Provider verfügbar ist."""
        return self.llm_enabled

    def get_llm_provider_name(self) -> str:
        """Gibt den Namen des aktuellen LLM-Providers zurück."""
        if not self.llm_enabled or not self.llm_provider:
            return "Keiner"
        if isinstance(self.llm_provider, ClaudeProvider):
            return "Claude"
        if isinstance(self.llm_provider, OpenAIProvider):
            return "OpenAI"
        return "Unbekannt"


# Globale Instanz
_hybrid_classifier: Optional[HybridClassifier] = None


def get_hybrid_classifier() -> HybridClassifier:
    """Gibt die globale Hybrid-Klassifikator-Instanz zurück."""
    global _hybrid_classifier
    if _hybrid_classifier is None:
        _hybrid_classifier = HybridClassifier()
    return _hybrid_classifier
