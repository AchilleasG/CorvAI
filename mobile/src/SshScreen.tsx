import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Alert, Modal, Platform, ScrollView, StyleSheet, Switch, Text, TextInput, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import {
  closeSshTerminalSession,
  connectSshMachine,
  createSshMachine,
  createSshTerminalSession,
  deleteSshMachine,
  disconnectSshMachine,
  fetchSshMachines,
  fetchSshTerminalSessions,
  runSshTerminalCommand,
  updateSshMachine,
} from "./api";
import type { SshMachine, SshTerminalSession } from "./types";

const colors = { bg: "#09111f", card: "#101a2b", card2: "#0b1525", border: "#223149", text: "#edf4ff", muted: "#8fa1b8", green: "#2ad1a3", blue: "#60a5fa", red: "#fb7185", amber: "#f7c266" };

function errText(error: unknown) {
  if (!(error instanceof Error)) return "Something went wrong";
  try { const value = JSON.parse(error.message); return value.detail || value.message || error.message; } catch { return error.message; }
}

export default function SshScreen() {
  const [machines, setMachines] = useState<SshMachine[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SshTerminalSession[]>([]);
  const [terminalId, setTerminalId] = useState<string | null>(null);
  const [command, setCommand] = useState("");
  const [output, setOutput] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("22");
  const [username, setUsername] = useState("");
  const [authType, setAuthType] = useState<"password" | "private_key" | "agent">("private_key");
  const [secret, setSecret] = useState("");
  const selected = useMemo(() => machines.find((item) => item.id === selectedId) || null, [machines, selectedId]);

  async function refresh(preferred?: string) {
    const response = await fetchSshMachines();
    setMachines(response.machines);
    setSelectedId((current) => preferred || (current && response.machines.some((item) => item.id === current) ? current : response.machines[0]?.id || null));
  }

  async function refreshSessions(machineId: string) {
    const response = await fetchSshTerminalSessions(machineId);
    setSessions(response.sessions);
    setTerminalId((current) => current && response.sessions.some((item) => item.id === current) ? current : response.sessions[0]?.id || null);
  }

  useEffect(() => { refresh().catch((e) => setError(errText(e))).finally(() => setLoading(false)); }, []);
  useEffect(() => { if (selectedId) refreshSessions(selectedId).catch(() => setSessions([])); }, [selectedId]);

  async function toggleConnection() {
    if (!selected) return;
    setBusy(true); setError("");
    try { selected.connected ? await disconnectSshMachine(selected.id) : await connectSshMachine(selected.id); await refresh(selected.id); }
    catch (e) { setError(errText(e)); } finally { setBusy(false); }
  }

  async function toggleAi(value: boolean) {
    if (!selected) return;
    try { await updateSshMachine(selected.id, { allow_ai_commands: value }); await refresh(selected.id); }
    catch (e) { setError(errText(e)); }
  }

  async function addMachine() {
    if (!name.trim() || !host.trim() || !username.trim()) return;
    setBusy(true); setError("");
    try {
      const created = await createSshMachine({
        name: name.trim(), host: host.trim(), port: Number(port) || 22, username: username.trim(), auth_type: authType,
        password: authType === "password" ? secret : "", private_key: authType === "private_key" ? secret : "",
        passphrase: "", allow_ai_commands: true, connect_timeout_seconds: 15, command_timeout_seconds: 120,
        keepalive_seconds: 30, notes: "",
      });
      setFormOpen(false); setName(""); setHost(""); setUsername(""); setSecret(""); await refresh(created.id);
    } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  }

  async function ensureTerminal(): Promise<string> {
    if (!selected) throw new Error("Choose a machine");
    if (terminalId) return terminalId;
    const created = await createSshTerminalSession(selected.id, "Mobile");
    await refreshSessions(selected.id); setTerminalId(created.id); return created.id;
  }

  async function runCommand() {
    if (!selected || !command.trim()) return;
    setBusy(true); setError("");
    try {
      const id = await ensureTerminal();
      const result = await runSshTerminalCommand(selected.id, id, command.trim());
      setOutput((current) => `${current}${current ? "\n\n" : ""}$ ${command.trim()}\n${result.stdout || ""}${result.stderr || ""}`);
      setCommand("");
    } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  }

  async function closeTerminal() {
    if (!selected || !terminalId) return;
    await closeSshTerminalSession(selected.id, terminalId); setTerminalId(null); setOutput(""); await refreshSessions(selected.id);
  }

  async function removeMachine() {
    if (!selected) return;
    Alert.alert("Delete machine?", selected.name, [{ text: "Cancel" }, { text: "Delete", style: "destructive", onPress: async () => { try { await deleteSshMachine(selected.id); await refresh(); } catch (e) { setError(errText(e)); } } }]);
  }

  return <View style={s.screen}>
    <View style={s.hero}><View><Text style={s.eyebrow}>REMOTE SYSTEMS</Text><Text style={s.title}>SSH connections</Text><Text style={s.subtitle}>Saved machines and persistent shells, wherever you are.</Text></View><TouchableOpacity style={s.primaryIcon} onPress={() => setFormOpen(true)}><Ionicons name="add" size={22} color="#041316" /></TouchableOpacity></View>
    {error ? <Text style={s.error}>{error}</Text> : null}
    {loading ? <ActivityIndicator color={colors.green} /> : <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.machineTabs}>{machines.map((item) => <TouchableOpacity key={item.id} style={[s.machineTab, selectedId === item.id && s.machineTabActive]} onPress={() => setSelectedId(item.id)}><View style={[s.dot, item.connected && s.dotOnline]} /><View><Text style={s.machineName}>{item.name}</Text><Text style={s.small}>{item.username}@{item.host}</Text></View></TouchableOpacity>)}</ScrollView>}
    {!loading && !machines.length ? <View style={s.empty}><Ionicons name="server-outline" size={32} color={colors.muted} /><Text style={s.cardTitle}>No saved machines</Text><Text style={s.muted}>Add your first SSH target to use it from Corv and Coding.</Text></View> : null}
    {selected ? <ScrollView contentContainerStyle={s.content} keyboardShouldPersistTaps="handled">
      <View style={s.card}><View style={s.cardHead}><View><Text style={s.cardTitle}>{selected.name}</Text><Text style={s.muted}>{selected.username}@{selected.host}:{selected.port}</Text></View><View style={[s.status, selected.connected && s.statusOnline]}><Text style={[s.statusText, selected.connected && s.statusTextOnline]}>{selected.connected ? "Connected" : "Offline"}</Text></View></View>
        <View style={s.switchRow}><View style={s.switchCopy}><Text style={s.label}>Allow Corv commands</Text><Text style={s.small}>Required for AI and Codex access.</Text></View><Switch value={selected.allow_ai_commands} onValueChange={toggleAi} trackColor={{ false: colors.border, true: "#16795f" }} thumbColor={selected.allow_ai_commands ? colors.green : "#94a3b8"} /></View>
        <View style={s.actionRow}><TouchableOpacity style={s.secondary} onPress={toggleConnection} disabled={busy}><Text style={s.secondaryText}>{selected.connected ? "Disconnect" : "Connect"}</Text></TouchableOpacity><TouchableOpacity style={s.dangerButton} onPress={removeMachine}><Text style={s.dangerText}>Delete</Text></TouchableOpacity></View>
      </View>
      <View style={s.card}><View style={s.cardHead}><View><Text style={s.cardTitle}>Persistent shell</Text><Text style={s.muted}>{terminalId ? `Session active · ${sessions.find((item) => item.id === terminalId)?.name || "Mobile"}` : "Created when you run the first command"}</Text></View>{terminalId ? <TouchableOpacity onPress={closeTerminal}><Text style={s.dangerText}>Close</Text></TouchableOpacity> : null}</View>
        <View style={s.terminal}><ScrollView><Text selectable style={s.terminalText}>{output || "Your command output will appear here."}</Text></ScrollView></View>
        <View style={s.commandRow}><TextInput style={s.commandInput} value={command} onChangeText={setCommand} placeholder="Enter command…" placeholderTextColor="#607089" autoCapitalize="none" onSubmitEditing={runCommand} /><TouchableOpacity style={[s.send, (!command.trim() || busy) && s.disabled]} onPress={runCommand} disabled={!command.trim() || busy}><Ionicons name="arrow-up" size={18} color="#041316" /></TouchableOpacity></View>
      </View>
    </ScrollView> : null}
    <Modal visible={formOpen} transparent animationType="slide" onRequestClose={() => setFormOpen(false)}><View style={s.modalBackdrop}><View style={s.modal}><View style={s.cardHead}><Text style={s.title}>Add SSH machine</Text><TouchableOpacity onPress={() => setFormOpen(false)}><Ionicons name="close" size={24} color={colors.text} /></TouchableOpacity></View>
      <TextInput style={s.input} value={name} onChangeText={setName} placeholder="Machine name" placeholderTextColor={colors.muted} />
      <TextInput style={s.input} value={host} onChangeText={setHost} placeholder="Host or IP" placeholderTextColor={colors.muted} autoCapitalize="none" />
      <View style={s.split}><TextInput style={[s.input, s.flex]} value={username} onChangeText={setUsername} placeholder="Username" placeholderTextColor={colors.muted} autoCapitalize="none" /><TextInput style={[s.input, s.port]} value={port} onChangeText={setPort} placeholder="Port" keyboardType="number-pad" placeholderTextColor={colors.muted} /></View>
      <View style={s.authTabs}>{(["private_key", "password", "agent"] as const).map((value) => <TouchableOpacity key={value} style={[s.authTab, authType === value && s.authTabActive]} onPress={() => setAuthType(value)}><Text style={[s.authText, authType === value && s.authTextActive]}>{value === "private_key" ? "Key" : value === "password" ? "Password" : "Agent"}</Text></TouchableOpacity>)}</View>
      {authType !== "agent" ? <TextInput style={[s.input, authType === "private_key" && s.keyInput]} value={secret} onChangeText={setSecret} placeholder={authType === "password" ? "Password" : "Private key"} placeholderTextColor={colors.muted} secureTextEntry={authType === "password"} multiline={authType === "private_key"} autoCapitalize="none" /> : null}
      <TouchableOpacity style={[s.primary, busy && s.disabled]} onPress={addMachine} disabled={busy}><Text style={s.primaryText}>{busy ? "Saving…" : "Save machine"}</Text></TouchableOpacity>
    </View></View></Modal>
  </View>;
}

