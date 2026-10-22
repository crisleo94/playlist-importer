# Playlist Importer (Spotify ↔ YouTube Music)

Herramienta web construida con **Django**, **uv**, **Celery**, **Redis**, **PostgreSQL**, **HTMX** y **Tailwind CSS** para sincronizar y migrar playlists entre Spotify y YouTube Music.

## 🚀 Requisitos

- [uv](https://docs.astral.sh/uv/) (v0.11+)
- Python 3.12+
- Docker y Docker Compose (opcional para ejecución con PostgreSQL y Celery)

## 🛠️ Instalación y Desarrollo Local

1. **Clonar el repositorio**:
   ```bash
   git clone <repo-url>
   cd playlist-importer
   ```

2. **Instalar dependencias con `uv`**:
   ```bash
   uv sync
   ```

3. **Configurar variables de entorno**:
   ```bash
   cp .env.example .env
   ```
   Edita `.env` con tus claves de desarrollador de Spotify y Google Console.

4. **Ejecutar migraciones de base de datos**:
   ```bash
   uv run python manage.py migrate
   ```

5. **Iniciar el servidor de desarrollo**:
   ```bash
   uv run python manage.py runserver
   ```

## 🐳 Ejecución con Docker Compose (Producción / Completo)

Para levantar todos los servicios (`web`, `celery worker`, `redis`, `postgresql`):

```bash
docker compose up --build
```

La aplicación estará disponible en `http://localhost:8000`.
