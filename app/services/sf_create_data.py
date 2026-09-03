import base64

from typing import Optional

from fastapi import HTTPException
from simple_salesforce import Salesforce

from app.dependencias.sf_service import SesionExpiradaError, es_error_sesion, query_con_reintento


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
    extrae el Id del registro duplicado del error.

    - Si reintentar_sin_expediente es False, se lanza LeadDuplicadoError de inmediato
      (sin reintentar) con ese Id, para que el llamador decida qué hacer (ver
      crearLeadCampo.py, que puede crear una Opportunity o una tarea de seguimiento).
    - Si reintentar_sin_expediente es True (default, usado por cotización): si hay
      expediente, se elimina (junto con Negocio__c) y se reintenta; si ese reintento
      también falla por duplicado y hay Email en los datos, se elimina el Email y se
      reintenta una vez más. Si no hay expediente pero sí Email, se elimina el Email
      y se reintenta una vez.

    Returns:
        tuple: (lead_result: OrderedDict, duplicate_record_id: str | None)

        lead_result: resultado de la creación del lead
        duplicate_record_id: Id del registro duplicado (si aplica) o None si no hubo duplicado
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
        if es_error_sesion(e):
            print("Sesión expirada al crear lead.")
            raise SesionExpiradaError(error_str) from e

        if "DUPLICATES_DETECTED" not in error_str:
            print(f"Error al crear el lead: {e}")
            raise

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

        if not reintentar_sin_expediente:
            # El llamador decide qué hacer con el duplicado (ej. crear una Opportunity
            # sobre la cuenta ya existente) en lugar de reintentar silenciosamente.
            raise LeadDuplicadoError(
                "Ya existe un prospecto con este expediente o este correo, gracias por su interés.",
                record_id=duplicate_record_id
            )

        if 'No_expediente_No_colaborador__c' in lead_data:
            # Eliminar expediente (y Negocio__c, ligado a la misma validación) y reintentar
            del lead_data['No_expediente_No_colaborador__c']
            if 'Negocio__c' in lead_data:
                del lead_data['Negocio__c']
            print("Expediente eliminado del lead_data, reintentando...")
            try:
                sf.headers.update({'Sforce-Auto-Assign': 'TRUE'})
                lead = sf.Lead.create(lead_data)
                sf.headers.pop('Sforce-Auto-Assign', None)
                print(f"Lead creado exitosamente en reintento: {lead}")
                return lead, duplicate_record_id
            except Exception as retry_e:
                retry_error_str = str(retry_e)
                print(f"Error en reintento: {retry_error_str}")

                # Si el reintento sigue fallando por DUPLICATES_DETECTED (email),
                # eliminar el Email y reintentar una vez más
                if "DUPLICATES_DETECTED" in retry_error_str and 'Email' in lead_data:
                    del lead_data['Email']
                    print("Email eliminado del lead_data por duplicado, reintentando...")
                    try:
                        sf.headers.update({'Sforce-Auto-Assign': 'TRUE'})
                        lead = sf.Lead.create(lead_data)
                        sf.headers.pop('Sforce-Auto-Assign', None)
                        print(f"Lead creado exitosamente en segundo reintento: {lead}")
                        return lead, duplicate_record_id
                    except Exception as retry2_e:
                        print(f"Error en segundo reintento: {retry2_e}")
                        raise HTTPException(
                            status_code=402,
                            detail="Ya existe un prospecto con este expediente o este correo, gracias por su interés."
                        )

                raise HTTPException(
                    status_code=402,
                    detail="Ya existe un prospecto con este expediente o este correo, gracias por su interés."
                )
        else:
            # Si no hay expediente pero el duplicado es por email,
            # eliminar el Email y reintentar
            if 'Email' in lead_data:
                del lead_data['Email']
                print("Email eliminado del lead_data por duplicado (sin expediente), reintentando...")
                try:
                    sf.headers.update({'Sforce-Auto-Assign': 'TRUE'})
                    lead = sf.Lead.create(lead_data)
                    sf.headers.pop('Sforce-Auto-Assign', None)
                    print(f"Lead creado exitosamente en reintento sin email: {lead}")
                    return lead, duplicate_record_id
                except Exception as retry_e:
                    print(f"Error en reintento sin email: {retry_e}")
                    raise HTTPException(
                        status_code=402,
                        detail="Ya existe un prospecto con este expediente o este correo, gracias por su interés."
                    )
            else:
                raise HTTPException(
                    status_code=402,
                    detail="Ya existe un prospecto con este expediente o este correo, gracias por su interés."
                )

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
        data = base64.b64encode(html_content.encode('utf-8')).decode('utf-8')
        note_data = {
            'Title': titulo,
            'Content': data
        }
        nota = sf.ContentNote.create(note_data)
        nota_id = nota['id']
        print(f"ContentNote creada: {nota_id}")

        link_data = {
            'ContentDocumentId': nota_id,
            'LinkedEntityId': id_lead
        }
        link_result = sf.ContentDocumentLink.create(link_data)
        print(f"ContentDocumentLink creado: {link_result}")

        print(f"Nota '{titulo}' creada exitosamente")
        return True
    except Exception as e:
        if es_error_sesion(e):
            print(f"Sesión expirada al crear nota '{titulo}'.")
            raise SesionExpiradaError(str(e)) from e
        print(f"Error al crear nota '{titulo}': {e}")
        if hasattr(e, 'content'):
            print(f"Contenido del error: {e.content}")
        elif hasattr(e, 'message'):
            print(f"Mensaje del error: {e.message}")
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

