package com.ryx.history.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Paleta tomada del logo: dorado, naranja y verde sobre un marrón casi negro
val RyxInk = Color(0xFF14100C)
val RyxSurface = Color(0xFF1E1812)
val RyxRaised = Color(0xFF2A2118)
val RyxGold = Color(0xFFFFC400)
val RyxOrange = Color(0xFFFF8A00)
val RyxGreen = Color(0xFF1FD34A)
val RyxCream = Color(0xFFFFF6DC)
val RyxMuted = Color(0xFFB8A98A)
val RyxRed = Color(0xFFFF5A4D)

private val scheme = darkColorScheme(
    primary = RyxGold, onPrimary = RyxInk,
    secondary = RyxGreen, onSecondary = RyxInk,
    tertiary = RyxOrange, onTertiary = RyxInk,
    background = RyxInk, onBackground = RyxCream,
    surface = RyxSurface, onSurface = RyxCream,
    surfaceVariant = RyxRaised, onSurfaceVariant = RyxMuted,
    outline = Color(0xFF5A4A33),
    error = RyxRed, onError = Color.White
)

@Composable
fun RyxTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = scheme, content = content)
}
