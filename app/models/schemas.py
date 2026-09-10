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
    negocio: Optional[str] = None
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


class ResumenEjecutivo(BaseModel):
    """
    Resumen ejecutivo del embudo de ventas.
    """
    totales_embudo: Dict[str, int] = {}
    metrica_financiera: Dict[str, float] = {}
    total_registros_seguimiento: int = 0


class DetalleProspeccion(BaseModel):
    """
    Detalle de la prospección (prospectos/leads por estado).
    """
    convertidos: int = 0
    no_convertidos: int = 0
    stand_by: int = 0
    nuevos: int = 0


class DetalleOportunidades(BaseModel):
    """
    Detalle de oportunidades por origen y etapa.
    """
    origen: Dict[str, int] = {}
    etapas: Dict[str, int] = {}


class DetalleFoliosTramite(BaseModel):
    """
    Detalle de folios/pólizas por estado.
    """
    total_folios: int = 0
    emitidos: int = 0
    en_proceso: int = 0
    no_emitidos: int = 0


class DetalleRamosFolios(BaseModel):
    """
    Desglose de folios por Ramo__c y por Sub_ramos__c.
    """
    ramo: Dict[str, int] = {}
    sub_ramo: Dict[str, int] = {}


class DetalleRamos(BaseModel):
    """
    Desglose por ramo de prospectos, oportunidades y folios.
    """
    prospectos: Dict[str, int] = {}
    oportunidades: Dict[str, int] = {}
    folios: DetalleRamosFolios


class Pagination(BaseModel):
    page: int = 0
    size: int = 10
    total_pages: int = 0
    total_records: int = 0


class FiltrosAplicados(BaseModel):
    status_lead: Optional[str] = None
    stage_opp: Optional[str] = None
    ramo: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    periodo: Optional[str] = None
    con_folio: Optional[bool] = None


class DistribucionOrigenItem(BaseModel):
    origen: str
    total: int = 0
    porcentaje: float = 0.0
    emitidas: int = 0
    porcentaje_emitidas: float = 0.0


class ComposicionOrigenEmisiones(BaseModel):
    """De las pólizas emitidas del periodo, cuántas vienen de un Lead vs. de una Cuenta existente."""
    prospectos_nuevos: int = 0
    cuentas_existentes: int = 0
    pct_origen_prospectos: float = 0.0
    pct_origen_cuentas_existentes: float = 0.0


class ComposicionInmediatezEmisiones(BaseModel):
    """De las pólizas emitidas del periodo, cuántas nacieron de una oportunidad del mismo periodo vs. de arrastre."""
    mismo_periodo: int = 0
    arrastre_pasado: int = 0
    pct_mismo_periodo: float = 0.0
    pct_arrastre_pasado: float = 0.0


class MetricasBucketEmision(BaseModel):
    """
    Métricas comunes a cualquier bucket de distribucion_ramo_emisiones
    (el ramo mismo, y sus desgloses anidados por sub_ramo/empresa): monto y
    conteo de pólizas emitidas, ambos partidos por mismo_periodo/arrastre_pasado.
    `porcentaje`/`porcentaje_emitidas` son relativos al total general en las
    entradas de nivel ramo, y al monto/conteo del ramo padre en los desgloses
    anidados (sub_ramo/empresa) — reflejan la composición interna del ramo,
    no su peso contra el total general.
    """
    monto: float = 0.0
    porcentaje: float = 0.0
    emitidas: int = 0
    porcentaje_emitidas: float = 0.0
    emitidas_mismo_periodo: int = 0
    emitidas_arrastre_pasado: int = 0
    prima_mismo_periodo: float = 0.0
    prima_arrastre_pasado: float = 0.0
    prima_total: float = 0.0


class DistribucionSubRamo(MetricasBucketEmision):
    """
    Desglose granular dentro de un ramo: Sub_ramos__c del folio, excepto en
    VIDA, donde se usa Producto_polizas__c en su lugar.
    """
    sub_ramo: str


class DistribucionEmpresa(MetricasBucketEmision):
    """
    Desglose por Account.Negocio__c, solo dentro del ramo ACCIDENTES Y
    ENFERMEDADES.
    """
    empresa: str


class DistribucionRamoEmision(MetricasBucketEmision):
    ramo: str
    distribucion_sub_ramo: List[DistribucionSubRamo] = []
    distribucion_empresa: List[DistribucionEmpresa] = []


class ProduccionPeriodoCierre(BaseModel):
    """
    Producción real del periodo (arrastre + del mes): folios emitidos
    cuyo Case.ClosedDate cae en el rango, sin importar cuándo se creó la
    oportunidad que los originó.
    """
    polizas_emitidas_total: int = 0
    prima_colocada_total: float = 0.0
    dias_promedio_emision: Optional[float] = None
    total_canceladas: int = 0
    total_vigentes: int = 0
    ticket_promedio_prima: Optional[float] = None
    composicion_origen_emisiones: Optional[ComposicionOrigenEmisiones] = None
    composicion_inmediatez_emisiones: Optional[ComposicionInmediatezEmisiones] = None
    distribucion_ramo_emisiones: List[DistribucionRamoEmision] = []


class GestionCohorteCreacion(BaseModel):
    """Leads/Oportunidades cuyo propio CreatedDate cae en el rango, y su resultado."""
    leads_registrados: int = 0
    oportunidades_generadas: int = 0
    emisiones_mismo_periodo: int = 0
    oportunidades_en_proceso: int = 0
    oportunidades_no_emitidas: int = 0


class EficienciaConversion(BaseModel):
    tasa_conversion_prospecto_pct: float = 0.0
    tasa_prospecto_oportunidad_pct: float = 0.0
    tasa_cierre_oportunidad_pct: float = 0.0


