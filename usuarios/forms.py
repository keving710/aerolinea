from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from .models import Ciudad, Usuario

OBLIGATORIOS = ["dni", "first_name", "last_name", "fecha_nacimiento", "ciudad_nacimiento", "direccion_facturacion", "genero", "email"]


class LoginForm(AuthenticationForm):
    username = forms.CharField(label="Usuario (ID)", widget=forms.TextInput(attrs={"autofocus": True}))
    password = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput)

    error_messages = {
        "invalid_login": "Usuario o contraseña incorrectos.",
        "inactive": "Esta cuenta está inactiva.",
    }


class _ClavesMixin:
    """Valida dos campos de contraseña iguales y seguros."""

    def clean_claves(self, campo1="password1", campo2="password2"):
        p1 = self.cleaned_data.get(campo1)
        p2 = self.cleaned_data.get(campo2)
        if p1 and p2 and p1 != p2:
            self.add_error(campo2, "Las contraseñas no coinciden.")
        elif p1:
            try:
                password_validation.validate_password(p1, getattr(self, "usuario", None))
            except forms.ValidationError as e:
                self.add_error(campo1, e)


class RegistroClienteForm(_ClavesMixin, forms.ModelForm):
    password1 = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmar contraseña", strip=False, widget=forms.PasswordInput)

    field_order = ["dni", "first_name", "last_name", "fecha_nacimiento", "ciudad_nacimiento",
                   "direccion_facturacion", "genero", "email", "username", "password1", "password2", "foto"]

    class Meta:
        model = Usuario
        fields = ["dni", "first_name", "last_name", "fecha_nacimiento", "ciudad_nacimiento", "direccion_facturacion", "genero", "email", "username", "foto"]
        widgets = {"fecha_nacimiento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
        labels = {"username": "Usuario (ID)"}
        help_texts = {"username": "Con este usuario iniciarás sesión."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre in OBLIGATORIOS:
            self.fields[nombre].required = True
        self.fields["ciudad_nacimiento"].queryset = Ciudad.objects.select_related("departamento")
        self.fields["ciudad_nacimiento"].empty_label = "Selecciona una ciudad"
        self.fields["foto"].required = False
        self.fields["foto"].widget = forms.FileInput(attrs={"accept": ".jpg,.jpeg,.png"})

    def clean(self):
        datos = super().clean()
        self.clean_claves()
        return datos

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.rol = Usuario.Rol.CLIENTE
        usuario.set_password(self.cleaned_data["password1"])
        if commit:
            usuario.save()
        return usuario


class PerfilForm(forms.ModelForm):
    """Perfil de clientes y administradores (HU 6 y HU 7). La foto es opcional."""

    class Meta:
        model = Usuario
        fields = ["dni", "first_name", "last_name", "fecha_nacimiento", "ciudad_nacimiento", "direccion_facturacion", "genero", "email", "foto"]
        widgets = {"fecha_nacimiento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre in OBLIGATORIOS:
            self.fields[nombre].required = True
        self.fields["ciudad_nacimiento"].queryset = Ciudad.objects.select_related("departamento")
        self.fields["ciudad_nacimiento"].empty_label = "Selecciona una ciudad"
        self.fields["foto"].required = False
        self.fields["foto"].widget = forms.FileInput(attrs={"accept": ".jpg,.jpeg,.png"})


class RootCredencialesForm(_ClavesMixin, forms.ModelForm):
    """El root solo puede cambiar su ID (usuario) y su contraseña (HU 4)."""

    password_actual = forms.CharField(label="Contraseña actual", strip=False, widget=forms.PasswordInput)
    password1 = forms.CharField(
        label="Nueva contraseña", strip=False, required=False, widget=forms.PasswordInput,
        help_text="Déjala vacía si solo quieres cambiar el usuario.",
    )
    password2 = forms.CharField(
        label="Confirmar nueva contraseña", strip=False, required=False, widget=forms.PasswordInput
    )

    class Meta:
        model = Usuario
        fields = ["username"]
        labels = {"username": "Usuario (ID)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = self.instance

    def clean_password_actual(self):
        actual = self.cleaned_data["password_actual"]
        if not self.instance.check_password(actual):
            raise forms.ValidationError("La contraseña actual no es correcta.")
        return actual

    def clean(self):
        datos = super().clean()
        self.clean_claves()
        return datos

    def save(self, commit=True):
        usuario = super().save(commit=False)
        if self.cleaned_data.get("password1"):
            usuario.set_password(self.cleaned_data["password1"])
        if commit:
            usuario.save()
        return usuario


class AdministradorNuevoForm(_ClavesMixin, forms.ModelForm):
    """El root crea administradores solo con ID y contraseña (HU 5)."""

    password1 = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmar contraseña", strip=False, widget=forms.PasswordInput)

    class Meta:
        model = Usuario
        fields = ["username"]
        labels = {"username": "Usuario (ID)"}

    def clean(self):
        datos = super().clean()
        self.clean_claves()
        return datos

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.rol = Usuario.Rol.ADMINISTRADOR
        usuario.set_password(self.cleaned_data["password1"])
        if commit:
            usuario.save()
        return usuario