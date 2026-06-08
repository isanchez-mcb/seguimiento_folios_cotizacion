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

        
def get_salesforce_data():
    global SALESFORCE_CACHE
    cache = SALESFORCE_CACHE
    cache_valido = cache['instance_url'] is not None and (datetime.now() - cache['timestamp']) < cache['lifetime']
    periodo_valido = (datetime.now() - cache['lastclean']) < LAST_VALIDATION
    if cache_valido:
        print("Usando conexión Salesforce en cache.")
        return cache['instance_url']
    if not cache_valido:
        if periodo_valido:
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