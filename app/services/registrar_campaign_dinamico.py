from typing import Optional, Tuple

from simple_salesforce import Salesforce

from app.models.schemas import RegistroCampaignDinamicoRequest
from app.services.asesor_campana import _obtener_cola_id, buscar_asesor_externo
from app.services.crearCortizacion import buscar_asesor_activo, fecha_recordatorio, normalizar_telefono
from app.dependencias.sf_service import get_salesforce_data, query_con_reintento
from app.services.registrar_campaign import (
    _buscar_cuenta_por_expediente,
    _es_verdadero,
    _resolver_empresa_por_tamano,
)
from app.services.sf_create_data import createCampaignMember, createLead, crear_nota_generica, crear_tarea_campana, obtener_record_type_id

from fastapi import HTTPException


# ─── Constantes ────────────────────────────────────────────────────

RECORD_TYPE_MASIVO = "Masivo"
RECORD_TYPE_NN_FISICA = "Persona física - Nuevos negocios"
COLA_EJECUTIVOS_NN = "Ejecutivos Nuevos Negocios"
LEAD_SOURCE_DINAMICO = "Sitio web"
SUBJECT_TAREA_CAMPANA = "Seguimiento de Campaña Buen Fin 2026"


def _resolver_nombre_completo(request: RegistroCampaignDinamicoRequest) -> str:
    return request.apellidos or f"{request.primer_nombre or ''} {request.segundo_nombre or ''}".strip() or "Sin apellido"


def _obtener_alias_usuario(sf: Salesforce, user_id: str) -> Optional[str]:
    """
    Obtiene el Alias del User asignado como owner de la tarea. El Alias
    equivale al numero_asesor (mismo criterio que usa /asesores-externos/buscar
    para encontrar al Asesor_externo__c correspondiente).
    """
    if not user_id:
        return None
    try:
        query = f"SELECT Id, Alias FROM User WHERE Id = '{user_id}'"
        result = query_con_reintento(sf, query)
        if result['totalSize'] > 0:
            return result['records'][0].get('Alias')
        return None
    except Exception as e:
        print(f"Error al obtener Alias del User {user_id}: {e}")
        return None


def _obtener_asesor_externo_id_por_owner(sf: Salesforce, user_id: str) -> Optional[str]:
    """
    Resuelve el Id del registro Asesor_externo__c correspondiente al User
    asignado como owner de la tarea. Asesor_externo_captura__c es un lookup
    a Asesor_externo__c (no texto), así que se necesita su Id, no el alias.
    El Alias del User equivale a Numero_de_asesor__c, que es como se busca
    el registro Asesor_externo__c.

    Numero_de_asesor__c es un campo numérico (la query de buscar_asesor_externo
    lo compara sin comillas), así que si el Alias no es puramente numérico
    (p. ej. el owner de respaldo/director, que no tiene numero_asesor) no se
    intenta la consulta: Salesforce la rechazaría con MALFORMED_QUERY, y de
    todas formas no existe ningún Asesor_externo__c para ese owner.
    """
    alias = _obtener_alias_usuario(sf, user_id)
    if not alias or not alias.strip().isdigit():
        return None
    asesor_data = buscar_asesor_externo(alias.strip(), sf)
    if asesor_data and asesor_data.get('Id'):
        return asesor_data['Id']
    return None


def _crear_nota_ocupacion(lead_id: str, request: RegistroCampaignDinamicoRequest, sf: Salesforce, last_name: str) -> None:
    if request.ocupacion and request.ocupacion.strip():
        html_ocupacion = f"Ocupación: {request.ocupacion.strip()}"
        titulo_nota = f'Ocupación - {last_name}'
        nota_creada = crear_nota_generica(lead_id, sf, html_ocupacion, titulo_nota)
        if nota_creada:
            print(f"Nota de ocupación creada para lead {lead_id}")
        else:
            print(f"ERROR: No se pudo crear la nota de ocupación para lead {lead_id}")


