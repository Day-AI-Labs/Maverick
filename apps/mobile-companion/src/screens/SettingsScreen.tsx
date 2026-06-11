/* Settings — dashboard base URL + bearer token, stored in the device
 * keychain via expo-secure-store. The app stays read-only regardless of the
 * token's privileges: it only ever issues GETs. */
import React, { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { loadSettings, saveSettings } from "../settings";

export function SettingsScreen(props: {
  onSaved: () => void;
}): React.JSX.Element {
  const [baseUrl, setBaseUrl] = useState("");
  const [token, setToken] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    loadSettings().then((s) => {
      setBaseUrl(s.baseUrl);
      setToken(s.token);
    });
  }, []);

  async function save(): Promise<void> {
    await saveSettings({ baseUrl, token });
    setNote("Saved.");
    props.onSaved();
  }

  return (
    <View style={styles.fill}>
      <Text style={styles.label}>Dashboard base URL</Text>
      <TextInput
        style={styles.input}
        value={baseUrl}
        onChangeText={setBaseUrl}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        placeholder="http://192.168.1.20:8400"
      />
      <Text style={styles.label}>API token (Authorization: Bearer …)</Text>
      <TextInput
        style={styles.input}
        value={token}
        onChangeText={setToken}
        autoCapitalize="none"
        autoCorrect={false}
        secureTextEntry
        placeholder="leave empty if dashboard auth is off"
      />
      <Pressable style={styles.button} onPress={save}>
        <Text style={styles.buttonText}>Save</Text>
      </Pressable>
      {note ? <Text style={styles.note}>{note}</Text> : null}
      <Text style={styles.help}>
        This app is read-only: it watches runs and never starts, cancels, or
        approves anything. The phone must be able to reach the dashboard
        (same network, VPN, or tunnel). The token is kept in the device
        keychain (expo-secure-store).
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, padding: 16 },
  label: { fontSize: 13, color: "#57606a", marginTop: 14, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: "#d0d7de", borderRadius: 6,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 15,
  },
  button: {
    marginTop: 20, backgroundColor: "#1f6feb", borderRadius: 6,
    paddingVertical: 10, alignItems: "center",
  },
  buttonText: { color: "#ffffff", fontSize: 15, fontWeight: "600" },
  note: { marginTop: 10, color: "#2da44e" },
  help: { marginTop: 24, fontSize: 13, color: "#57606a", lineHeight: 19 },
});
