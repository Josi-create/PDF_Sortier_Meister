"""
Werkzeug für die Übersetzung der Oberfläche (Issue #118).

    python tools/i18n_werkzeug.py kandidaten src/gui/datei.py
        Listet die noch nicht markierten Texte einer Datei. Art A steht an einer
        Stelle, die sicher Oberfläche ist (QLabel, setToolTip, ...), Art B sieht
        nur nach Text aus und muss von Hand bestätigt werden.

    python tools/i18n_werkzeug.py umstellen src/gui/datei.py [--auch 3,7-9] [--nicht 2]
        Setzt tr(...) um alle Texte der Art A (ohne die Nummern aus --nicht) und
        um die Texte der Art B aus --auch. f-Strings und "a" + b + "c" werden zu
        tr("a {b} c").format(b=b). Nummern wie in der Ausgabe von "kandidaten".

    python tools/i18n_werkzeug.py offen [--sprache en]
        Schreibt die Texte ohne Übersetzung nummeriert nach stdout (eine Zeile je
        Text, Zeilenumbrüche als \\n).

    python tools/i18n_werkzeug.py eintragen datei.txt [--sprache en]
        Liest Zeilen "Nummer<TAB>Übersetzung" (Nummern aus "offen") und schreibt
        die .po-Datei neu.

    python tools/i18n_werkzeug.py abgleich [--sprache en]
        Schreibt die .po-Datei neu (Reihenfolge wie im Code, verwaiste Einträge
        entfernt) und meldet fehlende Übersetzungen.

Die Datei gehört nicht zum Programm und wird nicht mit ausgeliefert.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.i18n import LOCALE_DIR, po_literal, read_po  # noqa: E402

# Aufrufe, deren Zeichenketten-Argumente sicher Oberfläche sind
UI_AUFRUFE = {
    "QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QGroupBox", "QAction",
    "QToolButton", "QMenu", "QCommandLinkButton", "QProgressDialog", "QErrorMessage",
    "setText", "setToolTip", "setStatusTip", "setWhatsThis", "setWindowTitle",
    "setPlaceholderText", "setTitle", "setSubTitle", "addAction", "addMenu", "addItem",
    "addItems", "insertItem", "insertItems", "addTab", "insertTab", "addRow", "insertRow",
    "setTabText", "setTabToolTip", "setItemText", "showMessage", "setLabelText",
    "setHeaderLabels", "setHorizontalHeaderLabels", "setVerticalHeaderLabels",
    "setHeaderLabel", "information", "warning", "critical", "question", "about",
    "setInformativeText", "setDetailedText", "addButton", "setButtonText", "getText",
    "getItem", "getInt", "getMultiLineText", "getOpenFileName", "getOpenFileNames",
    "getSaveFileName", "getExistingDirectory", "setSuffix", "setPrefix",
    "setSpecialValueText", "setAccessibleName", "setAccessibleDescription",
    "setCancelButtonText", "setFormat", "setHtml", "setPlainText", "setMarkdown",
    "QTreeWidgetItem", "QListWidgetItem", "QTableWidgetItem", "QMessageBox",
    "setNameFilter", "setLabel", "setItemToolTip", "setPlaceholder", "showText",
    "insertPlainText", "insertHtml", "appendPlainText", "appendHtml", "addSection",
    "setEmptyText", "setDescription", "setCheckBox",
}
# Aufrufe, deren Zeichenketten nie übersetzt werden
NIE_AUFRUFE = {
    "debug", "info", "exception", "log", "getLogger", "get_logger",
    "setObjectName", "setStyleSheet", "setProperty", "property", "getattr", "setattr",
    "hasattr", "isinstance", "open", "encode", "decode", "strftime", "strptime",
    "startswith", "endswith", "split", "rsplit", "replace", "strip", "lstrip", "rstrip",
    "compile", "sub", "match", "search", "fullmatch", "findall", "finditer", "Path",
    "QFont", "QColor", "QIcon", "setFamily", "pyqtSignal", "QKeySequence", "setShortcut",
    "execute", "text", "index", "find", "count", "removeprefix", "removesuffix",
    "partition", "rpartition", "setIconText", "import_module", "__import__", "glob",
    "rglob", "with_suffix", "with_name", "joinpath", "setFontFamily", "QSettings",
    "fromisoformat", "toString", "fromString", "setDisplayFormat", "setInputMask",
    "QRegularExpression", "run", "Popen", "check_output", "column", "Column", "tr",
    "environ", "getenv", "TypeVar", "field", "namedtuple", "setdefault_key",
    "mimeData", "setData", "hasFormat", "data", "setMimeData", "installEventFilter",
    "findChild", "findChildren", "inherits", "setDefaultSuffix", "add_argument",
    "add_parser", "pixmap", "fromTheme", "addPixmap", "load",
}
# Bei diesen Aufrufen ist nur das erste Argument ein Schlüssel
ERSTES_ARGUMENT_SCHLUESSEL = {"get", "pop", "setdefault", "set", "value", "setValue"}
# Empfänger, deren warning/error/critical Protokollaufrufe sind
LOG_NAMEN = re.compile(r"log", re.IGNORECASE)

BUCHSTABEN = re.compile(r"[^\W\d_]{2,}")


def _aufrufname(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _empfaenger(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        try:
            return ast.unparse(func.value)
        except Exception:  # noqa: BLE001
            return ""
    return ""


def _ist_text(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)) or isinstance(
        node, ast.JoinedStr
    )


def _literaltext(node: ast.AST) -> str:
    """Fester Textanteil eines Knotens (für die Prosa-Prüfung)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literaltext(node.left) + _literaltext(node.right)
    return ""


