/* Run detail — status header + event timeline.
 * GET /api/v1/goals/{id}/events?since=0&limit=200, polled every 5s.
 * Read-only: there is no cancel/resume/answer here by design. */
import React, { useCallback } from "react";
import { FlatList, Pressable, StyleSheet, Text, View } from "react-native";

import { GoalEvent, GoalEventsResponse, Settings, getGoalEvents } from "../api";
import { usePolling } from "../poll";

function clock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString();
}

export function RunDetailScreen(props: {
  settings: Settings;
  runId: number;
  onBack: () => void;
}): React.JSX.Element {
  const { settings, runId, onBack } = props;
  const fetcher = useCallback(
    () => getGoalEvents(settings, runId, 0, 200),
    [settings, runId],
  );
  const { data, error } = usePolling<GoalEventsResponse>(fetcher, 5_000);

  return (
    <View style={styles.fill}>
      <View style={styles.header}>
        <Pressable onPress={onBack} hitSlop={12}>
          <Text style={styles.back}>‹ Runs</Text>
        </Pressable>
        <Text style={styles.headline}>
          Run #{runId} — {data ? data.status : "loading…"}
        </Text>
      </View>
      {data?.result ? <Text style={styles.result}>{data.result}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <FlatList
        data={data ? [...data.events].reverse() : []}
        keyExtractor={(e: GoalEvent) => String(e.id)}
        ListEmptyComponent={<Text style={styles.empty}>No events yet.</Text>}
        renderItem={({ item }: { item: GoalEvent }) => (
          <View style={styles.event}>
            <View style={styles.spine} />
            <View style={styles.fill}>
              <Text style={styles.meta}>
                {clock(item.ts)} · {item.agent} · {item.kind}
              </Text>
              <Text style={styles.content} numberOfLines={6}>
                {item.content}
              </Text>
            </View>
          </View>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  header: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 14, borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#d0d7de",
  },
  back: { fontSize: 16, color: "#0969da" },
  headline: { fontSize: 16, fontWeight: "600", flexShrink: 1 },
  result: { padding: 12, backgroundColor: "#ddf4ff", fontSize: 14 },
  error: { color: "#cf222e", padding: 8, fontSize: 13 },
  empty: { padding: 24, textAlign: "center", color: "#57606a" },
  event: { flexDirection: "row", paddingHorizontal: 14, paddingVertical: 8 },
  spine: {
    width: 3, borderRadius: 2, backgroundColor: "#d0d7de", marginRight: 10,
  },
  meta: { fontSize: 12, color: "#57606a" },
  content: { fontSize: 14, marginTop: 2 },
});
