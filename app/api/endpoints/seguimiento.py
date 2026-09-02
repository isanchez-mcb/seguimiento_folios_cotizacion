"""
Endpoint de Trazabilidad End-to-End de Asesores (Agente Lucía).

Solo consulta (GET). No crea ni modifica registros en Salesforce.
"""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencias.security import verifiy_auth
from app.dependencias.sf_service import get_salesforce_data
from app.models.schemas import SeguimientoAsesorResponse, SeguimientoGlobalResponse
from app.services.trazabilidad_asesor import (
    STATUS_LEAD_VALIDOS,
    STAGE_OPP_VALIDOS,
    RAMOS_VALIDOS,
    obtener_trazabilidad_asesor,
)
from app.services.ranking_asesores import (
    ORDER_VALIDOS,
    PERIODO_VALIDOS,
    SORT_BY_VALIDOS,
    obtener_ranking_global,
)

router = APIRouter()


@router.get(
    "/api/v1/seguimiento/asesor",
    response_model=SeguimientoAsesorResponse,
    status_code=200,
    tags=["Seguimiento Asesor"],
)
def obtener_seguimiento_asesor(
    numero_asesor: str = Query(..., description="Número del Asesor Externo (obligatorio)"),
    status_lead: Optional[str] = Query(
        None,
        description="Filtra por Status exacto del Lead. Válidos: Nuevo, Stand by, Convertido, No convertido",
    ),
    stage_opp: Optional[str] = Query(
        None,
        description="Filtra por StageName de la Oportunidad. Válidos: Nueva, Cotización, Proceso de cierre, Cerrado ganado, Póliza emitida, Póliza no emitida, Concluido, Otros (etapas inactivas/rezagadas)",
    ),
    ramo: Optional[str] = Query(
        None,
        description="Filtra por Ramo/Ramos_de_interes (Lead, Oportunidad o Folio). Válidos: VIDA, DAÑOS, ACCIDENTES Y ENFERMEDADES",
    ),
    fecha_inicio: Optional[str] = Query(
        None,
        description="Filtra registros creados a partir de esta fecha (YYYY-MM-DD)",
    ),
    fecha_fin: Optional[str] = Query(
        None,
        description="Filtra registros creados hasta esta fecha (YYYY-MM-DD)",
    ),
    periodo: Optional[str] = Query(
        None,
        description="Filtra por periodo (YYYY-MM o YYYY-MM:YYYY-MM). Aplica si el Lead, la Oportunidad o alguna Póliza cae en el periodo",
    ),
    con_folio: Optional[bool] = Query(
        None,
        description="Si true, solo items con folios de emisión. Si false, solo items sin folios de emisión",
    ),
    page: int = Query(0, ge=0, description="Índice de página (zero-based)"),
    size: int = Query(10, ge=1, le=100, description="Cantidad de registros por página"),
    sf=Depends(get_salesforce_data),
    auth_user: str = Depends(verifiy_auth),
):
    """
    Consulta la trazabilidad end-to-end de un asesor externo.

    Retorna una matriz aplanada de seguimiento con KPIs agregados y paginación.
    """
    print(f"Peticion recibida para trazabilidad de asesor: {auth_user}")

    # ── Validar numero_asesor (TC-05) ────────────────────────────
    if not numero_asesor or not numero_asesor.strip():
        raise HTTPException(
            status_code=400,
            detail="El parámetro 'numero_asesor' es requerido.",
        )

    numero_asesor = numero_asesor.strip()

    # ── Validar status_lead ──────────────────────────────────────
    if status_lead and status_lead not in STATUS_LEAD_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Valor inválido para 'status_lead': '{status_lead}'. "
                f"Válidos: {', '.join(sorted(STATUS_LEAD_VALIDOS))}"
            ),
        )

    # ── Validar stage_opp ────────────────────────────────────────
    if stage_opp and stage_opp not in STAGE_OPP_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Valor inválido para 'stage_opp': '{stage_opp}'. "
                f"Válidos: {', '.join(sorted(STAGE_OPP_VALIDOS))}"
            ),
        )

    # ── Validar ramo ──────────────────────────────────────────────
    if ramo and ramo not in RAMOS_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Valor inválido para 'ramo': '{ramo}'. "
                f"Válidos: {', '.join(sorted(RAMOS_VALIDOS))}"
            ),
        )

    try:
        resultado = obtener_trazabilidad_asesor(
            sf=sf,
            numero_asesor=numero_asesor,
            status_lead=status_lead,
            stage_opp=stage_opp,
            ramo=ramo,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            periodo=periodo,
            con_folio=con_folio,
            page=page,
            size=size,
        )
        return resultado
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error en trazabilidad de asesor: {e}")
        raise HTTPException(status_code=500, detail=f"Error del servidor: {str(e)}")


