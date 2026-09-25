# BrandyManager Fase 4 - Contrato v0.4

Fecha: 2026-09-07

Estado: contrato en implementacion con cuatro bloques implementados en
Django. Implementado y probado en estos bloques: API cliente de canales,
configuracion de playlists/politica de canal, publicacion de `ChannelSnapshot`,
asignacion historica `ZoneChannelAssignment`, `ScheduleSnapshot` en publicacion
de programacion, `ZoneOperationalSnapshot` al cambiar/publicar configuracion de
zona, y el dominio durable de dispositivos: asignacion historica, limites,
activacion por codigo de un uso, credenciales rotables, comandos durables y
sesion web del dispositivo, manifiestos ligados a snapshots, entrega autorizada
de audio WAV con HTTP Range, motor Go de cola determinista, continuidad finita,
telemetria durable y entrega/acuse de comandos. El reproductor React y su
activacion estan implementados. La validacion completa de compatibilidad real
de navegadores sigue pendiente.

Alcance: canales, asignacion zona-canal, dispositivos, activacion del
reproductor web, manifiestos, funcionamiento offline, control remoto y
telemetria. Las Fases 1, 2 y 3 se consideran contratos cerrados y no deben
reimplementarse.

Fuera de alcance: subida de audio por clientes, subida de cunas por clientes,
generacion de audio por IA, streaming continuo tipo radio publica,
sincronizacion exacta entre dispositivos, volumen fisico del sistema operativo,
encendido fisico, actualizaciones nativas y administracion interna avanzada.

## 1. Diagrama textual de componentes

```text
React panel (/app)
  -> Django API
     - identidad de usuario, roles, scopes y suscripcion
     - Company, Site, Zone
     - Channel, ChannelPolicy y asignacion Zone-Channel
     - Device durable, activacion y credenciales
     - catalogo, playlists publicadas, programacion publicada
     - snapshots operativos, manifiestos y auditoria
  -> Go API solo para estado operativo agregado cuando exista contrato interno

React player (/activar-dispositivo, /reproductor/:deviceId)
  -> Django API
     - validar/consumir codigo de activacion
     - emitir/renovar credencial del dispositivo
  -> Go API
     - descargar manifiesto/cola autorizada
     - reproducir assets autorizados
     - heartbeats, comandos, telemetria y eventos

Go
  -> Django API interna autenticada
     - validar tokens/credenciales de dispositivo
     - leer snapshot operativo inmutable
     - persistir eventos, comandos y estado durable mediante servicios Django

PostgreSQL
  - fuente durable de negocio y auditoria

Cache/memoria de Go
  - estado efimero, polling, colas de entrega y deduplicacion temporal
```

Regla base: Go no escribe tablas de Django directamente. Si necesita persistir
estado durable lo hace mediante endpoints internos autenticados de Django o una
capa de servicio explicitamente aprobada. `GO_AUTH_MODE=passthrough` solo es
modo local de desarrollo; no es seguridad final.

## 2. Estado real inspeccionado

### Ya existe

- `Channel`, `ChannelPlaylist`, `ChannelPolicy` y `ContentAccessGrant` en
  `apps.playlists.models`.
- `Device`, `DeviceZoneAssignment`, `DeviceCredential`, `DeviceCommand`,
  `DeviceEvent`, `DeviceState`, `DeviceSync` y `DeviceCachedAsset` en
  `apps.devices.models`.
- `PlaybackPolicy`, `PlaybackPolicyAssignment`, `ContentManifest`,
  `ContentManifestItem`, `PlaybackSession` y `PlaybackEvent` en
  `apps.playback.models`.
- `Schedule.version` y `Schedule.revision`, pero no snapshot inmutable de
  programacion.
- `PlaylistSnapshot` y `PlaylistSnapshotItem` inmutables.
- Permisos semilla para `channels.view`, `channels.select`,
  `channels.manage`, `devices.view`, `devices.manage`, `playback.view`,
  `playback.control` y `playback.volume`.
- Go registra health, metadatos operativos y los endpoints `/api/player/*`.
  La antigua cola en memoria `POST /api/playback/commands` ya no se expone.

### Insuficiente para Fase 4

- Ya existen endpoints Django cliente para canales.
- No hay endpoints Django cliente para dispositivos.
- No hay modelo ni endpoint de codigo de activacion.
- `DeviceCredential` existe, pero no hay flujo de emision, rotacion,
  revocacion o autenticacion del player.
- `DeviceCommand` existe, pero el endpoint Go actual solo devuelve un comando
  aceptado en memoria y no valida permisos, empresa, dispositivo ni scopes.
- Existe `ZoneChannelAssignment` historico con una asignacion activa por zona.
- `Channel` tiene `revision` y `current_version`.
- Existe `ChannelSnapshot` inmutable.
- Existe `ScheduleSnapshot` inmutable creado al publicar programaciones.
- `ZoneOperationalSnapshot` existe y congela la configuracion publicada de zona.
- `ContentManifest` queda ligado al `ZoneOperationalSnapshot` que lo genero.
- Go expone la URL de audio y Django valida dispositivo, manifiesto y asset en
  cada descarga, con soporte HTTP Range.
- No hay telemetria real desde el player.

### Frontend actual que debe sustituirse

Las rutas `/app/canales`, `/app/canales/$channelId`,
`/app/dispositivos`, `/app/dispositivos/$deviceId` y
`/reproductor/$deviceId` usan `mockApi`, tipos de `src/lib/mock/models.ts`,
IDs fijos, endpoints `stream://...`, logs simulados, estados de reproduccion
inventados y progreso mediante temporizador. Deben desaparecer al integrar la
Fase 4. El dashboard ya distingue que reproduccion, canales y dispositivos son
Fase 4 y no muestra telemetria como real.

## 3. Modelos reutilizados y carencias

