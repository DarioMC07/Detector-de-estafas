import 'package:flutter/material.dart';

import 'config.dart';
import 'screens/login_screen.dart';
import 'services/chat_websocket_service.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AppConfig.load();
  runApp(const MensajeSeguroApp());
}

class MensajeSeguroApp extends StatefulWidget {
  const MensajeSeguroApp({super.key});

  @override
  State<MensajeSeguroApp> createState() => _MensajeSeguroAppState();
}

class _MensajeSeguroAppState extends State<MensajeSeguroApp> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Android suele cortar la conexión en segundo plano: reconectar al volver.
    if (state == AppLifecycleState.resumed) {
      ChatWebSocketService().reconnectNow();
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Mensaje Seguro',
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: const LoginScreen(autoLogin: true),
    );
  }
}
