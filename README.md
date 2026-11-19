# IB past-paper question database

Every question from IB Mathematics HL / Analysis & Approaches HL (1995–2025), Physics HL (2010–2025)
and Economics SL (2010–2025) past papers, cut out of the original PDFs, matched to its markscheme,
classified by topic, and browsable as a static website (no server, no accounts).

- 501 papers, 6,146 questions, 10,363 question/markscheme images
- Every question tagged with all topics/subtopics it examines (one taxonomy per subject applied to
  all years), transcribed to searchable text (LaTeX for maths), and visually checked
- Original papers can be reconstructed in order; repeats across time zones are detected

## Layout

| Path | What |
|---|---|
| `db/SCHEMA.md` | Data contract — read this first |
| `db/catalog.json` | Every exam paper + its source PDFs (built by `pipeline/catalog.py`) |
| `db/taxonomy.json`, `db/CLASSIFY.md` | Topic taxonomy and classification rules |
| `db/exams/<exam_id>/` | `exam.json` (generated), images, `labels.json` (topics/transcriptions/review — hand/agent-made, **irreplaceable**), `overrides.json` (manual crop fixes) |
| `pipeline/segment.py` | Cuts PDFs into questions (`seg_math.py`, `seg_physics.py`, `seg_economics.py`) |
| `pipeline/labels.py`, `pipeline/relabel.py` | Validate/merge labels; safe relabelling helpers |
| `pipeline/show.py` | Compact views of exams, taxonomy, audits |
| `site/` | The website (vanilla JS, KaTeX vendored) |
| `build.py` | Builds `dist/` from `db/` + `site/` |

Source PDFs live outside the repo (`~/stuff/IB PAST PAPERS - YEAR/`, `~/stuff/Math AA HL/`).

## Common tasks

```bash
python3 build.py --force                      # build dist/
cd dist && python3 -m http.server 8000        # preview at http://localhost:8000

python3 pipeline/segment.py --exam-id math-2015-M-P1-TZ1   # re-cut one exam (keeps its labels)
python3 pipeline/segment.py --all --subject physics         # re-cut a subject
python3 pipeline/labels.py --apply-all && python3 pipeline/labels.py --stats
python3 pipeline/relabel.py set <question_id> <subtopic> [...] --note "why"
```

## Deploy (Cloudflare Workers, static assets)

Connected to GitHub: build command `python3 build.py`, deploy command `npx wrangler deploy`
(`wrangler.jsonc` serves `dist/`). Every push to `main` redeploys. Manual deploy:

```bash
python3 build.py --force && npx wrangler deploy
```