| Dominio | Reutilizar | Carencia |
| --- | --- | --- |
| Canales | `Channel`, `ChannelPlaylist`, `ChannelPolicy` | `revision`, `current_version`, snapshot publicado, serializers/endpoints |
| Zona-canal | `Zone`, `Channel` | falta asignacion historica `ZoneChannelAssignment` |
| Dispositivos | `Device`, `DeviceZoneAssignment`, `DeviceCredential`, `DeviceState` | activacion, limites, endpoints, credenciales de player |
| Comandos | `DeviceCommand` | idempotencia por cliente, entrega/ack, enlace Go-Django |
| Manifiestos | `ContentManifest`, `ContentManifestItem` | relacion con snapshot operativo, expiracion offline, URLs autorizadas |
| Reproduccion | `PlaybackSession`, `PlaybackEvent` | endpoints Go/player y persistencia via Django |
| Programacion | `Schedule`, `ScheduleBlock`, `ScheduleException`, `ScheduleAssignment` | snapshot inmutable de programacion |
| Playlists | `PlaylistSnapshot`, `PlaylistSnapshotItem` | definir que Go consume solo snapshots publicados |

## 4. Estados y transiciones

### Channel

Estados actuales: `DRAFT`, `PUBLISHED`, `DISABLED`, `ARCHIVED`.

Transiciones propuestas:

- crear -> `DRAFT`
- editar metadatos/politica/composicion -> incrementa `revision`
- publicar -> crea `ChannelSnapshot`, pasa a `PUBLISHED`
- desactivar -> `DISABLED`; no elimina asignaciones historicas
- archivar -> `ARCHIVED`; bloqueado si hay asignacion activa a zonas salvo
  desasignacion transaccional explicita
- reactivar -> `DRAFT`

`PUBLISHED` significa disponible para configuracion operativa. No significa
"sonando".

### ZoneChannelAssignment

Modelo implementado, historico:

- `company`, `zone`, `channel`, `assigned_by`, `assigned_at`,
  `unassigned_by`, `unassigned_at`, `reason`, `created_at`
- restriccion parcial: una asignacion activa por zona
- validacion: `zone.company == company` y canal global o de la misma empresa

Cambiar el canal de una zona cierra la asignacion activa anterior, crea una
nueva y genera un nuevo `ZoneOperationalSnapshot`.

### Device

El modelo conserva el estado tecnico historico (`PROVISIONING`, `ONLINE`,
`OFFLINE`, `MAINTENANCE`, `DISABLED`, `REVOKED`) y separa persistentemente:

- Estado administrativo: `ACTIVE`, `SUSPENDED`, `ARCHIVED`.
- Activacion: `PENDING`, `ACTIVATED`, `REVOKED`.
- Conectividad: `UNKNOWN`, `ONLINE`, `OFFLINE`.
- Reproduccion: `DeviceState.playback_status`, que seguira siendo telemetria
  informada por el motor y no se infiere desde React.

Transiciones propuestas:

- crear desde panel -> `PROVISIONING`
- activar con codigo valido -> `ONLINE` si hay primer heartbeat inmediato, o
  `OFFLINE` con `activated_at` hasta heartbeat
- heartbeat reciente -> `ONLINE`
- sin heartbeat pasado el umbral acordado -> `OFFLINE`
- mantenimiento -> `MAINTENANCE`
- desactivar -> `DISABLED`
- revocar -> `REVOKED`, revoca credenciales, impide descargas y comandos

El `device_id` nunca es una credencial.

### DeviceCredential

Estados actuales: `ACTIVE`, `EXPIRED`, `REVOKED`.

Reglas:

- secreto raw visible una sola vez o guardado en cookie HttpOnly del navegador
  player
- solo se guarda `secret_hash`
- rotacion crea nueva credencial y enlaza `rotated_from`
- revocacion invalida refresh del dispositivo y access tokens futuros

Implementado: `DeviceActivation` guarda exclusivamente `code_hash` HMAC-SHA256,
caducidad de 15 minutos configurable, intentos/metadatos de intento y consumo o
revocacion. Generar un codigo nuevo revoca los anteriores. `DeviceCredential`
guarda `credential_id` y `secret_hash`; el secreto raw solo viaja dentro de la
cookie HttpOnly `bm_device_refresh` con path `/api/player/`. El access JWT de
dispositivo dura cinco minutos por defecto, tiene audience
`brandymanager-device` y no es aceptado como JWT de usuario.

### DeviceCommand

Estados actuales: `PENDING`, `DELIVERED`, `ACKNOWLEDGED`, `EXECUTED`,
`FAILED`, `EXPIRED`, `CANCELLED`.

Reglas:

- UUID del comando como idempotency key
- creacion durable en Django
- entrega y ack gestionados por Go/player
- resultado persistido via Django

### ContentManifest

Estados actuales: `GENERATING`, `READY`, `SUPERSEDED`, `ERROR`.

Reglas:

- version unico por zona
- `READY` contiene solo assets autorizados y disponibles
- `expires_at` define caducidad online/offline
- `SUPERSEDED` conserva historico
- debe apuntar al snapshot operativo que lo genero

## 5. Snapshot operativo inmutable

Requisito bloqueante para Fase 4: Go no debe consumir `Schedule`, `Channel` o
`Playlist` editables directamente.

Implementacion actual:

1. `ScheduleSnapshot`
   - congela `Schedule.version`, bloques, excepciones y asignaciones publicadas
   - se crea en `publish_schedule`
   - los cambios posteriores en `Schedule` no alteran el snapshot
   - se guarda como `snapshot_data` JSON inmutable, con identificadores de
     bloques, excepciones, asignaciones, playlists/canales y snapshots
     publicados aplicables

2. `ChannelSnapshot`
   - congela `Channel.current_version`, `ChannelPolicy` y las
     `ChannelPlaylist`
   - referencia `PlaylistSnapshot`, no `Playlist`
   - se crea en `publish_channel`

3. `ZoneOperationalSnapshot`
   - congela la configuracion efectiva de una zona
   - referencia `zone`, `channel_snapshot`, `schedule_snapshot` aplicable,
     assets primarios disponibles y checksums
   - estados implementados: `READY`, `SUPERSEDED`, `ERROR`
   - version unico por zona
   - `execution_observed` siempre es `false` en este bloque: es configuracion,
     no telemetria de reproduccion

4. `ContentManifest`
   - referencia el `ZoneOperationalSnapshot` que lo genero
   - contiene los `AudioAsset` concretos descargables/reproducibles

Go consumira `ZoneOperationalSnapshot` y `ContentManifest READY`, no borradores.
El snapshot operativo y su union directa con `ContentManifest` ya existen. La
cola operativa selecciona el item actual y los siguientes usando exclusivamente
las referencias congeladas del snapshot.

## 6. Resolucion operativa

La resolucion de Go parte del snapshot publicado y del manifiesto vigente.

