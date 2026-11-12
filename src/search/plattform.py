"""Plattformschicht der Dokumentensuche (Qt-frei): Windows, macOS, Linux.

Alles, was sich zwischen den Betriebssystemen unterscheidet, liegt hier
(Abschnitt 5 von ``docs/SUCHE_ARCHITEKTUR.md``): Dateisperre, „Arbeitsprozesse
sterben mit“, Hintergrundprioritaet, Cloud-Platzhalter, Junctions/Symlinks,
Unterprozess-Flags, Leerlaufzeit, Thunderbird-Profil, Wurzel-Vorschlaege,
Datei im Dateimanager zeigen, Tesseract.

``sys.platform`` wird bewusst erst zur Aufrufzeit gelesen, damit Tests die
Plattform per ``monkeypatch`` simulieren koennen. Windows-Importe (``msvcrt``,
``ctypes.wintypes``) stehen nur in Funktionen hinter ``sys.platform == "win32"``,
damit das Paket unter macOS und Linux importierbar bleibt. Linux laeuft als
Nebenprodukt der macOS-Zweige mit (``fcntl``, ``nice``, keine Cloud-Attribute),
ist aber kein Ziel.
"""

from __future__ import annotations

import configparser
import logging
import os
import re
import shutil
import stat as stat_modul
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from src.utils.platform_paths import (  # noqa: F401 - Re-Export
    file_manager_name,
    open_with_default_app,
)
from src.utils.tesseract import (  # noqa: F401 - Re-Export
    fehlende_sprachen,
    find_tesseract,
    tessdata_dir,
)
from src.i18n import tr

log = logging.getLogger("pdf_sortier_meister.suche")

# --------------------------------------------------------------------------- Konstanten
# Windows: Dateiattribute (st_file_attributes) und Reparse-Tags (st_reparse_tag)
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_NUR_WINDOWS = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
IO_REPARSE_TAG_SYMLINK = 0xA000000C
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
# Windows: Prozesse
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
PROCESS_MODE_BACKGROUND_BEGIN = 0x00100000
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
# Windows: Datei ersetzen (Textebene, ``datei_ersetzen``)
FILE_ATTRIBUTE_READONLY = 0x1
REPLACEFILE_IGNORE_MERGE_ERRORS = 0x2
REPLACEFILE_IGNORE_ACL_ERRORS = 0x4
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_ACCESS_DENIED = 5
ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33
ERROR_UNABLE_TO_REMOVE_REPLACED = 1175
ERROR_UNABLE_TO_MOVE_REPLACEMENT = 1176
# macOS: st_flags einer Datei, die ein File-Provider (iCloud, OneDrive, Dropbox) nur als Platzhalter haelt
SF_DATALESS = 0x40000000
# macOS: setiopolicy_np(IOPOL_TYPE_DISK, IOPOL_SCOPE_PROCESS, IOPOL_THROTTLE)
IOPOL_TYPE_DISK = 0
IOPOL_SCOPE_PROCESS = 0
IOPOL_THROTTLE = 3

_VOLUMES = Path("/Volumes")
_job = None  # Windows-Job-Objekt (Handle bleibt bis Prozessende offen)


def ist_windows() -> bool:
    return sys.platform == "win32"


def ist_macos() -> bool:
    return sys.platform == "darwin"


def _home() -> Path:
    return Path.home()


# --------------------------------------------------------------------------- Dateisperre

def sperren(f) -> None:
    """Exklusive, nicht blockierende Sperre auf der geoeffneten Datei; ``OSError``, wenn sie vergeben ist.

    Windows: ``msvcrt.locking`` auf das erste Byte. Sonst ``fcntl.flock`` (nicht
    ``lockf``): ``flock`` wirkt auch zwischen zwei Oeffnungen im selben Prozess,
    damit ``laeuft_gerade()`` im Dienst selbst stimmt.
    """
    if sys.platform == "win32":
        import msvcrt

        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def entsperren(f) -> None:
    """Sperre aus ``sperren`` freigeben (Fehler werden verschluckt: die Datei wird ohnehin geschlossen)."""
    try:
        if sys.platform == "win32":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


# --------------------------------------------------------------------------- Prozesse

