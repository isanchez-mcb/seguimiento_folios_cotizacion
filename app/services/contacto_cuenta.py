from typing import List, Optional

from simple_salesforce import Salesforce

from app.dependencias.sf_service import query_con_reintento
from app.services.registrar_campaign import (
    _generar_variaciones_con_ceros,
    _generar_variaciones_expediente,
)


# ─── Constantes ───────────────────────────────────────────────────

MAX_DIGITOS_EXPEDIENTE = 10


# ─── Búsqueda de cuenta ───────────────────────────────────────────

def _buscar_cuenta_por_expediente_exacto(sf: Salesforce, expediente: str) -> Optional[dict]:
    """
    Busca una cuenta por el expediente exacto.
    Retorna la cuenta o None.
    """
    query = (
        "SELECT Id, Name, PersonMobilePhone, PersonEmail, "
        "No_expediente_No_colaborador__c "
        "FROM Account "
        f"WHERE No_expediente_No_colaborador__c = '{expediente}'"
    )
    result = query_con_reintento(sf, query)
    if result['totalSize'] > 0:
        return result['records'][0]
    return None


def buscar_cuenta_contacto(sf: Salesforce, expediente: str) -> Optional[dict]:
    """
    Busca una cuenta por expediente con búsqueda en cascada:
    1. Expediente exacto (siempre priorizado)
    2. Variaciones quitando ceros a la izquierda
    3. Variaciones agregando ceros a la izquierda (máx. 10 caracteres)

    Retorna el registro de Account si encuentra, o None si no.
    """
    expediente_limpio = expediente.strip()

    # ── 1. Expediente exacto ─────────────────────────────────────
    print(f"Buscando cuenta con expediente exacto: {expediente_limpio}")
    account = _buscar_cuenta_por_expediente_exacto(sf, expediente_limpio)
    if account is not None:
        return account

    # ── 2. Variaciones quitando ceros ────────────────────────────
    variaciones = _generar_variaciones_expediente(expediente_limpio)
    for var in variaciones:
        print(f"Buscando cuenta con variación (quitando ceros): {var}")
        account = _buscar_cuenta_por_expediente_exacto(sf, var)
        if account is not None:
            print(f"Cuenta encontrada con variación '{var}' (quitando ceros)")
            return account

    # ── 3. Variaciones agregando ceros (máx. 10) ─────────────────
    variaciones_ceros = _generar_variaciones_con_ceros(expediente_limpio, max_digitos=MAX_DIGITOS_EXPEDIENTE)
    for var in variaciones_ceros:
        print(f"Buscando cuenta con variación (agregando ceros): {var}")
        account = _buscar_cuenta_por_expediente_exacto(sf, var)
        if account is not None:
            print(f"Cuenta encontrada con variación '{var}' (agregando ceros)")
            return account

    return None