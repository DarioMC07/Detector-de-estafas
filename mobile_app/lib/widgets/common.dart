import 'package:flutter/material.dart';

import '../models/chat_message.dart';
import '../services/chat_websocket_service.dart';
import '../theme.dart';
import '../utils/phone.dart';

/// Avatar circular con los dos últimos dígitos del número.
class PhoneAvatar extends StatelessWidget {
  final String phone;
  final bool online;
  final double radius;

  const PhoneAvatar({super.key, required this.phone, this.online = false, this.radius = 24});

  static const _palette = [
    Color(0xFF3B4A6B),
    Color(0xFF5A3F5E),
    Color(0xFF3F5E55),
    Color(0xFF6B553B),
    Color(0xFF4A3B6B),
    Color(0xFF5E3F3F),
  ];

  @override
  Widget build(BuildContext context) {
    final color = _palette[phone.codeUnits.fold<int>(0, (a, b) => a + b) % _palette.length];
    return SizedBox(
      width: radius * 2,
      height: radius * 2,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          CircleAvatar(
            radius: radius,
            backgroundColor: color,
            child: Text(
              phoneInitials(phone),
              style: TextStyle(color: AppColors.text, fontWeight: FontWeight.w700, fontSize: radius * 0.62),
            ),
          ),
          if (online)
            Positioned(
              right: 0,
              bottom: 0,
              child: Container(
                width: radius * 0.55,
                height: radius * 0.55,
                decoration: BoxDecoration(
                  color: AppColors.online,
                  shape: BoxShape.circle,
                  border: Border.all(color: AppColors.background, width: 2),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// Reloj = enviando · ✓ = guardado en el servidor · ✓✓ = entregado al otro teléfono.
class SendStatusIcon extends StatelessWidget {
  final SendStatus status;
  final double size;
  const SendStatusIcon({super.key, required this.status, this.size = 14});

  @override
  Widget build(BuildContext context) {
    switch (status) {
      case SendStatus.sending:
        return Icon(Icons.schedule, size: size, color: AppColors.textFaint);
      case SendStatus.sent:
        return Icon(Icons.done, size: size, color: AppColors.textMuted);
      case SendStatus.delivered:
        return Icon(Icons.done_all, size: size, color: AppColors.accent);
    }
  }
}

/// Franja que avisa cuando no hay conexión con el servidor.
class ConnectionBanner extends StatelessWidget {
  final ChatWebSocketService service;

  const ConnectionBanner({super.key, required this.service});

  @override
  Widget build(BuildContext context) {
    final status = service.status;
    if (status == ConnectionStatus.connected) return const SizedBox.shrink();

    final reconnecting = status == ConnectionStatus.reconnecting || status == ConnectionStatus.connecting;
    return Material(
      color: reconnecting ? AppColors.warningBg : AppColors.dangerBg,
      child: InkWell(
        onTap: service.reconnectNow,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Row(
            children: [
              if (reconnecting)
                const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.warning),
                )
              else
                const Icon(Icons.cloud_off, size: 16, color: AppColors.danger),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  reconnecting
                      ? 'Reconectando con el servidor… Los mensajes se enviarán al volver la conexión.'
                      : (service.lastError ?? 'Sin conexión. Toca para reintentar.'),
                  style: TextStyle(color: reconnecting ? AppColors.warning : const Color(0xFFFFC4C4), fontSize: 12),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
