from rest_framework import status

from shared.api.exceptions import DomainError


class CatalogSongNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="catalog_song_not_found",
            message="La cancion no existe o no esta disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
