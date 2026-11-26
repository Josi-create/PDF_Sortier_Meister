# Sorting and naming

## Name suggestion

PDFSM suggests a file name for the selected PDF. It uses the recognised **date** (e.g. 12.03.2026
or "March 2026"), the **category** (invoice, contract, insurance, bank, salary, tax …), the
**sender** and your previous renamings.

Example: `scan_0042.pdf` becomes `2026-03-12_Springfield Utilities_Electricity bill.pdf`.

## Renaming

- `F2` opens the **Rename...** dialog. There you can set your own **file name pattern** with
  placeholders such as `{datum}_{kontakt}_{betreff}` (date, contact, subject), with a live
  preview. The AI fills in the pattern.
- The basic settings for this are under **Settings › File names**.

## Moving

- **One click** on a target folder moves the PDF, renames it and saves the metadata.
- With the **"Move only"** switch the file name stays as it is.
- A PDF can also be copied into **several folders**.

## Metadata inside the PDF

PDFSM writes category, correspondent, amount (net and gross), VAT, IBAN, tax year and a summary
as **XMP metadata into the PDF itself**. This is an ISO standard; the data survives copying and
moving. In addition it goes into the search index.

With AI set up, PDFSM fills in the fields itself; the "Regenerate AI metadata" button asks the AI
again.

## Correspondents

The **"Correspondents"** tab on the left manages senders: name, other spellings (aliases),
category and colour. Clicking a correspondent filters the PDF list.

## Tax report

**Tools › Tax report...** shows yearly totals by category (gross, net, deductible) and exports
them as a CSV file, e.g. for your tax return.

Next: [Stacking, splitting and pages](04-stapeln-trennen.md)
