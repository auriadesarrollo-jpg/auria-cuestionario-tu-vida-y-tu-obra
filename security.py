import os
import sys
import base64
import logging
from cryptography.fernet import Fernet

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AUR+IA.Security")

class SecureKeyManager:
    """
    Gestiona el cifrado y descifrado de credenciales críticas en un entorno On-Premise.
    Implementa el principio de separación de claves: la clave de cifrado NUNCA se almacena
    en la misma base de datos que el contenido cifrado.
    
    Estrategia de Almacenamiento de Clave de Cifrado (Master Key):
    1. Intenta usar el Administrador de Credenciales de Windows (OS Keyring) vía la librería `keyring`.
    2. Si falla o no está instalada, recurre a un archivo de clave aislado en el perfil
       de usuario (~/.auria/master.key) con permisos del sistema de archivos restringidos.
    """
    
    SERVICE_NAME = "AUR_IA_PostalSystem"
    KEY_ACCOUNT_NAME = "MasterDatabaseEncryptionKey"
    
    def __init__(self):
        self._master_key = self._retrieve_or_generate_master_key()
        self._cipher = Fernet(self._master_key)

    def _retrieve_or_generate_master_key(self) -> bytes:
        """
        Busca la clave maestra en la variable de entorno (para producción en la nube),
        en el llavero del sistema operativo o en el archivo local seguro.
        Si no existe, la genera y la resguarda inmediatamente.
        """
        # 0. Prioridad absoluta para la variable de entorno (Render / Producción)
        env_master_key = os.environ.get("MASTER_KEY")
        if env_master_key:
            logger.info("Clave maestra recuperada exitosamente desde la variable de entorno.")
            return env_master_key.encode('utf-8')

        # 1. Intentar con el Llavero del Sistema Operativo (Windows Credential Manager / Keychain)
        try:
            import keyring
            key_str = keyring.get_password(self.SERVICE_NAME, self.KEY_ACCOUNT_NAME)
            if key_str:
                logger.info("Clave maestra recuperada exitosamente desde el llavero del S.O.")
                return key_str.encode('utf-8')
            
            # Generar una nueva clave si no existe
            new_key = Fernet.generate_key()
            keyring.set_password(self.SERVICE_NAME, self.KEY_ACCOUNT_NAME, new_key.decode('utf-8'))
            logger.info("Clave maestra generada y resguardada de forma segura en el llavero del S.O.")
            return new_key
        except Exception as e:
            logger.warning(f"No se pudo usar el llavero del S.O. ({e}). Usando almacenamiento secundario seguro en disco...")
            return self._retrieve_or_generate_from_file()

    def _retrieve_or_generate_from_file(self) -> bytes:
        """
        Almacenamiento fallback seguro en el directorio del usuario con permisos exclusivos del propietario.
        """
        home_dir = os.path.expanduser("~")
        auria_dir = os.path.join(home_dir, ".auria")
        key_file_path = os.path.join(auria_dir, "master.key")
        
        # Crear directorio de configuración local si no existe
        if not os.path.exists(auria_dir):
            os.makedirs(auria_dir, mode=0o700) # Lectura/Escritura exclusiva para el usuario
            
        if os.path.exists(key_file_path):
            try:
                with open(key_file_path, "rb") as f:
                    logger.info(f"Clave maestra recuperada desde archivo local protegido: {key_file_path}")
                    return f.read()
            except Exception as e:
                logger.critical(f"Error crítico al leer el archivo de clave local: {e}")
                raise
        
        # Generar y escribir una nueva clave
        new_key = Fernet.generate_key()
        try:
            # Abrir archivo con descriptor de archivos de baja visibilidad y permisos restrictivos
            with open(os.open(key_file_path, os.O_CREAT | os.O_WRONLY, 0o600), "wb") as f:
                f.write(new_key)
            logger.info(f"Nueva clave maestra generada y escrita con permisos restringidos en: {key_file_path}")
            return new_key
        except Exception as e:
            logger.critical(f"No se pudo inicializar la clave de seguridad local: {e}")
            raise e

    def encrypt_credential(self, plaintext_cred: str) -> str:
        """
        Recibe una credencial limpia (por ejemplo, el Google App Password de 16 caracteres)
        y la retorna cifrada en formato string listo para guardarse en la BD.
        """
        if not plaintext_cred:
            return ""
        
        # Sanitizar y normalizar a minúsculas, removiendo espacios que usualmente viajan con la clave
        clean_cred = plaintext_cred.replace(" ", "").lower().strip()
        
        if len(clean_cred) != 16:
            raise ValueError("La clave de aplicación de Google debe tener exactamente 16 caracteres.")
            
        encrypted_bytes = self._cipher.encrypt(clean_cred.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')

    def decrypt_credential(self, encrypted_cred_str: str) -> str:
        """
        Recibe la credencial cifrada leída desde la base de datos y retorna la clave de 16 caracteres
        en texto plano lista para que AURhelios inicie conexión SMTP/IMAP.
        """
        if not encrypted_cred_str:
            return ""
            
        decrypted_bytes = self._cipher.decrypt(encrypted_cred_str.encode('utf-8'))
        raw_cred = decrypted_bytes.decode('utf-8')
        
        # Formatear amigablemente con espacios cada 4 letras (ej. abcd efgh ijkl mnop)
        # Esto ayuda a visualizarla o loguearla internamente si fuese necesario
        formatted_cred = " ".join(raw_cred[i:i+4] for i in range(0, len(raw_cred), 4))
        return formatted_cred


# Demostración del funcionamiento básico
if __name__ == "__main__":
    try:
        manager = SecureKeyManager()
        ejemplo_clave = "abcd efgh ijkl mnop"
        print(f"Original: {ejemplo_clave}")
        
        cifrada = manager.encrypt_credential(ejemplo_clave)
        print(f"Cifrada en BD: {cifrada}")
        
        descifrada = manager.decrypt_credential(cifrada)
        print(f"Descifrada para AURhelios: {descifrada}")
    except Exception as err:
        print(f"Error en demostración: {err}")
