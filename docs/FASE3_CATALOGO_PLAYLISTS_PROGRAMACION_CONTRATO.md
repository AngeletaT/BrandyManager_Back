# BrandyManager Fase 3 - Contrato v0.1

Fecha: 2026-09-03

Estado: contrato versionado. Catalogo cliente, gestion de playlists y programacion persistente implementados en Django. A fecha de la inspeccion inicial, `config.urls` no registraba rutas Django para `catalog`, `playlists` ni `scheduling`; tras los bloques actuales se registran `api/catalog/`, `api/playlists/` y `api/scheduling/`.

Actualizacion 2026-09-03:

- Implementados `GET /api/catalog/genres/`, `GET /api/catalog/tags/`, `GET /api/catalog/songs/` y `GET /api/catalog/songs/{song_id}/`.
- Implementados `GET/POST /api/playlists/`, `GET/PATCH /api/playlists/{playlist_id}/`, gestion de items, duplicacion, publicacion, version publicada, archivado y reactivacion.
- Implementados `GET/POST /api/scheduling/schedules/`, detalle, bloques, excepciones, asignaciones, publicacion, archivado, desactivacion, ocurrencias y resolucion de configuracion.
- No se implementan subida/importacion de audio ni escucha previa porque el contrato no las aprobo.
- La lectura de catalogo se trata como funcion de producto y se bloquea con `functional_access_blocked` cuando la suscripcion/trial no permite acceso funcional.
- La lectura de programacion se permite con trial caducada para consultar configuracion; las mutaciones se bloquean con `functional_access_blocked`.

## 1. Inventario pantalla-operacion-endpoint-servicio

| Pantalla | Operacion UI | Endpoint propuesto | Servicio propietario | Estado actual |
| --- | --- | --- | --- | --- |
| `/app/catalogo` | Listar canciones disponibles | `GET /api/catalog/songs/` | Django | Implementado y probado |
| `/app/catalogo` | Detalle de cancion | `GET /api/catalog/songs/{song_id}/` | Django | Implementado y probado |
| `/app/catalogo` | Filtros de generos | `GET /api/catalog/genres/` | Django | Implementado y probado |
| `/app/catalogo` | Filtros de etiquetas | `GET /api/catalog/tags/` | Django | Implementado y probado |
| `/app/catalogo` | Anadir cancion a playlist | `POST /api/playlists/{playlist_id}/items/` | Django | Implementado y probado |
| `/app/catalogo` | Crear playlist con cancion inicial | `POST /api/playlists/` seguido de `POST /api/playlists/{playlist_id}/items/` | Django | Implementado y probado |
| `/app/playlists` | Listar playlists | `GET /api/playlists/` | Django | Implementado y probado |
| `/app/playlists` | Crear playlist | `POST /api/playlists/` | Django | Implementado y probado |
| `/app/playlists` | Duplicar playlist | `POST /api/playlists/{playlist_id}/duplicate/` | Django | Implementado y probado |
| `/app/playlists` | Archivar/reactivar playlist | `POST /api/playlists/{playlist_id}/archive/`, `POST /api/playlists/{playlist_id}/reactivate/` | Django | Implementado y probado |
| `/app/playlists/$playlistId` | Leer detalle e items | `GET /api/playlists/{playlist_id}/` | Django | Implementado y probado |
| `/app/playlists/$playlistId` | Editar metadatos | `PATCH /api/playlists/{playlist_id}/` | Django | Implementado y probado |
| `/app/playlists/$playlistId` | Reemplazar composicion/orden | `PUT /api/playlists/{playlist_id}/items/`, `PUT /api/playlists/{playlist_id}/items/order/` | Django | Implementado y probado |
| `/app/playlists/$playlistId` | Publicar version | `POST /api/playlists/{playlist_id}/publish/` | Django | Implementado y probado |
| `/app/programacion` | Listar programaciones | `GET /api/scheduling/schedules/` | Django | Implementado y probado |
| `/app/programacion` | Crear programacion | `POST /api/scheduling/schedules/` | Django | Implementado y probado |
| `/app/programacion` | Leer detalle con bloques y asignaciones | `GET /api/scheduling/schedules/{schedule_id}/` | Django | Implementado y probado |
| `/app/programacion` | Editar metadatos | `PATCH /api/scheduling/schedules/{schedule_id}/` | Django | Implementado y probado |
| `/app/programacion` | Crear/editar/eliminar bloques | `POST/PATCH/DELETE /api/scheduling/schedules/{schedule_id}/blocks/...` | Django | Implementado y probado |
| `/app/programacion` | Crear/editar/eliminar excepciones | `POST/PATCH/DELETE /api/scheduling/schedules/{schedule_id}/exceptions/...` | Django | Implementado y probado |
| `/app/programacion` | Asignar a empresa/sede/zona | `POST/PATCH/DELETE /api/scheduling/schedules/{schedule_id}/assignments/...` | Django | Implementado y probado |
| `/app/programacion` | Publicar programacion | `POST /api/scheduling/schedules/{schedule_id}/publish/` | Django | Implementado y probado |
| `/app/programacion` | Previsualizar ocurrencias | `GET /api/scheduling/schedules/{schedule_id}/occurrences/` | Django | Implementado y probado |
| `/app/programacion` | Resolver configuracion aplicable a una zona/instante | `GET /api/scheduling/schedules/resolve/` | Django | Implementado y probado |
| Dashboard `/app` | Resumen de playlists/catalogo/programacion | Endpoints anteriores, en modo resumen | Django | UI aun usa mocks |
| Detalle de sede | Dependencias de playlist/programacion | Debe esperar a endpoints reales anteriores | Django | Sin dependencia directa detectada en busqueda |