@router.get(
    "/api/v1/seguimiento/global",
    response_model=SeguimientoGlobalResponse,
    status_code=200,
    tags=["Seguimiento Asesor"],
)
def obtener_seguimiento_global(
    sort_by: str = Query(
        "prima_colocada",
        description=(
            "Criterio de orden: prima_colocada, polizas_emitidas, tasa_conversion, "
            "dias_promedio_emision, leads_registrados, oportunidades_generadas, general"
        ),
    ),
    order: str = Query("DESC", description="Dirección del orden: DESC o ASC"),
    periodo: Optional[str] = Query(
        None,
        description="Filtro rápido: mensual (30d), trimestral (90d), anual (365d), historico_total",
    ),
    fecha_inicio: Optional[str] = Query(None, description="Rango desde (YYYY-MM-DD)"),
    fecha_fin: Optional[str] = Query(None, description="Rango hasta (YYYY-MM-DD)"),
    ramo: Optional[str] = Query(
        None,
        description="Filtra por ramo(s), separados por coma. Válidos: VIDA, DAÑOS, ACCIDENTES Y ENFERMEDADES",
    ),
    puesto: Optional[str] = Query(
        None,
        description="Filtra por puesto(s) del asesor (Asesor_externo__c.Puesto__c), separados por coma",
    ),
    page: int = Query(0, ge=0, description="Índice de página (zero-based)"),
    size: int = Query(20, ge=1, le=100, description="Cantidad de asesores por página"),
    sf=Depends(get_salesforce_data),
    auth_user: str = Depends(verifiy_auth),
):
    """
    Ranking global de asesores: KPIs consolidados de toda la fuerza de
    ventas, con ordenamiento dinámico y paginación.
    """
    print(f"Peticion recibida para ranking global de asesores: {auth_user}")

    # ── Validar sort_by ───────────────────────────────────────────
    if sort_by not in SORT_BY_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Valor inválido para 'sort_by': '{sort_by}'. "
                f"Válidos: {', '.join(sorted(SORT_BY_VALIDOS))}"
            ),
        )

    # ── Validar order ─────────────────────────────────────────────
    order = order.upper()
    if order not in ORDER_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Valor inválido para 'order': '{order}'. "
                f"Válidos: {', '.join(sorted(ORDER_VALIDOS))}"
            ),
        )

    # ── Validar periodo ───────────────────────────────────────────
    if periodo and periodo not in PERIODO_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Valor inválido para 'periodo': '{periodo}'. "
                f"Válidos: {', '.join(sorted(PERIODO_VALIDOS))}"
            ),
        )

    # ── Validar formato de fechas ─────────────────────────────────
    for nombre_campo, valor in (("fecha_inicio", fecha_inicio), ("fecha_fin", fecha_fin)):
        if valor and not re.match(r"^\d{4}-\d{2}-\d{2}$", valor):
            raise HTTPException(
                status_code=400,
                detail=f"'{nombre_campo}' debe tener formato YYYY-MM-DD",
            )

    # ── Validar ramo (uno o varios, separados por coma) ────────────
    ramos_lista = [r.strip() for r in ramo.split(",") if r.strip()] if ramo else None
    if ramos_lista:
        invalidos = [r for r in ramos_lista if r not in RAMOS_VALIDOS]
        if invalidos:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Valor inválido para 'ramo': {', '.join(invalidos)}. "
                    f"Válidos: {', '.join(sorted(RAMOS_VALIDOS))}"
                ),
            )

    # ── Puesto: uno o varios, separados por coma (sin catálogo fijo) ─
    puestos_lista = [p.strip() for p in puesto.split(",") if p.strip()] if puesto else None

    try:
        resultado = obtener_ranking_global(
            sf=sf,
            sort_by=sort_by,
            order=order,
            periodo=periodo,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            ramo=ramos_lista,
            puesto=puestos_lista,
            page=page,
            size=size,
        )
        return resultado
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error en ranking global de asesores: {e}")
        raise HTTPException(status_code=500, detail=f"Error del servidor: {str(e)}")