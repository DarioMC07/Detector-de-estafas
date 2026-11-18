"""Formateo amigable de resultados de análisis para Telegram."""

from typing import Any, Dict, List


def format_analysis_response(data: Dict[str, Any]) -> str:
    """
    Formatea la respuesta devuelta por la API /analizar para el usuario de Telegram.

    Reutiliza:
    - Clasificación y nivel de riesgo
    - Indicadores / señales detectadas
    - Recomendaciones
    - Aviso de incertidumbre si corresponde
    - Aviso orientativo / datos demostrativos
    """
    etiqueta = data.get("etiqueta_modelo", "legitimo")
    incertidumbre = bool(data.get("incertidumbre", False))
    senales: List[Dict[str, Any]] = data.get("senales", [])
    recomendaciones: List[str] = data.get("recomendaciones", [])
    aviso_incertidumbre = data.get("aviso_incertidumbre")
    es_demo = bool(data.get("datos_demostrativos", False))

    if incertidumbre:
        header = "⚠️ RESULTADO INCIERTO"
        risk_str = "MEDIO"
    elif etiqueta == "fraudulento":
        header = "🚨 POSIBLE ESTAFA"
        risk_str = "ALTO"
    else:
        header = "✅ MENSAJE APARENTEMENTE LEGÍTIMO"
        risk_str = "BAJO"

    parts = [header, "", f"Nivel de riesgo: {risk_str}"]

    # Indicadores detectados
    parts.append("")
    parts.append("Indicadores detectados:")
    if senales:
        for s in senales:
            title = s.get("titulo") or s.get("codigo") or "Señal de alerta"
            parts.append(f"• {title}")
    else:
        parts.append("• No se detectaron patrones sospechosos evidentes en el texto.")

    # Si hay incertidumbre, añadir el aviso descriptivo
    if incertidumbre and aviso_incertidumbre:
        parts.append("")
        parts.append(f"Nota de incertidumbre:\n{aviso_incertidumbre}")

    # Recomendaciones
    if recomendaciones:
        parts.append("")
        parts.append("Recomendación:")
        for r in recomendaciones:
            parts.append(f"• {r}")

    # Pie orientativo y advertencia de datos demostrativos
    parts.append("")
    disclaimer = data.get("aviso", "Esta evaluación es orientativa y puede cometer errores.")
    if es_demo:
        disclaimer += " (Modelo entrenado con datos demostrativos)."
    parts.append(f"ℹ️ {disclaimer}")

    return "\n".join(parts)

