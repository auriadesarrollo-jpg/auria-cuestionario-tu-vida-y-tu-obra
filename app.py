import sys
import os
import time
import json
from pathlib import Path


# Configurar rutas base e incluir la carpeta contenedora de administrador_clientes
CARPETA_BACKEND = Path(__file__).resolve().parent
CARPETA_RAIZ = CARPETA_BACKEND.parent
RUTA_ADMIN_CLIENTES = CARPETA_RAIZ / "06_Administrador_Clientes"

# Inyectar las rutas necesarias en sys.path
for ruta in [CARPETA_BACKEND, CARPETA_RAIZ, RUTA_ADMIN_CLIENTES]:
    ruta_str = str(ruta)
    if ruta_str not in sys.path:
        sys.path.insert(0, ruta_str)

import re
import logging
from flask import Flask, request, jsonify, send_file, send_from_directory, session
import secrets
from datetime import timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from models import init_db, User, PersonalProfile, ProfessionalProfile, CategoryConfig, PerfilCliente


# Importaciones de módulos locales (ahora encuentran la ruta exacta)
from procesar_Cuestionario_vyo import generar_base_conocimiento, sincronizar_biblioteca_json
from administrador_clientes.generador_cliente import GeneradorCliente

# Definimos la raíz del proyecto subiendo un nivel desde auria_backend
BASE_PROYECTO = Path(__file__).resolve().parents[1]

# Agregamos la carpeta del procesador al sys.path
RUTA_PROCESADOR = BASE_PROYECTO / "03_Documentacion_del_Proyecto" / "todo_Cuestionario_VyO"
if str(RUTA_PROCESADOR) not in sys.path:
    sys.path.insert(0, str(RUTA_PROCESADOR))

print("Tiene atributo:", hasattr(User, "clave_aplicacion_cifrada"))
print(User.__table__.columns.keys())

from security import SecureKeyManager
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ----------------- RUTA A BASE DE DATOS DEFINITIVA (LOCAL O NUBE) -----------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CARPETA_RAIZ = os.path.abspath(os.path.join(BASE_DIR, ".."))

# Buscamos si existe una variable de entorno para la base de datos externa (Supabase)
database_url = os.environ.get('DATABASE_URL')

if database_url:
    # Corrección de prefijo si fuera necesario para SQLAlchemy
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    DB_PATH_DISPLAY = "Base de datos externa en la nube (Supabase)"
    SessionLocal = init_db(database_url)
else:
    # Comportamiento tradicional local (SQLite)
    DB_PATH = os.path.join(CARPETA_RAIZ, "instance", "aur_ia_data.db")
    DB_PATH_DISPLAY = DB_PATH
    SessionLocal = init_db(f"sqlite:///{DB_PATH}")

# ------------------------------------------------------------------------
print("===================================")
print("BASE DE DATOS UTILIZADA (OFICIAL):")
print(DB_PATH_DISPLAY)
print("===================================")

security_manager = SecureKeyManager()

# ---------------- ACCESO PERSONAL: secreto de sesión y claves de acceso ----------------
def _secreto_de_sesion():
    """Clave secreta con la que se firman las sesiones. Se crea una vez y se guarda en la carpeta instance."""
    ruta = os.path.join(CARPETA_RAIZ, "instance", "secreto_sesion.key")
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            return f.read().strip()
    secreto = secrets.token_hex(32)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(secreto)
    return secreto


app.secret_key = _secreto_de_sesion()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=timedelta(days=30))

ALFABETO_CLAVES = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin letras ni números que se confunden (I, O, 0, 1)
MAX_INTENTOS = 5          # intentos fallidos permitidos...
VENTANA_SEGUNDOS = 600    # ...dentro de estos 10 minutos
INTENTOS_FALLIDOS = {}


def _normalizar_clave(clave):
    """Pasa la clave a mayúsculas y le saca guiones y espacios: 'k7m2-qx9p' y 'K7M2QX9P' valen igual."""
    return "".join(c for c in (clave or "").upper() if c.isalnum())


