def resolve_effective_policy(*, zone, at=None):
    assignments = (
        zone.company.playback_policy_assignments.filter(is_active=True)
        .select_related("policy", "scope")
        .order_by("-is_locked", "-priority", "-created_at")
    )
    return assignments.first()


def can_execute_playback_action(*, user_has_permission, policy, action):
    if not user_has_permission:
        return False
    mapping = {
        "pause": policy.allow_pause,
        "skip": policy.allow_skip,
        "change_channel": policy.allow_channel_change,
        "volume": policy.allow_local_volume_change,
        "manual_message": policy.allow_manual_message,
    }
    return bool(mapping.get(action, False))


def create_manifest(*, zone, version, checksum, generated_at, items=None):
    from apps.playback.models import ContentManifest, ContentManifestItem

    manifest = ContentManifest.objects.create(
        company=zone.company,
        zone=zone,
        version=version,
        status=ContentManifest.Status.READY,
        generated_at=generated_at,
        checksum=checksum,
    )
    for item in items or []:
        ContentManifestItem.objects.create(manifest=manifest, **item)
    return manifest
