class tipo_folios:

    recordType_map = {
        'Emisión' : 'diccionario_emision',
        'Buzón de quejas' : 'diccionario_buzon',
        'Mantenimiento' : 'diccionario_mantenimiento',
        'Siniestros GMM' : 'diccionario_siniestros',
        'Siniestros vehículos' : 'diccionario_siniestros',
        'Siniestros vida' : 'diccionario_siniestros',
        'Cancelación' : 'diccionario_cancelacion',
    }

    referencia_clientes = {
        'Recibido' : 'Agradecemos su elección. Hemos recibido correctamente su solicitud y en breve iniciaremos la revisión de sus referencias.',
        'Validando Referencias' : 'Sus referencias están siendo validadas. Si la validación es satisfactoria, el proceso continuará automáticamente. En caso de requerir información adicional, lo contactaremos.',
        'Procesando Solicitud' : 'Estamos actualizando sus referencias en nuestros sistemas internos, muchas gracias por su espera',
        'En espera de Respuesta' : 'Agradecemos su colaboración. Estamos a la espera de la resolución final del proceso.',
        'Solicitud Finalizada' : '¡Felicidades! Su trámite se ha gestionado correctamente. Agradecemos el tiempo de espera. Próximamente, un asesor se pondrá en contacto con usted.'
    }

    diccionario_emision = {
        'Análisis' : 'Validando Referencias',
        'Asignado' : 'Recibido',
        'Procesado' : 'Procesando Solicitud',
        'Escalado a área correspondiente' : 'Validando Referencias',
        'Asignado áreas internas' : 'Procesando Solicitud',
        'Extensión de Información' : 'Validando Referencias',
        'Continuidad' : 'En espera de Respuesta',
        'Terminado' : 'Solicitud Finalizada'
    }

    diccionario_buzon = {
        'Asignado' : 'Recibido',
        'Procesado' : 'Procesando Solicitud',
        'Terminado' : 'Solicitud Finalizada',
    }

    diccionario_mantenimiento = {
        'Análisis' : 'Validando Referencias',
        'Asignado' : 'Recibido',
        'Procesado' : 'Procesando Solicitud',
        'Escalado a área correspondiente' : 'Validando Referencias',
        'Asignado áreas internas' : 'Procesando Solicitud',
        'Extensión de Información' : 'Validando Referencias',
        'Continuidad' : 'En espera de Respuesta',
        'Terminado' : 'Solicitud Finalizada'
    }

    diccionario_siniestros = {
        'Análisis' : 'Validando Referencias',
        'Asignado' : 'Recibido',
        'Procesado' : 'Procesando Solicitud',
        'Continuidad' : 'En espera de Respuesta',
        'Terminado' : 'Solicitud Finalizada'
    }

    diccionario_cancelacion = {
        'Asignado' : 'Recibido',
        'Procesado' : 'Procesando Solicitud',
        'Terminado' : 'Solicitud Finalizada'
    }

