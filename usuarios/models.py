from datetime import date

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


def validar_foto(archivo):
    """La foto debe ser JPG o PNG y pesar máximo 2 MB (HU 6 y HU 7)."""
    from django.conf import settings

    nombre = (archivo.name or "").lower()
    if not nombre.endswith((".jpg", ".jpeg", ".png")):
        raise ValidationError("La foto debe estar en formato JPG o PNG.")
    if archivo.size > settings.FOTO_PERFIL_MAX_BYTES:
        raise ValidationError("La foto no puede superar los 2 MB.")


def validar_fecha_nacimiento(valor):
    """La fecha no puede ser futura, la persona debe ser mayor de edad y la edad debe ser realista."""
    hoy = date.today()
    if valor > hoy:
        raise ValidationError("La fecha de nacimiento no puede ser futura.")
    edad = hoy.year - valor.year - ((hoy.month, hoy.day) < (valor.month, valor.day))
    if edad < 18:
        raise ValidationError("Debes ser mayor de 18 años.")
    if edad > 120:
        raise ValidationError("La fecha de nacimiento no es válida.")


class Departamento(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Ciudad(models.Model):
    nombre = models.CharField(max_length=100)
    departamento = models.ForeignKey(
        Departamento, on_delete=models.PROTECT, related_name="ciudades"
    )

    class Meta:
        ordering = ["departamento__nombre", "nombre"]
        unique_together = [("nombre", "departamento")]
        verbose_name_plural = "ciudades"

    def __str__(self):
        return f"{self.nombre}, {self.departamento.nombre}"


class Usuario(AbstractUser):
    class Rol(models.TextChoices):
        ROOT = "root", "Root"
        ADMINISTRADOR = "administrador", "Administrador"
        CLIENTE = "cliente", "Cliente"

    first_name = models.CharField("nombres", max_length=150, blank=True)
    last_name = models.CharField("apellidos", max_length=150, blank=True)
    email = models.EmailField("correo electrónico", unique=True, null=True, blank=True)
    dni = models.CharField(
        "documento de identidad", max_length=20, unique=True, null=True, blank=True
    )
    fecha_nacimiento = models.DateField(
        "fecha de nacimiento",
        null=True,
        blank=True,
        validators=[validar_fecha_nacimiento],
    )
    ciudad_nacimiento = models.ForeignKey(
        Ciudad,
        verbose_name="lugar de nacimiento",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="nacidos",
    )
    direccion_facturacion = models.CharField("dirección de facturación", max_length=200, blank=True)

    class Genero(models.TextChoices):
        FEMENINO = "femenino", "Femenino"
        MASCULINO = "masculino", "Masculino"
        OTRO = "otro", "Otro"

    genero = models.CharField("género", max_length=10, choices=Genero.choices, blank=True)
    telefono = models.CharField("teléfono", max_length=20, blank=True)
    foto = models.ImageField(
        "foto de perfil",
        upload_to="perfiles/",
        blank=True,
        null=True,
        validators=[validar_foto],
    )
    rol = models.CharField(max_length=15, choices=Rol.choices, default=Rol.CLIENTE)

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    def save(self, *args, **kwargs):
        # Los campos únicos opcionales se guardan como NULL, no como "".
        if not self.email:
            self.email = None
        if not self.dni:
            self.dni = None
        super().save(*args, **kwargs)

    @property
    def nombre_completo(self):
        return f"{self.first_name} {self.last_name}".strip() or self.username

    @property
    def iniciales(self):
        partes = [x for x in (self.first_name, self.last_name) if x]
        texto = "".join(x[0] for x in partes[:2]) or self.username[:2]
        return texto.upper()

    @property
    def es_root(self):
        return self.rol == self.Rol.ROOT

    @property
    def es_administrador(self):
        return self.rol == self.Rol.ADMINISTRADOR

    @property
    def es_cliente(self):
        return self.rol == self.Rol.CLIENTE

    @property
    def perfil_completo(self):
        """Datos obligatorios del perfil (HU 6)."""
        return all([
            self.first_name, self.last_name, self.dni, self.fecha_nacimiento,
            self.ciudad_nacimiento, self.direccion_facturacion, self.genero, self.email,
        ])

    def __str__(self):
        return f"{self.nombre_completo} ({self.get_rol_display()})"