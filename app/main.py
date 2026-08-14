import hashlib
import json
import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import AuditEntry, Document, get_session, init_db
from app.extraction import ExtractionError, extract_document
from app.validation import decide_status, validate_extraction

APP_DIR = os.path.dirname(__file__)
AUTO_APPROVE_THRESHOLD = float(os.getenv("AUTO_APPROVE_THRESHOLD", "0.85"))

app = FastAPI(title="Document Automation Pipeline")
templates = Jinja2Templates(directory=os.path.join(APP_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")

init_db()


def log(session, document_id: int, action: str, detail: str = ""):
    session.add(AuditEntry(document_id=document_id, action=action, detail=detail))


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    session = get_session()
    try:
        docs = session.query(Document).order_by(Document.created_at.desc()).all()
        stats = {
            "total": len(docs),
            "approved": sum(1 for d in docs if d.status == "approved"),
            "flagged": sum(1 for d in docs if d.status == "flagged"),
            "rolled_back": sum(1 for d in docs if d.status == "rolled_back"),
        }
        return templates.TemplateResponse(
            "index.html", {"request": request, "docs": docs, "stats": stats, "threshold": AUTO_APPROVE_THRESHOLD}
        )
    finally:
        session.close()


@app.get("/upload", response_class=HTMLResponse)
def upload_form(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Archivo vacio.")

    file_hash = hashlib.sha256(content).hexdigest()

    session = get_session()
    try:
        existing = session.query(Document).filter_by(file_hash=file_hash).first()
        if existing:
            # Idempotencia: no reprocesar el mismo documento dos veces.
            return RedirectResponse(url=f"/documents/{existing.id}", status_code=303)

        doc = Document(filename=file.filename, file_hash=file_hash, status="processing")
        session.add(doc)
        session.commit()
        session.refresh(doc)
        log(session, doc.id, "created", f"Archivo recibido: {file.filename}")
        session.commit()

        try:
            extracted = extract_document(content, file.filename)
            log(session, doc.id, "extracted", json.dumps(extracted, ensure_ascii=False))
        except ExtractionError as exc:
            doc.status = "flagged"
            doc.validation_notes = str(exc)
            log(session, doc.id, "flagged", f"Fallo de extraccion: {exc}")
            session.commit()
            return RedirectResponse(url=f"/documents/{doc.id}", status_code=303)

        confidence, notes = validate_extraction(extracted)
        status = decide_status(confidence, AUTO_APPROVE_THRESHOLD)

        doc.vendor = extracted.get("vendor")
        doc.doc_date = extracted.get("date")
        doc.total = extracted.get("total")
        doc.subtotal = extracted.get("subtotal")
        doc.tax = extracted.get("tax")
        doc.items_json = json.dumps(extracted.get("items") or [], ensure_ascii=False)
        doc.confidence = confidence
        doc.validation_notes = "; ".join(notes)
        doc.status = status

        action = "auto_approved" if status == "approved" else "flagged"
        log(session, doc.id, action, f"confidence={confidence} umbral={AUTO_APPROVE_THRESHOLD}")
        session.commit()

        return RedirectResponse(url=f"/documents/{doc.id}", status_code=303)
    finally:
        session.close()


@app.get("/documents/{doc_id}", response_class=HTMLResponse)
def document_detail(request: Request, doc_id: int):
    session = get_session()
    try:
        doc = session.query(Document).filter_by(id=doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Documento no encontrado.")
        items = json.loads(doc.items_json) if doc.items_json else []
        audit = session.query(AuditEntry).filter_by(document_id=doc_id).order_by(AuditEntry.created_at).all()
        return templates.TemplateResponse(
            "detail.html", {"request": request, "doc": doc, "items": items, "audit": audit}
        )
    finally:
        session.close()


@app.post("/documents/{doc_id}/rollback")
def rollback_document(doc_id: int):
    session = get_session()
    try:
        doc = session.query(Document).filter_by(id=doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Documento no encontrado.")
        if doc.status == "rolled_back":
            return RedirectResponse(url=f"/documents/{doc_id}", status_code=303)

        previous_status = doc.status
        doc.status = "rolled_back"
        log(session, doc.id, "rolled_back", f"Revertido desde estado '{previous_status}'.")
        session.commit()
        return RedirectResponse(url=f"/documents/{doc_id}", status_code=303)
    finally:
        session.close()


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok"}
