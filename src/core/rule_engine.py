"""
RuleEngine fuer automatische PDF-Sortierung (Phase 21 / Issue #22).

Wertet eine Liste von Regeln gegen ein PDF-Metadaten-Dict aus und wendet
die Aktionen der passenden Regeln an. Regeln werden in der Datenbank
(siehe ``Database.add_rule`` / ``list_rules``) als JSON persistiert.

Regel-Schema (Python-Dict):
    {
        "id": int,
        "name": str,
        "priority": int,         # hoeher = wichtiger
        "enabled": bool,
        "conditions": list[dict],  # UND-verknuepft
        "actions": list[dict],
    }

Bedingungs-Dicts (siehe ``evaluate_condition``):
    {"type": "korrespondent", "operator": "equals|contains", "value": str}
    {"type": "kategorie",     "operator": "equals|in",      "value": str|list}
    {"type": "betrag",        "operator": "gt|gte|lt|lte|between",
     "value": float | [min, max]}
    {"type": "datum",         "operator": "after|before|between",
     "value": "YYYY-MM-DD" | [iso1, iso2]}
    {"type": "keywords",      "operator": "any|all", "value": list[str]}

Aktions-Dicts (siehe ``apply_actions``):
    {"type": "target_folder",    "template": "Steuern/{steuerjahr}"}
    {"type": "filename_pattern", "template": "{datum}_{korrespondent}.pdf"}
    {"type": "metadata_field",   "field": "steuerjahr", "value": "auto"}
    {"type": "tag",              "value": "steuerlich-relevant"}

Konfidenz-Berechnung (siehe ``evaluate_condition``):
    * Alle Bedingungen matchen exakt: 1.0
    * N von M Bedingungen matchen:     N / M
    * "contains"-Operator:             0.8 (statt 1.0)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# --------------------------------------------------------------------------- #
# Konstanten
# --------------------------------------------------------------------------- #

# Unterstuetzte Bedingungs-Operatoren je Typ (fuer GUI-Validierung / Doku).
CONDITION_OPERATORS: dict[str, list[str]] = {
    "korrespondent": ["equals", "contains"],
    "kategorie":     ["equals", "in"],
    "betrag":        ["gt", "gte", "lt", "lte", "between"],
    "datum":         ["after", "before", "between"],
    "keywords":      ["any", "all"],
}


@dataclass
class RuleMatch:
    """Ergebnis einer einzelnen Regel-Auswertung.

    Attributes:
        rule: Die volle Regel (Dict aus ``Database.list_rules``).
        confidence: Konfidenz zwischen 0.0 und 1.0 (siehe Modul-Docstring).
        matched_actions: Liste der Aktions-Dicts dieser Regel, die als
            ``valid`` markiert wurden (z.B. target_folder-Aktionen mit
            existierenden Ordnern).
    """

    rule: dict
    confidence: float
    matched_actions: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# RuleEngine
# --------------------------------------------------------------------------- #


class RuleEngine:
    """Wertet Automatisierungs-Regeln gegen PDF-Metadaten aus.

    Args:
        db: ``Database``-Instanz, aus der die Regeln gelesen werden.
            Wird in ``evaluate`` per ``db.list_rules(enabled_only=True)``
            abgefragt.
    """

    def __init__(self, db: Any):
        self.db = db

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def evaluate(
        self,
        pdf_metadata: dict,
        available_folders: Optional[list[str]] = None,
    ) -> list[RuleMatch]:
        """Wertet alle aktivierten Regeln gegen ``pdf_metadata`` aus.

        Nur ``enabled=True``-Regeln werden beruecksichtigt. Deaktivierte
        oder fehlerhafte Regeln (z.B. unbekannter ``type``) werden
        uebersprungen und tauchen nicht im Ergebnis auf.

        Args:
            pdf_metadata: Metadaten-Dict einer PDF (z.B. aus
                ``PDFMetadata.to_dict()`` oder extrahierten LLM-Daten).
                Erwartete Schluessel: ``korrespondent``, ``kategorie``,
                ``betrag_brutto``/``betrag``/``betrag_netto``,
                ``datum``/``buchungsdatum``, ``keywords`` (list[str]).
            available_folders: Optionale Liste existierender Zielordner.
                ``target_folder``-Aktionen mit einem Pfad, der nicht
                in dieser Liste vorkommt, werden aus
                ``RuleMatch.matched_actions`` entfernt.

        Returns:
            Liste von ``RuleMatch``-Objekten, sortiert nach
            ``rule['priority']`` DESC (stabil).
        """
        rules = self.db.list_rules(enabled_only=True)

        matches: list[RuleMatch] = []
        for rule in rules:
            try:
                confidence = self._match_rule(rule, pdf_metadata)
            except Exception:
                # Defensive: bei Fehlern in einer Regel nicht die
                # gesamte Auswertung abbrechen.
                continue
            if confidence is None:
                # Regel wurde uebersprungen (unbekannter type o.ae.)
                continue
            if confidence <= 0.0:
                continue

            valid_actions = self._filter_actions_for_available_folders(
                rule.get("actions", []) or [],
                available_folders,
            )
            matches.append(
                RuleMatch(
                    rule=rule,
                    confidence=float(confidence),
                    matched_actions=valid_actions,
                )
            )

        # Sortierung nach priority DESC, dann id ASC (stabil).
        matches.sort(
            key=lambda m: (
                -(m.rule.get("priority") or 0),
                m.rule.get("id") or 0,
            )
        )
        return matches

    def apply_actions(
        self,
        actions: list[dict],
        pdf_metadata: dict,
    ) -> dict:
        """Wendet eine Liste von Aktionen auf das Metadaten-Dict an.

        Aktionen werden in Reihenfolge des Inputs angewendet. Mehrfaches
        Setzen desselben Feldes ist erlaubt (die letzte Aktion gewinnt).
        ``tag``-Aktionen werden zur Liste ``metadata['tags']`` zusammengefuehrt
        (Initialisierung als ``[]`` falls nicht vorhanden).

        Unterstuetzte Platzhalter in ``template``-Strings:
            ``{datum}``, ``{steuerjahr}``, ``{korrespondent}``,
            ``{kategorie}``, ``{betrag_brutto}``, ``{betrag_netto}``.

        Args:
            actions: Liste von Aktions-Dicts (siehe Modul-Docstring).
            pdf_metadata: Eingabe-Metadaten (wird NICHT mutiert).

        Returns:
            Neues Metadaten-Dict mit den angewendeten Aktionen.
        """
        if actions is None:
            actions = []
        if pdf_metadata is None:
            pdf_metadata = {}

        # Defensive Kopie, damit das Input-Dict nicht mutiert wird.
        result = dict(pdf_metadata)

        # Tags-Liste initialisieren (Mengenoperationen ermoeglichen).
        if "tags" not in result or not isinstance(result.get("tags"), list):
            result["tags"] = []

        for action in actions or []:
            if not isinstance(action, dict):
                continue
            atype = action.get("type")
            if atype == "target_folder":
                template = action.get("template") or ""
                result["target_folder"] = self._render_template(template, result)
            elif atype == "filename_pattern":
                template = action.get("template") or ""
                result["filename_pattern"] = self._render_template(template, result)
            elif atype == "metadata_field":
                field_name = action.get("field")
                if not field_name:
                    continue
                value = action.get("value")
                # "auto" als Sonderwert: lasse Feld unveraendert
                if value == "auto":
                    continue
                result[field_name] = value
            elif atype == "tag":
                tag = action.get("value")
                if tag is None:
                    continue
                tag_str = str(tag).strip()
                if not tag_str:
                    continue
                if tag_str not in result["tags"]:
                    result["tags"].append(tag_str)
            # Unbekannte Aktions-Typen werden ignoriert.

        return result

    # --------------------------------------------------------------------- #
    # Interne Helfer: Bedingungsauswertung
    # --------------------------------------------------------------------- #

    def _match_rule(self, rule: dict, pdf_metadata: dict) -> Optional[float]:
        """Berechnet die Konfidenz fuer eine Regel.

        Returns:
            ``None`` wenn die Regel uebersprungen werden soll (z.B.
            unbekannter ``type``), sonst Konfidenz im Bereich [0.0, 1.0].
        """
        conditions = rule.get("conditions") or []
        if not isinstance(conditions, list):
            return None

        # Leere Bedingungs-Liste: Regel matcht immer (confidence=1.0).
        if not conditions:
            return 1.0

        if pdf_metadata is None:
            pdf_metadata = {}

        scores: list[float] = []
        for cond in conditions:
            if not isinstance(cond, dict):
                # Kaputte Bedingung: ueberspringen.
                return None
            score = self.evaluate_condition(cond, pdf_metadata)
            if score is None:
                # Unbekannter Typ / Operator: gesamte Regel ueberspringen.
                return None
            scores.append(score)

        if not scores:
            return 1.0
        # Anteil der matchenden Bedingungen. "contains" zaehlt als 0.8,
        # alles andere als 1.0 (siehe evaluate_condition).
        return sum(scores) / len(scores)

    def evaluate_condition(self, cond: dict, pdf_metadata: dict) -> Optional[float]:
        """Wertet eine einzelne Bedingung aus.

        Returns:
            ``None`` bei unbekanntem ``type``/``operator`` (Aufrufer
            soll die Regel ueberspringen).
            ``1.0`` fuer exakten Match, ``0.8`` fuer "contains",
            ``0.0`` bei Nicht-Match.
        """
        if not isinstance(cond, dict):
            # Kaputte Bedingung (None, String, ...) -> ueberspringen.
            return None

        ctype = cond.get("type")
        operator = cond.get("operator")
        value = cond.get("value", None)

        if ctype == "korrespondent":
            return self._match_string(
                pdf_metadata.get("korrespondent"), operator, value
            )
        if ctype == "kategorie":
            return self._match_kategorie(
                pdf_metadata.get("kategorie"), operator, value
            )
        if ctype == "betrag":
            actual = self._extract_betrag(pdf_metadata)
            return self._match_betrag(actual, operator, value)
        if ctype == "datum":
            actual = self._extract_datum(pdf_metadata)
            return self._match_datum(actual, operator, value)
        if ctype == "keywords":
            keywords = self._extract_keywords(pdf_metadata)
            return self._match_keywords(keywords, operator, value)

        # Unbekannter Bedingungstyp -> Regel ueberspringen.
        return None

    # -- String-Operatoren -- #

    def _match_string(
        self,
        actual: Any,
        operator: Optional[str],
        expected: Any,
    ) -> Optional[float]:
        if operator not in ("equals", "contains"):
            return None
        a = self._norm_str(actual)
        e = self._norm_str(expected)
        if a is None or e is None:
            # Fehlender Wert: kein Match (nicht ueberspringen).
            return 0.0
        if operator == "equals":
            return 1.0 if a == e else 0.0
        # contains: Substring-Match, Konfidenz 0.8
        if e == "":
            return 0.0
        return 0.8 if e in a else 0.0

    # -- Kategorie -- #

    def _match_kategorie(
        self,
        actual: Any,
        operator: Optional[str],
        expected: Any,
    ) -> Optional[float]:
        if operator not in ("equals", "in"):
            return None
        a = self._norm_str(actual)
        if operator == "equals":
            e = self._norm_str(expected)
            if a is None or e is None:
                return 0.0
            return 1.0 if a == e else 0.0
        # "in": actual muss in der Liste vorkommen
        if not isinstance(expected, (list, tuple)):
            return None
        if a is None:
            return 0.0
        for item in expected:
            if self._norm_str(item) == a:
                return 1.0
        return 0.0

    # -- Betrag -- #

    @staticmethod
    def _extract_betrag(pdf_metadata: dict) -> Optional[float]:
        """Liest den relevantesten Betrag aus dem Metadaten-Dict.

        Reihenfolge: ``betrag_brutto`` → ``betrag`` → ``betrag_netto``.
        Strings mit Komma werden zu ``float`` normalisiert.
        """
        for key in ("betrag_brutto", "betrag", "betrag_netto"):
            value = pdf_metadata.get(key)
            if value is None or value == "":
                continue
            try:
                return float(str(value).replace(",", ".").replace(" ", ""))
            except (ValueError, TypeError):
                continue
        return None

    def _match_betrag(
        self,
        actual: Optional[float],
        operator: Optional[str],
        expected: Any,
    ) -> Optional[float]:
        if operator not in ("gt", "gte", "lt", "lte", "between"):
            return None
        if actual is None:
            return 0.0

        if operator == "between":
            if not isinstance(expected, (list, tuple)) or len(expected) != 2:
                return None
            try:
                lo = float(expected[0])
                hi = float(expected[1])
            except (ValueError, TypeError):
                return None
            return 1.0 if lo <= actual <= hi else 0.0

        try:
            threshold = float(expected)
        except (ValueError, TypeError):
            return None

        if operator == "gt":
            return 1.0 if actual > threshold else 0.0
        if operator == "gte":
            return 1.0 if actual >= threshold else 0.0
        if operator == "lt":
            return 1.0 if actual < threshold else 0.0
        if operator == "lte":
            return 1.0 if actual <= threshold else 0.0
        return None

    # -- Datum -- #

    @staticmethod
    def _extract_datum(pdf_metadata: dict) -> Optional[str]:
        """Liest ein ISO-Datum aus dem Metadaten-Dict.

        Bevorzugt ``datum`` → ``buchungsdatum``. Akzeptiert sowohl reine
        ISO-Strings (``YYYY-MM-DD``) als auch laengere ISO-Strings
        (``YYYY-MM-DDTHH:MM:SS``). Rueckgabe ist immer der 10-stellige
        Praefix, damit lexikografischer Vergleich funktioniert.
        """
        for key in ("datum", "buchungsdatum", "detected_date"):
            value = pdf_metadata.get(key)
            if value is None or value == "":
                continue
            s = str(value).strip()
            if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
                return s[:10]
        return None

    def _match_datum(
        self,
        actual: Optional[str],
        operator: Optional[str],
        expected: Any,
    ) -> Optional[float]:
        if operator not in ("after", "before", "between"):
            return None
        if actual is None:
            return 0.0

        if operator == "between":
            if not isinstance(expected, (list, tuple)) or len(expected) != 2:
                return None
            lo = self._norm_iso(expected[0])
            hi = self._norm_iso(expected[1])
            if lo is None or hi is None:
                return None
            return 1.0 if lo <= actual <= hi else 0.0

        ref = self._norm_iso(expected)
        if ref is None:
            return None

        if operator == "after":
            return 1.0 if actual > ref else 0.0
        if operator == "before":
            return 1.0 if actual < ref else 0.0
        return None

    # -- Keywords -- #

    @staticmethod
    def _extract_keywords(pdf_metadata: dict) -> list[str]:
        """Liest eine normalisierte Keyword-Liste.

        Akzeptiert:
            * ``list``/``tuple`` von Strings
            * Komma-getrennter String (z.B. aus ``PDFAnalysisResult.keywords``)
        """
        value = pdf_metadata.get("keywords")
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(v).strip().lower() for v in value if str(v).strip()]
        if isinstance(value, str):
            return [
                p.strip().lower() for p in value.split(",") if p.strip()
            ]
        return []

    def _match_keywords(
        self,
        keywords: list[str],
        operator: Optional[str],
        expected: Any,
    ) -> Optional[float]:
        if operator not in ("any", "all"):
            return None
        if not isinstance(expected, (list, tuple)):
            return None
        exp_norm = [
            str(v).strip().lower() for v in expected if str(v).strip()
        ]
        if not exp_norm:
            return 0.0
        kw_set = set(keywords or [])
        if operator == "any":
            return 1.0 if any(k in kw_set for k in exp_norm) else 0.0
        # "all"
        return 1.0 if all(k in kw_set for k in exp_norm) else 0.0

    # --------------------------------------------------------------------- #
    # Interne Helfer: Templates / Aktionen
    # --------------------------------------------------------------------- #

    @staticmethod
    def _render_template(template: str, metadata: dict) -> str:
        """Ersetzt Platzhalter ``{key}`` im Template durch Metadaten-Werte.

        Fehlende Schluessel werden durch ``""`` ersetzt. Dies ist bewusst
        permissiv, damit ein verschobener Platzhalter das Ergebnis nicht
        unbrauchbar macht.
        """
        if not template:
            return ""
        if metadata is None:
            return template

        # Bevorzugte Aliasse fuer haeufige Platzhalter.
        aliases = {
            "datum": metadata.get("datum")
                     or metadata.get("buchungsdatum")
                     or metadata.get("detected_date")
                     or "",
            "steuerjahr": str(metadata.get("steuerjahr") or ""),
            "korrespondent": str(metadata.get("korrespondent") or ""),
            "kategorie": str(metadata.get("kategorie") or ""),
            "betrag_brutto": str(metadata.get("betrag_brutto") or ""),
            "betrag_netto": str(metadata.get("betrag_netto") or ""),
        }

        result = template
        for key, alias_value in aliases.items():
            result = result.replace("{" + key + "}", alias_value)
        # Unbekannte Platzhalter: belassen (besser als leerer String,
        # damit der Nutzer fehlende Konfiguration erkennen kann).
        return result

    def _filter_actions_for_available_folders(
        self,
        actions: list[dict],
        available_folders: Optional[list[str]],
    ) -> list[dict]:
        """Filtert ``target_folder``-Aktionen mit nicht-existenten Ordnern.

        Wenn ``available_folders`` ``None`` ist, werden alle Aktionen
        zurueckgegeben. Andernfalls nur die, deren gerenderter Pfad in
        ``available_folders`` enthalten ist.
        """
        if available_folders is None:
            return list(actions or [])
        if not actions:
            return []
        result = []
        for action in actions or []:
            if not isinstance(action, dict):
                continue
            if action.get("type") != "target_folder":
                result.append(action)
                continue
            template = action.get("template") or ""
            # Ohne Metadaten koennen wir den Pfad nicht aufloesen -
            # in dem Fall bleiben wir permissiv.
            rendered = template  # ohne Metadaten unveraendert lassen
            if rendered in available_folders:
                result.append(action)
        return result

    # --------------------------------------------------------------------- #
    # Kleine String-Helfer
    # --------------------------------------------------------------------- #

    @staticmethod
    def _norm_str(value: Any) -> Optional[str]:
        """Normalisiert einen String-Wert (lowercase + strip) oder gibt ``None`` zurueck."""
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        return s.lower()

    @staticmethod
    def _norm_iso(value: Any) -> Optional[str]:
        """Normalisiert einen ISO-Datum-String auf YYYY-MM-DD oder gibt ``None`` zurueck."""
        if value is None:
            return None
        s = str(value).strip()
        if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
            return s[:10]
        return None