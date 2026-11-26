"""Deja la base lista para la sustentación: usuarios, tarjetas, vuelos y reservas de prueba.

Uso:
    python manage.py cargar_clientes_demo

Es repetible: borra los datos de prueba anteriores (solo los de estos usuarios y sus vuelos DEMO)
y los vuelve a crear, así que sirve también para reiniciar entre ensayos.

Usuarios (contraseña común: Demo2026!):
    admin_demo      administrador (HU 16 y 17)
    cliente_cinco   ya tiene 5 tiquetes comprados en un vuelo: el 6.º debe rechazarse (HU 27/29)
    cliente_saldo   tarjeta con solo $1.000 COP: la compra debe rechazarse por saldo (HU 29)
    cliente_demo    tarjeta con saldo alto, 2 tiquetes comprados y 1 reserva sin pagar (HU 28-33)
"""
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone

from finanzas import services as finanzas
from finanzas.models import Movimiento, Tarjeta
from reservas import servicios
from reservas.models import Reserva, Tiquete
from usuarios.models import Ciudad, Departamento, Usuario
from vuelos import reglas
from vuelos.models import Vuelo

CLAVE = "Demo2026!"

USUARIOS = {
    "admin_demo": dict(rol="administrador", first_name="Alicia", last_name="Admin", dni="900000001"),
    "cliente_cinco": dict(rol="cliente", first_name="Carlos", last_name="Cinco", dni="900000002"),
    "cliente_saldo": dict(rol="cliente", first_name="Sara", last_name="Saldo", dni="900000003"),
    "cliente_demo": dict(rol="cliente", first_name="Daniel", last_name="Demo", dni="900000004"),
}

# username -> (número ficticio válido, tipo, saldo inicial, cvv)
TARJETAS = {
    "cliente_cinco": ("4111111111111111", "credito", Decimal("30000000"), "123"),
    "cliente_saldo": ("5555555555554444", "debito", Decimal("1000"), "123"),
    "cliente_demo": ("4012888888881881", "credito", Decimal("30000000"), "123"),
}


def viajero(documento, nombres, apellidos, nacimiento, clase="economica"):
    return {"documento": str(documento), "nombres": nombres, "apellidos": apellidos,
            "fecha_nacimiento": nacimiento, "genero": "femenino", "telefono": "3001234567",
            "correo": f"viajero{documento}@correo.com", "contacto_nombre": "Contacto Demo",
            "contacto_telefono": "3109876543", "clase": clase}


