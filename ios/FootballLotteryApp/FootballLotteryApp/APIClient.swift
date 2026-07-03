import Foundation
import Combine

enum APIClientError: LocalizedError {
    case invalidBaseURL
    case invalidResponse
    case server(String)

    var errorDescription: String? {
        switch self {
        case .invalidBaseURL:
            return "后端地址格式不正确。"
        case .invalidResponse:
            return "服务器返回内容无法识别。"
        case .server(let message):
            return message
        }
    }
}

struct APIClient {
    var baseURL: String

    func generateAnalysis(issue: String, strengthXgMatches: Int) async throws -> AnalysisResponse {
        guard let root = URL(string: baseURL.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            throw APIClientError.invalidBaseURL
        }
        let url = root.appendingPathComponent("api").appendingPathComponent("analysis")
        let payload = AnalysisRequest(
            issue: issue,
            strengthModel: true,
            strengthXgMatches: strengthXgMatches,
            noHistory: false
        )
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(payload)

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIClientError.invalidResponse
        }
        let decoded = try JSONDecoder().decode(AnalysisResponse.self, from: data)
        if !(200..<300).contains(http.statusCode) || !decoded.ok {
            throw APIClientError.server(decoded.error ?? decoded.message ?? "生成分析报告失败。")
        }
        return decoded
    }

    func fetchHistory() async throws -> HistoryResponse {
        guard let root = URL(string: baseURL.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            throw APIClientError.invalidBaseURL
        }
        let url = root.appendingPathComponent("api").appendingPathComponent("history")
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw APIClientError.invalidResponse
        }
        return try JSONDecoder().decode(HistoryResponse.self, from: data)
    }
}

@MainActor
final class AnalysisViewModel: ObservableObject {
    @Published var issue = "26090"
    @Published var strengthXgMatches = 8.0
    @Published var isLoading = false
    @Published var report: AnalysisReport?
    @Published var message = ""
    @Published var errorMessage = ""

    @Published var baseURL: String {
        didSet {
            UserDefaults.standard.set(baseURL, forKey: "baseURL")
        }
    }

    init() {
        baseURL = UserDefaults.standard.string(forKey: "baseURL") ?? "http://127.0.0.1:8765"
    }

    func generateAnalysis() async {
        let issueText = issue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !issueText.isEmpty else {
            errorMessage = "请填写期号。"
            return
        }

        isLoading = true
        errorMessage = ""
        message = ""
        defer { isLoading = false }

        do {
            let client = APIClient(baseURL: normalizedBaseURL)
            let response = try await client.generateAnalysis(
                issue: issueText,
                strengthXgMatches: Int(strengthXgMatches)
            )
            report = response.report
            message = response.message ?? "分析报告已生成。"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private var normalizedBaseURL: String {
        let trimmed = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.hasSuffix("/") ? String(trimmed.dropLast()) : trimmed
    }
}

@MainActor
final class HistoryViewModel: ObservableObject {
    @Published var entries: [HistoryEntry] = []
    @Published var isLoading = false
    @Published var errorMessage = ""

    func refresh(baseURL: String) async {
        isLoading = true
        errorMessage = ""
        defer { isLoading = false }

        do {
            let client = APIClient(baseURL: baseURL.trimmingCharacters(in: .whitespacesAndNewlines))
            let response = try await client.fetchHistory()
            entries = response.entries
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