def obtener_record_type_id(sf, objeto: str, nombre_record_type: str) -> str:
    """
    Obtiene el Id de un RecordType de Salesforce por su nombre y objeto.
    
    Args:
        sf: Instancia autenticada de Salesforce.
        objeto: Nombre del objeto SObject (ej. 'Lead', 'Account', 'Opportunity').
        nombre_record_type: Nombre del RecordType (ej. 'Masivo', 'Persona física - Nuevos negocios').
    
    Returns:
        Id del RecordType.
    """
    try:
        query = (
            "SELECT Id FROM RecordType "
            f"WHERE SObjectType = '{objeto}' AND Name = '{nombre_record_type}'"
        )
        result = query_con_reintento(sf, query)
        if result['totalSize'] == 0:
            raise HTTPException(
                status_code=500,
                detail=f"No se encontró RecordType '{nombre_record_type}' para {objeto}"
            )
        return result['records'][0]['Id']
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error al obtener RecordType: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error al obtener RecordType '{nombre_record_type}' para {objeto}: {str(e)}"
        )


def createCampaignMember(sf, member_data: dict) -> str:
    """
    Crea un registro en CampaignMember (Miembro de Campaña) en Salesforce.
    
    Recibe el diccionario completo para máxima flexibilidad.
    El servicio que lo llama construye los campos específicos.
    
    Args:
        sf: Instancia autenticada de Salesforce.
        member_data: Dict con los campos del CampaignMember.
    
    Returns:
        ID del CampaignMember creado.
    """
    try:
        result = sf.CampaignMember.create(member_data)
        print(f"CampaignMember creado exitosamente: {result}")
        return result['id']
    except Exception as e:
        if es_error_sesion(e):
            print("Sesión expirada al crear CampaignMember.")
            raise SesionExpiradaError(str(e)) from e
        print(f"Error al crear CampaignMember: {e}")
        raise


