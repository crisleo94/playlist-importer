# Playlist Importer (Spotify ↔ YouTube Music)

Aplicación web moderna y robusta construida con **Django 5**, **Celery**, **Redis**, **PostgreSQL**, **HTMX**, **Alpine.js** y **Tailwind CSS** para sincronizar y migrar listas de reproducción de manera bidireccional entre **Spotify** y **YouTube Music**.

El sistema cuenta con un motor inteligente de emparejamiento por **código ISRC** y **búsqueda normalizada tolerante a variaciones**, previsualización en seco (*dry-run*), ejecución asíncrona mediante Celery workers con control preventivo de cuotas y seguimiento de avance en tiempo real mediante sondeo reactivo con HTMX.

---

## 🛠️ Stack Tecnológico

- **Backend:** Python 3.12, Django 5.x, Celery 5.x, psycopg (PostgreSQL 16), Cryptography (cifrado simétrico Fernet de tokens OAuth).
- **Gestión de Entorno y Paquetes:** [Astral uv](https://docs.astral.sh/uv/) con pinning estricto de dependencias en `pyproject.toml` y `uv.lock`.
- **Frontend / UI:** Interfaz comparativa de dos columnas con Tailwind CSS, componentes interactivos en Alpine.js y transiciones dinámicas sin recarga completa mediante HTMX.
- **Broker y Caché:** Redis 7 para colas de tareas Celery y almacenamiento en caché con claves normalizadas (MD5).
- **Contenedores:** Dockerfile multi-stage con stage builder optimizado con `uv` y runtime slim ejecutado por usuario no-root (`appuser`), orquestado con `docker-compose.yml`.

---

## 📋 Requisitos Previos

1. **Python 3.12** y el gestor de paquetes **[uv](https://docs.astral.sh/uv/)** instalado (`curl -LsSf https://astral.sh/uv/install.sh | sh` o en Windows `irm https://astral.sh/uv/install.ps1 | iex`).
2. **Docker y Docker Compose** (para despliegue contenedorizado o servicios auxiliares).
3. Cuentas de desarrollador en **Spotify** y **Google Cloud**.

---

## 🔑 Configuración de Credenciales de API

### 1. Spotify Developer Dashboard
1. Ingresa a [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) e inicia sesión.
2. Haz clic en **Create App**:
   - **App name:** `Playlist Importer`
   - **App description:** `Migración y sincronización de playlists`
   - **Redirect URI:** `http://localhost:8000/integrations/spotify/callback/`
   - **APIs used:** Web API
3. Acepta los términos y guarda la aplicación.
4. En la configuración de la app (**Settings**), copia el **Client ID** y **Client Secret**.

### 2. Google Cloud Console (YouTube Data API v3)
1. Ingresa a [Google Cloud Console](https://console.cloud.google.com/) y crea un nuevo proyecto.
2. Ve a **APIs & Services** > **Library**, busca **YouTube Data API v3** y actívala (**Enable**).
3. Configura la **OAuth consent screen**:
   - Selecciona **External** y llena los campos requeridos.
   - En **Scopes**, añade:
     - `https://www.googleapis.com/auth/youtube`
     - `https://www.googleapis.com/auth/youtube.force-ssl`
   - En **Test users**, añade tu correo de Google para poder autenticarte en modo de prueba.
4. Ve a **Credentials** > **Create Credentials** > **OAuth client ID**:
   - **Application type:** Web application
   - **Name:** `Playlist Importer Web`
   - **Authorized redirect URIs:** `http://localhost:8000/integrations/youtube/callback/`
5. Copia el **Client ID** y **Client Secret** generados.

---

## ⚙️ Configuración del Entorno (.env)

Copia la plantilla de variables de entorno:

```bash
cp .env.example .env
```

Genera una clave simétrica válida para el cifrado de tokens (Fernet de 32 bytes en base64 url-safe):

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Configura tu archivo `.env` con los valores correspondientes:

```env
# Django
DJANGO_SECRET_KEY=clave-secreta-larga-y-aleatoria-para-produccion
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,web

# Cifrado de Tokens
FIELD_ENCRYPTION_KEY=pega_aqui_la_clave_fernet_generada

# Spotify OAuth
SPOTIFY_CLIENT_ID=tu_spotify_client_id
SPOTIFY_CLIENT_SECRET=tu_spotify_client_secret
SPOTIFY_REDIRECT_URI=http://localhost:8000/integrations/spotify/callback/

# Google / YouTube Data API v3 OAuth
GOOGLE_CLIENT_ID=tu_google_client_id
GOOGLE_CLIENT_SECRET=tu_google_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/integrations/youtube/callback/

# Base de Datos (PostgreSQL)
POSTGRES_DB=playlist_importer
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Celery & Redis
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

---

## 🚀 Despliegue con Docker Compose (Recomendado)

Docker Compose levanta de forma automática los 4 servicios orquestados con healthchecks activos (`db`, `redis`, `web`, `worker`):

```bash
# Compilar las imágenes multi-stage y arrancar en segundo plano
docker compose up --build -d

# Ver el estado de salud de los servicios
docker compose ps

# Ver logs en tiempo real
docker compose logs -f
```

La aplicación estará disponible de inmediato en [http://localhost:8000](http://localhost:8000).

Para detener los servicios:

```bash
docker compose down
```

---

## 💻 Desarrollo Local

Si deseas correr los componentes directamente en tu máquina:

1. **Instalar dependencias:**
   ```bash
   uv sync
   ```

2. **Levantar base de datos y Redis (con Docker):**
   ```bash
   docker compose up -d db redis
   ```

3. **Ejecutar migraciones:**
   ```bash
   uv run python manage.py migrate
   ```

4. **Iniciar el worker de Celery en una terminal separada:**
   ```bash
   uv run celery -A config worker --loglevel=info --concurrency=2
   ```

5. **Iniciar el servidor web de Django:**
   ```bash
   uv run python manage.py runserver
   ```

Accede a [http://localhost:8000](http://localhost:8000) para registrarte, vincular tus cuentas y transferir tus listas.

---

## 🧪 Pruebas Automatizadas

La suite incluye pruebas unitarias e integrales End-to-End (E2E) con mocking exhaustivo de las APIs externas para validar todo el flujo sin consumir cuotas de API:

```bash
uv run python manage.py test
```

---

## 📄 Licencia

Este proyecto está bajo la licencia MIT.
