from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import CreateCotizacionRequest, CreateCotizacionResponse
from app.dependencias.sf_service import get_salesforce_data
from app.services.buscarFolio import buscar_folio 
import pandas as pd
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app.dependencias.security import verifiy_auth
from app.services.crearCortizacion import asignar_propietario_carrusel, buscar_asesor_activo, data_cotizacion, fecha_recordatorio, generar_texto, obtener_nombre_ramo
from app.services.sf_create_data import crear_nota, crearTarea, createLead
from app.services.enviar_correo import notificar_asignacion

router = APIRouter()

security = HTTPBasic()

@router.post("/cotizacion/crear", response_model=CreateCotizacionResponse, status_code=200, tags=["Cotización"])
def crear_cotizacion(request: CreateCotizacionRequest, sf=Depends(get_salesforce_data), auth_user: str = Depends(verifiy_auth)):
    try:
        lineas, descripcion = generar_texto(request)
        owner_id, nombre_propietario = asignar_propietario_carrusel(sf)

        ramo_activo = obtener_nombre_ramo(request)
        descripcion_con_ramo = f"Cotización: {ramo_activo}\n\n{descripcion}"
        lead_data = data_cotizacion(request, owner_id)
        lead, account_id = createLead(sf, lead_data)
        id_lead = lead['id']
        crear_nota(id_lead, sf, lineas, request)
        print("cotizacion realizada", lead_data)
        crearTarea(sf, id_lead, owner_id, descripcion_con_ramo, account_id=account_id)
        print(f"Asesor asignado: {nombre_propietario}")

        # Enviar notificación por correo al asesor asignado
        notificar_asignacion(
            sf=sf,
            owner_id=owner_id,
            nombre_asesor=nombre_propietario,
            lead_data=lead_data,
            ramo=ramo_activo,
            id_lead=id_lead
        )

        return CreateCotizacionResponse(asesor=str(nombre_propietario))
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=f"Error del servidor: {str(e)}")



@router.post("/cotizacion/tarea", response_model=CreateCotizacionResponse, status_code=200, tags=["Cotización"])
def crear_tarea(sf=Depends(get_salesforce_data), auth_user: str = Depends(verifiy_auth)):
    try:

        data_ejemplo = {
            'LeadSource' : 'Lucia',
            'FirstName' : f'Cotización: Prueba',
            'LastName' : 'Ian Uriel Sánchez Alvarado',
            'MobilePhone' : '+522211112145',
            'Ramos_de_interes__c' : 'VIDA',
            'RecordTypeId': '012WR000000GvGvYAK',
            'Tipo_de_prospecto__c': 'Masivo',
            'OwnerId': '005WR000008PRlCYAW'
        }

        lead, _ = createLead(sf, data_ejemplo)
        id_lead = lead['id']
        tarea = crearTarea(sf, id_lead, owner_id='005WR000008PRlCYAW', descripcion='Prueba')

        # Enviar notificación por correo al asesor asignado (prueba)
        notificar_asignacion(
            sf=sf,
            owner_id='005WR000008PRlCYAW',
            nombre_asesor='Administrador (prueba)',
            lead_data=data_ejemplo,
            ramo=data_ejemplo.get('Ramos_de_interes__c', 'Prueba'),
            id_lead=id_lead
        )
        
        return CreateCotizacionResponse(asesor="Prueba completada")
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=f"Error del servidor: {str(e)}")
