"""
Konfigurationsverwaltung für PDF Sortier Meister
"""

import copy
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.utils.platform_paths import get_app_data_dir

logger = logging.getLogger("pdf_sortier_meister.config")


@dataclass
class ChatConfig:
    """Konfiguration fuer das RAG-Chat-Feature (Phase 19 / M1).

    Werte sind so gewaehlt, dass das System auch mit kleinen lokalen
    Modellen (z.B. llama3.1 8B via Ollama) sicher laeuft.

    Attributes:
        max_context_docs: Maximale Anzahl an Dokumenten im Kontext
            (Top-K). Default 8 (Architektur-Vorgabe).
        max_history_turns: Anzahl der Konversations-Turns, die im
            Prompt beruecksichtigt werden (= N/2 Frage-Antwort-Paare).
            Default 4.
        snippet_max_chars: Maximale Laenge des Text-Snippets pro
            retrieved Document. Default 2000.
        cache_size: Anzahl der Q&A-Paare im LRU-Cache. Default 100.
        max_text_length: Maximale Laenge des ``extracted_text``-Felds
            beim Bulk-Index/Insert (Architektur-Entscheidung Q3, 5000).
    """
    max_context_docs: int = 8
    max_history_turns: int = 4
    snippet_max_chars: int = 2000
    cache_size: int = 100
    max_text_length: int = 5000


