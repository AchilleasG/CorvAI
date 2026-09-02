import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Linking,
  Modal,
  Platform,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";

import {
  cancelCodingDeviceAuth,
  closeCodingTerminal,
  createCodingSession,
  createFeatureDelegation,
  fetchCodingDeviceAuth,
  fetchCodingSession,
  fetchCodingSessionLogs,
  fetchCodingSessions,
  fetchCodingStatus,
  fetchCodingTerminal,
  fetchFeatureDelegation,
  fetchFeatureDelegations,
  fetchSshMachines,
  resumeFeatureDelegation,
  sendCodingTerminalInput,
  startCodingDeviceAuth,
  startCodingTask,
  startCodingTerminal,
  stopCodingSession,
  resumeCodingSession,
  stopFeatureDelegation,
  uploadFile,
} from "./api";
import type {
  CodingCliStatus,
  CodingDeviceAuth,
  CodingLiveLogs,
  CodingSession,
  CodingTerminal,
  FeatureDelegation,
  SshMachine,
} from "./types";

const c = {
  bg: "#09111f",
  card: "#101a2b",
  card2: "#0b1525",
  border: "#223149",
  text: "#edf4ff",
  muted: "#8fa1b8",
  green: "#2ad1a3",
  blue: "#60a5fa",
  red: "#fb7185",
  amber: "#f7c266",
  purple: "#a78bfa",
};
const ACTIVE = new Set(["queued", "coding", "qa", "fixing"]);
function errorText(e: unknown) {
  if (!(e instanceof Error)) return "Something went wrong";
  try {
    const v = JSON.parse(e.message);
    return v.detail || v.message || e.message;
  } catch {
    return e.message;
  }
}
function statusColor(status: string) {
  return status === "completed" || status === "ready"
    ? c.green
    : status === "needs_input"
      ? c.amber
      : status === "failed"
        ? c.red
        : status === "qa"
          ? c.purple
          : status === "running" ||
              status === "coding" ||
              status === "fixing" ||
              status === "queued"
            ? c.blue
            : c.muted;
}

