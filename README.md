# brandyManager Backend

Backend inicial en Django REST Framework con PostgreSQL levantado mediante Docker Compose.

## Requisitos

- Docker Desktop instalado y en ejecucion.
- Docker Compose disponible desde la terminal.

## Arranque rapido

Desde esta carpeta:

```bash
docker compose up --build
```

Servicios:

- Backend Django: http://localhost:8000
- API weather forecast: http://localhost:8000/api/weather-forecast/
- PostgreSQL: localhost:5432

El contenedor `backend` ejecuta automaticamente las migraciones antes de arrancar el servidor.

## Variables de entorno

Puedes crear un archivo `.env` usando `.env.example` como referencia:

```bash
cp .env.example .env
```

Valores por defecto para desarrollo:

- Base de datos: `brandymanager`
- Usuario: `brandymanager`
- Password: `brandymanager`
- Host interno desde Django: `db`

## Comandos utiles

```bash
docker compose up --build
docker compose down
docker compose exec backend python manage.py createsuperuser
docker compose exec backend python manage.py test
```

## Endpoint inicial

```http
GET /api/weather-forecast/
```

Respuesta de ejemplo:

```json
[
  {
    "date": "2026-07-08",
    "temperature_c": 8,
    "temperature_f": 46,
    "summary": "Freezing"
  }
]
```

Esta API es solo una base tecnica para comprobar que Django REST Framework, rutas y contenedores funcionan correctamente.
