import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

/// Configuración de conexión hacia la API de FastAPI.
///
/// La dirección del servidor, el número y el token del dispositivo se guardan
/// en el teléfono para no tener que escribirlos cada vez.
class AppConfig {
  /// Valor inicial. Cámbialo en la pantalla de inicio (Ajustes de servidor):
  /// - Celular en la misma red Wi-Fi: 'http://192.168.0.17:8000' (IP de tu PC)
  /// - Emulador Android: 'http://10.0.2.2:8000'
  /// - Internet con Cloudflare Tunnel: 'https://tu-subdominio.trycloudflare.com'
  static const defaultBaseUrl = 'http://192.168.0.17:8000';

  static String baseUrl = defaultBaseUrl;
  static String? savedPhone;
  static String deviceToken = '';

  static const _kServer = 'server_url';
  static const _kPhone = 'phone';
  static const _kToken = 'device_token';

  static String get wsUrl {
    if (baseUrl.startsWith('https://')) {
      return baseUrl.replaceFirst('https://', 'wss://');
    }
    return baseUrl.replaceFirst('http://', 'ws://');
  }

  /// Corrige direcciones escritas a mano: añade http:// y quita la barra final.
  /// "192.168.0.17:8000/" → "http://192.168.0.17:8000".
  static String? normalizeServerUrl(String raw) {
    var url = raw.trim();
    if (url.isEmpty) return null;
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      final isTunnel = url.contains('trycloudflare.com') || url.contains('ngrok');
      url = '${isTunnel ? 'https' : 'http'}://$url';
    }
    while (url.endsWith('/')) {
      url = url.substring(0, url.length - 1);
    }
    final uri = Uri.tryParse(url);
    if (uri == null || uri.host.isEmpty) return null;
    return url;
  }

  static Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    baseUrl = prefs.getString(_kServer) ?? defaultBaseUrl;
    savedPhone = prefs.getString(_kPhone);
    var token = prefs.getString(_kToken);
    if (token == null || token.length < 16) {
      final rnd = Random.secure();
      token = List.generate(32, (_) => rnd.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
      await prefs.setString(_kToken, token);
    }
    deviceToken = token;
  }

  static Future<void> saveServer(String url) async {
    baseUrl = url;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kServer, url);
  }

  static Future<void> savePhone(String? phone) async {
    savedPhone = phone;
    final prefs = await SharedPreferences.getInstance();
    if (phone == null) {
      await prefs.remove(_kPhone);
    } else {
      await prefs.setString(_kPhone, phone);
    }
  }
}
