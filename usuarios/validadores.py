from django.core.exceptions import ValidationError


class ComplejidadPasswordValidator:
    """Exige mayúscula, minúscula, número, carácter especial y ningún espacio."""

    def validate(self, password, user=None):
        errores = []

        if any(c.isspace() for c in password):
            errores.append(ValidationError(
                "La contraseña no puede contener espacios.", code="password_sin_espacios"))
        if not any(c.isupper() for c in password):
            errores.append(ValidationError(
                "La contraseña debe tener al menos una letra mayúscula.", code="password_sin_mayuscula"))
        if not any(c.islower() for c in password):
            errores.append(ValidationError(
                "La contraseña debe tener al menos una letra minúscula.", code="password_sin_minuscula"))
        if not any(c.isdigit() for c in password):
            errores.append(ValidationError(
                "La contraseña debe tener al menos un número.", code="password_sin_numero"))
        if not any(not c.isalnum() and not c.isspace() for c in password):
            errores.append(ValidationError(
                "La contraseña debe tener al menos un carácter especial (por ejemplo ! @ # $ % - _).",
                code="password_sin_especial"))

        if errores:
            raise ValidationError(errores)

    def get_help_text(self):
        return (
            "Debe tener al menos una mayúscula, una minúscula, un número y un carácter "
            "especial, y no puede contener espacios."
        )