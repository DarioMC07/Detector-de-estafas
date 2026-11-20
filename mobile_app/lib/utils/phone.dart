/// Normalización de números igual a la del servidor (app/chat_manager.py).
///
/// Así la app identifica correctamente sus propios mensajes y las conversaciones
/// aunque el número se escriba con espacios, guiones o sin prefijo.
final _phoneRe = RegExp(r'^\+\d{7,15}$');

/// Devuelve el número normalizado (ej. "+59177004938") o null si no es válido.
String? normalizePhone(String raw) {
  var cleaned = raw.trim().replaceAll(RegExp(r'[\s\-().]'), '');
  if (cleaned.isEmpty) return null;
  if (!cleaned.startsWith('+')) {
    final digitsOnly = RegExp(r'^\d+$').hasMatch(cleaned);
    if (digitsOnly && cleaned.length == 8) {
      cleaned = '+591$cleaned';
    } else if (digitsOnly && cleaned.length >= 7 && cleaned.length <= 15) {
      cleaned = '+$cleaned';
    }
  }
  return _phoneRe.hasMatch(cleaned) ? cleaned : null;
}

/// Formato legible: "+591 7700 4938".
String formatPhone(String phone) {
  if (phone.startsWith('+591') && phone.length == 12) {
    return '+591 ${phone.substring(4, 8)} ${phone.substring(8)}';
  }
  return phone;
}

/// Dos últimos dígitos para el avatar.
String phoneInitials(String phone) =>
    phone.length >= 2 ? phone.substring(phone.length - 2) : '#';
