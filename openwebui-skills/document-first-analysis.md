---
id: document-first-analysis
name: Document-First Analysis
description: Extract documents efficiently with native text and Markdown first, using OCR only for scanned pages or images.
---

# Document-First Analysis

When reading files:

1. Use existing Markdown or plain text directly.
2. Use a native parser for DOCX, searchable PDF, spreadsheets, presentations, JSON, and source code.
3. Detect whether a PDF page already contains text before applying OCR.
4. Use OCR only for scanned pages, screenshots, or images that need it.
5. Preserve filenames, headings, tables, page references, and source links.
6. Mark uncertain OCR text instead of silently correcting it.
7. Retrieve only the relevant sections for a question rather than injecting a large archive into every prompt.

For Arabic OCR, prefer Arabic and English language models together when the page mixes both scripts. Validate important names, numbers, dates, and legal or medical terms against the original image.
