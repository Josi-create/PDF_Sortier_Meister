"""Textausgabe von Suchergebnissen (fuer Kommandozeile und MCP).

Uebernommen aus PDFsuche (``ausgabe.py``).
"""

from __future__ import annotations

from datetime import datetime


def datum(ts) -> str:
    if not ts:
        return "?"
    try:
        return datetime.fromtimestamp(ts).strftime("%d.%m.%Y")
    except (OSError, ValueError, OverflowError):
        return "?"


def ausschnitt(text: str) -> str:
    """Fundstellen-Marker (\\x02/\\x03) in Anfuehrungszeichen umwandeln, Leerraum glaetten."""
    return " ".join((text or "").replace("\x02", "«").replace("\x03", "»").split())


def dokument_text(idx, dok_id: int, seiten: str | None = None, max_zeichen: int = 0) -> str:
    """Kopfzeilen und Text eines Dokuments (``seiten``: '3' oder '2-5'), optional gekuerzt."""
    d = idx.dokument(dok_id)
    if not d:
        return f"Dokument {dok_id} nicht gefunden."
    von = bis = None
    if seiten:
        teile = str(seiten).split("-")
        von = int(teile[0])
        bis = int(teile[-1])
    kopf = [f"# {d['name']}", f"Pfad: {d['pfad']}",
            f"Typ: {d['typ']}  Status: {d['textstatus']}  Datum: {datum(d['datum'])}"]
    if d["typ"] == "mail":
        kopf.append(f"Von: {d['mail_von']}\nAn: {d['mail_an']}\nAnhänge: {d['mail_anhaenge'] or '-'}")
    elif d.get("seiten"):
        kopf.append(f"Seiten: {d['seiten']}  (davon OCR: {d['ocr_seiten']})")
    text = []
    for s in idx.seiten_text(dok_id, von, bis):
        if d["typ"] == "pdf":
            text.append(f"\n--- Seite {s['seite']}{' (OCR)' if s['quelle'] == 'ocr' else ''} ---")
        elif d["format"] in ("xlsx", "xlsm", "xls"):
            text.append(f"\n--- Blatt {s['seite']} ---")
        text.append(s["text"])
    erg = "\n".join(kopf) + "\n" + "\n".join(text)
    if max_zeichen and len(erg) > max_zeichen:
        erg = erg[:max_zeichen] + f"\n\n[… gekürzt, insgesamt {len(erg)} Zeichen – mit Seitenangabe weiterlesen]"
    return erg


def status_text(idx) -> str:
    """Indexstand als Text (Kommandozeile und MCP)."""
    st = idx.status()
    if not st.get("vorhanden", True):
        return (f"Datenbank: {idx.db_datei} (noch nicht vorhanden – erster Lauf steht aus)\n"
                f"Indexierung läuft gerade: {'ja' if st.get('laeuft') else 'nein'}")
    z = [f"Datenbank: {idx.db_datei}",
         f"Dokumente: {st['dokumente']}  ({', '.join(f'{k}: {v}' for k, v in st['pro_typ'].items())})",
         f"Seiten: {st['seiten']}, davon per OCR erkannt: {st['ocr_seiten']}, OCR ausstehend: {st['ocr_ausstehend_seiten']}",
         "Status: " + ", ".join(f"{k}: {v}" for k, v in sorted(st["pro_status"].items())),
         f"Indexierung läuft gerade: {'ja' if st.get('laeuft') else 'nein'}",
         f"Fortschritt: {st['fortschritt']}"]
    if st.get("ocr_grund"):
        z.insert(3, f"Texterkennung (OCR): aus – {st['ocr_grund']}")
    te = st.get("textebene") or {}
    stufe = getattr(getattr(idx, "konfig", None), "textebene", "aus")
    if stufe != "aus" or te.get("geschrieben"):
        zeile = f"Textebene in PDFs ({stufe}): {te.get('geschrieben', 0)} geschrieben"
        if te.get("gruende"):
            from src.search.textebene import GRUENDE
            zeile += " – nicht geschrieben: " + ", ".join(
                f"{GRUENDE.get(k, k)}: {v}" for k, v in sorted(te["gruende"].items()))
        z.append(zeile)
    if st["laeufe"]:
        lauf = st["laeufe"][0]
        z.append(f"Letzter Lauf: {lauf['beginn']} bis {lauf['ende'] or '…'} – {lauf['status']} ({lauf['phase']})")
    return "\n".join(z)


def ergebnisse(erg: dict, abfrage: str) -> str:
    t = erg["treffer"]
    if not t:
        return f"Keine Treffer für: {abfrage}  (FTS-Abfrage: {erg['abfrage']})"
    kopf = f"{erg['gesamt']}{'+' if erg['mehr'] else ''} Dokumente für „{abfrage}“ – {len(t)} angezeigt ({erg['dauer_ms']} ms)"
    zeilen = [kopf, ""]
    for d in t:
        status = "" if d["textstatus"] in ("text", "ocr") else f" [{d['textstatus']}]"
        if d["typ"] == "mail":
            zeilen.append(f"[{d['id']}] MAIL {datum(d['datum'])}  {d['name']}{status}")
            zeilen.append(f"      Von: {d['mail_von']}  |  {d['ordner']}")
        else:
            seiten = f", {d['seiten']} S." if d.get("seiten") else ""
            ocr = ", OCR" if d.get("ocr_seiten") else ""
            zeilen.append(f"[{d['id']}] {d['typ'].upper()} {datum(d['datum'])}{seiten}{ocr}{status}  {d['pfad']}")
        if d.get("im_namen") and not d["stellen"]:
            zeilen.append("      (Treffer im Datei-/Ordnernamen)")
        for s in d["stellen"]:
            seite = (f"S.{s['seite']}: " if d["typ"] == "pdf"
                     else f"Blatt {s['seite']}: " if d.get("format") in ("xlsx", "xlsm", "xls") else "")
            zeilen.append(f"      {seite}{ausschnitt(s['text'])}")
        if d["treffer_seiten"] > len(d["stellen"]):
            zeilen.append(f"      … insgesamt {d['treffer_seiten']} Seiten mit Treffern")
        zeilen.append("")
    return "\n".join(zeilen)
