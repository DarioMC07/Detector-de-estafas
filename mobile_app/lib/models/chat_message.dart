import '../utils/fraud_labels.dart';
import 'signal_item.dart';

/// Estado de envío de un mensaje propio.
enum SendStatus { sending, sent, delivered }

/// Modelo de mensaje de chat con datos del análisis de seguridad
class ChatMessage {
  final String id;
  final String? clientId;
  final String remitente;
  final String destinatario;
  final String texto;
  final double timestamp;
  final SendStatus status;

  // Datos de seguridad devueltos por el backend
  final String etiquetaModelo; // 'legitimo', 'fraudulento', 'desconocido'
  final String nivel; // 'bajo', 'medio', 'alto'
  final bool incertidumbre;
  final String? avisoIncertidumbre;
  final List<SignalItem> senales;
  final List<String> recomendaciones;

  // Decisión táctica del motor Laya (Nivel 2)
  final String accionTactica; // 'PERMITIR', 'ADVERTIR', 'BLOQUEAR_ENLACES'
  final String categoriaFraude; // 'CONVERSACION_GENUINA', 'PHISHING_BANCARIO', ...

  ChatMessage({
    required this.id,
    this.clientId,
    required this.remitente,
    required this.destinatario,
    required this.texto,
    required this.timestamp,
    this.status = SendStatus.sent,
    this.etiquetaModelo = 'legitimo',
    this.nivel = 'bajo',
    this.incertidumbre = false,
    this.avisoIncertidumbre,
    this.senales = const [],
    this.recomendaciones = const [],
    this.accionTactica = 'PERMITIR',
    this.categoriaFraude = 'CONVERSACION_GENUINA',
  });

  bool get linksBlocked => accionTactica == 'BLOQUEAR_ENLACES';
  bool get hasRiskyLink => senales.any((s) => riskyLinkSignals.contains(s.codigo));
  bool get isFraud => etiquetaModelo == 'fraudulento';
  bool get isUnknown => etiquetaModelo == 'desconocido';
  bool get isSafe => etiquetaModelo == 'legitimo' && !incertidumbre;
  bool get isPending => status == SendStatus.sending;

  DateTime get dateTime =>
      DateTime.fromMillisecondsSinceEpoch((timestamp * 1000).toInt());

  /// Mensaje provisional que se muestra al instante mientras el servidor responde.
  factory ChatMessage.pending({
    required String clientId,
    required String remitente,
    required String destinatario,
    required String texto,
  }) {
    return ChatMessage(
      id: clientId,
      clientId: clientId,
      remitente: remitente,
      destinatario: destinatario,
      texto: texto,
      timestamp: DateTime.now().millisecondsSinceEpoch / 1000,
      status: SendStatus.sending,
    );
  }

  factory ChatMessage.fromJson(Map<String, dynamic> json, {SendStatus status = SendStatus.sent}) {
    final rawSignals = json['senales'] as List? ?? [];
    final rawRecs = json['recomendaciones'] as List? ?? [];

    return ChatMessage(
      id: (json['id'] ?? '').toString(),
      clientId: json['client_id'] as String?,
      remitente: (json['remitente'] ?? '').toString(),
      destinatario: (json['destinatario'] ?? '').toString(),
      texto: (json['texto'] ?? '').toString(),
      timestamp: (json['timestamp'] as num?)?.toDouble() ?? 0.0,
      status: status,
      etiquetaModelo: (json['etiqueta_modelo'] ?? 'legitimo').toString(),
      nivel: (json['nivel'] ?? 'bajo').toString(),
      incertidumbre: json['incertidumbre'] == true,
      avisoIncertidumbre: json['aviso_incertidumbre'] as String?,
      senales: rawSignals
          .map((s) => SignalItem.fromJson(Map<String, dynamic>.from(s as Map)))
          .toList(),
      recomendaciones: rawRecs.map((r) => r.toString()).toList(),
      accionTactica: (json['accion_tactica'] ?? 'PERMITIR').toString(),
      categoriaFraude: (json['categoria_fraude'] ?? 'CONVERSACION_GENUINA').toString(),
    );
  }

  ChatMessage withStatus(SendStatus newStatus) => ChatMessage(
        id: id,
        clientId: clientId,
        remitente: remitente,
        destinatario: destinatario,
        texto: texto,
        timestamp: timestamp,
        status: newStatus,
        etiquetaModelo: etiquetaModelo,
        nivel: nivel,
        incertidumbre: incertidumbre,
        avisoIncertidumbre: avisoIncertidumbre,
        senales: senales,
        recomendaciones: recomendaciones,
        accionTactica: accionTactica,
        categoriaFraude: categoriaFraude,
      );
}
