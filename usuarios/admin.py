from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "rol", "email")
    list_filter = ("rol", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("Datos adicionales", {"fields": ("rol", "dni", "telefono", "foto")}),
    )
