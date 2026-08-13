package com.example.footballlottery

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.chaquo.python.Python
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            FootballLotteryTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    FootballLotteryApp()
                }
            }
        }
    }
}

private enum class AppTab(val label: String) {
    Analysis("分析"),
    Review("复盘"),
    Single("单场"),
    Settings("设置"),
}

private const val SETTINGS_PREFS = "football_lottery_settings"
private const val PREF_THE_ODDS_API_KEY = "the_odds_api_key"
private const val PREF_FEISHU_WEBHOOK_URL = "feishu_webhook_url"
private const val PREF_FEISHU_AUTO_SEND = "feishu_auto_send"
private const val PREF_ANALYSIS_ISSUE = "analysis_issue"
private const val PREF_ANALYSIS_MAX_TICKET_COST = "analysis_max_ticket_cost"
private const val STRENGTH_XG_MATCHES = 20

data class AnalysisReport(
    val issue: String,
    val purchaseDeadline: String,
    val purchaseDeadlineSource: String,
    val saleBeginTime: String,
    val analysisMode: String,
    val analysisModeMessage: String,
    val foreignOddsStatus: ForeignOddsStatus?,
    val metrics: ReportMetrics,
    val choose9Keep: List<Int>,
    val choose9Drop: List<Int>,
    val predictions: List<MatchPrediction>,
    val reviewDiagnostics: ReviewDiagnostics?,
    val modelCalibration: ModelCalibration?,
)

data class ForeignOddsStatus(
    val status: String,
    val message: String,
    val requested: Boolean,
    val configured: Boolean,
    val attemptedQueries: Int,
    val successfulQueries: Int,
    val cacheHits: Int,
    val matchedMatches: Int,
    val totalMatches: Int,
    val creditsRemaining: Int?,
    val creditsUsed: Int?,
    val creditsLast: Int?,
)

data class ForeignOddsUsage(
    val status: String,
    val message: String,
    val creditsRemaining: Int?,
    val creditsUsed: Int?,
    val creditsLast: Int?,
    val activeSports: Int,
    val checkedAt: String,
)

data class ModelCalibration(
    val status: String,
    val sampleCount: Int,
    val minimumSamples: Int,
    val oddsWeight: Double,
    val signalsWeight: Double,
    val dixonColesWeight: Double,
)

data class ReportMetrics(
    val matchCount: Int,
    val singleCount: Int,
    val ticketSingleCount: Int,
    val budgetForcedSingleCount: Int,
    val lowRiskCount: Int,
    val averageConfidence: Double,
)

data class MatchPrediction(
    val seq: Int,
    val league: String,
    val kickoffDisplay: String,
    val home: String,
    val away: String,
    val pickText: String,
    val pickLabels: List<String>,
    val analysisPickText: String,
    val analysisPickLabels: List<String>,
    val budgetAdjusted: Boolean,
    val budgetForcedSingle: Boolean,
    val drawGuard: Boolean,
    val confidence: Double,
    val risk: String,
    val probabilities: OutcomeProbabilities,
    val scorelines: List<ScorelinePrediction>,
    val reasons: List<String>,
    val finalScore: String,
    val finalResult: String,
    val finalResultLabel: String,
    val outcomeHit: Boolean,
    val diagnosticTags: List<String>,
    val postMatchEvidence: List<PostMatchEvidence>,
)

data class PostMatchEvidence(
    val label: String,
    val summary: String,
    val sources: List<String>,
)

data class DiagnosticCount(
    val label: String,
    val count: Int,
)

data class ReviewDiagnostics(
    val issueMissCount: Int,
    val issueTags: List<DiagnosticCount>,
    val historyIssueCount: Int,
    val historyTags: List<DiagnosticCount>,
)

data class OutcomeProbabilities(
    val home: Double,
    val draw: Double,
    val away: Double,
)

data class ScorelinePrediction(
    val score: String,
    val probability: Double,
)

data class HistoryEntry(
    val id: String,
    val kind: String,
    val issue: String,
    val title: String,
    val createdAt: String,
    val htmlUrl: String,
    val markdownUrl: String,
    val markdownText: String,
    val report: AnalysisReport?,
)

data class HistoryGroup(
    val key: String,
    val issue: String,
    val kind: String,
    val entries: List<HistoryEntry>,
)

data class SinglePredictionResult(
    val home: String,
    val away: String,
    val pickLabel: String,
    val confidence: Double,
    val risk: String,
    val probabilities: OutcomeProbabilities,
    val scorelines: List<ScorelinePrediction>,
    val reasons: List<String>,
    val dataSource: String,
)

class AppViewModel : ViewModel() {
    var isTestingConnection by mutableStateOf(false)
        private set
    var connectionMessage by mutableStateOf("")
        private set
    var connectionError by mutableStateOf("")
        private set
    var theOddsApiKey by mutableStateOf("")
        private set
    var feishuWebhookUrl by mutableStateOf("")
        private set
    var feishuAutoSend by mutableStateOf(false)
        private set
    var settingsMessage by mutableStateOf("")
        private set
    var isTestingFeishu by mutableStateOf(false)
        private set
    var feishuTestMessage by mutableStateOf("")
        private set
    var feishuTestError by mutableStateOf("")
        private set
    var isCheckingApiUsage by mutableStateOf(false)
        private set
    var apiUsage by mutableStateOf<ForeignOddsUsage?>(null)
        private set

    fun loadSettings(context: Context) {
        val prefs = context.getSharedPreferences(SETTINGS_PREFS, Context.MODE_PRIVATE)
        theOddsApiKey = prefs.getString(PREF_THE_ODDS_API_KEY, "").orEmpty()
        feishuWebhookUrl = prefs.getString(PREF_FEISHU_WEBHOOK_URL, "").orEmpty()
        feishuAutoSend = prefs.getBoolean(PREF_FEISHU_AUTO_SEND, false)
    }

    fun updateTheOddsApiKey(value: String) {
        theOddsApiKey = value
        settingsMessage = ""
        apiUsage = null
    }

    fun updateFeishuWebhookUrl(value: String) {
        feishuWebhookUrl = value
        settingsMessage = ""
        feishuTestMessage = ""
        feishuTestError = ""
    }

    fun updateFeishuAutoSend(value: Boolean) {
        feishuAutoSend = value
        settingsMessage = ""
    }

    fun saveSettings(context: Context) {
        val prefs = context.getSharedPreferences(SETTINGS_PREFS, Context.MODE_PRIVATE)
        val cleanApiKey = theOddsApiKey.trim()
        prefs.edit()
            .putString(PREF_THE_ODDS_API_KEY, cleanApiKey)
            .apply()
        theOddsApiKey = cleanApiKey
        settingsMessage = "外盘设置已保存。"
    }

    fun saveFeishuSettings(context: Context) {
        val cleanWebhook = feishuWebhookUrl.trim()
        context.getSharedPreferences(SETTINGS_PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(PREF_FEISHU_WEBHOOK_URL, cleanWebhook)
            .putBoolean(PREF_FEISHU_AUTO_SEND, feishuAutoSend)
            .apply()
        feishuWebhookUrl = cleanWebhook
        settingsMessage = if (feishuAutoSend && cleanWebhook.isBlank()) {
            "已保存，但自动推送需要先填写飞书 Webhook。"
        } else {
            "飞书推送设置已保存。"
        }
    }

    fun testFeishu(engine: FootballLotteryLocalEngine) {
        val webhook = feishuWebhookUrl.trim()
        if (webhook.isBlank()) {
            feishuTestError = "请先填写飞书 Webhook。"
            return
        }
        viewModelScope.launch {
            isTestingFeishu = true
            feishuTestMessage = ""
            feishuTestError = ""
            runCatching {
                engine.sendFeishuText(webhook, "足球分析 App 飞书推送测试成功。")
            }.onSuccess {
                feishuTestMessage = "测试消息已发送到飞书。"
            }.onFailure { throwable ->
                feishuTestError = throwable.message ?: "飞书测试发送失败。"
            }
            isTestingFeishu = false
        }
    }

    fun refreshForeignOddsUsage(engine: FootballLotteryLocalEngine) {
        viewModelScope.launch {
            isCheckingApiUsage = true
            runCatching {
                engine.checkForeignOddsUsage(theOddsApiKey.trim())
            }.onSuccess { usage ->
                apiUsage = usage
            }.onFailure { throwable ->
                apiUsage = ForeignOddsUsage(
                    status = "network_error",
                    message = throwable.message ?: "The Odds API 用量查询失败。",
                    creditsRemaining = null,
                    creditsUsed = null,
                    creditsLast = null,
                    activeSports = 0,
                    checkedAt = "",
                )
            }
            isCheckingApiUsage = false
        }
    }

    fun testLocalEngine(engine: FootballLotteryLocalEngine) {
        viewModelScope.launch {
            isTestingConnection = true
            connectionMessage = ""
            connectionError = ""
            runCatching {
                engine.healthCheck()
            }.onSuccess { service ->
                connectionMessage = "手机本机分析引擎可用：$service。"
            }.onFailure { throwable ->
                connectionError = throwable.message ?: "本机分析引擎启动失败。"
            }
            isTestingConnection = false
        }
    }
}

class AnalysisViewModel : ViewModel() {
    private var savedInputsLoaded = false

    var issue by mutableStateOf("26090")
        private set
    var maxTicketCostYuan by mutableStateOf("500")
        private set
    var isLoading by mutableStateOf(false)
        private set
    var message by mutableStateOf("")
        private set
    var error by mutableStateOf("")
        private set
    var report by mutableStateOf<AnalysisReport?>(null)
        private set

    fun loadSavedInputs(context: Context) {
        if (savedInputsLoaded) {
            return
        }
        val prefs = context.getSharedPreferences(SETTINGS_PREFS, Context.MODE_PRIVATE)
        if (prefs.contains(PREF_ANALYSIS_ISSUE)) {
            issue = prefs.getString(PREF_ANALYSIS_ISSUE, issue).orEmpty()
        }
        if (prefs.contains(PREF_ANALYSIS_MAX_TICKET_COST)) {
            maxTicketCostYuan = prefs.getString(PREF_ANALYSIS_MAX_TICKET_COST, maxTicketCostYuan).orEmpty()
        }
        savedInputsLoaded = true
    }

