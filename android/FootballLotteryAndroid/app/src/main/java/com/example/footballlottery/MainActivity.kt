package com.example.footballlottery

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
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
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
                    AnalysisScreen()
                }
            }
        }
    }
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

class AnalysisViewModel : ViewModel() {
    var baseUrl by mutableStateOf("http://10.0.2.2:8765")
        private set
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

    fun updateBaseUrl(value: String) {
        baseUrl = value
    }

    fun updateIssue(value: String) {
        issue = value
    }

    fun updateXgMatches(value: Double) {
        xgMatches = value
    }

    fun generateAnalysis() {
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

class FootballLotteryApi(private val baseUrl: String) {
    suspend fun generateAnalysis(issue: String, xgMatches: Int): AnalysisReport = withContext(Dispatchers.IO) {
        val endpoint = baseUrl.trimEnd('/') + "/api/analysis"
        val body = JSONObject()
            .put("issue", issue)
            .put("strength_model", true)
            .put("strength_xg_matches", xgMatches)
            .put("no_history", false)
            .toString()
        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 20_000
            readTimeout = 120_000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }

        OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { writer ->
            writer.write(body)
        }

        val responseText = runCatching {
            connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        }.getOrElse {
            connection.errorStream?.bufferedReader(Charsets.UTF_8)?.use { reader -> reader.readText() }.orEmpty()
        }
        val json = JSONObject(responseText.ifBlank { "{}" })
        if (connection.responseCode !in 200..299 || !json.optBoolean("ok", false)) {
            throw IllegalStateException(json.optString("error", json.optString("message", "生成分析报告失败。")))
        }
        parseReport(json.getJSONObject("report"))
    }

    private fun parseReport(json: JSONObject): AnalysisReport {
        val metrics = json.getJSONObject("metrics")
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
            choose9Keep = json.getJSONArray("choose9_keep").toIntList(),
            choose9Drop = json.getJSONArray("choose9_drop").toIntList(),
            predictions = json.getJSONArray("predictions").mapObjects { parsePrediction(it) },
        )
    }

    private fun parsePrediction(json: JSONObject): MatchPrediction {
        val probabilities = json.getJSONObject("probabilities")
        return MatchPrediction(
            seq = json.optInt("seq"),
            league = json.optString("league"),
            kickoffDisplay = json.optString("kickoff_display"),
            home = json.optString("home"),
            away = json.optString("away"),
            pickText = json.optString("pick_text"),
            pickLabels = json.getJSONArray("pick_labels").toStringList(),
            confidence = json.optDouble("confidence"),
            risk = json.optString("risk"),
            probabilities = OutcomeProbabilities(
                home = probabilities.optDouble("home"),
                draw = probabilities.optDouble("draw"),
                away = probabilities.optDouble("away"),
            ),
            scorelines = json.getJSONArray("scorelines").mapObjects {
                ScorelinePrediction(
                    score = it.optString("score"),
                    probability = it.optDouble("probability"),
                )
            },
            reasons = json.getJSONArray("reasons").toStringList(),
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AnalysisScreen(viewModel: AnalysisViewModel = viewModel()) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFFF4F6FA))
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            RequestCard(viewModel)
        }
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
            EmptyCard()
        }
    }
}

@Composable
private fun RequestCard(viewModel: AnalysisViewModel) {
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
            OutlinedTextField(
                value = viewModel.baseUrl,
                onValueChange = viewModel::updateBaseUrl,
                label = { Text("后端地址") },
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
                onClick = viewModel::generateAnalysis,
                enabled = !viewModel.isLoading,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (viewModel.isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier
                            .height(18.dp)
                            .width(18.dp),
                        strokeWidth = 2.dp,
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                }
                Text(if (viewModel.isLoading) "生成中" else "生成分析报告")
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
            SequenceLine("任九保留", report.choose9Keep, Color(0xFF16845B))
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
                text = "比分倾向：" + prediction.scorelines.joinToString("、") { "${it.score} ${"%.1f".format(it.probability)}%" },
                style = MaterialTheme.typography.bodySmall,
                color = Color(0xFF087F8C),
            )
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
        Text(title, fontWeight = FontWeight.Bold, modifier = Modifier.width(72.dp))
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
private fun EmptyCard() {
    Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("等待生成", fontWeight = FontWeight.Bold)
            Text("启动后端服务，填期号生成分析。", color = Color(0xFF667085))
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

private fun JSONArray.toIntList(): List<Int> = List(length()) { index -> optInt(index) }

private fun JSONArray.toStringList(): List<String> = List(length()) { index -> optString(index) }

private fun <T> JSONArray.mapObjects(transform: (JSONObject) -> T): List<T> =
    List(length()) { index -> transform(getJSONObject(index)) }
