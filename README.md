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

## Usuarios y autenticacion

El usuario se identifica por email y no depende de `username`. Los accesos se resuelven mediante roles internos de plataforma, membresias de empresa, permisos y ambitos.

### Registro

```http
POST /api/users/register/
```

Body:

```json
{
  "email": "client@example.com",
  "password": "StrongPass123!",
  "first_name": "Client",
  "last_name": "Example"
}
```

Respuesta:

```json
{
  "user": {
    "id": 1,
    "email": "client@example.com",
    "first_name": "Client",
    "last_name": "Example",
    "created_at": "2026-07-08T18:44:00Z"
  },
  "tokens": {
    "refresh": "...",
    "access": "..."
  }
}
```

### Login

```http
POST /api/users/login/
```

Body:

```json
{
  "email": "client@example.com",
  "password": "StrongPass123!"
}
```

Devuelve la misma estructura que el registro, con `access` y `refresh`.

La API de usuarios es la primera base funcional del backend.
