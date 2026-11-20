import 'package:flutter/material.dart';

/// Paleta de la app (tema oscuro con acento dorado).
class AppColors {
  static const background = Color(0xFF0B0C0E);
  static const surface = Color(0xFF141518);
  static const surfaceHigh = Color(0xFF1C1E22);
  static const border = Color(0xFF2B2D33);
  static const accent = Color(0xFFD9BD87);
  static const onAccent = Color(0xFF0B0C0E);
  static const text = Color(0xFFEEEAE3);
  static const textMuted = Color(0xFF9A968F);
  static const textFaint = Color(0xFF66635D);

  static const bubbleMine = Color(0xFF2B4A3A);
  static const bubbleOther = Color(0xFF1E2024);

  static const online = Color(0xFF6FD39A);
  static const danger = Color(0xFFFF8A8A);
  static const dangerBg = Color(0xFF3A1A1A);
  static const dangerBorder = Color(0xFF8B2B2B);
  static const warning = Color(0xFFF1DFB8);
  static const warningBg = Color(0xFF3A3018);
  static const warningBorder = Color(0xFF8B6E22);
  static const safe = Color(0xFF94D9B0);
  static const safeBg = Color(0xFF1A2E22);
  static const safeBorder = Color(0xFF2A5E44);
}

ThemeData buildAppTheme() {
  final base = ThemeData(
    brightness: Brightness.dark,
    useMaterial3: true,
    colorScheme: const ColorScheme.dark(
      primary: AppColors.accent,
      onPrimary: AppColors.onAccent,
      secondary: AppColors.accent,
      surface: AppColors.surface,
      onSurface: AppColors.text,
      error: AppColors.danger,
    ),
  );
  return base.copyWith(
    scaffoldBackgroundColor: AppColors.background,
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.surface,
      foregroundColor: AppColors.text,
      elevation: 0,
      scrolledUnderElevation: 0,
      titleTextStyle: TextStyle(color: AppColors.text, fontSize: 18, fontWeight: FontWeight.w600),
    ),
    snackBarTheme: const SnackBarThemeData(
      backgroundColor: AppColors.surfaceHigh,
      contentTextStyle: TextStyle(color: AppColors.text),
      behavior: SnackBarBehavior.floating,
    ),
    dialogTheme: const DialogThemeData(backgroundColor: AppColors.surface),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surface,
      hintStyle: const TextStyle(color: AppColors.textFaint),
      labelStyle: const TextStyle(color: AppColors.textMuted),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.accent, width: 1.5),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: AppColors.accent,
        foregroundColor: AppColors.onAccent,
        disabledBackgroundColor: AppColors.accent.withAlpha(90),
        textStyle: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 20),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(foregroundColor: AppColors.accent),
    ),
    floatingActionButtonTheme: const FloatingActionButtonThemeData(
      backgroundColor: AppColors.accent,
      foregroundColor: AppColors.onAccent,
    ),
    dividerColor: AppColors.border,
  );
}