| Caso | Resultado propuesto |
| --- | --- |
| No existe canal asignado a la zona | player muestra `NO_CHANNEL_ASSIGNED`; no reproduce audio |
| No existe programacion activa | `NO_SCHEDULE_CONTENT`; no se inventa fallback |
| Playlist vacia | no publicable; no llega al manifiesto |
| Asset no disponible | se excluye; si deja cola vacia, manifiesto `ERROR` o item rechazado |
| Termina una pista | Go selecciona siguiente item segun `ChannelPolicy` congelada |
| Cambia programacion durante una pista | se aplica al solicitar el siguiente item; la pista actual no se interrumpe |
| Cambia canal de zona | se genera snapshot/manifiesto nuevo y comando `REFRESH_CONFIGURATION` |
| Dispositivo revocado | no refresh, no manifiesto, no audio online, telemetria solo de cierre si se permite |

Contenido de respaldo: no se define playlist fallback hasta decision expresa de
producto. Si no hay contenido aplicable, el resultado real es silencio/no
content.

## 7. Flujos

### Crear y publicar canal

1. React panel llama a Django `POST /api/channels/`.
2. Django valida usuario, `channels.manage`, acceso funcional y limite
   `channels`.
3. React anade playlists publicadas al canal.
4. Django valida que cada playlist es accesible y tiene snapshot publicado.
5. React publica el canal.
6. Django crea `ChannelSnapshot` inmutable.

### Asignar canal a zona

1. React panel llama a Django `PUT /api/channels/zone-assignments/{zone_id}/`.
2. Django valida `channels.select` sobre scope de la zona, canal accesible y
   zona no archivada.
3. Django cierra asignacion activa anterior y crea la nueva.
4. Django genera un `ZoneOperationalSnapshot` nuevo.
5. Los dispositivos reciben la nueva version al renovar manifiesto; el panel
   puede emitir `FORCE_SYNC` cuando necesite adelantar esa renovacion.

### Crear y activar dispositivo web

1. OWNER o MANAGER crea dispositivo en Django asignado a una zona.
2. Django crea `Device` y `DeviceZoneAssignment`, valida limite `devices` y
   genera un codigo temporal de un solo uso.
3. El navegador abre `/activar-dispositivo`.
4. El usuario introduce el codigo.
5. React player llama a Django para consumir el codigo.
6. Django valida hash, caducidad, intentos, empresa/zona y consume el codigo.
7. Django crea/rota `DeviceCredential`, setea cookie HttpOnly de refresh del
   dispositivo y devuelve un access token corto de dispositivo en JSON.
8. React abre `/reproductor/{device.id}`.
9. El player llama a Go con access token de dispositivo.
10. Go valida el token contra Django y entrega manifiesto/cola.

### Reproduccion web

1. El usuario pulsa "Iniciar reproduccion" por politica de autoplay.
2. El player obtiene manifiesto vigente de Go.
3. Go resuelve/lee snapshot operativo y devuelve cola real.
4. El player descarga assets con autorizacion; no usa tokens en URL.
5. El player envia heartbeats y eventos.
6. Go persiste estado durable llamando a Django.

### Offline

1. El player cachea solo assets proximos y obligatorios del manifiesto vigente.
2. El manifiesto incluye `offline_authorized_until`.
3. Si se pierde red, el player continua con contenido cacheado hasta caducidad.
4. Los eventos pendientes se guardan localmente en IndexedDB y se reenvian al
   recuperar conexion.
5. Si caduca la autorizacion offline, el player deja de reproducir y muestra
   bloqueo controlado.

## 8. Matriz endpoint, propietario y auth

### Django - panel de gestion

| Metodo | Ruta | Auth | Permiso | Estado |
| --- | --- | --- | --- | --- |
| GET | `/api/channels/` | User JWT | `channels.view` | Implementado |
| POST | `/api/channels/` | User JWT | `channels.manage` | Implementado |
| GET | `/api/channels/{channel_id}/` | User JWT | `channels.view` | Implementado |
| PATCH | `/api/channels/{channel_id}/` | User JWT | `channels.manage` | Implementado |
| PATCH | `/api/channels/{channel_id}/policy/` | User JWT | `channels.manage` | Implementado |
| PUT | `/api/channels/{channel_id}/playlists/` | User JWT | `channels.manage` | Implementado |
| POST | `/api/channels/{channel_id}/duplicate/` | User JWT | `channels.manage` | Implementado |
| POST | `/api/channels/{channel_id}/publish/` | User JWT | `channels.manage` | Implementado |
| GET | `/api/channels/{channel_id}/published-configuration/` | User JWT | `channels.view` | Implementado |
| GET | `/api/channels/{channel_id}/zones/` | User JWT | `channels.view` | Implementado |
| POST | `/api/channels/{channel_id}/archive/` | User JWT | `channels.manage` | Implementado |
| POST | `/api/channels/{channel_id}/reactivate/` | User JWT | `channels.manage` | Implementado |
| GET | `/api/channels/zone-assignments/{zone_id}/` | User JWT | `channels.view` | Implementado |
| PUT | `/api/channels/zone-assignments/{zone_id}/` | User JWT | `channels.select` | Implementado |
| DELETE | `/api/channels/zone-assignments/{zone_id}/` | User JWT | `channels.select` | Implementado |
| GET | `/api/devices/` | User JWT | `devices.view` | Implementado |
| POST | `/api/devices/` | User JWT | `devices.manage` | Implementado |
| GET | `/api/devices/{device_id}/` | User JWT | `devices.view` | Implementado |
| PATCH | `/api/devices/{device_id}/` | User JWT | `devices.manage` | Implementado |
| POST | `/api/devices/{device_id}/zone/` | User JWT | `devices.manage` en ambas zonas | Implementado |
| POST | `/api/devices/{device_id}/activation-codes/` | User JWT | `devices.manage` | Implementado |
| POST | `/api/devices/{device_id}/suspend/` | User JWT | `devices.manage` | Implementado |
| POST | `/api/devices/{device_id}/reactivate/` | User JWT | `devices.manage` | Implementado |
| POST | `/api/devices/{device_id}/archive/` | User JWT | `devices.manage` | Implementado |
| POST | `/api/devices/{device_id}/revoke/` | User JWT | `devices.manage` | Implementado |
| POST | `/api/devices/{device_id}/commands/` | User JWT | `playback.control`/`playback.volume` | Implementado |
| POST | `/api/catalog/internal/songs/` | User JWT | PlatformRole con `platform.content.manage` | Implementado |