    fun updateIssue(value: String, context: Context) {
        issue = value
        context.getSharedPreferences(SETTINGS_PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(PREF_ANALYSIS_ISSUE, value)
            .apply()
    }

    fun updateMaxTicketCostYuan(value: String, context: Context) {
        maxTicketCostYuan = value
        context.getSharedPreferences(SETTINGS_PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(PREF_ANALYSIS_MAX_TICKET_COST, value)
            .apply()
    }

    fun generateAnalysis(
        engine: FootballLotteryLocalEngine,
        foreignOddsApiKey: String,
        feishuAutoSend: Boolean,
        feishuWebhookUrl: String,
    ) {
        val cleanIssue = issue.trim()
        val cleanMaxTicketCostYuan = maxTicketCostYuan.trim().toIntOrNull()
        val cleanForeignOddsApiKey = foreignOddsApiKey.trim()
        if (cleanIssue.isEmpty()) {
            error = "请填写期号。"
            return
        }
        if (cleanMaxTicketCostYuan == null || cleanMaxTicketCostYuan < 2) {
            error = "请填写不低于 2 元的最高购彩金额。"
            return
        }
        viewModelScope.launch {
            isLoading = true
            error = ""
            message = ""
            runCatching {
                engine.generateAnalysis(
                    issue = cleanIssue,
                    maxTicketCostYuan = cleanMaxTicketCostYuan,
                    foreignOdds = cleanForeignOddsApiKey.isNotEmpty(),
                    foreignOddsApiKey = cleanForeignOddsApiKey,
                )
            }.onSuccess { response ->
                report = response
                val generatedMessage = if (response.analysisMode == "simple_fallback") {
                    "${response.issue} 分析报告已生成；检测到网络问题，已自动使用简单分析。"
                } else {
                    "${response.issue} 完整分析报告已生成。"
                }
                message = generatedMessage
                if (feishuAutoSend) {
                    val webhook = feishuWebhookUrl.trim()
                    if (webhook.isBlank()) {
                        error = "报告已生成，但未填写飞书 Webhook，无法自动推送。"
                    } else {
                        runCatching {
                            engine.sendAnalysisToFeishu(webhook, response)
                        }.onSuccess {
                            message = "$generatedMessage 出票建议已发送到飞书。"
                        }.onFailure { throwable ->
                            error = "报告已生成，但飞书推送失败：${throwable.message ?: "未知错误"}"
                        }
                    }
                }
            }.onFailure { throwable ->
                error = throwable.message ?: "生成分析报告失败。"
            }
            isLoading = false
        }
    }
}

class HistoryViewModel : ViewModel() {
    var isLoading by mutableStateOf(false)
        private set
    var hasLoaded by mutableStateOf(false)
        private set
    var error by mutableStateOf("")
        private set
    var message by mutableStateOf("")
        private set
    var isDeleting by mutableStateOf(false)
        private set
    var entries by mutableStateOf<List<HistoryEntry>>(emptyList())
        private set
    var selectedEntry by mutableStateOf<HistoryEntry?>(null)
        private set
    var expandedGroups by mutableStateOf<Set<String>>(emptySet())
        private set

    fun refresh(engine: FootballLotteryLocalEngine) {
        viewModelScope.launch {
            isLoading = true
            error = ""
            runCatching {
                engine.fetchHistory()
            }.onSuccess { response ->
                val previousSelection = selectedEntry
                entries = response
                selectedEntry = response.firstOrNull { it.id == previousSelection?.id }
                val availableGroups = response.map { historyGroupKey(it) }.toSet()
                expandedGroups = expandedGroups.intersect(availableGroups)
                hasLoaded = true
            }.onFailure { throwable ->
                error = throwable.message ?: "读取历史记录失败。"
            }
            isLoading = false
        }
    }

    fun deleteAnalysisEntries(engine: FootballLotteryLocalEngine, targets: List<HistoryEntry>) {
        val entryIds = targets.filter { it.kind == "analysis" }.map { it.id }.filter { it.isNotBlank() }.distinct()
        if (entryIds.isEmpty() || isDeleting) {
            return
        }
        viewModelScope.launch {
            isDeleting = true
            error = ""
            message = ""
            runCatching {
                val deletedCount = engine.deleteHistory(entryIds)
                deletedCount to engine.fetchHistory()
            }.onSuccess { (deletedCount, response) ->
                entries = response
                selectedEntry = selectedEntry?.takeIf { selected -> response.any { it.id == selected.id } }
                val availableGroups = response.map { historyGroupKey(it) }.toSet()
                expandedGroups = expandedGroups.intersect(availableGroups)
                message = "已删除 $deletedCount 条分析记录。"
                hasLoaded = true
            }.onFailure { throwable ->
                error = throwable.message ?: "删除分析记录失败。"
            }
            isDeleting = false
        }
    }

    fun select(entry: HistoryEntry) {
        selectedEntry = if (selectedEntry?.id == entry.id) null else entry
        expandedGroups = expandedGroups + historyGroupKey(entry)
    }

    fun toggleGroup(key: String) {
        expandedGroups = if (key in expandedGroups) {
            expandedGroups - key
        } else {
            expandedGroups + key
        }
    }
}

class ReviewViewModel : ViewModel() {
    var issue by mutableStateOf("26090")
        private set
    var autoResults by mutableStateOf(true)
        private set
    var resultsCsv by mutableStateOf("seq,score\n1,1-0\n2,0-0")
        private set
    var isLoading by mutableStateOf(false)
        private set
    var message by mutableStateOf("")
        private set
    var error by mutableStateOf("")
        private set
    var report by mutableStateOf<AnalysisReport?>(null)
        private set
    var analysisCandidates by mutableStateOf<List<HistoryEntry>>(emptyList())
        private set
    var selectedAnalysisId by mutableStateOf("")
        private set

    fun updateIssue(value: String) {
        issue = value
        analysisCandidates = emptyList()
        selectedAnalysisId = ""
    }

    fun updateAutoResults(value: Boolean) {
        autoResults = value
    }

    fun updateResultsCsv(value: String) {
        resultsCsv = value
    }

    fun selectAnalysis(entry: HistoryEntry) {
        selectedAnalysisId = entry.id
        error = ""
    }

    fun generateReview(engine: FootballLotteryLocalEngine) {
        val cleanIssue = issue.trim()
        if (cleanIssue.isEmpty()) {
            error = "请填写期号。"
            return
        }
        if (!autoResults && resultsCsv.trim().isEmpty()) {
            error = "请粘贴赛果 CSV，或打开自动拉取赛果。"
            return
        }
        viewModelScope.launch {
            isLoading = true
            error = ""
            message = ""
            runCatching {
                val matchingAnalyses = engine.fetchHistory().filter { entry ->
                    entry.kind == "analysis" && entry.issue.trim() == cleanIssue
                }
                analysisCandidates = matchingAnalyses
                val selectedAnalysis = matchingAnalyses.firstOrNull { it.id == selectedAnalysisId }
                if (matchingAnalyses.size > 1 && selectedAnalysis == null) {
                    throw IllegalStateException("发现 ${matchingAnalyses.size} 次分析结果，请先选择要依据哪一次分析进行复盘。")
                }
                engine.generateReview(
                    cleanIssue,
                    autoResults,
                    resultsCsv,
                    selectedAnalysis?.id ?: matchingAnalyses.singleOrNull()?.id.orEmpty(),
                )
            }.onSuccess { response ->
                report = response
                message = "${response.issue} 复盘报告已生成。"
            }.onFailure { throwable ->
                error = throwable.message ?: "生成复盘报告失败。"
            }
            isLoading = false
        }
    }
}

class SinglePredictionViewModel : ViewModel() {
    var home by mutableStateOf("")
        private set
    var away by mutableStateOf("")
        private set
    var homeOdds by mutableStateOf("")
        private set
    var drawOdds by mutableStateOf("")
        private set
    var awayOdds by mutableStateOf("")
        private set
    var isLoading by mutableStateOf(false)
        private set
    var error by mutableStateOf("")
        private set
    var result by mutableStateOf<SinglePredictionResult?>(null)
        private set

    fun updateHome(value: String) {
        home = value
    }

    fun updateAway(value: String) {
        away = value
    }

    fun updateHomeOdds(value: String) {
        homeOdds = value
    }

    fun updateDrawOdds(value: String) {
        drawOdds = value
    }

    fun updateAwayOdds(value: String) {
        awayOdds = value
    }

    fun predict(engine: FootballLotteryLocalEngine) {
        val cleanHome = home.trim()
        val cleanAway = away.trim()
        if (cleanHome.isEmpty() || cleanAway.isEmpty()) {
            error = "请填写主队和客队。"
            return
        }
        val oddsTexts = listOf(homeOdds.trim(), drawOdds.trim(), awayOdds.trim())
        val hasAnyOdds = oddsTexts.any { it.isNotEmpty() }
        val hasAllOdds = oddsTexts.all { it.isNotEmpty() }
        if (hasAnyOdds && !hasAllOdds) {
            error = "赔率请填写完整的主胜、平、客胜三项，或全部留空。"
            return
        }
        val oddsValues = if (hasAllOdds) oddsTexts.map { it.toDoubleOrNull() } else emptyList()
        if (oddsValues.any { it == null }) {
            error = "赔率必须是数字。"
            return
        }
        if (oddsValues.filterNotNull().any { it <= 1.0 }) {
            error = "赔率必须大于 1.00。"
            return
        }
        viewModelScope.launch {
            isLoading = true
            error = ""
            result = null
            runCatching {
                engine.singlePrediction(
                    home = cleanHome,
                    away = cleanAway,
                    homeOdds = oddsValues.getOrNull(0),
                    drawOdds = oddsValues.getOrNull(1),
                    awayOdds = oddsValues.getOrNull(2),
                )
            }.onSuccess { response ->
                result = response
            }.onFailure { throwable ->
                error = throwable.message ?: "单场预测失败。"
            }
            isLoading = false
        }
    }
}

class FootballLotteryLocalEngine(private val context: android.content.Context) {
    private val bridge by lazy { Python.getInstance().getModule("android_bridge") }
    private val workDir: String
        get() = context.filesDir.absolutePath

    suspend fun healthCheck(): String = withContext(Dispatchers.IO) {
        val json = JSONObject(bridge.callAttr("health").toString())
        json.optString("service", "football-lottery-agent-local")
    }

    suspend fun checkForeignOddsUsage(apiKey: String): ForeignOddsUsage = withContext(Dispatchers.IO) {
        val body = JSONObject().put("foreign_odds_api_key", apiKey)
        val json = JSONObject(bridge.callAttr("foreign_odds_usage", body.toString()).toString())
        if (!json.optBoolean("ok", false)) {
            throw IllegalStateException(json.optString("error", "The Odds API 用量查询失败。"))
        }
        parseForeignOddsUsage(json.optJSONObject("usage") ?: JSONObject())
    }

    suspend fun generateAnalysis(
        issue: String,
        maxTicketCostYuan: Int,
        foreignOdds: Boolean,
        foreignOddsApiKey: String,
    ): AnalysisReport = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("issue", issue)
            .put("max_ticket_cost_yuan", maxTicketCostYuan)
            .put("strength_model", true)
            .put("strength_xg_matches", STRENGTH_XG_MATCHES)
            .put("full_analysis", true)
            .put("foreign_odds", foreignOdds)
            .put("foreign_odds_api_key", foreignOddsApiKey)
        val json = JSONObject(bridge.callAttr("analysis", body.toString(), workDir).toString())
        if (!json.optBoolean("ok", false)) {
            throw IllegalStateException(json.optString("error", "本机分析失败。"))
        }
        parseReport(json.getJSONObject("report"))
    }

    suspend fun sendAnalysisToFeishu(webhookUrl: String, report: AnalysisReport) {
        sendFeishuText(webhookUrl, feishuAnalysisText(report))
    }

    suspend fun sendFeishuText(webhookUrl: String, text: String): Unit = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("webhook_url", webhookUrl)
            .put("text", text.take(3_500))
        val json = JSONObject(bridge.callAttr("send_feishu", body.toString()).toString())
        if (!json.optBoolean("ok", false)) {
            throw IllegalStateException(json.optString("error", "飞书发送失败。"))
        }
    }

