from rest_framework import status

from shared.api.exceptions import DomainError


class PlaylistNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="playlist_not_found",
            message="La playlist no existe o no esta disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class PlaylistItemNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="playlist_item_not_found",
            message="El elemento de la playlist no existe o no esta disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class PlaylistCodeConflict(DomainError):
    def __init__(self):
        super().__init__(
            code="playlist_code_conflict",
            message="Ya existe una playlist con este codigo en la empresa.",
            fields={"code": ["Ya existe una playlist con este codigo."]},
            status_code=status.HTTP_409_CONFLICT,
        )


class PlaylistLimitReached(DomainError):
    def __init__(self):
        super().__init__(
            code="playlist_limit_reached",
            message="Has alcanzado el limite de playlists de tu plan.",
            fields={"playlists": ["Limite alcanzado."]},
            status_code=status.HTTP_403_FORBIDDEN,
        )


class PlaylistRevisionConflict(DomainError):
    def __init__(self):
        super().__init__(
            code="playlist_revision_conflict",
            message="La playlist ha cambiado. Recarga los datos antes de guardar.",
            status_code=status.HTTP_409_CONFLICT,
        )


class PlaylistContentUnavailable(DomainError):
    def __init__(self):
        super().__init__(
            code="playlist_content_unavailable",
            message="La cancion no existe o no esta disponible para esta empresa.",
            fields={"song_id": ["La cancion no esta disponible."]},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class PlaylistNotPublishable(DomainError):
    def __init__(self, *, fields=None):
        super().__init__(
            code="playlist_not_publishable",
            message="La playlist no puede publicarse.",
            fields=fields or {},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class PlaylistInUse(DomainError):
    def __init__(self):
        super().__init__(
            code="playlist_in_use",
            message="La playlist esta siendo utilizada por una programacion y no puede archivarse.",
            status_code=status.HTTP_409_CONFLICT,
        )


class PlaylistOrderConflict(DomainError):
    def __init__(self):
        super().__init__(
            code="playlist_order_conflict",
            message="El orden enviado no coincide con los elementos actuales de la playlist.",
            fields={"item_ids": ["Deben enviarse todos los elementos actuales una sola vez."]},
            status_code=status.HTTP_409_CONFLICT,
        )


class ChannelNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="channel_not_found",
            message="El canal no existe o no esta disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ChannelCodeConflict(DomainError):
    def __init__(self):
        super().__init__(
            code="channel_code_conflict",
            message="Ya existe un canal con este codigo en la empresa.",
            fields={"code": ["Ya existe un canal con este codigo."]},
            status_code=status.HTTP_409_CONFLICT,
        )


class ChannelLimitReached(DomainError):
    def __init__(self):
        super().__init__(
            code="channel_limit_reached",
            message="Has alcanzado el limite de canales de tu plan.",
            fields={"channels": ["Limite alcanzado."]},
            status_code=status.HTTP_403_FORBIDDEN,
        )


class ChannelRevisionConflict(DomainError):
    def __init__(self):
        super().__init__(
            code="channel_revision_conflict",
            message="El canal ha cambiado. Recarga los datos antes de guardar.",
            status_code=status.HTTP_409_CONFLICT,
        )


class ChannelNotPublishable(DomainError):
    def __init__(self, *, fields=None):
        super().__init__(
            code="channel_not_publishable",
            message="El canal no puede publicarse.",
            fields=fields or {},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class ChannelPlaylistInvalid(DomainError):
    def __init__(self, *, fields=None):
        super().__init__(
            code="channel_playlist_invalid",
            message="La configuracion de playlists del canal no es valida.",
            fields=fields or {},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class ChannelInUse(DomainError):
    def __init__(self):
        super().__init__(
            code="channel_in_use",
            message="El canal esta asignado a una o mas zonas activas y no puede archivarse.",
            status_code=status.HTTP_409_CONFLICT,
        )


class ZoneChannelAssignmentInvalid(DomainError):
    def __init__(self, *, fields=None, message="La asignacion de canal a zona no es valida."):
        super().__init__(
            code="zone_channel_assignment_invalid",
            message=message,
            fields=fields or {},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