def _generar_clave_acceso():
    letras = "".join(secrets.choice(ALFABETO_CLAVES) for _ in range(8))
    return letras[:4] + "-" + letras[4:]


def _demasiados_intentos(codigo):
    ahora = time.time()
    recientes = [t for t in INTENTOS_FALLIDOS.get(codigo, []) if ahora - t < VENTANA_SEGUNDOS]
    INTENTOS_FALLIDOS[codigo] = recientes
    return len(recientes) >= MAX_INTENTOS


def _registrar_intento_fallido(codigo):
    INTENTOS_FALLIDOS.setdefault(codigo, []).append(time.time())


MINUTOS_SIN_ACTIVIDAD = 30   # una sesión sin "Recordarme" se cierra sola después de estos minutos sin actividad


def _sesion_vigente(renovar=True):
    """Devuelve el código de la persona si su sesión sigue vigente. Si venció por inactividad, la cierra y devuelve None."""
    codigo = session.get("codigo_usuario")
    if not codigo:
        return None
    if not session.get("recordar"):
        ahora = time.time()
        if ahora - session.get("ultimo_acceso", 0) > MINUTOS_SIN_ACTIVIDAD * 60:
            session.clear()
            return None
        if renovar:
            session["ultimo_acceso"] = ahora
    return codigo


def _acceso_permitido(codigo_usuario):
    """True solo si la persona ya demostró su identidad (código + clave), su sesión sigue vigente y el código coincide."""
    codigo = (codigo_usuario or "").strip().upper()
    return bool(codigo) and _sesion_vigente() == codigo


def _sin_cache(respuesta):
    """Evita que el navegador guarde en su memoria respuestas con datos personales."""
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AUR+IA.Backend")

def _nombre_para_carpeta(nombre):
    """Convierte un nombre en un texto seguro para el nombre de una carpeta en Windows (sin tildes ni símbolos)."""
    import unicodedata
    texto = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^A-Za-z0-9]+", "_", texto).strip("_").lower()
    return texto[:40] or "usuario"

def sanitize_input(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r'<[^>]*>', '', text)
    return clean.strip()

def _buscar_carpeta_usuario(codigo_usuario):
    """
    Busca la carpeta física de un usuario por su código (USU-XXXX).
    Devuelve la ruta completa si la encuentra, o None si no existe.
    """
    CARPETA_RAIZ = os.path.abspath(os.path.join(BASE_DIR, ".."))
    BASE_CONOCIMIENTO_DIR = os.path.join(CARPETA_RAIZ, "00_Base_Conocimiento_json_Clientes")

    if not os.path.exists(BASE_CONOCIMIENTO_DIR):
        return None

    for item in os.listdir(BASE_CONOCIMIENTO_DIR):
        if item.startswith(codigo_usuario):
            return os.path.join(BASE_CONOCIMIENTO_DIR, item)

    return None

def _clave_guardada(email_contacto):
    """True si ya hay una clave de aplicación cifrada guardada para ese email (nunca devuelve la clave)."""
    if not email_contacto or email_contacto == "modo_manual@local.com":
        return False
    sesion = SessionLocal()
    try:
        user = sesion.query(User).filter_by(email_contacto=email_contacto).first()
        return bool(user and user.clave_aplicacion_cifrada)
    except Exception:
        return False
    finally:
        sesion.close()

