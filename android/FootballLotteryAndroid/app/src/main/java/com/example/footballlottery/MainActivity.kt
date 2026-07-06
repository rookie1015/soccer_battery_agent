package com.example.footballlottery

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
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

data class AnalysisReport(
    val issue: String,
    val purchaseDeadline: String,
    val purchaseDeadlineSource: String,
    val saleBeginTime: String,
    val metrics: ReportMetrics,
    val choose9Keep: List<Int>,
    val choose9Drop: List<Int>,
    val predictions: List<MatchPrediction>,
)

data class ReportMetrics(
    val matchCount: Int,
    val singleCount: Int,
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
    val confidence: Double,
    val risk: String,
    val probabilities: OutcomeProbabilities,
    val scorelines: List<ScorelinePrediction>,
    val reasons: List<String>,
    val finalScore: String,
    val finalResult: String,
    val finalResultLabel: String,
    val outcomeHit: Boolean,
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
    var settingsMessage by mutableStateOf("")
        private set

    fun loadSettings(context: Context) {
        val prefs = context.getSharedPreferences(SETTINGS_PREFS, Context.MODE_PRIVATE)
        theOddsApiKey = prefs.getString(PREF_THE_ODDS_API_KEY, "").orEmpty()
    }

    fun updateTheOddsApiKey(value: String) {
        theOddsApiKey = value
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
    var issue by mutableStateOf("26090")
        private set
    var xgMatches by mutableDoubleStateOf(8.0)
        private set
    var fullAnalysis by mutableStateOf(false)
        private set
    var isLoading by mutableStateOf(false)
        private set
    var message by mutableStateOf("")
        private set
    var error by mutableStateOf("")
        private set
    var report by mutableStateOf<AnalysisReport?>(null)
        private set

    fun updateIssue(value: String) {
        issue = value
    }

    fun updateXgMatches(value: Double) {
        xgMatches = value
    }

    fun updateFullAnalysis(value: Boolean) {
        fullAnalysis = value
    }

    fun generateAnalysis(engine: FootballLotteryLocalEngine, foreignOddsApiKey: String) {
        val cleanIssue = issue.trim()
        val cleanForeignOddsApiKey = foreignOddsApiKey.trim()
        if (cleanIssue.isEmpty()) {
            error = "请填写期号。"
            return
        }
        viewModelScope.launch {
            isLoading = true
            error = ""
            message = ""
            runCatching {
                engine.generateAnalysis(
                    issue = cleanIssue,
                    xgMatches = xgMatches.toInt(),
                    fullAnalysis = fullAnalysis,
                    foreignOdds = fullAnalysis && cleanForeignOddsApiKey.isNotEmpty(),
                    foreignOddsApiKey = cleanForeignOddsApiKey,
                )
            }.onSuccess { response ->
                report = response
                message = "${response.issue} 分析报告已生成。"
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

    fun select(entry: HistoryEntry) {
        selectedEntry = entry
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

    fun updateIssue(value: String) {
        issue = value
    }

    fun updateAutoResults(value: Boolean) {
        autoResults = value
    }

    fun updateResultsCsv(value: String) {
        resultsCsv = value
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
                engine.generateReview(cleanIssue, autoResults, resultsCsv)
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

    suspend fun generateAnalysis(
        issue: String,
        xgMatches: Int,
        fullAnalysis: Boolean,
        foreignOdds: Boolean,
        foreignOddsApiKey: String,
    ): AnalysisReport = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("issue", issue)
            .put("strength_model", true)
            .put("strength_xg_matches", xgMatches)
            .put("full_analysis", fullAnalysis)
            .put("foreign_odds", foreignOdds)
            .put("foreign_odds_api_key", foreignOddsApiKey)
        val json = JSONObject(bridge.callAttr("analysis", body.toString(), workDir).toString())
        if (!json.optBoolean("ok", false)) {
            throw IllegalStateException(json.optString("error", "本机分析失败。"))
        }
        parseReport(json.getJSONObject("report"))
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

    suspend fun generateReview(issue: String, autoResults: Boolean, resultsCsv: String): AnalysisReport = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("issue", issue)
            .put("auto_results", autoResults)
            .put("results_csv", resultsCsv)
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
            metrics = ReportMetrics(
                matchCount = metrics.optInt("match_count"),
                singleCount = metrics.optInt("single_count"),
                lowRiskCount = metrics.optInt("low_risk_count"),
                averageConfidence = metrics.optDouble("average_confidence"),
            ),
            choose9Keep = json.optJSONArray("choose9_keep").orEmptyArray().toIntList(),
            choose9Drop = json.optJSONArray("choose9_drop").orEmptyArray().toIntList(),
            predictions = json.optJSONArray("predictions").orEmptyArray().mapObjects { parsePrediction(it) },
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
        xgMatches: Int,
        fullAnalysis: Boolean,
        foreignOdds: Boolean,
        foreignOddsApiKey: String,
    ): AnalysisReport = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("issue", issue)
            .put("strength_model", fullAnalysis)
            .put("strength_xg_matches", xgMatches)
            .put("full_analysis", fullAnalysis)
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

    suspend fun generateReview(issue: String, autoResults: Boolean, resultsCsv: String): AnalysisReport = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("issue", issue)
            .put("auto_results", autoResults)
            .put("results_csv", resultsCsv)
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
            metrics = ReportMetrics(
                matchCount = metrics.optInt("match_count"),
                singleCount = metrics.optInt("single_count"),
                lowRiskCount = metrics.optInt("low_risk_count"),
                averageConfidence = metrics.optDouble("average_confidence"),
            ),
            choose9Keep = json.optJSONArray("choose9_keep").orEmptyArray().toIntList(),
            choose9Drop = json.optJSONArray("choose9_drop").orEmptyArray().toIntList(),
            predictions = json.optJSONArray("predictions").orEmptyArray().mapObjects { parsePrediction(it) },
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
        historyGroups(entries).forEach { group ->
            HistoryGroupCard(
                group = group,
                selectedEntry = selectedEntry,
                expanded = group.key in viewModel.expandedGroups,
                onToggle = { viewModel.toggleGroup(group.key) },
                onSelect = { viewModel.select(it) },
            )
        }
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
                        onClick = { appViewModel.saveSettings(context.applicationContext) },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("保存外盘设置")
                    }
                    if (appViewModel.settingsMessage.isNotBlank()) {
                        StatusCard(text = appViewModel.settingsMessage, color = Color(0xFF16845B))
                    }
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RequestCard(
    localEngine: FootballLotteryLocalEngine,
    viewModel: AnalysisViewModel,
    appViewModel: AppViewModel,
) {
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("生成分析", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = viewModel.issue,
                    onValueChange = viewModel::updateIssue,
                    label = { Text("期号") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.weight(1f),
                    singleLine = true,
                )
                AnalysisModeDropdown(
                    fullAnalysis = viewModel.fullAnalysis,
                    onFullAnalysisChange = viewModel::updateFullAnalysis,
                    modifier = Modifier.weight(1f),
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("增强样本场次")
                Spacer(modifier = Modifier.weight(1f))
                Text(viewModel.xgMatches.toInt().toString(), fontWeight = FontWeight.Bold)
            }
            Text(
                if (viewModel.fullAnalysis) {
                    "完整分析会抓取新闻、伤停、交锋、实力模型、Polymarket 和已保存的外盘赔率，生成会明显变慢。"
                } else {
                    "简单分析只抓取赛程和轻量赔率，生成更快。"
                },
                color = Color(0xFF667085),
                style = MaterialTheme.typography.bodySmall,
            )
            Slider(
                value = viewModel.xgMatches.toFloat(),
                onValueChange = { viewModel.updateXgMatches(it.toDouble()) },
                valueRange = 0f..20f,
                steps = 19,
            )
            Button(
                onClick = { viewModel.generateAnalysis(localEngine, appViewModel.theOddsApiKey) },
                enabled = !viewModel.isLoading,
                modifier = Modifier.fillMaxWidth(),
            ) {
                LoadingPrefix(viewModel.isLoading)
                Text(if (viewModel.isLoading) "生成中" else "生成分析报告")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AnalysisModeDropdown(
    fullAnalysis: Boolean,
    onFullAnalysisChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    var expanded by remember { mutableStateOf(false) }
    val selectedText = if (fullAnalysis) "完整分析" else "简单分析"

    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = { expanded = it },
        modifier = modifier,
    ) {
        OutlinedTextField(
            value = selectedText,
            onValueChange = {},
            readOnly = true,
            label = { Text("分析模式") },
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
            DropdownMenuItem(
                text = { Text("简单分析") },
                onClick = {
                    onFullAnalysisChange(false)
                    expanded = false
                },
            )
            DropdownMenuItem(
                text = { Text("完整分析") },
                onClick = {
                    onFullAnalysisChange(true)
                    expanded = false
                },
            )
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
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("第 ${report.issue} 期", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(
                text = if (isReview) "赛后复盘结果" else deadlineText(report),
                style = MaterialTheme.typography.bodyMedium,
                color = Color(0xFF667085),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MetricTile("比赛", report.metrics.matchCount.toString(), Modifier.weight(1f))
                MetricTile(if (isReview) "单选命中" else "单选", report.metrics.singleCount.toString(), Modifier.weight(1f))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MetricTile(if (isReview) "胜平负命中" else "低风险", report.metrics.lowRiskCount.toString(), Modifier.weight(1f))
                MetricTile(if (isReview) "胜平负命中率" else "平均置信", "%.1f%%".format(report.metrics.averageConfidence), Modifier.weight(1f))
            }
            if (isReview) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    MetricTile("任选九命中", "$choose9Hits/$choose9Total", Modifier.weight(1f))
                    MetricTile("任选九命中率", "%.1f%%".format(choose9Rate), Modifier.weight(1f))
                }
            }
            if (!isReview) {
                SequenceLine("任选九保留", report.choose9Keep, Color(0xFF16845B))
                SequenceLine("建议剔除", report.choose9Drop, Color(0xFFB42318))
            }
        }
    }
}

@Composable
private fun PredictionCard(prediction: MatchPrediction) {
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
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
                }
            }
            Text(
                text = recommendationText(prediction),
                color = Color(0xFFB42318),
                fontWeight = FontWeight.Bold,
                style = MaterialTheme.typography.titleSmall,
            )
            ProbabilityLine("主胜", prediction.probabilities.home, Color(0xFFB42318))
            ProbabilityLine("平", prediction.probabilities.draw, Color(0xFF2364AA))
            ProbabilityLine("客胜", prediction.probabilities.away, Color(0xFF16845B))
            Text(
                text = "置信度 ${"%.1f".format(prediction.confidence)}% · 风险 ${prediction.risk}",
                color = Color(0xFF667085),
                style = MaterialTheme.typography.bodySmall,
            )
            Text(
                text = "比分倾向：" + prediction.scorelines.joinToString("，") { "${it.score} ${"%.1f".format(it.probability)}%" },
                style = MaterialTheme.typography.bodySmall,
                color = Color(0xFF087F8C),
            )
        }
    }
}

@Composable
private fun HistoryGroupCard(
    group: HistoryGroup,
    selectedEntry: HistoryEntry?,
    expanded: Boolean,
    onToggle: () -> Unit,
    onSelect: (HistoryEntry) -> Unit,
) {
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(onClick = onToggle),
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
                        text = "${group.entries.size} 条记录，最新 ${group.entries.firstOrNull()?.createdAt.orEmpty()}",
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
                    )
                    if (selectedEntry?.id == entry.id) {
                        entry.report?.let { report ->
                            SummaryCard(report)
                            Text(
                                text = if (entry.kind == "review") "逐场复盘" else "逐场预测",
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.Bold,
                            )
                            report.predictions.forEach { prediction ->
                                PredictionCard(prediction)
                            }
                        } ?: EmptyCard("历史详情", "这条历史记录暂时没有可结构化展示的数据。")
                    }
                }
            }
        }
    }
}

