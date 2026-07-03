import base64
import json
import os

import anthropic

MODEL = "claude-sonnet-4-5"

EXTRACTION_PROMPT = """Eres un sistema de extraccion de datos de facturas y recibos.
Analiza la imagen adjunta y devuelve UNICAMENTE un JSON valido (sin texto adicional, sin markdown)
con esta forma exacta:

{
  "vendor": "nombre del proveedor o null si no es legible",
  "date": "YYYY-MM-DD o null",
  "subtotal": numero o null,
  "tax": numero o null,
  "total": numero o null,
  "items": [{"description": "...", "quantity": numero, "unit_price": numero, "amount": numero}],
  "confidence": numero entre 0 y 1 que refleje que tan seguro estas de la extraccion,
  "notes": "cualquier ambiguedad o problema que detectes al leer el documento"
}

Si el documento no es una factura/recibo o es ilegible, pon confidence bajo (menor a 0.3) y explica por que en notes.
"""


class ExtractionError(Exception):
    pass


def _media_type(filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1]
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }.get(ext, "image/jpeg")


def extract_document(image_bytes: bytes, filename: str) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ExtractionError("ANTHROPIC_API_KEY no esta configurada en el entorno.")

    client = anthropic.Anthropic(api_key=api_key)
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": _media_type(filename),
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": EXTRACTION_PROMPT},
                    ],
                }
            ],
        )
    except anthropic.APIError as exc:
        raise ExtractionError(f"Error llamando a la API de Claude: {exc}") from exc

    raw_text = "".join(block.text for block in response.content if block.type == "text").strip()

    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"La respuesta del modelo no fue JSON valido: {raw_text[:300]}") from exc

    return data