def kinder_an_mich_binden() -> bool:
    """Arbeitsprozesse (und deren Tesseract) enden mit diesem Prozess.

    Windows: Job-Objekt mit ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``; endet der
    Dienst (z. B. Leerlauf vorbei, Aufgabenplanung bricht ab), raeumt das System
    alle Kinder weg. macOS/Linux: Die Kinder bleiben in der Prozessgruppe des
    Dienstes - startet ihn die Oberflaeche (``start_new_session=True``) oder
    launchd, ist das eine eigene Sitzung, und ``os.killpg(pid, SIGTERM)`` trifft
    Dienst, Arbeitsprozesse und Tesseract gemeinsam; im Terminal erreicht
    Strg+C weiterhin alle. Ein eigenes ``setpgrp`` wuerde den Dienst dort aus
    der Vordergrundgruppe loesen, deshalb unterbleibt es. Dazu prueft in jedem
    Arbeitsprozess ein Waechter-Thread den Elternprozess
    (``elternwaechter_starten``). Liefert True, wenn die Bindung eingerichtet
    werden konnte.
    """
    if sys.platform == "win32":
        return _job_objekt_anlegen()
    return hasattr(os, "getppid")


def _job_objekt_anlegen() -> bool:
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):  # noqa: N801 - Windows-API-Name
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    global _job
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) and \
                k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
            _job = job
            return True
    except Exception as e:  # nicht kritisch
        log.debug("Job-Objekt nicht möglich: %s", e)
    return False


def elternwaechter_starten(intervall: float = 2.0, beenden=os._exit) -> threading.Thread | None:
    """In Arbeitsprozessen (macOS/Linux): Thread, der ``os.getppid()`` prueft.

    Stirbt der Dienstprozess, uebernimmt launchd/init die Waisen und die
    Eltern-PID wechselt; der Arbeitsprozess beendet sich dann sofort mit
    ``os._exit`` (kein Aufraeumen, keine haengenden Futures). Windows: None,
    dort erledigt das Job-Objekt die Aufgabe.
    """
    if sys.platform == "win32":
        return None
    eltern = os.getppid()

    def _lauf() -> None:
        while True:
            time.sleep(intervall)
            if os.getppid() != eltern:
                beenden(1)
                return

    t = threading.Thread(target=_lauf, name="elternwaechter", daemon=True)
    t.start()
    return t


def _kernel32():
    import ctypes

    return ctypes.windll.kernel32


def niedrige_prioritaet_setzen() -> None:
    """Diesen Prozess in den Hintergrund: niedrige CPU- und Festplattenprioritaet.

    Windows: ``PROCESS_MODE_BACKGROUND_BEGIN`` (CPU, E/A und Speicher), Fallback
    ``BELOW_NORMAL``. macOS/Linux: ``nice`` 19; unter macOS zusaetzlich die
    E/A-Drosselung (``setiopolicy_np``) und, falls vorhanden, ``taskpolicy -b``
    (entspricht ``ProcessType=Background`` eines LaunchAgents). Arbeitsprozesse
    erben die Einstellung bzw. rufen sie selbst (``extract.arbeiter_start``).
    """
    if sys.platform == "win32":
        try:
            k32 = _kernel32()
            h = k32.GetCurrentProcess()
            if not k32.SetPriorityClass(h, PROCESS_MODE_BACKGROUND_BEGIN):
                k32.SetPriorityClass(h, BELOW_NORMAL_PRIORITY_CLASS)
        except Exception as e:  # pragma: no cover - nur ohne kernel32
            log.debug("Hintergrundpriorität nicht möglich: %s", e)
        return
    try:
        aktuell = os.nice(0)
        if aktuell < 19:
            os.nice(19 - aktuell)
    except (AttributeError, OSError):
        pass
    if sys.platform == "darwin":
        _io_drosseln()
        taskpolicy = shutil.which("taskpolicy")
        if taskpolicy:
            try:
                subprocess.run([taskpolicy, "-b", "-p", str(os.getpid())], capture_output=True, timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass


def _io_drosseln() -> None:
    """macOS: Festplattenzugriffe dieses Prozesses drosseln (wie ``nice`` fuer E/A)."""
    try:
        import ctypes
        import ctypes.util

        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        libc.setiopolicy_np(IOPOL_TYPE_DISK, IOPOL_SCOPE_PROCESS, IOPOL_THROTTLE)
    except Exception:  # nicht kritisch
        pass


def popen_flags(abgekoppelt: bool = False) -> dict:
    """Zusatzargumente fuer ``subprocess``.

    Standard: Unterprozess (Tesseract) ohne Konsolenfenster (nur Windows kennt
    das Flag). ``abgekoppelt``: der Dienst wird als eigener Prozess gestartet,
    der den Aufrufer (Oberflaeche, Web) ueberlebt - Windows
    ``DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP``, sonst eigene Sitzung.
    """
    if sys.platform == "win32":
        return {"creationflags": DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP if abgekoppelt else CREATE_NO_WINDOW}
    return {"start_new_session": True} if abgekoppelt else {}


# --------------------------------------------------------------------------- Dateien

def nur_cloud(st: os.stat_result) -> bool:
    """Datei liegt nur in der Cloud; Lesen wuerde einen Download ausloesen (``os.stat`` nicht).

    Windows: OneDrive-Platzhalter (``OFFLINE``, ``RECALL_ON_OPEN``,
    ``RECALL_ON_DATA_ACCESS``). macOS: ``SF_DATALESS`` eines File-Providers
    (iCloud Drive, OneDrive, Dropbox). Sonst immer False.
    """
    if sys.platform == "win32":
        return bool(getattr(st, "st_file_attributes", 0) & CLOUD_NUR_WINDOWS)
    if sys.platform == "darwin":
        return bool(getattr(st, "st_flags", 0) & SF_DATALESS)
    return False


def icloud_platzhalter(name: str) -> str | None:
    """Name der echten Datei zu einem iCloud-Platzhalter ``.Bericht.pdf.icloud``; sonst None.

    iCloud Drive legt fuer ausgelagerte Dateien einen versteckten Platzhalter
    ab, die eigentliche Datei fehlt im Ordner. Der Lauf nimmt sie dann nur mit
    Namen auf (Status ``cloud``), wie OneDrive-Platzhalter unter Windows.
    """
    if name.startswith(".") and name.lower().endswith(".icloud") and len(name) > 8:
        return name[1:-7]
    return None


def verknuepfung(st: os.stat_result) -> bool:
    """Junction/Symlink (Windows: Reparse-Tag) bzw. Symlink (sonst) - wird uebersprungen.

    Sonst entstehen Endlosschleifen und doppelte Eintraege. Windows:
    ``st_reparse_tag`` gibt es ab Python 3.8, ``os.path.isjunction`` erst ab 3.12.
    """
    if sys.platform == "win32":
        if not getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
            return False
        return getattr(st, "st_reparse_tag", 0) in (IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT)
    return stat_modul.S_ISLNK(getattr(st, "st_mode", 0))


def schreibgeschuetzt(st: os.stat_result) -> bool:
    """Datei ist schreibgeschuetzt (Windows: Attribut ``READONLY``, sonst fehlendes Schreibrecht des Besitzers)."""
    if sys.platform == "win32":
        return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_READONLY)
    return not st.st_mode & stat_modul.S_IWUSR


