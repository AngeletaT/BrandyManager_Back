from rest_framework import status

from shared.api.exceptions import DomainError


class ScheduleNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="schedule_not_found",
            message="La programacion no existe o no pertenece a tu empresa.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ScheduleBlockNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="schedule_block_not_found",
            message="El bloque de programacion no existe.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ScheduleExceptionNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="schedule_exception_not_found",
            message="La excepcion de programacion no existe.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ScheduleAssignmentNotFound(DomainError):
    def __init__(self):
        super().__init__(
            code="schedule_assignment_not_found",
            message="La asignacion de programacion no existe.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ScheduleRevisionConflict(DomainError):
    def __init__(self):
        super().__init__(
            code="schedule_revision_conflict",
            message="La programacion ha cambiado. Recarga antes de continuar.",
            status_code=status.HTTP_409_CONFLICT,
        )


class ScheduleConflict(DomainError):
    def __init__(self, *, fields=None, conflicts=None):
        super().__init__(
            code="schedule_conflict",
            message="La programacion tiene un conflicto temporal en el mismo destino.",
            fields=fields or {},
            status_code=status.HTTP_409_CONFLICT,
            extra={"conflicts": conflicts or []},
        )


class ScheduleAssignmentInvalid(DomainError):
    def __init__(self, *, fields=None, message=None):
        super().__init__(
            code="schedule_assignment_invalid",
            message=message or "El destino de la programacion no es valido.",
            fields=fields or {},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class ScheduleContentUnavailable(DomainError):
    def __init__(self, *, fields=None, message=None):
        super().__init__(
            code="schedule_content_unavailable",
            message=message or "El contenido de la programacion no esta disponible para esta empresa.",
            fields=fields or {},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class ScheduleNotPublishable(DomainError):
    def __init__(self, *, fields=None):
        super().__init__(
            code="schedule_not_publishable",
            message="La programacion no se puede publicar con la configuracion actual.",
            fields=fields or {},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

