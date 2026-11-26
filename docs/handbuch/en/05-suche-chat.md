# Search, mails and chat

## Turning on document search

Full-text search is off at first. Turn it on in the setup wizard or under **Settings › Search**.
There you choose the folders and drives to be searched. **Tools › Add folder to search index...**
adds further folders.

Searched are:

- PDFs, scanned ones too: text recognition reads all pages in the background. Each page is
  recognised only once, even if the file is later moved or renamed.
- Word, Excel and OpenDocument (`doc`, `docx`, `xls`, `xlsx`, `odt`) and Markdown.
- **Mails:** Thunderbird, on the Mac also Apple Mail, plus saved `.eml` and `.msg` files (e.g.
  from Outlook).

The index is refreshed **once a day in the background**, as soon as the computer is idle. If the
computer was off at the scheduled time, PDFSM catches up later when idle. "Index now" reads new
files immediately.

## The "Search" tab

`Ctrl+Shift+F` opens the **"Search"** tab in the middle. Results show the match highlighted and
with its page; the preview jumps to the matching page. You can filter by type, folder, period and
the PDFSM metadata (tax year, category, correspondent, amount). The "Sort by" choice orders by
relevance, date or the date in the file name.

Search syntax:

| Input | finds |
|---|---|
| `invoice utilities` | all words |
| `"exact phrase"` | exactly this phrase |
| `invoice*` | words starting like this |
| `electricity OR gas` | either word |
| `invoice NOT reminder` | the first without the second |

The German operators `ODER` and `NICHT` work as well.

Umlauts do not matter.

`Ctrl+F` (**View › Document search...**) searches the metadata of sorted PDFs.

## Chat about your own documents

With AI set up, there is a **"Chat"** tab on the left. Ask in plain words, e.g. "How much did I
pay for electricity in 2025?". The chat searches the same index, cites with page numbers, and the
sources are clickable.

- The selected PDF is the reference: contract, meter and customer numbers from it bring in linked
  documents (statement, contract, mails).
- If an answer points to a target folder, "Move to …" moves the PDF there in one click.
- Models with tool calls search and read the collection themselves and show their steps.
- The chat can use a different model than sorting.

## Browser interface

Optionally the same search is available in the browser at `http://localhost:18425`. It can only
be reached from this computer and can start at login.

## AI assistants (MCP)

Programs such as Claude Code, Claude Desktop or Hermes Agent can search the index directly. Set it
up under **Settings › Search › AI assistants (MCP)**: for each assistant it shows whether it is
installed and set up, with a button to set it up. Restart the assistant afterwards. All tools are
read-only; none of them moves or changes anything.

Next: [AI providers](06-ki.md)