def _crear_nota_datos_eliminados_por_duplicado(
    lead_id: str,
    sf: Salesforce,
    valores_originales: dict,
    lead_data_final: dict,
    last_name: str
) -> None:
    """
    Si createLead tuvo que quitar el expediente y/o el correo para poder crear
    el lead (por DUPLICATES_DETECTED), deja constancia de esos datos originales
    en una nota para no perderlos, ya que se eliminaron del registro creado.
    """
    campos_eliminados = {
        etiqueta: valor
        for etiqueta, (campo_sf, valor) in valores_originales.items()
        if campo_sf not in lead_data_final
    }
    if not campos_eliminados:
        return

    lineas = [f"<li><b>{etiqueta}:</b> {valor}</li>" for etiqueta, valor in campos_eliminados.items()]
    html = (
        "<p>Estos datos se eliminaron automáticamente del prospecto para poder "
        "crearlo (ya existía un registro duplicado):</p><ul>" + "".join(lineas) + "</ul>"
    )
    titulo_nota = f'Datos eliminados por duplicado - {last_name}'
    nota_creada = crear_nota_generica(lead_id, sf, html, titulo_nota)
    if nota_creada:
        print(f"Nota de datos eliminados por duplicado creada para lead {lead_id}")
    else:
        print(f"ERROR: No se pudo crear la nota de datos eliminados por duplicado para lead {lead_id}")


def _buscar_ultimos_owners_campana(sf: Salesforce, campaign_id: str, limit: int = 5) -> list:
    """
    Devuelve los OwnerId de las últimas asignaciones hechas para esta campaña
    específica (campaign_id), combinando los dos caminos posibles:

    - Lado prospecto (Lead nuevo): el Lead no puede llevar WhatId de campaña en
      su Task (Salesforce no lo permite cuando WhoId es un Lead), pero el Lead
      mismo sí trae su propio campo Campana_del__c, así que se lee de ahí
      directamente.
    - Lado cuenta existente (Contacto): no se crea Lead, pero la Task sí puede
      llevar WhatId=campaign_id porque WhoId es un Contact.

    Se combinan ambas listas y se ordenan por fecha para reconstruir el orden
    real de atención, scoped a esta campaña (no se mezcla con otras campañas
    ni con el endpoint /campaign/registrar).
    """
    query_leads = (
        "SELECT OwnerId, CreatedDate FROM Lead "
        f"WHERE Campana_del__c = '{campaign_id}' "
        f"ORDER BY CreatedDate DESC LIMIT {limit}"
    )
    query_tareas = (
        "SELECT OwnerId, CreatedDate FROM Task "
        f"WHERE WhatId = '{campaign_id}' AND Subject = '{SUBJECT_TAREA_CAMPANA}' "
        f"ORDER BY CreatedDate DESC LIMIT {limit}"
    )

    registros = []
    try:
        result_leads = query_con_reintento(sf, query_leads)
        registros.extend(result_leads['records'])
    except Exception as e:
        print(f"Error al consultar últimos Leads de la campaña: {e}")

    try:
        result_tareas = query_con_reintento(sf, query_tareas)
        registros.extend(result_tareas['records'])
    except Exception as e:
        print(f"Error al consultar últimas tareas de la campaña: {e}")

    registros.sort(key=lambda r: r['CreatedDate'], reverse=True)
    return [r['OwnerId'] for r in registros[:limit]]


def _asignar_propietario_carrusel_dinamico(sf: Salesforce, campaign_id: str) -> Tuple[str, str]:
    """
    Variante propia del carrusel omnichannel para este endpoint.

    asignar_propietario_carrusel (crearCortizacion.py, usado por cotizacion/crear)
    decide el turno mirando los últimos OwnerId de Lead por LeadSource. En este
    endpoint eso no sirve: cuando el prospecto ya es cliente (flujo de cuenta
    existente) no se crea ningún Lead, solo Account/Contact/CampaignMember/Task,
    así que ese puntero nunca avanzaría y siempre repetiría al mismo asesor.
    Aquí se reconstruye el orden real combinando Lead.Campana_del__c (lado
    prospecto) y Task.WhatId (lado cuenta existente), scoped al campaign_id de
    esta petición. Ver _buscar_ultimos_owners_campana.
    """
    owners_list = buscar_asesor_activo(sf)
    size = len(owners_list)

    if size == 0:
        print("Omni-Channel vacío. Asignando a director Telemarketing por respaldo.")
        return '005WR00000CO8C1YAL', 'Pronto se le asignara un asesor'

    owners_list.sort(key=lambda x: x['id'])
    print(f"DEBUG: Asesores disponibles y ordenados para el carrusel: {owners_list}")

    just_ids = [owner['id'] for owner in owners_list]
    last_owners_ids = _buscar_ultimos_owners_campana(sf, campaign_id)
    print(f"DEBUG: Últimos Owners de la campaña {campaign_id}: {last_owners_ids}")

    start_index = 0
    for last_owner in last_owners_ids:
        if last_owner in just_ids:
            start_index = (just_ids.index(last_owner) + 1) % size
            print(f"DEBUG: El último en atender fue {last_owner}. Turno inicial para índice: {start_index}")
            break

    candidato = owners_list[start_index]
    print(f"¡Asignado por carrusel! -> ID: {candidato['id']}, Nombre: {candidato['name']}")
    return candidato['id'], candidato['name']