@Composable
private fun HistoryEntryCard(entry: HistoryEntry, selected: Boolean, onClick: () -> Unit) {
    val context = LocalContext.current
    fun openUrl(url: String) {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    }

    Card(
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(containerColor = if (selected) Color(0xFFE8F0FB) else Color(0xFFF7F9FC)),
        modifier = Modifier.clickable(onClick = onClick),
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(entry.title.ifBlank { "第 ${entry.issue} 期报告" }, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                Text(kindLabel(entry.kind), color = Color(0xFF2364AA), style = MaterialTheme.typography.bodySmall)
            }
            Text(entry.createdAt.ifBlank { "未记录时间" }, color = Color(0xFF667085), style = MaterialTheme.typography.bodySmall)
            Text(if (selected) "已展开" else "点击展开", color = Color(0xFF667085), style = MaterialTheme.typography.bodySmall)
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
    val labels = prediction.pickLabels.ifEmpty { prediction.pickText.split("/") }
    return "建议选择：${labels.joinToString(" / ")}（${prediction.pickText}）"
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

private fun JSONArray?.orEmptyArray(): JSONArray = this ?: JSONArray()

private fun JSONArray.toIntList(): List<Int> = List(length()) { index -> optInt(index) }

private fun JSONArray.toStringList(): List<String> = List(length()) { index -> optString(index) }

private fun <T> JSONArray.mapObjects(transform: (JSONObject) -> T): List<T> =
    List(length()) { index -> transform(getJSONObject(index)) }
