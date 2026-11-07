"""
Prompts und Text-Builder fuer das RAG-Chat-Feature (Phase 19 / M1).

Stellt den System-Prompt (``docs/ARCHITECTURE.md`` Section 4) sowie zwei
Builder-Funktionen bereit:

* :func:`build_context_block` erzeugt den ``=== DOKUMENTE ===``-Block.
* :func:`build_user_prompt` baut die User-Message inkl. History.

Issue #166/#167 (Phase 2): :data:`SYSTEM_PROMPT_WERKZEUGE` bzw.
:func:`build_system_prompt_werkzeuge` fuer den Chat mit Werkzeugen
(Suche, Lesen, Ordnervorschlag, Korrespondent, optional SQL).

GPL-3.0-or-later - Copyright (c) 2026
"""

# System-Prompt - gleicher Wortlaut wie docs/ARCHITECTURE.md Section 4.
# Issue #166/#167: Schlussfolgerungen ueber gemeinsame Kennungen sind
# ausdruecklich erlaubt; der Nutzer wird nicht mehr zum Selbst-Suchen
# aufgefordert (die Suche macht das Programm).
SYSTEM_PROMPT = """\
Du bist ein Assistent für die private PDF-Sammlung des Nutzers.

REGELN:
1. Antworte NUR basierend auf den unten bereitgestellten Dokumentauszügen.
2. Schlussfolgerungen über mehrere Dokumente hinweg sind erwünscht, wenn eine
   gemeinsame Kennung (Vertragsnummer, Zählernummer, Kundennummer,
   Rechnungsnummer, IBAN, Adresse) die Verbindung belegt. Auch Dateiname und
   Ablageort eines Dokuments sind Belege. Nenne dann die Kette, z.B.
   "[1] nennt die Vertragsnummer X; [2] ordnet X der Abnahmestelle Y zu".
   Dokumente mit "gemeinsame Kennungen mit dem Bezugsdokument" gehören sicher
   zum Bezugsdokument; andere Suchtreffer können bloße Wortübereinstimmungen
   sein (z.B. "Objekt" in einer fremden Mail) und belegen nur, was sie selbst
   betrifft.
3. Wenn die Auszüge die Frage NICHT beantworten, sage wörtlich:
   "Ich finde dazu keine passenden Dokumente in deiner Sammlung."
   und nenne, was in den Auszügen am ehesten dazu passt. Fordere den Nutzer
   nicht auf, selbst zu suchen.
4. Erfinde KEINE Quellen, Zahlen, Daten oder Fakten, die nicht in den Auszügen stehen.
5. Zitiere jede konkrete Aussage mit [1], [2], ... (Index auf die bereitgestellten Dokumente).
6. Am Ende der Antwort: "Quellen:" gefolgt von der nummerierten Liste.
7. Antworte in der Sprache der Frage."""