def _buscar_miembros_cola(sf: Salesforce, nombre_cola: str) -> list:
    """
    Devuelve los Users activos miembros de la cola `nombre_cola` (GroupMember),
    para rotarlos en un carrusel. A diferencia de buscar_asesor_activo (usado
    por el carrusel de Telemarketing), aquí NO se filtra por disponibilidad en
    Omnichannel: todos los miembros de la cola entran al carrusel.
    """
    try:
        query_cola = (
            "SELECT UserOrGroupId FROM GroupMember "
            f"WHERE Group.Name = '{nombre_cola}' AND Group.Type = 'Queue'"
        )
        resultado_cola = query_con_reintento(sf, query_cola)
        ids_miembros = [rm['UserOrGroupId'] for rm in resultado_cola['records']]
        if not ids_miembros:
            return []

        ids_in = "','".join(ids_miembros)
        query_usuarios = f"SELECT Id, Name FROM User WHERE Id IN ('{ids_in}') AND IsActive = True"
        resultado_usuarios = query_con_reintento(sf, query_usuarios)

        miembros = [{'id': u['Id'], 'name': u['Name']} for u in resultado_usuarios['records']]
        print(f"Miembros activos de la cola '{nombre_cola}': {miembros}")
        return miembros
    except Exception as e:
        print(f"Error al buscar miembros de la cola '{nombre_cola}': {e}")
        return []


def _buscar_ultimos_owners_lead_nn(sf: Salesforce, campaign_id: str, limit: int = 5) -> list:
    """
    Último turno del carrusel de Nuevos Negocios, scoped a esta campaña.
    El flujo de Nuevos Negocios siempre crea un Lead (nunca actualiza cuenta
    existente), así que basta con mirar el OwnerId de los últimos Leads de
    esta campaña con Negocio__c = 'NUEVOS NEGOCIOS' (se excluyen los leads
    Masivo de la misma campaña: son carruseles independientes, con pools de
    usuarios distintos).
    """
    query = (
        "SELECT OwnerId, CreatedDate FROM Lead "
        f"WHERE Campana_del__c = '{campaign_id}' AND Negocio__c = 'NUEVOS NEGOCIOS' "
        f"ORDER BY CreatedDate DESC LIMIT {limit}"
    )
    try:
        result = query_con_reintento(sf, query)
        return [r['OwnerId'] for r in result['records']]
    except Exception as e:
        print(f"Error al consultar últimos Leads de Nuevos Negocios de la campaña: {e}")
        return []