    suspend fun fetchHistory(): List<HistoryEntry> = withContext(Dispatchers.IO) {
        val json = JSONObject(bridge.callAttr("history", workDir).toString())
        if (!json.optBoolean("ok", false)) {
            throw IllegalStateException(json.optString("error", "读取历史记录失败。"))
        }
        json.optJSONArray("entries").orEmptyArray().mapObjects {
            HistoryEntry(
                id = it.optString("id"),
                kind = it.optString("kind"),
                issue = it.optString("issue"),
                title = it.optString("title"),
                createdAt = it.optString("created_at"),
                htmlUrl = it.optString("html_url"),
                markdownUrl = it.optString("markdown_url"),
                markdownText = it.optString("markdown_text"),
                report = it.optJSONObject("report")?.let { reportJson -> parseReport(reportJson) },
            )
        }
    }

    suspend fun deleteHistory(entryIds: List<String>): Int = withContext(Dispatchers.IO) {
        val body = JSONObject().put("entry_ids", JSONArray(entryIds))
        val json = JSONObject(bridge.callAttr("delete_history", body.toString(), workDir).toString())
        if (!json.optBoolean("ok", false)) {
            throw IllegalStateException(json.optString("error", "删除分析记录失败。"))
        }
        json.optInt("deleted_count", 0)
    }

    suspend fun generateReview(
        issue: String,
        autoResults: Boolean,
        resultsCsv: String,
        analysisId: String = "",
    ): AnalysisReport = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("issue", issue)
            .put("auto_results", autoResults)
            .put("results_csv", resultsCsv)
            .put("analysis_id", analysisId)
        val json = JSONObject(bridge.callAttr("review", body.toString(), workDir).toString())
        if (!json.optBoolean("ok", false)) {
            throw IllegalStateException(json.optString("error", "本机复盘失败。"))
        }
        parseReport(json.getJSONObject("report"))
    }

    suspend fun singlePrediction(
        home: String,
        away: String,
        homeOdds: Double?,
        drawOdds: Double?,
        awayOdds: Double?,
    ): SinglePredictionResult = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("home", home)
            .put("away", away)
        homeOdds?.let { body.put("home_odds", it) }
        drawOdds?.let { body.put("draw_odds", it) }
        awayOdds?.let { body.put("away_odds", it) }
        val json = JSONObject(bridge.callAttr("single_prediction", body.toString(), workDir).toString())
        if (!json.optBoolean("ok", false)) {
            throw IllegalStateException(json.optString("error", "单场预测失败。"))
        }
        parseSinglePrediction(json)
    }

    private fun parseReport(json: JSONObject): AnalysisReport {
        val metrics = json.optJSONObject("metrics") ?: JSONObject()
        return AnalysisReport(
            issue = json.optString("issue"),
            purchaseDeadline = json.optString("purchase_deadline"),
            purchaseDeadlineSource = json.optString("purchase_deadline_source"),
            saleBeginTime = json.optString("sale_begin_time"),
            analysisMode = json.optString("analysis_mode", "full"),
            analysisModeMessage = json.optString("analysis_mode_message"),
            foreignOddsStatus = json.optJSONObject("foreign_odds_status")?.let(::parseForeignOddsStatus),
            metrics = ReportMetrics(
                matchCount = metrics.optInt("match_count"),
                singleCount = metrics.optInt("single_count"),
                ticketSingleCount = metrics.optInt("ticket_single_count", metrics.optInt("single_count")),
                budgetForcedSingleCount = metrics.optInt("budget_forced_single_count"),
                lowRiskCount = metrics.optInt("low_risk_count"),
                averageConfidence = metrics.optDouble("average_confidence"),
            ),
            choose9Keep = json.optJSONArray("choose9_keep").orEmptyArray().toIntList(),
            choose9Drop = json.optJSONArray("choose9_drop").orEmptyArray().toIntList(),
            predictions = json.optJSONArray("predictions").orEmptyArray().mapObjects { parsePrediction(it) },
            reviewDiagnostics = json.optJSONObject("review_diagnostics")?.let { diagnostics ->
                ReviewDiagnostics(
                    issueMissCount = diagnostics.optInt("issue_miss_count"),
                    issueTags = diagnostics.optJSONArray("issue_tags").orEmptyArray().mapObjects { item ->
                        DiagnosticCount(item.optString("label"), item.optInt("count"))
                    },
                    historyIssueCount = diagnostics.optInt("history_issue_count"),
                    historyTags = diagnostics.optJSONArray("history_tags").orEmptyArray().mapObjects { item ->
                        DiagnosticCount(item.optString("label"), item.optInt("count"))
                    },
                )
            },
            modelCalibration = json.optJSONObject("model_calibration")?.let { calibration ->
                val weights = calibration.optJSONObject("weights") ?: JSONObject()
                ModelCalibration(
                    status = calibration.optString("status"),
                    sampleCount = calibration.optInt("sample_count"),
                    minimumSamples = calibration.optInt("minimum_samples"),
                    oddsWeight = weights.optDouble("odds"),
                    signalsWeight = weights.optDouble("signals"),
                    dixonColesWeight = weights.optDouble("dixon_coles"),
                )
            },
        )
    }

    private fun parsePrediction(json: JSONObject): MatchPrediction {
        val probabilities = json.optJSONObject("probabilities") ?: JSONObject()
        return MatchPrediction(
            seq = json.optInt("seq"),
            league = json.optString("league"),
            kickoffDisplay = json.optString("kickoff_display"),
            home = json.optString("home"),
            away = json.optString("away"),
            pickText = json.optString("pick_text"),
            pickLabels = json.optJSONArray("pick_labels").orEmptyArray().toStringList(),
            analysisPickText = json.optString("analysis_pick_text", json.optString("pick_text")),
            analysisPickLabels = json.optJSONArray("analysis_pick_labels").orEmptyArray().toStringList()
                .ifEmpty { json.optJSONArray("pick_labels").orEmptyArray().toStringList() },
            budgetAdjusted = json.optBoolean("budget_adjusted"),
            budgetForcedSingle = json.optBoolean("budget_forced_single"),
            drawGuard = json.optBoolean("draw_guard"),
            confidence = json.optDouble("confidence"),
            risk = json.optString("risk"),
            probabilities = OutcomeProbabilities(
                home = probabilities.optDouble("home"),
                draw = probabilities.optDouble("draw"),
                away = probabilities.optDouble("away"),
            ),
            scorelines = json.optJSONArray("scorelines").orEmptyArray().mapObjects {
                ScorelinePrediction(
                    score = it.optString("score"),
                    probability = it.optDouble("probability"),
                )
            },
            reasons = json.optJSONArray("reasons").orEmptyArray().toStringList(),
            finalScore = json.optString("final_score"),
            finalResult = json.optString("final_result"),
            finalResultLabel = json.optString("final_result_label"),
            outcomeHit = json.optBoolean("outcome_hit"),
            diagnosticTags = json.optJSONArray("diagnostic_tags").orEmptyArray().toStringList(),
            postMatchEvidence = json.optJSONArray("post_match_evidence").orEmptyArray().mapObjects { item ->
                PostMatchEvidence(
                    label = item.optString("label"),
                    summary = item.optString("summary"),
                    sources = item.optJSONArray("sources").orEmptyArray().mapObjects { source ->
                        source.optString("title")
                    },
                )
            },
        )
    }

    private fun parseSinglePrediction(json: JSONObject): SinglePredictionResult {
        val probabilities = json.optJSONObject("probabilities") ?: JSONObject()
        return SinglePredictionResult(
            home = json.optString("home"),
            away = json.optString("away"),
            pickLabel = json.optString("pick_label"),
            confidence = json.optDouble("confidence"),
            risk = json.optString("risk"),
            probabilities = OutcomeProbabilities(
                home = probabilities.optDouble("home"),
                draw = probabilities.optDouble("draw"),
                away = probabilities.optDouble("away"),
            ),
            scorelines = json.optJSONArray("scorelines").orEmptyArray().mapObjects {
                ScorelinePrediction(
                    score = it.optString("score"),
                    probability = it.optDouble("probability"),
                )
            },
            reasons = json.optJSONArray("reasons").orEmptyArray().toStringList(),
            dataSource = json.optString("data_source"),
        )
    }
}

class FootballLotteryApi(private val baseUrl: String) {
    suspend fun healthCheck(): String = withContext(Dispatchers.IO) {
        val json = requestJson("GET", "/api/health")
        json.optString("service", "football-lottery-agent")
    }

