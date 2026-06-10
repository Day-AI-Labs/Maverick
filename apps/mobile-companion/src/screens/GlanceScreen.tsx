/* Glance — the at-a-glance fleet summary, polled every 15s.
 *
 * Online path composes two real read-only endpoints:
 *   GET /api/v1/oversight/active  (active runs + latest activity)
 *   GET /api/v1/spend             (total spend)
 * It also opportunistically refreshes the offline cache from
 * GET /api/v1/offline/bundle when the dashboard serves it (404 on older
 * dashboards is fine — the cache just isn't refreshed). When everything is
 * unreachable, renders the cached bundle with an offline banner. */
import React, { useCallback, useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import {
  ActiveGoal,
  Glance,
  Settings,
  SpendTotal,
  getActive,
  getOfflineBundle,
  getSpend,
} from "../api";
import { CachedBundle, loadBundle, offlineBanner, saveBundle } from "../offlineCache";
import { usePolling } from "../poll";

type GlanceData = { active: ActiveGoal[]; spend: SpendTotal | null };

export function GlanceScreen(props: { settings: Settings }): React.JSX.Element {
  const { settings } = props;
  const [cached, setCached] = useState<CachedBundle | null>(null);

  const fetcher = useCallback(async (): Promise<GlanceData> => {
    const [activeRes, spendRes] = await Promise.all([
      getActive(settings),
      getSpend(settings).catch(() => null),
    ]);
    // Best-effort cache refresh; endpoint may not exist on older dashboards.
    getOfflineBundle(settings).then(saveBundle).catch(() => undefined);
    return { active: activeRes.goals, spend: spendRes ? spendRes.total : null };
  }, [settings]);

  const { data, error } = usePolling<GlanceData>(fetcher, 15_000);

  useEffect(() => {
    if (error && !data) loadBundle().then(setCached);
  }, [error, data]);

  if (!data && cached) {
    const g = cached.bundle.glance;
    return (
      <ScrollView style={styles.fill}>
        <Text style={styles.banner}>{offlineBanner(cached)}</Text>
        <Stat label="active runs" value={String(g.counts.active)} />
        <Stat label="pending approvals" value={String(g.counts.pending_approvals)} />
        <Stat label="open questions" value={String(g.counts.open_questions)} />
        <Stat label="total spend" value={`$${g.spend.dollars.toFixed(2)}`} />
        <Text style={styles.section}>Active (cached)</Text>
        {g.active.map((a: Glance["active"][number]) => (
          <Text key={a.id} style={styles.row} numberOfLines={1}>
            #{a.id} {a.title}
          </Text>
        ))}
      </ScrollView>
    );
  }

  return (
    <ScrollView style={styles.fill}>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Stat label="active runs" value={data ? String(data.active.length) : "…"} />
      <Stat
        label="total spend"
        value={data?.spend ? `$${data.spend.dollars.toFixed(2)} over ${data.spend.runs} runs` : "…"}
      />
      <Text style={styles.section}>Active now</Text>
      {data && data.active.length === 0 ? (
        <Text style={styles.row}>Nothing running.</Text>
      ) : null}
      {(data ? data.active : []).map((a) => (
        <View key={a.id} style={styles.card}>
          <Text style={styles.cardTitle} numberOfLines={1}>
            #{a.id} {a.title}
          </Text>
          {a.activity ? (
            <Text style={styles.cardSub} numberOfLines={2}>{a.activity}</Text>
          ) : null}
        </View>
      ))}
    </ScrollView>
  );
}

function Stat(props: { label: string; value: string }): React.JSX.Element {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{props.value}</Text>
      <Text style={styles.statLabel}>{props.label}</Text>
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
  stat: { paddingHorizontal: 16, paddingVertical: 10 },
  statValue: { fontSize: 22, fontWeight: "700" },
  statLabel: { fontSize: 13, color: "#57606a" },
  section: {
    fontSize: 13, fontWeight: "700", color: "#57606a",
    textTransform: "uppercase", paddingHorizontal: 16, paddingTop: 16,
  },
  row: { paddingHorizontal: 16, paddingVertical: 6, fontSize: 14 },
  card: {
    marginHorizontal: 14, marginVertical: 6, padding: 12,
    borderRadius: 8, borderWidth: StyleSheet.hairlineWidth,
    borderColor: "#d0d7de",
  },
  cardTitle: { fontSize: 15, fontWeight: "600" },
  cardSub: { fontSize: 13, color: "#57606a", marginTop: 4 },
});
