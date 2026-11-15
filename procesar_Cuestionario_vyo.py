import os
import json
import re
import mimetypes
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, EmailStr, Field


# --- SCHEMAS DE VALIDACIÓN (Pydantic) ---

class CategoriaSchema(BaseModel):
    enabled: bool = False
    modo: str = ""
    tono: str = ""
    personalizado: str = ""
    remitentes: str = ""

class CuestionarioSchema(BaseModel):
    nombre: str = Field(..., min_length=2)
    email_contacto: EmailStr
    email_servicio: str = ""
    clave_aplicacion: str = ""
    celular: str = ""
    apodo: str = ""
    actividades: str = ""
    familia: str = ""
    amigos: str = ""
    mascotas: str = ""
    fechas: str = ""
    vida_extra: str = ""
    tarea_profesional: str = ""
    tipo_empleo: str = ""
    empresa: str = ""
    companeros: str = ""
    social_extra: str = ""
    obra_extra: str = ""
    conocimiento_manual: str = ""
    tiene_telegram: str = ""
    preferencia_whatsapp: str = ""
    es_jubilado: str = ""
    jubilado_comentario: str = ""
    categorias: Dict[str, Any] = {}


# --- FUNCIONES DE TRANSFORMACIÓN Y PERSISTENCIA ---

