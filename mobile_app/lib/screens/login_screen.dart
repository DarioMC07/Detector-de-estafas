import 'package:flutter/material.dart';

import '../config.dart';
import '../services/api_service.dart';
import '../services/chat_websocket_service.dart';
import '../theme.dart';
import '../utils/phone.dart';
import 'chat_list_screen.dart';

class LoginScreen extends StatefulWidget {
  /// Si hay un número guardado, intenta entrar automáticamente.
  final bool autoLogin;
  final String? initialError;

  const LoginScreen({super.key, this.autoLogin = false, this.initialError});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _phoneController = TextEditingController(text: AppConfig.savedPhone ?? '');
  final _service = ChatWebSocketService();
  bool _isLoading = false;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _errorMessage = widget.initialError;
    if (widget.autoLogin && AppConfig.savedPhone != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _login());
    }
  }

  @override
  void dispose() {
    _phoneController.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    final raw = _phoneController.text.trim();
    if (raw.isEmpty) {
      setState(() => _errorMessage = 'Ingresa tu número telefónico.');
      return;
    }
    if (normalizePhone(raw) == null) {
      setState(() => _errorMessage = 'Número inválido. Usa 8 dígitos (77004938) o formato internacional (+59177004938).');
      return;
    }
    FocusScope.of(context).unfocus();
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      await _service.login(raw);
      if (!mounted) return;
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (_) => const ChatListScreen()),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _isLoading = false;
        _errorMessage = e.toString();
      });
    }
  }

  Future<void> _openServerDialog() async {
    final result = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => const _ServerSheet(),
    );
    if (result != null && mounted) {
      setState(() {});
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Servidor guardado: $result')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final normalized = normalizePhone(_phoneController.text);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Center(
                    child: Container(
                      width: 84,
                      height: 84,
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          colors: [AppColors.accent.withAlpha(70), AppColors.accent.withAlpha(15)],
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                        ),
                        shape: BoxShape.circle,
                        border: Border.all(color: AppColors.accent.withAlpha(160), width: 1.5),
                      ),
                      child: const Icon(Icons.shield_outlined, color: AppColors.accent, size: 40),
                    ),
                  ),
                  const SizedBox(height: 22),
                  const Text(
                    'Mensaje Seguro',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: AppColors.text, fontSize: 30, fontWeight: FontWeight.w300, letterSpacing: -0.5),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Mensajería que te avisa cuando un mensaje\nparece una estafa.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: AppColors.textMuted, fontSize: 14, height: 1.4),
                  ),
                  const SizedBox(height: 36),
                  const Text('Tu número', style: TextStyle(color: AppColors.textMuted, fontSize: 13, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 8),
                  TextField(
                    controller: _phoneController,
                    keyboardType: TextInputType.phone,
                    enabled: !_isLoading,
                    style: const TextStyle(color: AppColors.text, fontSize: 18, letterSpacing: 0.5),
                    onChanged: (_) => setState(() {}),
                    onSubmitted: (_) => _login(),
                    decoration: const InputDecoration(
                      hintText: '77004938',
                      prefixIcon: Icon(Icons.phone_outlined, color: AppColors.textMuted),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    normalized != null
                        ? 'Entrarás como ${formatPhone(normalized)}'
                        : 'Sin prefijo se usa +591 (Bolivia). Para otro país escribe +54, +34…',
                    style: TextStyle(color: normalized != null ? AppColors.safe : AppColors.textFaint, fontSize: 12),
                  ),
                  if (_errorMessage != null) ...[
                    const SizedBox(height: 16),
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: AppColors.dangerBg,
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: AppColors.dangerBorder),
                      ),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Icon(Icons.error_outline, color: AppColors.danger, size: 18),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(_errorMessage!, style: const TextStyle(color: Color(0xFFFFC4C4), fontSize: 13, height: 1.35)),
                          ),
                        ],
                      ),
                    ),
                  ],
                  const SizedBox(height: 24),
                  SizedBox(
                    height: 52,
                    child: ElevatedButton(
                      onPressed: _isLoading ? null : _login,
                      child: _isLoading
                          ? const SizedBox(
                              width: 22,
                              height: 22,
                              child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.onAccent),
                            )
                          : const Text('Entrar'),
                    ),
                  ),
                  const SizedBox(height: 28),
                  Center(
                    child: InkWell(
                      borderRadius: BorderRadius.circular(10),
                      onTap: _isLoading ? null : _openServerDialog,
                      child: Container(
                        padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 14),
                        decoration: BoxDecoration(
                          color: AppColors.surface,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: AppColors.border),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.dns_outlined, size: 16, color: AppColors.accent),
                            const SizedBox(width: 8),
                            Flexible(
                              child: Text(
                                AppConfig.baseUrl,
                                style: const TextStyle(color: AppColors.textMuted, fontSize: 12),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            const SizedBox(width: 10),
                            const Text('Cambiar', style: TextStyle(color: AppColors.accent, fontSize: 12, fontWeight: FontWeight.bold)),
                          ],
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Hoja para cambiar y probar la dirección del servidor.
class _ServerSheet extends StatefulWidget {
  const _ServerSheet();

  @override
  State<_ServerSheet> createState() => _ServerSheetState();
}

class _ServerSheetState extends State<_ServerSheet> {
  final _controller = TextEditingController(text: AppConfig.baseUrl);
  bool _testing = false;
  String? _result;
  bool _ok = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _test() async {
    final url = AppConfig.normalizeServerUrl(_controller.text);
    if (url == null) {
      setState(() {
        _result = 'Dirección inválida.';
        _ok = false;
      });
      return;
    }
    _controller.text = url;
    setState(() {
      _testing = true;
      _result = null;
    });
    final error = await ApiService().checkServer(url);
    if (!mounted) return;
    setState(() {
      _testing = false;
      _ok = error == null;
      _result = error ?? 'Conexión correcta con el servidor.';
    });
  }

  Future<void> _save() async {
    final url = AppConfig.normalizeServerUrl(_controller.text);
    if (url == null) {
      setState(() {
        _result = 'Dirección inválida.';
        _ok = false;
      });
      return;
    }
    await AppConfig.saveServer(url);
    if (mounted) Navigator.pop(context, url);
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 12, 20, MediaQuery.of(context).viewInsets.bottom + 24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Center(
            child: Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(color: AppColors.border, borderRadius: BorderRadius.circular(2)),
            ),
          ),
          const SizedBox(height: 18),
          const Text('Servidor', style: TextStyle(color: AppColors.text, fontSize: 18, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          const Text(
            'Misma red Wi-Fi: la IP de tu PC, por ejemplo 192.168.0.17:8000.\n'
            'Fuera de casa: el enlace https de Cloudflare.',
            style: TextStyle(color: AppColors.textMuted, fontSize: 13, height: 1.4),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _controller,
            keyboardType: TextInputType.url,
            autocorrect: false,
            style: const TextStyle(color: AppColors.text),
            decoration: const InputDecoration(
              hintText: 'http://192.168.0.17:8000',
              prefixIcon: Icon(Icons.link, color: AppColors.textMuted),
            ),
          ),
          if (_result != null) ...[
            const SizedBox(height: 12),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(_ok ? Icons.check_circle_outline : Icons.error_outline,
                    size: 18, color: _ok ? AppColors.safe : AppColors.danger),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(_result!,
                      style: TextStyle(color: _ok ? AppColors.safe : const Color(0xFFFFC4C4), fontSize: 13, height: 1.35)),
                ),
              ],
            ),
          ],
          const SizedBox(height: 18),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: _testing ? null : _test,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.accent,
                    side: const BorderSide(color: AppColors.border),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                  child: _testing
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Text('Probar'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: ElevatedButton(onPressed: _save, child: const Text('Guardar')),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
