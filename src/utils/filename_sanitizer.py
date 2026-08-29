"""Zentrale Bereinigung von Dateinamen (KI-Vorschlaege und Nutzereingaben).

Ziel: Ein Dateiname enthaelt ausser der Endung ``.pdf`` keine Zeichen, die
auf Windows/macOS/Linux verboten sind oder in der Praxis Aerger machen
(Punkt, Klammeraffe, Umlaute). Leerzeichen sind erlaubt - Anwender mit
Bestandssystemen ("JK 069-01-01-20260512-Rechnung") brauchen sie; nur
Mehrfach-Leerzeichen und Leerzeichen neben ``_``/``-`` werden entfernt.

Die Funktion ist idempotent: ``sanitize_filename(sanitize_filename(x)) ==
sanitize_filename(x)``.
"""
from __future__ import annotations

import re
import unicodedata

# Auf Windows verbotene Zeichen (Linux/macOS: nur "/" bzw. ":")
INVALID_FILENAME_CHARS = '<>:"/\\|?*'

# Erlaubt, aber ungluecklich: Punkt (Doppel-Endungen, "versteckte" Dateien,
# Verwechslung mit Endung), Klammeraffe (E-Mail-Adressen, Shell/URL-Probleme).
DISCOURAGED_FILENAME_CHARS = ".@"

_UMLAUT_MAP = {
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "ß": "ss",
}

# Reservierte Geraetenamen unter Windows (case-insensitive, auch mit Endung)
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}

