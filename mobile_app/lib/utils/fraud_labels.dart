/// Textos en español para los campos del motor de decisión (Laya) del backend.
library;

const Set<String> riskyLinkSignals = {'enlace_inseguro', 'enlace_sospechoso', 'enlace_suplantacion'};

String categoriaLabel(String categoria) {
  switch (categoria) {
    case 'PHISHING_BANCARIO':
      return 'Robo de datos o claves';
    case 'SUPLANTACION_IDENTIDAD':
      return 'Suplantación de identidad';
    case 'PREMIO_FALSO':
      return 'Premio falso';
    case 'OTRO_FRAUDE':
      return 'Otro tipo de fraude';
    default:
      return '';
  }
}

String? accionLabel(String accion) {
  switch (accion) {
    case 'BLOQUEAR_ENLACES':
      return 'No abras los enlaces de este mensaje';
    case 'ADVERTIR':
      return 'Revisa con calma antes de responder';
    default:
      return null;
  }
}

String shortSignalLabel(String code, String title) {
  const names = {
    'urgencia': 'Urgencia',
    'credenciales': 'Pide claves',
    'enlace': 'Enlace',
    'enlace_inseguro': 'Enlace http',
    'enlace_sospechoso': 'Enlace sospechoso',
    'enlace_suplantacion': 'Enlace falso',
    'dinero': 'Dinero',
    'premio': 'Premio',
    'suplantacion': 'Suplantación',
  };
  return names[code] ?? (title.isNotEmpty ? title : code);
}
