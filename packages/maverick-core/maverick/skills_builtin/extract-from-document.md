---
name: extract-from-document
triggers:
  - pull data from this pdf
  - extract the table
  - ocr this
  - get the fields from this document
tools_needed:
  - read_file
  - extract_document
---
# What this skill does

Performs deterministic field and table extraction from a document (PDF, scan, image, form) with a per-field confidence score and an explicit could-not-read flag for anything illegible. The goal class is "turn a document into structured data you can trust": every extracted value carries provenance (page/region) and a confidence, and low-confidence or missing fields are surfaced rather than hallucinated.

# Steps

1. Read the document with read_file to understand its structure (native text vs scanned image, single table vs multi-page), then call extract_document with the target schema (the named fields and table columns you need).
2. For each field, return value plus source location (page and bounding region) plus confidence. For tables, preserve row/column structure and flag merged or split cells.
3. Mark any field that is illegible, absent, or ambiguous as could_not_read rather than inventing a plausible value. Do not infer a number that is not on the page.
4. Reconcile internal consistency where the document allows it (totals equal the sum of line items, dates are ordered) and flag any failed check for human review instead of silently correcting.

# Notes

The cardinal sin is filling a blank or smudged field with a confident guess; a missing value flagged as such is recoverable, a fabricated one is a landmine. OCR confidence is not document confidence — a crisp scan of a contradictory form is still wrong. Watch for scanned tables where row alignment drifts; verify against a total. This skill extracts and reports; it does not write the values into any system of record. Keep extraction deterministic: re-running on the same document should give the same fields and confidences.