    suspend fun generateAnalysis(
        issue: String,
        maxTicketCostYuan: Int,
        foreignOdds: Boolean,
        foreignOddsApiKey: String,
    ): AnalysisReport = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("issue", issue)
            .put("max_ticket_cost_yuan", maxTicketCostYuan)
            .put("strength_model", true)
            .put("strength_xg_matches", STRENGTH_XG_MATCHES)
            .put("full_analysis", true)
            .put("foreign_odds", foreignOdds)
            .put("foreign_odds_api_key", foreignOddsApiKey)
            .put("no_history", false)
        val json = requestJson("POST", "/api/analysis", body)
        parseReport(json.getJSONObject("report"))
    }

    suspend fun fetchHistory(): List<HistoryEntry> = withContext(Dispatchers.IO) {
        val json = requestJson("GET", "/api/history")
        json.optJSONArray("entries").orEmptyArray().mapObjects {
            HistoryEntry(
                id = it.optString("id"),
                kind = it.optString("kind"),
                issue = it.optString("issue"),
                title = it.optString("title"),
                createdAt = it.optString("created_at"),
                htmlUrl = it.optString("html_url"),
                markdownUrl = it.optString("markdown_url"),
                markdownText = it.optString("markdown_text"),
                report = it.optJSONObject("report")?.let { reportJson -> parseReport(reportJson) },
            )
        }
    }

    suspend fun generateReview(
        issue: String,
        autoResults: Boolean,
        resultsCsv: String,
        analysisId: String = "",
    ): AnalysisReport = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("issue", issue)
            .put("auto_results", autoResults)
            .put("results_csv", resultsCsv)
            .put("analysis_id", analysisId)
            .put("no_history", false)
        val json = requestJson("POST", "/api/review", body)
        parseReport(json.getJSONObject("report"))
    }

    suspend fun singlePrediction(
        home: String,
        away: String,
        homeOdds: Double?,
        drawOdds: Double?,
        awayOdds: Double?,
    ): SinglePredictionResult = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("home", home)
            .put("away", away)
        homeOdds?.let { body.put("home_odds", it) }
        drawOdds?.let { body.put("draw_odds", it) }
        awayOdds?.let { body.put("away_odds", it) }
        parseSinglePrediction(requestJson("POST", "/api/single-prediction", body))
    }

    private fun requestJson(method: String, path: String, body: JSONObject? = null): JSONObject {
        val endpoint = baseUrl.trimEnd('/') + path
        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 20_000
            readTimeout = 120_000
            setRequestProperty("Accept", "application/json")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }

        if (body != null) {
            OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { writer ->
                writer.write(body.toString())
            }
        }

        val responseText = runCatching {
            connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        }.getOrElse {
            connection.errorStream?.bufferedReader(Charsets.UTF_8)?.use { reader -> reader.readText() }.orEmpty()
        }
        val json = JSONObject(responseText.ifBlank { "{}" })
        if (connection.responseCode !in 200..299 || !json.optBoolean("ok", false)) {
            throw IllegalStateException(json.optString("error", json.optString("message", "请求失败。")))
        }
        connection.disconnect()
        return json
    }

    private fun parseReport(json: JSONObject): AnalysisReport {
        val metrics = json.optJSONObject("metrics") ?: JSONObject()
        return AnalysisReport(
            issue = json.optString("issue"),
            purchaseDeadline = json.optString("purchase_deadline"),
            purchaseDeadlineSource = json.optString("purchase_deadline_source"),
            saleBeginTime = json.optString("sale_begin_time"),
            analysisMode = json.optString("analysis_mode", "full"),
            analysisModeMessage = json.optString("analysis_mode_message"),
            foreignOddsStatus = json.optJSONObject("foreign_odds_status")?.let(::parseForeignOddsStatus),
            metrics = ReportMetrics(
                matchCount = metrics.optInt("match_count"),
                singleCount = metrics.optInt("single_count"),
                ticketSingleCount = metrics.optInt("ticket_single_count", metrics.optInt("single_count")),
                budgetForcedSingleCount = metrics.optInt("budget_forced_single_count"),
                lowRiskCount = metrics.optInt("low_risk_count"),
                averageConfidence = metrics.optDouble("average_confidence"),
            ),
            choose9Keep = json.optJSONArray("choose9_keep").orEmptyArray().toIntList(),
            choose9Drop = json.optJSONArray("choose9_drop").orEmptyArray().toIntList(),
            predictions = json.optJSONArray("predictions").orEmptyArray().mapObjects { parsePrediction(it) },
            reviewDiagnostics = json.optJSONObject("review_diagnostics")?.let { diagnostics ->
                ReviewDiagnostics(
                    issueMissCount = diagnostics.optInt("issue_miss_count"),
                    issueTags = diagnostics.optJSONArray("issue_tags").orEmptyArray().mapObjects { item ->
                        DiagnosticCount(item.optString("label"), item.optInt("count"))
                    },
                    historyIssueCount = diagnostics.optInt("history_issue_count"),
                    historyTags = diagnostics.optJSONArray("history_tags").orEmptyArray().mapObjects { item ->
                        DiagnosticCount(item.optString("label"), item.optInt("count"))
                    },
                )
            },
            modelCalibration = json.optJSONObject("model_calibration")?.let { calibration ->
                val weights = calibration.optJSONObject("weights") ?: JSONObject()
                ModelCalibration(
                    status = calibration.optString("status"),
                    sampleCount = calibration.optInt("sample_count"),
                    minimumSamples = calibration.optInt("minimum_samples"),
                    oddsWeight = weights.optDouble("odds"),
                    signalsWeight = weights.optDouble("signals"),
                    dixonColesWeight = weights.optDouble("dixon_coles"),
                )
            },
        )
    }

    private fun parsePrediction(json: JSONObject): MatchPrediction {
        val probabilities = json.optJSONObject("probabilities") ?: JSONObject()
        return MatchPrediction(
            seq = json.optInt("seq"),
            league = json.optString("league"),
            kickoffDisplay = json.optString("kickoff_display"),
            home = json.optString("home"),
            away = json.optString("away"),
            pickText = json.optString("pick_text"),
            pickLabels = json.optJSONArray("pick_labels").orEmptyArray().toStringList(),
            analysisPickText = json.optString("analysis_pick_text", json.optString("pick_text")),
            analysisPickLabels = json.optJSONArray("analysis_pick_labels").orEmptyArray().toStringList()
                .ifEmpty { json.optJSONArray("pick_labels").orEmptyArray().toStringList() },
            budgetAdjusted = json.optBoolean("budget_adjusted"),
            budgetForcedSingle = json.optBoolean("budget_forced_single"),
            drawGuard = json.optBoolean("draw_guard"),
            confidence = json.optDouble("confidence"),
            risk = json.optString("risk"),
            probabilities = OutcomeProbabilities(
                home = probabilities.optDouble("home"),
                draw = probabilities.optDouble("draw"),
                away = probabilities.optDouble("away"),
            ),
            scorelines = json.optJSONArray("scorelines").orEmptyArray().mapObjects {
                ScorelinePrediction(
                    score = it.optString("score"),
                    probability = it.optDouble("probability"),
                )
            },
            reasons = json.optJSONArray("reasons").orEmptyArray().toStringList(),
            finalScore = json.optString("final_score"),
            finalResult = json.optString("final_result"),
            finalResultLabel = json.optString("final_result_label"),
            outcomeHit = json.optBoolean("outcome_hit"),
            diagnosticTags = json.optJSONArray("diagnostic_tags").orEmptyArray().toStringList(),
            postMatchEvidence = json.optJSONArray("post_match_evidence").orEmptyArray().mapObjects { item ->
                PostMatchEvidence(
                    label = item.optString("label"),
                    summary = item.optString("summary"),
                    sources = item.optJSONArray("sources").orEmptyArray().mapObjects { source ->
                        source.optString("title")
                    },
                )
            },
        )
    }

    private fun parseSinglePrediction(json: JSONObject): SinglePredictionResult {
        val probabilities = json.optJSONObject("probabilities") ?: JSONObject()
        return SinglePredictionResult(
            home = json.optString("home"),
            away = json.optString("away"),
            pickLabel = json.optString("pick_label"),
            confidence = json.optDouble("confidence"),
            risk = json.optString("risk"),
            probabilities = OutcomeProbabilities(
                home = probabilities.optDouble("home"),
                draw = probabilities.optDouble("draw"),
                away = probabilities.optDouble("away"),
            ),
            scorelines = json.optJSONArray("scorelines").orEmptyArray().mapObjects {
                ScorelinePrediction(
                    score = it.optString("score"),
                    probability = it.optDouble("probability"),
                )
            },
            reasons = json.optJSONArray("reasons").orEmptyArray().toStringList(),
            dataSource = json.optString("data_source"),
        )
    }
}

