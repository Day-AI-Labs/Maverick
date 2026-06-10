import Foundation

/// The fixed glance payload served by `GET /api/v1/glance`.
struct Glance: Codable {
    let active: Int
    let done_today: Int
    let failed_today: Int
    let spend_today: Double
    let last_result: String
    let as_of: Int
}

@MainActor
final class GlanceModel: ObservableObject {
    @Published var glance: Glance?
    @Published var error: String?

    private var baseURL: URL? {
        let raw = ProcessInfo.processInfo.environment["MAVERICK_GLANCE_URL"]
            ?? UserDefaults.standard.string(forKey: "glance_url")
            ?? "http://127.0.0.1:8765"
        return URL(string: raw)?.appendingPathComponent("api/v1/glance")
    }

    func refresh() async {
        guard let url = baseURL else { error = "bad URL"; return }
        var request = URLRequest(url: url)
        if let token = ProcessInfo.processInfo.environment["MAVERICK_DASHBOARD_TOKEN"]
            ?? UserDefaults.standard.string(forKey: "dashboard_token") {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        do {
            let (data, _) = try await URLSession.shared.data(for: request)
            glance = try JSONDecoder().decode(Glance.self, from: data)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}