class tiempos_folios:
    gnp_linea_respaldo = {
        "Emisión": 7,
        "Baja de Asegurado(s)": 7,
        "Cancelación": 7,
        "Modificación de Datos": 7,
        "Cambio de Contratante": 7,
        "Cambio de Forma de Pago": 7,
        "Constancia de Antigüedad": 7,
        "Duplicado": 1,
        "Pago de Póliza": 3,
        "Suspensión de Descuentos": 5,
        "Devolución de Primas": 7,
        "Rehabilitación": 7,
        "Facturas": 7,
        "Asesoría": 1,
        "Reembolso": 12
    }

    gnp_prismas = {
        "Asesoría": 1,
        "Cambio de Forma de Pago": 5,
        "Modificación de Datos": 5,
        "Duplicado": 5,
        "Cambio de Contratante": 5,
        "Rescate": 5,
        "Vencimiento": 5,
        "Pago de Póliza": 3,
        "Devolución de Primas": 5,
        "Suspensión de Descuentos": 5,
        "Retiros Parciales": 5
    }

    gnp_auto_mas = {
        "Emisión": 5,
        "Modificación de Datos": 5,
        "Devolución de Primas": 10,
        "Cancelación": 1,
        "Duplicado": 1,
        "Asesoría": 1,
        "Pago de Póliza": 7,
        "Solicitud de Clave de Marca": 2,
        "Suspensión de Descuentos": 5,
        "Atención de Siniestros Autos": 45
    }

    qualitas_ana_axa = {
        "Emisión": 2,
        "Modificación de Datos": 3,
        "Devolución de Primas": 15,
        "Cancelación": 1,
        "Duplicado": 1,
        "Asesoría": 1,
        "Pago de Póliza": 3,
        "Solicitud de Clave de Marca": 3,
        "Suspensión de Descuentos": 5,
        "Atención de Siniestros Autos": 45
    }

    general_multi = {
        "Reembolso": 15,
        "Programación de cirugía": 5,
        "Programación de estudios": 5,
        "Programación de medicamentos": 5,
        "Programación de terapia": 5,
        "Programación de tratamiento": 5
    }

    vida_gnp_grupo = {
        "Indemnización": 7
    }

    vida_gnp_total = {
        "Indemnización": 22
    }

    vida_inbursa_total = {
        "Indemnización": 22
    }

    vida_general_grupo = {
        "Indemnización": 8
    }
    

    dias_maximos = {
        "GNP": {
            "LINEA AZUL":{
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": gnp_linea_respaldo,
                "GRUPO BIMBO": gnp_linea_respaldo,
                "CAJA DE AHORRO DE LOS TELEFONISTAS, S.C DE A.P. DE R.L. DE C.V.": gnp_linea_respaldo,
                "M.A. COOLEY Y ASOCIADOS, S.C.": gnp_linea_respaldo
            },
            "RESPALDO MEDICO":{
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": gnp_linea_respaldo
            },
            "VIDAMAS": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": {
                    "Emisión": 5,
                    "Rescate": 5,
                    "Asesoría": 1,
                    "Modificación de Datos": 5,
                    "Devolución de Primas": 5,
                    "Duplicado": 1,
                    "Retiro de Ahorro": 5,
                    "Vencimiento": 5,
                    "Cambio de Forma de Pago": 5,
                    "Suspensión de Descuentos": 5,
                    "Pago de Póliza": 3,
                    "Modificación de Ahorro": 3,
                    "Facturas": 7
                }
            },
            "VIDA TOTAL": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": {
                    "Emisión": 3,
                    "Cancelación": 5,
                    "Asesoría": 1,
                    "Modificación de Datos": 5,
                    "Devolución de Primas": 5,
                    "Duplicado": 1,
                    "Retiro de Dividendos": 5,
                    "Vencimiento": 5,
                    "Suspensión de Descuentos": 5,
                    "Facturas": 7,
                    "Indemnización": 22
                },
                "GRUPO BIMBO": vida_gnp_total,
                "CAJA DE AHORRO DE LOS TELEFONISTAS, S.C DE A.P. DE R.L. DE C.V.": vida_gnp_total,
                "M.A. COOLEY Y ASOCIADOS, S.C.": vida_gnp_total,
                "TECMARKETING, S.A. DE C.V.": vida_gnp_total
            },
            "VIDA GRUPO": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": vida_gnp_grupo,
                "GRUPO BIMBO": vida_gnp_grupo,
                "CAJA DE AHORRO DE LOS TELEFONISTAS, S.C DE A.P. DE R.L. DE C.V.": vida_gnp_grupo,
                "M.A. COOLEY Y ASOCIADOS, S.C.": vida_gnp_grupo,
                "TECMARKETING, S.A. DE C.V.": vida_gnp_grupo
            },
            "PRISMADOLARES": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": gnp_prismas
            },
            "PRISMATEL": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": gnp_prismas
            },
            "PRISMATELXXI": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": gnp_prismas
            },
            "COLECTIVO GNP": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": {
                    "Cancelación": 3,
                    "Asesoría": 1,
                    "Devolución de Primas": 5,
                    "Reembolso": 12
                }
            },
            "AUTOMAS": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": gnp_auto_mas,
                "GRUPO BIMBO": gnp_auto_mas,
                "CAJA DE AHORRO DE LOS TELEFONISTAS, S.C DE A.P. DE R.L. DE C.V.": gnp_auto_mas,
                "M.A. COOLEY Y ASOCIADOS, S.C.": gnp_auto_mas,
                "TECMARKETING, S.A. DE C.V.": gnp_auto_mas,
                "COMPAÑÍA DE TELÉFONOS Y BIENES RAÍCES, S.A. DE C.V.": gnp_auto_mas
            } 
        },
        "QUALITAS": {
            "AUTOQUALITAS": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": qualitas_ana_axa,
                "CAJA DE AHORRO DE LOS TELEFONISTAS, S.C DE A.P. DE R.L. DE C.V.": qualitas_ana_axa,
                "COMPAÑÍA DE TELÉFONOS Y BIENES RAÍCES, S.A. DE C.V.": qualitas_ana_axa,
                "TECMARKETING, S.A. DE C.V.": qualitas_ana_axa,
                "M.A. COOLEY Y ASOCIADOS, S.C.": qualitas_ana_axa
            }
        },
        "ANA": {
            "ANA COR": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": qualitas_ana_axa,
                "CAJA DE AHORRO DE LOS TELEFONISTAS, S.C DE A.P. DE R.L. DE C.V.": qualitas_ana_axa,
                "COMPAÑÍA DE TELÉFONOS Y BIENES RAÍCES, S.A. DE C.V.": qualitas_ana_axa,
                "TECMARKETING, S.A. DE C.V.": qualitas_ana_axa,
                "M.A. COOLEY Y ASOCIADOS, S.C.": qualitas_ana_axa
            }
        },
        "GENERAL": {
            "INDEMNIZATORIO": {
                "GRUPO BIMBO": {
                    "Emisión": 7,
                    "Baja de Asegurado(s)": 3,
                    "Cancelación": 3,
                    "Cambio de Contratante": 5,
                    "Modificación de Datos": 5,
                    "Cambio de Forma de Pago": 5
                }
            },
            "MULTI SALUD": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": general_multi,
                "GRUPO BIMBO": general_multi,
                "M.A. COOLEY Y ASOCIADOS, S.C.": general_multi
            },
            "VIDA GRUPO": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": vida_general_grupo,
                "GRUPO BIMBO": vida_general_grupo,
                "CAJA DE AHORRO DE LOS TELEFONISTAS, S.C DE A.P. DE R.L. DE C.V.": vida_general_grupo,
                "M.A. COOLEY Y ASOCIADOS, S.C.": vida_general_grupo,
                "TECMARKETING, S.A. DE C.V.": vida_general_grupo
            }
        },
        "GENERAL DE SALUD": {
            "INDEMNIZATORIO": {
                "GRUPO BIMBO": {
                    "Emisión": 7,
                    "Baja de Asegurado(s)": 3,
                    "Cancelación": 3,
                    "Cambio de Contratante": 5,
                    "Modificación de Datos": 5,
                    "Cambio de Forma de Pago": 5
                }
            },
            "MULTI SALUD": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": general_multi,
                "GRUPO BIMBO": general_multi,
                "M.A. COOLEY Y ASOCIADOS, S.C.": general_multi
            },
            "VIDA GRUPO": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": vida_general_grupo,
                "GRUPO BIMBO": vida_general_grupo,
                "CAJA DE AHORRO DE LOS TELEFONISTAS, S.C DE A.P. DE R.L. DE C.V.": vida_general_grupo,
                "M.A. COOLEY Y ASOCIADOS, S.C.": vida_general_grupo,
                "TECMARKETING, S.A. DE C.V.": vida_general_grupo
            }
        },
        "GMX": {
            "HOGAR": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": {
                    "Emisión": 5,
                    "Cancelación": 5,
                    "Cambio de Contratante": 5,
                    "Modificación de Datos": 5
                }
            }
        },
        "AXA": {
            "AUTO AXA": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": qualitas_ana_axa
            }
        },
        "INBURSA": { 
            "INBURDOLAR":{
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA":{
                    "Asesoría": 5,
                    "Modificación de Datos": 5,
                    "Facturas": 7,
                    "Rescate": 5,
                    "Duplicado": 5,
                    "Vencimiento": 5,
                    "Devolución de Primas": 5,
                    "Pago de Póliza": 3,
                    "Suspensión de Descuentos": 5
                }
            },
            "VIDA TOTAL": {
                "SINDICATO DE TELEFONISTAS DE LA REPÚBLICA MEXICANA": vida_inbursa_total,
                "CAJA DE AHORRO DE LOS TELEFONISTAS, S.C DE A.P. DE R.L. DE C.V.": vida_inbursa_total,
                "COMPAÑÍA DE TELÉFONOS Y BIENES RAÍCES, S.A. DE C.V.": vida_inbursa_total,
                "TECMARKETING, S.A. DE C.V.": vida_inbursa_total,
                "M.A. COOLEY Y ASOCIADOS, S.C.": vida_inbursa_total
            }
        }
    }

