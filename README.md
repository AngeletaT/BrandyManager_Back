# brandyManager Backend

Backends de brandyManager levantados mediante Docker Compose:

- `back_django`: API principal en Django REST Framework con PostgreSQL.
- `back_go`: servicio Go preparado como base para el motor de reproduccion.

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
- Backend Go: http://localhost:8080
- PostgreSQL: localhost:5432

El contenedor `back_django` ejecuta automaticamente las migraciones antes de arrancar el servidor.

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
- URL interna de Django desde Go: `http://back_django:8000`

## Comandos utiles

```bash
docker compose up --build
docker compose down
docker compose exec back_django python manage.py createsuperuser
docker compose exec back_django python manage.py test
```

## Estructura

```text
back_django/
  backend/
  requirements/
  Dockerfile

back_go/
  cmd/server/
  Dockerfile
  go.mod
```

## Backend Go

El backend Go queda como API operativa. Django sigue gestionando autenticacion, usuarios, permisos y administracion interna. Go recibira el JWT emitido por Django en las rutas `/api/v1`.

Responsabilidades iniciales de Go:

- Organizaciones operativas: empresas, sedes, zonas y ambitos.
- Facturacion operativa: planes, suscripciones, licencias y asignaciones.
- Catalogo, playlists, canales, programaciones y campanas.
- Dispositivos, manifiestos, comandos y reproduccion.

Endpoints iniciales publicos:

```http
GET /health
```

Endpoints iniciales protegidos con `Authorization: Bearer <token>`:

```http
GET /api/v1/system
GET /api/v1/modules
GET /api/v1/modules/{module}/status
POST /api/v1/playback/commands
```

El modo actual de autenticacion en Go es `passthrough`: exige que llegue un Bearer token de Django y deja preparada la capa para validar o introspectar el token en una iteracion posterior.

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
    "id": "2f3b2f9f-7a21-4b4a-9e4f-6c0e8f4b9132",
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