# Issue #166/#167, Phase 2: System-Prompt fuer die Werkzeug-Schleife. Die
# Regeln von SYSTEM_PROMPT bleiben; dazu kommt, wann das Modell welches
# Werkzeug nimmt und dass die Zitatnummern die D-Nummern aus Kontext und
# Werkzeugausgaben sind. ``{max_schritte}`` setzt
# :func:`build_system_prompt_werkzeuge` ein.
SYSTEM_PROMPT_WERKZEUGE = """\
Du bist ein Assistent für die private PDF-Sammlung des Nutzers. Du hast Werkzeuge,
mit denen du die Sammlung selbst durchsuchst und Dokumente liest.

VORGEHEN:
1. Die Dokumente unten (=== DOKUMENTE ===) sind nur der Startpunkt - sie können
   unvollständig sein oder fehlen. Bevor du sagst, dass es keine passenden Dokumente
   gibt, suche selbst mit dem Werkzeug suche: mehrere Suchen mit verschiedenen
   Begriffen (Kennungen wie Vertrags-, Zähler-, Kunden- oder Rechnungsnummer,
   Adresse, Name, Betrag; Wortanfang mit *; Begriffe mit ODER), bei Bedarf mit
   Filtern (Dateityp, z.B. typ=office für Excel-Tabellen; Ordner; Zeitraum).
   Fragen nach Beträgen, Summen oder einem Zeitraum beantwortest du nie aus dem
   Startkontext allein: suche (z.B. Vertragsnummer zusammen mit "Abschlag",
   "Lastschrift" oder dem Jahr) oder nutze sql_abfrage, bevor du sagst, es gebe
   nichts.
2. Reichen die Fundstellen nicht, lies das Dokument mit dokument_lesen - lange
   Dokumente seitenweise (seiten), bei Tabellen das passende Blatt.
3. Fragen nach Ordner oder Ablageort eines Dokuments: ordner_vorschlag. Schreibweise
   oder Hintergrund eines Absenders: korrespondent_info. Summen, Zählungen und
   Listen über viele Dokumente: sql_abfrage, falls vorhanden.
4. Du hast höchstens {max_schritte} Schritte (Modellaufrufe mit Werkzeugen). Danach
   antworte mit dem, was du hast. Rufe nicht zweimal dasselbe Werkzeug mit denselben
   Argumenten auf.

REGELN FÜR DIE ANTWORT:
1. Antworte NUR basierend auf den Dokumentauszügen unten und den Ergebnissen deiner
   Werkzeuge.
2. Schlussfolgerungen über mehrere Dokumente hinweg sind erwünscht, wenn eine
   gemeinsame Kennung (Vertragsnummer, Zählernummer, Kundennummer,
   Rechnungsnummer, IBAN, Adresse) die Verbindung belegt. Auch Dateiname und
   Ablageort eines Dokuments sind Belege. Nenne dann die Kette, z.B.
   "[1] nennt die Vertragsnummer X; [2] ordnet X der Abnahmestelle Y zu".
   Dokumente mit "gemeinsame Kennungen mit dem Bezugsdokument" gehören sicher
   zum Bezugsdokument; andere Suchtreffer können bloße Wortübereinstimmungen
   sein (z.B. "Objekt" in einer fremden Mail) und belegen nur, was sie selbst
   betrifft. Für Fragen zum Bezugsdokument werte zuerst D1 und die Dokumente
   mit gemeinsamen Kennungen aus.
3. Wenn auch deine Werkzeuge nichts Passendes liefern, sage wörtlich:
   "Ich finde dazu keine passenden Dokumente in deiner Sammlung."
   und nenne, was am ehesten dazu passt. Fordere den Nutzer nicht auf, selbst zu
   suchen - das Suchen ist deine Aufgabe.
4. Erfinde KEINE Quellen, Zahlen, Daten oder Fakten, die nicht in den Auszügen oder
   Werkzeugausgaben stehen. Beschreibe den Inhalt eines Dokuments nur, wenn du ihn
   gelesen hast (Fundstellen oder dokument_lesen) - aus einem Dateinamen allein
   darfst du keinen Inhalt ableiten.
5. Zitiere jede konkrete Aussage mit [1], [2], ... Die Nummer ist die Dokumentnummer
   aus dem Kontext ([D3]) oder aus den Werkzeugausgaben ([D7]), also [3] bzw. [7].
   Index-Ids, Seitenzahlen und Beträge sind keine Zitatnummern.
6. Am Ende der Antwort: "Quellen:" gefolgt von der Liste der zitierten Dokumente
   mit denselben Nummern wie im Text, z.B. "[7] Zählerstände Dez 2012.xlsx" -
   nicht neu durchnummerieren.
7. Antworte in der Sprache der Frage."""


def build_system_prompt_werkzeuge(max_schritte: int) -> str:
    """System-Prompt der Werkzeug-Schleife mit der Hoechstzahl der Schritte (Issue #166/#167)."""
    try:
        n = max(1, int(max_schritte))
    except (TypeError, ValueError):
        n = 1
    return SYSTEM_PROMPT_WERKZEUGE.replace("{max_schritte}", str(n))


# Issue #148: Kopfzeilen fuer das Bezugsdokument und die weiteren Suchtreffer
BEZUG_UEBERSCHRIFT = (
    "BEZUGSDOKUMENT (die Frage bezieht sich auf dieses Dokument, "
    "z.B. \"dieses Dokument\" oder \"dieses PDF\"):"
)
WEITERE_UEBERSCHRIFT = "WEITERE DOKUMENTE AUS DER SAMMLUNG (Suchtreffer):"
SORTIERLOGIK_PRAEFIX = "VORSCHLAG DER SORTIERLOGIK:"
# Issue #166/#167: Kennungen und Scan-Eingang
KENNUNGEN_PRAEFIX = "kennungen in diesem Dokument:"
GEMEINSAME_KENNUNGEN_PRAEFIX = "gemeinsame Kennungen mit dem Bezugsdokument:"
SCAN_EINGANG_HINWEIS = "LIEGT NOCH UNSORTIERT IM SCAN-EINGANG (noch kein Ablageort)."


