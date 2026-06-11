import SwiftUI

/// One-screen glance: counts, today's spend, last result. Complication-sized.
struct GlanceView: View {
    @StateObject private var model = GlanceModel()

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let g = model.glance {
                HStack {
                    Label("\(g.active)", systemImage: "play.circle")
                    Label("\(g.done_today)", systemImage: "checkmark.circle")
                    Label("\(g.failed_today)", systemImage: "xmark.circle")
                }
                .font(.headline)
                Text(String(format: "$%.2f today", g.spend_today))
                    .font(.caption)
                if !g.last_result.isEmpty {
                    Text(g.last_result)
                        .font(.caption2)
                        .lineLimit(2)
                        .foregroundStyle(.secondary)
                }
            } else if let err = model.error {
                Text(err).font(.caption2).foregroundStyle(.red)
            } else {
                ProgressView()
            }
        }
        .task { await model.refresh() }
        .refreshable { await model.refresh() }
    }
}