Go no crea endpoints privados de catalogo, playlists o programacion de negocio en Fase 3. Go mantiene responsabilidad operativa: health, modulos, comandos de playback y futura ingestion de manifiestos/versiones generadas por Django. El endpoint Go `GET /api/modules` declara catalogo, playlists y scheduling de configuracion como `managed_by: "django"`; `playback` permanece como `managed_by: "go"`.

## 2. Modelos existentes reutilizables

### Catalogo

- `Genre`: genero principal.
- `TagCategory` y `Tag`: clasificacion musical y comercial.
- `AudioContent`: entidad comun reproducible con `content_type`, `visibility`, `status`, duracion y propiedad opcional `owner_company`.
- `Song`: detalle de cancion IA con `genre` y relacion `audio_content`. No contiene artista ni album.
- `SongTag`: multiples etiquetas por cancion.
- `AudioAsset` y `AudioAnalysis`: metadatos tecnicos de archivos. No se guardan BLOBs en PostgreSQL.
- `UploadSession` y `ProcessingJob`: preparados para subida/procesado, pero la subida de clientes queda fuera del contrato hasta decision de producto.
- `AudioMessage`: existe, pero mensajes/campanas quedan fuera de Fase 3 salvo que una programacion permita `SILENCE`.

### Playlists

- `Playlist`: lista editable con `owner_company`, `playlist_type`, `visibility`, `status`, `current_version` y `revision` para control de concurrencia de edicion.
- `PlaylistItem`: composicion editable ordenada. Permite repetir canciones porque no existe unicidad `playlist + song`.
- `PlaylistSnapshot` y `PlaylistSnapshotItem`: version publicada e inmutable.
- `Channel`, `ChannelPlaylist`, `ChannelPolicy`: existen, pero la gestion completa de canales queda fuera de Fase 3.
- `ContentAccessGrant`: permite compartir audio, playlists o canales con empresas concretas.

### Programacion

- `Schedule`: programacion de empresa con estado, vigencia y version.
- `ScheduleBlock`: bloques semanales por dia/hora, con destino `CHANNEL`, `PLAYLIST` o `SILENCE`.
- `ScheduleException`: excepciones por fecha.
- `ScheduleAssignment`: asignacion de una programacion a `ResourceScope`.

## 3. Diferencias entre UI simulada y modelo real

| Area | UI actual simulada | Modelo real | Cambio requerido |
| --- | --- | --- | --- |
| Cancion | `titulo`, `artista`, `album`, `anio`, `decada`, `idioma`, `licencia` | `AudioContent.title`, `Song.genre`, `SongTag`, metadatos tecnicos opcionales | Eliminar artista/album del contrato cliente. No mostrar campos no existentes como datos reales. |
| Preview de audio | Mini player con `setInterval` y `Escuchar (mock)` | No existe streaming/preview autorizado en Fase 3 | Aplazar playback/preview a Fase 4 o mostrar estado sin audio reproducible. |
| Filtros catalogo | Genero, mood, energia, decada, idioma, estado | Genero y tags por categoria; `status` tecnico de contenido | Mapear mood/energia/etc. a `TagCategory` si existen seeds aprobados. |
| Playlist modo | `Manual`, `Aleatorio`, `Aleatorio sin repeticiones` | `PlaylistType`: `MANUAL`, `RULE_BASED`; `ChannelPolicy.order_mode` pertenece a canales | No traducir automaticamente modos UI a regla de negocio. Fase 3 debe iniciar con playlists `MANUAL`. |
| Duracion minima | Constante frontend `3600` segundos | No hay regla en backend | Tratarlo solo como aviso de UI si se mantiene; no bloquear publicacion sin decision. |
| Uso de playlist | Deducido desde canales, zonas y programacion mock | Canales fuera de Fase 3; schedule puede referenciar playlist | Mostrar usos por programaciones reales; no inventar uso en canales. |
| Programacion | Evento con `playlistId`, `channelId`, `venueId`, `zoneId` | `Schedule` + `ScheduleBlock` + `ScheduleAssignment` a scopes | Separar contenido del bloque y destino de asignacion. Eliminar filtro de empresa multiple. |
| Conflictos | Calculados en navegador por canal/dia/hora | Backend debe validar o reportar conflictos segun politica aprobada | Decision pendiente: bloquear solapes o permitirlos por prioridad. |
| Fallback | Playlist de reserva por canal | `ChannelPolicy.fallback_channel`, canales fuera de Fase 3 | Aplazar fallback a Fase 4. |

## 4. Propiedad de datos y responsabilidades

Django es propietario de:

- Catalogo musical persistente: `AudioContent`, `Song`, `Genre`, `Tag`, `AudioAsset`.
- Disponibilidad por empresa: `visibility`, `owner_company`, `ContentAccessGrant`.
- Playlists, items, snapshots y estados de publicacion.
- Programaciones, bloques, excepciones y asignaciones a scopes.
- Autorizacion, roles, membresias, limites de plan y acceso funcional.

Go es propietario de:

- Operativa de reproduccion.
- Comandos a dispositivos.
- Estado runtime y futura sincronizacion/manifiestos.
- Consumo de configuracion publicada por Django mediante API/contrato versionado.

