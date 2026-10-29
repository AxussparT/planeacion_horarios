from .validacion_bd import validar_y_registrar_profesor


class profesor:
    def __init__(self, no_cuenta, nombre_completo, periodos, correo_institucional=None, acude_toda_semana='SI'):
        self.no_cuenta = no_cuenta
        self.nombre_completo = nombre_completo
        self.periodos = periodos
        self.correo_institucional = correo_institucional
        self.acude_toda_semana = acude_toda_semana

        self.exito = validar_y_registrar_profesor(
            self.no_cuenta,
            self.nombre_completo,
            self.periodos,
            self.correo_institucional,
            self.acude_toda_semana
        )
