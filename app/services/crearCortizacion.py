import base64
import datetime

from datetime import datetime, timedelta
import pytz
from simple_salesforce.api import Salesforce
from app.services.sf_create_data import crear_nota, createLead

def obtener_nombre_ramo(data_request) -> str:
    from app.utils.diccionarios import campos_cotizacion
    for atributo, nombre_ramo in campos_cotizacion.MAPEO_RAMOS.items():
        if getattr(data_request, atributo, None) is not None:
            return nombre_ramo
            
    return ""

def normalizar_telefono(telefono_raw: str) -> str:
    if not telefono_raw:
        return ""
        
    telefono_limpio = "".join([c for c in str(telefono_raw) if c.isdigit() or c == '+'])
    
    if telefono_limpio.startswith("+52"):
        return telefono_limpio
        
    if len(telefono_limpio) == 12 and telefono_limpio.startswith("52"):
        return f"+{telefono_limpio}"
        
    if len(telefono_limpio) == 10 and telefono_limpio.isdigit():
        return f"+52{telefono_limpio}"
        
    return telefono_limpio

def data_cotizacion(data_cotizacion, owner_id):
    try:
        ramo_activo = obtener_nombre_ramo(data_cotizacion)
        telefono_normalizado = normalizar_telefono(data_cotizacion.telefono)
        Ramos_de_interes__c = None
        #RecordTypeId = '012WR000000GvGvYAK' #Masivo
        RecordTypeId = '012WR000000GvGwYAK' #NN
        Tipo = 'Nuevos negocios'
        if data_cotizacion.auto_data or data_cotizacion.hogar_data:
            Ramos_de_interes__c = 'DAÑOS'
        elif data_cotizacion.gmm_data or data_cotizacion.plan_seguro_data:
            Ramos_de_interes__c = 'ACCIDENTES Y ENFERMEDADES'
        elif data_cotizacion.vida_total_data or data_cotizacion.vida_mas_data:
            Ramos_de_interes__c = 'VIDA'
        
        
        if data_cotizacion.auto_data and not data_cotizacion.expediente_colaborador:
            Ramos_de_interes__c = None

        
        lead_data = {
            'LeadSource' : 'Lucia',
            'FirstName' : f'Cotización: {ramo_activo} - ',
            'LastName' : data_cotizacion.nombre,
            'MobilePhone' : telefono_normalizado,
            'Ramos_de_interes__c' : Ramos_de_interes__c,
            'RecordTypeId': '012WR000000GvGvYAK' if Ramos_de_interes__c else RecordTypeId,
            'Tipo_de_prospecto__c': 'Masivo' if Ramos_de_interes__c else Tipo,
            'OwnerId': owner_id
        }

        if data_cotizacion.expediente_colaborador:
            lead_data['No_expediente_No_colaborador__c'] = data_cotizacion.expediente_colaborador

        return lead_data
    except Exception as e:
        print(e)
        raise

def generar_texto(data_cotizacion) -> str:
    from app.utils.diccionarios import campos_cotizacion

    lineas = ["<ul>"]
    descripcion = []

    ramos_mapeo = [
        "auto_data", "gmm_data", "hogar_data", "vida_total_data", 
        "vida_mas_data", "plan_seguro_data", "mascota_data", "viajes_data"
    ]

    for atributo in ramos_mapeo:
        sub_modelo = getattr(data_cotizacion, atributo)
        
        if sub_modelo is not None:
            datos_producto = sub_modelo.model_dump() if hasattr(sub_modelo, "model_dump") else sub_modelo.dict()
            
            for campo_tecnico, valor in datos_producto.items():
                if valor is not None:
                    nombre_legible = campos_cotizacion.nombres_legibles.get(campo_tecnico, campo_tecnico)
                    
                    value = valor
                    if isinstance(valor, bool):
                        value = "Sí" if valor else "No"
                        
                    lineas.append(f"<li><b>{nombre_legible}:</b> {value}</li>")
                    descripcion.append(f"{nombre_legible}: {value}\n")

    lineas.append("</ul>")

    return "".join(lineas), "".join(descripcion)

