from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import FolioRequest, FolioResponse, FoliosPorExpedienteResponse
from app.dependencias.sf_service import get_salesforce_data
from app.services.buscarFolio import buscar_folio
from app.services.buscarCuentaFolios import buscar_cuenta_por_expediente_empresa, obtener_folios_de_cuenta
import pandas as pd
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app.dependencias.security import verifiy_auth

router = APIRouter()

security = HTTPBasic()

@router.get("/folios/buscar", response_model=FolioResponse, status_code=200, tags=["Folios"])
def buscar_folio_endpoint(case_number: str, sf=Depends(get_salesforce_data), auth_user: str = Depends(verifiy_auth)):

    print(f"Peticion recibida para buscar folio: {auth_user}")
    case_list = buscar_folio(case_number, sf)

    if case_list is None:
        raise HTTPException(
            status_code=404,
            detail=f"Información no disponible"
        )
    print("Folio encontrado")
    return {"CaseNumber": case_number, "Case_List": case_list}

@router.get("/folios/buscar-por-expediente", response_model=FoliosPorExpedienteResponse, status_code=200, tags=["Folios"])
def buscar_folios_por_expediente_endpoint(expediente: str, empresa: str, sf=Depends(get_salesforce_data), auth_user: str = Depends(verifiy_auth)):

    print(f"Peticion recibida para buscar folios por expediente: {auth_user}")
    account = buscar_cuenta_por_expediente_empresa(sf, expediente, empresa)

    if account is None:
        raise HTTPException(
            status_code=404,
            detail="No se encontró una cuenta asociada a ese expediente"
        )

    folios = obtener_folios_de_cuenta(sf, account["Id"])
    print(f"Folios encontrados: {len(folios)}")

    return FoliosPorExpedienteResponse(
        expediente_buscado=expediente,
        empresa=empresa,
        account_id=account["Id"],
        nombre_cuenta=account.get("Name"),
        folios=folios
    )