# Getting started

PDF Sortmeister (PDFSM for short) sorts scanned PDFs into your own folders, gives them
meaningful names and finds them again later. Everything runs on your computer; the files remain
ordinary PDFs in ordinary folders (OneDrive included).

## Installation

- **Windows:** Download `PDF_Sortier_Meister_Setup.exe` from the release page on GitHub and run
  it. Windows shows a warning on first start ("Windows protected your PC") because the program
  is not signed yet: click "More info", then "Run anyway". If you prefer not to install
  anything, use the portable ZIP.
- **macOS:** Download the matching DMG (Apple Silicon or Intel), open it and drag
  "PDF Sortier Meister" to "Applications".
- Text recognition (OCR, Tesseract) is included in both versions.
- **Update:** Simply install the new version over the old one. Settings and learning data are
  kept. **Help › Check for updates...** tells you whether a newer version exists.

## The setup wizard

On first start, a wizard guides you through the setup:

1. **Scan folder:** the folder where new scans arrive.
2. **Target folders:** the folders you sort into (e.g. `Taxes 2026`, `Insurance`).
3. **AI provider (optional):** The wizard checks the graphics card and recommends a local model
   or a cloud provider. Sorting works without AI, too.
4. **Document search (optional):** folders and drives to be searched.

You can run the wizard again at any time via **Tools › Setup wizard...**.

## The main window

The window has three columns:

- **Left:** the files of the scan folder as tiles. Above them the tabs **"PDFs"**, **"Chat"**
  and **"Correspondents"**.
- **Middle:** the tabs **"Preview"** (the selected PDF with suggestions for name and metadata)
  and **"Search"** (full-text search).
- **Right:** the target folders. Suggested folders are highlighted in green.

**Help › Getting started** shows the short guide to this workflow again. **Help › Manual**
(`F1`) opens this manual.

## The workflow in three steps

1. Click a PDF on the left. The middle shows the preview and suggests a file name.
2. Adjust the name if needed.
3. Click the target folder on the right. The PDF is moved, renamed and its metadata saved, all in
   one step. `Ctrl+Z` undoes it.

Tip for beginners: practise on a copy of a scan folder first. The program really moves and
renames files.

Next: [Scan folder and target folders](02-ordner.md)
