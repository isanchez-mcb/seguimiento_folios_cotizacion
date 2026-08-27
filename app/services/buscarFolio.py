import dateutil.parser
from simple_salesforce import Salesforce
from typing import Dict, Any, Optional, OrderedDict
from app.utils.diccionarios import tipo_folios, tiempos_folios
from datetime import datetime, timezone, timedelta

def calcular_dias(start_date, end_date):
    inicio = start_date.date()
    fin = end_date.date()
    if inicio >= fin:
        return 0
    
    dias_laborales = 0
    delta = timedelta(days=1)

    current = inicio + delta

    while current <= fin:
        if current.weekday() < 5:
            dias_laborales += 1
        current += delta

    return dias_laborales

def ajustar_horas(date):
    try:
        hora_ajustada = dateutil.parser.parse(date)
        hora_ajustada = hora_ajustada - timedelta(hours=6)

        return hora_ajustada.isoformat()
    except Exception as e:
        print(e)
        return date

def buscar_folio(CaseNumber: str, sf: Salesforce) -> str:
    if len(CaseNumber) < 8:
        ZerosSize = 8 - len(CaseNumber)
        CaseNumber = ZerosSize*"0" + CaseNumber
    try:
        query = f"SELECT CreatedDate, Case.Account.No_expediente_No_colaborador__c, Case.Account.Name, Case.Tipo_de_movimiento__c, Case.P_liza_de_seguro__r.Aseguradora__c, Case.P_liza_de_seguro__r.Producto__c, Case.P_liza_de_seguro__r.Ramos__c, Case.P_liza_de_seguro__r.Sub_ramos__c, Case.P_liza_de_seguro__r.Negocio__c, NewValue, Case.Status, Case.CreatedDate, Case.RecordType.Name, Case.CaseNumber FROM CaseHistory WHERE Field = 'Status' and Case.RecordType.Name NOT IN ('7.- Posible cancelación', '9.- Contacto') and case.casenumber = '{CaseNumber}'"
        result = sf.query(query)
        print(result)
        if result['totalSize'] == 0:
            # El Case pudo haberse creado hace muy poco: CaseHistory solo
            # registra cambios de Status, no el valor inicial ('Creado') con
            # el que nace el registro. Se intenta un fallback consultando
            # el Case directamente antes de asumir que no existe.
            return buscar_folio_creado(CaseNumber, sf)
        else:
            result = formatear_folio(result)
            return result
    except Exception as e:
        print(f"Error {e}")


def buscar_folio_creado(CaseNumber: str, sf: Salesforce) -> Optional[Dict[str, Any]]:
    """
    Fallback para folios recién creados que aún no tienen CaseHistory de
    Status (Salesforce no registra el valor inicial al crear el registro,
    solo cambios posteriores). Consulta el Case directamente y lo presenta
    como si su etapa inicial ('Creado') ya fuera 'Recibido'.

    Retorna None si el Case tampoco existe con esta consulta (folio
    realmente inexistente, o es de un RecordType excluido).
    """
    try:
        query = (
            "SELECT CreatedDate, Account.No_expediente_No_colaborador__c, Account.Name, "
            "Tipo_de_movimiento__c, P_liza_de_seguro__r.Aseguradora__c, P_liza_de_seguro__r.Producto__c, "
            "P_liza_de_seguro__r.Ramos__c, P_liza_de_seguro__r.Sub_ramos__c, P_liza_de_seguro__r.Negocio__c, "
            "Status, RecordType.Name, CaseNumber "
            "FROM Case "
            f"WHERE CaseNumber = '{CaseNumber}' "
            "AND RecordType.Name NOT IN ('7.- Posible cancelación', '9.- Contacto')"
        )
        result = sf.query(query)
        if result['totalSize'] == 0:
            return None
        return formatear_folio_creado(result['records'][0])
    except Exception as e:
        print(f"Error {e}")
        return None


