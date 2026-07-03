from datetime import datetime


def validate_extraction(data: dict) -> tuple[float, list[str]]:
    """Combina la confianza reportada por el modelo con chequeos de reglas de negocio.

    Devuelve (confianza_final, notas). La confianza final nunca supera la del
    modelo: las reglas solo pueden penalizarla, nunca inflarla.
    """
    notes: list[str] = []
    model_confidence = data.get("confidence")
    if not isinstance(model_confidence, (int, float)):
        model_confidence = 0.0
        notes.append("El modelo no reporto una confianza numerica valida.")
    confidence = float(model_confidence)

    total = data.get("total")
    subtotal = data.get("subtotal")
    tax = data.get("tax")
    items = data.get("items") or []

    if total is None:
        confidence *= 0.5
        notes.append("No se pudo extraer el monto total.")

    if subtotal is not None and tax is not None and total is not None:
        expected_total = round(float(subtotal) + float(tax), 2)
        if abs(expected_total - float(total)) > max(0.02, 0.01 * float(total)):
            confidence *= 0.6
            notes.append(
                f"Inconsistencia: subtotal+tax={expected_total} pero total={total}."
            )

    if items and total is not None:
        try:
            items_sum = round(sum(float(i.get("amount", 0)) for i in items), 2)
            if abs(items_sum - float(total)) > max(0.05, 0.02 * float(total)) and not (subtotal and tax):
                confidence *= 0.8
                notes.append(f"La suma de items ({items_sum}) no coincide con el total ({total}).")
        except (TypeError, ValueError):
            confidence *= 0.8
            notes.append("Items con montos no numericos.")

    doc_date = data.get("date")
    if doc_date:
        try:
            parsed = datetime.strptime(doc_date, "%Y-%m-%d")
            if parsed.year < 2000 or parsed > datetime.now():
                confidence *= 0.7
                notes.append(f"Fecha con validez cuestionable: {doc_date}.")
        except ValueError:
            confidence *= 0.6
            notes.append(f"Fecha en formato no reconocido: {doc_date}.")
    else:
        confidence *= 0.85
        notes.append("No se pudo extraer la fecha.")

    if not data.get("vendor"):
        confidence *= 0.85
        notes.append("No se pudo extraer el proveedor.")

    model_notes = data.get("notes")
    if model_notes:
        notes.append(f"Modelo: {model_notes}")

    return round(min(confidence, 1.0), 4), notes


def decide_status(confidence: float, threshold: float) -> str:
    if confidence >= threshold:
        return "approved"
    return "flagged"
