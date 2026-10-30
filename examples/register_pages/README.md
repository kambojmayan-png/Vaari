# Register Reader Evaluation Guide

> **Pilot v0.2:** the main evaluation set is now `synth_01` … `synth_06`, drawn by `scripts/make_synthetic_register_pages.py` (fixed seed, invented data). Only their `.expected.json` files are committed. The pass bar and the results are in [`docs/READER_EVAL.md`](../../docs/READER_EVAL.md).

This directory contains evaluation fixtures and benchmark results for the Vaari register intake OCR/vision reader (`python tasks.py reader-eval`).

---

## ⚠️ Privacy & Security: Non-Negotiable Rule

> **CRITICAL: Real or personal register pages must NEVER be committed to git.**
>
> Registers contain personal identifiable information (PII) including farmer names, phone numbers, acreage, and village locations. All sample files in this repository must use purely synthetic, fictional farmer records.
>
> `.gitignore` explicitly blocks all image files in this folder:
> ```gitignore
> examples/register_pages/*.jpg
> examples/register_pages/*.jpeg
> examples/register_pages/*.png
> ```
> Never force-add image files to version control.

---

## How to Add a Hand-Written Synthetic Page

To add a new synthetic benchmark evaluation case:

1. **Create the synthetic page image**:
   - Draw or write out a synthetic register page using **fictional names and simulated phone numbers** (e.g., matching the sample formats in `page1.expected.json`).
   - Save the image in this directory as `pageN.jpg` or `pageN.png` (e.g., `page2.jpg`).
   - Because of `.gitignore`, this image will remain local on your machine.

2. **Add the matching ground-truth expectation file**:
   - Create `pageN.expected.json` (e.g., `page2.expected.json`) side-by-side with your image.
   - Follow the established JSON schema:
     ```json
     {
       "rows": [
         {
           "row": 1,
           "fields": {
             "phone": "9000000101",
             "name": "Gurpreet Singh",
             "village": "Pind Kalan",
             "acres": 4.5,
             "service_type": "super_seeder",
             "harvest_date": "2026-10-22"
           }
         },
         {
           "row": 2,
           "fields": {
             "phone": "9000000102",
             "name": "Manpreet Kaur",
             "village": "Bhucho Khurd",
             "acres": 3.0,
             "service_type": "super_seeder",
             "harvest_date": "2026-10-23"
           }
         }
       ]
     }
     ```
   - Standard field names:
     - `phone`: 10-digit phone string.
     - `name`: Farmer name string (or `null` if blank).
     - `village`: Village name string.
     - `acres`: Floating-point acreage number.
     - `service_type`: Normalized service identifier (`super_seeder`, `happy_seeder`, `baler`, `zero_till_drill`, etc.).
     - `harvest_date`: ISO format date string (`YYYY-MM-DD`) or `null` if omitted.

---

## Running Reader Evaluations

Evaluation runs compare the output of the active reader against the corresponding `*.expected.json` files and write a count-based report into `docs/READER_EVAL.md`.

### 1. Running with the Mock Reader (Offline Default)
By default, Vaari uses the offline deterministic mock reader. To run evaluation:
```bash
python tasks.py reader-eval
```
- If an image file is absent locally, a tiny synthetic test JPEG is generated automatically so evaluation can run in CI and headless environments.
- Results are printed to the console and written into `docs/READER_EVAL.md` (the section for that reader).

### 2. Running with the Hosted Vision Reader
To evaluate a real hosted Multimodal LLM (Gemini or Anthropic Claude) on local synthetic images:
1. In `.env`, set:
   ```env
   VAARI_READER=hosted
   VAARI_ALLOW_HOSTED_READER=true
   VAARI_VISION_PROVIDER=gemini        # or anthropic
   VAARI_VISION_MODEL=gemini-2.5-flash # optional model override
   GEMINI_API_KEY=your_gemini_api_key  # or ANTHROPIC_API_KEY
   ```
2. Run the evaluation command:
   ```bash
   python tasks.py reader-eval
   ```
3. Inspect `docs/READER_EVAL.md` to review the error counts and execution time.

---

## Reporting Standard: Counts Only
Following Vaari's evaluation guidelines:
- Evaluation results report raw counts (e.g., `4 usable of 6 rows`), never misleading percentages on small sample sets.
- Model-reported confidence values are logged but never treated as calibrated certainty.
