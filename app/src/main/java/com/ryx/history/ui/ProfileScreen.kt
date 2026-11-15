package com.ryx.history.ui

import android.graphics.BitmapFactory
import android.util.Base64
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
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
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.graphics.drawable.toBitmap
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ryx.history.data.AppCount
import com.ryx.history.data.NotificationEntity
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/** Perfil de la cuenta: datos, Discord, y los mensajes por secciones. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(vm: AppViewModel, onBack: () -> Unit) {
    val profile by vm.profile.collectAsStateWithLifecycle()
    val apps by vm.apps.collectAsStateWithLifecycle()
    val total by vm.total.collectAsStateWithLifecycle()
    val sent by vm.sent.collectAsStateWithLifecycle()
    val pending by vm.pending.collectAsStateWithLifecycle()
    val busy by vm.busy.collectAsStateWithLifecycle()
    val contexto = LocalContext.current
    var section by remember { mutableStateOf("mensajes") }
    var appFilter by remember { mutableStateOf<String?>(null) }
    var rango by remember { mutableStateOf(0) }
    val desde = remember(rango) { rangeStart(rango) }
    val flujo = remember(appFilter, desde) {
        when {
            appFilter != null -> vm.byApp(appFilter!!, desde)
            desde > 0L -> vm.since(desde)
            else -> vm.list
        }
    }
    val mensajes by flujo.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) { vm.loadProfile() }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = {
                    Text("Perfil", fontWeight = FontWeight.Black, color = MaterialTheme.colorScheme.primary)
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.Close, contentDescription = "Volver")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface)
            )
        }
    ) { pad ->
        LazyColumn(
            Modifier.padding(pad).fillMaxSize(),
            contentPadding = PaddingValues(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            item {
                AccountCard(
                    nombre = profile?.name?.takeIf { it.isNotBlank() } ?: vm.userName.ifBlank { "Tu cuenta" },
                    correo = profile?.email ?: "",
                    discord = profile?.discord == true,
                    servidor = profile?.notifications ?: 0,
                    busy = busy,
                    onLink = { vm.linkDiscord(contexto) }
                )
            }
            item { StatsRow(total = total, sent = sent, pending = pending) }
            item {
                SectionRow(actual = section) {
                    section = it
                    appFilter = null
                }
            }
            item { RangeRow(actual = rango) { rango = it } }
            if (section == "apps") {
                items(apps, key = { it.packageName }) { app ->
                    AppRow(app) {
                        section = "mensajes"
                        appFilter = app.packageName
                    }
                }
                if (apps.isEmpty()) {
                    item { EmptyHint("Todavía no hay aplicaciones con notificaciones guardadas.") }
                }
            } else {
                if (appFilter != null) {
                    item {
                        Row(
                            Modifier.fillMaxWidth().padding(bottom = 4.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                "Filtrando por app: " + (apps.firstOrNull { it.packageName == appFilter }?.appName ?: appFilter),
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.weight(1f)
                            )
                            OutlinedButton(onClick = { appFilter = null }) { Text("Quitar filtro") }
                        }
                    }
                }
                items(mensajes, key = { it.uuid }) { item ->
                    ProfileMessageCard(item)
                }
                if (mensajes.isEmpty()) {
                    item { EmptyHint("No hay mensajes guardados en esta sección.") }
                }
            }
        }
    }
}

@Composable
private fun AccountCard(
    nombre: String, correo: String, discord: Boolean, servidor: Int, busy: Boolean,
    onLink: () -> Unit
) {
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(18.dp)
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(nombre, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Black)
            if (correo.isNotBlank()) {
                Text(correo, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Spacer(Modifier.height(12.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.size(10.dp).clip(RoundedCornerShape(5.dp)).background(
                        if (discord) MaterialTheme.colorScheme.secondary else MaterialTheme.colorScheme.tertiary
                    )
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    if (discord) "Discord vinculado" else "Sin Discord vinculado ($servidor notificaciones en el servidor)",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
            if (!discord) {
                Spacer(Modifier.height(12.dp))
                Button(onClick = onLink, enabled = !busy, modifier = Modifier.fillMaxWidth().height(46.dp)) {
                    Text("Vincular mi Discord", fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

@Composable
private fun StatsRow(total: Int, sent: Int, pending: Int) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Stat("GUARDADAS", total.toString(), Modifier.weight(1f))
        Stat("ENVIADAS", sent.toString(), Modifier.weight(1f))
        Stat("SIN ENVIAR", pending.toString(), Modifier.weight(1f))
    }
}

@Composable
private fun Stat(titulo: String, valor: String, modifier: Modifier = Modifier) {
    Card(
        modifier,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        shape = RoundedCornerShape(14.dp)
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(titulo, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(valor, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Black,
                color = MaterialTheme.colorScheme.primary)
        }
    }
}

@Composable
private fun SectionRow(actual: String, onSelect: (String) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionTab("Mensajes", actual == "mensajes", Modifier.weight(1f)) { onSelect("mensajes") }
        SectionTab("Por app", actual == "apps", Modifier.weight(1f)) { onSelect("apps") }
    }
}

@Composable
private fun SectionTab(texto: String, activo: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val peso by animateFloatAsState(if (activo) 1f else 0f, tween(220), label = "pestana")
    Card(
        modifier.clickable { onClick() },
        colors = CardDefaults.cardColors(
            containerColor = if (activo) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surface
        ),
        shape = RoundedCornerShape(14.dp)
    ) {
        Box(Modifier.fillMaxWidth().padding(vertical = 12.dp), contentAlignment = Alignment.Center) {
            Text(
                texto,
                fontWeight = FontWeight.Bold,
                color = if (activo) MaterialTheme.colorScheme.onPrimary
                else MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun RangeRow(actual: Int, onPick: (Int) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        listOf(0 to "Todo", 1 to "Hoy", 7 to "7 días", 30 to "30 días").forEach { (valor, texto) ->
            val activo = actual == valor
            Box(
                Modifier.weight(1f)
                    .clip(RoundedCornerShape(11.dp))
                    .background(
                        if (activo) MaterialTheme.colorScheme.secondary.copy(alpha = 0.2f)
                        else MaterialTheme.colorScheme.surface
                    )
                    .clickable { onPick(valor) }
                    .padding(vertical = 8.dp),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    texto,
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = if (activo) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

/** Desde cuándo se listan los mensajes: 0 = todo, 1 = hoy, 7 y 30 = últimos días. */
private fun rangeStart(dias: Int): Long {
    if (dias <= 0) return 0L
    if (dias == 1) {
        val cal = Calendar.getInstance()
        cal.set(Calendar.HOUR_OF_DAY, 0)
        cal.set(Calendar.MINUTE, 0)
        cal.set(Calendar.SECOND, 0)
        cal.set(Calendar.MILLISECOND, 0)
        return cal.timeInMillis
    }
    return System.currentTimeMillis() - dias * 86_400_000L
}

