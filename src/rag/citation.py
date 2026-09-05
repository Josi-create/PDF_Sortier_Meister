"""
Citation-Parser fuer das RAG-Chat-Feature (Phase 19 / M3/M1-Bridge).

Parst ``[N]``-Inline-Marker und ``[N] datei.pdf``-Footer-Zeilen aus
der LLM-Antwort, validiert sie gegen die retrieved Docs (Whitelist)
und liefert:

* ``cleaned_answer``: Antworttext mit ggf. entfernten invaliden Markern.
* ``valid_citations``: nur valide ``[N]``-Verweise mit file_path.
* ``dropped_invalid``: invalide Marker, die stillschweigend entfernt wurden.

Implementiert in M1, weil die ``RAGController.ask``-Pipeline den Parser
bereits aufrufen soll (M3 wird das ganze noch verfeinern: Ranking,
Footer-Rekonstruktion, Whitelist-Heuristiken).

GPL-3.0-or-later - Copyright (c) 2026
"""

import re
from dataclasses import dataclass, field


@dataclass
class Citation:
    """Eine einzelne Citation.

    Attributes:
        index: Der 1-basierte Index aus ``[N]``.
        filename: Zugehoeriger Dateiname (kann None sein, wenn der
            Marker ohne Footer-Zeile gefunden wurde und der Index
            nicht in den retrieved docs liegt).
        file_path: Absoluter Dateipfad, sofern ermittelbar.
        pdf_id: Stabile 32-stellige Hex-UUID aus der ``pdfs``-Master-
            Tabelle (Phase 3, Issue #25). Default leerer String, damit
            alte Aufrufer (ohne DB-Lookup) nicht brechen.
        valid: ``True`` wenn der Index zu einem retrieved Doc passt.
    """
    index: int
    filename: str = ""
    file_path: str = ""
    pdf_id: str = ""
    valid: bool = False


class CitationParser:
    """
    Parst ``[N]``-Citation-Marker aus einer LLM-Antwort.

    Zwei Patterns:
    * ``INLINE_PATTERN``: Inline-Marker wie ``...Aussage [1]...``.
    * ``FOOTER_PATTERN``: ``[1] datei.pdf`` in der Quellenliste.

    ``parse()`` liefert ein 3-Tupel ``(cleaned_answer, valid, dropped)``.
    """

    INLINE_PATTERN = re.compile(r"\[(\d+)\]")
    # Footer: '[1] datei.pdf' am Zeilenanfang (ggf. mit Whitespace).
    FOOTER_PATTERN = re.compile(
        r"(?:^|\n)\s*\[(\d+)\]\s+(\S+\.pdf)",
        re.MULTILINE,
    )

    def parse(
        self,
        raw_answer: str,
        retrieved_docs: list,
    ) -> tuple[str, list[Citation], list[Citation]]:
        """Parst die Antwort.

        Args:
            raw_answer: Roher LLM-Output.
            retrieved_docs: Liste von Dicts oder
                :class:`~src.rag.retrieval.RetrievedDoc`-Objekten mit
                ``index`` (oder ``"index"``) und ``filename``/``file_path``.

        Returns:
            Tupel ``(cleaned_answer, valid_citations, dropped_invalid)``.
            ``cleaned_answer`` enthaelt keine invaliden ``[N]``-Marker mehr.
        """
        if not raw_answer:
            return "", [], []
        # Defensiv: ``None`` wird als leere Liste behandelt, damit Caller
        # nicht aus Versehen einen TypeError ausloesen.
        if retrieved_docs is None:
            retrieved_docs = []

        # Whitelist der gueltigen Indizes + filename/file_path.
        whitelist: dict[int, dict] = {}
        for doc in retrieved_docs:
            if isinstance(doc, dict):
                idx = doc.get("index")
                fn = doc.get("filename", "")
                fp = doc.get("file_path", "")
                pid = doc.get("pdf_id", "")
            else:
                # RetrievedDoc-Instanz
                idx = getattr(doc, "index", None)
                fn = getattr(doc, "filename", "")
                fp = getattr(doc, "file_path", "")
                pid = getattr(doc, "pdf_id", "")
            if idx is None:
                continue
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                continue
            whitelist[idx] = {"filename": fn, "file_path": fp, "pdf_id": pid}

        # 1) Footer-Zeilen einsammeln (fuer zusaetzliche Whitelist-Updates).
        for m in self.FOOTER_PATTERN.finditer(raw_answer):
            try:
                idx = int(m.group(1))
            except (TypeError, ValueError):
                continue
            fn = m.group(2)
            # Wenn der Footer einen Dateinamen nennt, der nicht in der
            # Whitelist ist, ignorieren wir ihn (Whitelist wins).
            if idx in whitelist:
                # ggf. fehlenden Filename/Pfad aus dem Footer uebernehmen
                if not whitelist[idx].get("filename"):
                    whitelist[idx]["filename"] = fn

        # 2) Inline-Marker extrahieren.
        inline_indices: set[int] = set()
        for m in self.INLINE_PATTERN.finditer(raw_answer):
            try:
                inline_indices.add(int(m.group(1)))
            except (TypeError, ValueError):
                continue

        # 3) Valid vs. dropped klassifizieren.
        valid: list[Citation] = []
        dropped: list[Citation] = []

        # Footer-Citations (die in der Quellenliste auftauchen).
        footer_indices: set[int] = set()
        for m in self.FOOTER_PATTERN.finditer(raw_answer):
            try:
                footer_indices.add(int(m.group(1))
)
            except (TypeError, ValueError):
                continue

        all_indices = inline_indices | footer_indices
        for idx in sorted(all_indices):
            entry = whitelist.get(idx)
            if entry:
                valid.append(Citation(
                    index=idx,
                    filename=entry.get("filename", ""),
                    file_path=entry.get("file_path", ""),
                    # Phase 3 (Issue #25): pdf_id aus der Whitelist
                    # uebernehmen (default "", wenn nicht vorhanden).
                    pdf_id=entry.get("pdf_id", ""),
                    valid=True,
                ))
            else:
                dropped.append(Citation(
                    index=idx,
                    filename="",
                    file_path="",
                    pdf_id="",
                    valid=False,
                ))

        # 4) cleaned_answer: ungueltige Inline-Marker entfernen.
        def _filter_match(m: re.Match) -> str:
            try:
                idx = int(m.group(1))
            except (TypeError, ValueError):
                return ""
            return m.group(0) if idx in whitelist else ""

        cleaned = self.INLINE_PATTERN.sub(_filter_match, raw_answer)

        # Doppelte aufeinanderfolgende Leerzeichen/Newlines vermeiden.
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        return cleaned, valid, dropped