### Django - activacion/player

| Metodo | Ruta | Auth | Uso | Estado |
| --- | --- | --- | --- | --- |
| POST | `/api/player/activation/validate/` | Publico + rate limit | validar codigo sin consumir | Implementado |
| POST | `/api/player/activation/complete/` | Publico + rate limit | consumir codigo y emitir credencial | Implementado |
| POST | `/api/player/token/refresh/` | Cookie device refresh | renovar access corto | Implementado |
| POST | `/api/player/logout/` | Cookie device refresh | borrar cookie y revocar sesion | Implementado |
| GET | `/api/player/session/` | Device access JWT | verificar aislamiento de sesion player | Implementado |

### Django - interno para Go

| Metodo | Ruta | Auth | Uso | Estado |
| --- | --- | --- | --- | --- |
| POST | `/api/internal/player-token/introspect/` | `X-BrandyManager-Service-Token` | validar access/credencial de dispositivo | Implementado |
| GET | `/api/internal/audio/assets/{asset_id}/stream/` | Device access + service token | autorizar manifiesto y servir bytes a Go | Implementado |
| GET | `/api/internal/player/runtime/` | Device access + service token | identidad, snapshot, manifiesto y assets en una lectura | Implementado |
| POST | `/api/internal/player/runtime/` | Device access + service token | regenerar manifiesto para el snapshot publicado | Implementado |
| POST | `/api/internal/player/telemetry/` | Device access + service token | persistir lote idempotente y `DeviceState` | Implementado |
| POST | `/api/internal/playback/sessions/` | Service token Go | abrir/cerrar sesion | Propuesto |
| POST | `/api/internal/playback/events/` | Service token Go | registrar eventos de reproduccion | Propuesto |
| GET | `/api/internal/player/commands/` | Device access + service token | entregar comandos pendientes ordenados | Implementado |
| POST | `/api/internal/player/commands/{command_id}/ack/` | Device access + service token | ack/ejecutar/fallar de forma idempotente | Implementado |

### Go - player operativo

| Metodo | Ruta | Auth | Uso | Estado |
| --- | --- | --- | --- | --- |
| GET | `/health` | Publico | health | Existente |
| GET | `/api/modules` | User JWT actual | modulos | Existente |
| POST | `/api/playback/commands` | N/A | cola historica en memoria | Eliminado; los comandos se crean en Django |
| GET | `/api/player/manifest/current` | Device access introspectado | manifiesto y cola vigente | Implementado |
| POST | `/api/player/manifest/refresh` | Device access introspectado | renovar manifiesto sobre publicacion vigente | Implementado |
| GET | `/api/player/queue/current` | Device access introspectado | pista actual/siguientes calculadas | Implementado |
| POST | `/api/player/heartbeat` | Device access introspectado | lote heartbeat con el contrato de telemetria | Implementado |
| GET | `/api/player/commands` | Device access introspectado | comandos pendientes | Implementado |
| POST | `/api/player/commands/{command_id}/ack` | Device access introspectado | ack/resultado | Implementado |
| POST | `/api/player/telemetry` | Device access introspectado | eventos idempotentes en lote | Implementado |
| GET | `/api/player/audio/assets/{asset_id}/stream/` | Device access Bearer | proxy autorizado con HTTP Range | Implementado |

## 9. Contratos JSON propuestos

### Channel detail

```json
{
  "id": "uuid",
  "name": "Canal tienda",
  "code": "CANAL-TIENDA",
  "description": "",
  "visibility": "PRIVATE",
  "status": "PUBLISHED",
  "current_version": 3,
  "revision": 7,
  "policy": {
    "order_mode": "SHUFFLE",
    "repeat_song_gap_count": 10,
    "max_same_genre_in_row": 3,
    "avoid_same_tag_in_row": true,
    "crossfade_ms": 0,
    "fade_in_ms": 0,
    "fade_out_ms": 0,
    "normalize_loudness": true,
    "target_lufs": null
  },
  "playlists": [
    {
      "id": "uuid-channel-playlist",
      "playlist": {
        "id": "uuid-playlist",
        "name": "Retail manana",
        "status": "PUBLISHED",
        "current_version": 2,
        "published_snapshot_id": "uuid-snapshot"
      },
      "weight": 1,
      "priority": 0,
      "active_from": null,
      "active_until": null
    }
  ],
  "usage": {
    "zones": 2,
    "devices": 3
  },
  "permissions": {
    "can_view": true,
    "can_update": true,
    "can_publish": true,
    "can_archive": true,
    "can_assign_to_zone": true
  },
  "created_at": "2026-09-04T10:00:00Z",
  "updated_at": "2026-09-04T10:00:00Z"
}
```

### Zone channel assignment

```json
{
  "zone": {
    "id": "uuid-zone",
    "name": "Zona de cajas"
  },
  "channel": {
    "id": "uuid-channel",
    "name": "Canal tienda",
    "current_version": 3
  },
  "assigned_at": "2026-09-04T10:05:00Z",
  "configuration_status": "PENDING_REGENERATION"
}
```

### Device detail

```json
{
  "id": "uuid",
  "code": "CAJAS-PLAYER-01",
  "name": "Reproductor cajas 01",
  "device_type": "DESKTOP_APP",
  "status": "ONLINE",
  "site": {
    "id": "uuid-site",
    "name": "Mercadona Valencia"
  },
  "zone": {
    "id": "uuid-zone",
    "name": "Zona de cajas"
  },
  "channel": {
    "id": "uuid-channel",
    "name": "Canal tienda"
  },
  "state": {
    "playback_status": "PLAYING",
    "current_audio_content": {
      "id": "uuid-audio",
      "title": "Tema IA"
    },
    "current_playlist": {
      "id": "uuid-playlist",
      "name": "Retail manana"
    },
    "position_ms": 34000,
    "volume": 60,
    "is_online": true,
    "last_heartbeat_at": "2026-09-04T10:06:00Z",
    "manifest_version": 5,
    "schedule_version": 2
  },
  "last_seen_at": "2026-09-04T10:06:00Z",
  "last_sync_at": "2026-09-04T10:04:00Z",
  "permissions": {
    "can_view": true,
    "can_update": true,
    "can_disable": true,
    "can_revoke": true,
    "can_send_commands": true,
    "can_change_volume": true
  },
  "created_at": "2026-09-04T09:50:00Z",
  "updated_at": "2026-09-04T10:06:00Z"
}
```

