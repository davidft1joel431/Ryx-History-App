package com.ryx.history.ui

import android.content.Context
import android.content.Intent
import android.provider.Settings
import androidx.compose.animation.Crossfade
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationManagerCompat
import androidx.core.graphics.drawable.toBitmap
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ryx.history.R
import com.ryx.history.data.NotificationEntity
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

fun isListenerEnabled(ctx: Context): Boolean =
    NotificationManagerCompat.getEnabledListenerPackages(ctx).contains(ctx.packageName)

@Composable
fun AppRoot(vm: AppViewModel) {
    val ctx = LocalContext.current
    val loggedIn by vm.loggedIn.collectAsStateWithLifecycle()
    val msg by vm.message.collectAsStateWithLifecycle()
    var listenerOn by remember { mutableStateOf(isListenerEnabled(ctx)) }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { listenerOn = isListenerEnabled(ctx) }

    val snack = remember { SnackbarHostState() }
    LaunchedEffect(msg) {
        msg?.let {
            snack.showSnackbar(it)
            vm.message.value = null
        }
    }

    // Cambio de pantalla con un fundido corto en vez de un salto seco.
    var showProfile by remember { mutableStateOf(false) }
    val stage = when {
        !loggedIn -> "login"
        !listenerOn -> "permiso"
        showProfile -> "perfil"
        else -> "historial"
    }
    LaunchedEffect(stage) { if (stage == "historial" || stage == "perfil") vm.loadProfile() }

    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Box(Modifier.fillMaxSize()) {
            Crossfade(targetState = stage, animationSpec = tween(420), label = "pantalla") { actual ->
                when (actual) {
                    "login" -> LoginScreen(vm)
                    "permiso" -> PermissionScreen(onUseAnotherAccount = { vm.logout() })
                    "perfil" -> ProfileScreen(vm, onBack = { showProfile = false })
                    else -> HistoryScreen(vm, onOpenProfile = { showProfile = true })
                }
            }
            SnackbarHost(snack, Modifier.align(Alignment.BottomCenter).padding(12.dp))
        }
    }
}

/* ---------------------------------- Login ---------------------------------- */

@Composable
fun LoginScreen(vm: AppViewModel) {
    val ctx = LocalContext.current
    val busy by vm.busy.collectAsStateWithLifecycle()
    var register by remember { mutableStateOf(false) }
    var name by remember { mutableStateOf("") }
    var email by remember { mutableStateOf("") }
    var pass by remember { mutableStateOf("") }

    // Aparición del logo y resplandor dorado que respira detrás del formulario.
    val intro = remember { Animatable(0f) }
    LaunchedEffect(Unit) { intro.animateTo(1f, tween(700, easing = LinearOutSlowInEasing)) }
    val glowTransition = rememberInfiniteTransition(label = "resplandor")
    val glow by glowTransition.animateFloat(
        initialValue = 0.35f, targetValue = 0.95f,
        animationSpec = infiniteRepeatable(
            tween(4200, easing = FastOutSlowInEasing), RepeatMode.Reverse
        ),
        label = "glow"
    )

    Box(Modifier.fillMaxSize()) {
    Box(
        Modifier.fillMaxSize().background(
            Brush.radialGradient(
                colors = listOf(RyxGold.copy(alpha = 0.16f * glow), Color.Transparent),
                radius = 950f
            )
        )
    )
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Image(
            painterResource(R.drawable.logo), contentDescription = "Ryx History",
            modifier = Modifier.fillMaxWidth(0.75f).graphicsLayer {
                alpha = intro.value
                val escala = 0.88f + 0.12f * intro.value
                scaleX = escala
                scaleY = escala
            },
            contentScale = ContentScale.FillWidth
        )
        Spacer(Modifier.height(8.dp))
        Text(
            if (register) "Crea tu cuenta" else "Inicia sesión",
            style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Black
        )
        Spacer(Modifier.height(16.dp))
        if (register) {
            OutlinedTextField(name, { name = it }, label = { Text("Nombre") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(8.dp))
        }
        OutlinedTextField(
            email, { email = it }, label = { Text("Correo electrónico") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email), modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            pass, { pass = it }, label = { Text(if (register) "Contraseña (mínimo 8 caracteres)" else "Contraseña") },
            singleLine = true, visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(16.dp))
        Button(
            onClick = { if (register) vm.register(email, pass, name) else vm.login(email, pass) },
            enabled = !busy && email.isNotBlank() && pass.isNotEmpty() && (!register || name.isNotBlank()),
            modifier = Modifier.fillMaxWidth().height(48.dp)
        ) {
            if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
            else Text(if (register) "Crear cuenta" else "Entrar", fontWeight = FontWeight.Bold)
        }
        TextButton(onClick = { register = !register }) {
            Text(if (register) "Ya tengo cuenta" else "Crear una cuenta nueva")
        }
        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            HorizontalDivider(Modifier.weight(1f))
            Text("  o  ", color = MaterialTheme.colorScheme.onSurfaceVariant)
            HorizontalDivider(Modifier.weight(1f))
        }
        OutlinedButton(
            onClick = { vm.startDiscord(ctx) }, enabled = !busy,
            modifier = Modifier.fillMaxWidth().height(48.dp)
        ) { Text("Continuar con Discord", fontWeight = FontWeight.Bold) }
    }
    }
}

