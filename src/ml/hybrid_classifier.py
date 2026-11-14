"""
Hybrid-Klassifikator für PDF Sortier Meister

Kombiniert lokale TF-IDF Klassifikation mit optionaler LLM-Unterstützung
für bessere Sortier- und Benennungsvorschläge.

GPL-3.0-or-later - Copyright (c) 2026
"""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import logging

from src.ml.classifier import PDFClassifier, Suggestion, get_classifier
from src.ml.llm_provider import LLMProvider, LLMResponse, LLMProviderType
from src.ml.claude_provider import ClaudeProvider
from src.ml.openai_provider import OpenAIProvider
from src.ml.poe_provider import PoeProvider
from src.ml.openrouter_provider import OpenRouterProvider
from src.ml.ollama_provider import OllamaProvider, OllamaCloudProvider
from src.ml.strata_provider import StrataProvider
from src.ml.lmstudio_provider import LMStudioProvider
from src.ml.provider_factory import (
    GRUND_FEHLER, GRUND_KEINE_EINWILLIGUNG, erzeuge_provider,
)
from src.utils.config import get_config
from src.utils.database import get_database
from src.i18n import tr

logger = logging.getLogger(__name__)


def _provider_klassen() -> dict[str, type]:
    """Provider-Klassen aus *diesem* Modul fuer die Fabrik (Issue #166/#167).

    Die Fabrik (src.ml.provider_factory) kennt die Klassen selbst; hier werden
    die Modul-Namen durchgereicht, damit Tests, die z.B.
    ``hybrid_classifier.ClaudeProvider`` per monkeypatch ersetzen, weiter greifen.
    """
    return {
        "claude": ClaudeProvider,
        "openai": OpenAIProvider,
        "poe": PoeProvider,
        "openrouter": OpenRouterProvider,
        "ollama": OllamaProvider,
        "ollama_cloud": OllamaCloudProvider,
        "strata": StrataProvider,
        "lmstudio": LMStudioProvider,
    }


