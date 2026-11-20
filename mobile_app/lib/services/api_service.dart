import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config.dart';
import '../models/analyze_result.dart';

class ApiService {
  static const _timeout = Duration(seconds: 12);

  Future<AnalyzeResult> analizarTexto(String texto) async {
    final url = Uri.parse('${AppConfig.baseUrl}/analizar');
    final http.Response response;
    try {
      response = await http
          .post(
            url,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'texto': texto}),
          )
          .timeout(_timeout);
    } on TimeoutException {
      throw Exception('El servidor no respondió a tiempo (${AppConfig.baseUrl}).');
    } catch (_) {
      throw Exception('No se pudo conectar con el servidor (${AppConfig.baseUrl}).');
    }

    if (response.statusCode == 200) {
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      return AnalyzeResult.fromJson(Map<String, dynamic>.from(decoded as Map));
    }
    String detail = 'Error al analizar el mensaje (${response.statusCode})';
    try {
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      if (decoded['detail'] != null) detail = decoded['detail'].toString();
    } catch (_) {}
    throw Exception(detail);
  }

  /// Comprueba si el servidor responde. Devuelve null si todo va bien o un mensaje de error.
  Future<String?> checkServer(String baseUrl) async {
    try {
      final response = await http.get(Uri.parse('$baseUrl/estado')).timeout(const Duration(seconds: 6));
      if (response.statusCode == 200) {
        final decoded = jsonDecode(utf8.decode(response.bodyBytes));
        if (decoded['modelo_disponible'] == false) {
          return 'El servidor responde, pero el modelo no está entrenado (ejecuta training.train).';
        }
        return null;
      }
      return 'El servidor respondió con el código ${response.statusCode}.';
    } on TimeoutException {
      return 'Sin respuesta de $baseUrl. ¿El servidor se inició con --host 0.0.0.0 y el teléfono está en la misma red Wi-Fi?';
    } catch (_) {
      return 'No se pudo conectar con $baseUrl.';
    }
  }
}
