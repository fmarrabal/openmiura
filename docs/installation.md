# Guía de instalación limpia

Esta guía está pensada para una instalación desde cero, sin residuos previos, tanto en un portátil personal como en un servidor pequeño.

## 1. Requisitos

- Python 3.10, 3.11 o 3.12
- `pip`
- Git
- Opcionalmente Docker y Docker Compose
- Opcionalmente Ollama, o claves API de OpenAI / Anthropic / Kimi

## 2. Clonar el proyecto

```bash
git clone <tu-repo-openmiura>
cd openMiura
```

## 3. Crear entorno virtual

### Linux / macOS

```bash
python -m venv .venv
source .venv/bin/activate
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 4. Instalar openMiura

Instalación mínima:

```bash
pip install -e .
```

Instalación con soporte PostgreSQL:

```bash
pip install -e .[postgres]
```

Instalación con utilidades de desarrollo:

```bash
pip install -e .[dev]
```

## 5. Preparar configuración

```bash
cp .env.example .env
```

Revisa al menos:

- `OPENMIURA_ADMIN_TOKEN`
- `OPENMIURA_UI_ADMIN_USERNAME`
- `OPENMIURA_UI_ADMIN_PASSWORD`
- proveedor LLM elegido
- canales que realmente vayas a activar

La configuración principal está en:

- `configs/openmiura.yaml`
- `configs/agents.yaml`
- `configs/policies.yaml`

## 6. Verificación inicial

```bash
openmiura doctor --config configs/
```

Comprueba que el doctor informa correctamente de:

- config cargada
- backend de almacenamiento
- directorio sandbox
- provider LLM
- skills
- broker/MCP si están activados

## 7. Arranque

```bash
openmiura run --config configs/
```

Interfaz web:

- `http://localhost:8081/ui`

Healthcheck:

- `http://localhost:8081/health`

Metrics:

- `http://localhost:8081/metrics`

## 8. Instalación con Docker

```bash
cp .env.example .env
docker compose up --build
```

Con observabilidad:

```bash
docker compose --profile observability up --build
```

## 9. Instalación limpia recomendada antes de release

Antes de generar un artefacto público, asegúrate de que no se empaquetan:

- `data/audit.db`
- `__pycache__/`
- `.pytest_cache/`
- `.env`
- claves privadas o tokens

## 10. Checklist mínima post-instalación

- `openmiura version`
- `openmiura doctor --config configs/`
- acceso a `/ui`
- login admin bootstrap
- una conversación de prueba
- una tool sencilla como `time_now`
- una búsqueda de memoria