def _kette(node: ast.AST) -> list[ast.expr] | None:
    """Zerlegt a + b + c in [a, b, c]; None, wenn kein Textliteral beteiligt ist."""
    teile: list[ast.expr] = []

    def sammle(n: ast.AST) -> None:
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            sammle(n.left)
            sammle(n.right)
        else:
            teile.append(n)

    sammle(node)
    if any(_ist_text(t) for t in teile):
        return teile
    return None


class Fund:
    def __init__(self, node: ast.expr, art: str, grund: str):
        self.node = node
        self.art = art      # "A" oder "B"
        self.grund = grund  # Name des Aufrufs oder Art der Stelle
        self.nummer = 0


def _eltern(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    eltern: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            eltern[child] = parent
    return eltern


def _docstrings(tree: ast.AST) -> set[ast.AST]:
    ergebnis: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and _ist_text(body[0].value):
                ergebnis.add(body[0].value)
    return ergebnis


def _einordnen(node: ast.expr, eltern: dict[ast.AST, ast.AST]) -> tuple[str, str] | None:
    """Bestimmt Art und Grund eines Text-Ausdrucks; None = nicht übersetzen."""
    kind: ast.AST = node
    while True:
        parent = eltern.get(kind)
        if parent is None:
            return None
        if isinstance(parent, ast.Expr):
            return None  # allein stehende Zeichenkette (Docstring, Kommentar)
        if isinstance(parent, ast.FormattedValue):
            return None  # Ausdruck innerhalb eines f-Strings
        if isinstance(parent, ast.JoinedStr):
            return None
        if isinstance(parent, ast.BinOp):
            if isinstance(parent.op, ast.Add):
                if kind is node and _ist_text(node):
                    return None  # wird über die Kette (Wurzel) behandelt
                kind = parent
                continue
            if isinstance(parent.op, ast.Mod) and parent.left is kind:
                kind = parent
                continue
            return ("B", "rechnung")
        if isinstance(parent, ast.IfExp):
            if parent.test is kind:
                return None
            kind = parent
            continue
        if isinstance(parent, ast.BoolOp):
            kind = parent
            continue
        if isinstance(parent, (ast.List, ast.Tuple, ast.Set, ast.Starred)):
            kind = parent
            continue
        if isinstance(parent, ast.Dict):
            if kind in parent.keys:
                return None
            kind = parent
            continue
        if isinstance(parent, ast.keyword):
            kind = parent
            continue
        if isinstance(parent, ast.Attribute):
            # "…".format(...) / "…".join(...): Empfänger eines Methodenaufrufs
            gross = eltern.get(parent)
            if isinstance(gross, ast.Call) and gross.func is parent:
                if parent.attr == "format":
                    kind = gross
                    continue
                if parent.attr == "join":
                    return None  # Trennzeichen
            return None
        if isinstance(parent, ast.Call):
            if parent.func is kind:
                return None
            name = _aufrufname(parent.func)
            if name == "tr":
                return None
            if name in ("warning", "error", "critical") and LOG_NAMEN.search(
                _empfaenger(parent.func)
            ):
                return None
            if name in NIE_AUFRUFE:
                return None
            if name in UI_AUFRUFE:
                if name in ("addItem", "insertItem") and kind in parent.args:
                    davor = parent.args[: parent.args.index(kind)]
                    if any(_ist_text(a) or isinstance(a, ast.BinOp) for a in davor):
                        return None  # zweites Textargument = hinterlegter Wert
                return ("A", name)
            if name in ERSTES_ARGUMENT_SCHLUESSEL and parent.args and parent.args[0] is kind:
                return None
            return ("B", name or "aufruf")
        if isinstance(parent, (ast.Compare, ast.Subscript, ast.Slice)):
            return None
        if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            return ("B", "zuweisung")
        if isinstance(parent, ast.Return):
            return ("B", "return")
        if isinstance(parent, ast.Raise):
            return ("B", "raise")
        if isinstance(parent, ast.arguments):
            return ("B", "vorgabe")
        if isinstance(parent, (ast.Yield, ast.Lambda, ast.comprehension,
                               ast.ListComp, ast.GeneratorExp, ast.DictComp, ast.SetComp)):
            return ("B", "ausdruck")
        if isinstance(parent, (ast.match_case, ast.MatchValue, ast.Assert, ast.JoinedStr)):
            return None
        return None


def _sieht_nach_prosa_aus(text: str) -> bool:
    if not BUCHSTABEN.search(text):
        return False
    kern = text.strip()
    if " " in kern:
        return True
    if re.search(r"[äöüÄÖÜß…]", kern):
        return True
    # Einzelnes Wort: nur mit großem Anfangsbuchstaben und ohne Bezeichner-Zeichen
    if re.fullmatch(r"[A-ZÄÖÜ][A-Za-zäöüß]*[a-zäöüß][A-Za-zäöüß]*(-[A-Za-zäöüßÄÖÜ]+)*[:.!?…]*", kern):
        return True
    return False


def funde_in(quelle: str) -> list[Fund]:
    tree = ast.parse(quelle)
    eltern = _eltern(tree)
    doku = _docstrings(tree)
    funde: list[Fund] = []
    in_kette: set[ast.AST] = set()

    kandidaten: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            parent = eltern.get(node)
            if isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Add):
                continue  # nicht die Wurzel
            teile = _kette(node)
            if teile:
                for t in teile:
                    in_kette.add(t)
                kandidaten.append(node)
    for node in ast.walk(tree):
        if _ist_text(node) and node not in in_kette and node not in doku:
            kandidaten.append(node)

    for node in kandidaten:
        if isinstance(node, ast.Constant) and getattr(node, "kind", None) == "u":
            continue
        text = _literaltext(node)
        if not BUCHSTABEN.search(text):
            continue
        ergebnis = _einordnen(node, eltern)
        if ergebnis is None:
            continue
        art, grund = ergebnis
        if not _sieht_nach_prosa_aus(text):
            if art == "B":
                continue
            art = "a"  # Oberfläche, aber kein Satz (Kürzel, Bezeichner): von Hand entscheiden
        funde.append(Fund(node, art, grund))

    funde.sort(key=lambda f: (f.node.lineno, f.node.col_offset))
    for nummer, fund in enumerate(funde, 1):
        fund.nummer = nummer
    return funde


