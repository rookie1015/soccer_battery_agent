import SwiftUI

struct ReportSummaryView: View {
    let report: AnalysisReport

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("第 \(report.issue) 期")
                        .font(.title3.bold())
                    Text(deadlineText)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                RiskBadge(text: "\(report.metrics.averageConfidence, specifier: "%.1f")%")
            }

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                MetricTile(title: "比赛", value: "\(report.metrics.matchCount)", tint: .blue)
                MetricTile(title: "单选", value: "\(report.metrics.singleCount)", tint: .indigo)
                MetricTile(title: "低风险", value: "\(report.metrics.lowRiskCount)", tint: .green)
                MetricTile(title: "平均置信", value: "\(report.metrics.averageConfidence, specifier: "%.1f")%", tint: .orange)
            }

            VStack(alignment: .leading, spacing: 10) {
                SequenceRow(title: "任九保留", values: report.choose9Keep, color: .green)
                SequenceRow(title: "建议剔除", values: report.choose9Drop, color: .red)
            }
        }
        .padding(14)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private var deadlineText: String {
        if report.purchaseDeadline.isEmpty {
            return "购彩截止时间暂未获取"
        }
        if report.purchaseDeadlineSource.isEmpty {
            return "购彩截止时间：\(report.purchaseDeadline)"
        }
        return "购彩截止时间：\(report.purchaseDeadline) · \(report.purchaseDeadlineSource)"
    }
}

struct MatchListView: View {
    let predictions: [MatchPrediction]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("逐场预测")
                .font(.headline)
            ForEach(predictions) { prediction in
                NavigationLink {
                    MatchDetailView(prediction: prediction)
                } label: {
                    MatchRowView(prediction: prediction)
                }
                .buttonStyle(.plain)
            }
        }
    }
}

private struct MatchRowView: View {
    let prediction: MatchPrediction

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Text("\(prediction.seq)")
                .font(.headline)
                .foregroundStyle(.blue)
                .frame(width: 30, height: 30)
                .background(Color.blue.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))

            VStack(alignment: .leading, spacing: 4) {
                Text("\(prediction.home) vs \(prediction.away)")
                    .font(.subheadline.bold())
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                Text("\(prediction.league) · \(prediction.kickoffDisplay)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 8)

            VStack(alignment: .trailing, spacing: 4) {
                Text(prediction.pickText)
                    .font(.headline)
                    .foregroundStyle(.blue)
                Text("\(prediction.confidence, specifier: "%.1f")%")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

struct MatchDetailView: View {
    let prediction: MatchPrediction

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("\(prediction.home) vs \(prediction.away)")
                        .font(.title2.bold())
                    Text("\(prediction.league) · \(prediction.kickoffDisplay)")
                        .foregroundStyle(.secondary)
                    HStack {
                        RiskBadge(text: prediction.pickLabels.joined(separator: " / "))
                        RiskBadge(text: "风险 \(prediction.risk)")
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
                .background(.background)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

                ProbabilityPanel(probabilities: prediction.probabilities)
                ScorelinePanel(scorelines: prediction.scorelines)
                ReasonPanel(reasons: prediction.reasons)
            }
            .padding(16)
        }
        .background(Color(.systemGroupedBackground))
        .navigationTitle("第 \(prediction.seq) 场")
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct ProbabilityPanel: View {
    let probabilities: OutcomeProbabilities

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("胜平负概率")
                .font(.headline)
            ProbabilityRow(title: "主胜", value: probabilities.home, color: .red)
            ProbabilityRow(title: "平局", value: probabilities.draw, color: .blue)
            ProbabilityRow(title: "客胜", value: probabilities.away, color: .green)
        }
        .padding(14)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct ProbabilityRow: View {
    let title: String
    let value: Double
    let color: Color

    var body: some View {
        HStack {
            Text(title)
                .frame(width: 44, alignment: .leading)
            ProgressView(value: value, total: 100)
                .tint(color)
            Text("\(value, specifier: "%.1f")%")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 54, alignment: .trailing)
        }
    }
}

private struct ScorelinePanel: View {
    let scorelines: [ScorelinePrediction]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("比分倾向")
                .font(.headline)
            FlowLayout(items: scorelines.map { "\($0.score)  \($0.probability, specifier: "%.1f")%" })
        }
        .padding(14)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct ReasonPanel: View {
    let reasons: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("分析理由")
                .font(.headline)
            ForEach(Array(reasons.enumerated()), id: \.offset) { _, reason in
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "circle.fill")
                        .font(.system(size: 5))
                        .padding(.top, 7)
                        .foregroundStyle(.secondary)
                    Text(reason)
                        .font(.subheadline)
                }
            }
        }
        .padding(14)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct MetricTile: View {
    let title: String
    let value: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title3.bold())
                .foregroundStyle(tint)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(tint.opacity(0.1))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct SequenceRow: View {
    let title: String
    let values: [Int]
    let color: Color

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Text(title)
                .font(.subheadline.bold())
                .frame(width: 70, alignment: .leading)
            Text(values.map(String.init).joined(separator: "  "))
                .font(.subheadline.monospacedDigit())
                .foregroundStyle(color)
            Spacer()
        }
    }
}

private struct RiskBadge: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.caption.bold())
            .foregroundStyle(.blue)
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .background(Color.blue.opacity(0.12))
            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
    }
}

private struct FlowLayout: View {
    let items: [String]

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 92), spacing: 8)], alignment: .leading, spacing: 8) {
            ForEach(items, id: \.self) { item in
                Text(item)
                    .font(.caption.bold())
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                    .background(Color.cyan.opacity(0.12))
                    .foregroundStyle(.cyan)
                    .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            }
        }
    }
}
