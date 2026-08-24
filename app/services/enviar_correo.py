"""
Servicio de envío de notificaciones por correo electrónico vía SMTP.

Arquitectura por capas (SRP):
- consultar_email_sf: obtiene emails desde Salesforce
- construir_template: carga y renderiza templates HTML desde archivos
- enviar_correo_smtp: envía el correo (no sabe nada de SF)
- notificar_asignacion: orquesta la notificación de asignación de lead
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from string import Template
from typing import Optional

from simple_salesforce import Salesforce

from app.config import settings

logger = logging.getLogger(__name__)

# ─── Rutas base ──────────────────────────────────────────────────
TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates"
)


# ═══════════════════════════════════════════════════════════════════
# CAPA 1: Consultas a Salesforce
# ═══════════════════════════════════════════════════════════════════

def consultar_email_sf(sf: Salesforce, user_id: str) -> str:
    """
    Obtiene el email de un usuario de Salesforce por su ID.
    Retorna string vacío si no encuentra o hay error.
    """
    if not user_id:
        return ""
    try:
        query = f"SELECT Id, Email, Name FROM User WHERE Id = '{user_id}'"
        result = sf.query(query)
        records = result.get("records", [])
        if records:
            email = records[0].get("Email", "")
            if email:
                return email
        logger.warning(f"No se encontró email para User ID: {user_id}")
        return ""
    except Exception as e:
        logger.error(f"Error al consultar email de User {user_id}: {e}")
        return ""


# ═══════════════════════════════════════════════════════════════════
# CAPA 2: Carga y renderizado de templates HTML
# ═══════════════════════════════════════════════════════════════════

def _cargar_template(nombre_archivo: str) -> str:
    """
    Carga un archivo HTML de la carpeta app/templates/.
    Retorna el contenido como string o lanza FileNotFoundError.
    """
    ruta = os.path.join(TEMPLATES_DIR, nombre_archivo)
    if not os.path.exists(ruta):
        raise FileNotFoundError(
            f"Template no encontrado: {ruta}. "
            f"Verifica que el archivo exista en app/templates/"
        )
    with open(ruta, "r", encoding="utf-8") as f:
        return f.read()


def construir_template_asignacion(
    nombre_asesor: str,
    nombre_prospecto: str,
    last_name: str,
    telefono: str,
    ramo: str,
    lead_source: str,
    url_prospecto: str = "",
    detalle_producto: str = ""
) -> tuple:
    """
    Carga el template email_asignacion.html y sustituye los placeholders.
    
    El asunto del correo será exactamente el nombre completo del prospecto
    (FirstName + LastName) sin modificaciones ni prefijos.
    En el cuerpo del correo, el campo "Nombre" muestra solo el LastName.
    
    Retorna (asunto: str, cuerpo_html: str).
    
    Para agregar un nuevo template (ej. notificación de vencimiento):
    1. Crear app/templates/email_vencimiento.html
    2. Crear función construir_template_vencimiento() aquí
    3. La lógica SMTP y de consulta SF se reutiliza sin cambios.
    """
    html_raw = _cargar_template("email_asignacion.html")
    template = Template(html_raw)

    asunto = nombre_prospecto.strip()

    cuerpo_html = template.safe_substitute(
        nombre_asesor=nombre_asesor,
        nombre_prospecto=last_name.strip(),
        telefono=telefono,
        ramo=ramo,
        lead_source=lead_source,
        url_prospecto=url_prospecto,
        detalle_producto=detalle_producto,
    )

    return asunto, cuerpo_html


# ═══════════════════════════════════════════════════════════════════
# CAPA 3: Envío SMTP (no sabe nada de Salesforce ni de leads)
# ═══════════════════════════════════════════════════════════════════

def enviar_correo_smtp(
    destinatario: str,
    asunto: str,
    cuerpo_html: str,
    cc: Optional[str] = None
) -> bool:
    """
    Envía un correo HTML vía SMTP con configuración de app.config.settings.
    
    Intenta primero por SSL (puerto 465). Si el puerto configurado no es 465,
    intenta con STARTTLS (puerto 587).
    
    Args:
        destinatario: Correo del destinatario principal (To).
        asunto: Asunto del correo.
        cuerpo_html: Cuerpo del correo en HTML.
        cc: Correo para copia al carbón (Cc), opcional.
    
    Returns:
        True si se envió correctamente, False en caso contrario.
    """
    if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
        logger.warning("SMTP no configurado (username/password vacíos). "
                       "No se puede enviar correo.")
        return False

    if not destinatario:
        logger.warning("Destinatario vacío. No se envía correo.")
        return False

    try:
        mensaje = MIMEMultipart("alternative")
        mensaje["From"] = settings.SMTP_USERNAME
        mensaje["To"] = destinatario
        mensaje["Subject"] = asunto

        if cc:
            mensaje["Cc"] = cc

        parte_html = MIMEText(cuerpo_html, "html", "utf-8")
        mensaje.attach(parte_html)

        todos_destinatarios = [destinatario]
        if cc:
            todos_destinatarios.append(cc)

        print(
            f"DEBUG SMTP: host={settings.SMTP_HOST}, "
            f"puerto={settings.SMTP_PORT}, "
            f"username={settings.SMTP_USERNAME!r}, "
            f"password_len={len(settings.SMTP_PASSWORD)}, "
            f"password_inicio={settings.SMTP_PASSWORD[:4]!r}"
        )

        # Estrategia: intentar SSL directo (465) primero, fallback a STARTTLS (587)
        intentos = [
            ("SSL directo", 465, lambda: smtplib.SMTP_SSL(settings.SMTP_HOST, 465)),
            ("STARTTLS", 587, lambda: smtplib.SMTP(settings.SMTP_HOST, 587)),
        ]

        # Si el puerto configurado es distinto de 465, ponerlo como primer intento
        puerto_config = settings.SMTP_PORT
        if puerto_config not in (465, 587):
            if puerto_config == 587:
                pass  # ya es el segundo intento
            else:
                intentos.insert(0, (f"Puerto configurado {puerto_config}", puerto_config, None))

        enviado = False
        ultimo_error = None

        for nombre_intento, puerto_intento, constructor in intentos:
            try:
                if constructor:
                    with constructor() as servidor:
                        if puerto_intento != 465:
                            servidor.starttls()
                        servidor.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                        servidor.sendmail(
                            settings.SMTP_USERNAME,
                            todos_destinatarios,
                            mensaje.as_string(),
                        )
                else:
                    # Puerto personalizado no estándar
                    with smtplib.SMTP(settings.SMTP_HOST, puerto_intento) as servidor:
                        servidor.ehlo()
                        servidor.starttls()
                        servidor.ehlo()
                        servidor.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                        servidor.sendmail(
                            settings.SMTP_USERNAME,
                            todos_destinatarios,
                            mensaje.as_string(),
                        )

                logger.info(
                    f"Correo enviado a {destinatario}"
                    + (f" con CC a {cc}" if cc else "")
                    + f" (vía {nombre_intento}, puerto {puerto_intento})"
                )
                enviado = True
                break

            except (smtplib.SMTPException, ConnectionError, OSError) as e:
                ultimo_error = e
                logger.warning(
                    f"Intento {nombre_intento} (puerto {puerto_intento}) falló: {e}"
                )
                continue

        if enviado:
            return True
        else:
            logger.error(
                f"Todos los intentos SMTP fallaron. Último error: {ultimo_error}"
            )
            return False

    except Exception as e:
        logger.error(f"Error inesperado al enviar correo: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════
# CAPA 4: Orquestador para notificación de asignación
# ═══════════════════════════════════════════════════════════════════

def construir_template_folio_asignado(
    nombre_asesor: str,
    tipo_movimiento: str,
    numero_folio: str,
    url_folio: str,
) -> str:
    """
    Carga el template email_folio_asignado.html y sustituye los placeholders.
    
    Retorna el cuerpo HTML del correo para el caso en que hay asesor asignado.

    Para personalizar el correo de asignación de folios, editar
    app/templates/email_folio_asignado.html.
    """
    html_raw = _cargar_template("email_folio_asignado.html")
    template = Template(html_raw)

    cuerpo_html = template.safe_substitute(
        nombre_asesor=nombre_asesor,
        tipo_movimiento=tipo_movimiento,
        numero_folio=numero_folio,
        url_folio=url_folio,
    )

    return cuerpo_html


def construir_template_folio_sin_asesor(
    tipo_movimiento: str,
    numero_folio: str,
    url_folio: str,
) -> str:
    """
    Carga el template email_folio_sin_asesor.html y sustituye los placeholders.
    
    Retorna el cuerpo HTML del correo para el caso en que no hay asesor
    disponible y el folio requiere asignación manual.

    Para personalizar el correo de folio sin asesor, editar
    app/templates/email_folio_sin_asesor.html.
    """
    html_raw = _cargar_template("email_folio_sin_asesor.html")
    template = Template(html_raw)

    cuerpo_html = template.safe_substitute(
        tipo_movimiento=tipo_movimiento,
        numero_folio=numero_folio,
        url_folio=url_folio,
    )

    return cuerpo_html


def notificar_asignacion_folio(
    sf: Salesforce,
    owner_id: str,
    nombre_asesor: str,
    tipo_movimiento: str,
    numero_folio: str,
    url_folio: str,
    lider_id: str,
    es_fallback: bool = False,
) -> bool:
    """
    Orquesta el envío de correo cuando se asigna un folio (Case) a un asesor.

    Flujo:
    1. Consulta email del asesor asignado (owner_id).
    2. Consulta email del líder (lider_id).
    3. Construye template HTML con los datos del folio y enlace al Case.
    4. Envía correo al asesor con CC al líder.

    Escenario de fallback:
    - Si es_fallback es True (no hay asesor disponible, el folio fue al respaldo),
      envía el correo únicamente al líder con un mensaje de alerta.

    Args:
        sf: Instancia autenticada de Salesforce.
        owner_id: ID del asesor asignado (User).
        nombre_asesor: Nombre del asesor asignado.
        tipo_movimiento: Tipo de movimiento del folio (ej. 'Duplicado').
        numero_folio: Número de folio (CaseNumber).
        url_folio: Enlace al Case en Salesforce.
        lider_id: ID del líder/respaldo (User) que recibe copia o el fallback.
        es_fallback: True si el folio fue asignado al respaldo (sin asesor
            disponible). El llamador lo determina comparando contra la
            constante de respaldo.

    Returns:
        True si se envió al menos un correo, False si no se pudo enviar nada.
    """
    email_asesor = consultar_email_sf(sf, owner_id) if not es_fallback else ""
    email_lider = consultar_email_sf(sf, lider_id)

    asunto = f"Nuevo folio asignado - {tipo_movimiento}"

    if email_asesor and email_lider:
        # Escenario normal: asesor asignado + copia al líder
        cuerpo = construir_template_folio_asignado(
            nombre_asesor=nombre_asesor,
            tipo_movimiento=tipo_movimiento,
            numero_folio=numero_folio,
            url_folio=url_folio,
        )
        return enviar_correo_smtp(
            destinatario=email_asesor,
            asunto=asunto,
            cuerpo_html=cuerpo,
            cc=email_lider,
        )

    elif email_lider:
        # Fallback: no hay asesor disponible, solo al líder con alerta
        asunto_fallback = f"[SIN ASIGNAR] {asunto}"
        cuerpo_fallback = construir_template_folio_sin_asesor(
            tipo_movimiento=tipo_movimiento,
            numero_folio=numero_folio,
            url_folio=url_folio,
        )

        return enviar_correo_smtp(
            destinatario=email_lider,
            asunto=asunto_fallback,
            cuerpo_html=cuerpo_fallback,
        )

    else:
        logger.error(
            "No se pudo enviar correo: no hay email del asesor ni del líder "
            f"(owner_id={owner_id}, lider_id={lider_id})."
        )
        return False


def notificar_asignacion(
    sf: Salesforce,
    owner_id: str,
    nombre_asesor: str,
    lead_data: dict,
    ramo: str,
    id_lead: str = "",
    lider_id: str = "005ct00000FwEpxAAF", #005WR000008PRlCYAW, 005WR00000CO8C1YAL <-Asesor, 005ct00000FwEpxAAF <- sb
) -> bool:
    """
    Orquesta el envío de correo cuando se asigna un lead a un asesor.
    
    Flujo:
    1. Consulta email del asesor asignado (owner_id).
    2. Consulta email del líder de telemarketing (lider_id).
    3. Construye template HTML con los datos del lead y enlace al prospecto.
    4. Envía correo al asesor con CC al líder.
    
    Escenario de fallback:
    - Si owner_id está vacío, si el nombre del asesor contiene 
      "Pronto se le asignara", o si no se encuentra email del asesor,
      envía el correo únicamente al líder con un mensaje de alerta.
    - Si no se encuentra email ni del asesor ni del líder, retorna False.
    
    Returns:
        True si se envió al menos un correo, False si no se pudo enviar nada.
    """
    # Detectar fallback: cuando no hay asesor disponible (carrusel vacío)
    es_fallback = (
        not owner_id
        or "pronto se le asignara" in nombre_asesor.lower()
    )

    email_asesor = consultar_email_sf(sf, owner_id) if not es_fallback else ""
    #email_lider = consultar_email_sf(sf, lider_id)
    email_lider = 'isanchez@mcbrokers.com.mx'
    # Preparar datos para el template
    nombre_prospecto = (
        lead_data.get("FirstName", "")
        + " "
        + lead_data.get("LastName", "")
    ).strip()
    last_name = lead_data.get("LastName", "").strip()
    telefono = lead_data.get("MobilePhone", "Sin teléfono")
    lead_source = lead_data.get("LeadSource", "")

    # Construir URL del prospecto en Salesforce
    url_prospecto = (
        f"https://customer-customer-9846.lightning.force.com/lightning/r/Lead/{id_lead}/view"
        if id_lead
        else ""
    )

    # Detalle del producto (vacío por ahora, se puede enriquecer después)
    detalle_producto = ""

    asunto, cuerpo = construir_template_asignacion(
        nombre_asesor=nombre_asesor,
        nombre_prospecto=nombre_prospecto,
        last_name=last_name,
        telefono=telefono,
        ramo=ramo,
        lead_source=lead_source,
        url_prospecto=url_prospecto,
        detalle_producto=detalle_producto,
    )

    if email_asesor and email_lider:
        # Escenario normal: asesor asignado + copia al líder
        return enviar_correo_smtp(
            destinatario=email_asesor,
            asunto=asunto,
            cuerpo_html=cuerpo,
            cc=email_lider,
        )

    elif email_lider:
        # Fallback: no hay asesor disponible, solo al líder con alerta
        asunto_fallback = f"[SIN ASIGNAR] {asunto}"
        cuerpo_fallback_html = _cargar_template("email_asignacion.html")
        template_fallback = Template(cuerpo_fallback_html)
        cuerpo_fallback = template_fallback.safe_substitute(
            nombre_asesor="Pendiente de asignación",
            nombre_prospecto=nombre_prospecto,
            telefono=telefono,
            ramo=ramo,
            lead_source=lead_source,
            url_prospecto=url_prospecto,
            detalle_producto=(
                "<tr><td colspan='2' style='padding:10px; color:#EE2059; "
                "font-weight:bold;'>No se encontró un asesor disponible "
                "en el carrusel de Telemarketing. "
                "Requiere asignación manual.</td></tr>"
            ),
        )

        return enviar_correo_smtp(
            destinatario=email_lider,
            asunto=asunto_fallback,
            cuerpo_html=cuerpo_fallback,
        )

    else:
        logger.error(
            "No se pudo enviar correo: no hay email del asesor ni del líder "
            f"(owner_id={owner_id}, lider_id={lider_id})."
        )
        return False