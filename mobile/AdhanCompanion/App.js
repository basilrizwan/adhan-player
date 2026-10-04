import { useMemo, useState } from "react";
import {
  Platform,
  Pressable,
  SafeAreaView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { WebView } from "react-native-webview";
import { StatusBar as ExpoStatusBar } from "expo-status-bar";

const DEFAULT_HOST = "http://adhan.local:8080";

/**
 * Thin companion shell: opens the device's local PWA.
 * Android can later plug NSD for _adhan._tcp; iOS usually needs a typed host/IP.
 */
export default function App() {
  const [host, setHost] = useState(DEFAULT_HOST);
  const [url, setUrl] = useState(DEFAULT_HOST);
  const [showFinder, setShowFinder] = useState(true);

  const normalized = useMemo(() => {
    let h = host.trim();
    if (!h) return DEFAULT_HOST;
    if (!/^https?:\/\//i.test(h)) h = `http://${h}`;
    return h.replace(/\/$/, "");
  }, [host]);

  if (!showFinder) {
    return (
      <SafeAreaView style={styles.safe}>
        <ExpoStatusBar style="light" />
        <View style={styles.bar}>
          <Pressable onPress={() => setShowFinder(true)} style={styles.chip}>
            <Text style={styles.chipText}>Change device</Text>
          </Pressable>
          <Text style={styles.barUrl} numberOfLines={1}>
            {url}
          </Text>
        </View>
        <WebView
          source={{ uri: url }}
          style={styles.web}
          allowsBackForwardNavigationGestures
          startInLoadingState
        />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ExpoStatusBar style="light" />
      <View style={styles.hero}>
        <Text style={styles.brand}>Adhan Companion</Text>
        <Text style={styles.lede}>
          Opens the portal on your Adhan Player. Same Wi‑Fi required — no cloud account.
        </Text>

        <Text style={styles.label}>Device URL or IP</Text>
        <TextInput
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          placeholder="http://adhan.local:8080"
          placeholderTextColor="#7f9488"
          style={styles.input}
          value={host}
          onChangeText={setHost}
        />

        <Pressable
          style={styles.primary}
          onPress={() => {
            setUrl(normalized);
            setShowFinder(false);
          }}
        >
          <Text style={styles.primaryText}>Open portal</Text>
        </Pressable>

        <Pressable
          style={styles.secondary}
          onPress={() => {
            setHost(DEFAULT_HOST);
            setUrl(DEFAULT_HOST);
            setShowFinder(false);
          }}
        >
          <Text style={styles.secondaryText}>Try adhan.local</Text>
        </Pressable>

        <Text style={styles.hint}>
          {Platform.OS === "ios"
            ? "On iPhone, type the IP from the Pi QR code if .local does not resolve."
            : "On Android, you can also bookmark http://adhan.local:8080 in Chrome (PWA)."}
        </Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: "#0b1f18",
    paddingTop: Platform.OS === "android" ? StatusBar.currentHeight : 0,
  },
  hero: { flex: 1, padding: 24, justifyContent: "center", gap: 12 },
  brand: { color: "#f4efe4", fontSize: 34, fontWeight: "700", letterSpacing: -0.5 },
  lede: { color: "#b7c7bc", fontSize: 16, lineHeight: 22, marginBottom: 12 },
  label: { color: "#d4a24c", fontSize: 13, fontWeight: "600", textTransform: "uppercase" },
  input: {
    borderWidth: 1,
    borderColor: "rgba(244,239,228,0.15)",
    backgroundColor: "rgba(0,0,0,0.25)",
    color: "#f4efe4",
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 14,
    fontSize: 16,
  },
  primary: {
    backgroundColor: "#d4a24c",
    borderRadius: 14,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 8,
  },
  primaryText: { color: "#1a1205", fontWeight: "700", fontSize: 16 },
  secondary: {
    borderWidth: 1,
    borderColor: "rgba(244,239,228,0.15)",
    borderRadius: 14,
    paddingVertical: 14,
    alignItems: "center",
  },
  secondaryText: { color: "#f4efe4", fontWeight: "600" },
  hint: { color: "#7f9488", marginTop: 10, lineHeight: 20 },
  bar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: "rgba(244,239,228,0.1)",
  },
  chip: {
    backgroundColor: "rgba(212,162,76,0.2)",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
  },
  chipText: { color: "#d4a24c", fontWeight: "600", fontSize: 12 },
  barUrl: { color: "#b7c7bc", flex: 1, fontSize: 12 },
  web: { flex: 1, backgroundColor: "#0b1f18" },
});
