from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.db.models import F, Q

from . import reglas


class Consecutivo(models.Model):
    """Contador atómico para generar códigos de vuelo únicos (HU 10)."""

    nombre = models.CharField(max_length=30, unique=True)
    ultimo = models.PositiveIntegerField(default=0)

    @classmethod
    def siguiente(cls, nombre="vuelo"):
        with transaction.atomic():
            contador, _ = cls.objects.select_for_update().get_or_create(nombre=nombre)
            contador.ultimo += 1
            contador.save(update_fields=["ultimo"])
            return contador.ultimo


class Vuelo(models.Model):
    class Tipo(models.TextChoices):
        NACIONAL = "nacional", "Nacional"
        INTERNACIONAL = "internacional", "Internacional"

    class Estado(models.TextChoices):
        PROGRAMADO = "programado", "Programado"
        CANCELADO = "cancelado", "Cancelado"
        REALIZADO = "realizado", "Realizado"

    codigo = models.CharField(max_length=12, unique=True, editable=False)
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    origen = models.CharField(max_length=40)
    destino = models.CharField(max_length=40)
    salida = models.DateTimeField("salida (UTC)")
    llegada = models.DateTimeField("llegada (UTC)")
    duracion_minutos = models.PositiveIntegerField()
    costo_persona = models.DecimalField("costo por persona (COP)", max_digits=12, decimal_places=2)
    capacidad = models.PositiveIntegerField()
    # Contrato mínimo de inventario para iteración 3, sin venta ni reserva HTTP.
    tiquetes_vendidos = models.PositiveIntegerField(default=0, editable=False)
    cupos_reservados = models.PositiveIntegerField(default=0, editable=False)
    vuelo_ida = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="vuelo_regreso"
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="vuelos_creados"
    )
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PROGRAMADO)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["salida"]
        constraints = [
            models.CheckConstraint(condition=Q(capacidad__gt=0), name="vuelo_capacidad_positiva"),
            models.CheckConstraint(condition=Q(duracion_minutos__gt=0), name="vuelo_duracion_positiva"),
            models.CheckConstraint(condition=Q(capacidad__gte=F("tiquetes_vendidos") + F("cupos_reservados")), name="vuelo_inventario_valido"),
            models.CheckConstraint(condition=~Q(origen=F("destino")), name="vuelo_origen_distinto_destino"),
            models.CheckConstraint(condition=Q(llegada__gt=F("salida")), name="vuelo_llegada_posterior"),
            models.CheckConstraint(condition=Q(costo_persona__gt=0), name="vuelo_costo_positivo"),
        ]

    def save(self, *args, **kwargs):
        if not self.codigo:
            self.codigo = f"VU-{Consecutivo.siguiente():05d}"
        super().save(*args, **kwargs)

    @property
    def cupos_disponibles(self):
        return max(0, self.capacidad - self.tiquetes_vendidos - self.cupos_reservados)

    @property
    def motivo_no_editable(self):
        if self.tiquetes_vendidos:
            return "Este vuelo tiene tiquetes vendidos y no se puede editar."
        if self.estado == self.Estado.REALIZADO or self.salida <= timezone.now():
            return "Este vuelo ya se realizó o inició y no se puede editar."
        if self.estado != self.Estado.PROGRAMADO:
            return "Solo se pueden editar vuelos programados."
        return ""

    @property
    def imagen_catalogo(self):
        return f"img/vuelo-{self.tipo}.svg"

    # Zonas horarias locales de cada extremo.
    @property
    def zona_origen(self):
        return reglas.zona_de(self.origen)

    @property
    def zona_destino(self):
        return reglas.zona_de(self.destino)

    # Textos ya convertidos a hora local (las plantillas reconvertirían los datetimes aware).
    @property
    def salida_local(self):
        return reglas.formatear(self.salida, self.zona_origen)

    @property
    def llegada_local(self):
        return reglas.formatear(self.llegada, self.zona_destino)

    @property
    def duracion_texto(self):
        return reglas.formatear_duracion(self.duracion_minutos)

    @property
    def es_regreso(self):
        return self.vuelo_ida_id is not None

    def __str__(self):
        return f"{self.codigo}: {self.origen} → {self.destino}"