def source_folder_hint(pdf_path) -> Optional[str]:
    """Name des Ordners, in dem die PDF liegt - als Hinweis fuer den KI-Prompt (Issue #132).

    "Briefe 2004" verraet das Jahr, wenn OCR das Datum nicht lesen konnte.
    Fuer den Scan-Ordner selbst (Posteingang) gibt es keinen Hinweis.
    """
    try:
        parent = Path(pdf_path).parent
        scan_root = get_config().get_scan_folder()
        if scan_root and parent.resolve() == Path(scan_root).resolve():
            return None
        return parent.name or None
    except Exception:
        return None


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
    metadata: Optional[dict] = None  # Extrahierte Metadaten (nur bei LLM)


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
        # Letzter Fehler des KI-Aufrufs (Dateiname/Metadaten) - wird vom
        # Pre-Cache-Worker und dem Detail-Panel angezeigt, statt still zu scheitern
        self.last_llm_error: Optional[str] = None

        # LLM-Provider initialisieren falls konfiguriert
        self._init_llm_provider()

    def _init_llm_provider(self):
        """Initialisiert den LLM-Provider basierend auf Konfiguration.

        Die Regeln (kein Provider, Cloud-Einwilligung, API-Key, Provider-
        Zuordnung) liegen in :func:`src.ml.provider_factory.erzeuge_provider`,
        die auch der Chat fuer sein eigenes Modell nutzt (Issue #166/#167).
        """
        llm_config = self.config.get("llm", {}) or {}
        provider, grund = erzeuge_provider(llm_config, klassen=_provider_klassen())

        if grund == GRUND_KEINE_EINWILLIGUNG:
            logger.warning(
                "Cloud-Provider '%s' konfiguriert, aber keine Einwilligung "
                "zur Datenuebertragung erteilt. LLM bleibt deaktiviert.",
                llm_config.get("provider", "none"),
            )
        elif grund.startswith(GRUND_FEHLER):
            print(f"Fehler bei LLM-Initialisierung: {grund[len(GRUND_FEHLER):]}")

        if provider is None:
            self.llm_enabled = False
            return

        self.llm_provider = provider
        try:
            self.llm_enabled = provider.is_available()
        except Exception as e:
            print(f"Fehler bei LLM-Initialisierung: {e}")
            self.llm_enabled = False

    def set_llm_provider(
        self,
        provider_type: LLMProviderType,
        api_key: str,
        model: str = "",
        base_url: str = "",
    ) -> bool:
        """
        Setzt den LLM-Provider zur Laufzeit.

        Args:
            provider_type: Art des Providers (claude, openai, poe, openrouter, ollama,
                ollama_cloud, strata, lmstudio, none)
            api_key: API-Key (bei Ollama und LM Studio ignoriert)
            model: Modellname (optional)
            base_url: Server-URL (lokale Server: Ollama, Strata, LM Studio)

        Returns:
            True wenn der Provider erfolgreich aktiviert wurde.
        """
        pt = provider_type.value if hasattr(provider_type, "value") else str(provider_type)
        if pt == LLMProviderType.NONE.value:
            self.llm_provider = None
            self.llm_enabled = False
            return False

        # Standard-Modell je nach Provider (getattr: Tests ersetzen Klassen durch Stubs)
        default_models = {
            "claude": "haiku",
            "openai": "gpt-4o-mini",
            "poe": "GPT-4o-Mini",
            "openrouter": getattr(OpenRouterProvider, "DEFAULT_MODEL", ""),
            "ollama": getattr(OllamaProvider, "DEFAULT_MODEL", ""),
            "ollama_cloud": getattr(OllamaCloudProvider, "DEFAULT_MODEL", ""),
            "lmstudio": getattr(LMStudioProvider, "DEFAULT_MODEL", ""),
        }
        llm_config = {
            "provider": pt,
            "api_key": api_key,
            "model": model or default_models.get(pt, ""),
            "base_url": base_url,
        }
        # Cloud-Einwilligung gilt global und kommt aus der gespeicherten Konfiguration.
        consent = (self.config.get("llm", {}) or {}).get("cloud_consent", False)
        provider, grund = erzeuge_provider(
            llm_config, cloud_consent=consent, klassen=_provider_klassen(),
        )

        if provider is None:
            if grund.startswith(GRUND_FEHLER):
                print(f"Fehler bei LLM-Konfiguration: {grund[len(GRUND_FEHLER):]}")
            else:
                # keine Einwilligung / kein Key / unbekannt: Provider verwerfen
                self.llm_provider = None
            self.llm_enabled = False
            return False

        self.llm_provider = provider
        try:
            self.llm_enabled = provider.is_available()
        except Exception as e:
            print(f"Fehler bei LLM-Konfiguration: {e}")
            self.llm_enabled = False

        return self.llm_enabled

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
            matching_local.reason = tr("{reason} + LLM bestätigt").format(reason=matching_local.reason)
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
        file_date: str = None,
        source_folder: str = None,
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
            file_date: Änderungsdatum der Datei (Fallback)
            source_folder: Name des Quellordners als Hinweis fuer die KI (Issue #132)

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
                text, current_filename, keywords, detected_date, target_folder, file_date,
                source_folder,
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

    def _rename_examples(self, text: str, keywords: list[str] | None) -> list[str]:
        """Dateinamen, die der Nutzer fuer aehnliche Dokumente gewaehlt hat.

        Gehen als Stil-Beispiele in den KI-Prompt; was der Nutzer danach
        waehlt oder korrigiert, wird beim naechsten Mal selbst zum Beispiel.
        """
        try:
            entries = get_database().get_rename_examples(text, keywords, limit=5)
        except Exception as e:  # noqa: BLE001 - Beispiele sind optional
            logger.debug(f"Historien-Beispiele nicht verfuegbar: {e}")
            return []
        return [e.new_filename for e in entries if e.new_filename]

    def _similar_documents_info(
        self, text: str, keywords, detected_date: str | None, file_date: str | None,
    ) -> str:
        """Prompt-Abschnitt: wo liegen aehnliche, bereits einsortierte Dokumente?

        Aus Sortierhistorie und Suchindex; mit Jahres-Hinweis, damit eine
        Rechnung von 2026 nicht wegen eines Zwillings in "Steuer 2024" landet.
        """
        try:
            from src.core.similar_documents import (
                describe_similar_for_prompt, find_similar_documents, vorschlag_jahr,
            )
            config = get_config()
            roots = config.get_target_folders()
            if not roots:
                return ""
            similar = find_similar_documents(text, keywords, roots, db=get_database(), limit=5)
            # Issue #254: Bezugsjahr im Text ("Bescheid fuer 2020") vor dem Briefdatum
            info = describe_similar_for_prompt(
                similar, vorschlag_jahr(text, detected_date, file_date=file_date), roots)
        except Exception as e:  # noqa: BLE001 - Kontext ist optional
            logger.debug(f"Aehnliche Dokumente nicht verfuegbar: {e}")
            return ""
        # Issue #116: vorhandene Ordner als relative Pfade; die KI darf dann
        # auch einen neuen Pfad unter einem Zielordner nennen
        try:
            from src.core import neuer_ordner
            if neuer_ordner.aktiv(config):
                info += neuer_ordner.ordnerliste_fuer_prompt(roots)
        except Exception as e:  # noqa: BLE001 - Kontext ist optional
            logger.debug(f"Ordnerliste fuer den Prompt nicht verfuegbar: {e}")
        return info

    def _get_llm_filename_suggestion(
        self,
        text: str,
        current_filename: str,
        keywords: list[str],
        detected_date: str,
        target_folder: str,
        file_date: str = None,
        source_folder: str = None,
    ) -> Optional[HybridFilename]:
        """Holt einen Dateinamenvorschlag vom LLM."""
        if not self.llm_provider:
            return None

        self.last_llm_error = None
        response = self.llm_provider.suggest_filename(
            text=text,
            current_filename=current_filename,
            keywords=keywords,
            detected_date=detected_date,
            target_folder=target_folder,
            file_date=file_date,
            examples=self._rename_examples(text, keywords),
            source_folder=source_folder,
            similar_info=self._similar_documents_info(text, keywords, detected_date, file_date),
        )

        self.total_tokens_used += response.tokens_used

        if not response.success:
            self.last_llm_error = response.error_message or tr("KI-Aufruf fehlgeschlagen.")
            return None
        if not response.filename_suggestion:
            self.last_llm_error = tr("KI hat keinen Dateinamen geliefert.")
            return None
        self.last_llm_error = None

        # Letzte Instanz: keine verbotenen/ungluecklichen Zeichen (., @, ...)
        from src.utils.filename_sanitizer import sanitize_filename
        clean_name = sanitize_filename(response.filename_suggestion)
        if not clean_name:
            self.last_llm_error = tr("KI-Dateiname bestand nur aus ungueltigen Zeichen.")
            return None

        return HybridFilename(
            filename=clean_name,
            reason=response.filename_reason or "LLM-Vorschlag",
            confidence=response.confidence,
            source="llm",
            metadata=response.metadata,
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

    def get_llm_model_name(self, short: bool = False) -> str:
        """Gibt die Modell-ID des aktiven Providers zurueck (leer, wenn keins).

        Args:
            short: Anbieter-Praefix wie "z-ai/" (OpenRouter) weglassen - fuer
                   die knappe Anzeige in der Statusleiste.
        """
        if not self.llm_enabled or not self.llm_provider:
            return ""
        model = ""
        getter = getattr(self.llm_provider, "_get_model_id", None)
        if callable(getter):
            try:
                model = getter() or ""
            except Exception:
                model = ""
        if not model:
            model = getattr(getattr(self.llm_provider, "config", None), "model", "") or ""
        if short and "/" in model:
            model = model.rsplit("/", 1)[-1]
        return model

    def check_llm_connection(self) -> Optional[tuple[bool, str]]:
        """Prueft, ob ein lokaler LLM-Server (Ollama, Strata, LM Studio) gerade antwortet.

        Blockiert bis zu einigen Sekunden - nur im Hintergrund aufrufen.

        Returns:
            (erreichbar, Detail) oder None, wenn nichts zu pruefen ist
            (kein Provider aktiv oder Cloud-Anbieter).
        """
        provider = self.llm_provider
        if not self.llm_connection_checkable():
            return None
        ok, detail = provider.ping()
        if not ok or not isinstance(provider, OllamaProvider):
            return ok, detail
        # Ollama antwortet auch ohne das eingestellte Modell - dann scheitert
        # trotzdem jeder Aufruf. Deshalb das Modell mitpruefen.
        model = provider._get_model_id()
        installed = provider.list_models()
        if not _ollama_model_installed(model, installed):
            return False, (tr(
                "Modell „{model}“ ist in Ollama nicht installiert ({anzahl} Modell(e) "
                "vorhanden)."
            ).format(model=model, anzahl=len(installed)))
        return True, detail

    def llm_connection_checkable(self) -> bool:
        """True, wenn der aktive Provider ein lokaler Server mit ping() ist."""
        provider = self.llm_provider
        if not self.llm_enabled or provider is None:
            return False
        if isinstance(provider, OllamaCloudProvider):
            return False
        return isinstance(provider, (OllamaProvider, StrataProvider))

    def get_llm_provider_name(self) -> str:
        """Gibt den Namen des aktuellen LLM-Providers zurück."""
        if not self.llm_enabled or not self.llm_provider:
            return tr("Keiner")
        if isinstance(self.llm_provider, ClaudeProvider):
            return "Claude"
        if isinstance(self.llm_provider, OpenRouterProvider):
            return "OpenRouter"
        if isinstance(self.llm_provider, LMStudioProvider):
            return "LM Studio"
        if isinstance(self.llm_provider, StrataProvider):
            return "Strata"
        if isinstance(self.llm_provider, OpenAIProvider):
            return "OpenAI"
        if isinstance(self.llm_provider, PoeProvider):
            return "Poe"
        if isinstance(self.llm_provider, OllamaCloudProvider):
            return "Ollama Cloud"
        if isinstance(self.llm_provider, OllamaProvider):
            return "Ollama"
        return tr("Unbekannt")


def _ollama_model_installed(model: str, installed: list[str]) -> bool:
    """Ollama-Modellnamen vergleichen; ":latest" ist optional."""
    def norm(name: str) -> str:
        name = (name or "").strip().lower()
        return name[:-len(":latest")] if name.endswith(":latest") else name
    want = norm(model)
    return bool(want) and any(norm(n) == want for n in installed)


# Globale Instanz
_hybrid_classifier: Optional[HybridClassifier] = None


def get_hybrid_classifier() -> HybridClassifier:
    """Gibt die globale Hybrid-Klassifikator-Instanz zurück."""
    global _hybrid_classifier
    if _hybrid_classifier is None:
        _hybrid_classifier = HybridClassifier()
    return _hybrid_classifier