Go no debe modificar directamente tablas de negocio de Django. Para Fase 3, Go no necesita intervenir salvo que se documente el contrato que consumira en Fase 4. Tampoco debe confiarse en `GO_AUTH_MODE=passthrough` para endpoints privados.

## 5. Contratos propuestos

Todas las rutas usan `Authorization: Bearer <access>` y el formato comun de error:

```json
{
  "error": {
    "code": "machine_readable_code",
    "message": "Mensaje legible.",
    "fields": {}
  }
}
```

Lecturas funcionales pueden permitirse con trial caducada si son necesarias para contexto. Mutaciones deben usar `ensure_functional_access` y devolver `403 functional_access_blocked` con `block_reason`.

Decision aplicada en catalogo: la consulta de catalogo no es necesaria para el contexto de cuenta, por lo que requiere acceso funcional vigente.

La paginacion debe seguir la convencion de Fase 2:

```json
{
  "count": 0,
  "page": 1,
  "page_size": 20,
  "results": []
}
```

### 5.1 Catalogo

#### `GET /api/catalog/genres/`

Permiso: `catalog.view`.

Filtros: `is_active=true` implicito para cliente.

Respuesta `200`:

```json
{
  "results": [
    {
      "id": "uuid",
      "name": "Pop",
      "slug": "pop",
      "description": "",
      "sort_order": 10
    }
  ]
}
```

#### `GET /api/catalog/tags/`

Permiso: `catalog.view`.

Query params: `category`, `search`.

Respuesta `200`:

```json
{
  "results": [
    {
      "id": "uuid",
      "category": {
        "code": "MOOD",
        "name": "Mood"
      },
      "name": "Relajado",
      "slug": "relajado",
      "description": ""
    }
  ]
}
```

#### `GET /api/catalog/songs/`

Permiso: `catalog.view`.

Filtros: `search`, `genre`, `tags`, `status`, `page`, `page_size`, `ordering`.

Disponibilidad:

- `AudioContent.content_type = SONG`.
- `AudioContent.status = READY`.
- `AudioContent.is_active = true`.
- Global si `visibility = GLOBAL` y `owner_company is null`.
- Privada si `visibility = PRIVATE` y `owner_company` es la empresa actual.
- Compartida si `visibility = SHARED` y existe `ContentAccessGrant` activo para la empresa.

Respuesta `200`:

```json
{
  "count": 1,
  "page": 1,
  "page_size": 20,
  "results": [
    {
      "id": "uuid-song",
      "audio_content_id": "uuid-content",
      "title": "Apertura suave",
      "description": "",
      "genre": {
        "id": "uuid-genre",
        "name": "Lo-fi",
        "slug": "lo-fi"
      },
      "tags": [
        {
          "id": "uuid-tag",
          "category_code": "MOOD",
          "name": "Relajado",
          "slug": "relajado"
        }
      ],
      "duration_ms": 180000,
      "duration_unit": "milliseconds",
      "is_explicit": false,
      "visibility": "GLOBAL",
      "status": "READY",
      "published_at": "2026-09-03T10:00:00Z",
      "permissions": {
        "can_view": true,
        "can_use": true,
        "can_add_to_playlist": true
      }
    }
  ]
}
```

No incluir artista, album, compositor ni creditos.

#### `GET /api/catalog/songs/{song_id}/`

Igual que item de listado, con metadatos tecnicos permitidos:

```json
{
  "id": "uuid-song",
  "audio_content_id": "uuid-content",
  "title": "Apertura suave",
  "description": "",
  "genre": {
    "id": "uuid-genre",
    "name": "Lo-fi",
    "slug": "lo-fi"
  },
  "tags": [],
      "duration_ms": 180000,
      "duration_unit": "milliseconds",
      "is_explicit": false,
      "visibility": "GLOBAL",
      "status": "READY",
      "published_at": "2026-09-03T10:00:00Z",
      "permissions": {
        "can_view": true,
        "can_use": true,
        "can_add_to_playlist": true
      },
      "assets": [
        {
          "id": "uuid-asset",
          "asset_role": "PREVIEW",
          "mime_type": "audio/mpeg",
          "duration_ms": 30000,
          "duration_unit": "milliseconds",
          "processing_status": "READY"
        }
      ]
}
```

La URL de streaming/descarga no se define en Fase 3.

La implementacion solo expone assets `PREVIEW` con `processing_status = READY` y oculta `storage_key`, `storage_backend`, `checksum_sha256` y cualquier ruta fisica.

### 5.2 Playlists

#### `GET /api/playlists/`

Permiso: `playlists.view`.

Filtros: `search`, `status`, `visibility`, `page`, `page_size`.

Respuesta `200`:

```json
{
  "count": 1,
  "page": 1,
  "page_size": 20,
  "results": [
    {
      "id": "uuid",
      "name": "Mañanas suaves",
      "code": "MANANAS-SUAVES",
      "description": "",
      "playlist_type": "MANUAL",
      "visibility": "PRIVATE",
      "status": "DRAFT",
      "current_version": 0,
      "revision": 1,
      "song_count": 8,
      "duration_ms": 1440000,
      "published_at": null,
      "created_at": "2026-09-03T10:00:00Z",
      "updated_at": "2026-09-03T10:00:00Z",
      "permissions": {
        "can_view": true,
        "can_update": true,
        "can_archive": true,
        "can_reactivate": false,
        "can_publish": true,
        "can_duplicate": true
      }
    }
  ]
}
```

#### `POST /api/playlists/`

