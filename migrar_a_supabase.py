import os
import sys
import logging
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from models import (
    Base,
    PerfilCliente,
    User,
    PersonalProfile,
    ProfessionalProfile,
    CategoryConfig,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("migrar_a_supabase")


def normalizar_url_postgres(url: str) -> str:
    url = url.strip()
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def crear_sesion_sqlite(ruta_sqlite: str):
    if not os.path.exists(ruta_sqlite):
        raise FileNotFoundError(f"No se encontró la base SQLite en: {ruta_sqlite}")
    engine = create_engine(f"sqlite:///{ruta_sqlite}", connect_args={"check_same_thread": False})
    return sessionmaker(bind=engine)


def crear_sesion_postgres(database_url: str):
    url_limpia = normalizar_url_postgres(database_url)
    engine = create_engine(
        url_limpia,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=3,
        max_overflow=2,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def copiar_campos(origen, destino, excluir=("id",)):
    for columna in origen.__table__.columns:
        if columna.name not in excluir and hasattr(destino, columna.name):
            setattr(destino, columna.name, getattr(origen, columna.name))


def migrar_perfiles_cliente(src_session, dst_session) -> int:
    registros = src_session.execute(select(PerfilCliente)).scalars().all()
    insertados = 0
    for item in registros:
        existente = dst_session.execute(
            select(PerfilCliente).where(PerfilCliente.codigo_usuario == item.codigo_usuario)
        ).scalar_one_or_none()
        if existente is None:
            nuevo = PerfilCliente()
            copiar_campos(item, nuevo)
            dst_session.add(nuevo)
            insertados += 1
    return insertados


def migrar_usuarios_y_perfiles(src_session, dst_session) -> int:
    usuarios = src_session.execute(select(User)).scalars().all()
    insertados = 0

    for usr in usuarios:
        existente = dst_session.execute(
            select(User).where(User.email_contacto == usr.email_contacto)
        ).scalar_one_or_none()

        if existente is not None:
            continue

        nuevo_usr = User()
        copiar_campos(usr, nuevo_usr)
        dst_session.add(nuevo_usr)
        dst_session.flush()  # Genera nuevo_usr.id para las tablas hijas

        if usr.personal_profile:
            nuevo_personal = PersonalProfile(user_id=nuevo_usr.id)
            copiar_campos(usr.personal_profile, nuevo_personal, excluir=("id", "user_id"))
            dst_session.add(nuevo_personal)

        if usr.professional_profile:
            nuevo_prof = ProfessionalProfile(user_id=nuevo_usr.id)
            copiar_campos(usr.professional_profile, nuevo_prof, excluir=("id", "user_id"))
            dst_session.add(nuevo_prof)

        for cat in usr.categories:
            nueva_cat = CategoryConfig(user_id=nuevo_usr.id)
            copiar_campos(cat, nueva_cat, excluir=("id", "user_id"))
            dst_session.add(nueva_cat)

        insertados += 1

    return insertados


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ruta_sqlite = r"C:\Users\Anuar\AURIA_2\instance\aur_ia_data.db"
    database_url = os.environ.get("DATABASE_URL", "").strip()

    if not database_url:
        logger.error("Falta la variable de entorno DATABASE_URL con la cadena de conexión de Supabase.")
        sys.exit(1)

    logger.info("Iniciando migración desde SQLite local hacia Supabase...")
    SrcSession = crear_sesion_sqlite(ruta_sqlite)
    DstSession = crear_sesion_postgres(database_url)

    src_db = SrcSession()
    dst_db = DstSession()

    try:
        n_perfiles = migrar_perfiles_cliente(src_db, dst_db)
        n_usuarios = migrar_usuarios_y_perfiles(src_db, dst_db)
        dst_db.commit()
        logger.info(
            f"Migración finalizada con éxito. Nuevos en perfil_cliente: {n_perfiles} | Nuevos usuarios: {n_usuarios}"
        )
    except Exception as exc:
        dst_db.rollback()
        logger.exception(f"Error durante la migración (se revirtieron los cambios): {exc}")
        sys.exit(1)
    finally:
        src_db.close()
        dst_db.close()


if __name__ == "__main__":
    main()