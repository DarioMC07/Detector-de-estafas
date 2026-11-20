import 'signal_item.dart';

class AnalyzeResult {
  final String categoria;
  final String nivel;
  final bool incertidumbre;
  final String? avisoIncertidumbre;
  final String explicacion;
  final List<SignalItem> senales;
  final List<String> recomendaciones;
  final bool datosDemostrativos;

  AnalyzeResult({
    required this.categoria,
    required this.nivel,
    required this.incertidumbre,
    this.avisoIncertidumbre,
    required this.explicacion,
    required this.senales,
    required this.recomendaciones,
    required this.datosDemostrativos,
  });

  factory AnalyzeResult.fromJson(Map<String, dynamic> json) {
    var rawSignals = json['senales'] as List? ?? [];
    var rawRecs = json['recomendaciones'] as List? ?? [];

    return AnalyzeResult(
      categoria: json['categoria'] ?? '',
      nivel: json['nivel'] ?? 'bajo',
      incertidumbre: json['incertidumbre'] ?? false,
      avisoIncertidumbre: json['aviso_incertidumbre'],
      explicacion: json['explicacion'] ?? '',
      senales: rawSignals
          .map((s) => SignalItem.fromJson(Map<String, dynamic>.from(s)))
          .toList(),
      recomendaciones: rawRecs.map((r) => r.toString()).toList(),
      datosDemostrativos: json['datos_demostrativos'] ?? false,
    );
  }
}