Los campos de `state` pueden ser `null` cuando no exista telemetria real.

### Activation complete

Payload:

```json
{
  "code": "ABCD-1234-K9",
  "device_name": "Chrome kiosko cajas",
  "user_agent": "Mozilla/5.0...",
  "app_version": "web-player/1.0.0"
}
```

Respuesta `200`:

```json
{
  "device_access": "jwt-corto",
  "expires_in": 300,
  "device": {
    "id": "uuid-device",
    "code": "CAJAS-PLAYER-01",
    "name": "Reproductor cajas 01",
    "status": "ONLINE"
  },
  "zone": {
    "id": "uuid-zone",
    "name": "Zona de cajas"
  },
  "next_step": "PLAYER"
}
```

Cookie: `bm_device_refresh`, HttpOnly, Secure en produccion, SameSite=Lax,
Path restringido a rutas de player si es viable. El refresh raw nunca aparece
en JSON ni en `localStorage`.

### Go manifest current

```json
{
  "manifest": {
    "id": "uuid-manifest",
    "zone_id": "uuid-zone",
    "version": 5,
    "status": "READY",
    "generated_at": "2026-09-04T10:04:00Z",
    "valid_from": "2026-09-04T10:04:00Z",
    "expires_at": "2026-09-05T10:04:00Z",
    "offline_authorized_until": "2026-09-05T10:04:00Z",
    "checksum": "sha256",
    "total_size_bytes": 1234567
  },
  "configuration": {
    "operational_snapshot_id": "uuid-operational-snapshot",
    "channel_snapshot_id": "uuid-channel-snapshot",
    "schedule_snapshot_id": "uuid-schedule-snapshot",
    "execution_observed": false
  },
  "items": [
    {
      "audio_asset_id": "uuid-asset",
      "audio_content_id": "uuid-content",
      "title": "Tema IA",
      "duration_ms": 180000,
      "checksum_sha256": "64hex",
      "size_bytes": 1234567,
      "mime_type": "audio/mpeg",
      "stream_url": "/api/player/audio/assets/uuid-asset/stream/",
      "is_required": true,
      "reason": "PLAYLIST"
    }
  ]
}
```

`stream_url` no contiene secretos. La autorizacion viaja por cookie HttpOnly de
dispositivo o por `Authorization` cuando se use `fetch` controlado por el
player. El endpoint de audio debe soportar `Range`, MIME correcto y CORS con
credenciales.

### Heartbeat

```json
{
  "device_id": "uuid-device",
  "manifest_version": 5,
  "playback_status": "PLAYING",
  "position_ms": 34000,
  "volume": 60,
  "current_audio_content_id": "uuid-content",
  "current_playlist_id": "uuid-playlist",
  "current_channel_id": "uuid-channel",
  "network": {
    "online": true,
    "rtt_ms": 42
  },
  "storage": {
    "total_bytes": 1000000000,
    "free_bytes": 400000000
  },
  "occurred_at": "2026-09-04T10:06:00Z"
}
```

Respuesta:

```json
{
  "status": "accepted",
  "server_time": "2026-09-04T10:06:01Z",
  "online": true,
  "configuration": {
    "refresh_required": false,
    "latest_manifest_version": 5
  }
}
```

### Remote command

Payload panel -> Django:

```json
{
  "command_type": "SET_VOLUME",
  "payload": {
    "volume": 55
  },
  "idempotency_key": "uuid"
}
```

Respuesta:

```json
{
  "id": "uuid-command",
  "device_id": "uuid-device",
  "command_type": "SET_VOLUME",
  "status": "PENDING",
  "created_at": "2026-09-04T10:07:00Z",
  "expires_at": "2026-09-04T10:12:00Z"
}
```

## 10. Seguridad

### Contrato operativo implementado en Go (v0.4)

Las respuestas publicas de Go usan `{ "data": ... }`. El manifiesto contiene
`manifest_id`, `device_id`, `zone_id`, `channel_id`, `configuration_version`,
`published_version`, `generated_at`, `valid_until`, `server_time`,
`playback_policy`, `current`, `next`, `continuation_token`, `reason`,
`execution_observed=false`, `offline` y `source`. Cada item contiene
`asset_id`, `audio_content_id`, `title`, `duration_ms`, `mime_type`, `url`,
`etag`, `size_bytes`, `offline_cacheable`, `playlist_snapshot_id` y
`snapshot_item_id`.

`continuation_token` es opaco y esta firmado con HMAC-SHA256. Congela el ID de
manifiesto, version, siguiente indice y caducidad; un indice enviado libremente
por el navegador nunca se acepta. La cola excluye duraciones desconocidas y
assets ausentes del manifiesto autorizado. No existe fallback: se devuelve
`NO_CHANNEL_ASSIGNED`, `NO_PUBLISHED_CONFIGURATION`, `NO_SCHEDULE_CONTENT`,
`SCHEDULED_SILENCE`, `NO_AVAILABLE_ASSETS` o `INVALID_SCHEDULE_TIMEZONE`.

La resolucion usa la zona IANA congelada en `ScheduleSnapshot`, fechas de
vigencia inclusivas y bloques locales `[start, end)`. Los intervalos nocturnos
siguen rechazados por Django y deben dividirse en dos. Las excepciones ordenadas
por prioridad se aplican antes que los bloques. Los empates ya son rechazados al
publicar; el ID actua solo como desempate defensivo y determinista.

`SEQUENTIAL` conserva prioridad/posicion. `SHUFFLE` usa un orden determinista
derivado del checksum publicado y la fecha local. `WEIGHTED` utiliza el mismo
orden estable con puntuacion ponderada por los pesos congelados de playlist e
item. Renovar con el mismo cursor no vuelve a empezar la cola.

Al publicar una programacion, Django regenera atomicamente los snapshots de las
zonas para las que pasa a ser efectiva. En cada renovacion, Django tambien
detecta inicio/fin de vigencias o una version publicada posterior y genera un
snapshot operativo nuevo; este rollover nunca lee un borrador.

