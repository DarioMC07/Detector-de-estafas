import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../config.dart';
import '../models/chat_message.dart';
import '../utils/phone.dart';

enum ConnectionStatus { disconnected, connecting, connected, reconnecting }

class ChatException implements Exception {
  final String message;
  ChatException(this.message);
  @override
  String toString() => message;
}

/// Evento puntual para mostrar en pantalla (errores del servidor, mensajes nuevos…).
class ChatEvent {
  final String kind; // 'error' | 'nuevo_mensaje' | 'sesion_cerrada'
  final String message;
  final ChatMessage? chatMessage;
  ChatEvent(this.kind, this.message, {this.chatMessage});
}

/// Conexión WebSocket única con el servidor y estado de la mensajería.
class ChatWebSocketService extends ChangeNotifier {
  static final ChatWebSocketService _instance = ChatWebSocketService._internal();
  factory ChatWebSocketService() => _instance;
  ChatWebSocketService._internal();

  static const _connectTimeout = Duration(seconds: 8);
  static const _pingInterval = Duration(seconds: 25);

  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  Timer? _pingTimer;
  Timer? _reconnectTimer;
  int _retry = 0;
  bool _manualClose = false;

  /// Número propio, normalizado por el servidor (ej. +59177004938).
  String? myPhone;
  ConnectionStatus status = ConnectionStatus.disconnected;
  String? lastError;

  Set<String> onlineUsers = {};
  final Map<String, List<ChatMessage>> conversations = {};
  final Map<String, int> unread = {};

  /// Conversación abierta en pantalla (sus mensajes no cuentan como no leídos).
  String? activePeer;

  /// client_id enviados en esta conexión y aún sin confirmar, en orden.
  final List<String> _awaitingAck = [];

  final _events = StreamController<ChatEvent>.broadcast();
  Stream<ChatEvent> get events => _events.stream;

  bool get isConnected => status == ConnectionStatus.connected;
  bool get hasSession => myPhone != null;

  /// Conversaciones ordenadas por el último mensaje (más reciente primero).
  List<String> get sortedPeers {
    final peers = conversations.keys.where((p) => conversations[p]!.isNotEmpty).toList();
    peers.sort((a, b) => conversations[b]!.last.timestamp.compareTo(conversations[a]!.last.timestamp));
    return peers;
  }

  // ---------------------------------------------------------------------------
  // Conexión
  // ---------------------------------------------------------------------------

  /// Inicia sesión. Lanza [ChatException] si no se puede conectar.
  Future<void> login(String rawPhone) async {
    final phone = normalizePhone(rawPhone);
    if (phone == null) {
      throw ChatException('Número inválido. Usa 8 dígitos (77004938) o formato internacional (+59177004938).');
    }
    if (myPhone != phone) {
      _clearData();
    }
    _closeChannel();
    myPhone = phone;
    _manualClose = false;
    _retry = 0;
    try {
      await _open(initial: true);
    } catch (_) {
      myPhone = null;
      status = ConnectionStatus.disconnected;
      notifyListeners();
      rethrow;
    }
    await AppConfig.savePhone(myPhone);
  }

  Future<void> _open({bool initial = false}) async {
    final phone = myPhone;
    if (phone == null) return;
    _reconnectTimer?.cancel();
    status = initial ? ConnectionStatus.connecting : ConnectionStatus.reconnecting;
    notifyListeners();

    final uri = Uri.parse(
      '${AppConfig.wsUrl}/ws/chat/${Uri.encodeComponent(phone)}'
      '?token=${Uri.encodeQueryComponent(AppConfig.deviceToken)}',
    );

    final WebSocketChannel channel;
    try {
      channel = WebSocketChannel.connect(uri);
      await channel.ready.timeout(_connectTimeout);
    } catch (e) {
      final msg = 'No se pudo conectar con ${AppConfig.baseUrl}. '
          'Comprueba que el servidor esté encendido con --host 0.0.0.0, que el teléfono '
          'esté en la misma red Wi-Fi y que el firewall permita el puerto.';
      lastError = msg;
      if (initial) throw ChatException(msg);
      _scheduleReconnect();
      return;
    }

    _channel = channel;
    final welcome = Completer<void>();

    _subscription = channel.stream.listen(
      (data) {
        if (!identical(_channel, channel)) return;
        Map<String, dynamic> decoded;
        try {
          decoded = Map<String, dynamic>.from(jsonDecode(data as String) as Map);
        } catch (_) {
          return;
        }
        _handleIncoming(decoded);
        if (decoded['tipo'] == 'sistema' && !welcome.isCompleted) welcome.complete();
      },
      onError: (_) {},
      onDone: () {
        if (!identical(_channel, channel)) return;
        final error = _closeMessage(channel.closeCode);
        if (!welcome.isCompleted) {
          // Aún conectando: el fallo lo gestiona el bloque catch de abajo.
          welcome.completeError(ChatException(error ?? 'El servidor cerró la conexión.'));
          return;
        }
        _onClosed(channel.closeCode, error);
      },
    );

    try {
      await welcome.future.timeout(_connectTimeout);
    } catch (e) {
      final msg = e is ChatException ? e.message : 'El servidor no respondió a tiempo.';
      lastError = msg;
      if (identical(_channel, channel)) _closeChannel();
      if (initial) throw ChatException(msg);
      if (_isFatal(channel.closeCode)) {
        status = ConnectionStatus.disconnected;
        _events.add(ChatEvent('sesion_cerrada', msg));
        notifyListeners();
        return;
      }
      _scheduleReconnect();
      return;
    }

    status = ConnectionStatus.connected;
    lastError = null;
    _retry = 0;
    _pingTimer?.cancel();
    _pingTimer = Timer.periodic(_pingInterval, (_) => _send({'tipo': 'ping'}));
    _flushPending();
    notifyListeners();
  }

