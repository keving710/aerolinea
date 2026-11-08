from datetime import datetime, timezone
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class PreservacionIteracion1Tests(TransactionTestCase):
    def test_migracion_conserva_vuelo_existente(self):
        executor = MigrationExecutor(connection)
        nuevas = executor.loader.graph.leaf_nodes()
        anterior = [nodo for nodo in nuevas if nodo[0] != "vuelos"] + [("vuelos", "0002_alter_vuelo_estado")]
        try:
            executor.migrate(anterior)
            apps = executor.loader.project_state(anterior).apps
            Usuario = apps.get_model("usuarios", "Usuario")
            Vuelo = apps.get_model("vuelos", "Vuelo")
            admin = Usuario.objects.create(username="admin_migracion", rol="administrador", password="!")
            vuelo = Vuelo.objects.create(codigo="VU-90000", tipo="nacional", origen="Pereira", destino="Bogotá",
                salida=datetime(2028, 1, 1, 13, tzinfo=timezone.utc), llegada=datetime(2028, 1, 1, 14, tzinfo=timezone.utc),
                duracion_minutos=60, capacidad=150, costo_persona="250000.00", creado_por=admin)
            executor = MigrationExecutor(connection)
            executor.migrate(nuevas)
            apps = executor.loader.project_state(nuevas).apps
            actual = apps.get_model("vuelos", "Vuelo").objects.get(pk=vuelo.pk)
            self.assertEqual(actual.codigo, "VU-90000")
            self.assertEqual(actual.capacidad, 150)
            self.assertEqual(actual.creado_por_id, admin.pk)
            self.assertEqual(actual.tiquetes_vendidos, 0)
            self.assertEqual(actual.cupos_reservados, 0)
        finally:
            MigrationExecutor(connection).migrate(nuevas)