def _asignar_propietario_carrusel_nn(sf: Salesforce, campaign_id: str) -> Tuple[str, str]:
    """
    Carrusel para Nuevos Negocios: rota entre TODOS los miembros de la cola
    'Ejecutivos Nuevos Negocios' (sin filtrar por disponibilidad/Omnichannel),
    scoped a esta campaña. Si la cola no tiene miembros, cae de vuelta a
    asignar la cola misma como owner (comportamiento previo).
    """
    owners_list = _buscar_miembros_cola(sf, COLA_EJECUTIVOS_NN)
    size = len(owners_list)

    if size == 0:
        print(f"La cola '{COLA_EJECUTIVOS_NN}' no tiene miembros activos. Asignando a la cola directamente.")
        cola_id = _obtener_cola_id(COLA_EJECUTIVOS_NN, sf)
        return cola_id, COLA_EJECUTIVOS_NN

    owners_list.sort(key=lambda x: x['id'])
    print(f"DEBUG: Miembros de la cola '{COLA_EJECUTIVOS_NN}' ordenados para el carrusel: {owners_list}")

    just_ids = [owner['id'] for owner in owners_list]
    last_owners_ids = _buscar_ultimos_owners_lead_nn(sf, campaign_id)
    print(f"DEBUG: Últimos Owners de Nuevos Negocios en la campaña {campaign_id}: {last_owners_ids}")

    start_index = 0
    for last_owner in last_owners_ids:
        if last_owner in just_ids:
            start_index = (just_ids.index(last_owner) + 1) % size
            print(f"DEBUG: El último en atender fue {last_owner}. Turno inicial para índice: {start_index}")
            break

    candidato = owners_list[start_index]
    print(f"¡Asignado por carrusel de Nuevos Negocios! -> ID: {candidato['id']}, Nombre: {candidato['name']}")
    return candidato['id'], candidato['name']


# ─── Nuevos Negocios: siempre Lead nuevo, owner = carrusel de la cola ──

def _crear_lead_nuevos_negocios(
    request: RegistroCampaignDinamicoRequest,
    telefono_normalizado: str,
    sf: Salesforce
) -> Tuple[None, None, str, str, str]:
    last_name = _resolver_nombre_completo(request)

    record_type_id = obtener_record_type_id(sf, 'Lead', RECORD_TYPE_NN_FISICA)
    owner_id, _nombre_ejecutivo = _asignar_propietario_carrusel_nn(sf, request.campaign_id)

    print("Re-obteniendo sesión de Salesforce tras la asignación del carrusel...")
    sf = get_salesforce_data()

    lead_data = {
        'LeadSource': LEAD_SOURCE_DINAMICO,
        'FirstName': request.primer_nombre or '',
        'MiddleName': request.segundo_nombre or '',
        'LastName': last_name,
        'Email': request.correo,
        'MobilePhone': telefono_normalizado,
        'Negocio__c': 'NUEVOS NEGOCIOS',
        'Status': 'Nuevo',
        'Nivel_interes__c': 'Alto',
        'Campana_del__c': request.campaign_id,
        'RecordTypeId': record_type_id,
    }
    if owner_id:
        lead_data['OwnerId'] = owner_id

    valores_originales = {}
    if 'Email' in lead_data:
        valores_originales['Correo electrónico'] = ('Email', lead_data['Email'])

    lead_result, _ = createLead(sf, lead_data)
    lead_id = lead_result['id']
    print(f"Lead creado para campaña (Nuevos Negocios): {lead_id}")

    _crear_nota_datos_eliminados_por_duplicado(lead_id, sf, valores_originales, lead_data, last_name)
    _crear_nota_ocupacion(lead_id, request, sf, last_name)

    descripcion_tarea = f"Registro en campaña desde landing page.\nLead: {lead_id}"
    owner_tarea = owner_id or _obtener_cola_id(COLA_EJECUTIVOS_NN, sf)
    tarea_creada = crear_tarea_campana(sf, lead_id, request.campaign_id, owner_tarea, descripcion_tarea, subject=SUBJECT_TAREA_CAMPANA)
    if tarea_creada:
        print(f"Tarea de campaña creada para lead {lead_id}")
    else:
        print(f"ERROR: No se pudo crear la tarea de campaña para lead {lead_id}")

    return None, None, lead_id, "LEAD_CREADO", "NUEVOS NEGOCIOS"


# ─── Masivo: Lead nuevo (cuenta no encontrada o sin expediente), owner = carrusel ──