# ---------------------------------------------------------------------------
# Umschreiben
# ---------------------------------------------------------------------------

class NichtUmstellbar(Exception):
    pass


def _feldname(expr: ast.expr) -> str | None:
    if (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name)
            and expr.func.id == "len" and not expr.keywords):
        return "anzahl"
    if (isinstance(expr, ast.Subscript) and isinstance(expr.slice, ast.Constant)
            and isinstance(expr.slice.value, str) and expr.slice.value.isidentifier()):
        return expr.slice.value
    if isinstance(expr, ast.Name):
        name = expr.id
    elif isinstance(expr, ast.Attribute):
        name = expr.attr
    else:
        return None
    name = name.strip("_")
    if not name or not name.isidentifier() or name[0].isdigit():
        return None
    return name


class Formatbauer:
    """Baut aus Textteilen und Ausdrücken ``tr("...{feld}...").format(feld=ausdruck)``."""

    def __init__(self) -> None:
        self.text = ""
        self.positionen: list[str] = []          # Quelltext der Positionsargumente
        self.namen: dict[str, str] = {}          # Feldname -> Quelltext
        self._nach_quelle: dict[str, str] = {}   # Quelltext -> Feld

    def literal(self, text: str) -> None:
        self.text += text.replace("{", "{{").replace("}", "}}")

    def ausdruck(self, expr: ast.expr, conversion: int = -1, spec: str = "") -> None:
        quelle = ast.unparse(expr)
        feld = self._nach_quelle.get(quelle)
        if feld is None:
            name = _feldname(expr)
            if name is not None:
                basis, zaehler = name, 2
                while name in self.namen:
                    name = f"{basis}{zaehler}"
                    zaehler += 1
                self.namen[name] = quelle
                feld = name
            else:
                feld = str(len(self.positionen))
                self.positionen.append(quelle)
            self._nach_quelle[quelle] = feld
        zusatz = ""
        if conversion != -1:
            zusatz += "!" + chr(conversion)
        if spec:
            zusatz += ":" + spec
        self.text += "{" + feld + zusatz + "}"

    def joined(self, node: ast.JoinedStr) -> None:
        for wert in node.values:
            if isinstance(wert, ast.Constant):
                self.literal(wert.value)
            elif isinstance(wert, ast.FormattedValue):
                spec = ""
                if wert.format_spec is not None:
                    teile = wert.format_spec.values  # type: ignore[attr-defined]
                    if not all(isinstance(t, ast.Constant) for t in teile):
                        raise NichtUmstellbar("verschachtelte Formatangabe")
                    spec = "".join(t.value for t in teile)  # type: ignore[attr-defined]
                self.ausdruck(wert.value, wert.conversion, spec)
            else:
                raise NichtUmstellbar("unbekannter f-String-Teil")

    def argumente(self) -> str:
        teile = list(self.positionen) + [f"{n}={q}" for n, q in self.namen.items()]
        return ", ".join(teile)