Permiso: `playlists.manage`. Bloquea trial caducada.

Payload:

```json
{
  "name": "Mañanas suaves",
  "code": "MANANAS-SUAVES",
  "description": ""
}
```

Campos no aceptados desde navegador: `owner_company`, `company_id`, `status`, `current_version`, `visibility` global, `created_by`, `playlist_type` distinto de `MANUAL`.

Respuesta `201`: detalle de playlist.

Reglas:

- `owner_company` siempre es la Company actual.
- `visibility` inicial `PRIVATE`.
- `status` inicial `DRAFT`.
- Aplicar limite `playlists` del plan sobre playlists no archivadas de la empresa.
- `code` unico por empresa.

#### `GET /api/playlists/{playlist_id}/`

Permiso: `playlists.view`.

Respuesta `200`:

```json
{
  "id": "uuid",
  "name": "Mañanas suaves",
  "code": "MANANAS-SUAVES",
  "description": "",
  "playlist_type": "MANUAL",
  "visibility": "PRIVATE",
  "status": "DRAFT",
  "current_version": 0,
  "song_count": 2,
  "duration_ms": 360000,
  "published_at": null,
  "items": [
    {
      "id": "uuid-item",
      "position": 1,
      "weight": 1,
      "song": {
        "id": "uuid-song",
        "title": "Apertura suave",
        "genre": {
          "id": "uuid-genre",
          "name": "Lo-fi",
          "slug": "lo-fi"
        },
        "duration_ms": 180000,
        "is_explicit": false
      },
      "active_from": null,
      "active_until": null
    }
  ],
  "latest_snapshot": null,
  "permissions": {
    "can_view": true,
    "can_update": true,
    "can_archive": true,
    "can_publish": true,
    "can_duplicate": true
  }
}
```

#### `PATCH /api/playlists/{playlist_id}/`

Permiso: `playlists.manage`. Bloquea trial caducada.

Payload parcial:

```json
{
  "expected_revision": 1,
  "name": "Mañanas suaves",
  "code": "MANANAS-SUAVES",
  "description": ""
}
```

No permite editar `owner_company`, `status`, `current_version`, `created_by` ni items.

#### `PUT /api/playlists/{playlist_id}/items/`

Permiso: `playlists.manage`. Bloquea trial caducada.

Payload:

```json
{
  "expected_revision": 1,
  "items": [
    {
      "song_id": "uuid-song",
      "position": 1,
      "weight": 1
    }
  ]
}
```

Reglas:

- Operacion transaccional.
- Reemplaza la composicion editable completa.
- Permite repetir canciones de forma intencionada.
- Valida que cada cancion sea accesible por la empresa.
- Posiciones consecutivas recomendadas desde `1`.
- No modifica snapshots ya publicados.

Respuesta `200`: detalle de playlist.

#### `POST /api/playlists/{playlist_id}/items/`

Atajo para anadir una cancion al final.

Payload:

```json
{
  "expected_revision": 1,
  "song_id": "uuid-song",
  "weight": 1
}
```

Respuesta `201`: detalle de playlist actualizado.

#### `PUT /api/playlists/{playlist_id}/items/order/`

Reordena elementos existentes por `PlaylistItem.id`.

Payload:

```json
{
  "expected_revision": 1,
  "item_ids": ["uuid-item-2", "uuid-item-1"]
}
```

Respuesta `200`: detalle de playlist actualizado.

Reglas:

- Deben enviarse todos los elementos actuales una sola vez.
- No se aceptan elementos de otra playlist.
- La operacion es transaccional y deja posiciones consecutivas desde `1`.

#### `DELETE /api/playlists/{playlist_id}/items/{item_id}/`

Retira un elemento identificado por `PlaylistItem.id`.

Payload:

```json
{
  "expected_revision": 1
}
```

Respuesta `200`: detalle de playlist actualizado con posiciones normalizadas.

#### `POST /api/playlists/{playlist_id}/publish/`

Permiso: `playlists.manage`. Bloquea trial caducada.

Respuesta `201`:

```json
{
  "playlist": {
    "id": "uuid",
    "status": "PUBLISHED",
    "current_version": 1,
    "revision": 2,
    "published_at": "2026-09-03T10:00:00Z"
  },
  "snapshot": {
    "id": "uuid-snapshot",
    "version": 1,
    "status": "PUBLISHED",
    "checksum": "sha256",
    "published_at": "2026-09-03T10:00:00Z",
    "item_count": 8
  }
}
```

El servicio crea snapshots inmutables, actualiza la playlist y es idempotente para reintentos con el mismo checksum ya publicado. No se marcan snapshots anteriores como `SUPERSEDED` porque esa decision sigue pendiente.

#### `GET /api/playlists/{playlist_id}/published-version/`

Permiso: `playlists.view`.

Respuesta `200`:

```json
{
  "snapshot": {
    "id": "uuid-snapshot",
    "version": 1,
    "status": "PUBLISHED",
    "checksum": "sha256",
    "published_at": "2026-09-03T10:00:00Z",
    "item_count": 8
  }
}
```

Si no existe version publicada, `snapshot` es `null`.

#### `POST /api/playlists/{playlist_id}/duplicate/`

Permiso: `playlists.manage`. Bloquea trial caducada.

Payload opcional:

```json
{
  "name": "Mañanas suaves copia",
  "code": "MANANAS-SUAVES-COPIA"
}
```

Respuesta `201`: detalle de nueva playlist `DRAFT`, con items copiados y sin snapshots.

