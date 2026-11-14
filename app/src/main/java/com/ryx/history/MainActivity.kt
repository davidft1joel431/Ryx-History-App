package com.ryx.history

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import com.ryx.history.ui.AppRoot
import com.ryx.history.ui.AppViewModel
import com.ryx.history.ui.RyxTheme

class MainActivity : ComponentActivity() {
    private val vm: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Al recrearse la actividad (rotación, cambio de tema) el intent se entrega otra vez:
        // no volver a canjear el código de Discord, que ya se usó.
        if (savedInstanceState == null) handleIntent(intent)
        setContent { RyxTheme { AppRoot(vm) } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(i: Intent?) {
        val uri = i?.data ?: return
        if (!uri.scheme.equals("ryxhistory", ignoreCase = true)) return
        vm.handleDeepLink(uri)
    }
}
