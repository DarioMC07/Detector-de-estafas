/// Señal detectada por las reglas del modelo
class SignalItem {
  final String codigo;
  final String titulo;
  final String descripcion;

  SignalItem({
    required this.codigo,
    required this.titulo,
    required this.descripcion,
  });

  factory SignalItem.fromJson(Map<String, dynamic> json) {
    return SignalItem(
      codigo: json['codigo'] ?? '',
      titulo: json['titulo'] ?? '',
      descripcion: json['descripcion'] ?? '',
    );
  }

  Map<String, dynamic> toJson() => {
    'codigo': codigo,
    'titulo': titulo,
    'descripcion': descripcion,
  };
}