def sincronizar_con_procesador(data, email_contacto, clave_cifrada):
    """
    PUENTE: copia a las tablas que lee pipeline.py (users, personal_profiles,
    professional_profiles y category_configs) lo que la persona cargó en el Cuestionario.
    Solo se usa en Modo AUTOMÁTICO (email real). Usa su propia sesión: si algo falla,
    el guardado normal del Cuestionario no se ve afectado.
    """
    flujo = (data.get("flujo") or "profesional").lower()
    if flujo not in ("integral", "profesional"):
        flujo = "profesional"

    sesion = SessionLocal()
    try:
        user = sesion.query(User).filter_by(email_contacto=email_contacto).first()
        if not user:
            user = User(email_contacto=email_contacto)
            sesion.add(user)
            sesion.flush()

        user.email_servicio = sanitize_input(data.get("email_servicio") or "auria.desarrollo@gmail.com")
        user.nombre = sanitize_input(data.get("nombre", ""))
        user.celular = sanitize_input(data.get("celular", ""))
        user.flujo_activo = flujo
        if not user.correo_actual:
            user.correo_actual = email_contacto
        if clave_cifrada:  # solo se reemplaza si la persona escribió una clave nueva
            user.clave_aplicacion_cifrada = clave_cifrada

        # Perfil personal: solo se actualiza en vista INTEGRAL (en PROFESIONAL no se toca)
        personal = sesion.query(PersonalProfile).filter_by(user_id=user.id).first()
        if not personal:
            personal = PersonalProfile(user_id=user.id)
            sesion.add(personal)
        if flujo == "integral":
            personal.apodo = sanitize_input(data.get("apodo", ""))
            personal.actividades = sanitize_input(data.get("actividades", ""))
            personal.familia = sanitize_input(data.get("familia", ""))
            personal.amigos = sanitize_input(data.get("amigos", ""))
            personal.mascotas = sanitize_input(data.get("mascotas", ""))
            personal.fechas = sanitize_input(data.get("fechas", ""))
            personal.vida_extra = sanitize_input(data.get("vida_extra", ""))

        # Perfil profesional
        prof = sesion.query(ProfessionalProfile).filter_by(user_id=user.id).first()
        if not prof:
            prof = ProfessionalProfile(user_id=user.id)
            sesion.add(prof)
        prof.tarea_profesional = sanitize_input(data.get("tarea_profesional", ""))
        prof.fricciones_operativas = sanitize_input(data.get("fricciones_operativas", ""))
        prof.prioridades_delegacion = sanitize_input(data.get("prioridades_delegacion", ""))
        prof.tipo_empleo = sanitize_input(data.get("tipo_empleo", ""))
        prof.empresa = sanitize_input(data.get("empresa", ""))
        prof.companeros = sanitize_input(data.get("companeros", ""))
        prof.social_extra = sanitize_input(data.get("social_extra", ""))
        prof.obra_extra = sanitize_input(data.get("obra_extra", ""))

        # Las 9 categorías
        categorias_json = data.get("categorias") or {}
        for i in range(1, 10):
            cat_db = sesion.query(CategoryConfig).filter_by(user_id=user.id, category_number=i).first()
            if not cat_db:
                cat_db = CategoryConfig(user_id=user.id, category_number=i, category_name=f"Categoría {i}")
                sesion.add(cat_db)
            cat_data = categorias_json.get(str(i)) or {}
            cat_db.enabled = cat_data.get("enabled", True)
            cat_db.modo = cat_data.get("modo", "revision")
            cat_db.tono = sanitize_input(cat_data.get("tono", ""))
            cat_db.personalizado = sanitize_input(cat_data.get("personalizado", ""))
            cat_db.remitentes = sanitize_input(cat_data.get("remitentes", ""))

        sesion.commit()
        print(f"🔗 Puente al procesador: datos copiados a la base para {email_contacto}")
    except Exception:
        sesion.rollback()
        raise
    finally:
        sesion.close()

@app.route('/ver-archivo/<cliente_id>/<nombre_archivo>', methods=['GET'])
def ver_archivo(cliente_id, nombre_archivo):
    if not _acceso_permitido(cliente_id):
        return "Acceso no autorizado. Volvé al Cuestionario e ingresá con tu código y tu clave de acceso.", 401
    carpeta_usuario = _buscar_carpeta_usuario(cliente_id)
    if not carpeta_usuario:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404

    destino_biblioteca = os.path.join(carpeta_usuario, "Biblioteca_de_ARCHIVOS_PERSONALES")
    return send_from_directory(destino_biblioteca, nombre_archivo)