def gesperrt(pfad: str) -> bool:
    """Haelt ein anderes Programm die Datei so offen, dass niemand schreiben darf (z. B. PaperPort, Acrobat)?

    Nur unter Windows erkennbar (Freigabemodus beim Oeffnen); macOS und Linux
    kennen keine solche Sperre. Geoeffnet wird ohne zu schreiben, die
    Aenderungszeit bleibt. Haelt ein Programm die Datei nur zum Lesen offen,
    scheitert erst ``datei_ersetzen`` (``PermissionError``).
    """
    if sys.platform != "win32":
        return False
    try:
        fd = os.open(pfad, os.O_RDWR | getattr(os, "O_BINARY", 0))
    except FileNotFoundError:
        return False
    except OSError:
        return True
    os.close(fd)
    return False


def datei_ersetzen(ziel: str, ersatz: str) -> None:
    """``ziel`` durch ``ersatz`` (im selben Ordner) ersetzen; ``ziel`` muss noch existieren.

    Windows: ``ReplaceFileW`` statt ``os.replace``. Es behaelt Erstelldatum,
    Attribute, Zugriffsrechte, alternative Datenstroeme und die Identitaet der
    Datei (OneDrive fuehrt die Versionsgeschichte fort) und scheitert, wenn
    ``ziel`` inzwischen verschoben oder geloescht wurde - dann entsteht am
    alten Ort keine zweite Datei. Sonst ``os.replace`` (atomar) mit den
    Zugriffsrechten des Originals.

    Raises:
        FileNotFoundError: ``ziel`` gibt es nicht mehr (verschoben, geloescht).
        PermissionError: ``ziel`` ist geoeffnet oder gesperrt.
        OSError: sonstiger Fehler; ``ziel`` ist dann unveraendert.
    """
    if sys.platform == "win32":
        _ersetzen_windows(os.path.abspath(ziel), os.path.abspath(ersatz))
        return
    if not os.path.isfile(ziel):
        raise FileNotFoundError(2, tr("Datei nicht mehr vorhanden"), ziel)
    try:
        shutil.copymode(ziel, ersatz)
    except OSError:
        pass
    os.replace(ersatz, ziel)


