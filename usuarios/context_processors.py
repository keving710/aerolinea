def estado_perfil(request):
    """Avisa en todas las páginas si el administrador aún no completa su perfil (HU 6)."""
    usuario = getattr(request, "user", None)
    pendiente = bool(
        usuario
        and usuario.is_authenticated
        and usuario.es_administrador
        and not usuario.perfil_completo
    )
    return {"perfil_admin_pendiente": pendiente}
