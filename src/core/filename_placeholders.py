"""Platzhalter fuer das Dateinamen-Muster (Einstellungen > Dateinamen).

Eine Syntax fuer alles: ``{datum}``, ``{kontakt}``, ``{betreff}`` ... Das
Muster ist ein Hinweis an die KI; die Beschreibungen hier werden in den
Prompt uebernommen, damit jeder Platzhalter fuer das Modell dieselbe
Bedeutung hat wie fuer den Nutzer. Unbekannte Platzhalter (``{lieferant}``)
gehen als Freitext-Bezeichnung an die KI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Placeholder:
    key: str
    label: str        # Kurzbedeutung fuer die Legende
    example: str      # Beispielwert (Vorschau)
    prompt_hint: str  # Erklaerung fuer die KI


PLACEHOLDERS: list[Placeholder] = [
    Placeholder(
        "datum", "Datum des Dokuments (JJJJ-MM-TT)", "2024-03-12",
        "Datum des Dokuments im Format YYYY-MM-DD; steht keins im Dokument, das Scandatum",
    ),
    Placeholder(
        "datum_kompakt", "Datum als JJJJMMTT", "20240312",
        "Datum des Dokuments als JJJJMMTT ohne Trennzeichen; steht keins im Dokument, das Scandatum",
    ),
    Placeholder(
        "jahr", "Jahr des Dokuments", "2024",
        "vierstelliges Jahr des Dokuments (bzw. Steuerjahr)",
    ),
    Placeholder(
        "kategorie", "Dokumentart", "Behoerde",
        "Dokumentart in einem Wort: Rechnung, Vertrag, Bescheid, Versicherung, Bank, Arzt, Steuer ...",
    ),
    Placeholder(
        "kontakt", "Absender / andere Partei", "Agentur-fuer-Arbeit",
        "NAME der anderen Partei (Firma, Behoerde, Person) - nie der Dokumentbesitzer, "
        "nie eine E-Mail-Adresse, Telefonnummer oder Web-Adresse",
    ),
    Placeholder(
        "betreff", "Worum es geht (1-4 Wörter)", "Arbeitsuchendmeldung",
        "worum es geht, in 1-4 Woertern",
    ),
    Placeholder(
        "initialen", "Ihre Initialen", "JW",
        "Initialen des Dokumentbesitzers: 2-3 Grossbuchstaben, NIE ein ausgeschriebener Name",
    ),
    Placeholder(
        "projekt", "Projektname", "Umbau-Praxis",
        "Projektname oder -bezeichnung aus dem Dokument",
    ),
    Placeholder(
        "aktenzeichen", "Akten-/Kunden-/Rechnungsnummer", "AZ-4711",
        "Aktenzeichen, Kunden-, Vertrags- oder Rechnungsnummer aus dem Dokument",
    ),
    Placeholder(
        "betrag", "Rechnungsbetrag", "123-45-EUR",
        "Bruttobetrag mit Waehrung, Komma/Punkt durch - ersetzt (123-45-EUR)",
    ),
]

PLACEHOLDER_BY_KEY: dict[str, Placeholder] = {p.key: p for p in PLACEHOLDERS}
EXAMPLE_VALUES: dict[str, str] = {p.key: p.example for p in PLACEHOLDERS}

# Vorlagen fuer die Combo. Muster None = "Eigenes" (Feld frei editierbar).
PRESET_STANDARD = "Standard – KI entscheidet selbst"
PRESET_CUSTOM = "Eigenes Muster"
PRESETS: list[tuple[str, str | None]] = [
    (PRESET_STANDARD, ""),
    ("Rechnungen & Belege", "{datum}_{kategorie}_{kontakt}_{betreff}"),
    ("Akten & Projekte", "{initialen}_{aktenzeichen}_{datum}_{betreff}_{kontakt}"),
    ("Büro-Kürzel voran (JK 2024-03-12-Betreff)", "{initialen} {datum}-{betreff}"),
    (PRESET_CUSTOM, None),
]

_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")

# Alte Presets (bis 0.21) und Grosswort-Schreibweise -> neue Syntax
_LEGACY_PRESETS = {
    "YYYY-MM-DD_Rechnung_Kontakt_Betreff": "{datum}_{kategorie}_{kontakt}_{betreff}",
    "PROJEKTNUMMER_INITIALIEN/AKTENZEICHEN_YYYY-MM-DD_Betreff_Kontakt":
        "{initialen}_{aktenzeichen}_{datum}_{betreff}_{kontakt}",
}
_LEGACY_TOKENS: list[tuple[str, str]] = [
    (r"YYYY-MM-DD|JJJJ-MM-TT|DATUM", "datum"),
    (r"YYYY|JJJJ", "jahr"),
    (r"KONTAKT|ABSENDER|KORRESPONDENT|LIEFERANT|FIRMA", "kontakt"),
    (r"BETREFF|KURZBESCHREIBUNG|BESCHREIBUNG", "betreff"),
    (r"KATEGORIE|DOKUMENTTYP|DOKUMENTART", "kategorie"),
    (r"INITIALIEN|INITIALEN", "initialen"),
    (r"AKTENZEICHEN|AUFTRAGSNUMMER|RECHNUNGSNUMMER|KUNDENNUMMER", "aktenzeichen"),
    (r"PROJEKTNUMMER|PROJEKT", "projekt"),
    (r"BETRAG", "betrag"),
]


def find_placeholders(pattern: str) -> list[str]:
    """Alle ``{...}``-Schluessel im Muster, in Reihenfolge, ohne Duplikate."""
    seen: list[str] = []
    for key in _PLACEHOLDER_RE.findall(pattern or ""):
        key = key.strip().lower()
        if key and key not in seen:
            seen.append(key)
    return seen


def migrate_legacy_pattern(pattern: str) -> str:
    """Wandelt ein altes Muster (Grosswoerter, alte Presets) in ``{}``-Syntax um.

    Muster, die bereits ``{`` enthalten, bleiben unveraendert.
    """
    pattern = (pattern or "").strip()
    if not pattern or "{" in pattern:
        return pattern
    if pattern in _LEGACY_PRESETS:
        return _LEGACY_PRESETS[pattern]
    result = pattern
    for regex, key in _LEGACY_TOKENS:
        result = re.sub(
            rf"(?<![A-Za-z{{]){regex}(?![A-Za-z}}])",
            "{" + key + "}",
            result,
            flags=re.IGNORECASE,
        )
    # "INITIALIEN/AKTENZEICHEN" (oder) -> "/" ist im Dateinamen verboten
    result = result.replace("}/{", "}_{")
    return result


def render_example(pattern: str, values: dict[str, str] | None = None) -> str:
    """Rendert das Muster mit Beispiel- oder echten Werten zu einem Dateinamen.

    Unbekannte Platzhalter werden als Bezeichnung (``{lieferant}`` ->
    ``Lieferant``) eingesetzt. Mehrere Woerter innerhalb eines Werts werden
    mit "-" verbunden, damit "_" das Trennzeichen zwischen Platzhaltern bleibt.
    """
    from src.utils.filename_sanitizer import sanitize_filename

    merged = dict(EXAMPLE_VALUES)
    if values:
        merged.update({k: v for k, v in values.items() if v})
        # Abgeleitete Datumsformen, wenn nur {datum} (ISO) geliefert wurde
        iso = str(values.get("datum") or "")
        if iso:
            if not values.get("datum_kompakt"):
                merged["datum_kompakt"] = iso.replace("-", "")
            if not values.get("jahr"):
                merged["jahr"] = iso[:4]

    def _sub(m: re.Match) -> str:
        key = m.group(1).strip().lower()
        if key in merged:
            return "-".join(str(merged[key]).split())
        return key.capitalize()

    name = _PLACEHOLDER_RE.sub(_sub, pattern or "")
    return sanitize_filename(name)


def describe_for_prompt(pattern: str, initials: str = "") -> str:
    """Erklaert das Muster fuer den KI-Prompt (Platzhalterliste + Beispiel)."""
    pattern = (pattern or "").strip()
    if not pattern:
        return ""
    keys = find_placeholders(pattern)
    lines = [
        "\nBENUTZERDEFINIERTES DATEINAMEN-MUSTER:",
        f"    {pattern}",
    ]
    if not keys:
        # Freitext ohne Platzhalter: wie bisher als Strukturvorlage
        lines.append("Nutze dieses Muster als Strukturvorlage für den Dateinamen.")
        return "\n".join(lines) + "\n"

    lines.append(
        "Ersetze jeden Platzhalter durch den Wert aus dem Dokument und behalte die "
        "Trennzeichen des Musters bei. Mehrere Wörter innerhalb eines Platzhalters "
        'mit "-" verbinden. Fehlt ein Wert, den Platzhalter samt Trennzeichen weglassen.'
    )
    lines.append("Platzhalter:")
    for key in keys:
        ph = PLACEHOLDER_BY_KEY.get(key)
        if ph is None:
            lines.append(f'- {{{key}}}: frei nach der Bezeichnung "{key}" aus dem Dokument füllen')
            continue
        hint = ph.prompt_hint
        if key == "initialen" and initials:
            hint += f". Verwende genau: {initials}"
        lines.append(f"- {{{key}}}: {hint}")
    example_values = {"initialen": initials} if initials else None
    lines.append(f"Beispiel-Ergebnis: {render_example(pattern, example_values)}")
    return "\n".join(lines) + "\n"


def legend_html() -> str:
    """Kleine Tabelle aller Platzhalter fuer die Einstellungen."""
    rows = "".join(
        f"<tr><td><code>{{{p.key}}}</code></td><td>{p.label}</td>"
        f"<td style='color:#666'>{p.example}</td></tr>"
        for p in PLACEHOLDERS
    )
    return (
        "<table cellspacing='0' cellpadding='3'>"
        "<tr><th align='left'>Platzhalter</th><th align='left'>Bedeutung</th>"
        "<th align='left'>Beispiel</th></tr>"
        f"{rows}</table>"
        "<p style='color:#666'>Eigene Platzhalter wie <code>{lieferant}</code> sind erlaubt – "
        "die KI füllt sie nach der Bezeichnung.</p>"
    )
