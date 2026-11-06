"""Dokumentensuche: Thunderbird-mbox (Trennung, geloeschte Mails, Weiterlesen ab Offset, Postfaecher)."""

import helfer_suche as h
from src.search import mbox


def test_mails_trennen_und_geloeschte_ueberspringen(tmp_path):
    # "From " mitten im Text ohne Leerzeile davor ist keine Trennzeile (Thunderbird
    # maskiert echte Faelle ohnehin als ">From ")
    m1 = h.mail_roh("Erste", text="Hallo\nFrom hier ist keine Trennzeile", mozilla_status="0001")
    m2 = h.mail_roh("Geloescht", text="weg", mozilla_status="0009")   # 0x0008 = expunged
    m3 = h.mail_roh("Dritte", text="Ende", mozilla_status="0000")
    p = h.mbox(tmp_path / "INBOX", [m1, m2, m3])
    gefunden = list(mbox.mails(str(p)))
    assert [b"Subject: Erste" in roh for _, _, roh in gefunden] == [True, False]
    assert b"Subject: Dritte" in gefunden[1][2]
    # Offsets und Laengen beschreiben genau die Mail samt Trennzeile
    off, laenge, _ = gefunden[1]
    assert mbox.anfang_passt(str(p), off) is True
    roh = mbox.mail_roh(str(p), off, laenge)
    assert roh.startswith(b"X-Mozilla-Status: 0000") and roh.rstrip().endswith(b"Ende")
    assert off + laenge == p.stat().st_size


def test_weiterlesen_ab_offset(tmp_path):
    p = h.mbox(tmp_path / "INBOX", [h.mail_roh("Alt", mozilla_status="0000")])
    groesse = p.stat().st_size
    with open(p, "ab") as f:
        f.write(b"From - Thu Jan 11 10:00:00 2024\n" + h.mail_roh("Neu", mozilla_status="0000") + b"\n")
    assert mbox.anfang_passt(str(p), groesse)
    assert mbox.anfang_passt(str(p), groesse + 3) is False
    neue = list(mbox.mails(str(p), start=groesse))
    assert len(neue) == 1 and b"Subject: Neu" in neue[0][2] and neue[0][0] == groesse


def test_postfaecher_nur_mit_msf(tmp_path):
    konto = tmp_path / "Mail" / "pop.example.invalid"
    (konto / "Archiv.sbd").mkdir(parents=True)
    h.mbox(konto / "Inbox", [])
    h.mbox(konto / "Archiv.sbd" / "2023", [])
    (konto / "Entwuerfe").write_bytes(b"")           # ohne .msf -> keine mbox
    (konto / "msgFilterRules.dat").write_bytes(b"")
    (konto / "msgFilterRules.dat.msf").write_bytes(b"")
    namen = sorted(name for _, name in mbox.postfaecher(str(tmp_path / "Mail")))
    assert namen == ["Thunderbird/pop.example.invalid/Archiv/2023", "Thunderbird/pop.example.invalid/Inbox"]
    assert mbox.ist_mbox(str(konto / "Entwuerfe")) is False
