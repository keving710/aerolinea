from django.contrib import admin

from .models import Reserva, Tiquete


class TiqueteInline(admin.TabularInline):
    model = Tiquete
    extra = 0
    can_delete = False
    fields = readonly_fields = ("vuelo", "tramo", "estado", "nombres", "apellidos", "documento", "clase", "silla", "valor")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    """Solo lectura: todo cambio de inventario y dinero pasa por reservas.servicios."""

    list_display = ("codigo", "cliente", "estado", "trayecto", "creada_en")
    inlines = [TiqueteInline]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in Reserva._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