def _py_literal(text: str) -> str:
    ersetzt = (
        text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        .replace("\t", "\\t").replace("\r", "\\r")
    )
    for zeichen in set(ersetzt):
        if ord(zeichen) < 32 or zeichen in ("\u2028", "\u2029", "\x7f", "\xa0", "\u200b", "\ufeff"):
            ersetzt = ersetzt.replace(zeichen, f"\\u{ord(zeichen):04x}")
    return f'"{ersetzt}"'


def _literal_umbrochen(text: str, einzug: int, breite: int = 96) -> str:
    """Python-Literal, bei Bedarf als mehrere nebeneinanderstehende Zeichenketten."""
    if len(_py_literal(text)) + einzug + 4 <= breite:
        return _py_literal(text)
    grenze = max(breite - einzug - 8, 40)
    stuecke: list[str] = []
    aktuell = ""
    # An Zeilenumbrüchen und Leerzeichen teilen, Stücke bis zur Grenze auffüllen
    for teil in re.findall(r"[^ \n]*(?:\n+| +|$)", text):
        if not teil:
            continue
        if aktuell and len(_py_literal(aktuell + teil)) - 2 > grenze:
            stuecke.append(aktuell)
            aktuell = ""
        aktuell += teil
        if aktuell.endswith("\n") and len(aktuell) > grenze // 2:
            stuecke.append(aktuell)
            aktuell = ""
    if aktuell:
        stuecke.append(aktuell)
    if len(stuecke) <= 1:
        return _py_literal(text)
    innen = " " * (einzug + 4)
    return "\n" + "\n".join(innen + _py_literal(s) for s in stuecke) + "\n" + " " * einzug


def _neuer_ausdruck(node: ast.expr, segment: str, einzug: int) -> str:
    if isinstance(node, ast.Constant):
        return f"tr({segment})"
    bauer = Formatbauer()
    if isinstance(node, ast.JoinedStr):
        bauer.joined(node)
    else:
        for teil in _kette(node) or []:
            if isinstance(teil, ast.Constant) and isinstance(teil.value, str):
                bauer.literal(teil.value)
            elif isinstance(teil, ast.JoinedStr):
                bauer.joined(teil)
            else:
                bauer.ausdruck(teil)
    literal = _literal_umbrochen(bauer.text, einzug)
    argumente = bauer.argumente()
    if not argumente:
        # f-String ohne Platzhalter: {{ }} wieder zurück
        return f"tr({_literal_umbrochen(bauer.text.replace('{{', '{').replace('}}', '}'), einzug)})"
    return f"tr({literal}).format({argumente})"