La cache Go solo reutiliza un `Runtime` publicado si Django falla y
`manifest.valid_until` continua vigente. Nunca amplia esa fecha. Cada llamada
interna Django vuelve a validar JWT, credencial y estado del dispositivo, de
modo que la cache de introspeccion (10 segundos por defecto) no autoriza una
operacion durable ni una descarga tras la revocacion.

Telemetria: `POST /api/player/telemetry` y `/heartbeat` reciben entre 1 y 100
eventos, maximo 256 KiB. Cada evento requiere `event_id`, `sequence`,
`occurred_at` y `event_type`; admite referencias opcionales al manifiesto y
asset, posicion, estado, volumen, error y metadatos tecnicos acotados. Django
infiere dispositivo y empresa del token, valida referencias, deduplica por
`(device,event_id)` y solo actualiza `DeviceState` si la secuencia es posterior.
Se aceptan eventos retrasados durante 24 horas y hasta 5 minutos futuros.

Comandos implementados para el contrato de cliente: `SET_VOLUME`, `MUTE`,
`UNMUTE`, `RESTART_PLAYBACK`, `FORCE_SYNC`, `ENABLE` y `DISABLE`. Django los
persiste, Go los entrega por `created_at,id`, expira los vencidos y acepta los
estados `ACKNOWLEDGED`, `EXECUTED` y `FAILED`. El player debe aplicar en orden y
no aplicar un comando con `issued_at` anterior al ultimo comando de la misma
familia que ya haya ejecutado.

### Ingesta interna y entrega de audio

- `POST /api/catalog/internal/songs/` acepta `multipart/form-data` solamente
  para usuarios con un `UserPlatformRole` activo que incluya
  `platform.content.manage`. `is_staff` o un `CompanyRole` no conceden acceso.
- Campos obligatorios: `file`, `title`, `internal_code`, `genre_id`,
  `rights_holder` y `rights_reference`. `description`, `tag_ids`,
  `is_explicit` y referencias de generacion son opcionales.
- En esta entrega la lista cerrada admite exclusivamente WAV PCM real. Se
  validan cabecera, estructura, MIME declarado, tamano, duracion, sample rate,
  canales y SHA-256 antes de marcar el asset y contenido como `READY`.
- El checksum de un original `READY` es unico. Un fallo transaccional elimina
  el objeto de almacenamiento creado y nunca publica contenido parcial.
- No existen endpoints cliente para cargar canciones, cunas o mensajes. La
  generacion de mensajes por IA permanece fuera de Fase 4.
- El stream publico de Go reenvia el Bearer de dispositivo y un secreto de
  servicio al endpoint interno Django. Django vuelve a validar audiencia,
  credencial, estado del dispositivo, zona, manifiesto vigente y asset.
- La autorizacion offline expira con `ContentManifest.expires_at`; una respuesta
  cacheada no amplia esa vigencia. El cache maximo HTTP es configurable y nunca
  supera la caducidad del manifiesto.
- La entrega autenticada reduce exposicion accidental, pero no es DRM: un
  operador con acceso legitimo al navegador puede extraer los bytes recibidos.

- Codigos de activacion: aleatorios, normalizados, de 10 a 12 caracteres
  legibles, caducidad recomendada de 15 minutos, maximo 5 intentos, hash
  HMAC-SHA256 con secreto de aplicacion, consumo unico y revocacion de codigos
  anteriores del mismo dispositivo.
- No guardar codigos ni secretos raw.
- No poner tokens en URL. La URL `/reproductor/{deviceId}` solo identifica el
  dispositivo; no autentica.
- Device refresh en cookie HttpOnly; device access corto en memoria.
- React panel nunca recibe secretos de dispositivo salvo el codigo de
  activacion raw en el momento de generarlo.
- Go valida tokens de dispositivo con Django mediante introspeccion interna o
  clave publica dedicada. No usar `GO_AUTH_MODE=passthrough` fuera de local.
- Endpoints internos Django-Go protegidos con `SERVICE_TOKEN` o mTLS en una
  fase posterior de infraestructura.
- UUID conocido no concede acceso a canal, dispositivo, asset o manifiesto.
- Dispositivo revocado no puede refrescar token, pedir manifiesto, descargar
  audio ni recibir comandos.
- Todos los eventos sensibles generan auditoria: activacion, rotacion,
  revocacion, cambio de canal, comandos y cambios de politica.

## 11. Reproduccion web

- Autoplay: el player debe mostrar un boton inicial "Iniciar reproduccion".
- Fullscreen: requiere gesto del usuario; no se puede prometer apertura
  automatica.
- `AudioContext` puede iniciar suspendido y debe reanudarse con gesto.
- Refresh de pagina: usar cookie de dispositivo para recuperar access; si no
  existe o esta revocada, volver a activacion.
- Cambio de pista: controlado por Go segun cola/manifiesto.
- Precarga: solo siguiente contenido autorizado.
- Audio: endpoint Go con `Range`, `Content-Type`, `Accept-Ranges`,
  `Content-Length` y CORS.
- Si expira la autorizacion mientras suena una pista, permitir terminar el
  fragmento ya descargado, pero exigir renovacion para nuevas descargas.
- Segundo plano/bloqueo de pantalla: navegadores pueden limitar temporizadores;
  heartbeats deben tolerar retrasos.
- Safari/iOS: no declarar compatibilidad completa hasta pruebas especificas.
- PWA/Service Worker: recomendado para offline, pero debe auditar cookies,
  cache y expiracion antes de activar en produccion.

## 12. Offline

- No descargar catalogo completo.
- Descargar solo items proximos del manifiesto vigente.
- `offline_authorized_until` = minimo entre `manifest.expires_at` y ventana de
  politica offline aprobada.
- Cache API guarda respuestas de audio; IndexedDB guarda cola local,
  checksums y telemetria pendiente.
- Antes de reproducir offline se valida checksum y vigencia.
- Al recuperar conexion, enviar eventos pendientes con idempotency keys.
- Si un asset se borra/revoca en servidor, no hay nuevas descargas; contenido
  ya cacheado deja de estar autorizado al expirar la ventana offline.

## 13. Online/offline y heartbeats

- Heartbeat normal cada 30 segundos mientras el player esta activo.
- Dispositivo `OFFLINE` si no hay heartbeat aceptado en 90 segundos.
- Estado online del panel derivado de `DeviceState.last_heartbeat_at`, no de
  un estado calculado en React.

## 14. Permisos y scopes

