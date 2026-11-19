# Question database schema (contract shared by pipeline + site)

Everything lives under `db/`. The site (`site/` + `build.py`) reads ONLY what is described here.

## Sources (read-only, never modify)

- `~/stuff/IB PAST PAPERS - YEAR/` — `Math AA/`, `Physics HL/`, `Economics SL/` subtrees (+ per-year
  `20XX Examination Session/` trees which may contain the same or extra papers)
- `~/stuff/Math AA HL/<YYYY> <May|November> Examination Session/` — Mathematics HL 1995–2018 and
  Mathematics: analysis and approaches HL 2019+ (English files only; skip Spanish/French variants)

## Subjects & syllabuses

| subject   | syllabus id     | covers                                   |
|-----------|-----------------|------------------------------------------|
| math      | `math-hl-legacy`| Mathematics HL, exams up to Nov 2020     |
| math      | `math-aa-hl`    | Math Analysis & Approaches HL, 2021+     |
| physics   | `physics-legacy`| Physics HL, exams up to Nov 2024         |
| physics   | `physics-2023`  | Physics HL new syllabus, May 2025+       |
| economics | `econ-legacy`   | Economics SL, exams up to Nov 2021       |
| economics | `econ-2020`     | Economics SL new syllabus, May 2022+     |

(Exact boundary: whatever the paper itself says; the catalog decides per exam.)

## `db/catalog.json`

Array of exams:

```json
{
  "exam_id": "math-2015-M-P1-TZ1",
  "subject": "math",
  "syllabus": "math-hl-legacy",
  "year": 2015,
  "session": "May",            // "May" | "November"
  "tz": "TZ1",                 // "TZ1" | "TZ2" | "TZ3" | null
  "paper": "1",                // "1" | "2" | "3" | "1A" | "1B" (physics May 2025+ splits P1 into 1A MCQ / 1B data)
  "option": null,              // legacy math P3 option as printed, e.g. "Calculus", "Series and differential
                               // equations", "Discrete mathematics", "Sets relations and groups",
                               // "Statistics and probability"; else null
  "level": "HL",               // "HL" | "SL" | "HLSL"
  "qp_pdf": "/abs/path/to/question paper.pdf",
  "ms_pdf": "/abs/path/to/markscheme.pdf",   // or null if not found
  "notes": "free text: duplicates found, oddities"
}
```

exam_id = `{subject}-{year}-{M|N}-P{paper}[{-option slug}][-{tz}]`, e.g. `physics-2021-N-P2`,
`math-2016-M-P3-calculus`, `economics-2019-M-P1-TZ2`. Lowercase option slug.

## `db/taxonomy.json`

```json
{
  "math":      { "topics": [ { "code": "1", "name": "Number and algebra",
                               "subtopics": [ { "code": "1.1", "name": "..." } ] } ] },
  "physics":   { ... },
  "economics": { ... }
}
```

One unified taxonomy per subject that is applied to ALL years (so old and new papers filter
together). Codes are stable strings.

## `db/exams/<exam_id>/exam.json`

```json
{
  "exam_id": "...", ...all catalog fields...,
  "questions": [
    {
      "id": "math-2015-M-P1-TZ1-q7",   // exam_id + "-q" + num
      "num": "7",                      // top-level question number as printed
      "section": "A",                  // "A" | "B" | null
      "marks": 6,                      // total marks or null (MCQ = 1)
      "qtype": "short",                // "mcq" | "short" | "long" | "essay" | "data"
      "image": "q7.webp",              // tall grayscale image of the whole question (all pages stitched)
      "ms_image": "q7_ms.webp",        // markscheme crop for this question, or null
      "text": "extracted question text",
      "ms_text": "extracted markscheme text or null",
      "mcq_answer": null,              // "A".."D" for MCQ
      "topics": ["1", "5"],            // taxonomy topic codes, primary first, ALL that apply
      "subtopics": ["1.3", "5.6"],     // taxonomy subtopic codes, all that apply
      "answer_status": "ok",           // "ok" | "missing" | "suspect"
      "flags": []                      // e.g. ["crop-uncertain", "text-ocr", "diagram-heavy"]
    }
  ],
  "qp_pages": 12,
  "status": "done",                    // "done" | "partial" | "failed"
  "notes": ""
}
```

Images: WebP, grayscale, ~150 dpi, quality ~80, one file per question and one per markscheme
(multi-page questions are stitched vertically). Strip running headers/footers/page numbers.

## Additions found during segmentation

- `section`: "A"/"B" for sectioned papers; for physics P3 the option letter ("A"–"D" 2016+, "E"–"J"
  2009 syllabus); null for unsectioned papers and for the compulsory physics P3 Section A.
- `num` is exactly as printed ("A1", "G2" on older physics papers, "A1".."D5" on 2006–07 combined math P3).
- Optional per-question `option` (math pre-2006 P2 section B and combined P3).
- Flag vocabulary: `text-ocr`, `crop-uncertain`, `diagram-heavy`, `marks-from-ms`, `downscaled`,
  `mcq-multiple-answers`, `content-removed`, `parts-removed` (whole question removed for copyright in
  the public paper; hide by default), `topic-uncertain`, `crop-bad`, `key-disputed`.
- `status` = "partial" when any answer is not ok, numbering has gaps, a crop is uncertain or marks mismatch.

## Labels (`db/exams/<id>/labels.json`, merged by `pipeline/labels.py`)

Classifier/reviewer output lives in a separate file so re-segmenting never loses it; see the
docstring of `pipeline/labels.py`. Merged fields: `topics`, `subtopics`, `text_clean` (faithful
transcription used for search/copy in place of the raw extracted `text`), optional `qtype`, `marks`,
`answer_status` overrides, `add_flags`, `note` -> `review_note`.

## Segmenter contract (`pipeline/segment.py`)

```
python3 pipeline/segment.py --exam-id <exam_id> [--out db/exams/<exam_id>] [--overrides <file.json>]
```

Looks the exam up in `db/catalog.json`, dispatches to `pipeline/seg_<subject>.py`, writes
`<out>/exam.json` + images. If `--overrides` is omitted and `<out>/overrides.json` exists, it is used.

`overrides.json` (all keys optional; page = 0-based PDF page index, y in PDF points from page top;
crops are full content width, margins/headers still trimmed automatically):

```json
{
  "questions": [
    { "num": "3", "qp": [[2, 410.0, 790.0], [3, 40.0, 300.0]], "ms": [[7, 60.0, 700.0]] }
  ],
  "ms_offsets": {"skip_pages": 3},    // optional hint: markscheme front-matter pages to ignore
  "drop": ["0"],                      // question nums to remove (false positives)
  "mcq_answers": {"12": "C"}         // override MCQ key letters
}
```

A question listed in `questions` uses exactly those regions for qp and/or ms (whichever is
given); all other questions keep automatic boundaries. Re-running is idempotent.

## Hosting constraint

The built site must stay under 20,000 files and 25 MB per file, so: exactly ≤2 images per question,
no per-page files, JSON split per subject.