@Composable
fun FootballLotteryApp(
    appViewModel: AppViewModel = viewModel(),
    analysisViewModel: AnalysisViewModel = viewModel(),
    analysisHistoryViewModel: HistoryViewModel = viewModel(key = "analysisHistory"),
    reviewViewModel: ReviewViewModel = viewModel(),
    reviewHistoryViewModel: HistoryViewModel = viewModel(key = "reviewHistory"),
    singleViewModel: SinglePredictionViewModel = viewModel(),
) {
    val context = LocalContext.current
    val localEngine = remember(context) { FootballLotteryLocalEngine(context.applicationContext) }
    var selectedTab by remember { mutableStateOf(AppTab.Analysis) }

    LaunchedEffect(Unit) {
        appViewModel.loadSettings(context.applicationContext)
    }

    Scaffold(
        bottomBar = {
            NavigationBar(containerColor = Color.White) {
                AppTab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = selectedTab == tab,
                        onClick = {
                            selectedTab = tab
                        },
                        label = { Text(tab.label) },
                        icon = { Text(tab.label.take(1), fontWeight = FontWeight.Bold) },
                    )
                }
            }
        },
    ) { padding ->
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
            color = Color(0xFFF4F6FA),
        ) {
            when (selectedTab) {
                AppTab.Analysis -> AnalysisScreen(localEngine, analysisViewModel, analysisHistoryViewModel, appViewModel)
                AppTab.Review -> ReviewScreen(localEngine, reviewViewModel, reviewHistoryViewModel)
                AppTab.Single -> SinglePredictionScreen(localEngine, singleViewModel)
                AppTab.Settings -> SettingsScreen(
                    appViewModel = appViewModel,
                    localEngine = localEngine,
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AnalysisScreen(
    localEngine: FootballLotteryLocalEngine,
    viewModel: AnalysisViewModel,
    historyViewModel: HistoryViewModel,
    appViewModel: AppViewModel,
) {
    val context = LocalContext.current
    LaunchedEffect(Unit) {
        viewModel.loadSavedInputs(context.applicationContext)
    }
    LaunchedEffect(viewModel.report?.issue) {
        if (viewModel.report != null) {
            historyViewModel.refresh(localEngine)
        }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { RequestCard(localEngine, viewModel, appViewModel) }
        if (viewModel.error.isNotBlank()) {
            item { StatusCard(text = viewModel.error, color = Color(0xFFB42318)) }
        }
        if (viewModel.message.isNotBlank()) {
            item { StatusCard(text = viewModel.message, color = Color(0xFF16845B)) }
        }
        item {
            HistorySection(
                localEngine = localEngine,
                viewModel = historyViewModel,
                kind = "analysis",
                title = "历史分析报告",
            )
        }
    }
}

@Composable
private fun HistorySection(
    localEngine: FootballLotteryLocalEngine,
    viewModel: HistoryViewModel,
    kind: String,
    title: String,
) {
    var pendingDeletion by remember { mutableStateOf<List<HistoryEntry>>(emptyList()) }
    LaunchedEffect(Unit) {
        if (!viewModel.hasLoaded && !viewModel.isLoading) {
            viewModel.refresh(localEngine)
        }
    }

    val entries = viewModel.entries.filter { it.kind == kind }
    val selectedEntry = viewModel.selectedEntry?.takeIf { it.kind == kind }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        HeaderCard(
            title = title,
            subtitle = "读取手机本机生成过的${kindLabel(kind)}记录。",
            buttonText = if (viewModel.isLoading) "读取中" else "刷新",
            buttonEnabled = !viewModel.isLoading,
            onClick = { viewModel.refresh(localEngine) },
        )
        if (viewModel.error.isNotBlank()) {
            StatusCard(text = viewModel.error, color = Color(0xFFB42318))
        }
        if (viewModel.message.isNotBlank()) {
            StatusCard(text = viewModel.message, color = Color(0xFF16845B))
        }
        historyGroups(entries).forEach { group ->
            HistoryGroupCard(
                group = group,
                selectedEntry = selectedEntry,
                expanded = group.key in viewModel.expandedGroups,
                onToggle = { viewModel.toggleGroup(group.key) },
                onSelect = { viewModel.select(it) },
                onRequestDelete = if (kind == "analysis") {
                    { targets -> pendingDeletion = targets }
                } else {
                    null
                },
            )
        }
    }
    if (pendingDeletion.isNotEmpty()) {
        val issue = pendingDeletion.first().issue.ifBlank { "未记录" }
        val targetText = if (pendingDeletion.size == 1) {
            "第 $issue 期的这条分析记录"
        } else {
            "第 $issue 期的 ${pendingDeletion.size} 条分析记录"
        }
        AlertDialog(
            onDismissRequest = { if (!viewModel.isDeleting) pendingDeletion = emptyList() },
            title = { Text("删除分析结果？") },
            text = { Text("将删除${targetText}及其归档文件。此操作无法撤销。") },
            confirmButton = {
                TextButton(
                    enabled = !viewModel.isDeleting,
                    onClick = {
                        val targets = pendingDeletion
                        pendingDeletion = emptyList()
                        viewModel.deleteAnalysisEntries(localEngine, targets)
                    },
                ) {
                    Text("删除", color = Color(0xFFB42318))
                }
            },
            dismissButton = {
                TextButton(
                    enabled = !viewModel.isDeleting,
                    onClick = { pendingDeletion = emptyList() },
                ) {
                    Text("取消")
                }
            },
        )
    }
}

@Composable
fun ReviewScreen(
    localEngine: FootballLotteryLocalEngine,
    viewModel: ReviewViewModel,
    historyViewModel: HistoryViewModel,
) {
    LaunchedEffect(viewModel.report?.issue) {
        if (viewModel.report != null) {
            historyViewModel.refresh(localEngine)
        }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { ReviewRequestCard(localEngine, viewModel) }
        if (viewModel.error.isNotBlank()) {
            item { StatusCard(text = viewModel.error, color = Color(0xFFB42318)) }
        }
        if (viewModel.message.isNotBlank()) {
            item { StatusCard(text = viewModel.message, color = Color(0xFF16845B)) }
        }
        item {
            HistorySection(
                localEngine = localEngine,
                viewModel = historyViewModel,
                kind = "review",
                title = "历史复盘报告",
            )
        }
    }
}

@Composable
fun SinglePredictionScreen(localEngine: FootballLotteryLocalEngine, viewModel: SinglePredictionViewModel) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { SinglePredictionForm(localEngine, viewModel) }
        if (viewModel.error.isNotBlank()) {
            item { StatusCard(text = viewModel.error, color = Color(0xFFB42318)) }
        }
        viewModel.result?.let { result ->
            item { SinglePredictionResultCard(result) }
        }
    }
}

