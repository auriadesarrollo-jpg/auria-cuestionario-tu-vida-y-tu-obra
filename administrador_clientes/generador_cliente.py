"""
generador_cliente.py
====================

Administrador de altas de clientes de AUR+IA.

Responsabilidades:

- generar el próximo cliente_id
- normalizar nombres
- crear la estructura completa del cliente
- devolver la ruta creada

Versión: 1.0
"""

from pathlib import Path
import re
import json
from datetime import datetime
import shutil



BASE_PROYECTO = Path(__file__).resolve().parents[2]

BASE_CLIENTES = (
    BASE_PROYECTO /
    "00_Base_Conocimiento_json_Clientes"
)


class GeneradorCliente:

    def generar_cliente_id(self):
        """Genera el próximo cliente_id disponible."""

        BASE_CLIENTES.mkdir(parents=True, exist_ok=True)

        ids = []

        for carpeta in BASE_CLIENTES.iterdir():
            if carpeta.is_dir() and carpeta.name.startswith("USU-"):
                try:
                    numero = int(carpeta.name.split("_")[0].replace("USU-", ""))
                    ids.append(numero)
                except ValueError:
                    continue

        siguiente = max(ids, default=0) + 1

        return f"USU-{siguiente:04d}"

    def normalizar_nombre(self, nombre):
        """Convierte 'Anuar Giménez Tolosa' en 'anuar_gimenez_tolosa'."""
        nombre = nombre.lower()
        nombre = nombre.replace("á", "a")
        nombre = nombre.replace("é", "e")
        nombre = nombre.replace("í", "i")
        nombre = nombre.replace("ó", "o")
        nombre = nombre.replace("ú", "u")
        nombre = nombre.replace("ñ", "n")
        nombre = nombre.replace(" ", "_")
        nombre = nombre.replace(":", "_")
        nombre = nombre.replace("/", "_")
        nombre = nombre.replace("\\", "_")
        nombre = nombre.replace(".", "_")
        nombre = nombre.replace(",", "_")
        nombre = nombre.replace("(", "")
        nombre = nombre.replace(")", "")
        nombre = nombre.replace(";", "_")
        nombre = nombre.replace("*", "_")
        nombre = nombre.replace("?", "_")
        nombre = nombre.replace("\"", "")
        nombre = nombre.replace("<", "_")
        nombre = nombre.replace(">", "_")
        nombre = nombre.replace("|", "_")

        return nombre
    
    def crear_base_conocimiento(self, carpeta, cliente_id, nombre):

        plantilla = (
            BASE_CLIENTES
            / "USU-0001_anuar_gimenez_tolosa"
            / "USU-0001_anuar_gimenez_tolosa_base_conocimiento.json"
        )

        destino = carpeta / f"{cliente_id}_{self.normalizar_nombre(nombre)}_base_conocimiento.json"

        shutil.copy2(plantilla, destino)

        return destino

    def crear_carpeta_cliente(self, cliente_id, nombre_slug):
        """Crea la carpeta principal del cliente."""

        carpeta = BASE_CLIENTES / f"{cliente_id}_{nombre_slug}"

        carpeta.mkdir(parents=True, exist_ok=True)

        return carpeta

    def crear_cliente_config(self, carpeta, cliente_id, nombre):

        datos = {
            "cliente_id": cliente_id,
            "nombre": nombre,
            "estado": "activo",
            "fecha_alta": datetime.now().strftime("%Y-%m-%d"),
            "plan": "gratuito_individual"
        }

        ruta = carpeta / "cliente.json"

        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=4, ensure_ascii=False)

        return ruta


    def crear_memoria_db(self, carpeta):

        ruta = carpeta / "memoria.db"

        ruta.touch()

        return ruta

    def crear_directorio_reportes(self, carpeta):

        ruta = carpeta / "reportes"

        ruta.mkdir(exist_ok=True)

        return ruta

    def crear_directorio_logs(self, carpeta):

        ruta = carpeta / "logs"

        ruta.mkdir(exist_ok=True)

        return ruta

    def buscar_cliente_por_email(self, email):

        from models import PerfilCliente

        perfil = PerfilCliente.query.filter_by(
            email_contacto=email
        ).first()

        if not perfil:
            return None

        return perfil.cliente_id
    

    def obtener_carpeta(self, cliente_id):

        for carpeta in BASE_CLIENTES.iterdir():

            if carpeta.is_dir():

                if carpeta.name.startswith(cliente_id):

                    return carpeta

        return None

    def alta_cliente(self, nombre):

        cliente_id = self.generar_cliente_id()

        carpeta = self.crear_carpeta_cliente(
            cliente_id,
            self.normalizar_nombre(nombre)
        )

        self.crear_cliente_config(
            carpeta,
            cliente_id,
            nombre
        )

        self.crear_base_conocimiento(
            carpeta,
            cliente_id,
            nombre
        )

        self.crear_memoria_db(carpeta)

        self.crear_directorio_reportes(carpeta)

        self.crear_directorio_logs(carpeta)

        return cliente_id, carpeta

if __name__ == "__main__":

    print("\n========================================")
    print(" AUR+IA - GeneradorCliente")
    print("========================================")
    print("Este módulo es INTERNO.")
    print("No debe ejecutarse directamente.")
    print("Debe ser invocado únicamente por:")
    print("  • Administrador de Clientes")
    print("  • Backend de AUR+IA")
    print("========================================\n")

    