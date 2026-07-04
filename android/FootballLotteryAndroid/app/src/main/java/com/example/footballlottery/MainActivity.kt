package com.example.footballlottery

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
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
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
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
    History("历史"),
    Single("单场"),
    Settings("设置"),
}

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
    var baseUrl by mutableStateOf("http://10.0.2.2:8765")
        private set
    var isTestingConnection by mutableStateOf(false)
        private set
    var connectionMessage by mutableStateOf("")
        private set
    var connectionError by mutableStateOf("")
        private set

    fun updateBaseUrl(value: String) {
        baseUrl = value
        connectionMessage = ""
        connectionError = ""
    }

    fun testConnection() {
        viewModelScope.launch {
            isTestingConnection = true
            connectionMessage = ""
            connectionError = ""
            runCatching {
                FootballLotteryApi(baseUrl.trim()).fetchHistory()
            }.onSuccess { entries ->
                connectionMessage = "后端连接成功，读取到 ${entries.size} 条历史记录。"
            }.onFailure { throwable ->
                connectionError = throwable.message ?: "后端连接失败。"
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

    fun generateAnalysis(baseUrl: String) {
        val cleanIssue = issue.trim()
        if (cleanIssue.isEmpty()) {
            error = "请填写期号。"
            return
        }
        viewModelScope.launch {
            isLoading = true
            error = ""
            message = ""
            runCatching {
                FootballLotteryApi(baseUrl.trim()).generateAnalysis(cleanIssue, xgMatches.toInt())
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
    var error by mutableStateOf("")
        private set
    var entries by mutableStateOf<List<HistoryEntry>>(emptyList())
        private set

    fun refresh(baseUrl: String) {
        viewModelScope.launch {
            isLoading = true
            error = ""
            runCatching {
                FootballLotteryApi(baseUrl.trim()).fetchHistory()
            }.onSuccess { response ->
                entries = response
            }.onFailure { throwable ->
                error = throwable.message ?: "读取历史记录失败。"
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

    fun predict(baseUrl: String) {
        val cleanHome = home.trim()
        val cleanAway = away.trim()
        if (cleanHome.isEmpty() || cleanAway.isEmpty()) {
            error = "请填写主队和客队。"
            return
        }
        viewModelScope.launch {
            isLoading = true
            error = ""
            result = null
            runCatching {
                FootballLotteryApi(baseUrl.trim()).singlePrediction(
                    home = cleanHome,
                    away = cleanAway,
                    homeOdds = homeOdds.toDoubleOrNull(),
                    drawOdds = drawOdds.toDoubleOrNull(),
                    awayOdds = awayOdds.toDoubleOrNull(),
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

class FootballLotteryApi(private val baseUrl: String) {
    suspend fun generateAnalysis(issue: String, xgMatches: Int): AnalysisReport = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("issue", issue)
            .put("strength_model", true)
            .put("strength_xg_matches", xgMatches)
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
            )
        }
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
    historyViewModel: HistoryViewModel = viewModel(),
    singleViewModel: SinglePredictionViewModel = viewModel(),
) {
    val context = LocalContext.current
    val settings = remember(context) { context.getSharedPreferences("football_lottery_settings", 0) }
    var selectedTab by remember { mutableStateOf(AppTab.Analysis) }
    LaunchedEffect(Unit) {
        settings.getString("base_url", null)?.let(appViewModel::updateBaseUrl)
    }

    Scaffold(
        bottomBar = {
            NavigationBar(containerColor = Color.White) {
                AppTab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = selectedTab == tab,
                        onClick = { selectedTab = tab },
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
                AppTab.Analysis -> AnalysisScreen(appViewModel, analysisViewModel)
                AppTab.History -> HistoryScreen(appViewModel, historyViewModel)
                AppTab.Single -> SinglePredictionScreen(appViewModel, singleViewModel)
                AppTab.Settings -> SettingsScreen(
                    appViewModel = appViewModel,
                    onBaseUrlChanged = { value ->
                        appViewModel.updateBaseUrl(value)
                        settings.edit().putString("base_url", value).apply()
                    },
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AnalysisScreen(appViewModel: AppViewModel, viewModel: AnalysisViewModel) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { RequestCard(appViewModel, viewModel) }
        if (viewModel.error.isNotBlank()) {
            item { StatusCard(text = viewModel.error, color = Color(0xFFB42318)) }
        }
        if (viewModel.message.isNotBlank()) {
            item { StatusCard(text = viewModel.message, color = Color(0xFF16845B)) }
        }
        viewModel.report?.let { report ->
            item { SummaryCard(report) }
            item {
                Text(
                    text = "逐场预测",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
            }
            items(report.predictions) { prediction ->
                PredictionCard(prediction)
            }
        } ?: item {
            EmptyCard("等待生成", "启动后端服务，填写期号后生成分析。")
        }
    }
}

@Composable
fun HistoryScreen(appViewModel: AppViewModel, viewModel: HistoryViewModel) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            HeaderCard(
                title = "历史报告",
                subtitle = "从后端读取已生成的分析记录。",
                buttonText = if (viewModel.isLoading) "读取中" else "刷新",
                buttonEnabled = !viewModel.isLoading,
                onClick = { viewModel.refresh(appViewModel.baseUrl) },
            )
        }
        if (viewModel.error.isNotBlank()) {
            item { StatusCard(text = viewModel.error, color = Color(0xFFB42318)) }
        }
        if (viewModel.entries.isEmpty() && !viewModel.isLoading) {
            item { EmptyCard("暂无历史", "后端返回空列表，生成一次分析后这里会出现记录。") }
        }
        items(viewModel.entries) { entry ->
            HistoryEntryCard(entry)
        }
    }
}

@Composable
fun SinglePredictionScreen(appViewModel: AppViewModel, viewModel: SinglePredictionViewModel) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { SinglePredictionForm(appViewModel, viewModel) }
        if (viewModel.error.isNotBlank()) {
            item { StatusCard(text = viewModel.error, color = Color(0xFFB42318)) }
        }
        viewModel.result?.let { result ->
            item { SinglePredictionResultCard(result) }
        } ?: item {
            EmptyCard("单场预测", "输入主队和客队，可选填写竞彩赔率。")
        }
    }
}

@Composable
fun SettingsScreen(appViewModel: AppViewModel, onBaseUrlChanged: (String) -> Unit) {
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
                    OutlinedTextField(
                        value = appViewModel.baseUrl,
                        onValueChange = onBaseUrlChanged,
                        label = { Text("后端地址") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                    )
                    Text(
                        "Android 模拟器访问电脑本机服务通常使用 http://10.0.2.2:8765；真机需要填电脑在同一局域网内的 IP。",
                        color = Color(0xFF667085),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Button(
                        onClick = appViewModel::testConnection,
                        enabled = !appViewModel.isTestingConnection && appViewModel.baseUrl.isNotBlank(),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        LoadingPrefix(appViewModel.isTestingConnection)
                        Text(if (appViewModel.isTestingConnection) "测试中" else "测试连接")
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
private fun RequestCard(appViewModel: AppViewModel, viewModel: AnalysisViewModel) {
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("生成分析", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            OutlinedTextField(
                value = viewModel.issue,
                onValueChange = viewModel::updateIssue,
                label = { Text("期号") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("xG 样本场次")
                Spacer(modifier = Modifier.weight(1f))
                Text(viewModel.xgMatches.toInt().toString(), fontWeight = FontWeight.Bold)
            }
            Slider(
                value = viewModel.xgMatches.toFloat(),
                onValueChange = { viewModel.updateXgMatches(it.toDouble()) },
                valueRange = 0f..20f,
                steps = 19,
            )
            Button(
                onClick = { viewModel.generateAnalysis(appViewModel.baseUrl) },
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
private fun SinglePredictionForm(appViewModel: AppViewModel, viewModel: SinglePredictionViewModel) {
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
                onClick = { viewModel.predict(appViewModel.baseUrl) },
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
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("第 ${report.issue} 期", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(
                text = deadlineText(report),
                style = MaterialTheme.typography.bodyMedium,
                color = Color(0xFF667085),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MetricTile("比赛", report.metrics.matchCount.toString(), Modifier.weight(1f))
                MetricTile("单选", report.metrics.singleCount.toString(), Modifier.weight(1f))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MetricTile("低风险", report.metrics.lowRiskCount.toString(), Modifier.weight(1f))
                MetricTile("平均置信", "%.1f%%".format(report.metrics.averageConfidence), Modifier.weight(1f))
            }
            SequenceLine("任选九保留", report.choose9Keep, Color(0xFF16845B))
            SequenceLine("建议剔除", report.choose9Drop, Color(0xFFB42318))
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
                Text(prediction.pickText, color = Color(0xFF2364AA), fontWeight = FontWeight.Bold)
            }
            ProbabilityLine("主胜", prediction.probabilities.home, Color(0xFFB42318))
            ProbabilityLine("平", prediction.probabilities.draw, Color(0xFF2364AA))
            ProbabilityLine("客胜", prediction.probabilities.away, Color(0xFF16845B))
            Text(
                text = "比分倾向：" + prediction.scorelines.joinToString("，") { "${it.score} ${"%.1f".format(it.probability)}%" },
                style = MaterialTheme.typography.bodySmall,
                color = Color(0xFF087F8C),
            )
        }
    }
}

@Composable
private fun HistoryEntryCard(entry: HistoryEntry) {
    val context = LocalContext.current
    fun openUrl(url: String) {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    }

    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(entry.title.ifBlank { "第 ${entry.issue} 期报告" }, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                Text(entry.kind.ifBlank { "report" }, color = Color(0xFF2364AA), style = MaterialTheme.typography.bodySmall)
            }
            Text(entry.createdAt.ifBlank { "未记录时间" }, color = Color(0xFF667085), style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (entry.htmlUrl.isNotBlank()) {
                    Button(onClick = { openUrl(entry.htmlUrl) }) {
                        Text("打开 HTML")
                    }
                }
                if (entry.markdownUrl.isNotBlank()) {
                    Button(onClick = { openUrl(entry.markdownUrl) }) {
                        Text("打开 Markdown")
                    }
                }
            }
        }
    }
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