#### `POST /api/playlists/{playlist_id}/archive/`

Permiso: `playlists.manage`. Bloquea trial caducada.

Respuesta `200`: detalle de playlist con `status = ARCHIVED`.

Politica aplicada: se bloquea el archivado de playlists con usos reales en programacion mediante `409 playlist_in_use`. No se completan dependencias de canales con mocks.

#### `POST /api/playlists/{playlist_id}/reactivate/`

Permiso: `playlists.manage`. Bloquea trial caducada y valida limite del plan.

Respuesta `200`: detalle con `status = DRAFT`.

### 5.3 Programacion

La programacion debe modelarse como `Schedule` con bloques y asignaciones. No se debe conservar el contrato mock de `ScheduleEvent` como tabla plana.

#### `GET /api/scheduling/schedules/`

Permiso: `schedules.view`.

Filtros: `search`, `status`, `scope_type`, `site_id`, `zone_id`, `page`, `page_size`.

Respuesta `200`:

```json
{
  "count": 1,
  "page": 1,
  "page_size": 20,
  "results": [
    {
      "id": "uuid",
      "name": "Semana tipo Valencia",
      "description": "",
      "timezone": "Europe/Madrid",
      "status": "DRAFT",
      "valid_from": null,
      "valid_until": null,
      "version": 1,
      "revision": 1,
      "block_count": 5,
      "assignment_count": 1,
      "published_at": null,
      "created_at": "2026-09-03T10:00:00Z",
      "updated_at": "2026-09-03T10:00:00Z",
      "permissions": {
        "can_view": true,
        "can_update": true,
        "can_archive": true,
        "can_publish": true
      }
    }
  ]
}
```

#### `POST /api/scheduling/schedules/`

Permiso: `schedules.manage`. Bloquea trial caducada.

Payload:

```json
{
  "name": "Semana tipo Valencia",
  "description": "",
  "timezone": "Europe/Madrid",
  "valid_from": null,
  "valid_until": null
}
```

Respuesta `201`: detalle de schedule.

#### `GET /api/scheduling/schedules/{schedule_id}/`

Permiso: `schedules.view`.

Respuesta `200`:

```json
{
  "id": "uuid",
  "name": "Semana tipo Valencia",
  "description": "",
  "timezone": "Europe/Madrid",
  "status": "DRAFT",
  "valid_from": null,
      "valid_until": null,
      "version": 1,
      "revision": 1,
      "published_at": null,
  "blocks": [
    {
      "id": "uuid-block",
      "day_of_week": 0,
      "start_time": "10:00:00",
      "end_time": "14:00:00",
      "content_type": "PLAYLIST",
      "playlist": {
        "id": "uuid-playlist",
        "name": "Mañanas suaves",
        "status": "PUBLISHED",
        "current_version": 1
      },
      "channel": null,
      "priority": 0,
      "volume_override": null,
      "created_at": "2026-09-03T10:00:00Z",
      "updated_at": "2026-09-03T10:00:00Z"
    }
  ],
  "exceptions": [
    {
      "id": "uuid-exception",
      "date": "2026-09-07",
      "start_time": "10:30:00",
      "end_time": "11:00:00",
      "action": "SILENCE",
      "playlist": null,
      "channel": null,
      "priority": 10,
      "volume_override": null,
      "description": "",
      "created_at": "2026-09-03T10:00:00Z",
      "updated_at": "2026-09-03T10:00:00Z"
    }
  ],
  "assignments": [
    {
      "id": "uuid-assignment",
      "scope": {
        "id": "uuid-scope",
        "scope_type": "SITE",
        "name": "Mercadona Valencia"
      },
      "priority": 0,
      "is_locked": false,
      "starts_at": null,
      "ends_at": null,
      "is_active": true,
      "created_at": "2026-09-03T10:00:00Z",
      "updated_at": "2026-09-03T10:00:00Z"
    }
  ],
  "permissions": {
    "can_view": true,
    "can_update": true,
    "can_archive": true,
    "can_publish": true
  }
}
```

#### `PATCH /api/scheduling/schedules/{schedule_id}/`

Permiso: `schedules.manage`. Bloquea trial caducada.

Payload parcial:

```json
{
  "expected_revision": 1,
  "name": "Semana tipo Valencia",
  "description": "",
  "timezone": "Europe/Madrid",
  "valid_from": "2026-09-01",
  "valid_until": null
}
```

#### `POST /api/scheduling/schedules/{schedule_id}/blocks/`

Permiso: `schedules.manage`. Bloquea trial caducada.

Payload:

```json
{
  "expected_revision": 1,
  "day_of_week": 0,
  "start_time": "10:00:00",
  "end_time": "14:00:00",
  "content_type": "PLAYLIST",
  "playlist_id": "uuid-playlist",
  "priority": 0,
  "volume_override": null
}
```

Fase 3 debe aceptar `PLAYLIST` y `SILENCE`. `CHANNEL` queda aplazado a Fase 4 para no depender de gestion de canales.

Reglas:

- `day_of_week` 0-6.
- `start_time < end_time`; si cruza medianoche, React debe mandar dos bloques.
- `volume_override` 0-100 o null.
- Si `PLAYLIST`, solo `playlist_id` tiene valor y debe ser accesible/publicable por la empresa.
- Si `SILENCE`, `playlist_id` y `channel_id` son null.
- Los solapes con la misma prioridad dentro de la misma programacion se rechazan con `409 schedule_conflict`.
- Los solapes con distinta prioridad se permiten; la resolucion usa prioridad descendente y, despues, fecha de creacion.