class Config:
    """Verwaltet die Anwendungskonfiguration."""

    # Standard-Konfigurationswerte
    DEFAULTS = {
        "scan_folder": "",  # Wird beim ersten Start gesetzt
        "target_folders": [],  # Liste der Zielordner
        "window_width": 1200,
        "window_height": 800,
        "window_maximized": True,
        "thumbnail_size": 150,
        "backup_check_days": 7,
        "language": "de",
        "theme": "light",
        "last_used_folders": [],  # Zuletzt verwendete Zielordner
        "max_suggestions": 5,  # Maximale Anzahl Sortiervorschläge
        # Persönliche Daten (damit das System den Benutzer kennt)
        "owner_name": "",           # z.B. "Johannes Härle-Wack"
        "owner_name_variants": "",  # Weitere Namensvarianten, kommagetrennt
        "owner_company": "",        # Eigene Firma (falls vorhanden)
        "owner_address": "",        # Adresse (für Erkennung auf Dokumenten)
        "owner_emails": "",         # Eigene E-Mail-Adressen (kommagetrennt)
        "owner_initials": "",       # z.B. "JW" - fuer {initialen} in Dateinamen
        # Benutzerdefiniertes Dateinamen-Muster (leer = LLM-Default).
        # Wird als Few-Shot-Hinweis in den Filename-Prompt eingeflochten.
        "filename_pattern": "",
        # Dateiname aus Ordnerstruktur beim Verschieben (Issue #42), Opt-in.
        "folder_naming_enabled": False,
        "folder_naming_template": "{initialen} {ordnernummern}-{datum}-{text}",
        # LLM-Konfiguration
        "llm": {
            # Gueltige Werte: "none", "claude", "openai", "poe",
            # "openrouter", "ollama", "ollama_cloud".
            # "poe" war in 0.19.0 kurzzeitig entfernt (Issue #66) und wird
            # wieder unterstuetzt - poe.com vergibt wieder API-Keys.
            "provider": "none",
            "api_key": "",  # Key des aktiven Providers (Spiegel von api_keys)
            "api_keys": {},  # API-Keys pro Provider, z.B. {"openrouter": "...", "poe": "..."}
            "model": "",  # z.B. "haiku", "sonnet", "gpt-4o-mini", "llama3.1"
            "max_tokens": 2000,  # Reasoning-Modelle (GLM, DeepSeek-R1, ...) brauchen Luft
            "temperature": 0.3,
            "auto_use": False,  # LLM automatisch bei niedriger Konfidenz
            "base_url": "",  # nur fuer Ollama (lokaler Server)
            # Gecachte Modell-Liste pro Provider (gefuellt durch "Modelle aktualisieren")
            "cached_models": {},
            "cloud_consent": False,  # Opt-in fuer Cloud-Uebertragung von PDF-Inhalten
        },
        # Backup-Hinweis beim Start (Issue #7) abgehakt?
        "backup_hint_dismissed": False,
        # Erste-Schritte-Hinweis beim Start (Issue #51) abgehakt?
        "first_steps_hint_dismissed": False,
        # Update-Pruefung beim Start (Issue #73): fragt nur die Versionsnummer
        # des neuesten GitHub-Releases ab, sendet keine Nutzerdaten.
        "update_check_enabled": True,
        # Vom Nutzer per "Diese Version ueberspringen" ausgeblendete Version
        "update_skipped_version": "",
        # PDF oeffnen per Doppelklick (Issues #74/#76):
        # "integrated" (Vorschau-Fenster) | "system" (Standardprogramm) | "custom"
        "pdf_open_mode": "integrated",
        "pdf_open_command": "",  # Pfad zum eigenen Programm bei "custom"
        "preview_window_geometry": [],  # [x, y, w, h] des Vorschau-Fensters
        "detail_splitter_sizes": [],  # [Details, Vorschau] im mittleren Panel
    }

    def __init__(self, config_path: str = None):
        """
        Initialisiert die Konfiguration.

        Args:
            config_path: Pfad zur Konfigurationsdatei.
                        Standard: AppData/PDF_Sortier_Meister/config.json
        """
        if config_path is None:
            config_dir = get_app_data_dir()
            self.config_path = config_dir / "config.json"
        else:
            self.config_path = Path(config_path)

        self._config = copy.deepcopy(self.DEFAULTS)
        self.load()

    def load(self) -> None:
        """Lädt die Konfiguration aus der Datei."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    # Merge mit Defaults (für neue Konfigurationsoptionen)
                    self._config = {**copy.deepcopy(self.DEFAULTS), **loaded}
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Fehler beim Laden der Konfiguration: {e}")
                self._config = copy.deepcopy(self.DEFAULTS)
            else:
                self._migrate()

    # Alter App-Default fuer llm.max_tokens (bis 0.20.0). Reasoning-Modelle
    # verbrauchen damit das ganze Budget fuers Nachdenken und liefern leere
    # Antworten - deshalb wird der alte Default beim Laden angehoben.
    LEGACY_MAX_TOKENS = 500

    def _migrate(self) -> None:
        """Hebt veraltete Werte aus aelteren Versionen an."""
        changed = False

        llm = self._config.get("llm")
        if isinstance(llm, dict) and llm.get("max_tokens") == self.LEGACY_MAX_TOKENS:
            llm["max_tokens"] = self.DEFAULTS["llm"]["max_tokens"]
            logger.info(
                f"Konfiguration: llm.max_tokens {self.LEGACY_MAX_TOKENS} -> "
                f"{llm['max_tokens']} angehoben (alter Default, zu klein fuer Reasoning-Modelle)"
            )
            changed = True

        # Initialen (bis 0.21 unter "folder_naming_initials") -> owner_initials
        legacy_initials = (self._config.pop("folder_naming_initials", "") or "").strip()
        if legacy_initials and not self._config.get("owner_initials"):
            self._config["owner_initials"] = legacy_initials
            logger.info("Konfiguration: folder_naming_initials -> owner_initials uebernommen")
            changed = True

        # Dateinamen-Muster: Grosswort-Schreibweise -> {platzhalter}-Syntax
        pattern = self._config.get("filename_pattern", "") or ""
        if pattern:
            from src.core.filename_placeholders import migrate_legacy_pattern
            migrated = migrate_legacy_pattern(pattern)
            if migrated != pattern:
                self._config["filename_pattern"] = migrated
                logger.info(f"Konfiguration: filename_pattern '{pattern}' -> '{migrated}'")
                changed = True

        if changed:
            self.save()

    def save(self) -> None:
        """Speichert die Konfiguration in die Datei."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Fehler beim Speichern der Konfiguration: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Gibt einen Konfigurationswert zurück.

        Args:
            key: Der Konfigurationsschlüssel
            default: Standardwert, falls Schlüssel nicht existiert

        Returns:
            Der Konfigurationswert
        """
        return self._config.get(key, default)

    def set(self, key: str, value: Any, auto_save: bool = True) -> None:
        """
        Setzt einen Konfigurationswert.

        Args:
            key: Der Konfigurationsschlüssel
            value: Der zu setzende Wert
            auto_save: Automatisch speichern nach Änderung
        """
        self._config[key] = value
        if auto_save:
            self.save()

    def get_scan_folder(self) -> Path:
        """Gibt den Scan-Ordner als Path zurück."""
        folder = self.get("scan_folder", "")
        return Path(folder) if folder else None

    def set_scan_folder(self, folder: str | Path) -> None:
        """Setzt den Scan-Ordner."""
        self.set("scan_folder", str(folder))

    def get_target_folders(self) -> list[Path]:
        """Gibt die Liste der Zielordner zurück."""
        folders = self.get("target_folders", [])
        return [Path(f) for f in folders]

    def add_target_folder(self, folder: str | Path) -> None:
        """Fügt einen Zielordner hinzu."""
        folders = self.get("target_folders", [])
        folder_str = str(folder)
        if folder_str not in folders:
            folders.append(folder_str)
            self.set("target_folders", folders)

    def remove_target_folder(self, folder: str | Path) -> None:
        """Entfernt einen Zielordner."""
        folders = self.get("target_folders", [])
        folder_str = str(folder)
        if folder_str in folders:
            folders.remove(folder_str)
            self.set("target_folders", folders)

    def add_to_last_used(self, folder: str | Path) -> None:
        """Fügt einen Ordner zur Liste der zuletzt verwendeten hinzu."""
        last_used = self.get("last_used_folders", [])
        folder_str = str(folder)

        # Entferne wenn bereits vorhanden (wird ans Ende verschoben)
        if folder_str in last_used:
            last_used.remove(folder_str)

        # Ans Ende hinzufügen
        last_used.append(folder_str)

        # Maximal 20 Einträge behalten
        if len(last_used) > 20:
            last_used = last_used[-20:]

        self.set("last_used_folders", last_used)

    @property
    def data_dir(self) -> Path:
        """Gibt das Datenverzeichnis der Anwendung zurück."""
        return self.config_path.parent

    @property
    def database_path(self) -> Path:
        """Gibt den Pfad zur Datenbank zurück."""
        return self.data_dir / "history.db"

    @property
    def model_dir(self) -> Path:
        """Gibt das Verzeichnis für ML-Modelle zurück."""
        model_dir = self.data_dir / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        return model_dir

    # LLM-Konfigurationsmethoden
    def get_llm_config(self) -> dict:
        """Gibt die LLM-Konfiguration zurück."""
        return self.get("llm", self.DEFAULTS["llm"])

    def dialog_start_dir(self) -> str:
        """Startverzeichnis fuer Ordner-Dialoge: Parent des Scan-Ordners (Issue #11)."""
        scan = self.get_scan_folder()
        if not scan:
            return ""
        scan = Path(scan)
        parent = scan.parent
        if parent != scan and parent.exists():
            return str(parent)
        return str(scan) if scan.exists() else ""

    def set_llm_provider(self, provider: str) -> None:
        """
        Setzt den LLM-Provider.

        Args:
            provider: "none", "claude", oder "openai"
        """
        llm_config = self.get_llm_config()
        llm_config["provider"] = provider
        self.set("llm", llm_config)

    def set_llm_api_key(self, api_key: str) -> None:
        """
        Setzt den LLM API-Key.

        Args:
            api_key: Der API-Key
        """
        llm_config = self.get_llm_config()
        llm_config["api_key"] = api_key
        provider = llm_config.get("provider", "none")
        if provider not in ("none", "ollama"):
            api_keys = dict(llm_config.get("api_keys", {}))
            api_keys[provider] = api_key
            llm_config["api_keys"] = api_keys
        self.set("llm", llm_config)

    def set_llm_model(self, model: str) -> None:
        """
        Setzt das LLM-Modell.

        Args:
            model: Modellname (z.B. "haiku", "gpt-4o-mini")
        """
        llm_config = self.get_llm_config()
        llm_config["model"] = model
        self.set("llm", llm_config)

    def set_llm_auto_use(self, auto_use: bool) -> None:
        """
        Aktiviert/deaktiviert automatische LLM-Nutzung.

        Args:
            auto_use: True für automatische Nutzung bei niedriger Konfidenz
        """
        llm_config = self.get_llm_config()
        llm_config["auto_use"] = auto_use
        self.set("llm", llm_config)

    def get_cached_models(self, provider: str) -> list[str]:
        """Gibt die gecachte Modell-Liste fuer einen Provider zurueck."""
        llm_config = self.get_llm_config()
        cached = llm_config.get("cached_models", {})
        return cached.get(provider, [])

    def set_cached_models(self, provider: str, models: list[str]) -> None:
        """Speichert die abgerufene Modell-Liste fuer einen Provider."""
        llm_config = self.get_llm_config()
        cached = llm_config.get("cached_models", {})
        cached[provider] = list(models)
        llm_config["cached_models"] = cached
        self.set("llm", llm_config)

    def is_llm_configured(self) -> bool:
        """Prüft ob ein LLM-Provider konfiguriert ist."""
        llm_config = self.get_llm_config()
        return (
            llm_config.get("provider", "none") != "none"
            and bool(llm_config.get("api_key", ""))
        )

    # ChatConfig (RAG-Chat, Phase 19 / M1)
    def get_chat_config(self) -> ChatConfig:
        """Gibt die Chat/RAG-Konfiguration zurueck.

        Liest den ``"chat"``-Block aus der JSON-Config und merged ihn
        mit den ``ChatConfig``-Defaults. Fehlt der Block komplett,
        werden die Defaults unveraendert zurueckgegeben.
        """
        raw = self.get("chat", {}) or {}
        if not isinstance(raw, dict):
            raw = {}
        # Nur bekannte Felder uebernehmen, damit Tippfehler in der JSON
        # nicht zu stillen Defaultueberschreibungen werden.
        known = {f for f in ChatConfig.__dataclass_fields__}
        cleaned = {k: raw[k] for k in raw if k in known}
        return ChatConfig(**cleaned)


# Globale Konfigurationsinstanz
_config_instance: Config = None


def get_config() -> Config:
    """Gibt die globale Konfigurationsinstanz zurück."""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance
