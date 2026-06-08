from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import FolioRequest, FolioResponse
from app.dependencias.sf_service import get_salesforce_data
from app.services.buscarFolio import buscar_folio 
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