def _ersetzen_windows(ziel: str, ersatz: str) -> None:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    replace_file = k32.ReplaceFileW
    replace_file.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                             wintypes.LPVOID, wintypes.LPVOID]
    replace_file.restype = wintypes.BOOL
    if replace_file(ziel, ersatz, None, REPLACEFILE_IGNORE_MERGE_ERRORS | REPLACEFILE_IGNORE_ACL_ERRORS, None, None):
        return
    fehler = ctypes.get_last_error()
    if fehler in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
        raise FileNotFoundError(2, tr("Datei nicht mehr vorhanden"), ziel)
    if fehler == ERROR_UNABLE_TO_MOVE_REPLACEMENT and not os.path.exists(ziel) and os.path.exists(ersatz):
        # Laut Dokumentation ist das Original dann schon entfernt: den geprueften Ersatz an seinen Platz
        os.replace(ersatz, ziel)
        return
    if fehler in (ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION, ERROR_UNABLE_TO_REMOVE_REPLACED):
        raise PermissionError(13, tr("Datei ist geöffnet oder gesperrt"), ziel)
    raise OSError(fehler, ctypes.FormatError(fehler).strip(), ziel)


def onedrive_ordner() -> list[str]:
    """Von OneDrive synchronisierte Ordner (fuer die Schaetzung des Uploads beim Schreiben der Textebene).

    Windows: Umgebungsvariablen ``OneDrive``, ``OneDriveConsumer``,
    ``OneDriveCommercial``. macOS: ``~/Library/CloudStorage/OneDrive*`` und ein
    aelteres ``~/OneDrive``.
    """
    erg: list[str] = []
    if sys.platform == "win32":
        for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            p = os.environ.get(name)
            if p and os.path.isdir(p):
                erg.append(os.path.normpath(p))
    elif sys.platform == "darwin":
        basis = _home() / "Library" / "CloudStorage"
        try:
            erg += [str(p) for p in basis.iterdir() if p.name.startswith("OneDrive") and p.is_dir()]
        except OSError:
            pass
        if (_home() / "OneDrive").is_dir():
            erg.append(str(_home() / "OneDrive"))
    eindeutig: dict[str, str] = {}
    for p in erg:
        eindeutig.setdefault(os.path.normcase(p), p)
    return sorted(eindeutig.values(), key=str.lower)


def im_dateimanager_zeigen(pfad: str) -> None:
    """Datei im Explorer (Windows) bzw. Finder (macOS) markieren; sonst den Ordner oeffnen."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(pfad)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", pfad])
    else:
        open_with_default_app(os.path.dirname(pfad))


# --------------------------------------------------------------------------- Leerlauf

def leerlauf_sekunden() -> float | None:
    """Sekunden seit der letzten Eingabe des Nutzers; None, wenn nicht ermittelbar.

    Windows: ``GetLastInputInfo`` (die Aufgabenplanung prueft Leerlauf selbst,
    der Wert dient dem Lauf mit ``--nur-leerlauf``). macOS: ``HIDIdleTime`` aus
    ``ioreg`` (Nanosekunden); ein LaunchAgent kennt keine Leerlaufbedingung,
    deshalb pausiert der Indexer dort selbst. Linux: None.
    """
    if sys.platform == "win32":
        return _leerlauf_windows()
    if sys.platform == "darwin":
        return _leerlauf_macos()
    return None


def _leerlauf_windows() -> float | None:
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        user32 = ctypes.windll.user32
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return None


_HID_IDLE = re.compile(r'"HIDIdleTime"\s*=\s*(\d+)')


def _leerlauf_macos() -> float | None:
    try:
        r = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-r", "-d", "1"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    m = _HID_IDLE.search(r.stdout or "")
    if not m:
        return None
    return int(m.group(1)) / 1_000_000_000


# --------------------------------------------------------------------------- Thunderbird

@dataclass
class ThunderbirdProfil:
    name: str
    pfad: Path
    standard: bool = False


def thunderbird_basis() -> Path:
    """Ordner mit ``profiles.ini``: Windows ``%APPDATA%\\Thunderbird``, macOS ``~/Library/Thunderbird``, Linux ``~/.thunderbird``."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(_home() / "AppData" / "Roaming"))) / "Thunderbird"
    if sys.platform == "darwin":
        return _home() / "Library" / "Thunderbird"
    return _home() / ".thunderbird"