  bool _isFatal(int? code) => code == 4000 || code == 4001 || code == 4003;

  String? _closeMessage(int? code) {
    switch (code) {
      case 4000:
        return 'El servidor rechazó el número por formato inválido.';
      case 4001:
        return 'Tu número se abrió en otra sesión. Esta sesión se cerró.';
      case 4003:
        return 'Este número ya está registrado en otro teléfono. Usa tu propio número.';
    }
    return null;
  }

  void _onClosed(int? code, String? error) {
    _pingTimer?.cancel();
    _subscription?.cancel();
    _subscription = null;
    _channel = null;
    _awaitingAck.clear();
    if (_manualClose || myPhone == null) {
      status = ConnectionStatus.disconnected;
      notifyListeners();
      return;
    }
    if (_isFatal(code)) {
      status = ConnectionStatus.disconnected;
      lastError = error;
      _events.add(ChatEvent('sesion_cerrada', error ?? 'Sesión cerrada.'));
      notifyListeners();
      return;
    }
    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    if (_manualClose || myPhone == null) return;
    status = ConnectionStatus.reconnecting;
    notifyListeners();
    _reconnectTimer?.cancel();
    final seconds = min(30, 1 << min(_retry, 5));
    _retry++;
    _reconnectTimer = Timer(Duration(seconds: seconds), () => _open());
  }

  /// Reintenta de inmediato (p. ej. al volver a abrir la app).
  void reconnectNow() {
    if (myPhone == null || _manualClose) return;
    if (status == ConnectionStatus.connected || status == ConnectionStatus.connecting) return;
    _retry = 0;
    _open();
  }

  void _closeChannel() {
    _pingTimer?.cancel();
    _reconnectTimer?.cancel();
    _subscription?.cancel();
    _subscription = null;
    final ch = _channel;
    _channel = null;
    ch?.sink.close();
    _awaitingAck.clear();
  }

  Future<void> logout() async {
    _manualClose = true;
    _closeChannel();
    _clearData();
    myPhone = null;
    status = ConnectionStatus.disconnected;
    await AppConfig.savePhone(null);
    notifyListeners();
  }

  void _clearData() {
    conversations.clear();
    unread.clear();
    onlineUsers.clear();
    activePeer = null;
  }

  // ---------------------------------------------------------------------------
  // Mensajes entrantes
  // ---------------------------------------------------------------------------

