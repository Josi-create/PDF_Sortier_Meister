# Settings

**Tools › Settings...** opens the settings. They have five tabs.

## AI assistant (LLM)

Provider, model and API key, consent for cloud providers and the length of the text excerpt. The
chat can have a model of its own. More in the chapter [AI providers](06-ki.md).

## Personal data

Details about you (e.g. your name), so that PDFSM can tell who is the sender and who the
recipient of a letter.

## File names

How suggested file names are built, e.g. the pattern with placeholders such as
`{datum}_{kontakt}_{betreff}`.

## General

Among others:

- **Sprache / Language:** German or English.
- **Display** of the interface.
- **Scanning:** scanning program (with "Browse..." and "Suggestions"), the folder "New scans are
  saved in:" and whether "Scan now" always switches to this folder automatically.
- **Windows Explorer integration:** the PDF Sortmeister entry in Explorer's right-click menu.
- **Open PDF** (double-click on a thumbnail), **Updates**, **Backup reminder**.

## Search

Document search: **Folders and drives**, **Mails**, **Text recognition (OCR)**, **Background
indexing** (time of the daily run), **Browser interface**, **Improve scanned PDFs** (text layer,
rotation, skew) and **AI assistants (MCP)** with the switch "Allow SQL queries on the search
database".

## Backing up data

The **Tools** menu also offers:

- **Back up data (ZIP)...**: save settings and learning data to a ZIP file.
- **Restore data from backup...**: load such a ZIP file at the next start.
- **Check backup status**.

The data is stored on Windows in `%APPDATA%\PDF_Sortier_Meister`, on macOS in
`~/Library/Application Support/PDF_Sortier_Meister`.

Next: [Keyboard shortcuts](08-tastenkuerzel.md)
