"""
Konfigurationsverwaltung für PDF Sortier Meister
"""

import json
import os
from pathlib import Path
from typing import Any


class Config:
    """Verwaltet die Anwendungskonfiguration."""

    # Standard-Konfigurationswerte
    DEFAULTS = {
        "scan_folder": "",  # Wird beim ersten Start gesetzt
        "target_folders": [],  # Liste der Zielordner
        "window_width": 1200,
        "window_height": 800,
        "thumbnail_size": 150,
        "backup_check_days": 7,
        "language": "de",
        "theme": "light",
        "last_used_folders": [],  # Zuletzt verwendete Zielordner
        "max_suggestions": 5,  # Maximale Anzahl Sortiervorschläge
        # LLM-Konfiguration
        "llm": {
            "provider": "none",  # "none", "claude", "openai"
            "api_key": "",
            "model": "",  # z.B. "haiku", "sonnet", "gpt-4o-mini"
            "max_tokens": 500,
            "temperature": 0.3,
            "auto_use": False,  # LLM automatisch bei niedriger Konfidenz
        },
    }

    def __init__(self, config_path: str = None):
        """
        Initialisiert die Konfiguration.

        Args:
            config_path: Pfad zur Konfigurationsdatei.
                        Standard: AppData/PDF_Sortier_Meister/config.json
        """
        if config_path is None:
            app_data = os.environ.get("APPDATA", os.path.expanduser("~"))
            config_dir = Path(app_data) / "PDF_Sortier_Meister"
            config_dir.mkdir(parents=True, exist_ok=True)
            self.config_path = config_dir / "config.json"
        else:
            self.config_path = Path(config_path)

        self._config = self.DEFAULTS.copy()
        self.load()

    def load(self) -> None:
        """Lädt die Konfiguration aus der Datei."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    # Merge mit Defaults (für neue Konfigurationsoptionen)
                    self._config = {**self.DEFAULTS, **loaded}
            except (json.JSONDecodeError, IOError) as e:
                print(f"Fehler beim Laden der Konfiguration: {e}")
                self._config = self.DEFAULTS.copy()

    def save(self) -> None:
        """Speichert die Konfiguration in die Datei."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"Fehler beim Speichern der Konfiguration: {e}")

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

    def is_llm_configured(self) -> bool:
        """Prüft ob ein LLM-Provider konfiguriert ist."""
        llm_config = self.get_llm_config()
        return (
            llm_config.get("provider", "none") != "none"
            and bool(llm_config.get("api_key", ""))
        )


# Globale Konfigurationsinstanz
_config_instance: Config = None


def get_config() -> Config:
    """Gibt die globale Konfigurationsinstanz zurück."""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance
