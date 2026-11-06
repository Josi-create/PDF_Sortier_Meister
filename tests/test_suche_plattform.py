"""Dokumentensuche: Plattformschicht (``src/search/plattform.py``).

Die Plattform wird wie in ``test_platform_paths.py`` per ``monkeypatch`` von
``sys.platform`` simuliert; Systemaufrufe (kernel32, ioreg, taskpolicy,
setpgrp) werden durch Attrappen ersetzt. Nur die Dateisperre laeuft echt auf
der jeweiligen Plattform.
"""

import os
import stat
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.search import plattform
from src.utils.tesseract import fehlende_sprachen

# --------------------------------------------------------------------------- Dateisperre

def test_sperre_ist_exklusiv_auch_im_selben_prozess(tmp_path):
    p = tmp_path / "indexer.lock"
    with open(p, "a+") as f1, open(p, "a+") as f2:
        plattform.sperren(f1)
        with pytest.raises(OSError):
            plattform.sperren(f2)
        plattform.entsperren(f1)
        plattform.sperren(f2)          # frei: jetzt klappt es
        plattform.entsperren(f2)
        plattform.entsperren(f2)       # doppelt freigeben ist harmlos


# --------------------------------------------------------------------------- Dateien

def test_nur_cloud_je_plattform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert plattform.nur_cloud(SimpleNamespace(st_file_attributes=plattform.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS))
    assert plattform.nur_cloud(SimpleNamespace(st_file_attributes=plattform.FILE_ATTRIBUTE_OFFLINE))
    assert not plattform.nur_cloud(SimpleNamespace(st_file_attributes=0x20))        # ARCHIVE
    assert not plattform.nur_cloud(SimpleNamespace(st_flags=plattform.SF_DATALESS))  # macOS-Flag zaehlt hier nicht

    monkeypatch.setattr(sys, "platform", "darwin")
    assert plattform.nur_cloud(SimpleNamespace(st_flags=plattform.SF_DATALESS | 0x8000))
    assert not plattform.nur_cloud(SimpleNamespace(st_flags=0))
    assert not plattform.nur_cloud(SimpleNamespace(st_file_attributes=plattform.FILE_ATTRIBUTE_OFFLINE))

    monkeypatch.setattr(sys, "platform", "linux")
    assert not plattform.nur_cloud(SimpleNamespace(st_flags=plattform.SF_DATALESS))


def test_icloud_platzhalter():
    assert plattform.icloud_platzhalter(".Bericht.pdf.icloud") == "Bericht.pdf"
    assert plattform.icloud_platzhalter(".Mietvertrag 2024.docx.ICLOUD") == "Mietvertrag 2024.docx"
    assert plattform.icloud_platzhalter("Bericht.pdf") is None
    assert plattform.icloud_platzhalter("Bericht.pdf.icloud") is None   # nicht versteckt: kein Platzhalter
    assert plattform.icloud_platzhalter(".icloud") is None


def test_verknuepfung_je_plattform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    junction = SimpleNamespace(st_file_attributes=plattform.FILE_ATTRIBUTE_REPARSE_POINT,
                               st_reparse_tag=plattform.IO_REPARSE_TAG_MOUNT_POINT, st_mode=stat.S_IFDIR)
    symlink = SimpleNamespace(st_file_attributes=plattform.FILE_ATTRIBUTE_REPARSE_POINT,
                              st_reparse_tag=plattform.IO_REPARSE_TAG_SYMLINK, st_mode=stat.S_IFDIR)
    onedrive = SimpleNamespace(st_file_attributes=plattform.FILE_ATTRIBUTE_REPARSE_POINT,
                               st_reparse_tag=0x9000001A, st_mode=stat.S_IFDIR)  # Cloud-Files-Reparse-Punkt
    normal = SimpleNamespace(st_file_attributes=0x10, st_reparse_tag=0, st_mode=stat.S_IFDIR)
    assert plattform.verknuepfung(junction) and plattform.verknuepfung(symlink)
    assert not plattform.verknuepfung(onedrive) and not plattform.verknuepfung(normal)

    monkeypatch.setattr(sys, "platform", "darwin")
    assert plattform.verknuepfung(SimpleNamespace(st_mode=stat.S_IFLNK | 0o755))
    assert not plattform.verknuepfung(SimpleNamespace(st_mode=stat.S_IFDIR | 0o755))
    assert not plattform.verknuepfung(junction)   # Windows-Attribute zaehlen unter macOS nicht


