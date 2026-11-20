import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/chat_message.dart';
import '../services/chat_websocket_service.dart';
import '../theme.dart';
import '../utils/phone.dart';
import '../widgets/common.dart';
import 'chat_conversation_screen.dart';
import 'login_screen.dart';
import 'manual_analyzer_screen.dart';

class ChatListScreen extends StatefulWidget {
  const ChatListScreen({super.key});

  @override
  State<ChatListScreen> createState() => _ChatListScreenState();
}

class _ChatListScreenState extends State<ChatListScreen> {
  final _service = ChatWebSocketService();
  StreamSubscription<ChatEvent>? _eventsSub;

  @override
  void initState() {
    super.initState();
    _eventsSub = _service.events.listen(_onEvent);
  }

  @override
  void dispose() {
    _eventsSub?.cancel();
    super.dispose();
  }

  void _onEvent(ChatEvent event) {
    if (!mounted) return;
    if (event.kind == 'sesion_cerrada') {
      _service.logout();
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => LoginScreen(initialError: event.message)),
        (_) => false,
      );
      return;
    }
    // Avisos de mensajes nuevos solo si no estamos dentro de esa conversación
    // (la pantalla de conversación muestra sus propios errores).
    if (event.kind == 'nuevo_mensaje' && ModalRoute.of(context)?.isCurrent == true) {
      final msg = event.chatMessage!;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(msg.isFraud ? '🚨 ${event.message}: posible estafa' : event.message),
          action: SnackBarAction(label: 'Abrir', onPressed: () => _openChat(msg.remitente)),
        ),
      );
    } else if (event.kind == 'error' && ModalRoute.of(context)?.isCurrent == true) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(event.message)));
    }
  }

  void _openChat(String peer) {
    ScaffoldMessenger.of(context).hideCurrentSnackBar();
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => ChatConversationScreen(peerPhone: peer)),
    );
  }

  Future<void> _logout() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Cerrar sesión'),
        content: const Text('Se cerrará la sesión en este teléfono. Tus conversaciones siguen en el servidor.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Cerrar sesión')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await _service.logout();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  Future<void> _showNewChatDialog() async {
    final peer = await showDialog<String>(
      context: context,
      builder: (_) => _NewChatDialog(myPhone: _service.myPhone ?? ''),
    );
    if (peer != null && mounted) _openChat(peer);
  }

  String _formatTime(DateTime dt) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final day = DateTime(dt.year, dt.month, dt.day);
    if (day == today) return DateFormat('HH:mm').format(dt);
    if (today.difference(day).inDays == 1) return 'Ayer';
    if (today.difference(day).inDays < 7) {
      const days = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom'];
      return days[dt.weekday - 1];
    }
    return DateFormat('dd/MM/yy').format(dt);
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: _service,
      builder: (context, _) {
        final me = _service.myPhone ?? '';
        final peers = _service.sortedPeers;
        final online = _service.onlineUsers.where((u) => u != me).toList()..sort();

        return Scaffold(
          appBar: AppBar(
            titleSpacing: 16,
            title: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Mensaje Seguro', style: TextStyle(fontSize: 19, fontWeight: FontWeight.w600)),
                Text(
                  _service.isConnected ? formatPhone(me) : '${formatPhone(me)} · sin conexión',
                  style: TextStyle(
                    color: _service.isConnected ? AppColors.safe : AppColors.textMuted,
                    fontSize: 12,
                    fontWeight: FontWeight.normal,
                  ),
                ),
              ],
            ),
            actions: [
              IconButton(
                icon: const Icon(Icons.manage_search),
                tooltip: 'Analizar un mensaje',
                onPressed: () => Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const ManualAnalyzerScreen()),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.logout),
                tooltip: 'Cerrar sesión',
                onPressed: _logout,
              ),
            ],
          ),
          body: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ConnectionBanner(service: _service),
              if (online.isNotEmpty) ...[
                const _SectionTitle('EN LÍNEA'),
                SizedBox(
                  height: 86,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    itemCount: online.length,
                    separatorBuilder: (_, __) => const SizedBox(width: 14),
                    itemBuilder: (context, i) {
                      final user = online[i];
                      return InkWell(
                        borderRadius: BorderRadius.circular(12),
                        onTap: () => _openChat(user),
                        child: SizedBox(
                          width: 64,
                          child: Column(
                            children: [
                              PhoneAvatar(phone: user, online: true, radius: 24),
                              const SizedBox(height: 6),
                              Text(
                                user.length > 4 ? '…${user.substring(user.length - 4)}' : user,
                                style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
                ),
                const Divider(height: 1),
              ],
              const _SectionTitle('CHATS'),
              Expanded(
                child: peers.isEmpty
                    ? _EmptyChats(hasOnline: online.isNotEmpty)
                    : ListView.builder(
                        padding: const EdgeInsets.only(bottom: 90),
                        itemCount: peers.length,
                        itemBuilder: (context, i) => _buildTile(peers[i], me),
                      ),
              ),
            ],
          ),
          floatingActionButton: FloatingActionButton.extended(
            onPressed: _showNewChatDialog,
            icon: const Icon(Icons.edit_outlined),
            label: const Text('Nuevo chat', style: TextStyle(fontWeight: FontWeight.bold)),
          ),
        );
      },
    );
  }

  Widget _buildTile(String peer, String me) {
    final msgs = _service.conversations[peer] ?? const <ChatMessage>[];
    final last = msgs.last;
    final mine = last.remitente == me;
    final unread = _service.unread[peer] ?? 0;
    final fraudCount = msgs.where((m) => m.isFraud && m.remitente != me).length;

    return InkWell(
      onTap: () => _openChat(peer),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(
          children: [
            PhoneAvatar(phone: peer, online: _service.onlineUsers.contains(peer), radius: 25),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          formatPhone(peer),
                          style: const TextStyle(color: AppColors.text, fontWeight: FontWeight.w600, fontSize: 16),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      Text(
                        _formatTime(last.dateTime),
                        style: TextStyle(color: unread > 0 ? AppColors.accent : AppColors.textFaint, fontSize: 12),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      if (mine) ...[
                        SendStatusIcon(status: last.status, size: 15),
                        const SizedBox(width: 4),
                      ],
                      if (!mine && last.isFraud) ...[
                        const Icon(Icons.gpp_maybe, size: 16, color: AppColors.danger),
                        const SizedBox(width: 4),
                      ],
                      Expanded(
                        child: Text(
                          last.texto,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: !mine && last.isFraud ? AppColors.danger : AppColors.textMuted,
                            fontSize: 14,
                          ),
                        ),
                      ),
                      if (fraudCount > 0 && !(last.isFraud && !mine)) ...[
                        const SizedBox(width: 6),
                        const Icon(Icons.gpp_maybe_outlined, size: 16, color: AppColors.danger),
                      ],
                      if (unread > 0) ...[
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                          constraints: const BoxConstraints(minWidth: 22),
                          decoration: BoxDecoration(color: AppColors.accent, borderRadius: BorderRadius.circular(11)),
                          child: Text(
                            unread > 99 ? '99+' : '$unread',
                            textAlign: TextAlign.center,
                            style: const TextStyle(color: AppColors.onAccent, fontSize: 12, fontWeight: FontWeight.bold),
                          ),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String text;
  const _SectionTitle(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
      child: Text(
        text,
        style: const TextStyle(color: AppColors.accent, fontSize: 11, fontWeight: FontWeight.bold, letterSpacing: 1.3),
      ),
    );
  }
}

class _EmptyChats extends StatelessWidget {
  final bool hasOnline;
  const _EmptyChats({required this.hasOnline});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.forum_outlined, size: 56, color: AppColors.textFaint.withAlpha(150)),
            const SizedBox(height: 14),
            const Text('Aún no tienes chats', style: TextStyle(color: AppColors.text, fontSize: 16, fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            Text(
              hasOnline
                  ? 'Toca a alguien de la lista «En línea» o usa «Nuevo chat».'
                  : 'Usa «Nuevo chat» y escribe el número de la otra persona.',
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textMuted, fontSize: 13),
            ),
          ],
        ),
      ),
    );
  }
}

class _NewChatDialog extends StatefulWidget {
  final String myPhone;
  const _NewChatDialog({required this.myPhone});

  @override
  State<_NewChatDialog> createState() => _NewChatDialogState();
}

class _NewChatDialogState extends State<_NewChatDialog> {
  final _controller = TextEditingController();
  String? _error;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _submit() {
    final peer = normalizePhone(_controller.text);
    if (peer == null) {
      setState(() => _error = 'Número inválido. Ej: 77004938 o +59177004938');
      return;
    }
    if (peer == widget.myPhone) {
      setState(() => _error = 'Ese es tu propio número.');
      return;
    }
    Navigator.pop(context, peer);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Nuevo chat'),
      content: TextField(
        controller: _controller,
        autofocus: true,
        keyboardType: TextInputType.phone,
        style: const TextStyle(color: AppColors.text),
        onSubmitted: (_) => _submit(),
        decoration: InputDecoration(
          hintText: '77004938',
          errorText: _error,
          prefixIcon: const Icon(Icons.phone_outlined, color: AppColors.textMuted),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancelar')),
        TextButton(onPressed: _submit, child: const Text('Abrir chat')),
      ],
    );
  }
}