class Command(BaseCommand):
    help = "Crea usuarios, tarjetas, vuelos y reservas de prueba para la sustentación (repetible)."

    # -- limpieza ---------------------------------------------------------
    def _borrar_anteriores(self):
        usuarios = Usuario.objects.filter(username__in=USUARIOS)
        Tiquete.objects.filter(reserva__cliente__in=usuarios).delete()
        Reserva.objects.filter(cliente__in=usuarios).delete()
        Movimiento.objects.filter(tarjeta__cliente__in=usuarios).delete()
        Tarjeta.objects.filter(cliente__in=usuarios).delete()
        admin = Usuario.objects.filter(username="admin_demo").first()
        if admin:
            vuelos = Vuelo.objects.filter(creado_por=admin)
            Tiquete.objects.filter(vuelo__in=vuelos).delete()  # Tiquetes de otros clientes en vuelos DEMO.
            vuelos.filter(vuelo_ida__isnull=False).delete()
            vuelos.delete()

    def _ciudad(self):
        ciudad = Ciudad.objects.filter(nombre="Pereira").first() or Ciudad.objects.first()
        if ciudad is None:
            dep, _ = Departamento.objects.get_or_create(nombre="Risaralda")
            ciudad, _ = Ciudad.objects.get_or_create(nombre="Pereira", departamento=dep)
        return ciudad

    def _usuarios(self):
        ciudad, resultado = self._ciudad(), {}
        for username, datos in USUARIOS.items():
            usuario, _ = Usuario.objects.get_or_create(username=username, defaults={"rol": datos["rol"]})
            usuario.rol, usuario.is_active = datos["rol"], True
            usuario.first_name, usuario.last_name, usuario.dni = datos["first_name"], datos["last_name"], datos["dni"]
            usuario.email = f"{username}@demo.com"
            usuario.fecha_nacimiento = date(1990, 5, 20)
            usuario.ciudad_nacimiento = ciudad
            usuario.direccion_facturacion = "Calle 10 # 5-20, Pereira"
            usuario.genero, usuario.telefono = "otro", "3001112233"
            usuario.set_password(CLAVE)
            usuario.save()
            resultado[username] = usuario
        return resultado

    def _vuelo(self, creador, dias, hora, origen, destino, minutos, costo, tipo="nacional", ida=None):
        dia = date.today() + timedelta(days=dias)
        naive = datetime.combine(dia, time(hora, 0))
        if tipo == "nacional":
            salida = reglas.a_utc(naive, reglas.TZ_COLOMBIA)
            llegada = salida + timedelta(minutes=minutos)
            capacidad = reglas.CAPACIDAD_NACIONAL
        else:
            salida, llegada = reglas.calcular_llegada_internacional(naive, reglas.zona_de(origen), destino, minutos)
            capacidad = reglas.CAPACIDAD_INTERNACIONAL
        return Vuelo.objects.create(
            tipo=tipo, origen=origen, destino=destino, salida=salida, llegada=llegada, duracion_minutos=minutos,
            costo_persona=Decimal(costo), capacidad=capacidad, creado_por=creador, vuelo_ida=ida)

    # -- principal --------------------------------------------------------
    @transaction.atomic
    def handle(self, *args, **opciones):
        random.seed(2026)
        self._borrar_anteriores()
        usuarios = self._usuarios()
        admin = usuarios["admin_demo"]

        # Vuelos DEMO (con su regreso). Todos del administrador de prueba.
        limite = self._vuelo(admin, 12, 8, "Pereira", "Bogotá", 50, 200_000)
        limite_r = self._vuelo(admin, 16, 9, "Bogotá", "Pereira", 50, 190_000)
        alterno = self._vuelo(admin, 12, 15, "Pereira", "Bogotá", 50, 210_000)
        cartagena = self._vuelo(admin, 11, 9, "Pereira", "Cartagena de Indias", 85, 280_000)
        cartagena_r = self._vuelo(admin, 15, 10, "Cartagena de Indias", "Pereira", 85, 270_000)
        cartagena_alt = self._vuelo(admin, 11, 16, "Pereira", "Cartagena de Indias", 85, 290_000)
        promo = self._vuelo(admin, 14, 7, "Pereira", "Medellín", 40, 150_000)
        promo_r = self._vuelo(admin, 18, 8, "Medellín", "Pereira", 40, 150_000)
        miami = self._vuelo(admin, 20, 9, "Bogotá", "Miami", 225, 1_250_000, tipo="internacional")
        miami_r = self._vuelo(admin, 30, 10, "Miami", "Bogotá", 225, 1_250_000, tipo="internacional", ida=miami)

        tarjetas = {}
        for username, (numero, tipo, saldo, cvv) in TARJETAS.items():
            tarjetas[username] = finanzas.registrar_tarjeta(
                usuarios[username], numero, tipo, saldo, mes=12, anio=timezone.localdate().year + 4, cvv=cvv)

        # Los correos de confirmación no se imprimen en la consola durante la carga.
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            # Cliente 1: 5 tiquetes ya comprados en el vuelo `limite` (un tiquete = una persona).
            cinco = [viajero(7000001 + i, f"Viajero{i + 1}", "Cinco", "1992-03-10") for i in range(5)]
            servicios.comprar(usuarios["cliente_cinco"], [
                {"vuelo": limite.codigo, "regreso": "", "viajeros": cinco}], tarjetas["cliente_cinco"])
            # Cliente 3: dos tiquetes comprados (para cancelar compra y para cancelar el vuelo) y una reserva sin pagar.
            servicios.comprar(usuarios["cliente_demo"], [
                {"vuelo": cartagena.codigo, "regreso": "",
                 "viajeros": [viajero(8000001, "Daniel", "Demo", "1990-05-20"), viajero(8000002, "Diana", "Demo", "1991-07-02")]}],
                tarjetas["cliente_demo"])
            servicios.reservar(usuarios["cliente_demo"], {
                "vuelo": promo.codigo, "regreso": promo_r.codigo,
                "viajeros": [viajero(8000003, "Daniel", "Demo", "1990-05-20")]})

        self.vuelos = {"limite": limite, "limite_regreso": limite_r, "alterno": alterno, "cartagena": cartagena,
                       "cartagena_regreso": cartagena_r, "cartagena_alterno": cartagena_alt, "promo": promo,
                       "miami": miami, "miami_regreso": miami_r}
        self._resumen(usuarios, tarjetas)

    def _resumen(self, usuarios, tarjetas):
        w = self.stdout.write
        w(self.style.SUCCESS("Datos de prueba listos."))
        w(f"\nContraseña de todos: {CLAVE}")
        w("Usuarios: admin_demo (administrador) · cliente_cinco · cliente_saldo · cliente_demo")
        for username, tarjeta in tarjetas.items():
            tarjeta.refresh_from_db()
            w(f"  {username}: tarjeta {tarjeta.numero_visible} · CVV 123 · saldo ${tarjeta.saldo:,.0f} COP")
        w("\nVuelos de la demostración:")
        for clave, v in self.vuelos.items():
            w(f"  {clave:<18} {v.codigo}  {v.origen} → {v.destino}  {v.salida_local}  ${v.costo_vigente:,.0f}")