def _format_doc(doc: dict) -> str:
    """Formatiert ein einzelnes Doc-Dict als ``[Dn]``-Block.

    Erwartet die in ARCHITECTURE.md Section 4 spezifizierten Felder
    (index, filename, kategorie, steuerjahr, betrag, korrespondent,
    text_snippet). Fehlende Felder werden leer gelassen.

    Optional (Issue #148, Chat mit Bezugsdokument):

    * ``bezug`` (bool): Kopfzeile ``BEZUGSDOKUMENT`` vor dem Block.
    * ``ordner`` (str): Ablageort, eigene Zeile ``ordner=...``.
    * ``hinweise`` (list[str]): Zeilen vor dem Text, z.B.
      ``VORSCHLAG DER SORTIERLOGIK: ...``.

    Optional (Issue #166/#167, Kennungen):

    * ``kennungen`` (list[str]): Kennungen des Bezugsdokuments.
    * ``gemeinsame_kennungen`` (list[str]): Kennungen, die ein Suchtreffer
      mit dem Bezugsdokument teilt.
    """
    if not isinstance(doc, dict):
        return ""

    idx = doc.get("index", 0)
    filename = doc.get("filename", "") or ""
    kategorie = doc.get("kategorie", "") or ""
    steuerjahr = doc.get("steuerjahr", "") or ""
    betrag = doc.get("betrag", "") or ""
    korrespondent = doc.get("korrespondent", "") or ""
    text = doc.get("text_snippet", "") or ""

    parts: list[str] = []
    if doc.get("bezug"):
        parts.append(BEZUG_UEBERSCHRIFT)
    parts.append(f"[D{idx}] dateiname={filename}")
    # Metadaten-Zeile: nur Felder mit Wert
    meta_bits: list[str] = []
    if kategorie:
        meta_bits.append(f"kategorie={kategorie}")
    if steuerjahr:
        meta_bits.append(f"steuerjahr={steuerjahr}")
    if betrag:
        meta_bits.append(f"betrag={betrag}")
    if meta_bits or korrespondent:
        line = "     " + " | ".join(meta_bits)
        if korrespondent:
            line += f"\n     korrespondent={korrespondent}"
        parts.append(line)
    ordner = doc.get("ordner", "") or ""
    if ordner:
        parts.append(f"     ordner={ordner}")
    kennungen = [str(k) for k in (doc.get("kennungen") or ()) if k]
    if kennungen:
        parts.append(f"     {KENNUNGEN_PRAEFIX} {', '.join(kennungen)}")
    gemeinsame = [str(k) for k in (doc.get("gemeinsame_kennungen") or ()) if k]
    if gemeinsame:
        parts.append(f"     {GEMEINSAME_KENNUNGEN_PRAEFIX} {', '.join(gemeinsame)}")
    for hinweis in doc.get("hinweise") or ():
        if hinweis:
            parts.append(str(hinweis))
    parts.append("--- text ---")
    parts.append(text)
    return "\n".join(parts)


def build_context_block(docs: list[dict]) -> str:
    """Baut den ``=== DOKUMENTE ===``-Block aus den uebergebenen Docs.

    Args:
        docs: Liste von Doc-Dicts (siehe :func:`_format_doc`).

    Returns:
        Mehrzeiliger String mit Kopf/Fuss und einem Block pro Doc.
        Bei leerer Liste wird der Block dennoch mit Start/Ende-Markern
        erzeugt, damit das LLM die Struktur erkennt.
    """
    if not docs:
        return (
            "=== DOKUMENTE ===\n\n"
            "(Keine Dokumente verfuegbar.)\n\n"
            "=== ENDE DOKUMENTE ==="
        )

    bloecke = [_format_doc(d) for d in docs]
    # Nach dem Bezugsdokument (Issue #148) die Suchtreffer abgrenzen
    if len(docs) > 1 and isinstance(docs[0], dict) and docs[0].get("bezug"):
        bloecke.insert(1, WEITERE_UEBERSCHRIFT)
    body = "\n\n".join(bloecke)
    return f"=== DOKUMENTE ===\n\n{body}\n\n=== ENDE DOKUMENTE ==="


def build_user_prompt(
    question: str,
    history: list = None,
    context_block: str = "",
) -> str:
    """Baut die User-Message.

    Aufbau (falls context_block uebergeben):

        <context_block>

        FRAGE: <question>

        BISHERIGER GESPRAECHSVERLAUF:
        <history>

    Args:
        question: Aktuelle Nutzerfrage.
        history: Optionale Liste von ChatTurn-Objekten oder
            Dicts mit ``role``/``content``-Schluesseln.
        context_block: Optional der bereits formatierte
            ``=== DOKUMENTE ===``-Block. Wird er nicht uebergeben,
            wird in der User-Message nur die Frage gestellt.
    """
    parts: list[str] = []

    if context_block:
        parts.append(context_block)
        parts.append("")

    parts.append(f"FRAGE: {question.strip() if question else ''}")

    if history:
        # History kompakt formatieren; cap auf max 4 Turns (Architektur-Vorgabe).
        turns = history[-4:] if len(history) > 4 else history
        if turns:
            parts.append("")
            parts.append("BISHERIGER GESPRAECHSVERLAUF:")
            for turn in turns:
                if hasattr(turn, "role") and hasattr(turn, "content"):
                    role = turn.role
                    content = turn.content
                elif isinstance(turn, dict):
                    role = turn.get("role", "user")
                    content = turn.get("content", "")
                else:
                    continue
                # Rollen-Header in GROSSBUCHSTABEN.
                header = "NUTZER:" if str(role).lower() == "user" else "ASSISTENT:"
                parts.append(f"{header} {content}")

    return "\n".join(parts)
