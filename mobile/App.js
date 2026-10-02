import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Modal,
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
import * as Location from "expo-location";

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
  const [expanded, setExpanded] = useState(false);
  const canAssign = canDispatch && load.status === "Available";
  const canDeliver = canDispatch && load.status === "Assigned";
  return (
    <View style={styles.loadCard}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${expanded ? "Hide" : "Open"} ${load.customer} load details`}
        accessibilityState={{ expanded }}
        onPress={() => setExpanded((open) => !open)}
        style={({ pressed }) => [styles.loadCardHeader, pressed && styles.cardPressed]}
      >
        <View style={styles.loadTopLine}>
          <Text style={styles.loadCustomer} numberOfLines={1}>{load.customer}</Text>
          <Text style={[styles.statusPill, load.status === "Delivered" && styles.statusDelivered]}>
            {load.status}
          </Text>
        </View>
        {load.company ? <Text style={styles.companyName}>{load.company}</Text> : null}
        <Text style={styles.expandHint}>{expanded ? "Hide details  ▲" : "Tap to view load details  ▼"}</Text>
      </Pressable>
      <View style={styles.assignmentLine}>
        <Text style={styles.assignmentText}>Driver: {load.driver || "Not assigned"}</Text>
        {load.priority ? <Text style={styles.priorityText}>{load.priority}</Text> : null}
      </View>
      {expanded ? (
        <>
          <View style={styles.routeBlock}>
            <Text style={styles.routeLabel}>PICKUP</Text>
            <Text style={styles.routeValue}>{load.pickup}</Text>
            <Text style={[styles.routeLabel, styles.deliveryLabel]}>DELIVERY</Text>
            <Text style={styles.routeValue}>{load.delivery}</Text>
          </View>
        </>
      ) : null}
      {canAssign ? (
        <PrimaryButton
          title={busy ? "Dispatching…" : "Dispatch to best available driver"}
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

function InfoCard({ title, lines = [] }) {
  return (
    <View style={styles.infoCard}>
      <Text style={styles.infoTitle}>{title}</Text>
      {lines.filter(Boolean).map((line, index) => (
        <Text key={`${title}-${index}`} style={styles.infoLine}>{line}</Text>
      ))}
    </View>
  );
}

const SECTION_TITLES = {
  dashboard: "Dashboard",
  companies: "Client Companies",
  customers: "Customers",
  drivers: "Drivers",
  trucks: "Trucks",
  trailers: "Trailers",
  loads: "Loads",
  dispatch_board: "Dispatch Board",
  ai_dispatch: "AI Dispatch",
  fleet_map: "Fleet Map",
  account_team: "Administrators",
  client_teams: "Client Teams",
};

const CREATE_FIELDS = {
  companies: [
    ["name", "Company name"], ["dot_number", "DOT number"], ["mc_number", "MC number"],
    ["phone", "Phone"], ["email", "Email"],
  ],
  customers: [["name", "Customer name"], ["location", "Location"], ["company", "Client company"]],
  drivers: [["name", "Driver name"], ["location", "Location"], ["phone", "Phone"], ["company", "Client company"], ["login_username", "Driver app username"], ["login_password", "Driver app password"]],
  trucks: [["unit_number", "Truck unit number"], ["capacity", "Capacity (lb)"], ["company", "Client company"]],
  trailers: [["trailer_number", "Trailer number"], ["location", "Location"], ["company", "Client company"]],
  loads: [["customer", "Existing customer name"], ["pickup", "Pickup location"], ["delivery", "Delivery location"]],
};
const CREATE_TITLES = {
  companies: "company", customers: "customer", drivers: "driver",
  trucks: "truck", trailers: "trailer", loads: "load",
};
const createTypeForScreen = (screen) => ["dispatch_board", "ai_dispatch"].includes(screen) ? "loads" : screen;

const BASE_MENU_ITEMS = [
  { key: "dashboard", icon: "🏠" },
  { key: "companies", icon: "🏢", accountAdminOnly: true },
  { key: "customers", icon: "👥" },
  { key: "drivers", icon: "👤" },
  { key: "trucks", icon: "🚛" },
  { key: "trailers", icon: "🚚" },
  { key: "loads", icon: "📦" },
  { key: "dispatch_board", icon: "📋" },
  { key: "ai_dispatch", icon: "🤖" },
  { key: "fleet_map", icon: "🗺️" },
  { key: "account_team", icon: "🛡️", ownerOnly: true },
  { key: "client_teams", icon: "👥", teamAdminOnly: true },
];

function getSectionCards(screen, workspace) {
  if (!workspace) return [];
  const card = (title, values) => ({ title, lines: values });
  if (screen === "companies") return workspace.companies.map((item) => card(item.name, [
    item.dot_number ? `DOT ${item.dot_number}` : "",
    item.mc_number ? `MC ${item.mc_number}` : "",
    item.phone,
    item.email,
    item.active ? "Active" : "Inactive",
  ]));
  if (screen === "customers") return workspace.customers.map((item) => card(item.name, [item.location, item.company]));
  if (screen === "drivers") return workspace.drivers.map((item) => card(item.name, [
    `${item.status}${item.available ? " · Available" : ""}`,
    item.company,
    item.truck ? `Truck ${item.truck}` : "",
    item.location,
  ]));
  if (screen === "trucks") return workspace.trucks.map((item) => card(item.unit_number, [
    `${item.status} · ${item.capacity.toLocaleString()} lb capacity`, item.company,
  ]));
  if (screen === "trailers") return workspace.trailers.map((item) => card(item.trailer_number, [
    `${item.status}${item.available ? " · Available" : ""}`, item.location, item.company,
  ]));
  if (screen === "fleet_map") return workspace.trucks.map((item) => card(`🚛 ${item.unit_number}`, [
    item.company,
    `Location: ${Number(item.latitude).toFixed(4)}, ${Number(item.longitude).toFixed(4)}`,
  ]));
  if (screen === "account_team") return workspace.account_team.map((item) => card(item.username, [item.role]));
  if (screen === "client_teams") return workspace.client_teams.map((team) => card(team.company,
    team.members.length ? team.members.map((member) => `${member.username} · ${member.role}`) : ["No team members yet."],
  ));
  return [];
}

function nextDriverStep(load) {
  if (!load.pickup_arrived_at) return ["pickup-arrived", "Arrived at pickup"];
  if (!load.pickup_departed_at) return ["pickup-departed", "Departed pickup"];
  if (!load.delivery_arrived_at) return ["delivery-arrived", "Arrived at delivery"];
  if (!load.delivery_departed_at) return ["delivery-departed", "Departed delivery · Complete load"];
  return null;
}

function stopTime(value) {
  return value ? new Date(value).toLocaleString() : "";
}

function durationLabel(seconds = 0) {
  const safeSeconds = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

function DriverLoadCard({ load, index, onAction, busy }) {
  const nextStep = nextDriverStep(load);
  return (
    <View style={styles.driverLoadCard}>
      <Text style={styles.eyebrow}>{index === 0 ? "CURRENT LOAD" : "NEXT LOAD"}</Text>
      <Text style={styles.driverLoadTitle}>{load.customer}</Text>
      {load.company ? <Text style={styles.mutedText}>{load.company}</Text> : null}
      <View style={styles.routeBlock}>
        <Text style={styles.routeLabel}>PICKUP</Text>
        <Text style={styles.routeValue}>{load.pickup}</Text>
        <Text style={[styles.routeLabel, styles.deliveryLabel]}>DELIVERY</Text>
        <Text style={styles.routeValue}>{load.delivery}</Text>
      </View>
      <Text style={styles.driverEquipment}>Truck {load.truck || "not assigned"} · Trailer {load.trailer || "not assigned"}</Text>
      {nextStep ? (
        <PrimaryButton
          title={busy ? "Saving update…" : nextStep[1]}
          disabled={busy}
          onPress={() => onAction(load, nextStep[0])}
        />
      ) : null}
      <View style={styles.driverTimeline}>
        <Text style={styles.driverTimelineText}>{load.pickup_arrived_at ? `✓ At pickup · ${stopTime(load.pickup_arrived_at)}` : "○ Pickup arrival"}</Text>
        <Text style={styles.driverTimelineText}>{load.pickup_departed_at ? `✓ Left pickup · ${stopTime(load.pickup_departed_at)}` : "○ Pickup departure"}</Text>
        <Text style={styles.driverTimelineText}>{load.delivery_arrived_at ? `✓ At delivery · ${stopTime(load.delivery_arrived_at)}` : "○ Delivery arrival"}</Text>
        <Text style={styles.driverTimelineText}>{load.delivery_departed_at ? `✓ Left delivery · ${stopTime(load.delivery_departed_at)}` : "○ Delivery departure"}</Text>
      </View>
    </View>
  );
}

function DriverHome({ token, onSignOut }) {
  const [driverData, setDriverData] = useState(null);
  const [dutyData, setDutyData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyLoadId, setBusyLoadId] = useState(null);
  const [busyDuty, setBusyDuty] = useState(false);
  const [locationNotice, setLocationNotice] = useState("Checking tablet location permission…");
  const [error, setError] = useState("");
  const locationPostBusy = useRef(false);

  const refreshLoads = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const [loads, duty] = await Promise.all([
        request("/driver/loads/", token),
        request("/driver/duty-log/", token),
      ]);
      setDriverData(loads);
      setDutyData(duty);
    } catch (exception) {
      setError(exception.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token]);

  useEffect(() => { refreshLoads(); }, [refreshLoads]);

  useEffect(() => {
    let active = true;
    let subscription = null;

    async function startLocationWatch() {
      try {
        const permission = await Location.requestForegroundPermissionsAsync();
        if (!active) return;
        if (permission.status !== "granted") {
          setLocationNotice("Location is off. You can still set your status manually.");
          return;
        }

        setLocationNotice("Automatic Driving detection runs while this app is open.");
        const nextSubscription = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.High, timeInterval: 10000, distanceInterval: 50 },
          async (location) => {
            if (!active || locationPostBusy.current) return;
            if ((location.coords.accuracy ?? 999) > 60) {
              setLocationNotice("Waiting for a good location signal. You can still set your status manually.");
              return;
            }
            locationPostBusy.current = true;
            try {
              const result = await request("/driver/location/", token, {
                method: "POST",
                body: JSON.stringify({
                  latitude: location.coords.latitude,
                  longitude: location.coords.longitude,
                  accuracy: location.coords.accuracy,
                  speed_mph: Math.max(0, location.coords.speed || 0) * 2.236936,
                }),
              });
              if (active) {
                setDutyData((current) => ({ ...current, ...result }));
                if (result.automatic_change) setLocationNotice("Movement detected. Your status changed to Driving.");
                else setLocationNotice("Automatic Driving detection is on while this app is open.");
              }
            } catch (exception) {
              if (active) setLocationNotice("Location update paused. You can still set your status manually.");
            } finally {
              locationPostBusy.current = false;
            }
          },
        );
        if (active) subscription = nextSubscription;
        else nextSubscription.remove();
      } catch (exception) {
        if (active) setLocationNotice("Location is unavailable. You can still set your status manually.");
      }
    }

    startLocationWatch();
    return () => {
      active = false;
      subscription?.remove();
    };
  }, [token]);

  async function recordStop(load, action) {
    setBusyLoadId(load.id);
    setError("");
    try {
      await request(`/driver/loads/${load.id}/${action}/`, token, { method: "POST" });
      await refreshLoads(true);
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusyLoadId(null);
    }
  }

  async function changeDutyStatus(nextStatus) {
    setBusyDuty(true);
    setError("");
    try {
      await request("/driver/duty-status/", token, {
        method: "POST",
        body: JSON.stringify({ status: nextStatus }),
      });
      await refreshLoads(true);
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusyDuty(false);
    }
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar barStyle="light-content" backgroundColor={colors.navy} />
      <View style={styles.topBar}>
        <View style={styles.topBarBrand}>
          <Text style={styles.topBarEmoji}>🚚</Text>
          <View>
            <Text style={styles.topBarTitle}>G Fleet IQ Driver</Text>
            <Text style={styles.topBarAccount} numberOfLines={1}>{driverData?.driver || "Driver"}</Text>
          </View>
        </View>
        <Pressable accessibilityRole="button" onPress={onSignOut} style={styles.signOutButton}>
          <Text style={styles.signOutText}>Log out</Text>
        </Pressable>
      </View>
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); refreshLoads(true); }} tintColor={colors.blue} />}
      >
        <Text style={styles.eyebrow}>DRIVER WORKSPACE</Text>
        <Text style={styles.pageTitle}>Your loads</Text>
        {driverData?.truck ? <Text style={styles.mutedText}>Truck {driverData.truck}</Text> : null}
        {error ? <Text accessibilityRole="alert" style={styles.errorBox}>{error}</Text> : null}
        {loading && !driverData ? <ActivityIndicator color={colors.blue} style={styles.loader} /> : null}
        <View style={styles.dutyCard}>
          <Text style={styles.eyebrow}>TODAY'S DAILY LOG</Text>
          <Text style={styles.dutyCurrent}>Current status: {dutyData?.current_status_label || "Not started"}</Text>
          <View style={styles.dutyTotals}>
            <View style={styles.dutyTotal}><Text style={styles.dutyLabel}>WORKED</Text><Text style={styles.dutyValue}>{durationLabel(dutyData?.totals?.worked)}</Text></View>
            <View style={styles.dutyTotal}><Text style={styles.dutyLabel}>DRIVING</Text><Text style={styles.dutyValue}>{durationLabel(dutyData?.totals?.driving)}</Text></View>
            <View style={styles.dutyTotal}><Text style={styles.dutyLabel}>ON DUTY · NOT DRIVING</Text><Text style={styles.dutyValue}>{durationLabel(dutyData?.totals?.on_duty)}</Text></View>
            <View style={styles.dutyTotal}><Text style={styles.dutyLabel}>OFF DUTY</Text><Text style={styles.dutyValue}>{durationLabel(dutyData?.totals?.off_duty)}</Text></View>
          </View>
          <Text style={styles.dutyPrompt}>Tap when your work status changes:</Text>
          <Text style={styles.locationNotice}>{locationNotice}</Text>
          <View style={styles.dutyActions}>
            {[["on_duty", "On duty · not driving"], ["driving", "Driving"], ["off_duty", "Off duty"]].map(([status, label]) => (
              <Pressable
                key={status}
                accessibilityRole="button"
                accessibilityLabel={label}
                disabled={busyDuty || dutyData?.current_status === status}
                onPress={() => changeDutyStatus(status)}
                style={({ pressed }) => [styles.dutyAction, dutyData?.current_status === status && styles.dutyActionActive, pressed && !busyDuty && styles.cardPressed]}
              >
                <Text style={[styles.dutyActionText, dutyData?.current_status === status && styles.dutyActionTextActive]}>{busyDuty ? "Saving…" : label}</Text>
              </Pressable>
            ))}
          </View>
          {(dutyData?.entries || []).length ? (
            <View style={styles.dutyTimeline}>
              <Text style={styles.dutyTimelineTitle}>TODAY'S TIMELINE</Text>
              {dutyData.entries.map((entry, index) => (
                <Text key={`${entry.started_at}-${index}`} style={styles.dutyTimelineText}>
                  {new Date(entry.started_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} · {entry.status_label}{entry.source === "automatic" ? " · Auto" : ""} · {durationLabel(entry.duration_seconds)}{entry.active ? " · Current" : ""}
                </Text>
              ))}
            </View>
          ) : <Text style={styles.dutyEmpty}>Choose a status to start today's log.</Text>}
          {(dutyData?.stop_events || []).length ? (
            <View style={styles.dutyTimeline}>
              <Text style={styles.dutyTimelineTitle}>PICKUP & DELIVERY UPDATES</Text>
              {dutyData.stop_events.map((event, index) => (
                <Text key={`${event.occurred_at}-${index}`} style={styles.dutyTimelineText}>
                  {new Date(event.occurred_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} · {event.label} · {event.customer} · {event.location}
                </Text>
              ))}
            </View>
          ) : null}
          <Text style={styles.dutyNote}>Movement can switch your status to Driving at 10 mph or after more than 2 miles. Keep this app open for automatic detection. This is an activity log, not a certified electronic log.</Text>
        </View>
        {(driverData?.loads || []).length ? driverData.loads.map((load, index) => (
          <DriverLoadCard
            key={load.id}
            load={load}
            index={index}
            onAction={recordStop}
            busy={busyLoadId === load.id}
          />
        )) : (!loading ? <Text style={styles.emptyCard}>No loads assigned yet. Your next load will appear here after dispatch assigns it.</Text> : null)}
      </ScrollView>
    </SafeAreaView>
  );
}

export default function App() {
  const passwordInput = useRef(null);
  const [token, setToken] = useState(null);
  const [userType, setUserType] = useState(null);
  const [screen, setScreen] = useState("dashboard");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [dashboard, setDashboard] = useState(null);
  const [loadsData, setLoadsData] = useState(null);
  const [workspaceData, setWorkspaceData] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createValues, setCreateValues] = useState({});
  const [savingRecord, setSavingRecord] = useState(false);
  const [loginBusy, setLoginBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [busyLoadId, setBusyLoadId] = useState(null);
  const [error, setError] = useState("");

  const resetLogin = useCallback(async () => {
    await SecureStore.deleteItemAsync("gfleetiq_token").catch(() => {});
    await SecureStore.deleteItemAsync("gfleetiq_user_type").catch(() => {});
    setToken(null);
    setUserType(null);
    setDashboard(null);
    setLoadsData(null);
    setWorkspaceData(null);
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

  const loadWorkspace = useCallback(async (activeToken, quiet = false) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const data = await request("/workspace/", activeToken);
      setWorkspaceData(data);
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
    Promise.all([
      SecureStore.getItemAsync("gfleetiq_token"),
      SecureStore.getItemAsync("gfleetiq_user_type"),
    ])
      .then(([savedToken, savedUserType]) => {
        if (!active || !savedToken) return;
        if (savedUserType !== "driver") {
          SecureStore.deleteItemAsync("gfleetiq_token").catch(() => {});
          SecureStore.deleteItemAsync("gfleetiq_user_type").catch(() => {});
          setError("This mobile app is for driver accounts. Office and admin accounts should use the G Fleet IQ website.");
          return;
        }
        setToken(savedToken);
        setUserType(savedUserType);
      })
      .catch(() => setError("Could not open the saved sign-in. Please sign in again."));
    return () => { active = false; };
  }, [loadDashboard]);

  useEffect(() => {
    if (!token || userType === "driver") return;
    if (["loads", "dispatch_board", "ai_dispatch"].includes(screen) && !loadsData) loadLoads(token);
    if (screen === "dashboard" && !dashboard) loadDashboard(token);
    if (!["dashboard", "loads", "dispatch_board", "ai_dispatch"].includes(screen) && !workspaceData) loadWorkspace(token);
  }, [token, userType, screen, loadsData, dashboard, workspaceData, loadDashboard, loadLoads, loadWorkspace]);

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
      if (result.user_type !== "driver") {
        setPassword("");
        setError("This mobile app is for driver accounts. Office and admin accounts should use the G Fleet IQ website.");
        return;
      }
      await SecureStore.setItemAsync("gfleetiq_token", result.token);
      await SecureStore.setItemAsync("gfleetiq_user_type", result.user_type);
      setToken(result.token);
      setUserType(result.user_type);
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

  if (token && userType === "driver") {
    return <DriverHome token={token} onSignOut={signOut} />;
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

  function beginCreate() {
    const values = {};
    (CREATE_FIELDS[createTypeForScreen(screen)] || []).forEach(([key]) => { values[key] = ""; });
    setCreateValues(values);
    setError("");
    setCreateOpen(true);
  }

  async function saveRecord() {
    setSavingRecord(true);
    setError("");
    try {
      await request("/records/", token, {
        method: "POST",
        body: JSON.stringify({ ...createValues, type: createTypeForScreen(screen) }),
      });
      setCreateOpen(false);
      setCreateValues({});
      if (["loads", "dispatch_board", "ai_dispatch"].includes(screen)) {
        setLoadsData(null);
        await loadLoads(token);
      } else {
        setWorkspaceData(null);
        await loadWorkspace(token);
      }
      setDashboard(null);
    } catch (exception) {
      setError(exception.message);
    } finally {
      setSavingRecord(false);
    }
  }

  function openSection(section) {
    setScreen(section);
    setMenuOpen(false);
    setError("");
    if (["loads", "dispatch_board", "ai_dispatch"].includes(section)) setLoadsData(null);
  }

  function refresh() {
    setRefreshing(true);
    if (["loads", "dispatch_board", "ai_dispatch"].includes(screen)) loadLoads(token, true);
    else if (screen === "dashboard") loadDashboard(token, true);
    else loadWorkspace(token, true);
  }

  if (!token) {
    return (
      <SafeAreaView style={styles.safeArea}>
        <StatusBar barStyle="light-content" backgroundColor={colors.navy} />
        <View style={styles.brandHeader}>
          <View style={styles.brandMark}><Text style={styles.brandEmoji}>🚚</Text></View>
          <View>
            <Text style={styles.brandTitle}>G Fleet IQ</Text>
          <Text style={styles.brandSubtitle}>Driver loads and stop updates</Text>
          </View>
        </View>
        <View style={styles.loginContent}>
          <Text style={styles.eyebrow}>DRIVER APP</Text>
          <Text style={styles.loginTitle}>Welcome back</Text>
          <Text style={styles.mutedText}>Sign in with the driver username and password provided by your dispatcher.</Text>
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

  const loadScreens = ["loads", "dispatch_board", "ai_dispatch"];
  const currentLoads = loadScreens.includes(screen) ? loadsData?.loads : dashboard?.recent_loads;
  const canDispatch = loadScreens.includes(screen) ? loadsData?.can_dispatch : dashboard?.can_dispatch;
  const accountAdmin = ["owner", "admin"].includes(dashboard?.role);
  const visibleMenuItems = BASE_MENU_ITEMS.filter((item) => {
    if (item.accountAdminOnly && !accountAdmin) return false;
    if (item.ownerOnly && !dashboard?.can_manage_account) return false;
    if (item.teamAdminOnly && !accountAdmin && dashboard?.role !== "client_admin") return false;
    return true;
  });
  const sectionCards = getSectionCards(screen, workspaceData);

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
        <View style={styles.topBarActions}>
          <Pressable accessibilityRole="button" accessibilityLabel="Open menu" onPress={() => setMenuOpen(true)} style={styles.menuButton}>
            <Text style={styles.menuButtonText}>☰</Text>
          </Pressable>
          <Pressable accessibilityRole="button" onPress={signOut} style={styles.signOutButton}>
            <Text style={styles.signOutText}>Log out</Text>
          </Pressable>
        </View>
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
        ) : loadScreens.includes(screen) ? (
          <>
            <Text style={styles.eyebrow}>FLEET OPERATIONS</Text>
            <Text style={styles.pageTitle}>{SECTION_TITLES[screen]}</Text>
            {loadsData?.can_dispatch ? (
              <PrimaryButton title="＋ Add load" onPress={beginCreate} />
            ) : null}
            <Text style={styles.mutedText}>
              {screen === "ai_dispatch"
                ? "Review loads and assign the best available driver and equipment."
                : "View and manage loads your account can access."}
            </Text>
            {loading && !loadsData ? <ActivityIndicator color={colors.blue} style={styles.loader} /> : null}
            {(currentLoads || []).length ? (currentLoads || []).map((load) => (
              <LoadCard key={load.id} load={load} canDispatch={canDispatch} onAction={doLoadAction} busy={busyLoadId === load.id} />
            )) : (!loading ? <Text style={styles.emptyCard}>No loads found.</Text> : null)}
          </>
        ) : (
          <>
            <Text style={styles.eyebrow}>FLEET OPERATIONS</Text>
            <Text style={styles.pageTitle}>{SECTION_TITLES[screen]}</Text>
            {CREATE_FIELDS[createTypeForScreen(screen)] && (
              createTypeForScreen(screen) === "companies" ? accountAdmin : dashboard?.can_dispatch
            ) ? (
              <PrimaryButton title={`＋ Add ${CREATE_TITLES[createTypeForScreen(screen)]}`} onPress={beginCreate} />
            ) : null}
            {screen === "fleet_map" ? (
              <Text style={styles.mutedText}>Truck locations from your fleet records.</Text>
            ) : null}
            {loading && !workspaceData ? <ActivityIndicator color={colors.blue} style={styles.loader} /> : null}
            {sectionCards.length ? sectionCards.map((item, index) => (
              <InfoCard key={`${screen}-${index}`} title={item.title} lines={item.lines} />
            )) : (!loading ? <Text style={styles.emptyCard}>No information to show yet.</Text> : null)}
          </>
        )}
        <Text style={styles.footerNote}>G Fleet IQ · Secure fleet operations</Text>
      </ScrollView>

      <View style={styles.tabBar}>
        <Pressable onPress={() => openSection("dashboard")} style={styles.tabButton}>
          <Text style={[styles.tabIcon, screen === "dashboard" && styles.tabActive]}>⌂</Text>
          <Text style={[styles.tabLabel, screen === "dashboard" && styles.tabActive]}>Home</Text>
        </Pressable>
        <Pressable onPress={() => openSection("loads")} style={styles.tabButton}>
          <Text style={[styles.tabIcon, loadScreens.includes(screen) && styles.tabActive]}>▤</Text>
          <Text style={[styles.tabLabel, screen === "loads" && styles.tabActive]}>Loads</Text>
        </Pressable>
      </View>

      <Modal visible={menuOpen} transparent animationType="fade" onRequestClose={() => setMenuOpen(false)}>
        <View style={styles.menuModal}>
          <Pressable accessibilityLabel="Close menu" onPress={() => setMenuOpen(false)} style={styles.menuBackdrop} />
          <View style={styles.menuPanel}>
            <View style={styles.menuHeading}>
              <Text style={styles.menuTitle}>G Fleet IQ Menu</Text>
              <Pressable accessibilityRole="button" accessibilityLabel="Close menu" onPress={() => setMenuOpen(false)} style={styles.menuClose}>
                <Text style={styles.menuCloseText}>×</Text>
              </Pressable>
            </View>
            <ScrollView>
              {visibleMenuItems.map((item) => (
                <Pressable
                  key={item.key}
                  accessibilityRole="button"
                  onPress={() => openSection(item.key)}
                  style={({ pressed }) => [styles.menuItem, pressed && styles.menuItemPressed]}
                >
                  <Text style={styles.menuItemIcon}>{item.icon}</Text>
                  <Text style={styles.menuItemLabel}>{SECTION_TITLES[item.key]}</Text>
                  <Text style={styles.menuItemArrow}>›</Text>
                </Pressable>
              ))}
            </ScrollView>
          </View>
        </View>
      </Modal>

      <Modal visible={createOpen} transparent animationType="slide" onRequestClose={() => setCreateOpen(false)}>
        <View style={styles.createModal}>
          <Pressable accessibilityLabel="Close form" onPress={() => setCreateOpen(false)} style={styles.menuBackdrop} />
          <View style={styles.createPanel}>
            <View style={styles.menuHeading}>
              <Text style={styles.menuTitle}>Add {CREATE_TITLES[createTypeForScreen(screen)]}</Text>
              <Pressable accessibilityRole="button" accessibilityLabel="Close form" onPress={() => setCreateOpen(false)} style={styles.menuClose}>
                <Text style={styles.menuCloseText}>×</Text>
              </Pressable>
            </View>
            <ScrollView keyboardShouldPersistTaps="handled">
              {(CREATE_FIELDS[createTypeForScreen(screen)] || []).map(([key, label]) => (
                <View key={key}>
                  <Text style={styles.inputLabel}>{label}</Text>
                  <TextInput
                    value={createValues[key] || ""}
                    onChangeText={(value) => setCreateValues((current) => ({ ...current, [key]: value }))}
                    placeholder={label}
                    placeholderTextColor={colors.muted}
                    autoCapitalize={["email", "login_username"].includes(key) ? "none" : "words"}
                    autoCorrect={key !== "login_username"}
                    secureTextEntry={key === "login_password"}
                    keyboardType={key === "capacity" ? "numeric" : key === "email" ? "email-address" : "default"}
                    style={styles.input}
                  />
                </View>
              ))}
              {createTypeForScreen(screen) === "loads" ? <Text style={styles.mutedText}>The customer must already exist in your account. Add it from Customers first if needed.</Text> : null}
              <PrimaryButton title={savingRecord ? "Saving…" : "Save"} onPress={saveRecord} disabled={savingRecord} />
              <PrimaryButton title="Cancel" tone="green" onPress={() => setCreateOpen(false)} disabled={savingRecord} />
            </ScrollView>
          </View>
        </View>
      </Modal>
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
  topBarActions: { flexDirection: "row", alignItems: "center", gap: 8 },
  menuButton: { width: 42, height: 42, alignItems: "center", justifyContent: "center", borderColor: "#62728a", borderWidth: 1, borderRadius: 9 },
  menuButtonText: { color: colors.white, fontSize: 23, fontWeight: "700" },
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
  infoCard: { backgroundColor: colors.white, borderColor: colors.border, borderWidth: 1, borderRadius: 14, padding: 15, marginBottom: 12 },
  infoTitle: { color: colors.ink, fontSize: 16, fontWeight: "800", marginBottom: 6 },
  infoLine: { color: colors.muted, fontSize: 13, lineHeight: 19, marginTop: 2 },
  driverLoadCard: { backgroundColor: colors.white, borderColor: colors.border, borderWidth: 1, borderRadius: 14, padding: 16, marginTop: 14, marginBottom: 4 },
  driverLoadTitle: { color: colors.ink, fontSize: 20, fontWeight: "800", marginBottom: 4 },
  driverEquipment: { color: colors.muted, fontSize: 12, marginTop: 12 },
  driverTimeline: { borderTopWidth: 1, borderTopColor: colors.border, marginTop: 15, paddingTop: 11, gap: 5 },
  driverTimelineText: { color: colors.muted, fontSize: 12, lineHeight: 17 },
  loadCardHeader: { minHeight: 48, justifyContent: "center" },
  cardPressed: { opacity: 0.72 },
  expandHint: { color: colors.blue, fontSize: 12, fontWeight: "700", marginTop: 9 },
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
  dutyCard: { backgroundColor: colors.white, borderRadius: 16, borderColor: colors.border, borderWidth: 1, padding: 16, marginTop: 16, marginBottom: 18 },
  dutyCurrent: { color: colors.ink, fontSize: 16, fontWeight: "800", marginTop: 7 },
  dutyTotals: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 12 },
  dutyTotal: { minWidth: "46%", flexGrow: 1, backgroundColor: colors.background, borderRadius: 10, padding: 10 },
  dutyLabel: { color: colors.muted, fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
  dutyValue: { color: colors.ink, fontSize: 17, fontWeight: "800", marginTop: 3 },
  dutyPrompt: { color: colors.ink, fontSize: 13, fontWeight: "700", marginTop: 14 },
  locationNotice: { color: colors.muted, fontSize: 11, lineHeight: 16, marginTop: 5 },
  dutyActions: { gap: 8, marginTop: 9 },
  dutyAction: { minHeight: 44, justifyContent: "center", paddingHorizontal: 12, borderRadius: 10, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.white },
  dutyActionActive: { backgroundColor: colors.blue, borderColor: colors.blue },
  dutyActionText: { color: colors.ink, fontWeight: "700", textAlign: "center" },
  dutyActionTextActive: { color: colors.white },
  dutyTimeline: { marginTop: 14, paddingTop: 12, borderTopWidth: 1, borderTopColor: colors.border },
  dutyTimelineTitle: { color: colors.muted, fontSize: 10, fontWeight: "800", letterSpacing: 0.8, marginBottom: 7 },
  dutyTimelineText: { color: colors.ink, fontSize: 12, lineHeight: 20 },
  dutyEmpty: { color: colors.muted, fontSize: 12, marginTop: 12 },
  dutyNote: { color: colors.muted, fontSize: 10, lineHeight: 15, marginTop: 12 },
  loader: { marginVertical: 24 },
  footerNote: { color: colors.muted, fontSize: 11, textAlign: "center", marginTop: 20 },
  tabBar: { backgroundColor: colors.white, borderTopColor: colors.border, borderTopWidth: 1, flexDirection: "row", paddingTop: 8, paddingBottom: 6 },
  tabButton: { flex: 1, alignItems: "center", paddingVertical: 4 },
  tabIcon: { color: colors.muted, fontSize: 22 },
  tabLabel: { color: colors.muted, fontSize: 11, fontWeight: "700", marginTop: 1 },
  tabActive: { color: colors.blue },
  menuModal: { flex: 1, justifyContent: "flex-end" },
  createModal: { flex: 1, justifyContent: "center", padding: 18 },
  createPanel: { maxHeight: "88%", backgroundColor: colors.white, borderRadius: 20, paddingHorizontal: 18, paddingTop: 12, paddingBottom: 22 },
  menuBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(8, 20, 38, 0.5)" },
  menuPanel: { maxHeight: "82%", backgroundColor: colors.white, borderTopLeftRadius: 20, borderTopRightRadius: 20, paddingHorizontal: 18, paddingTop: 12, paddingBottom: 24 },
  menuHeading: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: colors.border },
  menuTitle: { color: colors.ink, fontSize: 19, fontWeight: "800" },
  menuClose: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  menuCloseText: { color: colors.muted, fontSize: 30, lineHeight: 34 },
  menuItem: { minHeight: 52, flexDirection: "row", alignItems: "center", borderBottomWidth: 1, borderBottomColor: colors.border, paddingHorizontal: 6 },
  menuItemPressed: { backgroundColor: colors.background },
  menuItemIcon: { width: 36, fontSize: 19 },
  menuItemLabel: { flex: 1, color: colors.ink, fontSize: 15, fontWeight: "700" },
  menuItemArrow: { color: colors.muted, fontSize: 25 },
});