def thunderbird_profile(profiles_ini: Path | str | None = None) -> list[ThunderbirdProfil]:
    """Profile aus ``profiles.ini``, das Standardprofil zuerst; leer, wenn kein Thunderbird gefunden wird.

    ``[ProfileN]``: ``Name``, ``Path``, ``IsRelative`` (0 = absoluter Pfad, z. B.
    ein Profil auf einem anderen Laufwerk), ``Default=1``. Neuere Versionen
    fuehren das Standardprofil je Installation in ``[InstallXXXX]`` mit
    ``Default=<Pfad>``; dieser Eintrag hat Vorrang. Apple Mail (``.emlx``) ist
    nur vorgemerkt, nicht umgesetzt.
    """
    ini = Path(profiles_ini) if profiles_ini else thunderbird_basis() / "profiles.ini"
    if not ini.is_file():
        return []
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        cp.read(ini, encoding="utf-8-sig")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return []
    basis = ini.parent
    install_standard: set[Path] = set()
    for sec in cp.sections():
        if sec.lower().startswith("install"):
            p = cp[sec].get("default", "").strip()
            if p:
                install_standard.add(_norm_profilpfad(p, basis, relativ=not Path(p).is_absolute()))
    profile: list[ThunderbirdProfil] = []
    for sec in cp.sections():
        if not sec.lower().startswith("profile"):
            continue
        s = cp[sec]
        p = s.get("path", "").strip()
        if not p:
            continue
        pfad = _norm_profilpfad(p, basis, relativ=s.get("isrelative", "1").strip() != "0")
        standard = pfad in install_standard if install_standard else s.get("default", "0").strip() == "1"
        profile.append(ThunderbirdProfil(name=s.get("name", sec).strip() or sec, pfad=pfad, standard=standard))
    if profile and not any(p.standard for p in profile):
        profile[0].standard = True
    profile.sort(key=lambda p: not p.standard)
    return profile


def _norm_profilpfad(p: str, basis: Path, relativ: bool) -> Path:
    pfad = (basis / p) if relativ else Path(p)
    return Path(os.path.normpath(str(pfad)))


def thunderbird_mail_ordner(profiles_ini: Path | str | None = None) -> list[str]:
    """``Mail/`` und ``ImapMail/`` des Standardprofils, soweit vorhanden (Standard fuer ``mail_ordner``)."""
    profile = thunderbird_profile(profiles_ini)
    if not profile:
        return []
    profil = profile[0]
    return [str(profil.pfad / n) for n in ("Mail", "ImapMail") if (profil.pfad / n).is_dir()]


# --------------------------------------------------------------------------- Wurzeln

def _laufwerke() -> list[tuple[str, int]]:
    """Windows: (``C:\\``, Laufwerkstyp) fuer alle Laufwerksbuchstaben."""
    import ctypes

    k32 = ctypes.windll.kernel32
    maske = k32.GetLogicalDrives()
    ergebnis = []
    for i in range(26):
        if maske & (1 << i):
            wurzel = f"{chr(65 + i)}:\\"
            ergebnis.append((wurzel, int(k32.GetDriveTypeW(wurzel))))
    return ergebnis


def wurzel_vorschlaege() -> list[str]:
    """Vorschlaege fuer Wurzeln im Einrichtungsassistenten (Scan- und Zielordner kommen aus der PDFSM-Konfiguration).

    Windows: feste und Wechsellaufwerke (keine CD/DVD, keine Netzlaufwerke -
    die traegt man bewusst ein). macOS: Benutzerordner und eingehaengte
    ``/Volumes/*`` (ohne den Systemdatentraeger, der nach ``/`` zeigt). Linux:
    Benutzerordner und ``/media/<Nutzer>/*``, ``/mnt/*``.
    """
    if sys.platform == "win32":
        try:
            return [w for w, typ in _laufwerke() if typ in (DRIVE_FIXED, DRIVE_REMOVABLE)]
        except Exception:
            return []
    home = _home()
    vorschlaege = [str(home)]
    if sys.platform == "darwin":
        kandidaten = [_VOLUMES]
    else:
        kandidaten = [Path("/media") / home.name, Path("/mnt")]
    for ordner in kandidaten:
        try:
            eintraege = sorted(os.scandir(ordner), key=lambda e: e.name.lower())
        except OSError:
            continue
        for e in eintraege:
            try:
                if not e.is_dir(follow_symlinks=False) or e.name.startswith("."):
                    continue
                if os.path.realpath(e.path) == os.path.realpath("/"):
                    continue
            except OSError:
                continue
            vorschlaege.append(e.path)
    return vorschlaege