export default function CodingScreen({
  requestedSessionId,
  requestedDelegationId,
  onRequestHandled,
}: {
  requestedSessionId?: string | null;
  requestedDelegationId?: string | null;
  onRequestHandled?: () => void;
}) {
  const [cli, setCli] = useState<CodingCliStatus | null>(null);
  const [auth, setAuth] = useState<CodingDeviceAuth | null>(null);
  const [machines, setMachines] = useState<SshMachine[]>([]);
  const [sessions, setSessions] = useState<CodingSession[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(
    requestedSessionId || null,
  );
  const [selected, setSelected] = useState<CodingSession | null>(null);
  const [delegations, setDelegations] = useState<FeatureDelegation[]>([]);
  const [selectedDelegation, setSelectedDelegation] =
    useState<FeatureDelegation | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [newSession, setNewSession] = useState(false);
  const [sessionName, setSessionName] = useState("");
  const [machineId, setMachineId] = useState("");
  const [remoteDir, setRemoteDir] = useState("~");
  const [task, setTask] = useState("");
  const [taskFiles, setTaskFiles] = useState<
    DocumentPicker.DocumentPickerAsset[]
  >([]);
  const [featureOpen, setFeatureOpen] = useState(false);
  const [featureTitle, setFeatureTitle] = useState("");
  const [featureDescription, setFeatureDescription] = useState("");
  const [criteria, setCriteria] = useState("");
  const [featureFiles, setFeatureFiles] = useState<
    DocumentPicker.DocumentPickerAsset[]
  >([]);
  const [qaEnabled, setQaEnabled] = useState(true);
  const [decision, setDecision] = useState("");
  const [logsOpen, setLogsOpen] = useState(false);
  const [logs, setLogs] = useState<CodingLiveLogs | null>(null);
  const [terminal, setTerminal] = useState<CodingTerminal | null>(null);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalInput, setTerminalInput] = useState("");
  const eligibleMachines = useMemo(
    () => machines.filter((item) => item.allow_ai_commands),
    [machines],
  );

  async function refreshSessions(preferred?: string | null) {
    const response = await fetchCodingSessions();
    setSessions(response.sessions);
    setSelectedId((current) => {
      const id = preferred === undefined ? current : preferred;
      return id && response.sessions.some((item) => item.id === id)
        ? id
        : response.sessions[0]?.id || null;
    });
  }
  async function refreshSelected(id = selectedId) {
    if (!id) {
      setSelected(null);
      setDelegations([]);
      return;
    }
    const [session, featureResponse] = await Promise.all([
      fetchCodingSession(id),
      fetchFeatureDelegations(id),
    ]);
    setSelected(session);
    setSessions((items) =>
      items.map((item) => (item.id === session.id ? session : item)),
    );
    setDelegations(featureResponse.delegations);
    const delegationId =
      requestedDelegationId ||
      selectedDelegation?.id ||
      featureResponse.delegations[0]?.id;
    if (delegationId) {
      try {
        setSelectedDelegation(await fetchFeatureDelegation(delegationId));
      } catch {
        setSelectedDelegation(null);
      }
    }
  }

  useEffect(() => {
    Promise.all([
      fetchCodingStatus(),
      fetchCodingDeviceAuth(),
      fetchSshMachines(),
      fetchCodingSessions(),
    ])
      .then(([status, device, ssh, coding]) => {
        setCli(status);
        setAuth(device);
        setMachines(ssh.machines);
        setSessions(coding.sessions);
        const id = requestedSessionId || coding.sessions[0]?.id || null;
        setSelectedId(id);
        setMachineId(
          ssh.machines.find((item) => item.is_default && item.allow_ai_commands)
            ?.id ||
            ssh.machines.find((item) => item.allow_ai_commands)?.id ||
            "",
        );
      })
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    refreshSelected(selectedId).catch((e) => setError(errorText(e)));
  }, [selectedId]);
  useEffect(() => {
    if (!requestedSessionId) return;
    setSelectedId(requestedSessionId);
    onRequestHandled?.();
  }, [requestedSessionId]);
  useEffect(() => {
    if (!auth?.active) return;
    const timer = setInterval(
      () =>
        fetchCodingDeviceAuth().then(async (value) => {
          setAuth(value);
          if (value.status === "succeeded") setCli(await fetchCodingStatus());
        }),
      1000,
    );
    return () => clearInterval(timer);
  }, [auth?.active]);
  useEffect(() => {
    if (!selectedId) return;
    const timer = setInterval(
      () => {
        refreshSelected(selectedId).catch(() => undefined);
        refreshSessions().catch(() => undefined);
      },
      selected?.status === "running" ? 1400 : 3500,
    );
    return () => clearInterval(timer);
  }, [selectedId, selected?.status, selectedDelegation?.id]);
  useEffect(() => {
    if (!logsOpen || !selectedId) return;
    const pull = () =>
      fetchCodingSessionLogs(selectedId)
        .then(setLogs)
        .catch(() => undefined);
    pull();
    const timer = setInterval(pull, 700);
    return () => clearInterval(timer);
  }, [logsOpen, selectedId]);
  useEffect(() => {
    if (!terminalOpen || !selectedId) return;
    const pull = () =>
      fetchCodingTerminal(selectedId)
        .then(setTerminal)
        .catch(() => undefined);
    pull();
    const timer = setInterval(pull, 700);
    return () => clearInterval(timer);
  }, [terminalOpen, selectedId]);

  async function startLogin() {
    setBusy(true);
    try {
      setAuth(await startCodingDeviceAuth());
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function createSession() {
    if (!sessionName.trim() || !machineId) return;
    setBusy(true);
    try {
      const value = await createCodingSession({
        name: sessionName.trim(),
        machine_id: machineId,
        remote_working_directory: remoteDir.trim() || "~",
      });
      setNewSession(false);
      setSessionName("");
      await refreshSessions(value.id);
      setSelectedId(value.id);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function uploadInputs(
    files: DocumentPicker.DocumentPickerAsset[],
    sessionId: string,
  ) {
    return Promise.all(
      files.map(async (file) =>
        uploadFile(await (await fetch(file.uri)).blob(), {
          filename: file.name,
          session_id: sessionId,
          tags: ["coding-input"],
        }),
      ),
    );
  }
  async function pickInputs(setter: typeof setTaskFiles) {
    const result = await DocumentPicker.getDocumentAsync({
      multiple: true,
      copyToCacheDirectory: true,
    });
    if (!result.canceled) setter((items) => [...items, ...result.assets]);
  }
  async function delegateTask() {
    if (!selected || !task.trim()) return;
    setBusy(true);
    try {
      const files = await uploadInputs(taskFiles, selected.id);
      await startCodingTask(
        selected.id,
        task.trim(),
        files.map((file) => file.id),
      );
      setTask("");
      setTaskFiles([]);
      await refreshSelected(selected.id);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function delegateFeature() {
    if (!selected) return;
    const list = criteria
      .split("\n")
      .map((x) => x.replace(/^\s*[-*\d.)]+\s*/, "").trim())
      .filter(Boolean);
    if (!featureTitle.trim() || !featureDescription.trim() || !list.length) {
      setError(
        "Feature name, description, and acceptance criteria are required.",
      );
      return;
    }
    setBusy(true);
    try {
      const files = await uploadInputs(featureFiles, selected.id);
      const item = await createFeatureDelegation(selected.id, {
        title: featureTitle.trim(),
        description: featureDescription.trim(),
        acceptance_criteria: list,
        qa_enabled: qaEnabled,
        max_iterations: 6,
        file_ids: files.map((file) => file.id),
      });
      setFeatureOpen(false);
      setFeatureTitle("");
      setFeatureDescription("");
      setCriteria("");
      setFeatureFiles([]);
      setSelectedDelegation(item);
      await refreshSelected(selected.id);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function resumeFeature(
    value?: string,
    mode: "auto" | "qa" | "coding" = "auto",
  ) {
    if (!selectedDelegation) return;
    setBusy(true);
    try {
      const item = await resumeFeatureDelegation(
        selectedDelegation.id,
        (value ?? decision).trim(),
        mode,
      );
      setDecision("");
      setSelectedDelegation(item);
      await refreshSelected(item.session_id);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function stopFeature() {
    if (!selectedDelegation) return;
    setSelectedDelegation(await stopFeatureDelegation(selectedDelegation.id));
    if (selected) await refreshSelected(selected.id);
  }
  async function openTerminal() {
    if (!selected) return;
    setBusy(true);
    try {
      setTerminal(await startCodingTerminal(selected.id));
      setTerminalOpen(true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function sendTerminal() {
    if (!selected || !terminalInput) return;
    setTerminal(
      await sendCodingTerminalInput(selected.id, {
        text: terminalInput,
        key: "Enter",
      }),
    );
    setTerminalInput("");
  }

  if (loading)
    return (
      <View style={s.center}>
        <ActivityIndicator color={c.green} />
      </View>
    );
  return (
    <View style={s.screen}>
      <View style={s.hero}>
        <View>
          <Text style={s.eyebrow}>REMOTE DEVELOPMENT</Text>
          <Text style={s.title}>Coding</Text>
          <Text style={s.subtitle}>
            Persistent Codex sessions with autonomous QA.
          </Text>
        </View>
        <TouchableOpacity
          style={s.primaryIcon}
          onPress={() => setNewSession(true)}
          disabled={!cli?.authenticated}
        >
          <Ionicons name="add" size={22} color="#041316" />
        </TouchableOpacity>
      </View>
      {error ? <Text style={s.error}>{error}</Text> : null}
      {cli?.authenticated && cli.auth_mode === "profile" && cli.usage ? (
        <View style={s.usageCard}>
          <View style={s.cardHead}>
            <View>
              <Text style={s.eyebrow}>CHATGPT PROFILE</Text>
              <Text style={s.cardTitle}>Codex usage</Text>
            </View>
            {cli.usage.plan_type ? (
              <Text style={s.usagePlan}>{cli.usage.plan_type}</Text>
            ) : null}
          </View>
          {cli.usage.available ? (
            <View style={s.usageRows}>
              {[cli.usage.primary, cli.usage.secondary]
                .filter(Boolean)
                .map((window, index) =>
                  window ? (
                    <View
                      key={`${window.window_minutes || "window"}-${index}`}
                      style={s.usageRow}
                    >
                      <Text style={s.muted}>
                        {window.window_minutes && window.window_minutes < 1440
                          ? `${Math.round(window.window_minutes / 60)} hour limit`
                          : `${Math.round((window.window_minutes || 10080) / 1440)} day limit`}
                      </Text>
                      <Text style={s.usageAvailable}>
                        {window.remaining_percent}% available
                      </Text>
                    </View>
                  ) : null,
                )}
            </View>
          ) : (
            <Text style={s.muted}>
              {cli.usage.reason || "Profile usage is temporarily unavailable."}
            </Text>
          )}
        </View>
      ) : null}
      {!cli?.authenticated && cli?.auth_mode === "api_key" ? (
        <View style={s.authCard}>
          <View style={s.authIcon}>
            <Ionicons name="key-outline" size={23} color={c.green} />
          </View>
          <View style={s.authCopy}>
            <Text style={s.cardTitle}>API key needed</Text>
            <Text style={s.muted}>
              Add an OpenAI API key or switch to your ChatGPT profile in
              Settings.
            </Text>
          </View>
        </View>
      ) : null}
      {!cli?.authenticated && cli?.auth_mode !== "api_key" ? (
        <View style={s.authCard}>
          <View style={s.authIcon}>
            <Ionicons name="key-outline" size={23} color={c.green} />
          </View>
          <View style={s.authCopy}>
            <Text style={s.cardTitle}>Sign in to Codex</Text>
            <Text style={s.muted}>
              Use OpenAI’s device flow once; the session stays stored in Corv.
            </Text>
            {auth?.user_code ? (
              <TouchableOpacity
                style={s.codeBox}
                onPress={() =>
                  auth.verification_url &&
                  Linking.openURL(auth.verification_url)
                }
              >
                <Text style={s.code}>{auth.user_code}</Text>
                <Text style={s.codeLink}>Open sign-in</Text>
              </TouchableOpacity>
            ) : null}
          </View>
          <TouchableOpacity
            style={s.compactPrimary}
            onPress={
              auth?.active
                ? () => cancelCodingDeviceAuth().then(setAuth)
                : startLogin
            }
          >
            <Text style={s.primaryText}>
              {auth?.active ? "Cancel" : "Sign in"}
            </Text>
          </TouchableOpacity>
        </View>
      ) : null}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={s.sessionTabs}
      >
        {sessions.map((item) => (
          <TouchableOpacity
            key={item.id}
            style={[s.sessionTab, selectedId === item.id && s.sessionTabActive]}
            onPress={() => setSelectedId(item.id)}
          >
            <View
              style={[s.dot, { backgroundColor: statusColor(item.status) }]}
            />
            <View>
              <Text style={s.sessionName}>{item.name}</Text>
              <Text style={s.small}>
                {item.machine_name} · {item.status.replace("_", " ")}
              </Text>
            </View>
          </TouchableOpacity>
        ))}
      </ScrollView>
      {!sessions.length ? (
        <View style={s.empty}>
          <Ionicons name="code-slash-outline" size={34} color={c.muted} />
          <Text style={s.cardTitle}>No coding sessions</Text>
          <Text style={s.muted}>
            Create one on an SSH machine with Corv command access enabled.
          </Text>
        </View>
      ) : null}
      {selected ? (
        <ScrollView
          contentContainerStyle={s.content}
          keyboardShouldPersistTaps="handled"
        >
          <View style={s.card}>
            <View style={s.cardHead}>
              <View style={s.flex}>
                <Text style={s.cardTitle}>{selected.name}</Text>
                <Text style={s.muted}>{selected.machine_target}</Text>
              </View>
              <View
                style={[s.badge, { borderColor: statusColor(selected.status) }]}
              >
                <Text
                  style={[s.badgeText, { color: statusColor(selected.status) }]}
                >
                  {selected.status.replace("_", " ")}
                </Text>
              </View>
            </View>
            <Text style={s.path}>{selected.remote_working_directory}</Text>
            <View style={s.actionRow}>
              <TouchableOpacity
                style={s.secondary}
                onPress={() => setLogsOpen(true)}
              >
                <Ionicons name="pulse-outline" size={16} color={c.text} />
                <Text style={s.secondaryText}>Live logs</Text>
              </TouchableOpacity>
              {selected.status === "stopped" ? (
                <TouchableOpacity
                  style={s.resumeButton}
                  onPress={() =>
                    resumeCodingSession(selected.id)
                      .then(() => refreshSelected(selected.id))
                      .catch((e) => setError(errorText(e)))
                  }
                >
                  <Ionicons name="play" size={15} color="#041316" />
                  <Text style={s.primaryText}>Resume</Text>
                </TouchableOpacity>
              ) : (
                <>
                  <TouchableOpacity
                    style={s.secondary}
                    onPress={openTerminal}
                    disabled={selected.status === "running"}
                  >
                    <Ionicons
                      name="terminal-outline"
                      size={16}
                      color={c.text}
                    />
                    <Text style={s.secondaryText}>Codex CLI</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={s.stop}
                    onPress={() =>
                      Alert.alert("Stop session?", selected.name, [
                        { text: "Cancel" },
                        {
                          text: "Stop",
                          style: "destructive",
                          onPress: () =>
                            stopCodingSession(selected.id).then(() =>
                              refreshSelected(selected.id),
                            ),
                        },
                      ])
                    }
                  >
                    <Text style={s.stopText}>Stop</Text>
                  </TouchableOpacity>
                </>
              )}
            </View>
          </View>
          <View style={s.card}>
            <Text style={s.kicker}>QUICK TASK</Text>
            <Text style={s.cardTitle}>Delegate a focused change</Text>
            <TextInput
              style={[s.input, s.textarea]}
              multiline
              value={task}
              onChangeText={setTask}
              placeholder="Describe a small coding task…"
              placeholderTextColor={c.muted}
            />
            <TouchableOpacity
              style={s.secondary}
              onPress={() => pickInputs(setTaskFiles)}
            >
              <Ionicons name="attach" size={16} color={c.text} />
              <Text style={s.secondaryText}>
                Attach files{taskFiles.length ? ` (${taskFiles.length})` : ""}
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[
                s.primary,
                (!task.trim() || busy || selected.status === "running") &&
                  s.disabled,
              ]}
              onPress={delegateTask}
              disabled={!task.trim() || busy || selected.status === "running"}
            >
              <Text style={s.primaryText}>Delegate task</Text>
            </TouchableOpacity>
          </View>
          <View style={s.card}>
            <View style={s.cardHead}>
              <View>
                <Text style={s.kicker}>AUTONOMOUS DELIVERY</Text>
                <Text style={s.cardTitle}>Feature delegations</Text>
              </View>
              <TouchableOpacity
                style={s.compactPrimary}
                onPress={() => setFeatureOpen(true)}
                disabled={selected.status === "running"}
              >
                <Text style={s.primaryText}>New feature</Text>
              </TouchableOpacity>
            </View>
            <Text style={s.muted}>
              Coder → independent QA → automatic fixes, until it passes or needs
              you.
            </Text>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={s.featureTabs}
            >
              {delegations.map((item) => (
                <TouchableOpacity
                  key={item.id}
                  style={[
                    s.featureTab,
                    selectedDelegation?.id === item.id && s.featureTabActive,
                  ]}
                  onPress={() =>
                    fetchFeatureDelegation(item.id).then(setSelectedDelegation)
                  }
                >
                  <Text numberOfLines={1} style={s.featureName}>
                    {item.title}
                  </Text>
                  <Text style={[s.small, { color: statusColor(item.status) }]}>
                    {item.status.replace("_", " ")} · {item.current_iteration}/
                    {item.max_iterations}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            {selectedDelegation ? (
              <View style={s.featureDetail}>
                <View style={s.cardHead}>
                  <Text style={s.featureHeading}>
                    {selectedDelegation.title}
                  </Text>
                  <Text
                    style={[s.qaBadge, selectedDelegation.qa_enabled && s.qaOn]}
                  >
                    {selectedDelegation.qa_enabled ? "QA ON" : "QA OFF"}
                  </Text>
                </View>
                <Text style={s.body}>{selectedDelegation.description}</Text>
                {selectedDelegation.acceptance_criteria.map((item, index) => (
                  <View style={s.criterion} key={`${index}-${item}`}>
                    <Text style={s.criterionNumber}>{index + 1}</Text>
                    <Text style={s.criterionText}>{item}</Text>
                  </View>
                ))}
                {selectedDelegation.implementation_summary ? (
                  <View style={s.report}>
                    <Text style={s.reportLabel}>CODER REPORT</Text>
                    <Text style={s.body}>
                      {selectedDelegation.implementation_summary}
                    </Text>
                  </View>
                ) : null}
                {selectedDelegation.qa_summary ? (
                  <View style={[s.report, s.qaReport]}>
                    <Text style={s.reportLabel}>QA REPORT</Text>
                    <Text style={s.body}>{selectedDelegation.qa_summary}</Text>
                  </View>
                ) : null}
                {selectedDelegation.status === "needs_input" ||
                selectedDelegation.status === "stopped" ? (
                  <View style={s.decision}>
                    <Text style={s.decisionTitle}>
                      {selectedDelegation.status === "stopped"
                        ? "Delegation stopped"
                        : "Your decision is needed"}
                    </Text>
                    <Text style={s.body}>
                      {selectedDelegation.pending_question ||
                        "Continue from the saved coder and QA threads."}
                    </Text>
                    {selectedDelegation.can_retry_qa ? (
                      <View style={s.optionWrap}>
                        <TouchableOpacity
                          style={s.compactPrimary}
                          onPress={() => resumeFeature(undefined, "qa")}
                        >
                          <Text style={s.primaryText}>Retry QA only</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                          style={s.option}
                          onPress={() =>
                            resumeFeature(
                              decision ||
                                "Review the QA blocker and make any required application changes.",
                              "coding",
                            )
                          }
                        >
                          <Text style={s.optionText}>Return to coder</Text>
                        </TouchableOpacity>
                      </View>
                    ) : null}
                    <View style={s.optionWrap}>
                      {selectedDelegation.pending_options.map((option) => (
                        <TouchableOpacity
                          style={s.option}
                          key={option}
                          onPress={() => resumeFeature(option)}
                        >
                          <Text style={s.optionText}>{option}</Text>
                        </TouchableOpacity>
                      ))}
                    </View>
                    <TextInput
                      style={s.input}
                      value={decision}
                      onChangeText={setDecision}
                      placeholder={
                        selectedDelegation.can_retry_qa
                          ? "Optional QA retry instruction…"
                          : "Optional continuation instruction…"
                      }
                      placeholderTextColor={c.muted}
                    />
                    <TouchableOpacity
                      style={s.primary}
                      onPress={() => resumeFeature()}
                    >
                      <Text style={s.primaryText}>
                        {selectedDelegation.can_retry_qa
                          ? "Retry QA"
                          : "Resume delegation"}
                      </Text>
                    </TouchableOpacity>
                  </View>
                ) : null}
                {ACTIVE.has(selectedDelegation.status) ? (
                  <TouchableOpacity onPress={stopFeature}>
                    <Text style={s.stopFeature}>Stop delegation</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
            ) : null}
          </View>
          <View style={s.card}>
            <Text style={s.cardTitle}>Recent managed turns</Text>
            {selected.turns.slice(0, 8).map((turn) => (
              <View style={s.turn} key={turn.id}>
                <View
                  style={[
                    s.turnRail,
                    { backgroundColor: statusColor(turn.status) },
                  ]}
                />
                <View style={s.flex}>
                  <Text style={s.turnTitle}>
                    {turn.source === "feature"
                      ? "Feature cycle"
                      : turn.source === "decision"
                        ? "Decision"
                        : "Delegated task"}
                  </Text>
                  <Text numberOfLines={2} style={s.small}>
                    {turn.summary || turn.prompt}
                  </Text>
                </View>
                <Text style={[s.small, { color: statusColor(turn.status) }]}>
                  {turn.status.replace("_", " ")}
                </Text>
              </View>
            ))}
          </View>
        </ScrollView>
      ) : null}

      <Modal
        visible={newSession}
        transparent
        animationType="slide"
        onRequestClose={() => setNewSession(false)}
      >
        <View style={s.modalBackdrop}>
          <View style={s.modal}>
            <ModalHead
              title="New coding session"
              close={() => setNewSession(false)}
            />
            <TextInput
              style={s.input}
              value={sessionName}
              onChangeText={setSessionName}
              placeholder="Session name"
              placeholderTextColor={c.muted}
            />
            <TextInput
              style={s.input}
              value={remoteDir}
              onChangeText={setRemoteDir}
              placeholder="Remote project directory"
              placeholderTextColor={c.muted}
              autoCapitalize="none"
            />
            <Text style={s.label}>SSH machine</Text>
            <ScrollView horizontal contentContainerStyle={s.optionWrap}>
              {eligibleMachines.map((item) => (
                <TouchableOpacity
                  key={item.id}
                  style={[s.option, machineId === item.id && s.optionActive]}
                  onPress={() => setMachineId(item.id)}
                >
                  <Text style={s.optionText}>{item.name}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <View style={s.fullAccess}>
              <Ionicons name="warning-outline" color={c.amber} size={18} />
              <Text style={s.fullAccessText}>
                Codex runs with full access on the selected machine.
              </Text>
            </View>
            <TouchableOpacity style={s.primary} onPress={createSession}>
              <Text style={s.primaryText}>Create session</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
      <Modal
        visible={featureOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setFeatureOpen(false)}
      >
        <View style={s.modalBackdrop}>
          <View style={s.modal}>
            <ModalHead
              title="Delegate feature"
              close={() => setFeatureOpen(false)}
            />
            <ScrollView keyboardShouldPersistTaps="handled">
              <TextInput
                style={s.input}
                value={featureTitle}
                onChangeText={setFeatureTitle}
                placeholder="Feature name"
                placeholderTextColor={c.muted}
              />
              <TextInput
                style={[s.input, s.textarea]}
                multiline
                value={featureDescription}
                onChangeText={setFeatureDescription}
                placeholder="Describe the feature and constraints…"
                placeholderTextColor={c.muted}
              />
              <TextInput
                style={[s.input, s.criteriaInput]}
                multiline
                value={criteria}
                onChangeText={setCriteria}
                placeholder={
                  "Acceptance criteria · one per line\nThe complete flow works\nErrors are handled clearly"
                }
                placeholderTextColor={c.muted}
              />
              <TouchableOpacity
                style={s.secondary}
                onPress={() => pickInputs(setFeatureFiles)}
              >
                <Ionicons name="attach" size={16} color={c.text} />
                <Text style={s.secondaryText}>
                  Attach files{featureFiles.length ? ` (${featureFiles.length})` : ""}
                </Text>
              </TouchableOpacity>
              <View style={s.qaToggle}>
                <View style={s.flex}>
                  <Text style={s.labelNoMargin}>Independent QA bot</Text>
                  <Text style={s.small}>
                    Tests the actual result and automatically sends failures
                    back.
                  </Text>
                </View>
                <Switch
                  value={qaEnabled}
                  onValueChange={setQaEnabled}
                  trackColor={{ false: c.border, true: "#16795f" }}
                  thumbColor={qaEnabled ? c.green : "#94a3b8"}
                />
              </View>
              <TouchableOpacity style={s.primary} onPress={delegateFeature}>
                <Text style={s.primaryText}>Start delegation</Text>
              </TouchableOpacity>
            </ScrollView>
          </View>
        </View>
      </Modal>
      <Modal
        visible={logsOpen}
        animationType="slide"
        onRequestClose={() => setLogsOpen(false)}
      >
        <View style={s.fullModal}>
          <ModalHead
            title="Live session logs"
            close={() => setLogsOpen(false)}
          />
          <View style={s.liveState}>
            <View style={[s.dot, logs?.active && s.dotLive]} />
            <Text style={s.muted}>
              {logs?.active ? "Receiving output" : "Session idle"}
            </Text>
          </View>
          <ScrollView style={s.logBox} contentContainerStyle={s.logContent}>
            <Text selectable style={s.logText}>
              {logs?.content || "Waiting for output…"}
            </Text>
          </ScrollView>
        </View>
      </Modal>
      <Modal
        visible={terminalOpen}
        animationType="slide"
        onRequestClose={() => setTerminalOpen(false)}
      >
        <View style={s.fullModal}>
          <ModalHead
            title="Direct Codex CLI"
            close={async () => {
              if (selected) await closeCodingTerminal(selected.id);
              setTerminalOpen(false);
            }}
          />
          <ScrollView style={s.logBox} contentContainerStyle={s.logContent}>
            <Text selectable style={s.logText}>
              {terminal?.output || "Codex is starting…"}
            </Text>
          </ScrollView>
          <View style={s.terminalInputRow}>
            <TextInput
              style={[s.input, s.flex]}
              value={terminalInput}
              onChangeText={setTerminalInput}
              placeholder="Type into Codex…"
              placeholderTextColor={c.muted}
              onSubmitEditing={sendTerminal}
            />
            <TouchableOpacity style={s.send} onPress={sendTerminal}>
              <Ionicons name="arrow-up" size={18} color="#041316" />
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function ModalHead({ title, close }: { title: string; close: () => void }) {
  return (
    <View style={s.cardHead}>
      <Text style={s.title}>{title}</Text>
      <TouchableOpacity onPress={close}>
        <Ionicons name="close" size={25} color={c.text} />
      </TouchableOpacity>
    </View>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: c.bg },
  center: {
    flex: 1,
    backgroundColor: c.bg,
    alignItems: "center",
    justifyContent: "center",
  },
  hero: {
    padding: 18,
    paddingBottom: 12,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  eyebrow: {
    color: c.green,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1.5,
  },
  title: { color: c.text, fontSize: 24, fontWeight: "800", marginTop: 3 },
  subtitle: { color: c.muted, fontSize: 13, marginTop: 4 },
  primaryIcon: {
    width: 42,
    height: 42,
    borderRadius: 14,
    backgroundColor: c.green,
    alignItems: "center",
    justifyContent: "center",
  },
  error: {
    color: "#fecdd3",
    backgroundColor: "#3b1823",
    marginHorizontal: 18,
    marginBottom: 10,
    padding: 10,
    borderRadius: 10,
  },
  usageCard: {
    marginHorizontal: 18,
    marginBottom: 10,
    padding: 14,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#29496f",
    backgroundColor: "#102038",
  },
  usagePlan: {
    color: c.blue,
    fontSize: 11,
    fontWeight: "700",
    textTransform: "capitalize",
  },
  usageRows: { marginTop: 9, gap: 7 },
  usageRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  usageAvailable: { color: c.green, fontSize: 12, fontWeight: "700" },
  authCard: {
    marginHorizontal: 18,
    marginBottom: 10,
    padding: 14,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#1d5e50",
    backgroundColor: "#102338",
    flexDirection: "row",
    alignItems: "center",
    gap: 11,
  },
  authIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: "#113d34",
    alignItems: "center",
    justifyContent: "center",
  },
  authCopy: { flex: 1 },
  codeBox: { marginTop: 8, flexDirection: "row", alignItems: "center", gap: 9 },
  code: {
    color: "#b9f8e5",
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace" }),
    fontWeight: "800",
    letterSpacing: 1,
  },
  codeLink: { color: c.blue, fontSize: 12 },
  sessionTabs: { paddingHorizontal: 18, paddingBottom: 12, gap: 9 },
  sessionTab: {
    minWidth: 190,
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.card,
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
  },
  sessionTabActive: { borderColor: c.green, backgroundColor: "#10273a" },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: c.muted },
  dotLive: { backgroundColor: c.green },
  sessionName: { color: c.text, fontWeight: "700" },
  small: { color: c.muted, fontSize: 11, marginTop: 2 },
  content: { padding: 18, paddingTop: 3, paddingBottom: 45, gap: 12 },
  card: {
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 18,
    padding: 15,
  },
  cardHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
  },
  flex: { flex: 1 },
  cardTitle: { color: c.text, fontSize: 16, fontWeight: "700" },
  muted: { color: c.muted, fontSize: 12, marginTop: 3 },
  badge: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 9,
    paddingVertical: 5,
  },
  badgeText: { fontSize: 10, fontWeight: "700", textTransform: "capitalize" },
  path: {
    marginTop: 13,
    padding: 10,
    borderRadius: 10,
    backgroundColor: c.card2,
    color: "#bdd3eb",
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace" }),
    fontSize: 11,
  },
  actionRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 12 },
  secondary: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 11,
    paddingVertical: 9,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 10,
  },
  secondaryText: { color: c.text, fontSize: 12, fontWeight: "600" },
  resumeButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderRadius: 10,
    backgroundColor: c.green,
  },
  stop: { padding: 10 },
  stopText: { color: c.red, fontSize: 12, fontWeight: "600" },
  kicker: {
    color: c.green,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 1.3,
    marginBottom: 4,
  },
  input: {
    backgroundColor: c.card2,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 11,
    color: c.text,
    marginTop: 10,
  },
  textarea: { minHeight: 92, textAlignVertical: "top" },
  criteriaInput: { minHeight: 120, textAlignVertical: "top" },
  primary: {
    backgroundColor: c.green,
    borderRadius: 12,
    padding: 12,
    alignItems: "center",
    marginTop: 11,
  },
  compactPrimary: {
    backgroundColor: c.green,
    borderRadius: 10,
    paddingHorizontal: 11,
    paddingVertical: 9,
  },
  primaryText: { color: "#041316", fontWeight: "800", fontSize: 12 },
  disabled: { opacity: 0.45 },
  featureTabs: { gap: 7, paddingTop: 12, paddingBottom: 7 },
  featureTab: {
    width: 155,
    padding: 10,
    borderRadius: 11,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.card2,
  },
  featureTabActive: { borderColor: c.purple, backgroundColor: "#1c1d3d" },
  featureName: { color: c.text, fontWeight: "600", fontSize: 12 },
  featureDetail: {
    borderTopWidth: 1,
    borderTopColor: c.border,
    marginTop: 8,
    paddingTop: 12,
    gap: 8,
  },
  featureHeading: { color: c.text, fontWeight: "700", fontSize: 15, flex: 1 },
  qaBadge: {
    fontSize: 9,
    color: c.muted,
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 999,
    paddingHorizontal: 7,
    paddingVertical: 4,
  },
  qaOn: { color: "#b9f8e5", borderColor: c.green },
  body: { color: "#cbd5e1", fontSize: 12, lineHeight: 18 },
  criterion: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  criterionNumber: {
    width: 20,
    height: 20,
    borderRadius: 10,
    textAlign: "center",
    textAlignVertical: "center",
    backgroundColor: "#14392f",
    color: c.green,
    fontSize: 10,
    fontWeight: "800",
  },
  criterionText: { flex: 1, color: "#d8e2ef", fontSize: 12, lineHeight: 18 },
  report: {
    padding: 11,
    borderRadius: 11,
    borderLeftWidth: 3,
    borderLeftColor: c.blue,
    backgroundColor: c.card2,
  },
  qaReport: { borderLeftColor: c.purple },
  reportLabel: {
    color: c.muted,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 1,
    marginBottom: 5,
  },
  decision: {
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#785b23",
    backgroundColor: "#302515",
  },
  decisionTitle: { color: c.amber, fontWeight: "700", marginBottom: 5 },
  optionWrap: { flexDirection: "row", flexWrap: "wrap", gap: 7, marginTop: 9 },
  option: {
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 9,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  optionActive: { borderColor: c.green, backgroundColor: "#14392f" },
  optionText: { color: c.text, fontSize: 11, fontWeight: "600" },
  stopFeature: { color: c.red, fontSize: 12, fontWeight: "600", marginTop: 4 },
  turn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  turnRail: { width: 3, height: 34, borderRadius: 3 },
  turnTitle: { color: c.text, fontSize: 12, fontWeight: "600" },
  empty: {
    margin: 18,
    padding: 28,
    alignItems: "center",
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: 18,
    backgroundColor: c.card,
    gap: 7,
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: "rgba(2,6,15,.8)",
    justifyContent: "flex-end",
  },
  modal: {
    maxHeight: "90%",
    backgroundColor: c.card,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: 20,
    paddingBottom: 34,
    borderWidth: 1,
    borderColor: c.border,
  },
  label: { color: c.text, fontSize: 12, fontWeight: "600", marginTop: 13 },
  labelNoMargin: { color: c.text, fontSize: 12, fontWeight: "600" },
  fullAccess: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 13,
    padding: 10,
    borderRadius: 10,
    backgroundColor: "#302515",
  },
  fullAccessText: { color: "#f8dda1", fontSize: 11, flex: 1 },
  qaToggle: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#1d5e50",
    marginTop: 11,
  },
  fullModal: {
    flex: 1,
    backgroundColor: c.bg,
    paddingTop: Platform.OS === "ios" ? 55 : 24,
    paddingHorizontal: 16,
    paddingBottom: 18,
  },
  liveState: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginVertical: 12,
  },
  logBox: {
    flex: 1,
    backgroundColor: "#030712",
    borderRadius: 14,
    borderWidth: 1,
    borderColor: c.border,
  },
  logContent: { padding: 13 },
  logText: {
    color: "#c7f9e8",
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace" }),
    fontSize: 11,
    lineHeight: 17,
  },
  terminalInputRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  send: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: c.green,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 10,
  },
});