Matriz derivada del seed actual:

| Rol | Canales | Dispositivos | Playback |
| --- | --- | --- | --- |
| OWNER | ver/gestionar/asignar | ver/gestionar | ver/control/volumen |
| MANAGER | ver/gestionar/asignar | ver/gestionar | ver/control/volumen |
| EDITOR_PLAYLISTS | ver | no gestiona | sin control |
| OPERADOR_SEDES | ver/asignar canal segun scope | ver segun scope | control/volumen segun scope |
| VIEWER | ver | ver | ver |

Reglas:

- Backend es autoridad; React solo oculta botones.
- Scope `COMPANY` permite toda la empresa.
- Scope `SITE` permite zonas/dispositivos de esa sede.
- Scope `ZONE` permite esa zona y sus dispositivos.
- Crear/editar dispositivos requiere `devices.manage`.
- Enviar comandos requiere `playback.control`; volumen requiere
  `playback.volume`.
- Cambiar canal de zona requiere `channels.select` sobre la zona.
- Mutaciones funcionales bloqueadas con trial caducada.

## 15. Versionado de configuracion

- `PlaylistSnapshot`: ya existe y debe seguir siendo la unidad consumible de
  canciones.
- `ChannelSnapshot`: nuevo, congela combinacion de playlists publicadas y
  politica de canal.
- `ScheduleSnapshot`: nuevo, congela programacion publicada.
- `ZoneOperationalSnapshot`: nuevo, une zona, canal, programacion y politica.
- `ContentManifest`: materializa assets concretos a descargar/reproducir.

Versiones:

- `Channel.current_version` incrementa al publicar.
- `Schedule.version` ya incrementa al publicar, pero debe apuntar a snapshot.
- `ContentManifest.version` unico por zona.
- Go debe rechazar snapshots `SUPERSEDED` salvo para cerrar sesiones ya
  iniciadas.

## 16. Plan de migraciones

Migraciones nuevas, sin editar historicas:

1. `playlists`: anadir `revision` y `current_version` a `Channel`.
2. `playlists`: crear `ChannelSnapshot` y `ChannelSnapshotPlaylist`.
3. `organizations` o nueva app acordada: crear `ZoneChannelAssignment`.
4. `scheduling`: crear `ScheduleSnapshot`, `ScheduleSnapshotBlock`,
   `ScheduleSnapshotException` y `ScheduleSnapshotAssignment`.
5. `devices`: crear `DeviceActivationCode` con hash, caducidad, intentos,
   consumo y revocacion.
6. `devices`: crear sesion/refresh de dispositivo si no se reutiliza
   `DeviceCredential`.
7. `playback`: crear `ZoneOperationalSnapshot` y relacionarlo con
   `ContentManifest`.
8. `devices/playback`: indices por `company`, `zone`, `device`, `status`,
   `created_at`, `last_seen_at`, `expires_at`.

## 17. Errores

Mantener envelope comun Django:

```json
{
  "error": {
    "code": "machine_readable_code",
    "message": "Mensaje seguro.",
    "fields": {}
  }
}
```

Codigos nuevos propuestos:

| Codigo | HTTP | Caso |
| --- | --- | --- |
| `channel_not_found` | 404 | canal inexistente o inaccesible |
| `channel_code_conflict` | 409 | codigo duplicado |
| `channel_limit_reached` | 403 | limite de canales alcanzado |
| `channel_revision_conflict` | 409 | edicion concurrente |
| `channel_not_publishable` | 400 | sin playlists publicadas validas |
| `zone_channel_assignment_invalid` | 400 | zona/canal incoherente |
| `device_not_found` | 404 | dispositivo inexistente o inaccesible |
| `device_limit_reached` | 403 | limite de dispositivos alcanzado |
| `device_activation_invalid` | 400 | codigo invalido, caducado o consumido |
| `device_activation_rate_limited` | 429 | demasiados intentos |
| `device_credential_revoked` | 401 | credencial revocada |
| `device_session_expired` | 401 | refresh/access caducado |
| `manifest_not_ready` | 409 | manifiesto aun no disponible |
| `audio_asset_unavailable` | 404 | asset no autorizado/no disponible |
| `playback_command_invalid` | 400 | comando o payload invalido |
| `playback_command_conflict` | 409 | comando duplicado/no aplicable |
| `functional_access_blocked` | 403 | trial/plan bloqueado |

## 18. Compatibilidad con frontend

Crear clientes reales:

- `src/lib/api/channels.ts`
- `src/lib/api/devices.ts`
- `src/lib/api/player.ts`
- `src/lib/api/playback.ts`

Extender tipos en `src/lib/api/types.ts`:

- `ChannelSummary`, `ChannelDetail`, `ChannelPolicy`
- `ChannelPlaylist`, `ChannelSnapshotSummary`
- `ZoneChannelAssignment`
- `DeviceSummary`, `DeviceDetail`, `DeviceState`
- `DeviceActivationValidateResponse`
- `DeviceActivationCompleteResponse`
- `PlayerManifest`, `PlayerQueue`, `PlayerHeartbeatPayload`
- `PlaybackCommand`

Pantallas a conectar:

- `/app/canales`: listado, filtros, crear, estado real sin "sonando".
- `/app/canales/$channelId`: detalle, composicion, publicar, asignaciones,
  usos reales y estado operativo real si existe.
- `/app/dispositivos`: listado, crear dispositivo, generar codigo, filtros.
- `/app/dispositivos/$deviceId`: estado real, comandos, revocacion,
  incidencias y logs reales.
- `/activar-dispositivo`: nueva ruta publica.
- `/reproductor/$deviceId`: reproductor web real con credencial de dispositivo.
- Dashboard/detalles de sede/zona: usar resumen real de canal/dispositivo sin
  telemetria simulada.

No editar manualmente `src/routeTree.gen.ts`.

## 19. Plan de pruebas

Backend Django:

- restricciones de `ZoneChannelAssignment`
- limite de canales/dispositivos por plan
- permisos por rol y scope
- activacion: hash, caducidad, intentos, consumo unico, revocacion
- credencial: no raw en DB, refresh, rotacion, revocacion
- comandos: idempotencia, permisos, expiracion, transiciones
- snapshots: channel/schedule/operational inmutables
- manifiestos: assets autorizados, checksums, expiracion, aislamiento empresa
- trial caducada bloquea mutaciones

