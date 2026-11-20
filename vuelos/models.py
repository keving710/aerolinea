from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.db.models import F, Q

from django.core.exceptions import ValidationError

from . import reglas

IMAGEN_VUELO_MAX_BYTES = 3 * 1024 * 1024  # 3 MB


def validar_imagen_vuelo(archivo):
    """Imagen del vuelo elegida por el administrador: JPG, PNG o WEBP de máximo 3 MB."""
    nombre = (getattr(archivo, "name", "") or "").lower()
    if not nombre.endswith((".jpg", ".jpeg", ".png", ".webp")):
        raise ValidationError("La imagen debe estar en formato JPG, PNG o WEBP.")
    try:
        tamano = archivo.size
    except (OSError, ValueError):
        return  # Archivo ya guardado que no está disponible: no se valida de nuevo.
    if tamano > IMAGEN_VUELO_MAX_BYTES:
        raise ValidationError("La imagen no puede superar los 3 MB.")


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

    @classmethod
    def proximo_codigo(cls, nombre="vuelo"):
        """Código que recibirá el próximo vuelo (solo para mostrarlo en el formulario, HU 10)."""
        ultimo = cls.objects.filter(nombre=nombre).values_list("ultimo", flat=True).first() or 0
        return f"VU-{ultimo + 1:05d}"


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
    imagen = models.ImageField("imagen del vuelo", upload_to="vuelos/", blank=True, null=True,
                               validators=[validar_imagen_vuelo])
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

    @property
    def imagen_url(self):
        """Imagen elegida por el administrador o, si no hay, la ilustración según el tipo."""
        if self.imagen:
            try:
                return self.imagen.url
            except ValueError:
                pass
        from django.templatetags.static import static
        return static(self.imagen_catalogo)

    @property
    def imagen_alt(self):
        if self.imagen:
            return f"Imagen del vuelo {self.origen} – {self.destino}"
        return f"Ilustración de un vuelo {self.get_tipo_display().lower()}"

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