def _gleichwertig(node: ast.expr, neu: str) -> bool:
    """Prüft mit Probewerten, dass alter und neuer Ausdruck denselben Text liefern."""
    if isinstance(node, ast.Constant):
        try:
            return ast.literal_eval("(" + neu[3:-1] + ")") == node.value
        except Exception:  # noqa: BLE001
            return False
    alt_baum = ast.parse(ast.unparse(node), mode="eval")
    neu_baum = ast.parse(neu.strip(), mode="eval")
    namen: dict[str, str] = {}

    def ersetze(baum: ast.AST) -> None:
        # Alle Ausdrücke außerhalb der Literale durch Platzhalternamen ersetzen
        class T(ast.NodeTransformer):
            def visit_FormattedValue(self, n: ast.FormattedValue):  # noqa: N802
                n.value = self._name(n.value)
                return n

            def visit_keyword(self, n: ast.keyword):  # noqa: N802
                n.value = self._name(n.value)
                return n

            def visit_Call(self, n: ast.Call):  # noqa: N802
                if isinstance(n.func, ast.Attribute) and n.func.attr == "format":
                    n.func.value = self.visit(n.func.value)
                    n.args = [self._name(a) for a in n.args]
                    n.keywords = [self.visit(k) for k in n.keywords]
                    return n
                if isinstance(n.func, ast.Name) and n.func.id == "tr":
                    return n
                return self._name(n)

            def visit_BinOp(self, n: ast.BinOp):  # noqa: N802
                if isinstance(n.op, ast.Add):
                    n.left = self._teil(n.left)
                    n.right = self._teil(n.right)
                    return n
                return self._name(n)

            def _teil(self, n: ast.expr):
                if _ist_text(n) or (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add)):
                    return self.visit(n)
                return self._name(n)

            def _name(self, n: ast.expr):
                quelle = ast.unparse(n)
                name = namen.setdefault(quelle, f"_w{len(namen)}")
                return ast.copy_location(ast.Name(id=name, ctx=ast.Load()), n)

        T().visit(baum)
        ast.fix_missing_locations(baum)

    ersetze(alt_baum)
    ersetze(neu_baum)
    for probe in (3.14159, 7, "Wä{r}t"):
        umgebung = {name: probe for name in namen.values()}
        umgebung["tr"] = lambda s: s
        try:
            alt_wert = eval(compile(alt_baum, "<alt>", "eval"), umgebung)  # noqa: S307
        except Exception:  # noqa: BLE001
            continue
        try:
            neu_wert = eval(compile(neu_baum, "<neu>", "eval"), umgebung)  # noqa: S307
        except Exception:  # noqa: BLE001
            return False
        if alt_wert != neu_wert:
            return False
        return True
    # Kein Probewert passt für alle Felder (z. B. :d neben + Text): gemischt versuchen
    return _gleichwertig_gemischt(alt_baum, neu_baum, list(namen.values()))


def _gleichwertig_gemischt(alt_baum: ast.AST, neu_baum: ast.AST, namen: list[str]) -> bool:
    import itertools

    for werte in itertools.product((7, "Wä{r}t", 3.5), repeat=min(len(namen), 6)):
        umgebung = dict(zip(namen, werte))
        for name in namen[6:]:
            umgebung[name] = "x"
        umgebung["tr"] = lambda s: s
        try:
            alt_wert = eval(compile(alt_baum, "<alt>", "eval"), umgebung)  # noqa: S307
        except Exception:  # noqa: BLE001
            continue
        try:
            return alt_wert == eval(compile(neu_baum, "<neu>", "eval"), umgebung)  # noqa: S307
        except Exception:  # noqa: BLE001
            return False
    return False


def _nummern(angabe: str | None) -> set[int]:
    ergebnis: set[int] = set()
    for teil in (angabe or "").replace(" ", "").split(","):
        if not teil:
            continue
        if "-" in teil:
            von, bis = teil.split("-", 1)
            ergebnis.update(range(int(von), int(bis) + 1))
        else:
            ergebnis.add(int(teil))
    return ergebnis


def _lesen(pfad: Path) -> tuple[str, bool]:
    roh = pfad.read_bytes().decode("utf-8")
    crlf = "\r\n" in roh
    return roh.replace("\r\n", "\n"), crlf


def _schreiben(pfad: Path, text: str, crlf: bool) -> None:
    if crlf:
        text = text.replace("\n", "\r\n")
    pfad.write_bytes(text.encode("utf-8"))


