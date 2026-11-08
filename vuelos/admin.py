from django.contrib import admin

from .models import Vuelo


@admin.register(Vuelo)
class VueloAdmin(admin.ModelAdmin):
    list_display = ("codigo", "tipo", "origen", "destino", "salida", "estado")
    # La edición se realiza en la vista con rol, bloqueo y reglas de HU 15.
    readonly_fields = tuple(f.name for f in Vuelo._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