def _crear_lead_masivo(
    request: RegistroCampaignDinamicoRequest,
    telefono_normalizado: str,
    sf: Salesforce
) -> Tuple[None, None, str, str, str]:
    last_name = _resolver_nombre_completo(request)

    record_type_id = obtener_record_type_id(sf, 'Lead', RECORD_TYPE_MASIVO)
    owner_id, _nombre_asesor = _asignar_propietario_carrusel_dinamico(sf, request.campaign_id)

    print("Re-obteniendo sesión de Salesforce tras la asignación del carrusel...")
    sf = get_salesforce_data()

    negocio_resuelto = request.negocio

    lead_data = {
        'LeadSource': LEAD_SOURCE_DINAMICO,
        'FirstName': request.primer_nombre or '',
        'MiddleName': request.segundo_nombre or '',
        'LastName': last_name,
        'Email': request.correo,
        'MobilePhone': telefono_normalizado,
        'Negocio__c': negocio_resuelto,
        'Status': 'Nuevo',
        'Nivel_interes__c': 'Alto',
        'Campana_del__c': request.campaign_id,
        'RecordTypeId': record_type_id,
    }
    if owner_id:
        lead_data['OwnerId'] = owner_id
    if request.expediente and request.expediente.strip():
        lead_data['No_expediente_No_colaborador__c'] = request.expediente

    valores_originales = {}
    if 'Email' in lead_data:
        valores_originales['Correo electrónico'] = ('Email', lead_data['Email'])
    if 'No_expediente_No_colaborador__c' in lead_data:
        valores_originales['Expediente/No. colaborador'] = ('No_expediente_No_colaborador__c', lead_data['No_expediente_No_colaborador__c'])

    try:
        lead_result, _ = createLead(sf, lead_data)
    except Exception as e:
        error_str = str(e)
        if "FIELD_CUSTOM_VALIDATION_EXCEPTION" in error_str and "No_expediente_No_colaborador__c" in error_str:
            print("Validación de empresa falló en lead. Resolviendo empresa por tamaño del expediente...")

            empresa_por_tamano = _resolver_empresa_por_tamano(request.expediente)
            if empresa_por_tamano:
                lead_data['Negocio__c'] = empresa_por_tamano
                negocio_resuelto = empresa_por_tamano

                expediente_limpio = request.expediente.strip()
                if len(expediente_limpio) < 5:
                    lead_data['No_expediente_No_colaborador__c'] = expediente_limpio.zfill(5)
                    print(f"Expediente rellenado con ceros: {lead_data['No_expediente_No_colaborador__c']}")

                print(f"Empresa resuelta por tamaño para lead: {empresa_por_tamano}")
                lead_result, _ = createLead(sf, lead_data)
            else:
                raise
        else:
            raise

    lead_id = lead_result['id']
    print(f"Lead creado para campaña (Masivo): {lead_id}")

    _crear_nota_datos_eliminados_por_duplicado(lead_id, sf, valores_originales, lead_data, last_name)
    _crear_nota_ocupacion(lead_id, request, sf, last_name)

    descripcion_tarea = f"Registro en campaña desde landing page.\nLead: {lead_id}"
    owner_tarea = owner_id or COLA_EJECUTIVOS_NN
    tarea_creada = crear_tarea_campana(sf, lead_id, request.campaign_id, owner_tarea, descripcion_tarea, subject=SUBJECT_TAREA_CAMPANA)
    if tarea_creada:
        print(f"Tarea de campaña creada para lead {lead_id}")
    else:
        print(f"ERROR: No se pudo crear la tarea de campaña para lead {lead_id}")

    return None, None, lead_id, "LEAD_CREADO", negocio_resuelto


# ─── Masivo: cuenta ya existente → actualizar + CampaignMember, owner = carrusel ──