class EficienciaProspeccion(BaseModel):
    """
    EJE A: Prospección (Leads Nuevos) — sobre leads_registrados.
    """
    tasa_conversion_prospecto_pct: float = 0.0
    tasa_cierre_prospeccion_pct: float = 0.0


class EficienciaComercial(BaseModel):
    """
    EJE B: Eficiencia Comercial (Oportunidades Totales) — sobre
    oportunidades_generadas. No mide oportunidades/leads: la mayoría de
    las oportunidades no nacen de un Lead.
    """
    tasa_cierre_oportunidad_pct: float = 0.0
    tasa_oportunidades_perdidas_pct: float = 0.0
    pct_origen_cuentas_existentes: float = 0.0
    pct_origen_prospectos: float = 0.0


class MetricaFinancieraCohorte(BaseModel):
    monto_total_cotizado: float = 0.0


class Meta(BaseModel):
    numero_asesor: str
    nombre_asesor: Optional[str] = None
    fecha_minima: Optional[str] = None
    resumen_ejecutivo: ResumenEjecutivo
    detalle_prospeccion: DetalleProspeccion
    detalle_oportunidades: DetalleOportunidades
    detalle_folios_tramite: DetalleFoliosTramite
    detalle_ramos: DetalleRamos
    produccion_periodo_cierre: Optional[ProduccionPeriodoCierre] = None
    gestion_cohorte_creacion: GestionCohorteCreacion
    eficiencia_prospeccion: EficienciaProspeccion
    eficiencia_comercial: EficienciaComercial
    metrica_financiera_cohorte: MetricaFinancieraCohorte
    distribucion_origen: List[DistribucionOrigenItem] = []
    pagination: Pagination
    filtros_aplicados: FiltrosAplicados


class SeguimientoAsesorResponse(BaseModel):
    status: str = "success"
    meta: Meta
    items: List[ItemSeguimiento]


# ═══════════════════════════════════════════════════════════════════
# Módulo de Ranking Global de Asesores (Agente Lucía)
# ═══════════════════════════════════════════════════════════════════

class VendedorInfo(BaseModel):
    numero_asesor: str
    nombre_asesor: Optional[str] = None
    zona: Optional[str] = None
    puesto: Optional[str] = None


class MetricasOperativasRanking(BaseModel):
    leads_registrados: int = 0
    cotizaciones_generadas: int = 0
    oportunidades_generadas: int = 0
    polizas_emitidas: int = 0
    prima_colocada_total: float = 0.0
    dias_promedio_emision: Optional[float] = None
    tasa_conversion_prospecto_pct: float = 0.0


class DesgloseRamoMonto(BaseModel):
    ramo: str
    monto: float = 0.0


class MetricaFinancieraRanking(BaseModel):
    monto_total_cotizado: float = 0.0
    monto_total_emitido: float = 0.0


class ItemRanking(BaseModel):
    """
    Leaderboard plano: solo lo necesario para ordenar/mostrar la tabla de
    ranking. El detalle analítico (desglose por ramo, origen, producción
    vs. cohorte) se consulta por separado vía /api/v1/seguimiento/asesor.
    """
    posicion_ranking: int
    vendedor: VendedorInfo
    metricas_operativas: MetricasOperativasRanking


class TotalesOperativosGlobal(BaseModel):
    total_asesores_evaluados: int = 0
    leads_registrados: int = 0
    cotizaciones_generadas: int = 0
    polizas_emitidas: int = 0
    prima_colocada_total: float = 0.0


class DistribucionPuestoItem(BaseModel):
    puesto: str
    total: int = 0
    porcentaje: float = 0.0
    emitidas: int = 0
    porcentaje_emitidas: float = 0.0
    emitidas_mismo_periodo: int = 0
    emitidas_arrastre_pasado: int = 0


class EficienciaGlobal(BaseModel):
    tasa_conversion_global_pct: float = 0.0
    dias_promedio_emision_global: Optional[float] = None
    distribucion_origen: List[DistribucionOrigenItem] = []
    distribucion_puesto: List[DistribucionPuestoItem] = []


class PrimaRamoGlobal(BaseModel):
    ramo: str
    monto_emitido: float = 0.0
    porcentaje: float = 0.0


class ResumenGeneralEmpresa(BaseModel):
    """
    Homologado con Meta (endpoint por-asesor): producción del periodo,
    gestión de cohorte y eficiencia separada en dos ejes. La distribución
    de prima por ramo vive en produccion_periodo_cierre.distribucion_ramo_emisiones
    (ya no hay un prima_por_ramo_global separado — era el mismo dato).
    """
    totales_operativos: TotalesOperativosGlobal
    eficiencia_global: EficienciaGlobal
    produccion_periodo_cierre: ProduccionPeriodoCierre
    gestion_cohorte_creacion: GestionCohorteCreacion
    eficiencia_prospeccion: EficienciaProspeccion
    eficiencia_comercial: EficienciaComercial
    metrica_financiera: MetricaFinancieraRanking


class PaginationGlobal(BaseModel):
    page: int = 0
    size: int = 20
    total_pages: int = 0
    total_records: int = 0


class FiltrosAplicadosGlobal(BaseModel):
    sort_by: str
    order: str
    periodo: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    ramo: Optional[List[str]] = None
    puesto: Optional[List[str]] = None


class MetaGlobal(BaseModel):
    fecha_generacion: str
    resumen_general_empresa: ResumenGeneralEmpresa
    pagination: PaginationGlobal
    filtros_aplicados: FiltrosAplicadosGlobal


class SeguimientoGlobalResponse(BaseModel):
    status: str = "success"
    meta: MetaGlobal
    items: List[ItemRanking]

