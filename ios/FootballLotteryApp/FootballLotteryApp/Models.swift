import Foundation

struct AnalysisRequest: Encodable {
    let issue: String
    let strengthModel: Bool
    let strengthXgMatches: Int
    let noHistory: Bool

    enum CodingKeys: String, CodingKey {
        case issue
        case strengthModel = "strength_model"
        case strengthXgMatches = "strength_xg_matches"
        case noHistory = "no_history"
    }
}

struct AnalysisResponse: Decodable {
    let ok: Bool
    let message: String?
    let error: String?
    let report: AnalysisReport?
    let htmlURL: String?
    let markdownURL: String?
    let historyURL: String?

    enum CodingKeys: String, CodingKey {
        case ok
        case message
        case error
        case report
        case htmlURL = "html_url"
        case markdownURL = "markdown_url"
        case historyURL = "history_url"
    }
}

struct HistoryResponse: Decodable {
    let ok: Bool
    let entries: [HistoryEntry]
}

struct HistoryEntry: Decodable, Identifiable {
    let id: String
    let kind: String
    let issue: String
    let title: String
    let createdAt: String
    let htmlURL: String?
    let markdownURL: String?

    enum CodingKeys: String, CodingKey {
        case id
        case kind
        case issue
        case title
        case createdAt = "created_at"
        case htmlURL = "html_url"
        case markdownURL = "markdown_url"
    }
}

struct AnalysisReport: Decodable, Identifiable {
    var id: String { issue }

    let issue: String
    let purchaseDeadline: String
    let purchaseDeadlineSource: String
    let saleBeginTime: String
    let drawHedge: DrawHedgeReport?
    let linePortfolio: LinePortfolioReport?
    let metrics: ReportMetrics
    let choose9Keep: [Int]
    let choose9Drop: [Int]
    let predictions: [MatchPrediction]

    enum CodingKeys: String, CodingKey {
        case issue
        case purchaseDeadline = "purchase_deadline"
        case purchaseDeadlineSource = "purchase_deadline_source"
        case saleBeginTime = "sale_begin_time"
        case drawHedge = "draw_hedge"
        case linePortfolio = "line_portfolio"
        case metrics
        case choose9Keep = "choose9_keep"
        case choose9Drop = "choose9_drop"
        case predictions
    }
}

struct LinePortfolioReport: Decodable {
    let lineCount: Int
    let costYuan: Int
    let multiDrawLines: Int
    let minimumDrawPairLines: Int
    let drawCoverages: [DrawCoverageReport]
    let lines: [PortfolioLineReport]

    enum CodingKeys: String, CodingKey {
        case lineCount = "line_count"
        case costYuan = "cost_yuan"
        case multiDrawLines = "multi_draw_lines"
        case minimumDrawPairLines = "minimum_draw_pair_lines"
        case drawCoverages = "draw_coverages"
        case lines
    }
}

struct DrawCoverageReport: Decodable, Identifiable {
    var id: Int { seq }
    let seq: Int
    let home: String
    let away: String
    let probability: Double
    let targetLines: Int
    let actualLines: Int

    enum CodingKeys: String, CodingKey {
        case seq, home, away, probability
        case targetLines = "target_lines"
        case actualLines = "actual_lines"
    }
}

struct PortfolioLineReport: Decodable, Identifiable {
    var id: Int { number }
    let number: Int
    let pickText: String

    enum CodingKeys: String, CodingKey {
        case number
        case pickText = "pick_text"
    }
}

struct DrawHedgeReport: Decodable {
    let candidateSeq: Int
    let home: String
    let away: String
    let lineCount: Int
    let costYuan: Int
    let mainCostYuan: Int
    let totalCostYuan: Int
    let score: Double
    let evidence: [String]
    let selections: [DrawHedgeSelection]

    enum CodingKeys: String, CodingKey {
        case candidateSeq = "candidate_seq"
        case home, away
        case lineCount = "line_count"
        case costYuan = "cost_yuan"
        case mainCostYuan = "main_cost_yuan"
        case totalCostYuan = "total_cost_yuan"
        case score, evidence, selections
    }
}

struct DrawHedgeSelection: Decodable {
    let seq: Int
    let pickText: String

    enum CodingKeys: String, CodingKey {
        case seq
        case pickText = "pick_text"
    }
}

struct ReportMetrics: Decodable {
    let matchCount: Int
    let singleCount: Int
    let ticketSingleCount: Int?
    let budgetForcedSingleCount: Int?
    let tacticalDrawCount: Int?
    let drawHedgeCount: Int?
    let linePortfolioCount: Int?
    let drawCandidateCount: Int?
    let lowRiskCount: Int
    let averageConfidence: Double

    enum CodingKeys: String, CodingKey {
        case matchCount = "match_count"
        case singleCount = "single_count"
        case ticketSingleCount = "ticket_single_count"
        case budgetForcedSingleCount = "budget_forced_single_count"
        case tacticalDrawCount = "tactical_draw_count"
        case drawHedgeCount = "draw_hedge_count"
        case linePortfolioCount = "line_portfolio_count"
        case drawCandidateCount = "draw_candidate_count"
        case lowRiskCount = "low_risk_count"
        case averageConfidence = "average_confidence"
    }
}

struct MatchPrediction: Decodable, Identifiable {
    var id: Int { seq }

    let seq: Int
    let league: String
    let kickoff: String
    let kickoffDisplay: String
    let home: String
    let away: String
    let pickText: String
    let pickLabels: [String]
    let picks: [String]
    let analysisPickText: String?
    let analysisPickLabels: [String]?
    let budgetAdjusted: Bool?
    let budgetForcedSingle: Bool?
    let drawGuard: Bool?
    let tacticalDraw: Bool?
    let confidence: Double
    let risk: String
    let probabilities: OutcomeProbabilities
    let scorelines: [ScorelinePrediction]
    let reasons: [String]

    enum CodingKeys: String, CodingKey {
        case seq
        case league
        case kickoff
        case kickoffDisplay = "kickoff_display"
        case home
        case away
        case pickText = "pick_text"
        case pickLabels = "pick_labels"
        case picks
        case analysisPickText = "analysis_pick_text"
        case analysisPickLabels = "analysis_pick_labels"
        case budgetAdjusted = "budget_adjusted"
        case budgetForcedSingle = "budget_forced_single"
        case drawGuard = "draw_guard"
        case tacticalDraw = "tactical_draw"
        case confidence
        case risk
        case probabilities
        case scorelines
        case reasons
    }
}

struct OutcomeProbabilities: Decodable {
    let home: Double
    let draw: Double
    let away: Double
}

struct ScorelinePrediction: Decodable, Identifiable {
    var id: String { score }

    let score: String
    let probability: Double
}
