from django.db import migrations


def relabel_content_types(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")

    mappings = [
        ("main", "departments", "employees", "departments"),
        ("main", "employees", "employees", "employees"),
        ("main", "vacationrequest", "leave", "vacationrequest"),
    ]

    for old_app, old_model, new_app, new_model in mappings:
        old_ct = ContentType.objects.filter(app_label=old_app, model=old_model).first()
        if old_ct is None:
            continue

        new_ct = ContentType.objects.filter(app_label=new_app, model=new_model).first()
        if new_ct and new_ct.pk != old_ct.pk:
            Permission.objects.filter(content_type=old_ct).update(content_type=new_ct)
            old_ct.delete()
            continue

        old_ct.app_label = new_app
        old_ct.model = new_model
        old_ct.save(update_fields=["app_label", "model"])

    obsolete_models = ["vacation", "preholidays", "canceledholidays", "сanceledholidays"]
    for content_type in ContentType.objects.filter(app_label="main", model__in=obsolete_models):
        Permission.objects.filter(content_type=content_type).delete()
        content_type.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0001_initial"),
        ("leave", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(relabel_content_types, migrations.RunPython.noop),
    ]