def _offsets(quelle: str) -> list[int]:
    """Byte-Offsets der Zeilenanfänge (ast zählt Spalten in UTF-8-Bytes)."""
    offsets, summe = [], 0
    for zeile in quelle.encode("utf-8").split(b"\n"):
        offsets.append(summe)
        summe += len(zeile) + 1
    return offsets


def _import_einfuegen(quelle: str) -> str:
    if re.search(r"^from src\.i18n import .*\btr\b", quelle, re.MULTILINE):
        return quelle
    tree = ast.parse(quelle)
    zeilen = quelle.split("\n")
    letzte = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            letzte = node.end_lineno or node.lineno
        elif isinstance(node, ast.Expr) and _ist_text(node.value) and letzte == 0:
            letzte = node.end_lineno or node.lineno
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            break
    zeilen.insert(letzte, "from src.i18n import tr")
    return "\n".join(zeilen)


def cmd_kandidaten(args: argparse.Namespace) -> int:
    for name in args.dateien:
        pfad = Path(name)
        quelle, _ = _lesen(pfad)
        for fund in funde_in(quelle):
            if args.nur and fund.art != args.nur:
                continue
            text = _literaltext(fund.node).replace("\n", "\\n")
            if len(text) > args.breite:
                text = text[: args.breite] + "…"
            print(f"{fund.nummer}\t{fund.art}\t{fund.node.lineno}\t{fund.grund}\t{text}")
    return 0


def cmd_umstellen(args: argparse.Namespace) -> int:
    pfad = Path(args.datei)
    quelle, crlf = _lesen(pfad)
    auch, nicht = _nummern(args.auch), _nummern(args.nicht)
    funde = [
        f for f in funde_in(quelle)
        if (f.art == "A" and f.nummer not in nicht) or (f.art != "A" and f.nummer in auch)
    ]
    daten = quelle.encode("utf-8")
    offsets = _offsets(quelle)
    ersetzungen: list[tuple[int, int, bytes]] = []
    for fund in funde:
        node = fund.node
        anfang = offsets[node.lineno - 1] + node.col_offset
        ende = offsets[node.end_lineno - 1] + node.end_col_offset
        segment = daten[anfang:ende].decode("utf-8")
        if ersetzungen and anfang < ersetzungen[-1][1]:
            continue  # liegt in einem schon umgestellten Ausdruck
        try:
            gleich = ast.dump(ast.parse("(" + segment + ")", mode="eval").body) == ast.dump(node)
        except SyntaxError:
            gleich = False
        if not gleich:
            print(f"  übersprungen Nr. {fund.nummer} Zeile {node.lineno}: Quelltext nicht eindeutig")
            continue
        zeilenanfang = daten[offsets[node.lineno - 1]:anfang].decode("utf-8")
        einzug = len(zeilenanfang) - len(zeilenanfang.lstrip(" "))
        try:
            neu = _neuer_ausdruck(node, segment, einzug)
        except NichtUmstellbar as fehler:
            print(f"  übersprungen Nr. {fund.nummer} Zeile {node.lineno}: {fehler}")
            continue
        if not _gleichwertig(node, neu):
            print(f"  NICHT GLEICHWERTIG Nr. {fund.nummer} Zeile {node.lineno}: übersprungen")
            continue
        ersetzungen.append((anfang, ende, neu.encode("utf-8")))
    ersetzungen.sort()
    for (a1, e1, _), (a2, _, _) in zip(ersetzungen, ersetzungen[1:]):
        if a2 < e1:
            print(f"Überlappung bei Byte {a2}, Abbruch")
            return 1
    for anfang, ende, neu in reversed(ersetzungen):
        daten = daten[:anfang] + neu + daten[ende:]
    ergebnis = daten.decode("utf-8")
    if ersetzungen:
        ergebnis = _import_einfuegen(ergebnis)
    ast.parse(ergebnis)
    _schreiben(pfad, ergebnis, crlf)
    print(f"{pfad}: {len(ersetzungen)} Texte umgestellt")
    return 0


# ---------------------------------------------------------------------------
# Katalog
# ---------------------------------------------------------------------------