/* ------------------------- Permiso de notificaciones ------------------------- */

@Composable
fun PermissionScreen(onUseAnotherAccount: () -> Unit) {
    val ctx = LocalContext.current
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Image(
            painterResource(R.drawable.logo), contentDescription = null,
            modifier = Modifier.fillMaxWidth(0.6f), contentScale = ContentScale.FillWidth
        )
        Spacer(Modifier.height(20.dp))
        Text("Falta un permiso", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Black)
        Spacer(Modifier.height(10.dp))
        Text(
            "Para guardar tu historial, Ryx History necesita acceso a las notificaciones. " +
                "Verás el texto de cada notificación que recibas (mensajes, códigos, avisos) y se enviará a tu cuenta.",
            textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(10.dp))
        Text(
            "Si Android muestra “Configuración restringida”, entra a Ajustes → Apps → Ryx History → menú ⋮ → " +
                "Permitir ajustes restringidos, y vuelve a intentarlo.",
            textAlign = TextAlign.Center, style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(22.dp))
        Button(
            onClick = { ctx.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) },
            modifier = Modifier.fillMaxWidth().height(48.dp)
        ) { Text("Dar acceso a notificaciones", fontWeight = FontWeight.Bold) }
        // Sin esto, quien entró con la cuenta equivocada queda atrapado en esta pantalla.
        TextButton(onClick = onUseAnotherAccount) { Text("Usar otra cuenta") }
    }
}

