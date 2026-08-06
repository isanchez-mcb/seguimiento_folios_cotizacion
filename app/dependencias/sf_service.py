import os
import requests
from simple_salesforce import Salesforce
from dotenv import load_dotenv
from datetime import datetime, timedelta
from fastapi import Depends
from fastapi import HTTPException

SALESFORCE_CACHE = {
    'instance_url': None,
    'timestamp': datetime.min,
    'lifetime': timedelta(hours=1),
    'lastclean': datetime.min
}

ACCOUNT_CACHE = {
    'data': None,
    'vendedores': None,
    'timestamp': datetime.min,
    'rfc_id': None,
    'exp_id_num': None,
    'exp_id_str': None,
    'nombre_id': None
}

CACHE_DURATION = timedelta(hours=24)
LAST_VALIDATION = timedelta(minutes=2)


load_dotenv()
APP_ENV = os.getenv("APP_ENV")

def sf_auth(url, data):
    try:
        resp = requests.post(url, data=data)
        if resp.status_code == 200:
            auth_response = resp.json()
            access_token = auth_response['access_token']
            instance_url = auth_response['instance_url']
            sf = Salesforce(instance_url=instance_url, session_id=access_token)
            print("Conexión OAuth2 SalesForce exitosa.")
            SALESFORCE_CACHE['instance_url'] = sf
            SALESFORCE_CACHE['timestamp'] = datetime.now()
            return sf
        else:
            print("Error al obtener el token:", resp.status_code)
            print(resp.text)
            raise HTTPException(status_code=401, detail="No se pudo autenticar con Salesforce")
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error de conexion con Salesforce")

        
def _verificar_sesion_valida(sf) -> bool:
    """
    Verifica si la sesión de Salesforce sigue activa con un query barato.
    Si la sesión expiró, Salesforce devuelve INVALID_SESSION_ID.
    """
    try:
        sf.query("SELECT Id FROM User WHERE IsActive = True LIMIT 1")
        return True
    except Exception as e:
        error_str = str(e)
        if "INVALID_SESSION_ID" in error_str or "Session expired" in error_str:
            print("Sesión de Salesforce expirada. Se limpiará el cache.")
            return False
        # Otros errores no son de sesión, asumir que la sesión es válida
        print(f"Error al verificar sesión (no es de expiración): {e}")
        return True


def get_salesforce_data():
    global SALESFORCE_CACHE
    cache = SALESFORCE_CACHE
    cache_valido = cache['instance_url'] is not None and (datetime.now() - cache['timestamp']) < cache['lifetime']
    periodo_valido = (datetime.now() - cache['lastclean']) < LAST_VALIDATION
    sesion_expirada = False

    if cache_valido:
        # Verificar que la sesión siga activa antes de devolver el cache
        if _verificar_sesion_valida(cache['instance_url']):
            print("Usando conexión Salesforce en cache.")
            return cache['instance_url']
        else:
            # Sesión expirada → limpiar cache y re-autenticar
            print("Limpiando cache por sesión expirada...")
            cache['instance_url'] = None
            cache['timestamp'] = datetime.min
            cache['lastclean'] = datetime.min
            cache_valido = False
            sesion_expirada = True

    if not cache_valido:
        # Si la sesión expiró, re-autenticar inmediatamente sin importar periodo_valido
        if periodo_valido and not sesion_expirada:
            print("Última validación de token hace menos de 2 minutos, no se limpiara cache...")
            return cache['instance_url']
        else:
            suffix = "" if APP_ENV == 'production' else "_SANDBOX"
            print(f"Entorno {APP_ENV}")
            CONSUMER_KEY = os.getenv(f'CONSUMER_KEY{suffix}')
            CONSUMER_SECRET = os.getenv(f'CONSUMER_SECRET{suffix}')
            url = os.getenv(f'url{suffix}')
            
            data = {
                'grant_type': 'client_credentials',
                'client_id': CONSUMER_KEY,
                'client_secret': CONSUMER_SECRET
            }
            
            return sf_auth(url, data)