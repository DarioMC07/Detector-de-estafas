import 'package:flutter/material.dart';

import '../models/chat_message.dart';
import '../theme.dart';
import '../utils/fraud_labels.dart';

/// Resultado del detector para un mensaje recibido.
///
/// Los mensajes legítimos muestran una línea discreta; los sospechosos, una
/// tarjeta con las señales y recomendaciones (desplegable).
class RiskAlertCard extends StatefulWidget {
  final ChatMessage message;

  const RiskAlertCard({super.key, required this.message});

  @override
  State<RiskAlertCard> createState() => _RiskAlertCardState();
}

class _RiskAlertCardState extends State<RiskAlertCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final m = widget.message;

    if (m.isUnknown) {
      return const _InlineVerdict(
        icon: Icons.help_outline,
        color: AppColors.textMuted,
        text: 'No se pudo analizar (modelo no disponible). Sé precavido.',
      );
    }

    if (m.isSafe && m.senales.isEmpty) {
      return const _InlineVerdict(
        icon: Icons.verified_user_outlined,
        color: AppColors.safe,
        text: 'Sin señales de estafa',
      );
    }

    final isFraud = m.isFraud;
    // Un enlace http/sospechoso sin otros indicios se muestra como precaución, no como "incierto".
    final isLinkWarning = !isFraud && m.hasRiskyLink;
    final isUncertain = m.incertidumbre || isLinkWarning;
    final Color bg = isFraud ? AppColors.dangerBg : (isUncertain ? AppColors.warningBg : AppColors.safeBg);
    final Color border = isFraud ? AppColors.dangerBorder : (isUncertain ? AppColors.warningBorder : AppColors.safeBorder);
    final Color fg = isFraud ? const Color(0xFFFFB4B4) : (isUncertain ? AppColors.warning : AppColors.safe);
    final IconData icon = isFraud
        ? Icons.gpp_maybe
        : (isLinkWarning ? Icons.link_off : (isUncertain ? Icons.warning_amber_rounded : Icons.verified_user_outlined));
    final category = categoriaLabel(m.categoriaFraude);
    final String title = isFraud
        ? (category.isNotEmpty ? 'Posible estafa: $category' : 'Posible estafa')
        : (isLinkWarning
            ? 'Precaución: enlace no seguro'
            : (isUncertain ? 'Resultado incierto' : 'Parece legítimo, con señales a revisar'));
    final action = (isFraud || isUncertain) ? accionLabel(m.accionTactica) : null;
    final hasDetails = m.senales.isNotEmpty || m.recomendaciones.isNotEmpty || m.avisoIncertidumbre != null;

    return Container(
      margin: const EdgeInsets.only(top: 8),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: border),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: hasDetails ? () => setState(() => _expanded = !_expanded) : null,
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(icon, size: 18, color: fg),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        '$title · riesgo ${m.nivel}',
                        style: TextStyle(color: fg, fontWeight: FontWeight.bold, fontSize: 13),
                      ),
                    ),
                    if (hasDetails)
                      Icon(_expanded ? Icons.expand_less : Icons.expand_more, size: 18, color: fg),
                  ],
                ),
                if (action != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Row(
                      children: [
                        Icon(m.linksBlocked ? Icons.block : Icons.pan_tool_alt_outlined, size: 14, color: fg),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(action,
                              style: TextStyle(color: fg, fontSize: 12, fontWeight: FontWeight.w600)),
                        ),
                      ],
                    ),
                  ),
                if (!_expanded && m.senales.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Wrap(
                      spacing: 6,
                      runSpacing: 4,
                      children: m.senales
                          .map((s) => Container(
                                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                decoration: BoxDecoration(
                                  color: Colors.black.withAlpha(50),
                                  borderRadius: BorderRadius.circular(8),
                                ),
                                child: Text(
                                  shortSignalLabel(s.codigo, s.titulo),
                                  style: TextStyle(color: fg, fontSize: 11),
                                ),
                              ))
                          .toList(),
                    ),
                  ),
                if (_expanded) ...[
                  if (m.avisoIncertidumbre != null) ...[
                    const SizedBox(height: 8),
                    Text(m.avisoIncertidumbre!, style: TextStyle(color: fg, fontSize: 12, height: 1.35)),
                  ],
                  if (m.senales.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text('Señales detectadas', style: TextStyle(color: fg, fontWeight: FontWeight.w700, fontSize: 12)),
                    const SizedBox(height: 4),
                    ...m.senales.map((s) => _Bullet(
                          color: fg,
                          title: s.titulo.isNotEmpty ? s.titulo : s.codigo,
                          body: s.descripcion,
                        )),
                  ],
                  if (m.recomendaciones.isNotEmpty && (isFraud || isUncertain)) ...[
                    const SizedBox(height: 8),
                    Text('Qué hacer', style: TextStyle(color: fg, fontWeight: FontWeight.w700, fontSize: 12)),
                    const SizedBox(height: 4),
                    ...m.recomendaciones.map((r) => _Bullet(color: fg, title: r)),
                  ],
                  const SizedBox(height: 6),
                  Text(
                    'Evaluación orientativa: puede equivocarse.',
                    style: TextStyle(color: fg.withAlpha(170), fontSize: 10.5, fontStyle: FontStyle.italic),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _InlineVerdict extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String text;
  const _InlineVerdict({required this.icon, required this.color, required this.text});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 13, color: color),
          const SizedBox(width: 4),
          Flexible(child: Text(text, style: TextStyle(color: color, fontSize: 11))),
        ],
      ),
    );
  }
}

class _Bullet extends StatelessWidget {
  final Color color;
  final String title;
  final String? body;
  const _Bullet({required this.color, required this.title, this.body});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('•  ', style: TextStyle(color: color, fontSize: 12)),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: TextStyle(color: color, fontSize: 12, height: 1.3)),
                if (body != null && body!.isNotEmpty)
                  Text(body!, style: TextStyle(color: color.withAlpha(180), fontSize: 11, height: 1.3)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
