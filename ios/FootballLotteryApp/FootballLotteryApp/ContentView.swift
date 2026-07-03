import SwiftUI

struct ContentView: View {
    @StateObject private var viewModel = AnalysisViewModel()

    var body: some View {
        TabView {
            AnalysisHomeView(viewModel: viewModel)
                .tabItem {
                    Label("分析", systemImage: "chart.bar.doc.horizontal")
                }

            HistoryView(baseURL: $viewModel.baseURL)
                .tabItem {
                    Label("历史", systemImage: "clock.arrow.circlepath")
                }
        }
    }
}

private struct AnalysisHomeView: View {
    @ObservedObject var viewModel: AnalysisViewModel

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    RequestPanel(viewModel: viewModel)

                    if !viewModel.errorMessage.isEmpty {
                        StatusBanner(text: viewModel.errorMessage, style: .error)
                    }
                    if !viewModel.message.isEmpty {
                        StatusBanner(text: viewModel.message, style: .success)
                    }

                    if let report = viewModel.report {
                        ReportSummaryView(report: report)
                        MatchListView(predictions: report.predictions)
                    } else {
                        EmptyReportView()
                    }
                }
                .padding(16)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("足球彩票分析")
            .navigationBarTitleDisplayMode(.large)
        }
    }
}

private struct HistoryView: View {
    @Binding var baseURL: String
    @StateObject private var viewModel = HistoryViewModel()

    var body: some View {
        NavigationStack {
            List {
                if !viewModel.errorMessage.isEmpty {
                    Text(viewModel.errorMessage)
                        .foregroundStyle(.red)
                }
                if viewModel.entries.isEmpty && !viewModel.isLoading {
                    Text("还没有历史记录。")
                        .foregroundStyle(.secondary)
                }
                ForEach(viewModel.entries) { entry in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text(entry.kind == "review" ? "复盘" : "分析")
                                .font(.caption.bold())
                                .foregroundStyle(entry.kind == "review" ? .orange : .blue)
                            Spacer()
                            Text(entry.createdAt.replacingOccurrences(of: "T", with: " "))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Text(entry.title)
                            .font(.headline)
                        Text("期号 \(entry.issue)")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        if let htmlURL = entry.htmlURL {
                            Text(htmlURL)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }
                    .padding(.vertical, 6)
                }
            }
            .navigationTitle("历史报告")
            .toolbar {
                Button {
                    Task { await viewModel.refresh(baseURL: baseURL) }
                } label: {
                    if viewModel.isLoading {
                        ProgressView()
                    } else {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .task {
                await viewModel.refresh(baseURL: baseURL)
            }
        }
    }
}

private struct RequestPanel: View {
    @ObservedObject var viewModel: AnalysisViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("生成分析")
                .font(.headline)

            TextField("期号", text: $viewModel.issue)
                .keyboardType(.numberPad)
                .textFieldStyle(.roundedBorder)

            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("xG 样本场次")
                    Spacer()
                    Text("\(Int(viewModel.strengthXgMatches))")
                        .fontWeight(.semibold)
                        .foregroundStyle(.secondary)
                }
                Slider(value: $viewModel.strengthXgMatches, in: 0...20, step: 1)
            }

            DisclosureGroup {
                TextField("后端地址", text: $viewModel.baseURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .textFieldStyle(.roundedBorder)
                Text("真机调试时填电脑局域网地址，例如 http://192.168.1.8:8765")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } label: {
                Label("连接设置", systemImage: "network")
            }

            Button {
                Task { await viewModel.generateAnalysis() }
            } label: {
                HStack {
                    if viewModel.isLoading {
                        ProgressView()
                            .tint(.white)
                    }
                    Text(viewModel.isLoading ? "生成中" : "生成分析报告")
                        .fontWeight(.semibold)
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(viewModel.isLoading)
        }
        .padding(14)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct EmptyReportView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("等待生成", systemImage: "doc.text.magnifyingglass")
                .font(.headline)
            Text("输入期号后生成分析，报告会在这里显示。")
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private enum BannerStyle {
    case success
    case error

    var color: Color {
        switch self {
        case .success: return .green
        case .error: return .red
        }
    }

    var icon: String {
        switch self {
        case .success: return "checkmark.circle.fill"
        case .error: return "exclamationmark.triangle.fill"
        }
    }
}

private struct StatusBanner: View {
    let text: String
    let style: BannerStyle

    var body: some View {
        Label(text, systemImage: style.icon)
            .font(.callout)
            .foregroundStyle(style.color)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(style.color.opacity(0.12))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

#Preview {
    ContentView()
}
