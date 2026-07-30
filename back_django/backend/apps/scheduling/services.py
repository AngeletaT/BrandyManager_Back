def resolve_effective_schedule(*, zone, at=None):
    specificity = {
        "COMPANY": 1,
        "ORGANIZATIONAL_UNIT": 2,
        "RESOURCE_GROUP": 3,
        "SITE": 4,
        "ZONE": 5,
    }
    assignments = zone.company.schedule_assignments.filter(is_active=True).select_related("schedule", "scope")
    return sorted(
        assignments,
        key=lambda assignment: (
            assignment.is_locked,
            assignment.priority,
            specificity.get(assignment.scope.scope_type, 0),
            assignment.created_at,
        ),
        reverse=True,
    )[0] if assignments else None
