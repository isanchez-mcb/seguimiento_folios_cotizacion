import base64

from typing import Optional

from fastapi import HTTPException
from simple_salesforce import Salesforce


class LeadDuplicadoError(Exception):
    """
    Se lanza desde createLead cuando reintentar_sin_expediente es False y Salesforce
    detecta un duplicado. record_id es el Id del registro existente extraído del error
    de Salesforce (puede ser una Account si ya es cliente, o un Lead si ya existe un
    prospecto con estos datos), o None si no se pudo extraer.
    """
    def __init__(self, mensaje: str, record_id: Optional[str] = None):
        self.mensaje = mensaje
        self.record_id = record_id
        super().__init__(mensaje)


def createOpportunity(sf, oportunidad_data: dict) -> str:
    try:
        oportunidad = sf.Opportunity.create(oportunidad_data)

        print(f"Oportunidad creada exitosamente: {oportunidad}")
        return oportunidad
    except Exception as e:
        print(e)
        print(f"Error al crear la oportunidad: {e}")
        raise

def createLead(sf, lead_data: dict, reintentar_sin_expediente: bool = True) -> tuple:
    """
    Crea un lead en Salesforce.

    Si se detecta DUPLICATES_DETECTED por la regla Masivo_2_0 (expediente duplicado),
    extrae el AccountId del error. Si reintentar_sin_expediente es True (default),
    elimina No_expediente_No_colaborador__c de los datos y reintenta la creación;
    si es False, se lanza directamente el error de duplicado sin reintentar.

    Returns:
        tuple: (lead_result: OrderedDict, account_id: str | None)

        lead_result: resultado de la creación del lead
        account_id: ID de la cuenta duplicada (si aplica) o None si no hubo duplicado
    """
    try:
        headers = {'Sforce-Auto-Assign': 'TRUE'}
        sf.headers.update(headers)
        lead = sf.Lead.create(lead_data)
        sf.headers.pop('Sforce-Auto-Assign', None)
        print(f"Lead creado exitosamente: {lead}")
        return lead, None
    except Exception as e:
        error_str = str(e)
        print(e)
        if "DUPLICATES_DETECTED" in error_str:
            duplicate_record_id = None
            try:
                # Extraer el Id del registro duplicado del error (formato: 'Id': '001WR...')
                import re
                match = re.search(r"'Id':\s*'(\w+)'", error_str)
                if match:
                    duplicate_record_id = match.group(1)
                    print(f"Registro duplicado encontrado: {duplicate_record_id}")
            except Exception as parse_error:
                print(f"Error al parsear el Id del duplicado: {parse_error}")

            # Eliminar expediente y reintentar
            if reintentar_sin_expediente and 'No_expediente_No_colaborador__c' in lead_data:
                del lead_data['No_expediente_No_colaborador__c']
                print("Expediente eliminado del lead_data, reintentando...")
                try:
                    sf.headers.update({'Sforce-Auto-Assign': 'TRUE'})
                    lead = sf.Lead.create(lead_data)
                    sf.headers.pop('Sforce-Auto-Assign', None)
                    print(f"Lead creado exitosamente en reintento: {lead}")
                    return lead, duplicate_record_id
                except Exception as retry_e:
                    print(f"Error en reintento: {retry_e}")
                    raise HTTPException(
                        status_code=402,
                        detail="Ya existe un prospecto con este expediente o este correo, gracias por su interés."
                    )
            elif not reintentar_sin_expediente:
                # El llamador decide qué hacer con el duplicado (ej. crear una Opportunity
                # sobre la cuenta ya existente) en lugar de reintentar silenciosamente.
                raise LeadDuplicadoError(
                    "Ya existe un prospecto con este expediente o este correo, gracias por su interés.",
                    record_id=duplicate_record_id
                )
            else:
                raise HTTPException(
                    status_code=402,
                    detail="Ya existe un prospecto con este expediente o este correo, gracias por su interés."
                )

        print(f"Error al crear el lead: {e}")
        raise