def test_im_dateimanager_zeigen(monkeypatch, tmp_path):
    aufrufe = []
    monkeypatch.setattr(plattform.subprocess, "Popen", lambda args, **kw: aufrufe.append(args))
    monkeypatch.setattr(plattform, "open_with_default_app", lambda p: aufrufe.append(["xdg", str(p)]))
    datei = str(tmp_path / "Ordner" / "Brief.pdf")

    monkeypatch.setattr(sys, "platform", "win32")
    plattform.im_dateimanager_zeigen(datei)
    assert aufrufe[-1] == ["explorer", "/select,", os.path.normpath(datei)]
    monkeypatch.setattr(sys, "platform", "darwin")
    plattform.im_dateimanager_zeigen(datei)
    assert aufrufe[-1] == ["open", "-R", datei]
    monkeypatch.setattr(sys, "platform", "linux")
    plattform.im_dateimanager_zeigen(datei)
    assert aufrufe[-1] == ["xdg", os.path.dirname(datei)]


# --------------------------------------------------------------------------- Prozesse

@pytest.mark.parametrize("platform, abgekoppelt, erwartet", [
    ("win32", False, {"creationflags": plattform.CREATE_NO_WINDOW}),
    ("win32", True, {"creationflags": plattform.DETACHED_PROCESS | plattform.CREATE_NEW_PROCESS_GROUP}),
    ("darwin", False, {}),
    ("darwin", True, {"start_new_session": True}),
    ("linux", True, {"start_new_session": True}),
])
def test_popen_flags(monkeypatch, platform, abgekoppelt, erwartet):
    monkeypatch.setattr(sys, "platform", platform)
    assert plattform.popen_flags(abgekoppelt=abgekoppelt) == erwartet


def test_kinder_an_mich_binden_posix_laesst_prozessgruppe_in_ruhe(monkeypatch):
    """Kein setpgrp: der Dienst bliebe sonst im Terminal ohne Strg+C; die Oberflaeche startet ihn ohnehin in eigener Sitzung."""
    monkeypatch.setattr(sys, "platform", "darwin")

    def verboten():
        raise AssertionError("setpgrp darf nicht aufgerufen werden")

    monkeypatch.setattr(plattform.os, "setpgrp", verboten, raising=False)
    monkeypatch.setattr(plattform.os, "setsid", verboten, raising=False)
    assert plattform.kinder_an_mich_binden() is True


@pytest.mark.skipif(sys.platform != "win32", reason="Job-Objekt gibt es nur unter Windows")
def test_kinder_an_mich_binden_windows(monkeypatch):
    # Echtes Job-Objekt fuer den Testprozess: unkritisch, pytest hat keine Kinder, die sterben koennten.
    monkeypatch.setattr(plattform, "_job", None)
    if not plattform.kinder_an_mich_binden():
        pytest.skip("Job-Objekt in dieser Umgebung nicht erlaubt (Prozess steckt in einem fremden Job)")
    assert plattform._job is not None


