from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import RegistroCampaignDinamicoRequest, RegistroCampaignDinamicoResponse
from app.dependencias.sf_service import get_salesforce_data
from app.services.registrar_campaign_dinamico import registrar_en_campaign_dinamico
from app.dependencias.security import verifiy_auth

router = APIRouter()


@router.post("/campaign/registrar-dinamico", response_model=RegistroCampaignDinamicoResponse, status_code=200, tags=["Registro Campaña"])
def registrar_en_campaign_dinamico_endpoint(
    request: RegistroCampaignDinamicoRequest,
    sf=Depends(get_salesforce_data),
    auth_user: str = Depends(verifiy_auth)
):
    print(f"Peticion recibida para registrar en campaña (dinámico): {auth_user}")

    try:
        account_id, contact_id, lead_id, campaign_member_id, negocio = registrar_en_campaign_dinamico(request, sf)

        print(f"Registro en campaña (dinámico) exitoso: campaign_member={campaign_member_id}, lead={lead_id}")
        return RegistroCampaignDinamicoResponse(
            account_id=account_id,
            contact_id=contact_id,
            lead_id=lead_id,
            campaign_member_id=campaign_member_id,
            negocio=negocio,
        )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error al registrar en campaña (dinámico): {e}")
        raise HTTPException(status_code=500, detail=f"Error del servidor: {str(e)}")