#### `PATCH /api/scheduling/schedules/{schedule_id}/blocks/{block_id}/`

Mismo payload parcial y reglas.

#### `DELETE /api/scheduling/schedules/{schedule_id}/blocks/{block_id}/`

Permiso: `schedules.manage`. Respuesta `204`.

El borrado de bloques editables es aceptable si no son historicos; snapshots/versiones publicadas deben preservar la configuracion anterior.

#### `POST /api/scheduling/schedules/{schedule_id}/exceptions/`

Permiso: `schedules.manage`. Bloquea trial caducada.

Payload:

```json
{
  "expected_revision": 1,
  "date": "2026-09-07",
  "start_time": "10:30:00",
  "end_time": "11:00:00",
  "action": "SILENCE",
  "playlist_id": null,
  "priority": 10,
  "volume_override": null,
  "description": ""
}
```

Acciones admitidas: `REPLACE`, `SILENCE`, `VOLUME_OVERRIDE`. `REPLACE` exige playlist publicada; `VOLUME_OVERRIDE` exige `volume_override`.

#### `PATCH /api/scheduling/schedules/{schedule_id}/exceptions/{exception_id}/`

Mismo contrato parcial que creacion, con `expected_revision`.

#### `DELETE /api/scheduling/schedules/{schedule_id}/exceptions/{exception_id}/`

Permiso: `schedules.manage`. Respuesta `204`.

#### `POST /api/scheduling/schedules/{schedule_id}/assignments/`

Permiso: `schedules.manage`. Bloquea trial caducada.

Payload:

```json
{
  "expected_revision": 1,
  "scope_type": "SITE",
  "site_id": "uuid-site",
  "zone_id": null,
  "priority": 0,
  "is_locked": false,
  "starts_at": null,
  "ends_at": null
}
```

Scopes admitidos en Fase 3: `COMPANY`, `SITE`, `ZONE`. `ORGANIZATIONAL_UNIT` y `RESOURCE_GROUP` existen en modelo, pero no tienen UI completa en Fase 3.

Respuesta `201`: detalle de assignment.

#### `PATCH /api/scheduling/schedules/{schedule_id}/assignments/{assignment_id}/`

Permiso: `schedules.manage`.

Campos editables: `priority`, `is_locked`, `starts_at`, `ends_at`, `is_active`.

#### `DELETE /api/scheduling/schedules/{schedule_id}/assignments/{assignment_id}/`

Respuesta `200` con detalle de schedule. Se aplica baja logica (`is_active=false`) para conservar historial operativo.

#### `POST /api/scheduling/schedules/{schedule_id}/publish/`

Permiso: `schedules.manage`.

Payload:

```json
{
  "expected_revision": 1
}
```

Respuesta `200`:

```json
{
  "id": "uuid",
  "status": "PUBLISHED",
  "version": 2,
  "published_at": "2026-09-03T10:00:00Z"
}
```

No existe modelo de snapshot de schedule. Si Go necesita una version inmutable exacta en Fase 4, debe acordarse si basta con `Schedule.version` + manifiesto posterior o si hace falta un `ScheduleSnapshot`.

#### `POST /api/scheduling/schedules/{schedule_id}/archive/`

Permiso: `schedules.manage`. Bloquea trial caducada. Desactiva asignaciones activas y devuelve detalle de schedule con `status = ARCHIVED`.

#### `POST /api/scheduling/schedules/{schedule_id}/disable/`

Permiso: `schedules.manage`. Bloquea trial caducada. Desactiva asignaciones activas y devuelve detalle con `status = DISABLED`.

#### `POST /api/scheduling/schedules/{schedule_id}/reactivate/`

Permiso: `schedules.manage`. Bloquea trial caducada. Devuelve detalle con `status = DRAFT`.

#### `GET /api/scheduling/schedules/{schedule_id}/occurrences/`

Permiso: `schedules.view`. Lectura permitida con trial caducada.

Query params: `start_at`, `days` entre 1 y 90, `limit` entre 1 y 100.

Respuesta `200`:

```json
{
  "schedule_id": "uuid",
  "calculation_type": "configuration_preview",
  "execution_observed": false,
  "results": []
}
```

#### `GET /api/scheduling/schedules/resolve/`

Permiso: `schedules.view`. Lectura permitida con trial caducada.

Query params: `zone_id`, `at`.

Respuesta `200`:

```json
{
  "calculation_type": "configuration_preview",
  "execution_observed": false,
  "zone": {
    "id": "uuid-zone",
    "name": "Zona de cajas"
  },
  "at": "2026-09-07T08:45:00Z",
  "schedule": null,
  "assignment": null,
  "block": null,
  "exception": null,
  "content": {
    "content_type": "NONE",
    "playlist": null
  }
}
```

## 6. Errores implementados

