import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useRef } from "react";
import * as SecureStore from "expo-secure-store";

const SERVER_ORIGIN = (process.env.EXPO_PUBLIC_API_URL || "https://g-fleet-iq.onrender.com").replace(/\/+$/, "");
const API_BASE = `${SERVER_ORIGIN}/api/mobile`;

async function request(path, token, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Token ${token}` } : {}),
      ...options.headers,
    },
  });
  const body = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body?.detail || "Could not reach G Fleet IQ. Please try again.");
    error.status = response.status;
    throw error;
  }
  return body;
}

function PrimaryButton({ title, onPress, disabled, tone = "blue" }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={title}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        styles[`button_${tone}`],
        disabled && styles.buttonDisabled,
        pressed && !disabled && styles.buttonPressed,
      ]}
    >
      <Text style={styles.buttonText}>{title}</Text>
    </Pressable>
  );
}

function StatCard({ label, value, icon }) {
  return (
    <View style={styles.statCard}>
      <Text style={styles.statIcon}>{icon}</Text>
      <Text style={styles.statValue}>{value ?? 0}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function LoadCard({ load, canDispatch, onAction, busy }) {
  const canAssign = canDispatch && load.status === "Available";
  const canDeliver = canDispatch && load.status === "Assigned";
  return (
    <View style={styles.loadCard}>
      <View style={styles.loadTopLine}>
        <Text style={styles.loadCustomer} numberOfLines={1}>{load.customer}</Text>
        <Text style={[styles.statusPill, load.status === "Delivered" && styles.statusDelivered]}>
          {load.status}
        </Text>
      </View>
      {load.company ? <Text style={styles.companyName}>{load.company}</Text> : null}
      <View style={styles.routeBlock}>
        <Text style={styles.routeLabel}>PICKUP</Text>
        <Text style={styles.routeValue}>{load.pickup}</Text>
        <Text style={[styles.routeLabel, styles.deliveryLabel]}>DELIVERY</Text>
        <Text style={styles.routeValue}>{load.delivery}</Text>
      </View>
      <View style={styles.assignmentLine}>
        <Text style={styles.assignmentText}>Driver: {load.driver || "Unassigned"}</Text>
        {load.priority ? <Text style={styles.priorityText}>{load.priority}</Text> : null}
      </View>
      {canAssign ? (
        <PrimaryButton
          title={busy ? "Assigning…" : "Assign best available equipment"}
          disabled={busy}
          onPress={() => onAction(load, "assign")}
        />
      ) : null}
      {canDeliver ? (
        <PrimaryButton
          title={busy ? "Updating…" : "Mark delivered"}
          tone="green"
          disabled={busy}
          onPress={() => onAction(load, "deliver")}
        />
      ) : null}
    </View>
  );
}

export default function App() {
  const passwordInput = useRef(null);
  const [token, setToken] = useState(null);
  const [screen, setScreen] = useState("dashboard");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [dashboard, setDashboard] = useState(null);
  const [loadsData, setLoadsData] = useState(null);
  const [loginBusy, setLoginBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [busyLoadId, setBusyLoadId] = useState(null);
  const [error, setError] = useState("");

  const resetLogin = useCallback(async () => {
    await SecureStore.deleteItemAsync("gfleetiq_token").catch(() => {});
    setToken(null);
    setDashboard(null);
    setLoadsData(null);
    setPassword("");
  }, []);

  const loadDashboard = useCallback(async (activeToken, quiet = false) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const data = await request("/dashboard/", activeToken);
      setDashboard(data);
    } catch (exception) {
      if (exception.status === 401) {
        await resetLogin();
        setError("Please sign in again to continue.");
      } else {
        setError(exception.message);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [resetLogin]);

  const loadLoads = useCallback(async (activeToken, quiet = false) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const data = await request("/loads/", activeToken);
      setLoadsData(data);
    } catch (exception) {
      if (exception.status === 401) await resetLogin();
      setError(exception.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [resetLogin]);

  useEffect(() => {
    let active = true;
    SecureStore.getItemAsync("gfleetiq_token")
      .then((savedToken) => {
        if (!active || !savedToken) return;
        setToken(savedToken);
      })
      .catch(() => setError("Could not open the saved sign-in. Please sign in again."));
    return () => { active = false; };
  }, [loadDashboard]);

  useEffect(() => {
    if (!token) return;
    if (screen === "loads" && !loadsData) loadLoads(token);
    if (screen === "dashboard" && !dashboard) loadDashboard(token);
  }, [token, screen, loadsData, dashboard, loadDashboard, loadLoads]);

  async function signIn() {
    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }
    setLoginBusy(true);
    setError("");
    try {
      const result = await request("/login/", null, {
        method: "POST",
        body: JSON.stringify({ username: username.trim(), password }),
      });
      await SecureStore.setItemAsync("gfleetiq_token", result.token);
      setToken(result.token);
      setPassword("");
      setScreen("dashboard");
    } catch (exception) {
      setError(exception.message);
    } finally {
      setLoginBusy(false);
    }
  }

  async function signOut() {
    const currentToken = token;
    await request("/logout/", currentToken, { method: "POST" }).catch(() => {});
    await resetLogin();
    setError("");
    setScreen("dashboard");
  }

  async function doLoadAction(load, action) {
    setBusyLoadId(load.id);
    setError("");
    try {
      await request(`/loads/${load.id}/${action}/`, token, { method: "POST" });
      setLoadsData(null);
      setDashboard(null);
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusyLoadId(null);
    }
  }

  function refresh() {
    setRefreshing(true);
    if (screen === "loads") loadLoads(token, true);
    else loadDashboard(token, true);
  }

  if (!token) {
    return (
      <SafeAreaView style={styles.safeArea}>
        <StatusBar barStyle="light-content" backgroundColor={colors.navy} />
        <View style={styles.brandHeader}>
          <View style={styles.brandMark}><Text style={styles.brandEmoji}>🚚</Text></View>
          <View>
            <Text style={styles.brandTitle}>G Fleet IQ</Text>
            <Text style={styles.brandSubtitle}>Fleet dispatch, wherever you are</Text>
          </View>
        </View>
        <View style={styles.loginContent}>
          <Text style={styles.eyebrow}>DISPATCHER & OWNER APP</Text>
          <Text style={styles.loginTitle}>Welcome back</Text>
          <Text style={styles.mutedText}>Sign in with your G Fleet IQ account.</Text>
          {error ? <Text accessibilityRole="alert" style={styles.errorBox}>{error}</Text> : null}
          <Text style={styles.inputLabel}>Username</Text>
          <TextInput
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="username"
            value={username}
            onChangeText={setUsername}
            onSubmitEditing={() => passwordInput.current?.focus()}
            placeholder="Enter your username"
            placeholderTextColor={colors.muted}
            returnKeyType="next"
            style={styles.input}
          />
          <Text style={styles.inputLabel}>Password</Text>
          <TextInput
            ref={passwordInput}
            autoCapitalize="none"
            autoComplete="current-password"
            secureTextEntry
            value={password}
            onChangeText={setPassword}
            onSubmitEditing={signIn}
            placeholder="Enter your password"
            placeholderTextColor={colors.muted}
            returnKeyType="go"
            style={styles.input}
          />
          <PrimaryButton title={loginBusy ? "Signing in…" : "Sign in"} onPress={signIn} disabled={loginBusy} />
          <Text style={styles.secureNote}>🔒 Your sign-in is stored securely on this device.</Text>
        </View>
      </SafeAreaView>
    );
  }

  const currentLoads = screen === "loads" ? loadsData?.loads : dashboard?.recent_loads;
  const canDispatch = screen === "loads" ? loadsData?.can_dispatch : dashboard?.can_dispatch;

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar barStyle="light-content" backgroundColor={colors.navy} />
      <View style={styles.topBar}>
        <View style={styles.topBarBrand}>
          <Text style={styles.topBarEmoji}>🚚</Text>
          <View>
            <Text style={styles.topBarTitle}>G Fleet IQ</Text>
            <Text style={styles.topBarAccount} numberOfLines={1}>{dashboard?.account_name || "Fleet workspace"}</Text>
          </View>
        </View>
        <Pressable accessibilityRole="button" onPress={signOut} style={styles.signOutButton}>
          <Text style={styles.signOutText}>Log out</Text>
        </Pressable>
      </View>

      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.blue} />}
      >
        {error ? <Text accessibilityRole="alert" style={styles.errorBox}>{error}</Text> : null}
        {screen === "dashboard" ? (
          <>
            <Text style={styles.eyebrow}>COMMAND CENTER</Text>
            <Text style={styles.pageTitle}>Your fleet at a glance</Text>
            <Text style={styles.mutedText}>Signed in as {dashboard?.username || username}</Text>
            <View style={styles.statsGrid}>
              <StatCard label="Active loads" value={dashboard?.summary?.active_loads} icon="📦" />
              <StatCard label="Loads" value={dashboard?.summary?.loads} icon="🧾" />
              <StatCard label="Available drivers" value={dashboard?.summary?.available_drivers} icon="👤" />
              <StatCard label="Available trucks" value={dashboard?.summary?.available_trucks} icon="🚛" />
              <StatCard label="Available trailers" value={dashboard?.summary?.available_trailers} icon="🚚" />
              <StatCard label="Total trucks" value={dashboard?.summary?.trucks} icon="🗺️" />
            </View>
            <View style={styles.sectionHeadingRow}>
              <Text style={styles.sectionTitle}>Recent loads</Text>
              <Pressable onPress={() => { setScreen("loads"); setLoadsData(null); }}>
                <Text style={styles.linkText}>See all</Text>
              </Pressable>
            </View>
            {loading && !dashboard ? <ActivityIndicator color={colors.blue} /> : null}
            {(currentLoads || []).length ? (currentLoads || []).map((load) => (
              <LoadCard key={load.id} load={load} canDispatch={canDispatch} onAction={doLoadAction} busy={busyLoadId === load.id} />
            )) : (!loading ? <Text style={styles.emptyCard}>No loads yet.</Text> : null)}
          </>
        ) : (
          <>
            <Text style={styles.eyebrow}>FLEET OPERATIONS</Text>
            <Text style={styles.pageTitle}>Loads</Text>
            <Text style={styles.mutedText}>View and manage loads your account can access.</Text>
            {loading && !loadsData ? <ActivityIndicator color={colors.blue} style={styles.loader} /> : null}
            {(currentLoads || []).length ? (currentLoads || []).map((load) => (
              <LoadCard key={load.id} load={load} canDispatch={canDispatch} onAction={doLoadAction} busy={busyLoadId === load.id} />
            )) : (!loading ? <Text style={styles.emptyCard}>No loads found.</Text> : null)}
          </>
        )}
        <Text style={styles.footerNote}>G Fleet IQ · Secure fleet operations</Text>
      </ScrollView>

      <View style={styles.tabBar}>
        <Pressable onPress={() => { setScreen("dashboard"); setError(""); }} style={styles.tabButton}>
          <Text style={[styles.tabIcon, screen === "dashboard" && styles.tabActive]}>⌂</Text>
          <Text style={[styles.tabLabel, screen === "dashboard" && styles.tabActive]}>Home</Text>
        </Pressable>
        <Pressable onPress={() => { setScreen("loads"); setError(""); }} style={styles.tabButton}>
          <Text style={[styles.tabIcon, screen === "loads" && styles.tabActive]}>▤</Text>
          <Text style={[styles.tabLabel, screen === "loads" && styles.tabActive]}>Loads</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const colors = {
  navy: "#10233f",
  blue: "#1769f5",
  green: "#138557",
  background: "#f3f6fb",
  ink: "#14243a",
  muted: "#68788d",
  border: "#e0e7f0",
  white: "#ffffff",
  red: "#a9333e",
};

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.background },
  brandHeader: { backgroundColor: colors.navy, paddingHorizontal: 24, paddingVertical: 24, flexDirection: "row", alignItems: "center", gap: 14 },
  brandMark: { width: 54, height: 54, borderRadius: 16, backgroundColor: colors.blue, alignItems: "center", justifyContent: "center" },
  brandEmoji: { fontSize: 27 },
  brandTitle: { color: colors.white, fontWeight: "800", fontSize: 23 },
  brandSubtitle: { color: "#bfd2f2", fontSize: 13, marginTop: 3 },
  loginContent: { flex: 1, padding: 24, justifyContent: "center" },
  eyebrow: { color: colors.blue, fontWeight: "800", fontSize: 11, letterSpacing: 1.2, marginBottom: 7 },
  loginTitle: { color: colors.ink, fontSize: 29, fontWeight: "800", marginBottom: 5 },
  mutedText: { color: colors.muted, fontSize: 14, lineHeight: 21 },
  inputLabel: { color: colors.ink, fontSize: 14, fontWeight: "700", marginTop: 20, marginBottom: 7 },
  input: { backgroundColor: colors.white, color: colors.ink, borderColor: colors.border, borderWidth: 1, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 14, fontSize: 16 },
  button: { borderRadius: 12, minHeight: 48, paddingHorizontal: 16, alignItems: "center", justifyContent: "center", marginTop: 14 },
  button_blue: { backgroundColor: colors.blue },
  button_green: { backgroundColor: colors.green },
  buttonDisabled: { opacity: 0.6 },
  buttonPressed: { opacity: 0.82 },
  buttonText: { color: colors.white, fontSize: 14, fontWeight: "800", textAlign: "center" },
  secureNote: { color: colors.muted, fontSize: 12, textAlign: "center", marginTop: 18 },
  errorBox: { color: colors.red, backgroundColor: "#fde7e8", borderColor: "#f1bdc0", borderWidth: 1, borderRadius: 10, padding: 12, marginVertical: 12, fontSize: 14, lineHeight: 19 },
  topBar: { backgroundColor: colors.navy, paddingHorizontal: 18, paddingVertical: 14, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  topBarBrand: { flexDirection: "row", alignItems: "center", gap: 11, flex: 1 },
  topBarEmoji: { fontSize: 26 },
  topBarTitle: { color: colors.white, fontSize: 17, fontWeight: "800" },
  topBarAccount: { color: "#bfd2f2", fontSize: 11, marginTop: 2, maxWidth: 220 },
  signOutButton: { paddingHorizontal: 12, paddingVertical: 9, borderColor: "#62728a", borderWidth: 1, borderRadius: 9 },
  signOutText: { color: colors.white, fontWeight: "700", fontSize: 12 },
  scrollContent: { padding: 18, paddingBottom: 32 },
  pageTitle: { color: colors.ink, fontSize: 25, fontWeight: "800", marginBottom: 4 },
  statsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 19, marginBottom: 25 },
  statCard: { flexGrow: 1, flexBasis: "30%", minWidth: 98, backgroundColor: colors.white, borderRadius: 14, borderWidth: 1, borderColor: colors.border, padding: 13, minHeight: 105, justifyContent: "center", alignItems: "flex-start" },
  statIcon: { fontSize: 19, marginBottom: 5 },
  statValue: { color: colors.ink, fontSize: 23, fontWeight: "800" },
  statLabel: { color: colors.muted, fontSize: 11, marginTop: 2, lineHeight: 15 },
  sectionHeadingRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 3, marginBottom: 10 },
  sectionTitle: { color: colors.ink, fontSize: 18, fontWeight: "800" },
  linkText: { color: colors.blue, fontSize: 13, fontWeight: "700" },
  loadCard: { backgroundColor: colors.white, borderColor: colors.border, borderWidth: 1, borderRadius: 14, padding: 15, marginBottom: 12, shadowColor: "#1c3555", shadowOpacity: 0.04, shadowRadius: 7, shadowOffset: { width: 0, height: 3 }, elevation: 1 },
  loadTopLine: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  loadCustomer: { flex: 1, color: colors.ink, fontSize: 16, fontWeight: "800" },
  statusPill: { backgroundColor: "#e8f0ff", color: "#1754bd", overflow: "hidden", borderRadius: 20, paddingHorizontal: 9, paddingVertical: 5, fontSize: 11, fontWeight: "800" },
  statusDelivered: { backgroundColor: "#e5f7ee", color: "#147245" },
  companyName: { color: colors.muted, fontSize: 12, marginTop: 3 },
  routeBlock: { borderLeftWidth: 2, borderLeftColor: "#c9d9f7", marginTop: 13, marginLeft: 3, paddingLeft: 12 },
  routeLabel: { color: colors.muted, fontSize: 9, letterSpacing: 1, fontWeight: "800" },
  deliveryLabel: { marginTop: 10 },
  routeValue: { color: colors.ink, fontSize: 14, marginTop: 3, lineHeight: 19 },
  assignmentLine: { marginTop: 13, flexDirection: "row", justifyContent: "space-between", gap: 8 },
  assignmentText: { color: colors.muted, fontSize: 12, flex: 1 },
  priorityText: { color: colors.ink, fontSize: 11, fontWeight: "700" },
  emptyCard: { backgroundColor: colors.white, borderRadius: 14, borderColor: colors.border, borderWidth: 1, padding: 18, color: colors.muted },
  loader: { marginVertical: 24 },
  footerNote: { color: colors.muted, fontSize: 11, textAlign: "center", marginTop: 20 },
  tabBar: { backgroundColor: colors.white, borderTopColor: colors.border, borderTopWidth: 1, flexDirection: "row", paddingTop: 8, paddingBottom: 6 },
  tabButton: { flex: 1, alignItems: "center", paddingVertical: 4 },
  tabIcon: { color: colors.muted, fontSize: 22 },
  tabLabel: { color: colors.muted, fontSize: 11, fontWeight: "700", marginTop: 1 },
  tabActive: { color: colors.blue },
});
