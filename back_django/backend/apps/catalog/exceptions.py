from rest_framework import status

from shared.api.exceptions import DomainError


class CatalogSongNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="catalog_song_not_found",
            message="La cancion no existe o no esta disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class InternalCatalogPermissionDenied(DomainError):
    def __init__(self):
        super().__init__(
            code="internal_catalog_permission_denied",
            message="No tienes permiso para incorporar contenido al catalogo.",
            status_code=status.HTTP_403_FORBIDDEN,
        )


class AudioFileInvalid(DomainError):
    def __init__(self, *, message="El archivo de audio no es valido.", fields=None):
        super().__init__(
            code="audio_file_invalid",
            message=message,
            fields=fields or {"file": [message]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class AudioAssetDuplicate(DomainError):
    def __init__(self):
        super().__init__(
            code="audio_asset_duplicate",
            message="Este archivo de audio ya existe en el catalogo.",
            fields={"file": ["Este archivo ya fue incorporado."]},
            status_code=status.HTTP_409_CONFLICT,
        )


class AudioContentCodeConflict(DomainError):
    def __init__(self):
        super().__init__(
            code="audio_content_code_conflict",
            message="Ya existe contenido global con este codigo interno.",
            fields={"internal_code": ["Este codigo ya esta en uso."]},
            status_code=status.HTTP_409_CONFLICT,
        )


class AudioStorageFailed(DomainError):
    def __init__(self):
        super().__init__(
            code="audio_storage_failed",
            message="No se pudo almacenar el archivo de audio.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class AudioAssetUnavailable(DomainError):
    def __init__(self):
        super().__init__(
            code="audio_asset_unavailable",
            message="El audio no esta disponible para este dispositivo.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