def _actualizar_cuenta_existente(
    request: RegistroCampaignDinamicoRequest,
    account: dict,
    telefono_normalizado: str,
    sf: Salesforce
) -> Tuple[str, str, None, str, str]:
    account_id = account['Id']
    print(f"Cuenta encontrada: {account_id} - {account.get('Name', '')}")

    update_data = {
        'Email_landing_page__c': request.correo,
    }
    if telefono_normalizado:
        update_data['Phone'] = telefono_normalizado

    person_email_actual = account.get('PersonEmail')
    if not person_email_actual:
        update_data['PersonEmail'] = request.correo
        print("PersonEmail vacío → se rellena con el correo del usuario")

    person_phone_actual = account.get('PersonMobilePhone')
    if not person_phone_actual and telefono_normalizado:
        update_data['PersonMobilePhone'] = telefono_normalizado
        print("PersonMobilePhone vacío → se rellena con el teléfono del usuario")

    cuenta_verificada = account.get('Cuenta_verificada__c')
    if not _es_verdadero(cuenta_verificada):
        update_data['Cuenta_verificada__c'] = True
        print("Cuenta_verificada__c en false → se pasa a true")

    negocio_actual = account.get('Negocio__c')
    if not negocio_actual:
        update_data['Negocio__c'] = request.negocio
        print("Negocio__c vacío → se rellena con el negocio del usuario")

    try:
        sf.Account.update(account_id, update_data)
        print(f"Cuenta {account_id} actualizada: {', '.join(update_data.keys())}")
    except Exception as e:
        error_str = str(e)
        print(f"Error al actualizar cuenta {account_id}: {error_str}")

        if "DUPLICATES_DETECTED" in error_str and "Email" in error_str:
            print("Duplicado de PersonEmail detectado. Eliminando PersonEmail del update_data y reintentando...")
            update_data.pop('PersonEmail', None)
            try:
                sf.Account.update(account_id, update_data)
                print(f"Cuenta {account_id} actualizada sin PersonEmail: {', '.join(update_data.keys())}")
            except Exception as retry_e:
                print(f"Error en reintento sin PersonEmail: {retry_e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Error al actualizar la cuenta incluso después de omitir PersonEmail: {str(retry_e)}"
                )

        elif "FIELD_CUSTOM_VALIDATION_EXCEPTION" in error_str and "No_expediente_No_colaborador__c" in error_str:
            print("Regla de validación de expediente detectada. Reintentando con Negocio__c y No_expediente del formulario...")
            update_data['No_expediente_No_colaborador__c'] = request.expediente
            update_data['Negocio__c'] = request.negocio
            try:
                sf.Account.update(account_id, update_data)
                print(f"Cuenta {account_id} actualizada en reintento: {', '.join(update_data.keys())}")
            except Exception as retry_e:
                retry_error_str = str(retry_e)
                print(f"Error en reintento de actualización: {retry_error_str}")

                if "DUPLICATES_DETECTED" in retry_error_str and "Email" in retry_error_str:
                    update_data.pop('PersonEmail', None)
                    try:
                        sf.Account.update(account_id, update_data)
                        print(f"Cuenta {account_id} actualizada en segundo reintento: {', '.join(update_data.keys())}")
                    except Exception as retry2_e:
                        print(f"Error en segundo reintento: {retry2_e}")
                        raise HTTPException(
                            status_code=500,
                            detail=f"Error al actualizar la cuenta incluso después de corregir expediente y email: {str(retry2_e)}"
                        )
                elif "FIELD_CUSTOM_VALIDATION_EXCEPTION" in retry_error_str and "No_expediente_No_colaborador__c" in retry_error_str:
                    empresa_por_tamano = _resolver_empresa_por_tamano(request.expediente)
                    if empresa_por_tamano:
                        update_data['Negocio__c'] = empresa_por_tamano
                        try:
                            sf.Account.update(account_id, update_data)
                            print(f"Cuenta {account_id} actualizada en último intento: {', '.join(update_data.keys())}")
                        except Exception as retry3_e:
                            print(f"Error en último intento: {retry3_e}")
                            raise HTTPException(
                                status_code=500,
                                detail=f"Error al actualizar la cuenta incluso después de resolver empresa por tamaño: {str(retry3_e)}"
                            )
                    else:
                        raise HTTPException(
                            status_code=500,
                            detail=f"No se pudo resolver la empresa por tamaño del expediente: {request.expediente}"
                        )
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Error al actualizar la cuenta incluso después de corregir expediente y negocio: {retry_error_str}"
                    )
        else:
            raise HTTPException(status_code=500, detail=f"Error al actualizar la cuenta: {error_str}")

    query_contact = (
        "SELECT Id, Name, Email FROM Contact "
        f"WHERE AccountId = '{account_id}' "
        "ORDER BY CreatedDate DESC"
    )
    result_contact = query_con_reintento(sf, query_contact)
    if result_contact['totalSize'] == 0:
        raise HTTPException(status_code=404, detail=f"No se encontró contacto asociado a la cuenta: {account_id}")

    contact = result_contact['records'][0]
    contact_id = contact['Id']
    print(f"Contacto encontrado: {contact_id} - {contact.get('Name', '')}")

    owner_id, _nombre_asesor = _asignar_propietario_carrusel_dinamico(sf, request.campaign_id)

    print("Re-obteniendo sesión de Salesforce tras la asignación del carrusel...")
    sf = get_salesforce_data()

    member_data = {
        'ContactId': contact_id,
        'CampaignId': request.campaign_id,
        'Status': 'Registrado',
    }

    asesor_externo_id = _obtener_asesor_externo_id_por_owner(sf, owner_id)
    if asesor_externo_id:
        member_data['Asesor_externo_captura__c'] = asesor_externo_id
        print(f"CampaignMember → Asesor_externo_captura__c = {asesor_externo_id}")

    try:
        campaign_member_id = createCampaignMember(sf, member_data)
        print(f"CampaignMember creado: {campaign_member_id}")
    except Exception as e:
        error_str = str(e)
        if "DUPLICATE_VALUE" in error_str and "Ya es un miembro de campaña" in error_str:
            print("El contacto ya es miembro de la campaña")
            campaign_member_id = "EXISTENTE"
        else:
            print(f"Error al crear CampaignMember: {e}")
            raise HTTPException(status_code=500, detail=f"Error al crear el miembro de campaña: {str(e)}")

    if campaign_member_id != "EXISTENTE":
        descripcion_tarea = f"Registro en campaña desde landing page.\nContacto: {contact_id}\nCuenta: {account_id}"
        owner_tarea = owner_id or COLA_EJECUTIVOS_NN
        tarea_creada = crear_tarea_campana(sf, contact_id, request.campaign_id, owner_tarea, descripcion_tarea, subject=SUBJECT_TAREA_CAMPANA)
        if tarea_creada:
            print(f"Tarea de campaña creada para contacto {contact_id}")
        else:
            print(f"ERROR: No se pudo crear la tarea de campaña para contacto {contact_id}")

    return account_id, contact_id, None, campaign_member_id, request.negocio