_PDF_SUFFIX_RE = re.compile(r"\.pdf$", re.IGNORECASE)
# Kein "_" im Lokalteil: im Dateinamen ist "_" das Trennzeichen, sonst wuerde
# "Meldung_kathrin.haerle@web.de" als eine einzige Adresse gelesen.
_EMAIL_RE = re.compile(r"[A-Za-z0-9.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Lokalteile, die keinen Personennamen tragen (info@, kontakt@ ...)
_GENERIC_EMAIL_LOCALS = {
    "info", "kontakt", "contact", "mail", "email", "office", "post",
    "service", "support", "noreply", "no-reply", "nicht-antworten",
    "team", "hallo", "hello", "hi", "admin", "webmaster", "news",
    "newsletter", "kundenservice", "kundendienst", "buchhaltung",
    "rechnung", "rechnungen", "invoice", "billing", "verwaltung",
    "sekretariat", "praxis", "kanzlei", "zentrale", "anfrage", "bewerbung",
}

# Freemailer: der Domainteil sagt nichts ueber den Absender aus
_FREEMAIL_DOMAINS = {
    "web", "gmx", "gmail", "googlemail", "t-online", "outlook", "hotmail",
    "live", "yahoo", "icloud", "me", "posteo", "freenet", "aol", "mail",
    "protonmail", "proton", "arcor", "online", "email", "ymail", "msn",
}
_MULTI_UNDERSCORE_RE = re.compile(r"_{2,}")
_MULTI_SPACE_RE = re.compile(r" {2,}")
_SPACE_AROUND_SEP_RE = re.compile(r" *([_-]) *")
_UNDERSCORE_AROUND_DASH_RE = re.compile(r"_?-_?")


def _email_to_name(local: str, domain: str) -> str:
    """Macht aus einer E-Mail-Adresse einen Namensbestandteil.

    ``kathrin.haerle@web.de`` -> ``Kathrin_Haerle``;
    ``info@huk-coburg.de`` -> ``Huk-Coburg``;
    ``info@web.de`` -> ``""`` (nichts Brauchbares).
    """
    local_l = local.lower()
    # Plus-Adressierung und Ziffern-Anhaengsel abschneiden
    local_l = local_l.split("+", 1)[0]
    if local_l not in _GENERIC_EMAIL_LOCALS:
        # Ziffern-Anhaengsel (mueller2024) sind kein Namensbestandteil
        parts = [re.sub(r"[0-9]+", "", p) for p in re.split(r"[._-]+", local_l)]
        parts = [p for p in parts if p]
        if parts:
            return "_".join(p.capitalize() for p in parts)
    labels = [l for l in domain.lower().split(".") if l]
    # TLD und generische Sub-Labels (www, mail) abstreifen
    labels = labels[:-1] if len(labels) > 1 else labels
    labels = [l for l in labels if l not in {"www", "mail", "email", "smtp"}]
    if not labels or labels[-1] in _FREEMAIL_DOMAINS:
        return ""
    return "-".join(p.capitalize() for p in labels[-1].split("-"))


def contains_email(name: str) -> bool:
    """True, wenn im Namen eine E-Mail-Adresse steckt."""
    return _EMAIL_RE.search(name or "") is not None


def replace_email_addresses(name: str) -> str:
    """Ersetzt E-Mail-Adressen im Namen durch den daraus ableitbaren Namen.

    Eine E-Mail-Adresse ist kein Name; im Dateinamen wollen wir die Person
    bzw. die Organisation. Nicht ableitbare Adressen (``info@web.de``)
    werden entfernt.
    """
    def _sub(m: re.Match) -> str:
        local, _, domain = m.group(0).rpartition("@")
        return _email_to_name(local, domain)

    return _EMAIL_RE.sub(_sub, name)


def strip_pdf_extension(name: str) -> str:
    """Entfernt eine abschliessende ``.pdf``-Endung (case-insensitive)."""
    return _PDF_SUFFIX_RE.sub("", name.strip())


def find_problem_chars(name: str) -> list[str]:
    """Liefert die Zeichen (ohne Duplikate, in Reihenfolge), die
    :func:`sanitize_filename` im Namensteil ersetzen wuerde.

    Die ``.pdf``-Endung wird vorher abgetrennt, damit der Punkt der Endung
    nicht als Problem gemeldet wird.
    """
    stem = replace_email_addresses(strip_pdf_extension(name))
    found: list[str] = []
    for ch in stem:
        if ch in found:
            continue
        if ch in INVALID_FILENAME_CHARS or ch in DISCOURAGED_FILENAME_CHARS:
            found.append(ch)
        elif (ch.isspace() and ch != " ") or ord(ch) < 32 or ch == "\x7f":
            found.append(ch)
    return found


def sanitize_filename(name: str, ensure_pdf: bool = True) -> str:
    """Bereinigt einen Dateinamen fuer alle Plattformen.

    Schritte:
    1. ``.pdf``-Endung abtrennen (wird am Ende wieder angehaengt);
       E-Mail-Adressen durch den ableitbaren Namen ersetzen
       (``kathrin.haerle@web.de`` -> ``Kathrin_Haerle``).
    2. Umlaute/ß nach ae/oe/ue/ss; sonstige Akzente entfernen (é -> e).
    3. Verbotene Zeichen (``<>:"/\\|?*``), Steuerzeichen, Tabs/Umbrueche
       sowie ``.`` und ``@`` durch ``_`` ersetzen. Leerzeichen bleiben.
    4. Mehrfache Unterstriche/Leerzeichen zusammenfassen, Leerzeichen und
       Unterstriche um ``-`` entfernen, fuehrende/abschliessende ``_``/``-``
       abschneiden.
    5. Reservierte Windows-Namen (CON, NUL, ...) mit ``_`` entschaerfen.

    Args:
        name: Roher Dateiname (mit oder ohne ``.pdf``)
        ensure_pdf: ``.pdf`` anhaengen (Default). ``False`` liefert nur den
            bereinigten Namensteil.

    Returns:
        Bereinigter Dateiname. Leere Eingabe ergibt ``""`` bzw. ``".pdf"``
        wird NICHT erzeugt - bei leerem Namensteil kommt ``""`` zurueck.
    """
    stem = strip_pdf_extension(name or "")
    stem = replace_email_addresses(stem)

    for old, new in _UMLAUT_MAP.items():
        stem = stem.replace(old, new)
    # Sonstige Akzente abstreifen (NFKD zerlegt z.B. "é" in "e" + Akzent)
    stem = "".join(
        ch for ch in unicodedata.normalize("NFKD", stem)
        if not unicodedata.combining(ch)
    )

    cleaned = []
    for ch in stem:
        if (
            ch in INVALID_FILENAME_CHARS
            or ch in DISCOURAGED_FILENAME_CHARS
            or (ch.isspace() and ch != " ")
            or ord(ch) < 32
            or ch == "\x7f"
        ):
            cleaned.append("_")
        else:
            cleaned.append(ch)
    stem = "".join(cleaned)

    stem = _MULTI_SPACE_RE.sub(" ", stem)
    stem = _SPACE_AROUND_SEP_RE.sub(r"\1", stem)
    stem = _MULTI_UNDERSCORE_RE.sub("_", stem)
    stem = _UNDERSCORE_AROUND_DASH_RE.sub("-", stem)
    stem = stem.strip("_- ")

    if stem.upper() in _RESERVED_NAMES:
        stem = f"{stem}_"

    if not stem:
        return ""
    return f"{stem}.pdf" if ensure_pdf else stem
