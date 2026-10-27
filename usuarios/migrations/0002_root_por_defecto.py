from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations


def crear_root(apps, schema_editor):
    """HU 4: crea el usuario root por defecto si todavía no existe ninguno."""
    Usuario = apps.get_model("usuarios", "Usuario")
    if Usuario.objects.filter(rol="root").exists():
        return
    Usuario.objects.create(
        username=settings.ROOT_USERNAME,
        password=make_password(settings.ROOT_PASSWORD),
        rol="root",
        is_staff=True,
        is_superuser=True,
    )


class Migration(migrations.Migration):
    dependencies = [("usuarios", "0001_initial")]
    operations = [migrations.RunPython(crear_root, migrations.RunPython.noop)]