/* -------------------------------- Historial -------------------------------- */

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryScreen(vm: AppViewModel, onOpenProfile: () -> Unit) {
    val list by vm.list.collectAsStateWithLifecycle()
    val query by vm.query.collectAsStateWithLifecycle()
    val limit by vm.limit.collectAsStateWithLifecycle()
    val total by vm.total.collectAsStateWithLifecycle()
    val pending by vm.pending.collectAsStateWithLifecycle()
    var menu by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf<String?>(null) }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("Ryx History", fontWeight = FontWeight.Black, color = MaterialTheme.colorScheme.primary)
                        Text(
                            "$total guardadas · $pending sin enviar",
                            style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                },
                actions = {
                    IconButton(onClick = onOpenProfile) {
                        Icon(Icons.Default.Person, contentDescription = "Perfil")
                    }
                    IconButton(onClick = { vm.syncNow() }) { Icon(Icons.Default.Refresh, contentDescription = "Sincronizar ahora") }
                    Box {
                        IconButton(onClick = { menu = true }) { Icon(Icons.Default.MoreVert, contentDescription = "Más opciones") }
                        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                            DropdownMenuItem(text = { Text("Borrar todo mi historial") }, onClick = { menu = false; confirm = "wipe" })
                            DropdownMenuItem(text = { Text("Cerrar sesión") }, onClick = { menu = false; confirm = "logout" })
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface)
            )
        }
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            OutlinedTextField(
                value = query, onValueChange = { vm.query.value = it },
                placeholder = { Text("Buscar en el historial") }, singleLine = true,
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                trailingIcon = {
                    if (query.isNotEmpty()) IconButton(onClick = { vm.query.value = "" }) {
                        Icon(Icons.Default.Clear, contentDescription = "Borrar búsqueda")
                    }
                },
                modifier = Modifier.fillMaxWidth().padding(12.dp)
            )
            if (list.isEmpty()) {
                Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
                    Text(
                        if (query.isBlank()) "Todavía no hay notificaciones. Cuando llegue una, aparecerá aquí."
                        else "No hay resultados para “$query”.",
                        textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            } else {
                LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 12.dp, vertical = 4.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(list, key = { it.uuid }) {
                        NotificationCard(it, Modifier.animateItem())
                    }
                    if (list.size >= limit) item {
                        TextButton(onClick = { vm.loadMore() }, modifier = Modifier.fillMaxWidth()) { Text("Cargar más") }
                    }
                }
            }
        }
    }

    confirm?.let { action ->
        val wipe = action == "wipe"
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text(if (wipe) "¿Borrar todo?" else "¿Cerrar sesión?") },
            text = {
                Text(
                    if (wipe) "Se borrará tu historial del servidor y de este teléfono. No se puede deshacer."
                    else "Se cerrará la sesión y se quitará el historial guardado en este teléfono. Lo que ya se envió al servidor se conserva."
                )
            },
            confirmButton = {
                TextButton(onClick = { confirm = null; if (wipe) vm.wipeEverything() else vm.logout() }) {
                    Text(if (wipe) "Borrar" else "Cerrar sesión", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Cancelar") } }
        )
    }

}

@Composable
fun NotificationCard(n: NotificationEntity, modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    var open by remember { mutableStateOf(false) }
    val icon = remember(n.packageName) {
        runCatching { ctx.packageManager.getApplicationIcon(n.packageName).toBitmap(96, 96).asImageBitmap() }.getOrNull()
    }
    val time = remember(n.postedAt) { SimpleDateFormat("d MMM · HH:mm", Locale("es", "PE")).format(Date(n.postedAt)) }
    val body = n.bigText?.takeIf { it.isNotBlank() } ?: n.text
    val dotColor by animateColorAsState(
        targetValue = if (n.synced) MaterialTheme.colorScheme.secondary else MaterialTheme.colorScheme.tertiary,
        animationSpec = tween(500), label = "estado"
    )

    Card(
        modifier = modifier.fillMaxWidth().animateContentSize().clickable { open = !open },
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(12.dp)
    ) {
        Row(Modifier.padding(12.dp)) {
            if (icon != null) {
                Image(icon, contentDescription = null, modifier = Modifier.size(40.dp).clip(RoundedCornerShape(10.dp)))
            } else {
                Box(
                    Modifier.size(40.dp).clip(RoundedCornerShape(10.dp)).background(MaterialTheme.colorScheme.surfaceVariant),
                    contentAlignment = Alignment.Center
                ) { Text(n.appName.take(1).uppercase(), fontWeight = FontWeight.Black, color = MaterialTheme.colorScheme.primary) }
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        n.appName, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary,
                        maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f)
                    )
                    Text(time, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.width(6.dp))
                    Box(Modifier.size(8.dp).clip(RoundedCornerShape(4.dp)).background(dotColor))
                }
                if (!n.title.isNullOrBlank()) {
                    Text(
                        n.title, fontWeight = FontWeight.SemiBold,
                        maxLines = if (open) Int.MAX_VALUE else 1, overflow = TextOverflow.Ellipsis
                    )
                }
                if (!body.isNullOrBlank()) {
                    Text(
                        body, maxLines = if (open) 40 else 3, overflow = TextOverflow.Ellipsis,
                        color = MaterialTheme.colorScheme.onBackground
                    )
                }
            }
        }
    }
}