class campos_cotizacion:
    nombres_legibles = {
        "cp": "Código postal",
        "modelo": "Modelo del vehículo",
        "marca": "Marca del vehículo",
        "version": "Versión del vehículo",
        "fecha_nacimiento_conductor": "Fecha de nacimiento del conductor habitual",
        "genero": "Género",
        "negocio": "Negocio",
        "edad": "Edad",
        "tipo_de_vivienda": "¿Casa o departamento?",
        "propietario": "¿Es usted propietario y arrendador?",
        "fumador": "¿Ha fumado en los últimos 12 meses?",
        "fecha_nacimiento": "Fecha de nacimiento",
        "estado": "Estado donde radica",
        "raza": "Raza",
        "edad_mascota": "Edad de la mascota",
        "tipo_mascota": "¿Perro o gato?",
        "genero_mascota": "¿Hembra o macho?",
        "cp_contrante": "Código postal del contratante",
        "edad_contratante": "Edad del contratante",
        "fecha_inicio": "Fecha de inicio del viaje",
        "fecha_fin": "Fecha de fin del viaje",
        "pais_region": "País y región a las que van",
        "no_asegurados": "No. de asegurados",
        "mayores_de_edad": "¿Viajan con personas mayores a 79 años de edad?"
    }

    MAPEO_RAMOS = {
        "auto_data": "AUTO",
        "gmm_data": "GMM",
        "hogar_data": "HOGAR",
        "vida_total_data": "VIDA TOTAL",
        "vida_mas_data": "VIDA MÁS",
        "plan_seguro_data": "PLAN SEGURO",
        "mascota_data": "MASCOTA",
        "viajes_data": "VIAJES"
    }