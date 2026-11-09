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
        handleIntent(intent)
        setContent { RyxTheme { AppRoot(vm) } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(i: Intent?) {
        val uri = i?.data ?: return
        if (uri.scheme == "ryxhistory" && uri.host == "auth") vm.handleDeepLink(uri)
    }
}
