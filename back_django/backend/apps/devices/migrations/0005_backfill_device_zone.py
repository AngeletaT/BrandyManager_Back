from django.db import migrations


def backfill_device_zone(apps, schema_editor):
    Device = apps.get_model("devices", "Device")
    DeviceZoneAssignment = apps.get_model("devices", "DeviceZoneAssignment")
    for assignment in DeviceZoneAssignment.objects.filter(unassigned_at__isnull=True).only("device_id", "zone_id"):
        Device.objects.filter(id=assignment.device_id, zone__isnull=True).update(zone_id=assignment.zone_id)


class Migration(migrations.Migration):
    dependencies = [
        ("devices", "0004_deviceactivation_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_device_zone, migrations.RunPython.noop),
    ]