def crear_tarea_campana(sf, who_id: str, campaign_id: str, owner_id: str, descripcion: str) -> bool:
    """
    Crea una tarea en Salesforce asociada a un prospecto/contacto (WhoId) y una campaña (WhatId).
    
    Nota: Salesforce NO permite WhatId (campaña) cuando WhoId es un Lead.
    En ese caso, la campaña se incluye en la descripción.
    
    Args:
        sf: Instancia autenticada de Salesforce.
        who_id: ID del prospecto (Lead) o contacto (WhoId).
        campaign_id: ID de la campaña (WhatId, solo si WhoId es Contacto).
        owner_id: ID del usuario propietario de la tarea.
        descripcion: Descripción base de la tarea.
    
    Returns:
        True si se creó correctamente, False en caso contrario.
    """
    try:
        from app.services.crearCortizacion import fecha_recordatorio

        recordatorio = fecha_recordatorio()
        activity_date = recordatorio.split('T')[0]

        # Si WhoId es un Lead (00Q...), no se puede usar WhatId.
        # La campaña se agrega a la descripción.
        es_lead = who_id.startswith('00Q')
        descripcion_final = descripcion
        if es_lead:
            descripcion_final = (
                f"{descripcion}\n\n"
                f"Campaña: https://customer-customer-9846.lightning.force.com/lightning/r/Campaign/{campaign_id}/view"
            )

        task_data = {
            'WhoId': who_id,
            'OwnerId': owner_id,
            'Subject': 'Seguimiento de campaña',
            'ActivityDate': activity_date,
            'Status': 'Not Started',
            'Priority': 'High',
            'IsReminderSet': True,
            'Description': descripcion_final,
            'ReminderDateTime': recordatorio
        }

        # Solo incluir WhatId si NO es un Lead (Contacto o Cuenta)
        if not es_lead:
            task_data['WhatId'] = campaign_id

        headers_previos = dict(sf.headers)
        sf.headers.clear()
        headers = {
            'Sforce-Email-Notification': 'TRUE'
        }
        sf.headers.update(headers)

        response = sf.Task.create(task_data)
        print("Tarea de campaña creada", response)
        sf.headers.clear()
        sf.headers.update(headers_previos)
        
        return True
    except Exception as e:
        if es_error_sesion(e):
            print("Sesión expirada al crear tarea de campaña.")
            raise SesionExpiradaError(str(e)) from e
        print(f"Error al crear tarea de campaña: {e}")
        if hasattr(e, 'content'):
            print(f"Contenido del error: {e.content}")
        elif hasattr(e, 'message'):
            print(f"Mensaje del error: {e.message}")
        else:
            print(f"Error general: {str(e)}")
        return False


def crear_tarea_folio(sf, case_id: str, owner_id: str, descripcion: str) -> bool:
    """
    Crea una tarea de seguimiento en Salesforce asociada a un folio (Case).

    A diferencia de crearTarea/crear_tarea_campana (que usan WhoId para un
    Lead), un Case es un "What" en Salesforce, por lo que la tarea se asocia
    vía WhatId.

    Args:
        sf: Instancia autenticada de Salesforce.
        case_id: ID del Case al que asociar la tarea.
        owner_id: ID del usuario propietario de la tarea.
        descripcion: Descripción de la tarea.

    Returns:
        True si se creó correctamente, False en caso contrario.
    """
    try:
        from app.services.crearCortizacion import fecha_recordatorio

        recordatorio = fecha_recordatorio(19, 0)
        activity_date = recordatorio.split('T')[0]

        task_data = {
            'WhatId': case_id,
            'OwnerId': owner_id,
            'Subject': 'Seguimiento de folio',
            'ActivityDate': activity_date,
            'Status': 'Not Started',
            'Priority': 'High',
            'IsReminderSet': True,
            'Description': descripcion,
            'ReminderDateTime': recordatorio
        }

        headers_previos = dict(sf.headers)
        sf.headers.clear()
        headers = {
            'Sforce-Email-Notification': 'TRUE'
        }
        sf.headers.update(headers)

        response = sf.Task.create(task_data)
        print("Tarea de folio creada", response)
        sf.headers.clear()
        sf.headers.update(headers_previos)

        return True
    except Exception as e:
        if es_error_sesion(e):
            print("Sesión expirada al crear tarea de folio.")
            raise SesionExpiradaError(str(e)) from e
        print(f"Error al crear tarea de folio: {e}")
        if hasattr(e, 'content'):
            print(f"Contenido del error: {e.content}")
        elif hasattr(e, 'message'):
            print(f"Mensaje del error: {e.message}")
        else:
            print(f"Error general: {str(e)}")
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


