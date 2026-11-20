import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/chat_message.dart';
import '../theme.dart';
import 'common.dart';
import 'risk_alert_card.dart';

class MessageBubble extends StatelessWidget {
  final ChatMessage message;
  final bool isMe;

  /// true si el mensaje anterior es del mismo remitente (burbujas más juntas).
  final bool grouped;

  const MessageBubble({
    super.key,
    required this.message,
    required this.isMe,
    this.grouped = false,
  });

  @override
  Widget build(BuildContext context) {
    final time = message.timestamp > 0 ? DateFormat('HH:mm').format(message.dateTime) : '';
    const radius = Radius.circular(16);
    final tail = Radius.circular(grouped ? 16 : 4);
    final showFraudBorder = !isMe && message.isFraud;

    return Align(
      alignment: isMe ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.80),
        margin: EdgeInsets.only(left: isMe ? 48 : 10, right: isMe ? 10 : 48, top: grouped ? 2 : 8),
        padding: const EdgeInsets.fromLTRB(12, 8, 10, 6),
        decoration: BoxDecoration(
          color: isMe ? AppColors.bubbleMine : AppColors.bubbleOther,
          borderRadius: BorderRadius.only(
            topLeft: isMe ? radius : tail,
            topRight: isMe ? tail : radius,
            bottomLeft: radius,
            bottomRight: radius,
          ),
          border: showFraudBorder ? Border.all(color: AppColors.dangerBorder, width: 1.2) : null,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              message.texto,
              style: const TextStyle(color: AppColors.text, fontSize: 15, height: 1.35),
            ),
            if (!isMe) RiskAlertCard(message: message),
            if (isMe && message.isFraud)
              const Padding(
                padding: EdgeInsets.only(top: 6),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.info_outline, size: 13, color: AppColors.warning),
                    SizedBox(width: 4),
                    Flexible(
                      child: Text(
                        'El destinatario lo verá marcado como posible estafa',
                        style: TextStyle(color: AppColors.warning, fontSize: 11),
                      ),
                    ),
                  ],
                ),
              ),
            const SizedBox(height: 3),
            Align(
              alignment: Alignment.centerRight,
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(time, style: const TextStyle(color: AppColors.textMuted, fontSize: 11)),
                  if (isMe) ...[
                    const SizedBox(width: 4),
                    SendStatusIcon(status: message.status, size: 14),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
