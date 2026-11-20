import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/chat_message.dart';
import '../services/chat_websocket_service.dart';
import '../theme.dart';
import '../utils/phone.dart';
import '../widgets/common.dart';
import '../widgets/message_bubble.dart';

class ChatConversationScreen extends StatefulWidget {
  /// Número del otro usuario, ya normalizado.
  final String peerPhone;

  const ChatConversationScreen({super.key, required this.peerPhone});

  @override
  State<ChatConversationScreen> createState() => _ChatConversationScreenState();
}

class _ChatConversationScreenState extends State<ChatConversationScreen> {
  final _service = ChatWebSocketService();
  final _msgController = TextEditingController();
  final _scrollController = ScrollController();
  StreamSubscription<ChatEvent>? _eventsSub;
  int _lastCount = 0;

  @override
  void initState() {
    super.initState();
    _service.openConversation(widget.peerPhone);
    _service.requestHistory(widget.peerPhone);
    _service.addListener(_onServiceChanged);
    _eventsSub = _service.events.listen((event) {
      if (!mounted || event.kind != 'error') return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(event.message)));
    });
    _msgController.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _service.removeListener(_onServiceChanged);
    _service.closeConversation(widget.peerPhone);
    _eventsSub?.cancel();
    _msgController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _onServiceChanged() {
    // Mientras la conversación está abierta, los mensajes nuevos se dan por leídos.
    if ((_service.unread[widget.peerPhone] ?? 0) > 0) {
      _service.unread.remove(widget.peerPhone);
    }
    final count = _service.conversations[widget.peerPhone]?.length ?? 0;
    if (count != _lastCount) {
      _lastCount = count;
      _scrollToBottom();
    }
  }

  void _scrollToBottom() {
    // La lista está invertida: el final de la conversación es la posición 0.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(0, duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      }
    });
  }

  void _sendMessage() {
    final text = _msgController.text.trim();
    if (text.isEmpty) return;
    final error = _service.sendMessage(widget.peerPhone, text);
    if (error != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error)));
      return;
    }
    _msgController.clear();
    _scrollToBottom();
  }

  String _dayLabel(DateTime dt) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final day = DateTime(dt.year, dt.month, dt.day);
    final diff = today.difference(day).inDays;
    if (diff == 0) return 'Hoy';
    if (diff == 1) return 'Ayer';
    return DateFormat('dd/MM/yyyy').format(dt);
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: _service,
      builder: (context, _) {
        final msgs = _service.conversations[widget.peerPhone] ?? const <ChatMessage>[];
        final me = _service.myPhone ?? '';
        final isOnline = _service.onlineUsers.contains(widget.peerPhone);
        final fraudCount = msgs.where((m) => m.isFraud && m.remitente != me).length;

        return Scaffold(
          appBar: AppBar(
            titleSpacing: 0,
            title: Row(
              children: [
                PhoneAvatar(phone: widget.peerPhone, online: isOnline, radius: 19),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(formatPhone(widget.peerPhone), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
                      Text(
                        isOnline ? 'en línea' : 'desconectado',
                        style: TextStyle(
                          color: isOnline ? AppColors.safe : AppColors.textMuted,
                          fontSize: 12,
                          fontWeight: FontWeight.normal,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          body: Column(
            children: [
              ConnectionBanner(service: _service),
              if (fraudCount > 0)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  color: AppColors.dangerBg,
                  child: Row(
                    children: [
                      const Icon(Icons.gpp_maybe, size: 18, color: AppColors.danger),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          fraudCount == 1
                              ? 'Este contacto envió 1 mensaje marcado como posible estafa.'
                              : 'Este contacto envió $fraudCount mensajes marcados como posible estafa.',
                          style: const TextStyle(color: Color(0xFFFFC4C4), fontSize: 12),
                        ),
                      ),
                    ],
                  ),
                ),
              Expanded(
                child: msgs.isEmpty
                    ? const _EmptyConversation()
                    : ListView.builder(
                        controller: _scrollController,
                        reverse: true,
                        padding: const EdgeInsets.symmetric(vertical: 10),
                        itemCount: msgs.length,
                        itemBuilder: (context, index) {
                          final i = msgs.length - 1 - index;
                          final msg = msgs[i];
                          final prev = i > 0 ? msgs[i - 1] : null;
                          final showDay = prev == null || _dayLabel(prev.dateTime) != _dayLabel(msg.dateTime);
                          final grouped = prev != null && !showDay && prev.remitente == msg.remitente;
                          return Column(
                            children: [
                              if (showDay) _DayChip(_dayLabel(msg.dateTime)),
                              MessageBubble(message: msg, isMe: msg.remitente == me, grouped: grouped),
                            ],
                          );
                        },
                      ),
              ),
              _buildComposer(),
            ],
          ),
        );
      },
    );
  }

  Widget _buildComposer() {
    final canSend = _msgController.text.trim().isNotEmpty;
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
      decoration: const BoxDecoration(
        color: AppColors.surface,
        border: Border(top: BorderSide(color: AppColors.border, width: 0.8)),
      ),
      child: SafeArea(
        top: false,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: TextField(
                controller: _msgController,
                minLines: 1,
                maxLines: 5,
                maxLength: 5000,
                textCapitalization: TextCapitalization.sentences,
                style: const TextStyle(color: AppColors.text, fontSize: 15),
                decoration: InputDecoration(
                  hintText: 'Mensaje',
                  counterText: '',
                  fillColor: AppColors.background,
                  contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(24),
                    borderSide: const BorderSide(color: AppColors.border),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(24),
                    borderSide: const BorderSide(color: AppColors.border),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(24),
                    borderSide: const BorderSide(color: AppColors.accent),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            AnimatedOpacity(
              duration: const Duration(milliseconds: 150),
              opacity: canSend ? 1 : 0.45,
              child: Material(
                color: AppColors.accent,
                shape: const CircleBorder(),
                child: InkWell(
                  customBorder: const CircleBorder(),
                  onTap: canSend ? _sendMessage : null,
                  child: const Padding(
                    padding: EdgeInsets.all(12),
                    child: Icon(Icons.send_rounded, color: AppColors.onAccent, size: 22),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DayChip extends StatelessWidget {
  final String label;
  const _DayChip(this.label);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        decoration: BoxDecoration(color: AppColors.surfaceHigh, borderRadius: BorderRadius.circular(10)),
        child: Text(label, style: const TextStyle(color: AppColors.textMuted, fontSize: 12)),
      ),
    );
  }
}

class _EmptyConversation extends StatelessWidget {
  const _EmptyConversation();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: AppColors.border),
          ),
          child: const Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.shield_outlined, color: AppColors.accent),
              SizedBox(width: 12),
              Flexible(
                child: Text(
                  'Cada mensaje que recibas se analiza para detectar posibles estafas.',
                  style: TextStyle(color: AppColors.textMuted, fontSize: 13, height: 1.35),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
