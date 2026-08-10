from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import RegistroCampaignRequest, RegistroCampaignResponse
from app.dependencias.sf_service import get_salesforce_data
from app.services.registrar_campaign import registrar_en_campaign
from app.dependencias.security import verifiy_auth

router = APIRouter()


@router.post("/campaign/registrar", response_model=RegistroCampaignResponse, status_code=200, tags=["Registro Campaña"])
def registrar_en_campaign_endpoint(
    request: RegistroCampaignRequest,
    sf=Depends(get_salesforce_data),
    auth_user: str = Depends(verifiy_auth)
):
    print(f"Peticion recibida para registrar en campaña: {auth_user}")

    try:
        account_id, contact_id, lead_id, campaign_member_id, negocio = registrar_en_campaign(request, sf)

        print(f"Registro en campaña exitoso: campaign_member={campaign_member_id}, lead={lead_id}")
        return RegistroCampaignResponse(
            account_id=account_id,
            contact_id=contact_id,
            lead_id=lead_id,
            campaign_member_id=campaign_member_id,
            negocio=negocio,
        )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error al registrar en campaña: {e}")
        raise HTTPException(status_code=500, detail=f"Error del servidor: {str(e)}")