def generar_base_conocimiento(datos_cliente: dict, cliente_id: str, carpeta) -> dict:
    """
    Genera y guarda el archivo JSON de la base de conocimiento para un cliente (USU-XXXX),
    asegurando la creación física de la carpeta principal, subcarpetas y el archivo usuario.json.
    """
    # 1. Convertir 'carpeta' a Path para evitar errores de tipo (str / str)
    carpeta_path = Path(carpeta)

    # 2. Crear la carpeta principal del cliente si no existe
    carpeta_path.mkdir(parents=True, exist_ok=True)

    # 3. Crear las subcarpetas requeridas
    (carpeta_path / "Biblioteca_de_ARCHIVOS_PERSONALES").mkdir(exist_ok=True)
    (carpeta_path / "logs").mkdir(exist_ok=True)
    (carpeta_path / "reportes").mkdir(exist_ok=True)
    (carpeta_path / "memoria").mkdir(exist_ok=True)

    # 4. Definir la ruta del archivo JSON principal (usuario.json)
    json_path = carpeta_path / "usuario.json"
    
    # Preservar conocimiento manual previo si ya existía el archivo
    conocimiento_manual_previo = ""
    categorias_previas = {}
    fecha_alta_previa = ""
    perfil_previo = {}
    profesional_previo = {}
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                datos_previos = json.load(f)
                conocimiento_manual_previo = datos_previos.get("conocimiento_manual", "")
                categorias_previas = datos_previos.get("categorias", {})
                fecha_alta_previa = datos_previos.get("metadata", {}).get("fecha_alta", "")   # NUEVA
                perfil_previo = datos_previos.get("perfil_usuario", {})
                profesional_previo = datos_previos.get("esfera_profesional", {})
        except Exception as e:
            print(f"⚠️ No se pudo leer el JSON anterior: {e}")

    # 5. Estructura del JSON de Base de Conocimiento v3.2
    json_cliente = {
        "metadata": {
            "version": "3.2",
            "estado_servicio": "activo",
            "cliente_id": cliente_id,
            "fecha_alta": fecha_alta_previa or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "fecha_ultima_actualizacion": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "autor": "AURIA_2 — Onboarding Automático",
            "plan_servicio": "gratuito_jubilado" if datos_cliente.get("es_jubilado") == "si" else "gratuito_individual"
        },
        "perfil_usuario": {
            "nombre_completo": datos_cliente.get("nombre", ""),
            "apodo_preferido": datos_cliente.get("apodo", perfil_previo.get("apodo_preferido", "")),
            "tratamiento": "vos",
            "tipo_perfil": "individual",
            "segmento": "A_individual",
            "idiomas": ["español"],
            "zona_horaria": "America/Argentina/Buenos_Aires",
            "actividades_y_hobbies": datos_cliente.get("actividades", perfil_previo.get("actividades_y_hobbies", "")),
            "vinculos_y_entorno": {
                "familia": datos_cliente.get("familia", perfil_previo.get("vinculos_y_entorno", {}).get("familia", "")),
                "amigos": datos_cliente.get("amigos", perfil_previo.get("vinculos_y_entorno", {}).get("amigos", "")),
                "mascotas": datos_cliente.get("mascotas", perfil_previo.get("vinculos_y_entorno", {}).get("mascotas", "")),
                "fechas_importantes": datos_cliente.get("fechas", perfil_previo.get("vinculos_y_entorno", {}).get("fechas_importantes", ""))
            }
        },
        "contacto": {
            "email_principal": datos_cliente.get("email_contacto", ""),
            "email_servicio": datos_cliente.get("email_servicio", ""),
            "celular_whatsapp": datos_cliente.get("celular", ""),
            "telegram_chat_id": "",
            "nota_seguridad": "La App Password va ÚNICAMENTE en el archivo .env — nunca en este JSON"
        },
        "esfera_profesional": {
            "rol": datos_cliente.get("tarea_profesional", ""),
            "tipo_empleo": datos_cliente.get("tipo_empleo", ""),
            "empresa_o_proyecto": datos_cliente.get("empresa", ""),
            "companeros_clave": datos_cliente.get("companeros", ""),
            "fricciones_operativas": datos_cliente.get("fricciones_operativas", ""),
            "prioridades_delegacion": datos_cliente.get("prioridades_delegacion", ""),
            "social_extra": datos_cliente.get("social_extra", ""),
            "obra_extra": datos_cliente.get("obra_extra", ""),
            "vida_extra": datos_cliente.get("vida_extra", profesional_previo.get("vida_extra", "")),
            "contactos_prioritarios": [],
            "dominios_prioritarios": [],
            "palabras_clave_urgentes": []
        },
        "conocimiento_manual": datos_cliente.get("conocimiento_manual", conocimiento_manual_previo),
        "biblioteca_manual": [],
        "categorias": datos_cliente.get("categorias", categorias_previas)
    }

    # 5b. Respaldo automático de la versión anterior (antes de sobrescribir)
    if json_path.exists():
        try:
            carpeta_respaldos = carpeta_path / "respaldos"
            carpeta_respaldos.mkdir(exist_ok=True)
            marca = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(json_path, carpeta_respaldos / f"usuario_{marca}.json")
            # Conservar solo los 20 respaldos más recientes
            for viejo in sorted(carpeta_respaldos.glob("usuario_*.json"))[:-20]:
                viejo.unlink()
        except Exception as e:
            print(f"⚠️ No se pudo crear el respaldo de usuario.json: {e}")

    # 6. Guardar el archivo JSON físico
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_cliente, f, ensure_ascii=False, indent=4)

    print(f"✅ Base de Conocimiento creada/actualizada exitosamente en: {json_path}")

    sincronizar_biblioteca_json(str(carpeta_path), cliente_id)

    return json_cliente


def sincronizar_biblioteca_json(carpeta_cliente_str: str, cliente_id: str):
    """
    Sincroniza los archivos de la Biblioteca de ARCHIVOS PERSONALES con el archivo JSON del cliente.
    """
    carpeta = Path(carpeta_cliente_str)
    biblioteca = carpeta / "Biblioteca_de_ARCHIVOS_PERSONALES"
    json_path = carpeta / "usuario.json"

    if not json_path.exists():
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            datos = json.load(f)

        datos["biblioteca_manual"] = []

        if biblioteca.exists():
            for f_archivo in biblioteca.iterdir():
                if f_archivo.is_file():
                    datos["biblioteca_manual"].append({
                        "nombre": f_archivo.name,
                        "tamaño": f_archivo.stat().st_size,
                        "tipo": mimetypes.guess_type(f_archivo.name)[0] or "application/octet-stream",
                        "fecha": f_archivo.stat().st_mtime
                    })

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=4)

        print(f"🔄 Biblioteca sincronizada para {cliente_id}")
    except Exception as e:
        print(f"❌ Error al sincronizar biblioteca de {cliente_id}: {e}")