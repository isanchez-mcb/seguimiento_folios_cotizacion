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

def createLead(sf, lead_data: dict) -> str:
    try:
        headers = {'Sforce-Auto-Assign': 'TRUE'}
        sf.headers.update(headers)
        lead = sf.Lead.create(lead_data)
        sf.headers.pop('Sforce-Auto-Assign', None)
        print(f"Lead creado exitosamente: {lead}")
        return lead
    except Exception as e:
        error = str(e)
        print(e)
        if "DUPLICATES_DETECTED" in error:
            raise HTTPException(status_code=402, detail="Ya existe un prospecto con este expediente o este correo, gracias por su interés.")

        print(f"Error al crear el lead: {e}")
        raise

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

def crearTarea(sf, lead_id, owner_id, descripcion):
    try:
        from app.services.crearCortizacion import fecha_recordatorio

        recordatorio = fecha_recordatorio()
        activity_date = recordatorio.split('T')[0]

        task_data = {
            'WhoId': lead_id, 
            'OwnerId': owner_id,
            'Subject': 'Call',
            'ActivityDate': activity_date,
            'Status': 'Not Started',
            'Priority': 'High',
            'IsReminderSet': True,
            'Description': descripcion,
            'ReminderDateTime': recordatorio
        }

        headers = {
            'Sforce-Auto-Assign': 'FALSE', 
            'Sforce-Email-Notification': 'TRUE' 
        }
        sf.headers.update(headers)

        response = sf.Task.create(task_data)
        print("Tarea asignada", response)
        sf.headers.pop('Sforce-Email-Notification', None)
        
        return response
    except Exception as e:
        print(f"Error al crear la tareas {e}")
        if hasattr(e, 'content'):
            print(f"Contenido del error: {e.content}")
        elif hasattr(e, 'message'):
            print(f"Mensaje del error: {e.message}")
        else:
            print(f"Error general: {str(e)}")


