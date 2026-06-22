# 🌐 Gateway Multicanal — Vertex AI Agent Runtime

Microservicio FastAPI que conecta **WhatsApp**, **Telegram** y una **Web App** con un Agente de IA desplegado en [Vertex AI Agent Runtime](https://cloud.google.com/vertex-ai/docs/reasoning-engine/overview) (Reasoning Engine).

## Arquitectura

```
WhatsApp  ──┐
Telegram  ──┼──▶  Cloud Run Gateway  ──▶  Vertex AI Reasoning Engine
Web App   ──┘          (FastAPI)               (Agente de IA)
```

## Estructura del Proyecto

```
gateway/
├── app/
│   ├── main.py                  # Entry point + lifespan
│   ├── core/
│   │   └── config.py            # Settings (.env)
│   ├── services/
│   │   └── agent_service.py     # Wrapper ReasoningEngine
│   ├── api/v1/
│   │   ├── router.py
│   │   └── endpoints/
│   │       ├── web.py           # POST /api/chat
│   │       ├── telegram.py      # POST /webhook/telegram
│   │       └── whatsapp.py      # GET+POST /webhook/whatsapp
│   └── schemas/
│       └── messages.py          # Pydantic models
├── .env.example
├── Dockerfile
├── requirements.txt
└── README.md
```

## Configuración Local

### 1. Clonar y configurar variables de entorno

```bash
cp .env.example .env
# Edita .env con tus credenciales reales
```

### 2. Crear entorno virtual e instalar dependencias

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Autenticación con Google Cloud

```bash
# Opción A: Credenciales de aplicación (desarrollo local)
gcloud auth application-default login

# Opción B: Service Account key (producción)
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/sa-key.json"
```

### 4. Ejecutar el servidor

```bash
uvicorn app.main:app --reload --port 8000
```

### 5. Probar el endpoint web

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hola, ¿qué puedes hacer?", "session_id": "test-123"}'
```

### 6. Health check

```bash
curl http://localhost:8000/health
```

## Despliegue en Cloud Run

### Opción 1: Deploy desde código fuente (recomendado)

```bash
gcloud run deploy gateway \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "PROJECT_ID=tu-proyecto,LOCATION=us-central1,REASONING_ENGINE_ID=projects/tu-proyecto/locations/us-central1/reasoningEngines/123456" \
  --set-env-vars "TELEGRAM_BOT_TOKEN=tu-token" \
  --set-env-vars "WHATSAPP_ACCESS_TOKEN=tu-token,WHATSAPP_VERIFY_TOKEN=tu-secret,WHATSAPP_PHONE_NUMBER_ID=123456"
```

### Opción 2: Build manual + deploy

```bash
# Build
docker build -t gcr.io/TU_PROYECTO/gateway .

# Push
docker push gcr.io/TU_PROYECTO/gateway

# Deploy
gcloud run deploy gateway \
  --image gcr.io/TU_PROYECTO/gateway \
  --region us-central1 \
  --allow-unauthenticated
```

## Configuración de Webhooks

Una vez desplegado, obtendrás una URL como `https://gateway-xxxxx.run.app`.

### Telegram

```bash
curl "https://api.telegram.org/bot<TU_TOKEN>/setWebhook?url=https://gateway-xxxxx.run.app/webhook/telegram"
```

### WhatsApp

1. Ve al [Meta App Dashboard](https://developers.facebook.com/)
2. En **Webhooks**, configura la URL: `https://gateway-xxxxx.run.app/webhook/whatsapp`
3. Usa el mismo `WHATSAPP_VERIFY_TOKEN` que configuraste en `.env`
4. Suscríbete al campo `messages`

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/chat` | Chat web (JSON) |
| `POST` | `/webhook/telegram` | Webhook Telegram |
| `GET` | `/webhook/whatsapp` | Verificación Meta |
| `POST` | `/webhook/whatsapp` | Mensajes WhatsApp |

## Service Account

La Service Account de Cloud Run necesita el rol:

```
roles/aiplatform.user
```

Esto permite al Gateway llamar al Reasoning Engine en Vertex AI.