def formatear_folio_creado(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Arma la respuesta (mismo formato que formatear_folio) para un Case sin
    CaseHistory de Status todavía, mostrando su etapa inicial como
    'Recibido'.
    """
    tipo_folio = case_data.get('RecordType', {}).get('Name')
    tipo_folio = tipo_folio[4:] if tipo_folio else "SIN INFORMACIÓN"

    account_data = case_data.get('Account', {}) or {}
    no_colaborador = account_data.get('No_expediente_No_colaborador__c') or "SIN INFORMACIÓN"
    nombre = account_data.get('Name') or "SIN INFORMACIÓN"

    poliza_data = case_data.get('P_liza_de_seguro__r', {}) or {}
    aseguradora = poliza_data.get('Aseguradora__c') or "SIN INFORMACIÓN"
    producto = poliza_data.get('Producto__c') or "SIN INFORMACIÓN"
    negocio = poliza_data.get('Negocio__c') or "SIN INFORMACIÓN"
    ramo = poliza_data.get('Ramos__c') or "SIN INFORMACIÓN"
    sub_ramo = poliza_data.get('Sub_ramos__c') or "SIN INFORMACIÓN"
    tipo_movimiento = case_data.get('Tipo_de_movimiento__c') or "SIN INFORMACIÓN"

    max_dias = ''
    try:
        dias_por_aseguradora = tiempos_folios.dias_maximos.get(aseguradora)
        if dias_por_aseguradora:
            dias_por_producto = dias_por_aseguradora.get(producto)
            if dias_por_producto:
                dias_por_negocio = dias_por_producto.get(negocio)
                if dias_por_negocio:
                    max_dias = dias_por_negocio.get(tipo_movimiento, '')
    except Exception:
        max_dias = ''

    current_day = datetime.now(timezone.utc)
    created_day = ajustar_horas(case_data.get('CreatedDate'))
    created_day = dateutil.parser.parse(created_day)
    days_passed = calcular_dias(created_day, current_day)

    if max_dias == '':
        dias_restantes = "SIN INFORMACIÓN"
        max_dias = "SIN INFORMACIÓN"
    else:
        dias_restantes = max_dias - days_passed
        dias_restantes = "ATRASADO" if dias_restantes <= 0 else dias_restantes

    # Resolver 'Status' con la misma tabla de mapeo que usa formatear_folio;
    # si el status actual no estuviera mapeado, se muestra 'Recibido' por default
    # (en este punto el Case no tiene historial, así que apenas va comenzando).
    status_dict_name = tipo_folios.recordType_map.get(tipo_folio)
    status_dict = getattr(tipo_folios, status_dict_name, {}) if status_dict_name else {}
    status_cliente = status_dict.get(case_data.get('Status'), 'Recibido')

    case_info = {
        'No_colaborador': no_colaborador,
        'Nombre': nombre,
        'Case': case_data.get('CaseNumber'),
        'CreatedDate': created_day,
        'Status': status_cliente,
        'Tipo': tipo_folio,
        'Aseguradora': aseguradora,
        'Ramo': ramo,
        'Subramo': sub_ramo,
        'Producto': producto,
        'Empresa': negocio,
        'Tipo_movimiento': tipo_movimiento,
        'Dias_maximos': max_dias,
        'Dias_transcurridos': days_passed,
        'Dias_restantes': dias_restantes
    }

    case_history = [{
        'DateHistory': created_day,
        'StatusHistory': status_cliente,
        'Note': tipo_folios.referencia_clientes.get(status_cliente, '')
    }]

    return {
        "CaseNumber": case_info,
        "Case_History": case_history
    }

def formatear_folio(case_list: Dict[str, Any]) -> list[Dict[str, Any]]:
    if not case_list:
        return []
    records = case_list['records']
    cleaned_records = []
    case_list_response = {}
    final_response = {
        "CaseNumber": {},
        "Case_History": []
    }
    for record in records:
        current_record = dict(record)
        current_record.pop('attributes', None) 

        if not case_list_response and 'Case' in current_record:
            case_data = current_record['Case']
            tipo_folio = case_data.get('RecordType', {}).get('Name')
            tipo_folio = tipo_folio[4:]
            no_colaborador = 'SIN INFORMACIÓN'
            nombre = 'SIN INFORMACIÓN'
            aseguradora = "SIN INFORMACIÓN"
            producto = "SIN INFORMACIÓN"
            negocio = "SIN INFORMACIÓN"
            ramo = "SIN INFORMACIÓN"
            sub_ramo = "SIN INFORMACIÓN"
            tipo_movimiento = "SIN INFORMACIÓN"
            max_dias = ''
            try:
                aseguradora_data = case_data.get('P_liza_de_seguro__r', {}).get('Aseguradora__c')
                producto_data = case_data.get('P_liza_de_seguro__r', {}).get('Producto__c')
                negocio_data = case_data.get('P_liza_de_seguro__r', {}).get('Negocio__c')
                tipo_movimiento_data = case_data.get('Tipo_de_movimiento__c')
                ramo_data = case_data.get('P_liza_de_seguro__r', {}).get('Ramos__c')
                subramo_data = case_data.get('P_liza_de_seguro__r', {}).get('Sub_ramos__c')
                no_colaborador_data = case_data.get('Account', {}).get('No_expediente_No_colaborador__c')
                nombre_data = case_data.get('Account', {}).get('Name')

                aseguradora = aseguradora_data if aseguradora_data is not None else "SIN INFORMACIÓN"
                producto = producto_data if producto_data is not None else "SIN INFORMACIÓN"
                negocio = negocio_data if negocio_data is not None else "SIN INFORMACIÓN"
                tipo_movimiento = tipo_movimiento_data if tipo_movimiento_data is not None else "SIN INFORMACIÓN"
                ramo = ramo_data if ramo_data is not None else "SIN INFORMACIÓN"
                sub_ramo = subramo_data if subramo_data is not None else "SIN INFORMACIÓN"
                no_colaborador = no_colaborador_data if no_colaborador_data is not None else "SIN INFORMACIÓN"
                nombre = nombre_data if nombre_data is not None else "SIN INFORMACIÓN"

                dias_por_aseguradora = tiempos_folios.dias_maximos.get(aseguradora)

                if dias_por_aseguradora:
                    dias_por_producto = dias_por_aseguradora.get(producto)

                    if dias_por_producto:
                        dias_por_negocio = dias_por_producto.get(negocio)

                        if dias_por_negocio:
                            max_dias = dias_por_negocio.get(tipo_movimiento, '')
            except:
                max_dias = ''


            current_day = datetime.now(timezone.utc)
            created_day = case_data.get('CreatedDate')
            created_day = ajustar_horas(created_day)
            created_day = dateutil.parser.parse(created_day)
            days_passed = calcular_dias(created_day, current_day)

            if max_dias == '':
                dias_restantes = "SIN INFORMACIÓN"
                max_dias = "SIN INFORMACIÓN"
            else:
                dias_restantes = max_dias - days_passed

                if dias_restantes <= 0:
                    dias_restantes = "ATRASADO"
                else:
                    dias_restantes = dias_restantes

            case_info = {
                    'No_colaborador': no_colaborador,
                    'Nombre': nombre,
                    'Case': case_data.get('CaseNumber'),
                    'CreatedDate': created_day,
                    'Status': case_data.get('Status'),
                    'Tipo': tipo_folio,
                    'Aseguradora': aseguradora,
                    'Ramo': ramo,
                    'Subramo': sub_ramo,
                    'Producto': producto,
                    'Empresa': negocio,
                    'Tipo_movimiento': tipo_movimiento,
                    'Dias_maximos': max_dias,
                    'Dias_transcurridos' : days_passed,
                    'Dias_restantes' : dias_restantes
                }
            
            if isinstance(case_data, (Dict, OrderedDict)):
                case_data.pop('attributes', None)

        note = ""

        if case_info.get('Tipo') in tipo_folios.recordType_map:
            status_map = tipo_folios.recordType_map[case_info.get('Tipo')]
            status_map = getattr(tipo_folios, status_map, {})
            status_map = status_map.get(current_record.get('NewValue'))
            if status_map is None:
                continue
            else:
                referencia = tipo_folios.referencia_clientes[status_map]

        else:
            note = "Sin Status"

        date_history = current_record.get('CreatedDate')
        date_history = ajustar_horas(date_history)
        date_history = dateutil.parser.parse(date_history)
        case_list_response = {
            'DateHistory' : date_history,
            'StatusHistory' : status_map,
            'Note' : referencia
        }

        cleaned_records.append(case_list_response)

    cleaned_records.sort(key=lambda x:x['DateHistory'])

    last_status = cleaned_records[-1].get('StatusHistory') 

    if not cleaned_records:
        return None
    
    if last_status is not None:
        case_info['Status'] = last_status

    if last_status == 'Solicitud Finalizada':
        case_info['Dias_transcurridos'] = "Finalizado"
        case_info['Dias_restantes'] = "Finalizado"
    
    final_response['CaseNumber'] = case_info
    final_response['Case_History'] = cleaned_records
    return final_response