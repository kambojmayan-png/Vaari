# Future: a custom register reader

**Status: planned, not built. No training data is collected or stored today.**

The Gemini reader is for demonstrations on synthetic pages only, because it sends register photos to a third party. The long-term plan is a reader of Vaari's own, run on infrastructure the hiring centre (or the state) controls, so a real register page never leaves that boundary. This page sets out what that reader must do, how it would be judged, and how training data could be gathered with consent, later.

## 1. The interface it must meet

The app already talks to it. `VAARI_READER=custom` makes `app/intake/custom.py` call `VAARI_CUSTOM_READER_URL`. Nothing else in Vaari changes when a real model is plugged in.

**Request.** `POST <VAARI_CUSTOM_READER_URL>` with `Authorization: Bearer <VAARI_CUSTOM_READER_TOKEN>` (if set) and JSON:

```json
{
  "image_base64": "<JPEG, already cleaned and preprocessed by Vaari>",
  "media_type": "image/jpeg",
  "prompt_version": "v2",
  "fields": ["phone", "name", "village", "acres", "service_type", "harvest_date"]
}
```

The image has no EXIF or GPS, is upright, 1000–2000 px on the long side, greyscale and contrast-stretched (`app/intake/preprocess.py`).

**Response.** HTTP 200 with the same strict JSON the hosted reader must return (`app/intake/draft_json.parse_rows`):

```json
{
  "model": "vaari-reader-0.1",
  "rows": [
    {
      "row": 1,
      "fields": {"phone": "੯੮੭੬੫ ੪੩੨੧੦", "name": "…", "village": "…", "acres": "3.5 ਏਕੜ",
                 "service_type": "ਸੁਪਰ ਸੀਡਰ", "harvest_date": "18/10", "note": null},
      "confidence": {"phone": 0.97, "name": 0.62, "village": 0.91, "acres": 0.88,
                     "service_type": 0.95, "harvest_date": 0.80}
    }
  ]
}
```

Rules:

- **Return what is written, not a guess.** Gurmukhi digits and Punjabi words may be returned as written: Vaari's normaliser (`app/intake/normalize.py`) turns them into plain values. A blank cell is `null`.
- **A confidence from 0 to 1 for every one of the six fields on every row**, blank cells included. Anything else is refused.
- **Never invent a row.** Skip header and crossed-out rows. `row` is the line number on the page, from 1.
- **Answer within `VAARI_READER_TIMEOUT_S`** (20 s). A slow or failed answer makes the intake screen fall back to typing beside the photo.
- **Keep nothing.** The service must not store the image or its answer beyond the request. Logs must not hold image bytes or field values.

Whatever it returns goes through the same validation as every other reader, and **nothing it returns becomes a request until a person has checked and confirmed the row**.

## 2. How it would be judged

Use the same tool and bar as the Gemini demo: `python tasks.py reader-eval` with `VAARI_READER=custom`, and the pass bar in `docs/READER_EVAL.md`, which was fixed before any run. The most important line is **zero silent phone or acres errors**: a wrong value the reader is sure about.

The printed synthetic set (`synth_01` … `synth_06`) is only a smoke test. Before a custom model is trusted, it needs:

| Set | Size (at least) | Made how | Used for |
| --- | --- | --- | --- |
| Handwritten synthetic | 30 pages, about 300 rows | Staff write invented entries on real register paper with real pens; photographed on centre phones in normal light | Development and tuning |
| Held-out handwritten synthetic | 10 pages, written by people not in the first set | As above, kept apart and never used for training | The pass/fail decision |
| Consented real pages (later, section 3) | Only after consent and review | Real registers with the farmers' and centre's agreement | Checking the model holds up on real writing |

Each page needs a `.expected.json` written by two people independently and reconciled. Scores are reported as *k of N* per field, per page. The held-out set is run once per candidate model, not tuned against.

## 3. Collecting operator corrections as training data, with consent (later)

The most valuable training signal is what operators change on the confirmation screen: the reader said "੯੮੭੬੫ ੪੩੨੧", the operator typed "9876543210". Vaari already records, for audit, which fields an operator edited (`register_draft.edited`, `edited_fields_json`) and keeps register images for 7 days before `purge-images` deletes them. **None of that is used for training, exported, or kept longer for that purpose today, and this plan must not start until every step below is in place.**

1. **Legal and ethical review first.** Collecting register images (names, phone numbers, land) for model training is a new purpose. It needs a lawful basis under India's Digital Personal Data Protection Act, 2023, sign-off from the department that runs the centres, and a written data protection assessment.
2. **Consent per farmer, separate and optional.** A new consent, `consent_training`, recorded per farmer with date and wording version, separate from the service and evidence consents. Saying no changes nothing about the service. It can be withdrawn at any time, and withdrawal deletes that farmer's training records.
3. **Consent per centre** to use its register pages at all.
4. **Collect the minimum.** Store a cropped image of the row, not the page. Redact or never keep cells the model does not need, and keep only the corrected text and the reader's original output. Never the farmer's other records.
5. **Separate store.** Training records live outside the operational database, encrypted, access-logged, inside the same controlled boundary as the custom reader. Never sent to a third-party model or service.
6. **Retention limit.** For example, deleted after the model version that used them is retired or after 2 years, whichever is sooner. A command to delete everything for one farmer or one centre.
7. **Review before use.** A second person checks a sample of corrections, because operators make mistakes too. Corrections made under time pressure are labelled as such.
8. **Visible on screen.** The intake screen says when a confirmed row will be kept for training (only with consent), the same way it now says where a photo goes.

## 4. What is deliberately not done now

- No `consent_training` field, no training store, no export command, and no longer retention of images. (`register_draft` keeps operational edit records for audit, as in v0.1.)
- No custom model, and no model files or weights in the repository.
- The custom reader client exists only so a model can be plugged in later without changing the app, and so the contract above is tested (`tests/unit/test_reader_interface.py`).