# ─── Orquestador principal ────────────────────────────────────────

def registrar_en_campaign_dinamico(
    request: RegistroCampaignDinamicoRequest,
    sf: Salesforce
) -> Tuple[Optional[str], Optional[str], Optional[str], str, str]:
    """
    Registra un prospecto en una campaña de Salesforce (id de campaña dinámico).

    Flujo:
    1. Si request.negocio viene vacío → Nuevos Negocios: siempre crea un Lead
       nuevo, owner = cola "Ejecutivos Nuevos Negocios".
    2. Si request.negocio viene lleno → Masivo:
       a. Si hay expediente, busca la cuenta existente con la misma cascada
          que /campaign/registrar. Si la encuentra → actualiza cuenta y crea
          CampaignMember.
       b. Si no hay cuenta (o no hay expediente) → crea Lead nuevo.
       En ambos casos el owner se resuelve con el carrusel omnichannel de
       asesores de Telemarketing activos.

    Returns:
        Tuple (account_id, contact_id, lead_id, campaign_member_id, negocio)
    """
    telefono_normalizado = normalizar_telefono(request.telefono) if request.telefono else ""

    negocio_vacio = not request.negocio or not request.negocio.strip()
    if negocio_vacio:
        print("Negocio vacío. Creando lead como Nuevos Negocios...")
        return _crear_lead_nuevos_negocios(request, telefono_normalizado, sf)

    if not request.expediente or not request.expediente.strip():
        print("Masivo sin expediente. Creando lead para campaña...")
        return _crear_lead_masivo(request, telefono_normalizado, sf)

    account = _buscar_cuenta_por_expediente(sf, request.expediente, request.negocio)
    if account is None:
        print("Cuenta no encontrada. Creando lead para campaña...")
        return _crear_lead_masivo(request, telefono_normalizado, sf)

    print("Re-obteniendo sesión de Salesforce tras búsqueda de cuenta...")
    sf = get_salesforce_data()
    return _actualizar_cuenta_existente(request, account, telefono_normalizado, sf)