  void _handleIncoming(Map<String, dynamic> data) {
    final tipo = data['tipo'];
    switch (tipo) {
      case 'sistema':
        final phone = data['telefono'];
        if (phone is String && phone.isNotEmpty) myPhone = phone;
        _updateOnline(data);
        final convs = data['conversaciones'];
        if (convs is Map) {
          convs.forEach((peer, list) {
            if (list is List) _mergeHistory(peer.toString(), list);
          });
        }
        break;
      case 'usuario_conectado':
      case 'usuario_desconectado':
        _updateOnline(data);
        break;
      case 'mensaje_enviado':
        final msg = ChatMessage.fromJson(
          data,
          status: data['entregado'] == true ? SendStatus.delivered : SendStatus.sent,
        );
        _awaitingAck.remove(msg.clientId);
        _upsert(msg.destinatario, msg);
        break;
      case 'mensaje_recibido':
        final msg = ChatMessage.fromJson(data);
        final isNew = _upsert(msg.remitente, msg);
        if (isNew && activePeer != msg.remitente) {
          unread[msg.remitente] = (unread[msg.remitente] ?? 0) + 1;
          _events.add(ChatEvent('nuevo_mensaje', 'Nuevo mensaje de ${formatPhone(msg.remitente)}', chatMessage: msg));
        }
        break;
      case 'historial':
        final peer = data['con'];
        final list = data['mensajes'];
        if (peer is String && list is List) _mergeHistory(peer, list);
        break;
      case 'error':
        // El servidor procesa en orden: el error corresponde al primer envío sin confirmar.
        if (_awaitingAck.isNotEmpty) {
          final failed = _awaitingAck.removeAt(0);
          for (final list in conversations.values) {
            list.removeWhere((m) => m.clientId == failed && m.isPending);
          }
        }
        _events.add(ChatEvent('error', (data['mensaje'] ?? 'Error del servidor').toString()));
        break;
      default:
        // 'info' (destinatario desconectado) se refleja con un solo check; 'pong' se ignora.
        return;
    }
    notifyListeners();
  }

  void _updateOnline(Map<String, dynamic> data) {
    final list = data['usuarios_online'];
    if (list is List) onlineUsers = list.map((e) => e.toString()).toSet();
  }

  /// Inserta o actualiza un mensaje. Devuelve true si es nuevo.
  bool _upsert(String peer, ChatMessage msg) {
    final list = conversations.putIfAbsent(peer, () => []);
    final idx = list.indexWhere((m) =>
        m.id == msg.id || (msg.clientId != null && m.clientId == msg.clientId));
    if (idx >= 0) {
      list[idx] = msg;
      return false;
    }
    list.add(msg);
    list.sort((a, b) => a.timestamp.compareTo(b.timestamp));
    return true;
  }

  /// Sustituye el historial con el del servidor, conservando los envíos pendientes.
  void _mergeHistory(String peer, List raw) {
    final server = raw
        .whereType<Map>()
        .map((m) => ChatMessage.fromJson(Map<String, dynamic>.from(m)))
        .toList();
    final serverClientIds = server.map((m) => m.clientId).whereType<String>().toSet();
    final pending = (conversations[peer] ?? [])
        .where((m) => m.isPending && !serverClientIds.contains(m.clientId))
        .toList();
    conversations[peer] = [...server, ...pending];
  }

  // ---------------------------------------------------------------------------
  // Envío
  // ---------------------------------------------------------------------------

  /// Devuelve un mensaje de error si no se puede enviar, o null si se envió/encoló.
  String? sendMessage(String peer, String text) {
    final me = myPhone;
    final texto = text.trim();
    if (me == null) return 'No hay sesión iniciada.';
    if (texto.isEmpty) return null;
    if (texto.length > 5000) return 'El mensaje supera los 5000 caracteres.';
    if (peer == me) return 'No puedes enviarte mensajes a ti mismo.';

    final clientId = 'c${DateTime.now().microsecondsSinceEpoch}${Random().nextInt(1 << 20)}';
    final pending = ChatMessage.pending(
      clientId: clientId,
      remitente: me,
      destinatario: peer,
      texto: texto,
    );
    conversations.putIfAbsent(peer, () => []).add(pending);
    if (isConnected) _sendPending(pending);
    notifyListeners();
    return null;
  }

  void _sendPending(ChatMessage m) {
    if (_send({
      'tipo': 'mensaje',
      'destinatario': m.destinatario,
      'texto': m.texto,
      'client_id': m.clientId,
    })) {
      _awaitingAck.add(m.clientId!);
    }
  }

  /// Reenvía los mensajes escritos mientras no había conexión.
  void _flushPending() {
    for (final list in conversations.values) {
      for (final m in list.where((m) => m.isPending).toList()) {
        if (!_awaitingAck.contains(m.clientId)) _sendPending(m);
      }
    }
  }

  void requestHistory(String peer) => _send({'tipo': 'historial', 'destinatario': peer});

  bool _send(Map<String, dynamic> payload) {
    final ch = _channel;
    if (ch == null) return false;
    try {
      ch.sink.add(jsonEncode(payload));
      return true;
    } catch (_) {
      return false;
    }
  }

  // ---------------------------------------------------------------------------
  // Lectura
  // ---------------------------------------------------------------------------

  void openConversation(String peer) {
    activePeer = peer;
    unread.remove(peer);
    notifyListeners();
  }

  void closeConversation(String peer) {
    if (activePeer == peer) activePeer = null;
  }
}
