from django.contrib import admin

from .models import Vuelo


@admin.register(Vuelo)
class VueloAdmin(admin.ModelAdmin):
    list_display = ("codigo", "tipo", "origen", "destino", "salida", "estado")
    readonly_fields = ("codigo",)