@Composable
fun SettingsScreen(appViewModel: AppViewModel, localEngine: FootballLotteryLocalEngine) {
    val context = LocalContext.current
    LaunchedEffect(Unit) {
        if (appViewModel.theOddsApiKey.isNotBlank() && appViewModel.apiUsage == null) {
            appViewModel.refreshForeignOddsUsage(localEngine)
        }
    }
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
                Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("设置", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(
                        "App 版本 0.2.3（5） · 已支持分析完成后自动推送到飞书",
                        color = Color(0xFF2364AA),
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        "当前为手机本机独立模式：分析引擎已经打包进 App，不需要电脑后端，也不需要填写后端地址。生成当前期分析时，手机需要联网抓取赛程和赔率数据。",
                        color = Color(0xFF667085),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    OutlinedTextField(
                        value = appViewModel.theOddsApiKey,
                        onValueChange = appViewModel::updateTheOddsApiKey,
                        label = { Text("The Odds API Key") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        visualTransformation = PasswordVisualTransformation(),
                    )
                    Button(
                        onClick = {
                            appViewModel.saveSettings(context.applicationContext)
                            appViewModel.refreshForeignOddsUsage(localEngine)
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("保存并检查 API Key")
                    }
                    if (appViewModel.settingsMessage.isNotBlank()) {
                        StatusCard(text = appViewModel.settingsMessage, color = Color(0xFF16845B))
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("The Odds API 用量", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                        Button(
                            onClick = { appViewModel.refreshForeignOddsUsage(localEngine) },
                            enabled = !appViewModel.isCheckingApiUsage,
                        ) {
                            LoadingPrefix(appViewModel.isCheckingApiUsage)
                            Text(if (appViewModel.isCheckingApiUsage) "查询中" else "刷新用量")
                        }
                    }
                    appViewModel.apiUsage?.let { usage ->
                        ForeignOddsUsageCard(usage)
                    }
                    Text(
                        "用量查询调用官方 /v4/sports 接口，不消耗赔率额度。这里的 API 状态与下面的本机引擎状态相互独立。",
                        color = Color(0xFF667085),
                        style = MaterialTheme.typography.bodySmall,
                    )
                    HorizontalDivider()
                    Text("飞书推送", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(
                        "填写飞书群自定义机器人的 Webhook 后，App 可在每次分析完成时直接把出票建议推送到该群。Webhook 仅保存在本机。",
                        color = Color(0xFF667085),
                        style = MaterialTheme.typography.bodySmall,
                    )
                    OutlinedTextField(
                        value = appViewModel.feishuWebhookUrl,
                        onValueChange = appViewModel::updateFeishuWebhookUrl,
                        label = { Text("飞书机器人 Webhook") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        visualTransformation = PasswordVisualTransformation(),
                    )
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(
                            checked = appViewModel.feishuAutoSend,
                            onCheckedChange = appViewModel::updateFeishuAutoSend,
                        )
                        Text("每次分析完成后自动发送出票建议")
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = { appViewModel.saveFeishuSettings(context.applicationContext) },
                            modifier = Modifier.weight(1f),
                        ) {
                            Text("保存飞书设置")
                        }
                        Button(
                            onClick = { appViewModel.testFeishu(localEngine) },
                            enabled = !appViewModel.isTestingFeishu,
                            modifier = Modifier.weight(1f),
                        ) {
                            LoadingPrefix(appViewModel.isTestingFeishu)
                            Text(if (appViewModel.isTestingFeishu) "发送中" else "测试推送")
                        }
                    }
                    if (appViewModel.feishuTestMessage.isNotBlank()) {
                        StatusCard(text = appViewModel.feishuTestMessage, color = Color(0xFF16845B))
                    }
                    if (appViewModel.feishuTestError.isNotBlank()) {
                        StatusCard(text = appViewModel.feishuTestError, color = Color(0xFFB42318))
                    }
                    HorizontalDivider()
                    Button(
                        onClick = { appViewModel.testLocalEngine(localEngine) },
                        enabled = !appViewModel.isTestingConnection,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        LoadingPrefix(appViewModel.isTestingConnection)
                        Text(if (appViewModel.isTestingConnection) "测试中" else "测试本机引擎")
                    }
                    if (appViewModel.connectionMessage.isNotBlank()) {
                        StatusCard(text = appViewModel.connectionMessage, color = Color(0xFF16845B))
                    }
                    if (appViewModel.connectionError.isNotBlank()) {
                        StatusCard(text = appViewModel.connectionError, color = Color(0xFFB42318))
                    }
                }
            }
        }
    }
}

@Composable
private fun ForeignOddsUsageCard(usage: ForeignOddsUsage) {
    val color = when (usage.status) {
        "valid" -> Color(0xFF16845B)
        "not_configured" -> Color(0xFF667085)
        else -> Color(0xFFB42318)
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(color.copy(alpha = 0.10f), RoundedCornerShape(8.dp))
            .padding(10.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(usage.message, color = color, fontWeight = FontWeight.Bold)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            MetricTile("剩余额度", usage.creditsRemaining?.toString() ?: "--", Modifier.weight(1f))
            MetricTile("累计已用", usage.creditsUsed?.toString() ?: "--", Modifier.weight(1f))
            MetricTile("本次查询", usage.creditsLast?.toString() ?: "--", Modifier.weight(1f))
        }
        val details = buildList {
            if (usage.activeSports > 0) add("当前开放项目 ${usage.activeSports} 个")
            if (usage.checkedAt.isNotBlank()) add("查询时间 ${usage.checkedAt.replace('T', ' ')}")
        }
        if (details.isNotEmpty()) {
            Text(details.joinToString(" · "), color = Color(0xFF667085), style = MaterialTheme.typography.bodySmall)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RequestCard(
    localEngine: FootballLotteryLocalEngine,
    viewModel: AnalysisViewModel,
    appViewModel: AppViewModel,
) {
    val context = LocalContext.current.applicationContext
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("生成分析", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = viewModel.issue,
                    onValueChange = { viewModel.updateIssue(it, context) },
                    label = { Text("期号") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.weight(1f),
                    singleLine = true,
                )
                OutlinedTextField(
                    value = viewModel.maxTicketCostYuan,
                    onValueChange = { viewModel.updateMaxTicketCostYuan(it, context) },
                    label = { Text("最高购彩金额") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.weight(1f),
                    singleLine = true,
                )
            }
            Text(
                "默认执行完整分析，增强样本固定为最近 20 场；检测到关键资料源网络故障时自动降级为简单分析，并在结论理由中列出未获得的信息来源。",
                color = Color(0xFF667085),
                style = MaterialTheme.typography.bodySmall,
            )
            Button(
                onClick = {
                    viewModel.generateAnalysis(
                        localEngine,
                        appViewModel.theOddsApiKey,
                        appViewModel.feishuAutoSend,
                        appViewModel.feishuWebhookUrl,
                    )
                },
                enabled = !viewModel.isLoading,
                modifier = Modifier.fillMaxWidth(),
            ) {
                LoadingPrefix(viewModel.isLoading)
                Text(if (viewModel.isLoading) "生成中" else "生成分析报告")
            }
        }
    }
}

@Composable
private fun SinglePredictionForm(localEngine: FootballLotteryLocalEngine, viewModel: SinglePredictionViewModel) {
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("单场预测", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            OutlinedTextField(
                value = viewModel.home,
                onValueChange = viewModel::updateHome,
                label = { Text("主队") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            OutlinedTextField(
                value = viewModel.away,
                onValueChange = viewModel::updateAway,
                label = { Text("客队") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OddsField("主胜", viewModel.homeOdds, viewModel::updateHomeOdds, Modifier.weight(1f))
                OddsField("平", viewModel.drawOdds, viewModel::updateDrawOdds, Modifier.weight(1f))
                OddsField("客胜", viewModel.awayOdds, viewModel::updateAwayOdds, Modifier.weight(1f))
            }
            Button(
                onClick = { viewModel.predict(localEngine) },
                enabled = !viewModel.isLoading,
                modifier = Modifier.fillMaxWidth(),
            ) {
                LoadingPrefix(viewModel.isLoading)
                Text(if (viewModel.isLoading) "预测中" else "开始预测")
            }
        }
    }
}

@Composable
private fun OddsField(label: String, value: String, onValueChange: (String) -> Unit, modifier: Modifier) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        modifier = modifier,
        singleLine = true,
    )
}

@Composable
private fun ReviewRequestCard(localEngine: FootballLotteryLocalEngine, viewModel: ReviewViewModel) {
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("生成复盘", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            OutlinedTextField(
                value = viewModel.issue,
                onValueChange = viewModel::updateIssue,
                label = { Text("期号") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(
                    checked = viewModel.autoResults,
                    onCheckedChange = viewModel::updateAutoResults,
                )
                Text("自动拉取开奖结果")
            }
            if (!viewModel.autoResults) {
                OutlinedTextField(
                    value = viewModel.resultsCsv,
                    onValueChange = viewModel::updateResultsCsv,
                    label = { Text("赛果 CSV") },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 4,
                )
            }
            if (viewModel.analysisCandidates.size > 1) {
                AnalysisHistoryDropdown(
                    entries = viewModel.analysisCandidates,
                    selectedId = viewModel.selectedAnalysisId,
                    onSelect = viewModel::selectAnalysis,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            Button(
                onClick = { viewModel.generateReview(localEngine) },
                enabled = !viewModel.isLoading,
                modifier = Modifier.fillMaxWidth(),
            ) {
                LoadingPrefix(viewModel.isLoading)
                Text(if (viewModel.isLoading) "复盘中" else "生成复盘报告")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AnalysisHistoryDropdown(
    entries: List<HistoryEntry>,
    selectedId: String,
    onSelect: (HistoryEntry) -> Unit,
    modifier: Modifier = Modifier,
) {
    var expanded by remember { mutableStateOf(false) }
    val selected = entries.firstOrNull { it.id == selectedId }
    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = { expanded = it },
        modifier = modifier,
    ) {
        OutlinedTextField(
            value = selected?.let(::analysisHistoryLabel).orEmpty(),
            onValueChange = {},
            readOnly = true,
            label = { Text("选择复盘依据") },
            placeholder = { Text("请选择一次分析结果") },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            modifier = Modifier
                .menuAnchor()
                .fillMaxWidth(),
            singleLine = true,
        )
        ExposedDropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
        ) {
            entries.forEach { entry ->
                DropdownMenuItem(
                    text = { Text(analysisHistoryLabel(entry)) },
                    onClick = {
                        onSelect(entry)
                        expanded = false
                    },
                )
            }
        }
    }
    Text(
        text = "该期有 ${entries.size} 次分析，请选择本次复盘要对照的结果。",
        color = Color(0xFF667085),
        style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun HeaderCard(
    title: String,
    subtitle: String,
    buttonText: String,
    buttonEnabled: Boolean,
    onClick: () -> Unit,
) {
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Row(
            modifier = Modifier.padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(subtitle, color = Color(0xFF667085), style = MaterialTheme.typography.bodyMedium)
            }
            Button(onClick = onClick, enabled = buttonEnabled) {
                if (!buttonEnabled) LoadingPrefix(true)
                Text(buttonText)
            }
        }
    }
}

@Composable
private fun SummaryCard(report: AnalysisReport) {
    val isReview = report.purchaseDeadlineSource == "复盘报告"
    val keepSet = report.choose9Keep.toSet()
    val choose9Total = report.choose9Keep.size
    val choose9Hits = report.predictions.count { prediction ->
        prediction.seq in keepSet && prediction.outcomeHit
    }
    val choose9Rate = if (choose9Total > 0) choose9Hits * 100.0 / choose9Total else 0.0
    val purchaseCostText = purchaseCostText(report)
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(
                    "第 ${report.issue} 期",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f),
                )
                if (!isReview && purchaseCostText.isNotBlank()) {
                    Text(
                        purchaseCostText,
                        color = Color(0xFF2364AA),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                    )
                }
            }
            Text(
                text = if (isReview) "赛后复盘结果" else deadlineText(report),
                style = MaterialTheme.typography.bodyMedium,
                color = Color(0xFF667085),
            )
            if (!isReview && report.analysisModeMessage.isNotBlank()) {
                Text(
                    text = report.analysisModeMessage,
                    color = if (report.analysisMode == "simple_fallback") Color(0xFFB54708) else Color(0xFF16845B),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (!isReview) {
                report.foreignOddsStatus?.let { status ->
                    ForeignOddsStatusCard(status)
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MetricTile("比赛", report.metrics.matchCount.toString(), Modifier.weight(1f))
                MetricTile(if (isReview) "模型单选命中" else "模型单选", report.metrics.singleCount.toString(), Modifier.weight(1f))
            }
            if (!isReview && report.metrics.budgetForcedSingleCount > 0) {
                Text(
                    text = "预算票面含 ${report.metrics.budgetForcedSingleCount} 场强制单选；这些场次不属于模型胆材。",
                    color = Color(0xFFB54708),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (isReview) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    MetricTile("胜平负命中", report.metrics.lowRiskCount.toString(), Modifier.weight(1f))
                    MetricTile("胜平负命中率", "%.1f%%".format(report.metrics.averageConfidence), Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    MetricTile("任选九命中", "$choose9Hits/$choose9Total", Modifier.weight(1f))
                    MetricTile("任选九命中率", "%.1f%%".format(choose9Rate), Modifier.weight(1f))
                }
                report.reviewDiagnostics?.let { diagnostics ->
                    ReviewDiagnosticsCard(diagnostics)
                }
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    MetricTile("平均置信度", "%.1f%%".format(report.metrics.averageConfidence), Modifier.weight(1f))
                }
            }
            if (!isReview) {
                SequenceLine("任选九保留", report.choose9Keep, Color(0xFF16845B))
                SequenceLine("建议剔除", report.choose9Drop, Color(0xFFB42318))
                report.modelCalibration?.let { calibration ->
                    Text(
                        text = calibrationText(calibration),
                        style = MaterialTheme.typography.bodySmall,
                        color = Color(0xFF667085),
                    )
                }
            }
        }
    }
}

@Composable
private fun ForeignOddsStatusCard(status: ForeignOddsStatus) {
    val color = when (status.status) {
        "success_live", "success_cache" -> Color(0xFF16845B)
        "not_requested" -> Color(0xFF667085)
        "not_configured", "no_supported_leagues", "called_no_match", "called_no_events",
        "cache_no_match", "cache_no_events" -> Color(0xFFB26A00)
        else -> Color(0xFFB42318)
    }
    val title = when (status.status) {
        "success_live" -> "The Odds API：本次已联网调用"
        "success_cache" -> "The Odds API：本次使用缓存"
        "not_requested" -> "The Odds API：本次未启用"
        "not_configured" -> "The Odds API：尚未配置 Key"
        "out_of_credits" -> "The Odds API：额度已用完"
        "invalid_key" -> "The Odds API：Key 无效"
        "rate_limited" -> "The Odds API：请求受限"
        "called_no_match" -> "The Odds API：已调用但未匹配"
        "called_no_events" -> "The Odds API：已调用但无赛事"
        "cache_no_match", "cache_no_events" -> "The Odds API：缓存无可用匹配"
        else -> "The Odds API：调用异常"
    }
    val requestText = "联网请求 ${status.attemptedQueries} 次 · 成功 ${status.successfulQueries} 次 · " +
        "缓存 ${status.cacheHits} 次 · 匹配 ${status.matchedMatches}/${status.totalMatches} 场"
    val quotaParts = buildList {
        status.creditsRemaining?.let { add("剩余 $it") }
        status.creditsUsed?.let { add("累计已用 $it") }
        status.creditsLast?.let { add("本次消耗 $it") }
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(color.copy(alpha = 0.10f), RoundedCornerShape(8.dp))
            .padding(10.dp),
        verticalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Text(title, color = color, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium)
        if (status.message.isNotBlank()) {
            Text(status.message, color = Color(0xFF344054), style = MaterialTheme.typography.bodySmall)
        }
        Text(requestText, color = Color(0xFF667085), style = MaterialTheme.typography.bodySmall)
        if (quotaParts.isNotEmpty()) {
            Text(
                "额度：${quotaParts.joinToString(" · ")}",
                color = Color(0xFF667085),
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

private fun calibrationText(calibration: ModelCalibration): String {
    return if (calibration.status == "experiment_active") {
        "纯胜平负权重已通过严格赛前走步回测：赔率 ${"%.0f".format(calibration.oddsWeight * 100)}% · 基本面 ${"%.0f".format(calibration.signalsWeight * 100)}% · Dixon-Coles ${"%.0f".format(calibration.dixonColesWeight * 100)}%"
    } else {
        "纯胜平负回测：已收集 ${calibration.sampleCount}/${calibration.minimumSamples} 场真实复盘，未通过晋级门槛前使用默认权重。"
    }
}

@Composable
private fun ReviewDiagnosticsCard(diagnostics: ReviewDiagnostics) {
    val issueText = if (diagnostics.issueMissCount == 0) {
        "本期胜平负推荐全部覆盖"
    } else {
        "本期 ${diagnostics.issueMissCount} 场未中：" + diagnostics.issueTags.joinToString(" · ") {
            "${it.label} ${it.count}"
        }
    }
    Card(
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(containerColor = Color(0xFFF6F8FC)),
    ) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("复盘诊断", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall)
            Text(issueText, color = Color(0xFF344054), style = MaterialTheme.typography.bodySmall)
            if (diagnostics.historyTags.isNotEmpty()) {
                Text(
                    "近 ${diagnostics.historyIssueCount} 期：" + diagnostics.historyTags.take(3).joinToString(" · ") {
                        "${it.label} ${it.count}"
                    },
                    color = Color(0xFF667085),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun PredictionCard(
    prediction: MatchPrediction,
    isReview: Boolean = false,
    choose9Keep: Set<Int> = emptySet(),
    expandCommand: PredictionExpandCommand? = null,
) {
    var expanded by remember(prediction.seq, prediction.home, prediction.away) { mutableStateOf(false) }
    LaunchedEffect(expandCommand?.revision) {
        expandCommand?.let { command -> expanded = command.expanded }
    }
    val cardModifier = if (isReview) {
        Modifier.fillMaxWidth()
    } else {
        Modifier
            .fillMaxWidth()
            .clickable { expanded = !expanded }
    }
    Card(
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (expanded && !isReview) Color(0xFFF7FAFF) else Color.White,
        ),
        modifier = cardModifier,
    ) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = prediction.seq.toString(),
                    color = Color(0xFF2364AA),
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier
                        .background(Color(0xFFE8F0FB), RoundedCornerShape(6.dp))
                        .padding(horizontal = 10.dp, vertical = 6.dp),
                )
                Spacer(modifier = Modifier.width(10.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "${prediction.home} vs ${prediction.away}",
                        fontWeight = FontWeight.Bold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        text = "${prediction.league} · ${prediction.kickoffDisplay}",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color(0xFF667085),
                    )
                }
                val finalText = resultText(prediction)
                if (finalText.isNotBlank()) {
                    Text(
                        text = finalText,
                        color = if (prediction.outcomeHit) Color(0xFF16845B) else Color(0xFFB42318),
                        fontWeight = FontWeight.Bold,
                    )
                } else if (!isReview) {
                    Text(
                        text = if (expanded) "收起" else "查看",
                        color = Color(0xFF2364AA),
                        fontWeight = FontWeight.Bold,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            if (isReview) {
                Text(
                    text = recommendationText(prediction),
                    color = Color(0xFFB42318),
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.titleSmall,
                )
                budgetSelectionText(prediction)?.let { text ->
                    Text(
                        text = text,
                        color = if (prediction.budgetForcedSingle) Color(0xFFB54708) else Color(0xFF667085),
                        style = MaterialTheme.typography.bodySmall,
                        fontWeight = if (prediction.budgetForcedSingle) FontWeight.Bold else FontWeight.Normal,
                    )
                }
                Text(
                    text = "任选九选择：" + if (prediction.seq in choose9Keep) "保留" else "未选",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (prediction.seq in choose9Keep) Color(0xFF16845B) else Color(0xFF667085),
                )
                Text(
                    text = if (prediction.outcomeHit) {
                        "复盘结论：本场推荐已命中"
                    } else {
                        val externalReason = prediction.postMatchEvidence.joinToString("；") { evidence ->
                            "${evidence.label}：${evidence.summary}"
                        }
                        val modelReason = prediction.diagnosticTags.joinToString("、").ifBlank { "赛前概率偏差" }
                        "分析未正确原因：" + if (externalReason.isBlank()) {
                            "未找到可验证的赛后报道。模型诊断：$modelReason"
                        } else {
                            "赛后报道线索：$externalReason\n模型诊断：$modelReason"
                        }
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = if (prediction.outcomeHit) Color(0xFF16845B) else Color(0xFFB54708),
                )
            } else if (expanded) {
                HorizontalDivider()
                Text(
                    text = "分析结论",
                    color = Color(0xFF667085),
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    text = recommendationText(prediction),
                    color = Color(0xFFB42318),
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.titleSmall,
                )
                budgetSelectionText(prediction)?.let { text ->
                    Text(
                        text = text,
                        color = if (prediction.budgetForcedSingle) Color(0xFFB54708) else Color(0xFF667085),
                        style = MaterialTheme.typography.bodySmall,
                        fontWeight = if (prediction.budgetForcedSingle) FontWeight.Bold else FontWeight.Normal,
                    )
                }
                Text(
                    text = "风险 ${prediction.risk} · 任九${if (prediction.seq in choose9Keep) "保留" else "剔除"}",
                    color = Color(0xFF667085),
                    style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    text = "胜平负概率",
                    color = Color(0xFF667085),
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.bodySmall,
                )
                ProbabilityLine("主胜", prediction.probabilities.home, Color(0xFFB42318))
                ProbabilityLine("平局", prediction.probabilities.draw, Color(0xFF2364AA))
                ProbabilityLine("客胜", prediction.probabilities.away, Color(0xFF16845B))
                Text(
                    text = "置信度 ${"%.1f".format(prediction.confidence)}%",
                    color = Color(0xFF2364AA),
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.titleSmall,
                )
                Text(
                    text = "得出结论的理由",
                    color = Color(0xFF667085),
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.bodySmall,
                )
                if (prediction.reasons.isEmpty()) {
                    Text(
                        text = "当前没有可展示的结论依据。",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color(0xFF475467),
                    )
                } else {
                    prediction.reasons.forEachIndexed { index, reason ->
                        Text(
                            text = "${index + 1}. $reason",
                            style = MaterialTheme.typography.bodySmall,
                            color = if (
                                reason.startsWith("完整分析资料审计") &&
                                "缺失或未匹配 无" !in reason
                            ) {
                                Color(0xFFB54708)
                            } else {
                                Color(0xFF475467)
                            },
                        )
                    }
                }
                Text(
                    text = "再次点击本场比赛即可收起",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color(0xFF2364AA),
                )
            }
        }
    }
}

private data class PredictionExpandCommand(
    val expanded: Boolean,
    val revision: Int,
)

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun HistoryGroupCard(
    group: HistoryGroup,
    selectedEntry: HistoryEntry?,
    expanded: Boolean,
    onToggle: () -> Unit,
    onSelect: (HistoryEntry) -> Unit,
    onRequestDelete: ((List<HistoryEntry>) -> Unit)?,
) {
    var allPredictionsExpanded by remember(selectedEntry?.id) { mutableStateOf(false) }
    var predictionExpandRevision by remember(selectedEntry?.id) { mutableStateOf(0) }
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .then(
                        if (onRequestDelete != null) {
                            Modifier.combinedClickable(
                                onClick = onToggle,
                                onLongClick = { onRequestDelete(group.entries) },
                            )
                        } else {
                            Modifier.clickable(onClick = onToggle)
                        },
                    ),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "${kindLabel(group.kind)} · 第 ${group.issue.ifBlank { "未记录" }} 期",
                        fontWeight = FontWeight.Bold,
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        text = "${group.entries.size} 条记录，最新 ${group.entries.firstOrNull()?.createdAt.orEmpty()}" +
                            if (onRequestDelete != null) " · 长按删除" else "",
                        color = Color(0xFF667085),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Text(if (expanded) "收起" else "展开", color = Color(0xFF2364AA), fontWeight = FontWeight.Bold)
            }
            if (expanded) {
                group.entries.forEach { entry ->
                    HistoryEntryCard(
                        entry = entry,
                        selected = selectedEntry?.id == entry.id,
                        onClick = { onSelect(entry) },
                        onLongClick = onRequestDelete?.let { request -> { request(listOf(entry)) } },
                    )
                    if (selectedEntry?.id == entry.id) {
                        entry.report?.let { report ->
                            SummaryCard(report)
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    text = if (entry.kind == "review") "逐场复盘" else "逐场预测",
                                    style = MaterialTheme.typography.titleMedium,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.weight(1f),
                                )
                                if (entry.kind != "review") {
                                    TextButton(
                                        onClick = {
                                            allPredictionsExpanded = !allPredictionsExpanded
                                            predictionExpandRevision += 1
                                        },
                                    ) {
                                        Text(if (allPredictionsExpanded) "一键收起" else "一键查看")
                                    }
                                }
                            }
                            report.predictions.forEach { prediction ->
                                PredictionCard(
                                    prediction = prediction,
                                    isReview = entry.kind == "review",
                                    choose9Keep = report.choose9Keep.toSet(),
                                    expandCommand = if (entry.kind == "review") {
                                        null
                                    } else {
                                        PredictionExpandCommand(
                                            expanded = allPredictionsExpanded,
                                            revision = predictionExpandRevision,
                                        )
                                    },
                                )
                            }
                        } ?: EmptyCard("历史详情", "这条历史记录暂时没有可结构化展示的数据。")
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun HistoryEntryCard(
    entry: HistoryEntry,
    selected: Boolean,
    onClick: () -> Unit,
    onLongClick: (() -> Unit)?,
) {
    val context = LocalContext.current
    fun openUrl(url: String) {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    }

    Card(
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(containerColor = if (selected) Color(0xFFE8F0FB) else Color(0xFFF7F9FC)),
        modifier = if (onLongClick != null) {
            Modifier.combinedClickable(onClick = onClick, onLongClick = onLongClick)
        } else {
            Modifier.clickable(onClick = onClick)
        },
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(entry.title.ifBlank { "第 ${entry.issue} 期报告" }, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                Text(kindLabel(entry.kind), color = Color(0xFF2364AA), style = MaterialTheme.typography.bodySmall)
            }
            Text(entry.createdAt.ifBlank { "未记录时间" }, color = Color(0xFF667085), style = MaterialTheme.typography.bodySmall)
            Text(
                (if (selected) "再次点击收起" else "点击展开") + if (onLongClick != null) " · 长按删除" else "",
                color = Color(0xFF667085),
                style = MaterialTheme.typography.bodySmall,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (isWebUrl(entry.htmlUrl)) {
                    Button(onClick = { openUrl(entry.htmlUrl) }) {
                        Text("打开 HTML")
                    }
                }
                if (isWebUrl(entry.markdownUrl)) {
                    Button(onClick = { openUrl(entry.markdownUrl) }) {
                        Text("打开 Markdown")
                    }
                }
            }
        }
    }
}

private fun recommendationText(prediction: MatchPrediction): String {
    val labels = prediction.analysisPickLabels.ifEmpty { prediction.analysisPickText.split("/") }
    return "模型建议：${labels.joinToString(" / ")}（${prediction.analysisPickText}）"
}

private fun budgetSelectionText(prediction: MatchPrediction): String? {
    if (!prediction.budgetAdjusted) {
        return null
    }
    val labels = prediction.pickLabels.ifEmpty { prediction.pickText.split("/") }
    val warning = if (prediction.budgetForcedSingle) "；预算强制单选，不等于模型胆材" else ""
    return "预算票面：${labels.joinToString(" / ")}（${prediction.pickText}）$warning"
}

private fun resultText(prediction: MatchPrediction): String {
    if (prediction.finalResultLabel.isBlank()) {
        return ""
    }
    return if (prediction.finalScore.isBlank()) {
        prediction.finalResultLabel
    } else {
        "${prediction.finalResultLabel}\n${prediction.finalScore}"
    }
}

private fun purchaseCostText(report: AnalysisReport): String {
    val units = report.predictions.fold(1L) { total, prediction ->
        total * recommendedChoiceCount(prediction).toLong()
    }
    if (units <= 0L) {
        return ""
    }
    return "购彩 ¥${"%,d".format(units * 2L)}"
}

private fun feishuAnalysisText(report: AnalysisReport): String = buildString {
    appendLine("足球彩票分析 · 第 ${report.issue} 期")
    appendLine(deadlineText(report))
    purchaseCostText(report).takeIf { it.isNotBlank() }?.let(::appendLine)
    appendLine("任选九保留：${report.choose9Keep.joinToString("、")}")
    appendLine("建议剔除：${report.choose9Drop.joinToString("、")}")
    appendLine()
    appendLine("14 场出票建议")
    report.predictions.forEach { prediction ->
        val selection = prediction.pickLabels.ifEmpty { prediction.pickText.split("/") }.joinToString("/")
        appendLine("${prediction.seq}. ${prediction.home} vs ${prediction.away}：$selection（${prediction.pickText}）")
    }
    appendLine()
    append("仅供信息分析和娱乐参考，请理性购彩。")
}

private fun recommendedChoiceCount(prediction: MatchPrediction): Int {
    val pickCount = prediction.pickText
        .split("/")
        .count { it.isNotBlank() }
    if (pickCount > 0) {
        return pickCount
    }
    return prediction.pickLabels.size.coerceAtLeast(1)
}

private fun historyGroups(entries: List<HistoryEntry>): List<HistoryGroup> {
    return entries
        .groupBy { historyGroupKey(it) }
        .map { (key, items) ->
            val first = items.first()
            HistoryGroup(
                key = key,
                issue = first.issue,
                kind = first.kind,
                entries = items,
            )
        }
}

private fun historyGroupKey(entry: HistoryEntry): String {
    return "${entry.kind.ifBlank { "analysis" }}:${entry.issue.ifBlank { "unknown" }}"
}

private fun analysisHistoryLabel(entry: HistoryEntry): String {
    val time = entry.createdAt.ifBlank { entry.id }
    return "$time · ${entry.title.ifBlank { "第 ${entry.issue} 期分析报告" }}"
}

private fun kindLabel(kind: String): String {
    return if (kind == "review") "复盘" else "分析"
}

private fun isWebUrl(value: String): Boolean {
    return value.startsWith("http://") || value.startsWith("https://")
}

private fun resolveReportUrl(baseUrl: String, url: String): String {
    if (url.startsWith("http://") || url.startsWith("https://")) {
        return url
    }
    val cleanBase = baseUrl.trim().trimEnd('/')
    val cleanPath = if (url.startsWith("/")) url else "/$url"
    return cleanBase + cleanPath
}

@Composable
private fun SinglePredictionResultCard(result: SinglePredictionResult) {
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("${result.home} vs ${result.away}", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text("数据源：${result.dataSource.ifBlank { "本地模型" }}", color = Color(0xFF667085), style = MaterialTheme.typography.bodySmall)
                }
                Text(result.pickLabel, color = Color(0xFF2364AA), fontWeight = FontWeight.Bold)
            }
            HorizontalDivider()
            ProbabilityLine("主胜", result.probabilities.home, Color(0xFFB42318))
            ProbabilityLine("平", result.probabilities.draw, Color(0xFF2364AA))
            ProbabilityLine("客胜", result.probabilities.away, Color(0xFF16845B))
            Text("置信度 ${"%.1f".format(result.confidence)}% · 风险 ${result.risk}", color = Color(0xFF667085))
            Text(
                text = "比分倾向：" + result.scorelines.joinToString("，") { "${it.score} ${"%.1f".format(it.probability)}%" },
                color = Color(0xFF087F8C),
                style = MaterialTheme.typography.bodySmall,
            )
            result.reasons.take(3).forEach { reason ->
                Text("· $reason", color = Color(0xFF344054), style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun MetricTile(title: String, value: String, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .background(Color(0xFFF0F4FA), RoundedCornerShape(8.dp))
            .padding(10.dp),
    ) {
        Text(title, style = MaterialTheme.typography.bodySmall, color = Color(0xFF667085))
        Text(value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun SequenceLine(title: String, values: List<Int>, color: Color) {
    Row {
        Text(title, fontWeight = FontWeight.Bold, modifier = Modifier.width(88.dp))
        Text(values.joinToString("  "), color = color)
    }
}

@Composable
private fun ProbabilityLine(title: String, value: Double, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(title, modifier = Modifier.width(44.dp), style = MaterialTheme.typography.bodySmall)
        LinearProgressIndicator(
            progress = { (value / 100.0).toFloat().coerceIn(0f, 1f) },
            modifier = Modifier.weight(1f),
            color = color,
        )
        Text(
            text = "%.1f%%".format(value),
            modifier = Modifier.width(58.dp),
            style = MaterialTheme.typography.bodySmall,
            color = Color(0xFF667085),
        )
    }
}

@Composable
private fun LoadingPrefix(isLoading: Boolean) {
    if (isLoading) {
        CircularProgressIndicator(
            modifier = Modifier
                .height(18.dp)
                .width(18.dp),
            strokeWidth = 2.dp,
        )
        Spacer(modifier = Modifier.width(8.dp))
    }
}

@Composable
private fun StatusCard(text: String, color: Color) {
    Text(
        text = text,
        color = color,
        modifier = Modifier
            .fillMaxWidth()
            .background(color.copy(alpha = 0.12f), RoundedCornerShape(8.dp))
            .padding(12.dp),
    )
}

@Composable
private fun EmptyCard(title: String, text: String) {
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, fontWeight = FontWeight.Bold)
            Text(text, color = Color(0xFF667085))
        }
    }
}

@Composable
private fun FootballLotteryTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(primary = Color(0xFF2364AA)),
        content = content,
    )
}

private fun deadlineText(report: AnalysisReport): String {
    if (report.purchaseDeadline.isBlank()) {
        return "购彩截止时间暂未获取"
    }
    return if (report.purchaseDeadlineSource.isBlank()) {
        "购彩截止时间：${report.purchaseDeadline}"
    } else {
        "购彩截止时间：${report.purchaseDeadline} · ${report.purchaseDeadlineSource}"
    }
}

private fun parseForeignOddsStatus(json: JSONObject): ForeignOddsStatus = ForeignOddsStatus(
    status = json.optString("status"),
    message = json.optString("message"),
    requested = json.optBoolean("requested"),
    configured = json.optBoolean("configured"),
    attemptedQueries = json.optInt("attempted_queries"),
    successfulQueries = json.optInt("successful_queries"),
    cacheHits = json.optInt("cache_hits"),
    matchedMatches = json.optInt("matched_matches"),
    totalMatches = json.optInt("total_matches"),
    creditsRemaining = json.optNullableInt("credits_remaining"),
    creditsUsed = json.optNullableInt("credits_used"),
    creditsLast = json.optNullableInt("credits_last"),
)

private fun parseForeignOddsUsage(json: JSONObject): ForeignOddsUsage = ForeignOddsUsage(
    status = json.optString("status"),
    message = json.optString("message"),
    creditsRemaining = json.optNullableInt("credits_remaining"),
    creditsUsed = json.optNullableInt("credits_used"),
    creditsLast = json.optNullableInt("credits_last"),
    activeSports = json.optInt("active_sports"),
    checkedAt = json.optString("checked_at"),
)

private fun JSONObject.optNullableInt(key: String): Int? =
    if (has(key) && !isNull(key)) optInt(key) else null

private fun JSONArray?.orEmptyArray(): JSONArray = this ?: JSONArray()

private fun JSONArray.toIntList(): List<Int> = List(length()) { index -> optInt(index) }

private fun JSONArray.toStringList(): List<String> = List(length()) { index -> optString(index) }

private fun <T> JSONArray.mapObjects(transform: (JSONObject) -> T): List<T> =
    List(length()) { index -> transform(getJSONObject(index)) }