const s = StyleSheet.create({
  screen:{flex:1,backgroundColor:colors.bg}, hero:{padding:18,paddingBottom:14,flexDirection:"row",justifyContent:"space-between",alignItems:"center"}, eyebrow:{color:colors.green,fontSize:10,fontWeight:"800",letterSpacing:1.5},title:{color:colors.text,fontSize:24,fontWeight:"800",marginTop:3},subtitle:{color:colors.muted,fontSize:13,marginTop:4,maxWidth:290},primaryIcon:{width:42,height:42,borderRadius:14,backgroundColor:colors.green,alignItems:"center",justifyContent:"center"},machineTabs:{paddingHorizontal:18,paddingBottom:12,gap:9},machineTab:{minWidth:180,padding:12,borderRadius:14,borderWidth:1,borderColor:colors.border,backgroundColor:colors.card,flexDirection:"row",alignItems:"center",gap:10},machineTabActive:{borderColor:colors.green,backgroundColor:"#10273a"},dot:{width:8,height:8,borderRadius:4,backgroundColor:"#52637a"},dotOnline:{backgroundColor:colors.green},machineName:{color:colors.text,fontWeight:"700"},small:{color:colors.muted,fontSize:11,marginTop:2},content:{padding:18,paddingTop:4,paddingBottom:40,gap:12},card:{backgroundColor:colors.card,borderWidth:1,borderColor:colors.border,borderRadius:18,padding:15},cardHead:{flexDirection:"row",alignItems:"center",justifyContent:"space-between",gap:10},cardTitle:{color:colors.text,fontSize:16,fontWeight:"700"},muted:{color:colors.muted,fontSize:12,marginTop:3},status:{paddingHorizontal:9,paddingVertical:5,borderRadius:999,backgroundColor:"#1a2638"},statusOnline:{backgroundColor:"#123e34"},statusText:{color:colors.muted,fontSize:10,fontWeight:"700"},statusTextOnline:{color:"#9cf3d7"},switchRow:{flexDirection:"row",alignItems:"center",justifyContent:"space-between",marginTop:16,paddingTop:14,borderTopWidth:1,borderTopColor:colors.border},switchCopy:{flex:1,paddingRight:12},label:{color:colors.text,fontWeight:"600"},actionRow:{flexDirection:"row",gap:9,marginTop:14},secondary:{paddingVertical:10,paddingHorizontal:14,borderRadius:11,borderWidth:1,borderColor:colors.border},secondaryText:{color:colors.text,fontWeight:"600"},dangerButton:{paddingVertical:10,paddingHorizontal:14},dangerText:{color:colors.red,fontWeight:"600"},terminal:{height:260,backgroundColor:"#030712",borderRadius:12,borderWidth:1,borderColor:"#1d293d",padding:12,marginTop:14},terminalText:{color:"#c7f9e8",fontFamily:Platform.select({ios:"Menlo",android:"monospace"}),fontSize:12,lineHeight:18},commandRow:{flexDirection:"row",gap:8,marginTop:10},commandInput:{flex:1,backgroundColor:colors.card2,borderWidth:1,borderColor:colors.border,borderRadius:12,paddingHorizontal:12,paddingVertical:11,color:colors.text},send:{width:43,borderRadius:12,backgroundColor:colors.green,alignItems:"center",justifyContent:"center"},disabled:{opacity:.5},empty:{margin:18,padding:28,alignItems:"center",borderWidth:1,borderColor:colors.border,borderRadius:18,backgroundColor:colors.card,gap:7},error:{color:"#fecdd3",backgroundColor:"#3b1823",marginHorizontal:18,marginBottom:10,padding:10,borderRadius:10},modalBackdrop:{flex:1,backgroundColor:"rgba(2,6,15,.78)",justifyContent:"flex-end"},modal:{backgroundColor:colors.card,borderTopLeftRadius:24,borderTopRightRadius:24,padding:20,paddingBottom:34,borderWidth:1,borderColor:colors.border},input:{backgroundColor:colors.card2,borderWidth:1,borderColor:colors.border,borderRadius:12,paddingHorizontal:12,paddingVertical:12,color:colors.text,marginTop:10},split:{flexDirection:"row",gap:8},flex:{flex:1},port:{width:82},authTabs:{flexDirection:"row",gap:7,marginTop:12},authTab:{flex:1,paddingVertical:9,borderRadius:10,borderWidth:1,borderColor:colors.border,alignItems:"center"},authTabActive:{backgroundColor:"#14392f",borderColor:colors.green},authText:{color:colors.muted,fontSize:12},authTextActive:{color:"#b9f8e5",fontWeight:"700"},keyInput:{minHeight:120,textAlignVertical:"top"},primary:{backgroundColor:colors.green,borderRadius:12,padding:13,alignItems:"center",marginTop:15},primaryText:{color:"#041316",fontWeight:"800"},
});
