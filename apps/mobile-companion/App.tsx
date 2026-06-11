/* Maverick mobile companion — read-only oversight from a phone.
 *
 * Three tabs (Runs, Glance, Settings) plus a run-detail drill-down. Plain
 * state-based navigation: no navigation library, so the dependency surface
 * stays react/react-native/expo only. All data comes from the dashboard's
 * existing read-only REST endpoints (see src/api.ts); the app never mutates.
 */
import { StatusBar } from "expo-status-bar";
import React, { useCallback, useEffect, useState } from "react";
import { Pressable, SafeAreaView, StyleSheet, Text, View } from "react-native";

import type { Settings } from "./src/api";
import { loadSettings } from "./src/settings";
import { GlanceScreen } from "./src/screens/GlanceScreen";
import { RunDetailScreen } from "./src/screens/RunDetailScreen";
import { RunsListScreen } from "./src/screens/RunsListScreen";
import { SettingsScreen } from "./src/screens/SettingsScreen";

type Tab = "runs" | "glance" | "settings";

export default function App(): React.JSX.Element {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [tab, setTab] = useState<Tab>("runs");
  const [runId, setRunId] = useState<number | null>(null);

  const reloadSettings = useCallback(() => {
    loadSettings().then(setSettings);
  }, []);
  useEffect(reloadSettings, [reloadSettings]);

  let body: React.JSX.Element;
  if (!settings) {
    body = <Text style={styles.loading}>Loading settings…</Text>;
  } else if (tab === "runs" && runId !== null) {
    body = (
      <RunDetailScreen
        settings={settings}
        runId={runId}
        onBack={() => setRunId(null)}
      />
    );
  } else if (tab === "runs") {
    body = <RunsListScreen settings={settings} onOpenRun={setRunId} />;
  } else if (tab === "glance") {
    body = <GlanceScreen settings={settings} />;
  } else {
    body = <SettingsScreen onSaved={reloadSettings} />;
  }

  return (
    <SafeAreaView style={styles.fill}>
      <StatusBar style="auto" />
      <View style={styles.fill}>{body}</View>
      <View style={styles.tabbar}>
        {(["runs", "glance", "settings"] as Tab[]).map((t) => (
          <Pressable
            key={t}
            style={styles.tab}
            onPress={() => {
              setTab(t);
              setRunId(null);
            }}
          >
            <Text style={[styles.tabText, tab === t && styles.tabActive]}>
              {t}
            </Text>
          </Pressable>
        ))}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  loading: { padding: 24, textAlign: "center", color: "#57606a" },
  tabbar: {
    flexDirection: "row",
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: "#d0d7de",
  },
  tab: { flex: 1, alignItems: "center", paddingVertical: 12 },
  tabText: { fontSize: 14, color: "#57606a", textTransform: "capitalize" },
  tabActive: { color: "#1f6feb", fontWeight: "700" },
});
