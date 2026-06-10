/* Runs list — GET /api/v1/goals (newest first), polled every 10s.
 * Falls back to the cached offline bundle when the dashboard is unreachable. */
import React, { useCallback, useEffect, useState } from "react";
import { FlatList, Pressable, StyleSheet, Text, View } from "react-native";

import { BundleGoal, Goal, Settings, listGoals } from "../api";
import { CachedBundle, loadBundle, offlineBanner } from "../offlineCache";
import { usePolling } from "../poll";

const STATUS_COLOR: Record<string, string> = {
  active: "#2da44e",
  pending: "#bf8700",
  blocked: "#bf8700",
  done: "#57606a",
  failed: "#cf222e",
  cancelled: "#57606a",
};

export function RunsListScreen(props: {
  settings: Settings;
  onOpenRun: (id: number) => void;
}): React.JSX.Element {
  const { settings, onOpenRun } = props;
  const fetcher = useCallback(() => listGoals(settings, 50), [settings]);
  const { data, error } = usePolling<Goal[]>(fetcher, 10_000);
  const [cached, setCached] = useState<CachedBundle | null>(null);

  useEffect(() => {
    if (error && !data) loadBundle().then(setCached);
  }, [error, data]);

  const offline = !data && cached;
  const rows: Goal[] = data
    ? data
    : cached
      ? cached.bundle.goals.map((g: BundleGoal) => ({
          id: g.id, status: g.status, title: g.title, result: g.result,
        }))
      : [];

  return (
    <View style={styles.fill}>
      {offline && cached ? (
        <Text style={styles.banner}>{offlineBanner(cached)}</Text>
      ) : null}
      {error && !offline ? <Text style={styles.error}>{error}</Text> : null}
      <FlatList
        data={rows}
        keyExtractor={(g: Goal) => String(g.id)}
        ListEmptyComponent={<Text style={styles.empty}>No runs yet.</Text>}
        renderItem={({ item }: { item: Goal }) => (
          <Pressable style={styles.row} onPress={() => onOpenRun(item.id)}>
            <View
              style={[
                styles.dot,
                { backgroundColor: STATUS_COLOR[item.status] ?? "#57606a" },
              ]}
            />
            <View style={styles.fill}>
              <Text style={styles.title} numberOfLines={1}>
                #{item.id} {item.title}
              </Text>
              <Text style={styles.sub} numberOfLines={1}>
                {item.status}
                {item.result ? ` — ${item.result}` : ""}
              </Text>
            </View>
          </Pressable>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  banner: {
    backgroundColor: "#fff8c5", color: "#4d2d00",
    padding: 8, textAlign: "center", fontSize: 13,
  },
  error: { color: "#cf222e", padding: 8, fontSize: 13 },
  empty: { padding: 24, textAlign: "center", color: "#57606a" },
  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 14, paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: "#d0d7de",
  },
  dot: { width: 10, height: 10, borderRadius: 5 },
  title: { fontSize: 15, fontWeight: "600" },
  sub: { fontSize: 13, color: "#57606a" },
});
