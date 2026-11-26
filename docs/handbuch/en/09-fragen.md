# Frequently asked questions and problems

## Windows warns during installation

The program is not signed yet. In the blue window "Windows protected your PC", click "More info"
and then "Run anyway".

## A scan has no text

Scanned PDFs often contain only an image. PDFSM recognises the text itself (OCR). When you click a
scan, the first five pages are read immediately, the rest in the background by the document
search.

## The first analysis with Ollama takes long

On the first call after start, Ollama loads the model into memory. This takes one to two minutes,
afterwards it is faster. See [AI providers](06-ki.md).

## The model is missing or Ollama is not running

Double-clicking the status bar opens the "Background analysis" window. It says what is missing
and offers a button to fix it.

## Moved or renamed something by mistake

`Ctrl+Z` undoes it. Deleted files are in the Recycle Bin.

## PaperPort files (.max)

PDF Sortmeister does not show the old PaperPort files with the extension `.max`. If you still
have some, convert them to PDF in PaperPort first.

Support for `.max` is not being built proactively, because probably hardly anyone still has such
files. If you need it, open an issue on GitHub: on request (and for a coffee) the developer will
gladly add it.

## Where is my data?

Configuration, learning history, search index and logs are stored on Windows in
`%APPDATA%\PDF_Sortier_Meister`, on macOS in
`~/Library/Application Support/PDF_Sortier_Meister`. They are deliberately kept when you
uninstall; to remove everything, delete this folder afterwards.

## Reporting a problem

Please report problems and wishes as an issue on GitHub:
<https://github.com/Josi-create/PDF_Sortier_Meister/issues>

The log file `logs\pdf_sortier_meister.log` in the data folder helps a lot. It contains file
names, but no document contents and no API keys.

## Support

PDF Sortmeister is free software (GPL-3.0). **Help › Support the project ...** shows how you can
support the work with a coffee. Nothing gets unlocked by it.