@app.route('/descargar-archivo/<cliente_id>/<nombre_archivo>', methods=['GET'])
def descargar_archivo(cliente_id, nombre_archivo):
    if not _acceso_permitido(cliente_id):
        return "Acceso no autorizado. Volvé al Cuestionario e ingresá con tu código y tu clave de acceso.", 401
    carpeta_usuario = _buscar_carpeta_usuario(cliente_id)
    if not carpeta_usuario:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404

    destino_biblioteca = os.path.join(carpeta_usuario, "Biblioteca_de_ARCHIVOS_PERSONALES")
    return send_from_directory(destino_biblioteca, nombre_archivo, as_attachment=True)


@app.route('/eliminar-archivo/<cliente_id>/<nombre_archivo>', methods=['DELETE'])
def eliminar_archivo(cliente_id, nombre_archivo):
    if not _acceso_permitido(cliente_id):
        return jsonify({"status": "error", "message": "Necesitás ingresar con tu código y tu clave de acceso."}), 401
    carpeta_usuario = _buscar_carpeta_usuario(cliente_id)
    if not carpeta_usuario:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404

    destino_biblioteca = os.path.join(carpeta_usuario, "Biblioteca_de_ARCHIVOS_PERSONALES")
    ruta_archivo = os.path.join(destino_biblioteca, nombre_archivo)

    if not os.path.exists(ruta_archivo):
        return jsonify({"status": "error", "message": "Archivo no encontrado"}), 404

    try:
        os.remove(ruta_archivo)
        sincronizar_biblioteca_json(carpeta_usuario, cliente_id)
        return jsonify({"status": "success", "message": f'"{nombre_archivo}" fue eliminado correctamente.'}), 200
    except Exception as e:
        print(f"⚠️ Error al eliminar archivo: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/eliminar-archivos', methods=['POST'])
def eliminar_archivos():
    try:
        datos = request.get_json(silent=True) or {}
        codigo_usuario = (datos.get("codigo_usuario") or "").strip().upper()
        nombres = datos.get("nombres") or []

        if not codigo_usuario:
            return jsonify({"status": "error", "message": "Falta el código de usuario."}), 400
        if not _acceso_permitido(codigo_usuario):
            return jsonify({"status": "error", "message": "Necesitás ingresar con tu código y tu clave de acceso."}), 401
        if not isinstance(nombres, list) or not nombres:
            return jsonify({"status": "error", "message": "No se indicó ningún archivo."}), 400

        carpeta_usuario = _buscar_carpeta_usuario(codigo_usuario)
        if not carpeta_usuario:
            return jsonify({"status": "error", "message": f"No se encontró la carpeta de {codigo_usuario}."}), 404

        destino_biblioteca = os.path.join(carpeta_usuario, "Biblioteca_de_ARCHIVOS_PERSONALES")
        eliminados = []
        no_encontrados = []
        for nombre in nombres:
            nombre_archivo = os.path.basename(str(nombre))
            ruta = os.path.join(destino_biblioteca, nombre_archivo)
            if nombre_archivo and os.path.isfile(ruta):
                os.remove(ruta)
                eliminados.append(nombre_archivo)
            else:
                no_encontrados.append(nombre_archivo)

        # La lista de usuario.json se arma una sola vez, leyendo la carpeta real
        sincronizar_biblioteca_json(carpeta_usuario, codigo_usuario)
        print(f"🗑 {len(eliminados)} archivo(s) eliminado(s) de la Biblioteca de {codigo_usuario}")

        return jsonify({
            "status": "success",
            "message": f"{len(eliminados)} archivo(s) eliminado(s).",
            "eliminados": eliminados,
            "no_encontrados": no_encontrados
        }), 200

    except Exception as e:
        print(f"⚠️ Error al eliminar archivos: {e}")
        return jsonify({"status": "error", "message": "No se pudieron eliminar los archivos. Intentá de nuevo."}), 500

@app.route('/enviar-cuestionario', methods=['POST'])
def enviar_cuestionario():
    session_db = SessionLocal()
    try:
        data = request.get_json() or request.form.to_dict()
        email_contacto = data.get("email_contacto") or data.get("correo_actual") or "modo_manual@local.com"
        nombre = data.get("nombre", "Usuario").strip()
        codigo_usuario_ingresado = (data.get("codigo_usuario") or data.get("codigo_usu") or "").strip().upper()

        # --- Protección: no aceptar un formulario sin nombre (evita borrar datos por error) ---
        if not nombre:
            return jsonify({"status": "error", "message": "Por favor, escribí tu nombre completo antes de enviar."}), 400

        # --- Modo AUTOMÁTICO = email real. Validar y cifrar la clave de aplicación ANTES de guardar nada ---
        es_automatico = email_contacto != "modo_manual@local.com"
        clave_raw = (data.get("clave_aplicacion") or "").replace(" ", "").strip()
        clave_cifrada = None
        if es_automatico and clave_raw:
            try:
                clave_cifrada = security_manager.encrypt_credential(clave_raw)
            except ValueError as ve:
                return jsonify({"status": "error", "message": str(ve)}), 400

        # 1. BUSCAR A LA PERSONA: solo por código, y solo si ya demostró su identidad en esta sesión
        perfil = None
        if codigo_usuario_ingresado:
            perfil = session_db.query(PerfilCliente).filter(
                PerfilCliente.codigo_usuario == codigo_usuario_ingresado
            ).first()
            if not perfil:
                return jsonify({"status": "error", "message": "Ese código de usuario no existe. Revisalo, o dejá el campo vacío si es tu primera vez."}), 404
            if not _acceso_permitido(perfil.codigo_usuario):
                return jsonify({"status": "error", "message": "Para modificar tus datos primero ingresá con tu código y tu clave de acceso (botón RECARGAR MIS DATOS)."}), 401

        # 1b. Un correo = una persona: si el correo ya está vinculado a OTRA cuenta, se rechaza (evita pisar la configuración de otra persona)
        if es_automatico:
            codigo_propio = perfil.codigo_usuario if perfil else ""
            for otra in session_db.query(PerfilCliente).filter(PerfilCliente.codigo_usuario != codigo_propio).all():
                if (otra.email_contacto or "").strip().lower() == email_contacto.strip().lower():
                    return jsonify({"status": "error", "message": "Ese correo ya está vinculado a otra cuenta de AUR+IA. Si es tuyo y perdiste tu acceso, escribinos por WhatsApp."}), 409

        # 2. CREAR O ACTUALIZAR EL REGISTRO SQL (todavía sin confirmar)
        clave_acceso_nueva = None
        if perfil:
            codigo_usuario = perfil.codigo_usuario

            # Persona con el correo conectado (Modo AUTOMÁTICO): si envía desde el Modo MANUAL, se conserva su correo y sus categorías
            correo_actual = (perfil.email_contacto or "").strip()
            if correo_actual not in ("", "modo_manual@local.com") and not es_automatico:
                email_contacto = correo_actual
                data["email_contacto"] = correo_actual
                carpeta_previa = _buscar_carpeta_usuario(codigo_usuario)
                ruta_previa = os.path.join(carpeta_previa, "usuario.json") if carpeta_previa else None
                if ruta_previa and os.path.exists(ruta_previa):
                    with open(ruta_previa, "r", encoding="utf-8") as f:
                        previo = json.load(f)
                    if previo.get("categorias"):
                        data["categorias"] = previo["categorias"]
                print(f"🛡️ {codigo_usuario} ya está en Modo AUTOMÁTICO: se conserva su correo y sus categorías")

            perfil.nombre = nombre
            perfil.email_contacto = email_contacto

            perfil.email_servicio = data.get("email_servicio", perfil.email_servicio)
            perfil.celular = data.get("celular", perfil.celular)
            print(f"🔄 Actualizando usuario en BD: {codigo_usuario}")
        else:
            ultimo = session_db.query(PerfilCliente).order_by(PerfilCliente.id.desc()).first()
            siguiente_num = (ultimo.id + 1) if ultimo else 1
            codigo_usuario = f"USU-{siguiente_num:04d}"
            clave_acceso_nueva = _generar_clave_acceso()

            perfil = PerfilCliente(
                codigo_usuario=codigo_usuario,
                cliente_id=codigo_usuario,
                nombre=nombre,
                email_contacto=email_contacto,
                email_servicio=data.get("email_servicio", ""),
                celular=data.get("celular", ""),
                clave_acceso_hash=generate_password_hash(_normalizar_clave(clave_acceso_nueva))
            )
            session_db.add(perfil)
            print(f"✨ Registrando nuevo usuario en BD: {codigo_usuario}")

        # Se reserva el número de la persona, pero todavía NO se confirma
        session_db.flush()

        # 3. GENERAR CARPETA FÍSICA Y ARCHIVO JSON
        CARPETA_RAIZ = os.path.abspath(os.path.join(BASE_DIR, ".."))
        BASE_CONOCIMIENTO_DIR = os.path.join(CARPETA_RAIZ, "00_Base_Conocimiento_json_Clientes")

        carpeta_existente = _buscar_carpeta_usuario(codigo_usuario)
        if carpeta_existente:
            ruta_carpeta_usuario = carpeta_existente
        else:
            ruta_carpeta_usuario = os.path.join(BASE_CONOCIMIENTO_DIR, f"{codigo_usuario}_{_nombre_para_carpeta(nombre)}")

        generar_base_conocimiento(data, cliente_id=codigo_usuario, carpeta=ruta_carpeta_usuario)

        # Recién ahora, con la carpeta y el usuario.json listos, se confirma a la persona en la base
        session_db.commit()

        # La persona queda identificada en esta sesión (si es nueva, ya está adentro)
        session["codigo_usuario"] = codigo_usuario

        if clave_acceso_nueva:   # persona nueva: sesión normal, sin "Recordarme"
            session.permanent = False
            session["recordar"] = False
        session["ultimo_acceso"] = time.time()

        # --- PUENTE al procesador de correos (solo Modo AUTOMÁTICO); si falla, no afecta el guardado ---
        if es_automatico:
            try:
                sincronizar_con_procesador(data, email_contacto, clave_cifrada)
            except Exception as e:
                print(f"⚠️ El puente al procesador falló (el guardado normal NO se afectó): {e}")

        clave_ok = _clave_guardada(email_contacto) if es_automatico else False
        aviso = None
        if es_automatico and not clave_ok:
            aviso = "Tu información se guardó, pero todavía falta tu contraseña de aplicación para activar la lectura automática de tu correo."

        respuesta = {
            "status": "success",
            "message": "Datos guardados correctamente en BD y JSON.",
            "codigo_usuario": codigo_usuario,
            "clave_guardada": clave_ok,
            "aviso": aviso
        }
        if clave_acceso_nueva:
            respuesta["clave_acceso"] = clave_acceso_nueva  # solo se muestra esta vez, a la persona nueva
        return jsonify(respuesta), 200

    except Exception as e:
        session_db.rollback()
        print(f"❌ Error en enviar_cuestionario: {str(e)}")
        return jsonify({"status": "error", "message": "No pudimos guardar tu información. Revisá los datos e intentá de nuevo."}), 500

    finally:
        session_db.close()

    
@app.route('/subir-biblioteca', methods=['POST'])
def subir_biblioteca():
    try:
        archivos = request.files.getlist('archivo') or request.files.getlist('file')
        if not archivos:
            return jsonify({"status": "error", "message": "No se envió ningún archivo"}), 400

        codigo_usuario = (request.form.get('codigo_usuario') or request.form.get('codigo_usu') or '').strip().upper()
        if not codigo_usuario:
            return jsonify({"status": "error", "message": "Falta el código de usuario: los archivos no se guardaron."}), 400
        if not _acceso_permitido(codigo_usuario):
            return jsonify({"status": "error", "message": "Necesitás ingresar con tu código y tu clave de acceso."}), 401

        carpeta_usuario = _buscar_carpeta_usuario(codigo_usuario)
        if not carpeta_usuario:
            return jsonify({"status": "error", "message": f"No se encontró la carpeta de {codigo_usuario}."}), 404

        destino_biblioteca = os.path.join(carpeta_usuario, "Biblioteca_de_ARCHIVOS_PERSONALES")
        os.makedirs(destino_biblioteca, exist_ok=True)

        guardados = 0
        for archivo in archivos:
            if not archivo or not archivo.filename:
                continue
            nombre_archivo = os.path.basename(archivo.filename)
            archivo.save(os.path.join(destino_biblioteca, nombre_archivo))
            guardados += 1
            print(f"📎 Archivo guardado en la Biblioteca de {codigo_usuario}: {nombre_archivo}")

        # La lista de archivos de usuario.json se arma leyendo la carpeta real
        sincronizar_biblioteca_json(carpeta_usuario, codigo_usuario)

        return jsonify({"status": "success", "message": f"{guardados} archivo(s) subido(s) correctamente a {codigo_usuario}"}), 200

    except Exception as e:
        print(f"⚠️ Error al subir archivo a la biblioteca: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/cargar-datos', methods=['POST'])
def cargar_datos():
    session_db = SessionLocal()
    try:
        entrada = request.get_json(silent=True) or {}
        codigo = (entrada.get("codigo_usu") or "").strip().upper()
        clave = _normalizar_clave(entrada.get("clave"))

        if not codigo or not clave:
            return jsonify({"status": "error", "message": "Escribí tu código de usuario y tu clave de acceso."}), 400
        if _demasiados_intentos(codigo):
            return jsonify({"status": "error", "message": "Demasiados intentos fallidos. Esperá unos minutos y volvé a probar."}), 429

        perfil = session_db.query(PerfilCliente).filter(PerfilCliente.codigo_usuario == codigo).first()
        if not perfil or not perfil.clave_acceso_hash or not check_password_hash(perfil.clave_acceso_hash, clave):
            _registrar_intento_fallido(codigo)
            return jsonify({"status": "error", "message": "El código o la clave de acceso no son correctos."}), 401

        # La persona demostró quién es: queda registrada en esta sesión del navegador
        INTENTOS_FALLIDOS.pop(codigo, None)
        session.permanent = bool(entrada.get("recordar"))
        session["codigo_usuario"] = perfil.codigo_usuario

        session["recordar"] = bool(entrada.get("recordar"))
        session["ultimo_acceso"] = time.time()
        print(f"🔑 Ingreso de {perfil.codigo_usuario}: recordar={session['recordar']}")

        datos_json = {}
        carpeta_usuario = _buscar_carpeta_usuario(perfil.codigo_usuario)
        if carpeta_usuario:
            ruta_json = os.path.join(carpeta_usuario, "usuario.json")
            if os.path.exists(ruta_json):
                with open(ruta_json, "r", encoding="utf-8") as f:
                    datos_json = json.load(f)

        return jsonify({
            "status": "success",
            "datos": {
                "codigo_usuario": perfil.codigo_usuario,
                "nombre": perfil.nombre,
                "email_contacto": perfil.email_contacto,
                "email_servicio": perfil.email_servicio,
                "celular": perfil.celular,
                "clave_guardada": _clave_guardada(perfil.email_contacto),
                "modo": _modo_de_persona(perfil),
                "json_conocimiento": datos_json
            }
        }), 200

    except Exception as e:
        print(f"❌ Error en /cargar-datos: {e}")
        return jsonify({"status": "error", "message": "No se pudieron cargar los datos. Intentá de nuevo."}), 500
    finally:
        session_db.close()

def _armar_datos_persona(perfil):
    """Arma los datos de una persona para mostrarlos en el Cuestionario (los mismos que devuelve /cargar-datos)."""
    datos_json = {}
    carpeta_usuario = _buscar_carpeta_usuario(perfil.codigo_usuario)
    if carpeta_usuario:
        ruta_json = os.path.join(carpeta_usuario, "usuario.json")
        if os.path.exists(ruta_json):
            with open(ruta_json, "r", encoding="utf-8") as f:
                datos_json = json.load(f)
    return {
        "codigo_usuario": perfil.codigo_usuario,
        "nombre": perfil.nombre,
        "email_contacto": perfil.email_contacto,
        "email_servicio": perfil.email_servicio,
        "celular": perfil.celular,
        "clave_guardada": _clave_guardada(perfil.email_contacto),
        "modo": _modo_de_persona(perfil),
        "json_conocimiento": datos_json
    }

def _modo_de_persona(perfil):
    """'automatico' si la persona tiene un correo real conectado; si no, 'manual'."""
    correo = (perfil.email_contacto or "").strip()
    return "manual" if correo in ("", "modo_manual@local.com") else "automatico"




@app.route('/mi-sesion', methods=['GET'])
def mi_sesion():
    """Si el navegador ya está identificado (y la sesión no venció), devuelve los datos de la persona."""
    cookie_recibida = 'session' in request.cookies
    recordar_guardado = session.get("recordar")
    codigo = _sesion_vigente(renovar=False)   # refrescar la página no alarga la sesión
    print(f"🔎 /mi-sesion: sesión de {codigo or 'nadie'} | recordar={recordar_guardado} | cookie recibida={'sí' if cookie_recibida else 'no'}")
    if not codigo:
        return _sin_cache(jsonify({"status": "sin_sesion"})), 200
    session_db = SessionLocal()
    try:
        perfil = session_db.query(PerfilCliente).filter(PerfilCliente.codigo_usuario == codigo).first()
        if not perfil:
            session.clear()
            return _sin_cache(jsonify({"status": "sin_sesion"})), 200
        return _sin_cache(jsonify({"status": "success", "datos": _armar_datos_persona(perfil)})), 200
    except Exception as e:
        print(f"❌ Error en /mi-sesion: {e}")
        return jsonify({"status": "error", "message": "No se pudieron cargar los datos."}), 500
    finally:
        session_db.close()


@app.route('/cerrar-sesion', methods=['POST'])
def cerrar_sesion():
    print(f"🚪 /cerrar-sesion: se cierra la sesión de {session.get('codigo_usuario') or 'nadie'}")
    session.clear()
    return _sin_cache(jsonify({"status": "success"})), 200


# ----------------- ENDPOINT AGREGADO PARA EVITAR EL 404 -----------------
@app.route('/ver-instructivo-prueba', methods=['GET'])
def ver_instructivo_prueba():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AUR+IA - Instructivo de Prueba</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #eef2f3; text-align: center; padding: 50px; }
            .card { background: white; padding: 40px; border-radius: 12px; max-width: 600px; margin: 0 auto; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
            h1 { color: #0047AB; }
            p { font-size: 1.1em; color: #555; line-height: 1.6; }
            .badge { background: #D4AF37; color: white; padding: 6px 12px; border-radius: 5px; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>✨ ¡Conexión Exitosa con AUR+IA!</h1>
            <p>La configuración de tu <strong>Vida y Obra</strong> ha sido sincronizada y guardada.</p>
            <p><span class="badge">AURelia</span> y <span class="badge">AURhelios</span> ya tienen acceso local y están listos para procesar tu correspondencia.</p>
        </div>
    </body>
    </html>
    """, 200

@app.route('/')
def cuestionario():
    return send_file(os.path.join(CARPETA_RAIZ, 'index.html'))

@app.route('/validation.js')
def validation_js():
    return send_file(os.path.join(CARPETA_RAIZ, 'validation.js'))

@app.route('/instructivo')
def instructivo():
    return send_file(os.path.join(CARPETA_RAIZ, 'emails_para_clientes_potenciales', 'email_04_INSTRUCTIVO.html'))

@app.route('/imagenes_Cuestionario_VyO/<path:filename>')
def servir_imagenes(filename):
    return send_from_directory(os.path.join(CARPETA_RAIZ, 'imagenes_Cuestionario_VyO'), filename)

@app.route('/ping', methods=['GET'])
def ping():
    return "OK", 200

if __name__ == '__main__':
    print("*" * 60)
    print(f"  Base de datos oficial en uso: {DB_PATH_DISPLAY}")
    print(f"  Servidor escuchando en: http://127.0.0.1:5000")
    print("*" * 60)
    app.run(debug=True, port=5000)