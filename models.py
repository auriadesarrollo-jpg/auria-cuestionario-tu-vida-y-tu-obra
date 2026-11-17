import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()

class PerfilCliente(Base):
    __tablename__ = 'perfil_cliente'

    id = Column(Integer, primary_key=True, autoincrement=True)
    cliente_id = Column(String)
    codigo_usuario = Column(String)
    nombre = Column(String)
    email_contacto = Column(String)
    email_servicio = Column(String)
    clave_aplicacion = Column(String)
    celular = Column(String)
    fecha_recepcion = Column(String)
    clave_acceso_hash = Column(String)

class User(Base):
    """
    Representa el usuario del sistema local AUR+IA.
    Identificado unívocamente por su dirección de email de contacto.
    """
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    email_contacto = Column(String(255), unique=True, nullable=False, index=True)
    email_servicio = Column(String(255), nullable=False, default="auria.desarrollo@gmail.com")
    nombre = Column(String(255), nullable=True)
    celular = Column(String(50), nullable=True)

    correo_actual = Column(String(255), nullable=True)
    correo_anterior = Column(String(255), nullable=True)
    fecha_actualizacion_correo = Column(String(50), nullable=True)
    ultima_llave_conexion = Column(String(64), nullable=True)
    
    # Almacenaremos la clave de 16 caracteres de Google en formato cifrado (AES-256-CBC)
    clave_aplicacion_cifrada = Column(String(512), nullable=True)
    
    # Modo activo: 'integral' o 'profesional'
    flujo_activo = Column(String(50), nullable=False, default='profesional')
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relaciones uno a uno con perfiles específicos
    personal_profile = relationship("PersonalProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    professional_profile = relationship("ProfessionalProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    
    # Relación uno a muchos con configuraciones de categorías
    categories = relationship("CategoryConfig", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.email_contacto} (Flujo: {self.flujo_activo})>"


class PersonalProfile(Base):
    """
    Almacena los campos del 'Bloque 2' (Vida personal).
    En el Modo Profesional, esta tabla puede permanecer con valores nulos o vacíos.
    """
    __tablename__ = 'personal_profiles'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    
    apodo = Column(String(255), nullable=True)
    actividades = Column(Text, nullable=True)  # Actividades personales, espirituales, artísticas
    familia = Column(Text, nullable=True)      # Miembros de la familia
    amigos = Column(Text, nullable=True)       # Amigos cercanos
    mascotas = Column(Text, nullable=True)     # Mascotas
    fechas = Column(Text, nullable=True)       # Fechas importantes
    vida_extra = Column(Text, nullable=True)   # Aspectos adicionales

    user = relationship("User", back_populates="personal_profile")


class ProfessionalProfile(Base):
    """
    Almacena los campos de la sección 'Tu Obra' (Ámbito laboral y comercial).
    Común a ambos modos, pero prioritario en el Modo Profesional.
    """
    __tablename__ = 'professional_profiles'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    
    tarea_profesional = Column(Text, nullable=True)
    fricciones_operativas = Column(Text, nullable=True)  # Obstáculos y atascos de comunicación
    prioridades_delegacion = Column(Text, nullable=True) # Prioridades inmediatas de delegación
    tipo_empleo = Column(String(255), nullable=True)     # Independiente o Relación de dependencia
    empresa = Column(String(255), nullable=True)         # Emprendimiento o firma
    companeros = Column(Text, nullable=True)             # Colegas y vínculos institucionales
    social_extra = Column(Text, nullable=True)           # Actividades sociales
    obra_extra = Column(Text, nullable=True)             # Aspectos adicionales profesionales

    user = relationship("User", back_populates="professional_profile")


class CategoryConfig(Base):
    """
    Almacena la configuración particular para cada una de las 9 categorías postales de AUR+IA.
    """
    __tablename__ = 'category_configs'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    
    category_number = Column(Integer, nullable=False) # 1 a 9
    category_name = Column(String(100), nullable=False)
    enabled = Column(Boolean, default=True)            # Toggle de activación
    modo = Column(String(50), default="revision")      # 'automatica', 'revision', 'archivo'
    tono = Column(String(255), nullable=True)          # Tono deseado (Cariñoso, formal, urgente, etc.)
    personalizado = Column(Text, nullable=True)        # Escenarios o remitentes personalizados
    remitentes = Column(Text, nullable=True)           # Direcciones de correo clave para forzar esta categoría

    user = relationship("User", back_populates="categories")


# Helper para inicializar la base de datos (por defecto SQLite local oficial)
def init_db(database_url="sqlite:///aur_ia_data.db"):
    engine = create_engine(database_url, connect_args={"check_same_thread": False} if "sqlite" in database_url else {})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)