| Codigo | HTTP | Uso |
| --- | --- | --- |
| `validation_error` | 400 | Payload invalido o constraints de campo |
| `catalog_song_not_found` | 404 | Cancion inexistente o no accesible por empresa |
| `playlist_not_found` | 404 | Playlist inexistente o fuera de empresa |
| `playlist_code_conflict` | 409 | Codigo duplicado en empresa |
| `playlist_limit_reached` | 403 | Limite de playlists del plan alcanzado |
| `playlist_revision_conflict` | 409 | La playlist cambio desde la revision esperada por el cliente |
| `playlist_content_unavailable` | 400 | Cancion no accesible o no disponible para la empresa |
| `playlist_item_not_found` | 404 | Elemento inexistente o ajeno a la playlist |
| `playlist_not_publishable` | 400 | Playlist vacia o con canciones no disponibles |
| `playlist_in_use` | 409 | Archivado bloqueado por usos reales en programacion |
| `playlist_order_conflict` | 409 | Reordenacion con elementos ausentes, ajenos o incompletos |
| `schedule_not_found` | 404 | Programacion inexistente o fuera de empresa |
| `schedule_block_not_found` | 404 | Bloque inexistente o ajeno a la programacion |
| `schedule_exception_not_found` | 404 | Excepcion inexistente o ajena a la programacion |
| `schedule_assignment_not_found` | 404 | Asignacion inexistente o ajena a la programacion |
| `schedule_revision_conflict` | 409 | La programacion cambio desde la revision esperada por el cliente |
| `schedule_conflict` | 409 | Solape con la misma prioridad en bloques, excepciones o asignaciones |
| `schedule_assignment_invalid` | 400 | Scope incoherente o recurso fuera de empresa |
| `schedule_content_unavailable` | 400 | Playlist inexistente, inaccesible o no publicada |
| `schedule_not_publishable` | 400 | Programacion sin bloques validos o con contenido no publicable |
| `permission_denied` | 403 | Rol/scope insuficiente |
| `functional_access_blocked` | 403 | Trial/plan sin acceso funcional |

## 7. Estados y transiciones

### AudioContent

- Cliente solo ve `READY`, `is_active=true`.
- `DRAFT`, `PROCESSING`, `ERROR`, `DISABLED`, `ARCHIVED` no aparecen en catalogo cliente.
- Publicacion/ingesta de audio queda fuera de Fase 3 cliente.

### Playlist

Transiciones recomendadas:

- Crear: `DRAFT`.
- Editar metadatos/items: permanece `DRAFT` o, si estaba `PUBLISHED`, crea cambios editables sobre la playlist actual sin alterar snapshots ya publicados.
- Publicar: `PUBLISHED`, incrementa `current_version`, crea `PlaylistSnapshot`.
- Archivar: `ARCHIVED`, no borra items ni snapshots.
- Reactivar: `DRAFT`, sujeto a limite de plan.
- `DISABLED` reservado para soporte/admin interno.

Decision pendiente: efecto exacto de editar una playlist publicada ya asignada a programaciones. Recomendacion tecnica: las programaciones visibles pueden apuntar a la playlist, pero ejecucion operativa debe consumir la ultima snapshot publicada; editar no cambia ejecucion hasta publicar de nuevo.

### Schedule

Transiciones recomendadas:

- Crear: `DRAFT`.
- Publicar: `PUBLISHED`, incrementa `version`.
- Desactivar: `DISABLED`.
- Archivar: `ARCHIVED`.

No hay snapshot inmutable de programacion. Para Fase 4 se debe decidir si los manifiestos congelan schedule/version o si se crea snapshot explicito.

## 8. Permisos y scopes

Permisos existentes reutilizables:

- `catalog.view`
- `playlists.view`
- `playlists.manage`
- `schedules.view`
- `schedules.manage`

Asignacion actual por rol oficial:

| Rol | Catalogo | Playlists | Programacion | Nota |
| --- | --- | --- | --- | --- |
| `OWNER` | ver | ver/gestionar | ver/gestionar | Control completo de empresa |
| `MANAGER` | ver | ver | ver | Actualmente no tiene `playlists.manage` ni `schedules.manage` |
| `EDITOR_PLAYLISTS` | ver | ver/gestionar | ver/gestionar | Rol natural para Fase 3 |
| `OPERADOR_SEDES` | no catalogo segun seed actual | no playlists | ver | Opera por scopes, sin gestion global |
| `VIEWER` | ver | ver | ver | Solo lectura |

La autorizacion debe usar `require_company_permission` y los scopes de `MembershipGrant`, no deducir permisos solo por nombre de rol en React.

Alcance recomendado:

- Catalogo: lectura por empresa actual; scope `COMPANY`.
- Playlists: propiedad de empresa; lectura/gestion segun scope `COMPANY` inicialmente. Si se desea editor por sede/zona, hace falta decision porque `Playlist` no pertenece a sede/zona.
- Programacion: `ScheduleAssignment` define alcance efectivo mediante `ResourceScope`. Fase 3 puede permitir asignar a `COMPANY`, `SITE` y `ZONE`.

Lectura con trial caducada:

- Catalogo y playlists: se bloquean como funciones de producto cuando no hay acceso funcional.
- Programacion: lectura permitida para consultar configuracion; mutaciones bloqueadas.

## 9. Limites del plan

Limites existentes relevantes:

| Plan | Playlists | Canales | Zonas | Sedes |
| --- | ---: | ---: | ---: | ---: |
| `BASIC` | 10 | 1 | 4 | 2 |
| `STANDARD` | 50 | 6 | 30 | 10 |
| `PREMIUM` | sin limite practico (`null`) | 25 | 150 | 50 |

Fase 3 debe aplicar:

- `playlists`: contar playlists de la empresa no archivadas.

Fase 3 no debe aplicar todavia:

- `channels`: pertenece a Fase 4.
- Limite de schedules: no existe clave de plan actual. No inventar uno sin decision.
- Limite de canciones: el catalogo lo gestiona BrandyManager; no cuenta contra cliente.

## 10. Politica de publicacion y versiones

Playlists:

