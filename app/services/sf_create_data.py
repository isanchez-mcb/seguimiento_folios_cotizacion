import base64

from fastapi import HTTPException
from simple_salesforce import Salesforce


def createOpportunity(sf, oportunidad_data: dict) -> str:
    try:
        oportunidad = sf.Opportunity.create(oportunidad_data)

        print(f"Oportunidad creada exitosamente: {oportunidad}")
        return oportunidad
    except Exception as e:
        print(e)
        print(f"Error al crear la oportunidad: {e}")
        raise

def createLead(sf, lead_data: dict) -> tuple:
    """
    Crea un lead en Salesforce.
    
    Si se detecta DUPLICATES_DETECTED por la regla Masivo_2_0 (expediente duplicado),
    extrae el AccountId del error, elimina No_expediente_No_colaborador__c de los datos
    y reintenta la creación.
    
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
            account_id = None
            try:
                # Extraer el AccountId del error (formato: 'Id': '001WR...')
                import re
                match = re.search(r"'Id':\s*'(\w+)'", error_str)
                if match:
                    account_id = match.group(1)
                    print(f"Cuenta duplicada encontrada: {account_id}")
            except Exception as parse_error:
                print(f"Error al parsear account_id del error: {parse_error}")

            # Eliminar expediente y reintentar
            if 'No_expediente_No_colaborador__c' in lead_data:
                del lead_data['No_expediente_No_colaborador__c']
                if 'Negocio__c' in lead_data:
                    del lead_data['Negocio__c']
                print("Expediente eliminado del lead_data, reintentando...")
                try:
                    sf.headers.update({'Sforce-Auto-Assign': 'TRUE'})
                    lead = sf.Lead.create(lead_data)
                    sf.headers.pop('Sforce-Auto-Assign', None)
                    print(f"Lead creado exitosamente en reintento: {lead}")
                    return lead, account_id
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
                            return lead, account_id
                        except Exception as retry2_e:
                            print(f"Error en segundo reintento: {retry2_e}")
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
                        return lead, account_id
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
        result = sf.query(query)
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
        print(f"Error al crear tarea de campaña: {e}")
        if hasattr(e, 'content'):
            print(f"Contenido del error: {e.content}")
        elif hasattr(e, 'message'):
            print(f"Mensaje del error: {e.message}")
        else:
            print(f"Error general: {str(e)}")
        return False


def crearTarea(sf, lead_id, owner_id, descripcion, account_id=None):
    try:
        from app.services.crearCortizacion import fecha_recordatorio

        recordatorio = fecha_recordatorio()
        activity_date = recordatorio.split('T')[0]

        # Si hay una cuenta duplicada, agregar enlace al final de la descripción
        descripcion_final = descripcion
        if account_id:
            descripcion_final = f"{descripcion}\n\nCuenta asociada: https://customer-customer-9846.lightning.force.com/lightning/r/Account/{account_id}/view"

        task_data = {
            'WhoId': lead_id, 
            'OwnerId': owner_id,
            'Subject': 'Call',
            'ActivityDate': activity_date,
            'Status': 'Not Started',
            'Priority': 'High',
            'IsReminderSet': True,
            'Description': descripcion_final,
            'ReminderDateTime': recordatorio
        }

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


