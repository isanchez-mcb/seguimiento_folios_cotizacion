from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional, Union
from datetime import date, datetime
from typing import Dict, Any

app = FastAPI()

class FolioRequest(BaseModel):
    CaseNumber : str

class FolioResponse(BaseModel):
    Case_List: Dict[str, Any]

class AutoData(BaseModel):
    cp: str
    modelo: str
    marca: str
    version: str
    fecha_nacimiento_conductor: date
    genero: str

class GMMData(BaseModel):
    negocio: str
    genero: str
    edad: int

class HogarData(BaseModel):
    tipo_de_vivienda: str
    propietario: bool
    cp: str

class VidaTotalData(BaseModel):
    genero: str
    edad: int
    fumador: bool

class VidaMasData(BaseModel):
    fecha_nacimiento: date
    genero: str
    fumador: bool

class PlanSeguroData(BaseModel):
    genero: str
    fecha_nacimiento: date
    estado: str

class MascotaData(BaseModel):
    raza: str
    edad_mascota: int
    tipo_mascota: str
    genero_mascota: str
    cp_contrante: str
    edad_contratante: int

class ViajesData(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    pais_region: str
    no_asegurados: int
    mayores_de_edad: bool

class CreateCotizacionRequest(BaseModel):
    nombre: str
    expediente_colaborador: Optional[str] = None
    origen_prospecto: Optional[str] = None
    telefono: str
    auto_data: Optional[AutoData] = None
    gmm_data: Optional[GMMData] = None
    hogar_data: Optional[HogarData] = None
    vida_total_data: Optional[VidaTotalData] = None
    vida_mas_data: Optional[VidaMasData] = None
    plan_seguro_data: Optional[PlanSeguroData] = None
    mascota_data: Optional[MascotaData] = None
    viajes_data: Optional[ViajesData] = None

class RegistroCampaignRequest(BaseModel):
    expediente: Optional[str] = None
    telefono: Optional[str] = None
    correo: Optional[str] = None
    negocio: Optional[str] = None
    primer_nombre: Optional[str] = None
    segundo_nombre: Optional[str] = None
    apellidos: Optional[str] = None
    ocupacion: Optional[str] = None
    numero_asesor: Optional[str] = None

class RegistroCampaignResponse(BaseModel):
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    lead_id: Optional[str] = None
    campaign_member_id: str
    negocio: str

class CreateCotizacionResponse(BaseModel):
    asesor: str

class DatosContactoRequest(BaseModel):
    expediente_colaborador: str

class DatosContactoResponse(BaseModel):
    expediente_buscado: str
    nombre_cuenta: Optional[str] = None
    correo: Optional[str] = None
    telefono: Optional[str] = None
    mensaje: str

class CrearFolioRequest(BaseModel):
    expediente_colaborador: str
    numero_poliza: str
    ramo: Optional[str] = None
    correo: Optional[str] = None
    telefono: Optional[str] = None
    origen_folio: Optional[str] = None

class CrearFolioResponse(BaseModel):
    case_id: str
    case_number: Optional[str] = None
    case_link: Optional[str] = None
    mensaje: str


# ═══════════════════════════════════════════════════════════════════
# Módulo de Trazabilidad End-to-End de Asesores (Agente Lucía)
# ═══════════════════════════════════════════════════════════════════

class ProspectoInfo(BaseModel):
    lead_id: str
    name: Optional[str] = None
    status: Optional[str] = None
    is_converted: bool = False
    negocio: Optional[str] = None
    filial: Optional[str] = None
    no_expediente_no_colaborador: Optional[str] = None
    rfc: Optional[str] = None
    estado_republica: Optional[str] = None
    genero: Optional[str] = None
    edad: Optional[int] = None
    fecha_nacimiento: Optional[str] = None
    ramos_interes: Optional[str] = None
    email: Optional[str] = None
    mobile_phone: Optional[str] = None
    lead_source: Optional[str] = None
    nivel_interes: Optional[str] = None
    presupuesto_disponible: Optional[float] = None
    campana_del: Optional[str] = None
    razon_perdida: Optional[str] = None
    impedimentos: Optional[str] = None
    comentarios_lead_perdido: Optional[str] = None
    owner_name: Optional[str] = None
    created_by_name: Optional[str] = None
    last_modified_by_name: Optional[str] = None
    created_date: Optional[str] = None
    last_modified_date: Optional[str] = None


class CuentaInfo(BaseModel):
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    created_by_name: Optional[str] = None
    created_date: Optional[str] = None


class DuracionEtapas(BaseModel):
    nueva_dias: Optional[int] = None
    cotizacion_dias: Optional[int] = None
    proceso_cierre_dias: Optional[int] = None


class OportunidadInfo(BaseModel):
    opportunity_id: Optional[str] = None
    name: Optional[str] = None
    stage_name: Optional[str] = None
    sub_estatus: Optional[str] = None
    record_type_name: Optional[str] = None
    campaign_name: Optional[str] = None
    presupuesto_disponible: Optional[float] = None
    ramos_interes: Optional[str] = None
    nivel_interes: Optional[str] = None
    owner_name: Optional[str] = None
    origen_oportunidad: Optional[str] = None
    close_date: Optional[str] = None
    probability: Optional[int] = None
    fecha_seguimiento: Optional[str] = None
    fecha_cita_agendada: Optional[str] = None
    ciclo_de_vida: Optional[str] = None
    duracion_etapas: Optional[DuracionEtapas] = None
    responsable_decision: Optional[str] = None
    tiempo_estimado: Optional[str] = None
    impedimentos: Optional[str] = None
    ramos: Optional[str] = None
    sub_ramos: Optional[str] = None
    prima_total_cotizada: Optional[float] = None
    prima_total_emitida: Optional[float] = None
    cotizacion: Optional[Union[str, bool]] = None
    razon_perdida: Optional[str] = None
    otra_razon_perdida: Optional[str] = None
    created_date: Optional[str] = None
    last_modified_date: Optional[str] = None
    last_modified_by_name: Optional[str] = None


class FolioEmisionInfo(BaseModel):
    case_id: Optional[str] = None
    case_number: Optional[str] = None
    nomenclatura: Optional[str] = None
    status: Optional[str] = None
    subject: Optional[str] = None
    tipo_movimiento: Optional[str] = None
    poliza_name: Optional[str] = None
    poliza_prima_total: Optional[float] = None
    poliza_status: Optional[str] = None
    poliza_emitida: Optional[bool] = None
    poliza_no_emitida: Optional[bool] = None
    razon_no_emision: Optional[str] = None
    ramo: Optional[str] = None
    sub_ramos: Optional[str] = None
    aseguradora: Optional[str] = None
    producto_polizas: Optional[str] = None
    created_date: Optional[str] = None
    closed_date: Optional[str] = None
    asesor_externo_name: Optional[str] = None
    created_by_name: Optional[str] = None
    last_modified_by_name: Optional[str] = None
    owner_name: Optional[str] = None


class ItemSeguimiento(BaseModel):
    seguimiento_id: str
    origen_registro: Optional[str] = None
    prospecto: Optional[ProspectoInfo] = None
    cuenta: Optional[CuentaInfo] = None
    oportunidad: Optional[OportunidadInfo] = None
    folios_emision: List[FolioEmisionInfo] = []


class KPIsTotales(BaseModel):
    total_prospectos: int = 0
    total_prospectos_nuevos: int = 0
    total_prospectos_stand_by: int = 0
    total_prospectos_convertidos: int = 0
    total_prospectos_no_convertidos: int = 0
    total_oportunidades_generadas: int = 0
    oportunidades_nueva: int = 0
    oportunidades_cotizacion: int = 0
    oportunidades_proceso_cierre: int = 0
    oportunidades_cerrado_ganado: int = 0
    oportunidades_poliza_emitida: int = 0
    oportunidades_poliza_no_emitida: int = 0
    oportunidades_concluido: int = 0
    oportunidades_otros: int = 0
    total_folios: int = 0
    total_folios_emitidos: int = 0
    total_folios_no_emitidos: int = 0
    total_folios_en_proceso: int = 0
    monto_total_cotizado: float = 0.0
    monto_total_emitido: float = 0.0
    total_registros_seguimiento: int = 0
    oportunidades_origen_prospecto: int = 0
    oportunidades_origen_cuenta_existente: int = 0


class Pagination(BaseModel):
    page: int = 0
    size: int = 10
    total_pages: int = 0
    total_records: int = 0


class FiltrosAplicados(BaseModel):
    status_lead: Optional[str] = None
    stage_opp: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    periodo: Optional[str] = None
    con_folio: Optional[bool] = None


class Meta(BaseModel):
    numero_asesor: str
    nombre_asesor: Optional[str] = None
    fecha_minima: Optional[str] = None
    kpis_totales: KPIsTotales
    pagination: Pagination
    filtros_aplicados: FiltrosAplicados


class SeguimientoAsesorResponse(BaseModel):
    status: str = "success"
    meta: Meta
    items: List[ItemSeguimiento]