- `publish_playlist` ya crea una `PlaylistSnapshot` con checksum calculado desde `song_id`, `position` y `weight`.
- Los dispositivos y Go deben consumir snapshots publicados, no la lista editable.
- Existe endpoint `POST /api/playlists/{playlist_id}/publish/`.
- Falta definir si snapshots anteriores pasan a `SUPERSEDED`.

Programacion:

- `Schedule.version` existe.
- `Schedule.revision` existe para control de concurrencia de edicion.
- No existe snapshot de programacion.
- `GET /api/scheduling/schedules/resolve/` calcula la configuracion aplicable para una zona e instante usando asignaciones publicadas, vigencia, excepciones, bloques, prioridad, especificidad y zona horaria IANA. Devuelve `execution_observed=false` porque no es telemetria de reproduccion.
- Para Fase 4, Django debe exponer a Go una configuracion publicada y versionada, idealmente mediante un endpoint interno autenticado o mediante manifiestos creados desde Django.

## 11. Dependencias aplazadas a Fase 4

- Gestion completa de canales.
- Politicas de canal (`ChannelPolicy`) como orden real, crossfade, loudness y fallback.
- Dispositivos y asignacion de configuracion a dispositivos.
- Streaming, preview audible y URLs de assets.
- Reproduccion efectiva y cola real.
- Telemetria, eventos de reproduccion y manifiestos.
- Resolucion operativa de programacion en tiempo real dentro de Go.
- Contenido de respaldo/fallback cuando no hay programacion.

## 12. Decisiones pendientes antes de implementar

1. Origen real del catalogo inicial: no hay canciones ni assets autorizados en seed de produccion. Se puede implementar API con estados vacios reales, pero para probar catalogo util hace falta una fuente autorizada o carga interna.
2. Subida de audio por clientes: los modelos lo soportan, pero AGENTS limita Fase 3 a catalogo gestionado por BrandyManager. Recomendacion: no permitir subida cliente.
3. Biblioteca privada de cliente: `owner_company` lo permite. Recomendacion: aplazar creacion privada hasta definir flujo de subida/aprobacion.
4. Disponibilidad/derechos: usar `visibility` + `ContentAccessGrant`, pero falta politica comercial de quien puede ver contenido `GLOBAL`.
5. Modos de playlist: no esta aprobado mapear `Aleatorio` o `Aleatorio sin repeticiones` a reglas de playback. Recomendacion: Fase 3 solo `MANUAL`; orden real en Fase 4 con `ChannelPolicy`.
6. Duracion minima de playlist: la constante frontend `3600` es aviso de UX, no regla de negocio aprobada.
7. Solapes avanzados de programacion: Fase 3 rechaza empates de misma prioridad y permite distintas prioridades; queda para producto si se quieren advertencias no bloqueantes o reglas por tipo de negocio.
8. Destinos de programacion: modelo permite scopes amplios. Recomendacion Fase 3: empresa, sede y zona; canal queda fuera.
9. Editar playlist publicada usada por programacion: decidir si ejecucion sigue usando snapshot anterior hasta republicar. Recomendacion: si.
10. Snapshot de programacion: si Go necesita reproducibilidad exacta antes de manifiestos, podria requerir modelo nuevo.
11. Semantica de `MANAGER` en Fase 3: seed actual le concede lectura de playlists/programaciones, no gestion. Si producto espera que MANAGER gestione Fase 3, hay que actualizar permisos de seed de forma explicita.

## 13. Fuente de audio autorizada

No se ha identificado una fuente de audio autorizada disponible en el repositorio. Las migraciones y seed inicial crean generos, categorias, permisos, roles y planes, pero no contenido musical productivo. Por tanto:

- No descargar musica arbitraria.
- No crear canciones ficticias en base persistente.
- Permitir catalogo vacio real.
- Usar factories/fixtures aisladas solo en tests automatizados.

## 14. Evidencia de inspeccion

- Backend Django registra `admin/`, `api/catalog/`, `api/onboarding/`, `api/organizations/`, `api/playlists/`, `api/scheduling/` y `api/users/` en `back_django/backend/config/urls.py`.
- `apps.catalog.models` define `Genre`, `TagCategory`, `Tag`, `AudioContent`, `Song`, `SongTag`, `AudioAsset`, `UploadSession` y `ProcessingJob`.
- `apps.playlists.models` define `Playlist`, `PlaylistItem`, `PlaylistSnapshot`, `PlaylistSnapshotItem`, `Channel`, `ChannelPolicy` y `ContentAccessGrant`.
- `apps.playlists.services.publish_playlist` existe y crea snapshots.
- `apps.scheduling.models` define `Schedule`, `ScheduleBlock`, `ScheduleException` y `ScheduleAssignment`; `Schedule.revision` se usa para concurrencia de edicion.
- `apps.scheduling.services.resolve_effective_schedule` conserva compatibilidad devolviendo la asignacion efectiva; la API nueva usa `resolve_effective_schedule_for_zone` para calcular bloque/excepcion/contenido sobre configuracion publicada.
- Frontend Fase 3 usa `mockApi` en `/app/catalogo`, `/app/playlists`, `/app/playlists/$playlistId` y `/app/programacion`.
- Frontend actual usa artista/album y mini player simulado en catalogo, incompatibles con el modelo de cancion IA sin artista/album.
- Go registra `GET /health`, `GET /api/system`, `GET /api/modules`, `GET /api/modules/{module}/status` y `POST /api/playback/commands`.
