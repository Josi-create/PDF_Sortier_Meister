"""Textausgabe von Suchergebnissen (fuer Kommandozeile und MCP).

Uebernommen aus PDFsuche (``ausgabe.py``).
"""

from __future__ import annotations

from datetime import datetime
from src.i18n import tr


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
        return tr("Dokument {dok_id} nicht gefunden.").format(dok_id=dok_id)
    von = bis = None
    if seiten:
        teile = str(seiten).split("-")
        von = int(teile[0])
        bis = int(teile[-1])
    kopf = [f"# {d['name']}", tr("Pfad: {pfad}").format(pfad=d['pfad']),
            tr("Typ: {typ}  Status: {textstatus}  Datum: {0}").format(datum(d['datum']), typ=d['typ'], textstatus=d['textstatus'])]
    if d["typ"] == "mail":
        kopf.append(tr("Von: {mail_von}\nAn: {mail_an}\nAnhänge: {0}").format(d['mail_anhaenge'] or '-', mail_von=d['mail_von'], mail_an=d['mail_an']))
    elif d.get("seiten"):
        kopf.append(tr("Seiten: {seiten}  (davon OCR: {ocr_seiten})").format(seiten=d['seiten'], ocr_seiten=d['ocr_seiten']))
    text = []
    for s in idx.seiten_text(dok_id, von, bis):
        if d["typ"] == "pdf":
            text.append(tr("\n--- Seite {seite}{0} ---").format(tr(" (OCR)") if s['quelle'] == 'ocr' else '', seite=s['seite']))
        elif d["format"] in ("xlsx", "xlsm", "xls"):
            text.append(tr("\n--- Blatt {seite} ---").format(seite=s['seite']))
        text.append(s["text"])
    erg = "\n".join(kopf) + "\n" + "\n".join(text)
    if max_zeichen and len(erg) > max_zeichen:
        erg = tr("{0}\n\n[… gekürzt, insgesamt {anzahl} Zeichen – mit Seitenangabe weiterlesen]").format(erg[:max_zeichen], anzahl=len(erg))
    return erg


def status_text(idx) -> str:
    """Indexstand als Text (Kommandozeile und MCP)."""
    st = idx.status()
    if not st.get("vorhanden", True):
        return (tr(
            "Datenbank: {db_datei} (noch nicht vorhanden – erster Lauf steht aus)\n"
            "Indexierung läuft gerade: {0}"
        ).format(tr("ja") if st.get('laeuft') else tr("nein"), db_datei=idx.db_datei))
    z = [tr("Datenbank: {db_datei}").format(db_datei=idx.db_datei),
         tr("Dokumente: {dokumente}  ({0})").format(', '.join((f'{k}: {v}' for k, v in st['pro_typ'].items())), dokumente=st['dokumente']),
         tr(
             "Seiten: {seiten}, davon per OCR erkannt: {ocr_seiten}, OCR ausstehend: "
             "{ocr_ausstehend_seiten}"
         ).format(seiten=st['seiten'], ocr_seiten=st['ocr_seiten'], ocr_ausstehend_seiten=st['ocr_ausstehend_seiten']),
         tr("Status: {0}").format(', '.join((f'{k}: {v}' for k, v in sorted(st['pro_status'].items())))),
         tr("Indexierung läuft gerade: {0}").format(tr("ja") if st.get('laeuft') else tr("nein")),
         tr("Fortschritt: {fortschritt}").format(fortschritt=st['fortschritt'])]
    if st.get("ocr_grund"):
        z.insert(3, tr("Texterkennung (OCR): aus – {ocr_grund}").format(ocr_grund=st['ocr_grund']))
    te = st.get("textebene") or {}
    stufe = getattr(getattr(idx, "konfig", None), "textebene", "aus")
    if stufe != "aus" or te.get("geschrieben"):
        zeile = tr("Textebene in PDFs ({stufe}): {0} geschrieben").format(te.get('geschrieben', 0), stufe=stufe)
        if te.get("gruende"):
            from src.search.textebene import GRUENDE
            zeile += tr(" – nicht geschrieben: {0}").format(', '.join((f'{GRUENDE.get(k, k)}: {v}' for k, v in sorted(te['gruende'].items()))))
        z.append(zeile)
    drehen = getattr(getattr(idx, "konfig", None), "auto_drehen", "aus")
    if drehen != "aus" or te.get("gedreht"):
        z.append(tr("Gedrehte Scans richtig herum gespeichert ({drehen}): {0} PDFs").format(te.get('gedreht', 0), drehen=drehen))
    gerade = getattr(getattr(idx, "konfig", None), "auto_gerade", "aus")
    if gerade != "aus" or te.get("gerade"):
        z.append(tr("Schiefe Scans gerade ausgerichtet ({gerade}): {0} PDFs").format(te.get('gerade', 0), gerade=gerade))
    if st["laeufe"]:
        lauf = st["laeufe"][0]
        z.append(tr("Letzter Lauf: {beginn} bis {0} – {status} ({phase})").format(lauf['ende'] or '…', beginn=lauf['beginn'], status=lauf['status'], phase=lauf['phase']))
    return "\n".join(z)


def ergebnisse(erg: dict, abfrage: str) -> str:
    t = erg["treffer"]
    if not t:
        return tr("Keine Treffer für: {abfrage}  (FTS-Abfrage: {abfrage2})").format(abfrage=abfrage, abfrage2=erg['abfrage'])
    kopf = tr("{gesamt}{0} Dokumente für „{abfrage}“ – {anzahl} angezeigt ({dauer_ms} ms)").format('+' if erg['mehr'] else '', gesamt=erg['gesamt'], abfrage=abfrage, anzahl=len(t), dauer_ms=erg['dauer_ms'])
    zeilen = [kopf, ""]
    for d in t:
        status = "" if d["textstatus"] in ("text", "ocr") else f" [{d['textstatus']}]"
        if d["typ"] == "mail":
            zeilen.append(tr("[{id}] MAIL {0}  {name}{status}").format(datum(d['datum']), id=d['id'], name=d['name'], status=status))
            zeilen.append(tr("      Von: {mail_von}  |  {ordner}").format(mail_von=d['mail_von'], ordner=d['ordner']))
        else:
            seiten = f", {d['seiten']} S." if d.get("seiten") else ""
            ocr = tr(", OCR") if d.get("ocr_seiten") else ""
            zeilen.append(f"[{d['id']}] {d['typ'].upper()} {datum(d['datum'])}{seiten}{ocr}{status}  {d['pfad']}")
        if d.get("im_namen") and not d["stellen"]:
            zeilen.append(tr("      (Treffer im Datei-/Ordnernamen)"))
        for s in d["stellen"]:
            seite = (f"S.{s['seite']}: " if d["typ"] == "pdf"
                     else tr("Blatt {seite}: ").format(seite=s['seite']) if d.get("format") in ("xlsx", "xlsm", "xls") else "")
            zeilen.append(f"      {seite}{ausschnitt(s['text'])}")
        if d["treffer_seiten"] > len(d["stellen"]):
            zeilen.append(tr("      … insgesamt {treffer_seiten} Seiten mit Treffern").format(treffer_seiten=d['treffer_seiten']))
        zeilen.append("")
    return "\n".join(zeilen)