def markierte_texte(wurzel: Path = ROOT / "src") -> dict[tuple[str | None, str], list[str]]:
    """Alle ``tr("...")``-Texte: ``(kontext, text) -> [Dateien]`` in Reihenfolge des Codes."""
    ergebnis: dict[tuple[str | None, str], list[str]] = {}
    for pfad in sorted(wurzel.rglob("*.py")):
        tree = ast.parse(pfad.read_text(encoding="utf-8"))
        rel = pfad.relative_to(wurzel.parent).as_posix()
        aufrufe = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr"
        ]
        aufrufe.sort(key=lambda n: (n.lineno, n.col_offset))
        for node in aufrufe:
            if not node.args or not (
                isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
            ):
                print(f"WARNUNG {rel}:{node.lineno}: tr() ohne Zeichenkettenliteral")
                continue
            kontext = None
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                kontext = node.args[1].value
            for kw in node.keywords:
                if kw.arg == "kontext" and isinstance(kw.value, ast.Constant):
                    kontext = kw.value.value
            dateien = ergebnis.setdefault((kontext, node.args[0].value), [])
            if rel not in dateien:
                dateien.append(rel)
    return ergebnis


def _po_pfad(sprache: str) -> Path:
    return LOCALE_DIR / f"{sprache}.po"


def _schluessel(kontext: str | None, text: str) -> str:
    return f"{kontext}\x04{text}" if kontext else text


def _po_schreiben(sprache: str, uebersetzungen: dict[str, str], kopf: dict[str, str]) -> list:
    texte = markierte_texte()
    namen = {"en": "English"}
    kopf = {
        "Language": sprache,
        "X-Language-Name": namen.get(sprache, sprache),
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
        **kopf,
    }
    zeilen = [
        f"# Übersetzung der Oberfläche von PDF Sortier Meister ({sprache}).",
        "# Erzeugt und geordnet von tools/i18n_werkzeug.py; die msgstr-Zeilen werden",
        "# von Hand gepflegt. msgid ist der deutsche Text aus dem Code.",
        "#",
        'msgid ""',
        'msgstr ""',
    ]
    for name, wert in kopf.items():
        zeilen.append(po_literal(f"{name}: {wert}\n"))
    zeilen.append("")
    # Der Programmname steht immer als erster Eintrag (einzige Stelle für eine Umbenennung)
    from src.i18n import APP_NAME

    reihenfolge = [(None, APP_NAME)] + [k for k in texte if k != (None, APP_NAME)]
    texte.setdefault((None, APP_NAME), ["src/i18n/__init__.py"])
    uebersetzungen.setdefault(APP_NAME, APP_NAME)
    fehlend = []
    for kontext, text in reihenfolge:
        for datei in texte[(kontext, text)]:
            zeilen.append(f"#: {datei}")
        if kontext:
            zeilen.append(f"msgctxt {po_literal(kontext)}")
        zeilen.append(f"msgid {po_literal(text)}")
        msgstr = uebersetzungen.get(_schluessel(kontext, text), "")
        if not msgstr:
            fehlend.append((kontext, text))
        zeilen.append(f"msgstr {po_literal(msgstr)}")
        zeilen.append("")
    _po_pfad(sprache).write_text("\n".join(zeilen), encoding="utf-8", newline="\n")
    return fehlend


def _po_laden(sprache: str) -> tuple[dict[str, str], dict[str, str]]:
    pfad = _po_pfad(sprache)
    if pfad.exists():
        return read_po(pfad)
    return {}, {}


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")


def _unescape(text: str) -> str:
    text = text.replace("␣", " ")  # Leerzeichen am Rand, das Editoren sonst abschneiden
    return re.sub(
        r"\\(.)", lambda m: {"n": "\n", "t": "\t", "\\": "\\"}.get(m.group(1), m.group(0)), text
    )


def _offene(sprache: str) -> list[tuple[str | None, str]]:
    uebersetzungen, _ = _po_laden(sprache)
    return [k for k in markierte_texte() if _schluessel(*k) not in uebersetzungen]


def cmd_offen(args: argparse.Namespace) -> int:
    for nummer, (kontext, text) in enumerate(_offene(args.sprache), 1):
        vor = f"[{kontext}] " if kontext else ""
        print(f"{nummer}\t{vor}{_escape(text)}")
    return 0


PLATZHALTER = re.compile(r"\{[^{}]*\}|%[sdif]|%\([a-z_]+\)[sdif]")
TAGS = re.compile(r"</?[a-zA-Z][^>]*>")