def test_elternwaechter_beendet_bei_elternwechsel(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    ppids = iter([4711, 4711, 1])      # Start, noch da, dann uebernimmt launchd/init die Waise
    monkeypatch.setattr(plattform.os, "getppid", lambda: next(ppids, 1))
    beendet = threading.Event()
    codes = []

    def beenden(code):
        codes.append(code)
        beendet.set()

    t = plattform.elternwaechter_starten(intervall=0.01, beenden=beenden)
    assert t is not None and t.daemon
    assert beendet.wait(5) and codes == [1]
    t.join(5)
    assert not t.is_alive()

    monkeypatch.setattr(sys, "platform", "win32")
    assert plattform.elternwaechter_starten(intervall=0.01, beenden=beenden) is None


def test_niedrige_prioritaet_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    aufrufe = []

    class FakeK32:
        def GetCurrentProcess(self):  # noqa: N802 - Windows-API-Name
            return 42

        def SetPriorityClass(self, h, klasse):  # noqa: N802 - Windows-API-Name
            aufrufe.append((h, klasse))
            return 0 if klasse == plattform.PROCESS_MODE_BACKGROUND_BEGIN else 1   # Hintergrundmodus schlaegt fehl

    monkeypatch.setattr(plattform, "_kernel32", lambda: FakeK32())
    plattform.niedrige_prioritaet_setzen()
    assert aufrufe == [(42, plattform.PROCESS_MODE_BACKGROUND_BEGIN), (42, plattform.BELOW_NORMAL_PRIORITY_CLASS)]


def test_niedrige_prioritaet_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    aufrufe = []
    nice_stand = {"wert": 5}

    def nice(inc):
        nice_stand["wert"] += inc
        aufrufe.append(("nice", inc))
        return nice_stand["wert"]

    monkeypatch.setattr(plattform.os, "nice", nice, raising=False)
    monkeypatch.setattr(plattform, "_io_drosseln", lambda: aufrufe.append(("io",)))
    monkeypatch.setattr(plattform.shutil, "which", lambda n: "/usr/sbin/taskpolicy" if n == "taskpolicy" else None)
    monkeypatch.setattr(plattform.subprocess, "run", lambda args, **kw: aufrufe.append(tuple(args)))
    plattform.niedrige_prioritaet_setzen()
    assert ("nice", 0) in aufrufe and ("nice", 14) in aufrufe and nice_stand["wert"] == 19
    assert ("io",) in aufrufe
    assert ("/usr/sbin/taskpolicy", "-b", "-p", str(os.getpid())) in aufrufe

    # Linux: nice, aber weder E/A-Drosselung noch taskpolicy
    aufrufe.clear()
    nice_stand["wert"] = 19
    monkeypatch.setattr(sys, "platform", "linux")
    plattform.niedrige_prioritaet_setzen()
    assert aufrufe == [("nice", 0)]


# --------------------------------------------------------------------------- Leerlauf

def test_leerlauf_sekunden_macos_und_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    ausgabe = ('+-o IOHIDSystem  <class IOHIDSystem, id 0x100000123, registered, matched, active>\n'
               '    {\n      "HIDIdleTime" = 125500000000\n      "IOClass" = "IOHIDSystem"\n    }\n')
    monkeypatch.setattr(plattform.subprocess, "run",
                        lambda args, **kw: subprocess.CompletedProcess(args, 0, stdout=ausgabe, stderr=""))
    assert plattform.leerlauf_sekunden() == 125.5
    monkeypatch.setattr(plattform.subprocess, "run",
                        lambda args, **kw: subprocess.CompletedProcess(args, 0, stdout="nichts", stderr=""))
    assert plattform.leerlauf_sekunden() is None

    def fehlt(args, **kw):
        raise FileNotFoundError("ioreg")

    monkeypatch.setattr(plattform.subprocess, "run", fehlt)
    assert plattform.leerlauf_sekunden() is None

    monkeypatch.setattr(sys, "platform", "linux")
    assert plattform.leerlauf_sekunden() is None


@pytest.mark.skipif(sys.platform != "win32", reason="GetLastInputInfo gibt es nur unter Windows")
def test_leerlauf_sekunden_windows_echt():
    s = plattform.leerlauf_sekunden()
    assert s is None or 0 <= s < 365 * 86400


# --------------------------------------------------------------------------- Thunderbird

PROFILES_INI = """[General]
StartWithLastProfile=1
Version=2

[Profile1]
Name=alt
IsRelative=1
Path=Profiles/abcd1234.default
Default=1

[Profile0]
Name=default-release
IsRelative=0
Path={absolut}

[Install9A1B2C3D]
Default={absolut}
Locked=1
"""


def test_thunderbird_profile_und_mail_ordner(tmp_path):
    basis = tmp_path / "Thunderbird"
    (basis / "Profiles" / "abcd1234.default").mkdir(parents=True)
    extern = tmp_path / "Anderswo" / "Profil"
    (extern / "Mail" / "Local Folders").mkdir(parents=True)
    (extern / "ImapMail").mkdir()
    ini = basis / "profiles.ini"
    ini.write_text(PROFILES_INI.format(absolut=str(extern)), encoding="utf-8")

    profile = plattform.thunderbird_profile(ini)
    assert [p.name for p in profile] == ["default-release", "alt"]
    assert profile[0].standard is True and profile[0].pfad == Path(os.path.normpath(str(extern)))
    assert profile[1].standard is False
    assert profile[1].pfad == Path(os.path.normpath(str(basis / "Profiles" / "abcd1234.default")))
    assert plattform.thunderbird_mail_ordner(ini) == [str(extern / "Mail"), str(extern / "ImapMail")]


def test_thunderbird_ohne_install_abschnitt_nimmt_default_1(tmp_path):
    ini = tmp_path / "profiles.ini"
    ini.write_text("[Profile0]\nName=a\nIsRelative=1\nPath=Profiles/a\n\n"
                   "[Profile1]\nName=b\nIsRelative=1\nPath=Profiles/b\nDefault=1\n", encoding="utf-8")
    profile = plattform.thunderbird_profile(ini)
    assert [p.name for p in profile] == ["b", "a"] and profile[0].standard
    assert plattform.thunderbird_mail_ordner(ini) == []   # Ordner existieren nicht
    # Einziges Profil ohne Default-Markierung ist das Standardprofil
    ini.write_text("[Profile0]\nName=a\nIsRelative=1\nPath=Profiles/a\n", encoding="utf-8")
    assert plattform.thunderbird_profile(ini)[0].standard is True


def test_thunderbird_fehlt(tmp_path, monkeypatch):
    assert plattform.thunderbird_profile(tmp_path / "gibt-es-nicht.ini") == []
    assert plattform.thunderbird_mail_ordner(tmp_path / "gibt-es-nicht.ini") == []
    monkeypatch.setattr(plattform, "_home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert plattform.thunderbird_basis() == tmp_path / "Library" / "Thunderbird"
    assert plattform.thunderbird_profile() == []
    monkeypatch.setattr(sys, "platform", "linux")
    assert plattform.thunderbird_basis() == tmp_path / ".thunderbird"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert plattform.thunderbird_basis() == tmp_path / "Roaming" / "Thunderbird"


# --------------------------------------------------------------------------- Wurzeln

def test_wurzel_vorschlaege_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(plattform, "_laufwerke", lambda: [
        ("C:\\", plattform.DRIVE_FIXED), ("D:\\", 5), ("E:\\", plattform.DRIVE_REMOVABLE), ("Z:\\", 4)])
    assert plattform.wurzel_vorschlaege() == ["C:\\", "E:\\"]   # keine CD (5), keine Netzlaufwerke (4)


def test_wurzel_vorschlaege_macos_und_linux(monkeypatch, tmp_path):
    home = tmp_path / "home" / "nutzer"
    home.mkdir(parents=True)
    volumes = tmp_path / "Volumes"
    (volumes / "Daten").mkdir(parents=True)
    (volumes / "Backup").mkdir()
    (volumes / ".Zeitmaschine").mkdir()
    (volumes / "Datei.txt").write_text("x")
    monkeypatch.setattr(plattform, "_home", lambda: home)
    monkeypatch.setattr(plattform, "_VOLUMES", volumes)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert plattform.wurzel_vorschlaege() == [str(home), str(volumes / "Backup"), str(volumes / "Daten")]

    monkeypatch.setattr(sys, "platform", "linux")
    assert plattform.wurzel_vorschlaege() == [str(home)]   # /media/nutzer und /mnt gibt es hier nicht


# --------------------------------------------------------------------------- Tesseract

def test_fehlende_sprachen(tmp_path):
    assert fehlende_sprachen(None, "deu+eng") == []
    assert fehlende_sprachen(str(tmp_path / "nicht-da"), "deu+eng") == []
    (tmp_path / "deu.traineddata").write_bytes(b"x")
    assert fehlende_sprachen(str(tmp_path), "deu+eng") == ["eng"]
    assert fehlende_sprachen(str(tmp_path), "deu") == []
    assert fehlende_sprachen(str(tmp_path), " deu + fra ") == ["fra"]
