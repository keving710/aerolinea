"""Compra y reserva de tiquetes (iteración 3)."""
import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q

# Sin 0/O ni 1/I para que el código sea fácil de leer y dictar.
ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generar_codigo():
    return "RES-" + "".join(secrets.choice(ALFABETO_CODIGO) for _ in range(8))


class Reserva(models.Model):
    """Una compra o una reserva de uno o varios viajeros (un solo trayecto o ida y vuelta).

    El código de reserva es el insumo del check-in de la iteración 4 (HU 31).
    """

    class Estado(models.TextChoices):
        RESERVADA = "reservada", "Reservada"
        COMPRADA = "comprada", "Comprada"
        CANCELADA = "cancelada", "Cancelada"
        VENCIDA = "vencida", "Vencida"

    class Trayecto(models.TextChoices):
        UNICO = "unico", "Solo ida"
        COMPLETO = "completo", "Ida y vuelta"

    codigo = models.CharField(max_length=12, unique=True, editable=False)
    cliente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reservas")
    estado = models.CharField(max_length=10, choices=Estado.choices)
    trayecto = models.CharField(max_length=10, choices=Trayecto.choices, default=Trayecto.UNICO)
    # Tarjeta con la que se pagó (solo compras); a ella se devuelve el dinero al cancelar.
    tarjeta = models.ForeignKey("finanzas.Tarjeta", null=True, blank=True, on_delete=models.PROTECT, related_name="reservas")
    creada_en = models.DateTimeField(auto_now_add=True)
    expira_en = models.DateTimeField("la reserva se libera el", null=True, blank=True)
    pagada_en = models.DateTimeField(null=True, blank=True)
    cancelada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creada_en", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(estado__in=["reservada", "comprada", "cancelada", "vencida"]), name="reserva_estado_valido"),
            models.CheckConstraint(condition=~Q(estado="reservada") | Q(expira_en__isnull=False), name="reserva_reservada_con_vencimiento"),
            models.CheckConstraint(condition=~Q(estado="comprada") | Q(tarjeta__isnull=False), name="reserva_comprada_con_tarjeta"),
        ]

    def save(self, *args, **kwargs):
        if not self.codigo:
            # 32^8 combinaciones: la colisión es improbable, pero se verifica igualmente.
            while True:
                codigo = generar_codigo()
                if not Reserva.objects.filter(codigo=codigo).exists():
                    self.codigo = codigo
                    break
        super().save(*args, **kwargs)

    @property
    def activa(self):
        return self.estado in (self.Estado.RESERVADA, self.Estado.COMPRADA)

    @property
    def tiquetes_activos(self):
        return [t for t in self.tiquetes.all() if t.estado == Tiquete.Estado.ACTIVO]

    @property
    def total_activo(self):
        return sum((t.valor for t in self.tiquetes_activos), 0)

    def __str__(self):
        return f"{self.codigo} ({self.get_estado_display()})"


class Tiquete(models.Model):
    """Un viajero en un vuelo, con su clase y su silla (HU 27 y 30)."""

    class Estado(models.TextChoices):
        ACTIVO = "activo", "Activo"
        CANCELADO = "cancelado", "Cancelado"

    class Clase(models.TextChoices):
        PRIMERA = "primera", "Primera clase"
        ECONOMICA = "economica", "Clase económica"

    class Tramo(models.IntegerChoices):
        IDA = 1, "Ida"
        REGRESO = 2, "Regreso"

    reserva = models.ForeignKey(Reserva, on_delete=models.PROTECT, related_name="tiquetes")
    vuelo = models.ForeignKey("vuelos.Vuelo", on_delete=models.PROTECT, related_name="tiquetes")
    tramo = models.PositiveSmallIntegerField(choices=Tramo.choices, default=Tramo.IDA)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVO)
    clase = models.CharField(max_length=10, choices=Clase.choices)
    silla = models.PositiveSmallIntegerField()
    # Valor con el que se emitió: una promoción posterior no lo modifica (HU 16).
    valor = models.DecimalField(max_digits=12, decimal_places=2)

    documento = models.CharField("documento", max_length=20)
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    fecha_nacimiento = models.DateField()
    genero = models.CharField(max_length=10)
    telefono = models.CharField(max_length=20)
    correo = models.EmailField()
    contacto_nombre = models.CharField("nombre del contacto", max_length=120)
    contacto_telefono = models.CharField("teléfono del contacto", max_length=20)

    # El check-in se implementa en la iteración 4; aquí solo se refleja su estado (HU 33).
    checkin_completado = models.BooleanField(default=False)
    reubicado_desde = models.ForeignKey("vuelos.Vuelo", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    motivo_cancelacion = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["tramo", "pk"]
        constraints = [
            # Dos tiquetes activos del mismo vuelo nunca comparten silla ni viajero.
            models.UniqueConstraint(fields=["vuelo", "silla"], condition=Q(estado="activo"), name="tiquete_silla_unica_por_vuelo"),
            models.UniqueConstraint(fields=["vuelo", "documento"], condition=Q(estado="activo"), name="tiquete_viajero_unico_por_vuelo"),
            models.CheckConstraint(condition=Q(valor__gt=0), name="tiquete_valor_positivo"),
            models.CheckConstraint(condition=Q(silla__gte=1), name="tiquete_silla_positiva"),
        ]

    @property
    def nombre_completo(self):
        return f"{self.nombres} {self.apellidos}"

    @property
    def estado_checkin(self):
        return "Completado" if self.checkin_completado else "Pendiente"

    def __str__(self):
        return f"{self.reserva.codigo} · {self.nombre_completo} · {self.vuelo.codigo} · silla {self.silla}"
