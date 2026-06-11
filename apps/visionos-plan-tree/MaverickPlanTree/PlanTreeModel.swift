import Foundation

/// One goal node from `GET /api/v1/goal-tree` — the server has already
/// computed the layered layout (`depth`, `x`, `y` in pixels).
struct GoalNode: Decodable, Identifiable {
    let id: Int
    let parentId: Int?
    let title: String
    let status: String
    let depth: Int
    let x: Double
    let y: Double

    enum CodingKeys: String, CodingKey {
        case id, title, status, depth, x, y
        case parentId = "parent_id"
    }
}

struct GoalForest: Decodable {
    let nodes: [GoalNode]
    let edges: [[Int]]
    let count: Int
}

@MainActor
final class PlanTreeModel: ObservableObject {
    @Published var forest: GoalForest?
    @Published var error: String?

    /// Dashboard base URL; the in-app settings or the scheme environment
    /// (`MAVERICK_DASHBOARD_URL`) override the loopback default.
    var baseURL: String =
        ProcessInfo.processInfo.environment["MAVERICK_DASHBOARD_URL"]
        ?? "http://127.0.0.1:8765"
    var token: String? =
        ProcessInfo.processInfo.environment["MAVERICK_DASHBOARD_TOKEN"]

    func refresh() async {
        guard let url = URL(string: "\(baseURL)/api/v1/goal-tree") else {
            error = "bad dashboard URL"
            return
        }
        var req = URLRequest(url: url)
        if let token, !token.isEmpty {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
                error = "dashboard returned \((resp as? HTTPURLResponse)?.statusCode ?? -1)"
                return
            }
            forest = try JSONDecoder().decode(GoalForest.self, from: data)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// Status -> display color name, mirroring the dashboard's palette.
func statusColorName(_ status: String) -> String {
    switch status {
    case "active", "running": return "blue"
    case "done", "succeeded", "completed": return "green"
    case "failed", "blocked": return "red"
    case "cancelled": return "gray"
    default: return "yellow"   // pending and anything new
    }
}
