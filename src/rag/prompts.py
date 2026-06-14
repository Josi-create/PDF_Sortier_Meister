"""
Prompts und Text-Builder fuer das RAG-Chat-Feature (Phase 19 / M1).

Stellt den exakten System-Prompt aus der Architektur-Spezifikation
(``docs/ARCHITECTURE.md`` Section 4) sowie zwei Builder-Funktionen
bereit:

* :func:`build_context_block` erzeugt den ``=== DOKUMENTE ===``-Block.
* :func:`build_user_prompt` baut die User-Message inkl. History.

MIT License - Copyright (c) 2026
"""

# System-Prompt - VERBATIM aus docs/ARCHITECTURE.md Section 4.
# Nicht modifizieren: Wird vom M1-Testsuitet als Referenztext erwartet.
SYSTEM_PROMPT = """\
Du bist ein Assistent für die private PDF-Sammlung des Nutzers.

REGELN:
1. Antworte NUR basierend auf den unten bereitgestellten Dokumentauszügen.
2. Wenn die Auszüge die Frage NICHT beantworten, sage wörtlich:
   "Ich finde dazu keine passenden Dokumente in deiner Sammlung."
   und schlage vor, wonach der Nutzer stattdessen suchen könnte.
3. Erfinde KEINE Quellen, Zahlen, Daten oder Fakten, die nicht in den Auszügen stehen.
4. Zitiere jede konkrete Aussage mit [1], [2], ... (Index auf die bereitgestellten Dokumente).
5. Am Ende der Antwort: "Quellen:" gefolgt von der nummerierten Liste.
6. Antworte in der Sprache der Frage."""


def _format_doc(doc: dict) -> str:
    """Formatiert ein einzelnes Doc-Dict als ``[Dn]``-Block.

    Erwartet die in ARCHITECTURE.md Section 4 spezifizierten Felder
    (index, filename, kategorie, steuerjahr, betrag, korrespondent,
    text_snippet). Fehlende Felder werden leer gelassen.
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

    body = "\n\n".join(_format_doc(d) for d in docs)
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
