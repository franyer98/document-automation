# Document Automation Pipeline

Pipeline autónomo de extracción de datos de facturas/recibos. Sube una imagen,
Claude (con visión) extrae los campos estructurados, un módulo de validación
combina reglas de negocio con la confianza del modelo, y el sistema decide
por sí solo si auto-aprobar el documento o marcarlo para revisión — sin
humano en el loop, pero con auditoría completa y rollback por si algo sale mal.

## Cómo funciona

1. **Ingesta** — subes una imagen (JPG/PNG) de una factura o recibo.
2. **Extracción** — Claude analiza la imagen y devuelve JSON estructurado
   (proveedor, fecha, montos, ítems) más su propia confianza.
3. **Validación** — se contrastan reglas de negocio (¿subtotal + impuesto =
   total? ¿fecha plausible? ¿ítems consistentes?) que solo pueden penalizar
   la confianza reportada, nunca inflarla.
4. **Decisión autónoma** — si la confianza final supera el umbral
   (`AUTO_APPROVE_THRESHOLD`, default 0.85), el documento se auto-aprueba;
   si no, queda `flagged` para revisión posterior (no bloquea el flujo).
5. **Auditoría y rollback** — cada acción queda registrada. Cualquier
   documento (aprobado o no) puede revertirse desde el dashboard.
6. **Idempotencia** — subir el mismo archivo dos veces no crea un duplicado
   (se identifica por hash del contenido).

## Correr en local

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env            # y pega tu ANTHROPIC_API_KEY
uvicorn app.main:app --reload
```

Abre http://localhost:8000

## Desplegar en Render (gratis)

1. Crea un repo en GitHub y sube este proyecto (ver pasos abajo).
2. Entra a [render.com](https://render.com) y crea una cuenta (gratis, con GitHub).
3. **New +** → **Blueprint** → conecta tu repo. Render detecta `render.yaml`
   automáticamente y configura el servicio.
4. En la sección **Environment**, agrega la variable `ANTHROPIC_API_KEY`
   con tu clave real (no se sube al repo, se guarda solo en Render).
5. Deploy. En unos minutos tendrás una URL pública tipo
   `https://document-automation-xxxx.onrender.com`.

**Nota sobre persistencia:** el plan free de Render no soporta disco
persistente, así que la base SQLite se reinicia en cada redeploy o cuando
el servicio duerme por inactividad. Para un portafolio esto es aceptable
(el objetivo es demostrar el pipeline funcionando); si necesitas que los
datos sobrevivan, sube al plan "Starter" y descomenta el bloque `disk` en
`render.yaml`, o cambia a una base de datos gestionada (ej. Postgres en
Render/Supabase/Neon, todos con capa gratuita).

## Variables de entorno

| Variable | Descripción |
|---|---|
| `ANTHROPIC_API_KEY` | Requerida. Clave de la API de Anthropic (console.anthropic.com). |
| `AUTO_APPROVE_THRESHOLD` | Umbral de confianza (0–1) para auto-aprobar. Default `0.85`. |

## Decisiones de diseño (por qué es "de sistemas" y no solo un script)

- **Ninguna acción destructiva ocurre sin registro**: toda transición de
  estado (`created`, `extracted`, `auto_approved`, `flagged`, `rolled_back`)
  queda en `audit_entries` con timestamp y detalle.
- **La confianza combina modelo + reglas**: el LLM puede "sonar seguro" y
  estar equivocado; las reglas de negocio actúan como segunda capa de
  verificación independiente del propio modelo.
- **Idempotencia por hash de contenido**: reintentar una subida (por error
  de red, doble clic, etc.) no duplica datos.
- **Fallos de la API no rompen el pipeline**: si Claude falla o devuelve
  algo no parseable, el documento se marca `flagged` con el motivo exacto,
  en vez de crashear la request.