Go:

- valida device access via Django o stub de contrato
- rechaza passthrough en modo no local
- genera cola desde snapshot/manifiesto
- audio Range y CORS
- heartbeat y comandos idempotentes
- telemetria batch con reintentos
- caida de Django sin fallback simulado

Frontend:

- no `mockApi` en consumidores de Fase 4
- activacion valida/invalida/caducada
- player requiere gesto de inicio
- recarga recupera sesion de dispositivo
- canal sin programacion muestra no content
- revocacion corta nuevas descargas
- comandos remotos muestran estado confirmado
- offline cachea solo manifiesto autorizado

Implementacion del reproductor web:

- `/activar-dispositivo` valida y consume el codigo solamente por accion
  explicita del usuario; no lo persiste ni lo coloca en la URL.
- La sesion de dispositivo mantiene el access token solo en memoria y recupera
  el refresh mediante cookie HttpOnly de Django.
- `/reproductor/$deviceId` obtiene manifiestos, comandos, audio autorizado y
  telemetria exclusivamente mediante los contratos de Go.
- La primera reproduccion y la solicitud de pantalla completa ocurren dentro
  del gesto sobre `Iniciar reproduccion`.
- Los cambios de `configuration_version` se aplican al terminar la pista en
  curso; una revocacion interrumpe nuevas autorizaciones y limpia la cache.
- Cache Storage conserva solo audio proximo autorizado; IndexedDB conserva
  metadatos, secuencias, comandos procesados y una cola limitada de telemetria.
- El Service Worker cachea solamente la shell same-origin. No intercepta APIs,
  tokens ni audio autenticado.
- El cliente descarga cada asset autorizado como `Blob`, verifica SHA-256 y
  reproduce mediante una URL de objeto local. HTTP Range esta disponible en el
  backend, aunque esta primera integracion web descarga el asset completo.

Integracion:

- OWNER/MANAGER crean canal y dispositivo
- asignacion canal-zona afecta dispositivos
- publicar canal genera snapshot
- publicar schedule genera snapshot
- Go consume snapshot operativo, no draft
- reproduccion de audio sintetico aislado
- telemetria persiste en PostgreSQL
- refresh/reinicio conserva estado durable

## 20. Decisiones cerradas y pendientes

1. Playlist de respaldo cuando no hay programacion.
   - Cerrada para Fase 4: no hay fallback; se devuelve ausencia real.

2. Cambio de programacion/canal inmediato o al final de pista.
   - Cerrada: aplicar al pedir el siguiente item. Revocacion corta nuevas
     autorizaciones inmediatamente y la cache local solo dura hasta el
     manifiesto vigente.

3. Duracion offline maxima.
   - Implementacion inicial: una hora configurable mediante
     `BM_CONTENT_MANIFEST_TTL_SECONDS`; no se amplia durante una caida.

4. Tiempo exacto para declarar dispositivo offline.
   - Cerrada: 90 segundos sin heartbeat aceptado.

5. Retencion de telemetria y eventos.
   - Recomendacion: eventos detallados 90 dias, agregados 24 meses; confirmar
     antes de migraciones de particionado/limpieza.

6. Alcance exacto de `OPERADOR_SEDES`.
   - Recomendacion: puede ver y controlar playback de sus scopes; no crear,
     revocar ni reasignar dispositivos.

7. Si una zona sin canal admite dispositivo activado.
   - Cerrada: si, y el player devuelve `NO_CHANNEL_ASSIGNED`.

8. Politica de fallback de canal (`ChannelPolicy.fallback_channel`).
   - El modelo actual apunta a otro canal, no a playlist. Hay que decidir si se
     conserva asi o si el fallback real debe ser playlist/silencio.

9. Autenticacion servicio a servicio.
   - Implementada con secreto interno por entorno y validacion doble junto al
     JWT de dispositivo. mTLS o firma asimetrica queda para despliegue.

10. Compatibilidad Safari/iOS/PWA.
    - Recomendacion: declarar soporte inicial Chromium/Edge/Firefox desktop y
      validar Safari antes de comprometer offline robusto.

## 21. Riesgos

- Audio con `Authorization` header no funciona directamente con `<audio src>`;
  hay que resolver cookie HttpOnly o descarga controlada por `fetch`.
- Cookies entre puertos en `localhost` deben probarse en navegadores reales.
- Offline con datos cacheados exige expiracion estricta para evitar reproducir
  contenido ya no autorizado.
- La telemetria puede crecer rapido; no particionar prematuramente, pero si
  disenar indices y retencion desde el inicio.
- `ChannelPolicy.fallback_channel` puede no representar el fallback de producto
  esperado.

## 22. Fuentes inspeccionadas

- `AGENTS.md`
- `../BrandyManager_Front/AGENTS.md`
- `docs/FASE3_CATALOGO_PLAYLISTS_PROGRAMACION_CONTRATO.md`
- `back_django/backend/apps/playlists/models.py`
- `back_django/backend/apps/scheduling/models.py`
- `back_django/backend/apps/scheduling/services.py`
- `back_django/backend/apps/scheduling/selectors.py`
- `back_django/backend/apps/devices/models.py`
- `back_django/backend/apps/devices/services.py`
- `back_django/backend/apps/playback/models.py`
- `back_django/backend/apps/playback/services.py`
- `back_django/backend/apps/authorization/catalog.py`
- `back_django/backend/apps/billing/plans.py`
- `back_go/internal/api/router.go`
- `back_go/internal/api/handlers.go`
- `back_go/internal/playback/service.go`
- `back_go/internal/operations/service.go`
- `back_go/internal/platform/middleware/auth.go`
- `back_go/internal/config/config.go`
- `../BrandyManager_Front/src/routes/app.canales.index.tsx`
- `../BrandyManager_Front/src/routes/app.canales.$channelId.tsx`
- `../BrandyManager_Front/src/routes/app.dispositivos.index.tsx`
- `../BrandyManager_Front/src/routes/app.dispositivos.$deviceId.tsx`
- `../BrandyManager_Front/src/routes/reproductor.$deviceId.tsx`
- `../BrandyManager_Front/src/routes/app.index.tsx`
- `../BrandyManager_Front/src/lib/mockApi.ts`
- `../BrandyManager_Front/src/lib/mock/models.ts`
- `../BrandyManager_Front/src/lib/mock/seed.ts`
