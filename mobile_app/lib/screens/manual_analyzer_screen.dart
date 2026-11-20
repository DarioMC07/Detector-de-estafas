import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/analyze_result.dart';
import '../services/api_service.dart';
import '../theme.dart';

class ManualAnalyzerScreen extends StatefulWidget {
  const ManualAnalyzerScreen({super.key});

  @override
  State<ManualAnalyzerScreen> createState() => _ManualAnalyzerScreenState();
}

class _ManualAnalyzerScreenState extends State<ManualAnalyzerScreen> {
  final _textController = TextEditingController();
  final _apiService = ApiService();
  bool _isLoading = false;
  AnalyzeResult? _result;
  String? _error;

  @override
  void initState() {
    super.initState();
    _textController.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _textController.dispose();
    super.dispose();
  }

  Future<void> _paste() async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    final text = data?.text;
    if (text != null && text.isNotEmpty) {
      _textController.text = text;
      _textController.selection = TextSelection.collapsed(offset: text.length);
    }
  }

  Future<void> _analyze() async {
    final text = _textController.text.trim();
    if (text.isEmpty) return;
    FocusScope.of(context).unfocus();

    setState(() {
      _isLoading = true;
      _error = null;
      _result = null;
    });

    try {
      final res = await _apiService.analizarTexto(text);
      if (!mounted) return;
      setState(() {
        _result = res;
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString().replaceFirst('Exception: ', '');
        _isLoading = false;
      });
    }
  }

  void _clear() {
    _textController.clear();
    setState(() {
      _result = null;
      _error = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final hasText = _textController.text.trim().isNotEmpty;
    return Scaffold(
      appBar: AppBar(title: const Text('Analizar un mensaje')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              '¿Te llegó un mensaje dudoso por SMS, WhatsApp o correo? Pégalo aquí para evaluarlo.',
              style: TextStyle(color: AppColors.textMuted, fontSize: 14, height: 1.4),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _textController,
              minLines: 5,
              maxLines: 10,
              maxLength: 5000,
              style: const TextStyle(color: AppColors.text, height: 1.4),
              decoration: const InputDecoration(hintText: 'Pega el mensaje aquí…'),
            ),
            const SizedBox(height: 4),
            Row(
              children: [
                TextButton.icon(
                  onPressed: _isLoading ? null : _paste,
                  icon: const Icon(Icons.content_paste, size: 18),
                  label: const Text('Pegar'),
                ),
                if (hasText || _result != null)
                  TextButton.icon(
                    onPressed: _isLoading ? null : _clear,
                    icon: const Icon(Icons.clear, size: 18),
                    label: const Text('Limpiar'),
                  ),
                const Spacer(),
                ElevatedButton(
                  onPressed: _isLoading || !hasText ? null : _analyze,
                  child: _isLoading
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.onAccent),
                        )
                      : const Text('Analizar'),
                ),
              ],
            ),
            if (_error != null) ...[
              const SizedBox(height: 20),
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: AppColors.dangerBg,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppColors.dangerBorder),
                ),
                child: Text(_error!, style: const TextStyle(color: Color(0xFFFFC4C4))),
              ),
            ],
            if (_result != null) ...[
              const SizedBox(height: 20),
              _buildResultCard(_result!),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildResultCard(AnalyzeResult r) {
    final isFraud = r.nivel == 'alto';
    final isUncertain = r.incertidumbre;

    final Color bg = isFraud ? AppColors.dangerBg : (isUncertain ? AppColors.warningBg : AppColors.safeBg);
    final Color border = isFraud ? AppColors.dangerBorder : (isUncertain ? AppColors.warningBorder : AppColors.safeBorder);
    final Color fg = isFraud ? const Color(0xFFFFB4B4) : (isUncertain ? AppColors.warning : AppColors.safe);
    final IconData icon = isFraud ? Icons.gpp_maybe : (isUncertain ? Icons.warning_amber_rounded : Icons.verified_user_outlined);

    return Container(
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(color: bg, border: Border(bottom: BorderSide(color: border))),
            child: Row(
              children: [
                Icon(icon, color: fg, size: 28),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(r.categoria, style: TextStyle(color: fg, fontWeight: FontWeight.bold, fontSize: 17)),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (r.avisoIncertidumbre != null) ...[
                  Text(r.avisoIncertidumbre!, style: const TextStyle(color: AppColors.warning, fontSize: 13, height: 1.4)),
                  const SizedBox(height: 12),
                ],
                Text(r.explicacion, style: const TextStyle(color: Color(0xFFCCC7BE), fontSize: 14, height: 1.45)),
                if (r.senales.isNotEmpty) ...[
                  const SizedBox(height: 18),
                  const Text('Señales detectadas', style: TextStyle(color: AppColors.accent, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 8),
                  ...r.senales.map((s) => Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Padding(
                              padding: EdgeInsets.only(top: 2),
                              child: Icon(Icons.flag_outlined, size: 16, color: AppColors.accent),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(s.titulo, style: const TextStyle(color: AppColors.text, fontWeight: FontWeight.w600, fontSize: 13)),
                                  Text(s.descripcion, style: const TextStyle(color: AppColors.textMuted, fontSize: 12, height: 1.35)),
                                ],
                              ),
                            ),
                          ],
                        ),
                      )),
                ],
                if (r.recomendaciones.isNotEmpty) ...[
                  const SizedBox(height: 14),
                  const Text('Qué hacer', style: TextStyle(color: AppColors.accent, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 8),
                  ...r.recomendaciones.map((rec) => Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('•  ', style: TextStyle(color: AppColors.textMuted)),
                            Expanded(
                              child: Text(rec, style: const TextStyle(color: AppColors.textMuted, fontSize: 13, height: 1.35)),
                            ),
                          ],
                        ),
                      )),
                ],
                const SizedBox(height: 10),
                const Text(
                  'Esta evaluación es orientativa y puede cometer errores.',
                  style: TextStyle(color: AppColors.textFaint, fontSize: 11, fontStyle: FontStyle.italic),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