def pruefe_paar(deutsch: str, uebersetzt: str) -> list[str]:
    """Formale Prüfung einer Übersetzung; liefert Beanstandungen."""
    maengel = []
    if sorted(PLATZHALTER.findall(deutsch.replace("{{", "").replace("}}", ""))) != sorted(
        PLATZHALTER.findall(uebersetzt.replace("{{", "").replace("}}", ""))
    ):
        maengel.append("Platzhalter weichen ab")
    if deutsch.count("{{") != uebersetzt.count("{{") or deutsch.count("}}") != uebersetzt.count("}}"):
        maengel.append("geschweifte Klammern weichen ab")
    kuerzel = re.compile(r"&(?![&#]|amp;|nbsp;|lt;|gt;|quot;)\w")
    if bool(kuerzel.search(deutsch)) != bool(kuerzel.search(uebersetzt)):
        maengel.append("Tastenkürzel (&) weicht ab")
    if len(deutsch) - len(deutsch.lstrip()) != len(uebersetzt) - len(uebersetzt.lstrip()) or len(
        deutsch
    ) - len(deutsch.rstrip()) != len(uebersetzt) - len(uebersetzt.rstrip()):
        maengel.append("Leerraum am Rand weicht ab")
    if sorted(t.split()[0].strip("<>/") for t in TAGS.findall(deutsch)) != sorted(
        t.split()[0].strip("<>/") for t in TAGS.findall(uebersetzt)
    ):
        maengel.append("HTML-Tags weichen ab")
    return maengel


def cmd_eintragen(args: argparse.Namespace) -> int:
    if args.stand:
        # Nummern beziehen sich auf eine gespeicherte Ausgabe von "offen"
        offene = []
        for zeile in Path(args.stand).read_text(encoding="utf-8").splitlines():
            _, _, deutsch = zeile.partition("\t")
            treffer = re.match(r"\[([^\]]+)\] (.*)", deutsch, re.DOTALL)
            if treffer:
                offene.append((treffer.group(1), _unescape(treffer.group(2))))
            else:
                offene.append((None, _unescape(deutsch)))
    else:
        offene = _offene(args.sprache)
    uebersetzungen, kopf = _po_laden(args.sprache)
    fehler = 0
    for zeile in Path(args.datei).read_text(encoding="utf-8").splitlines():
        if not zeile.strip():
            continue
        nummer, _, text = zeile.partition("\t")
        if not nummer.strip().isdigit() or int(nummer) < 1 or int(nummer) > len(offene):
            print(f"Unbekannte Nummer: {zeile[:60]}")
            fehler += 1
            continue
        kontext, deutsch = offene[int(nummer) - 1]
        uebersetzt = _unescape(text)
        maengel = pruefe_paar(deutsch, uebersetzt)
        if maengel:
            print(f"{nummer}: {', '.join(maengel)}\n   de: {_escape(deutsch)}\n   en: {text}")
            fehler += 1
            continue
        uebersetzungen[_schluessel(kontext, deutsch)] = uebersetzt
    fehlend = _po_schreiben(args.sprache, uebersetzungen, kopf)
    print(f"{_po_pfad(args.sprache)}: {len(fehlend)} ohne Übersetzung, {fehler} abgelehnt")
    return 1 if fehler else 0


def cmd_abgleich(args: argparse.Namespace) -> int:
    uebersetzungen, kopf = _po_laden(args.sprache)
    fehlend = _po_schreiben(args.sprache, uebersetzungen, kopf)
    for kontext, text in fehlend:
        print(f"fehlt: {_escape(text)[:100]}")
    print(f"{len(fehlend)} Texte ohne Übersetzung")
    return 1 if fehlend else 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="befehl", required=True)

    p = sub.add_parser("kandidaten")
    p.add_argument("dateien", nargs="+")
    p.add_argument("--nur", choices=["A", "B", "a"])
    p.add_argument("--breite", type=int, default=110)
    p.set_defaults(func=cmd_kandidaten)

    p = sub.add_parser("umstellen")
    p.add_argument("datei")
    p.add_argument("--auch")
    p.add_argument("--nicht")
    p.set_defaults(func=cmd_umstellen)

    for name, func in (("offen", cmd_offen), ("abgleich", cmd_abgleich)):
        p = sub.add_parser(name)
        p.add_argument("--sprache", default="en")
        p.set_defaults(func=func)

    p = sub.add_parser("eintragen")
    p.add_argument("datei")
    p.add_argument("--sprache", default="en")
    p.add_argument("--stand", help="gespeicherte Ausgabe von 'offen', auf die sich die Nummern beziehen")
    p.set_defaults(func=cmd_eintragen)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