def buscar_asesor_activo(sf: Salesforce) -> str:
    try:
        query_cola = "SELECT UserOrGroupId FROM GroupMember Where Group.Name = 'Asesor Telemarketing'"
        resultado_cola = sf.query(query_cola)
        ids_cola = {rm['UserOrGroupId'] for rm in resultado_cola['records']}

        if not ids_cola:
            return ""

        query_activos = "SELECT UserId, User.Name, ServicePresenceStatus.DeveloperName, IsCurrentState FROM UserServicePresence WHERE IsCurrentState = true"
        resultado_activos = sf.query(query_activos)
        asesores_disponibles = []
        for reg in resultado_activos['records']:
            user_id = reg['UserId']
            user_name = reg['User']['Name'] if reg.get('User') else "Usuario Desconocido"
            estado = reg['ServicePresenceStatus']['DeveloperName']

            estados_validos = ['Disponible_Voice_chat', 'AvailableforVoice']
            if user_id in ids_cola and any(est in estado for est in estados_validos):
                asesores_disponibles.append({'id': user_id, 'name': user_name})

        print(f"Asesores de Telemarketing activos encontrados: {asesores_disponibles}")
        return asesores_disponibles

    except Exception as e:
        print(f"Error en la busqueda de asesores activos: {e}")
        return []

def asignar_propietario_carrusel(sf: Salesforce) -> tuple:
    try:
        owners_list = buscar_asesor_activo(sf)
        size = len(owners_list)
        
        if size == 0:
            print("Omni-Channel vacío. Asignando a director Telemarketing por respaldo.")
            return '005WR00000CO8C1YAL', 'Pronto se le asignara un asesor'
        
        owners_list.sort(key=lambda x: x['id'])
        print(f"DEBUG: Asesores disponibles y ordenados para el carrusel: {owners_list}")

        just_ids = [owner['id'] for owner in owners_list]

        query_ultimos = (
            "SELECT OwnerId FROM Lead WHERE CreatedBy.Name = 'Integraciones Desarrollo Digital' AND LeadSource = 'Lucia' ORDER BY CreatedDate DESC LIMIT 5"
        )
        
        last_owners_ids = []
        try:
            res_ultimos = sf.query(query_ultimos)
            for record in res_ultimos['records']:
                last_owners_ids.append(record['OwnerId'])
            print(f"DEBUG: Últimos Owners de Lucia en Salesforce: {last_owners_ids}")
        except Exception as e:
            print(f"Error al consultar últimos leads de Lucia: {e}")

        start_index = 0
        for last_owner in last_owners_ids:
            if last_owner in just_ids:
                start_index = (just_ids.index(last_owner) + 1) % size
                print(f"DEBUG: El último en atender fue {last_owner}. Turno inicial para índice: {start_index}")
                break

        candidato = owners_list[start_index]
        
        print(f"¡Asignado por carrusel! -> ID: {candidato['id']}, Nombre: {candidato['name']}")
        return candidato['id'], candidato['name']
        
    except Exception as e:
        print(f"Error en la asignacion: {e}")
        return "", ""

def fecha_recordatorio():
    zona_local = pytz.timezone('America/Mexico_City')
    zona_utc = pytz.utc

    #tiempo_ahora = fecha_prueba.astimezone(zona_local) if fecha_prueba.tzinfo else zona_local.localize(fecha_prueba)
    tiempo_ahora = datetime.now(zona_local)

    recordatorio = tiempo_ahora + timedelta(minutes=5)

    while recordatorio.weekday() > 4:
        recordatorio = recordatorio + timedelta(days=1)
        recordatorio = recordatorio.replace(hour=8, minute=30, second=0, microsecond=0)

    hora_inicio = recordatorio.replace(hour=8, minute=30, second=0, microsecond=0)
    hora_fin = recordatorio.replace(hour=17, minute=30, second=0, microsecond=0)

    if recordatorio < hora_inicio:
        recordatorio = hora_inicio

    elif recordatorio > hora_fin:
        recordatorio = recordatorio + timedelta(days=1)
        recordatorio = recordatorio.replace(hour=8, minute=30, second=0, microsecond=0)

        while recordatorio.weekday()>4:
            recordatorio = recordatorio + timedelta(days=1)
            recordatorio = recordatorio.replace(hour=8, minute=30, second=0, microsecond=0)

    recordatorio_utc = recordatorio.astimezone(zona_utc)

    recordatorio_utc = recordatorio_utc.strftime('%Y-%m-%dT%H:%M:%S.000+0000')

    return recordatorio_utc