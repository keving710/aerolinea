from django.db import migrations

from usuarios.datos_ciudades import CIUDADES


def cargar_ciudades(apps, schema_editor):
    """Carga departamentos y ciudades para que el registro tenga opciones de lugar de nacimiento."""
    Departamento = apps.get_model("usuarios", "Departamento")
    Ciudad = apps.get_model("usuarios", "Ciudad")
    for nombre_dep, ciudades in CIUDADES.items():
        dep, _ = Departamento.objects.get_or_create(nombre=nombre_dep)
        for nombre in ciudades:
            Ciudad.objects.get_or_create(nombre=nombre, departamento=dep)


class Migration(migrations.Migration):
    dependencies = [("usuarios", "0004_ciudad_departamento_remove_usuario_lugar_nacimiento_and_more")]
    operations = [migrations.RunPython(cargar_ciudades, migrations.RunPython.noop)]
