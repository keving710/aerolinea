import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Tarjeta(models.Model):
    class Tipo(models.TextChoices):
        DEBITO = "debito", "Débito"
        CREDITO = "credito", "Crédito"

    class Franquicia(models.TextChoices):
        VISA = "visa", "Visa"
        MASTERCARD = "mastercard", "Mastercard"
        AMEX = "amex", "American Express"
        DINERS = "diners", "Diners Club"
        DISCOVER = "discover", "Discover"
        JCB = "jcb", "JCB"

    cliente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tarjetas")
    tipo = models.CharField(max_length=7, choices=Tipo.choices)
    # Franquicia detectada a partir del número (simulación). El CVV nunca se guarda.
    franquicia = models.CharField(max_length=12, choices=Franquicia.choices, blank=True, editable=False)
    mes_vencimiento = models.PositiveSmallIntegerField(null=True, blank=True, editable=False)
    anio_vencimiento = models.PositiveSmallIntegerField(null=True, blank=True, editable=False)
    # Entorno de simulación: se guarda el número FICTICIO completo para mostrarlo en la billetera.
    # El CVV nunca se guarda. Las tarjetas anteriores a este campo se muestran enmascaradas.
    huella = models.CharField(max_length=64, editable=False)
    ultimos_cuatro = models.CharField(max_length=4, editable=False)
    numero_completo = models.CharField(max_length=19, blank=True, default="", editable=False)
    saldo = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["creada_en", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["cliente", "huella"], name="tarjeta_unica_cliente"),
            models.CheckConstraint(condition=Q(saldo__gte=0), name="tarjeta_saldo_no_negativo"),
            models.CheckConstraint(condition=Q(tipo__in=["debito", "credito"]), name="tarjeta_tipo_valido"),
            models.CheckConstraint(condition=Q(mes_vencimiento__isnull=True) | Q(mes_vencimiento__gte=1, mes_vencimiento__lte=12),
                                   name="tarjeta_mes_vencimiento_valido"),
        ]

    @property
    def numero_visible(self):
        """Número ficticio agrupado (4-4-4-4, o 4-6-5 en Amex); enmascarado si no se guardó completo."""
        n = self.numero_completo
        if not n:
            return f"•••• {self.ultimos_cuatro}"
        cortes = (4, 10) if self.franquicia == self.Franquicia.AMEX else tuple(range(4, len(n), 4))
        partes, ini = [], 0
        for c in (*cortes, len(n)):
            partes.append(n[ini:c]); ini = c
        return " ".join(p for p in partes if p)

    @property
    def vencimiento_texto(self):
        if not (self.mes_vencimiento and self.anio_vencimiento):
            return ""
        return f"{self.mes_vencimiento:02d}/{self.anio_vencimiento % 100:02d}"

    @property
    def vencida(self):
        """Una tarjeta es válida hasta el último día de su mes de vencimiento."""
        if not (self.mes_vencimiento and self.anio_vencimiento):
            return False
        from django.utils import timezone
        hoy = timezone.localdate()
        return (self.anio_vencimiento, self.mes_vencimiento) < (hoy.year, hoy.month)

    def __str__(self):
        marca = f"{self.get_franquicia_display()} " if self.franquicia else ""
        return f"{marca}{self.get_tipo_display()} {self.numero_visible}"


class Movimiento(models.Model):
    class Tipo(models.TextChoices):
        RECARGA = "recarga", "Recarga"
        COMPRA = "compra", "Compra simulada"
        REEMBOLSO = "reembolso", "Reembolso"

    tarjeta = models.ForeignKey(Tarjeta, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    valor = models.DecimalField(max_digits=14, decimal_places=2)
    saldo_resultante = models.DecimalField(max_digits=14, decimal_places=2)
    referencia = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    detalle = models.CharField(max_length=160)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(valor__gt=0), name="movimiento_valor_positivo"),
            models.CheckConstraint(condition=Q(saldo_resultante__gte=0), name="movimiento_saldo_no_negativo"),
            models.CheckConstraint(condition=Q(tipo__in=["recarga", "compra", "reembolso"]), name="movimiento_tipo_valido"),
        ]