def crear_nota_generica(id_lead: str, sf, html_content: str, titulo: str) -> bool:
    """
    Crea una ContentNote en Salesforce y la asocia a un lead.
    Versión genérica que no depende de modelos de cotización.
    
    Args:
        id_lead: ID del lead al que asociar la nota.
        sf: Instancia autenticada de Salesforce.
        html_content: Contenido HTML de la nota (se codifica a base64).
        titulo: Título de la nota.
    
    Returns:
        True si se creó correctamente, False en caso contrario.
    """
    try:
        import base64
        data = base64.b64encode(html_content.encode('utf-8')).decode('utf-8')
        note_data = {
            'Title': titulo,
            'Content': data
        }
        nota = sf.ContentNote.create(note_data)
        nota_id = nota['id']

        link_data = {
            'ContentDocumentId': nota_id,
            'LinkedEntityId': id_lead
        }
        sf.ContentDocumentLink.create(link_data)

        print(f"Nota '{titulo}' creada exitosamente")
        return True
    except Exception as e:
        print(f"Error al crear nota '{titulo}': {e}")
        return False


def crear_nota(id_lead, sf, data, request):
    try:
        from app.services.crearCortizacion import obtener_nombre_ramo

        ramo_activo = obtener_nombre_ramo(request)
        data = base64.b64encode(data.encode('utf-8')).decode('utf-8')
        note_data = {
            'Title': f'Cotizacion: {ramo_activo} - {request.nombre}',
            'Content': data
        } 
        nota = sf.ContentNote.create(note_data)
        nota_id = nota['id']
        note_asigned_data = {
            'ContentDocumentId': nota_id,
            'LinkedEntityId': id_lead
        }
        sf.ContentDocumentLink.create(note_asigned_data)
        print("Nota creada exitosamente")
        return True
    except Exception as e:
        print(f"Error al crear nota {e}")
        return False

def crearTarea(sf, lead_id, owner_id, descripcion, account_id=None, usar_what_id: bool = False):
    """
    Crea una Task de seguimiento asociada a un registro.

    usar_what_id: False (default) asocia la tarea vía WhoId (Lead/Contact), igual que
    siempre. True la asocia vía WhatId (Opportunity/Account/etc.), requerido por
    Salesforce cuando el registro relacionado no es un Lead ni un Contact.
    """
    try:
        from app.services.crearCortizacion import fecha_recordatorio

        recordatorio = fecha_recordatorio()
        activity_date = recordatorio.split('T')[0]

        # Si hay una cuenta duplicada, agregar enlace al final de la descripción
        descripcion_final = descripcion
        if account_id:
            descripcion_final = f"{descripcion}\n\nCuenta asociada: https://customer-customer-9846.lightning.force.com/lightning/r/Account/{account_id}/view"

        task_data = {
            'OwnerId': owner_id,
            'Subject': 'Call',
            'ActivityDate': activity_date,
            'Status': 'Not Started',
            'Priority': 'High',
            'IsReminderSet': True,
            'Description': descripcion_final,
            'ReminderDateTime': recordatorio
        }
        if usar_what_id:
            task_data['WhatId'] = lead_id
        else:
            task_data['WhoId'] = lead_id

        headers_previos = dict(sf.headers)
        sf.headers.clear()
        headers = {
            'Sforce-Email-Notification': 'TRUE'
        }
        sf.headers.update(headers)

        response = sf.Task.create(task_data)
        print("Tarea asignada", response)
        sf.headers.clear()
        sf.headers.update(headers_previos)
        
        return response
    except Exception as e:
        print(f"Error al crear la tareas {e}")
        if hasattr(e, 'content'):
            print(f"Contenido del error: {e.content}")
        elif hasattr(e, 'message'):
            print(f"Mensaje del error: {e.message}")
        else:
            print(f"Error general: {str(e)}")


