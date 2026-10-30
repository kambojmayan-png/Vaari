"""Prompt and schema definition for HostedVisionReader (Step 03).

NOTE ON CONFIDENCE: The confidence values returned by the vision model are the model's
own self-reported estimates and are NOT statistically calibrated probabilities.
"""

PROMPT_VERSION = "v2"  # v2 (pilot Part 5): confidence required for every field; strict schema

REGISTER_EXTRACTION_PROMPT = """You are reading a photograph of a handwritten crop-residue machinery booking register from a Custom Hiring Centre in Punjab (Gurmukhi Punjabi and English mixed).
All entries on this page are synthetic test entries.

Extract the rows into ONLY valid JSON matching this exact structure (no markdown fences, no prose):
{
  "rows": [
    {
      "row": 1,
      "fields": {
        "phone": "string or null",
        "name": "string or null",
        "village": "string or null",
        "acres": 4.5,
        "service_type": "super_seeder | happy_seeder | baler | mulcher | raw string",
        "harvest_date": "YYYY-MM-DD or DD/MM or null",
        "note": "string or null"
      },
      "confidence": {
        "phone": 0.95,
        "name": 0.60,
        "village": 0.90,
        "acres": 0.85,
        "service_type": 0.92,
        "harvest_date": 0.80
      }
    }
  ]
}

Strict rules:
1. Copy only what is written on the page. Keep Gurmukhi as Gurmukhi; do not translate names or villages.
2. Do not guess missing values — use null whenever a cell is blank.
3. Do not invent rows, and ignore crossed-out rows or header rows.
4. Every row MUST have a confidence number from 0.0 to 1.0 for EACH of: phone, name, village, acres,
   service_type, harvest_date. A blank cell still needs one: how sure you are that it is blank.
5. Give low confidence (below 0.6) to any cell that is smudged, overwritten, or unclear.
   Note: confidence is your own uncalibrated estimate from 0.0 to 1.0.
6. Use only the field names shown. "row" is the row's number on the page, starting at 1.
"""

# Gemini structured output: the same schema, enforced by the API where supported.
_CONF = {"type": "NUMBER"}
_TEXT = {"type": "STRING", "nullable": True}
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "rows": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "row": {"type": "INTEGER"},
                    "fields": {
                        "type": "OBJECT",
                        "properties": {
                            "phone": _TEXT,
                            "name": _TEXT,
                            "village": _TEXT,
                            "acres": _TEXT,
                            "service_type": _TEXT,
                            "harvest_date": _TEXT,
                            "note": _TEXT,
                        },
                    },
                    "confidence": {
                        "type": "OBJECT",
                        "properties": {
                            k: _CONF
                            for k in ("phone", "name", "village", "acres", "service_type", "harvest_date")
                        },
                        "required": ["phone", "name", "village", "acres", "service_type", "harvest_date"],
                    },
                },
                "required": ["row", "fields", "confidence"],
            },
        }
    },
    "required": ["rows"],
}

RETRY_JSON_MESSAGE = (
    "Return ONLY valid JSON matching the required schema with top-level key 'rows'. "
    "Every row needs a confidence number from 0 to 1 for phone, name, village, acres, service_type "
    "and harvest_date. Do not include markdown formatting or any explanation."
)