@Composable
private fun AppRow(app: AppCount, onClick: () -> Unit) {
    val ctx = LocalContext.current
    val icono = remember(app.packageName) {
        runCatching {
            ctx.packageManager.getApplicationIcon(app.packageName).toBitmap(72, 72).asImageBitmap()
        }.getOrNull()
    }
    Card(
        Modifier.fillMaxWidth().clickable { onClick() },
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(14.dp)
    ) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            if (icono != null) {
                Image(icono, contentDescription = null, modifier = Modifier.size(34.dp).clip(RoundedCornerShape(9.dp)))
            } else {
                Box(
                    Modifier.size(34.dp).clip(RoundedCornerShape(9.dp)).background(MaterialTheme.colorScheme.surfaceVariant),
                    contentAlignment = Alignment.Center
                ) { Text(app.appName.take(1).uppercase(), fontWeight = FontWeight.Black,
                    color = MaterialTheme.colorScheme.primary) }
            }
            Spacer(Modifier.width(12.dp))
            Text(app.appName, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            Text("${app.total}", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun ProfileMessageCard(n: NotificationEntity) {
    val ctx = LocalContext.current
    var abierto by remember { mutableStateOf(false) }
    val icono = remember(n.packageName) {
        runCatching {
            ctx.packageManager.getApplicationIcon(n.packageName).toBitmap(72, 72).asImageBitmap()
        }.getOrNull()
    }
    val hora = remember(n.postedAt) {
        SimpleDateFormat("d MMM · HH:mm", Locale("es", "PE")).format(Date(n.postedAt))
    }
    val cuerpo = n.bigText?.takeIf { it.isNotBlank() } ?: n.text
    val foto = remember(n.image) {
        n.image?.let { texto ->
            runCatching {
                val bytes = Base64.decode(texto, Base64.DEFAULT)
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
            }.getOrNull()
        }
    }

    Card(
        Modifier.fillMaxWidth().animateContentSize().clickable { abierto = !abierto },
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(14.dp)
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (icono != null) {
                    Image(icono, contentDescription = null,
                        modifier = Modifier.size(30.dp).clip(RoundedCornerShape(8.dp)))
                } else {
                    Box(
                        Modifier.size(30.dp).clip(RoundedCornerShape(8.dp))
                            .background(MaterialTheme.colorScheme.surfaceVariant),
                        contentAlignment = Alignment.Center
                    ) { Text(n.appName.take(1).uppercase(), fontWeight = FontWeight.Black,
                        color = MaterialTheme.colorScheme.primary) }
                }
                Spacer(Modifier.width(10.dp))
                Text(n.appName, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary,
                    maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                Text(hora, style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (!n.title.isNullOrBlank()) {
                Spacer(Modifier.height(6.dp))
                Text(n.title, fontWeight = FontWeight.SemiBold)
            }
            if (!cuerpo.isNullOrBlank()) {
                Text(
                    cuerpo,
                    maxLines = if (abierto) Int.MAX_VALUE else 3,
                    overflow = TextOverflow.Ellipsis,
                    color = MaterialTheme.colorScheme.onBackground
                )
            }
            if (foto != null) {
                Spacer(Modifier.height(8.dp))
                Image(
                    foto, contentDescription = "Imagen de la notificación",
                    modifier = Modifier.fillMaxWidth().height(if (abierto) 220.dp else 120.dp)
                        .clip(RoundedCornerShape(12.dp)),
                    contentScale = androidx.compose.ui.layout.ContentScale.Crop
                )
            }
        }
    }
}

@Composable
private fun EmptyHint(texto: String) {
    Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
        Text(texto, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
