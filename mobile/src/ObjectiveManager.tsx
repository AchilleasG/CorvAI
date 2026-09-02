import { useEffect, useMemo, useState } from "react";
import { Alert, Modal, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from "react-native";

import {
  createObjective,
  createObjectiveTask,
  deleteObjective,
  deleteObjectiveTask,
  fetchObjective,
  fetchObjectiveRoots,
  fetchObjectiveTree,
  updateObjective,
  updateObjectiveTask,
} from "./api";
import type { Objective, ObjectiveTask } from "./types";

type ObjectiveDraft = {
  id: string; parent_id: string; title: string; description: string; notes: string;
  status: string; deadline_at: string; estimated: string; remaining: string; priority: string;
};
type TaskDraft = {
  id: string; objective_id: string; title: string; description: string; status: string;
  due_at: string; estimated: string; remaining: string;
};

function flatten(root: Objective | null): Objective[] {
  return root ? [root, ...root.children.flatMap(flatten)] : [];
}

function dateValue(value?: string | null): string {
  return value ? new Date(value).toISOString().slice(0, 16) : "";
}

function isoValue(value: string): string | null {
  if (!value.trim()) return null;
  const parsed = new Date(value.trim());
  return Number.isNaN(parsed.getTime()) ? value.trim() : parsed.toISOString();
}

export default function ObjectiveManager({ onChanged }: { onChanged?: () => void }) {
  const [roots, setRoots] = useState<Objective[]>([]);
  const [tree, setTree] = useState<Objective | null>(null);
  const [selected, setSelected] = useState<Objective | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [objectiveDraft, setObjectiveDraft] = useState<ObjectiveDraft | null>(null);
  const [taskDraft, setTaskDraft] = useState<TaskDraft | null>(null);
  const nodes = useMemo(() => flatten(tree), [tree]);

  async function refresh(preferredRoot?: string | null, preferredNode?: string | null) {
    try {
      setBusy(true); setError("");
      const nextRoots = await fetchObjectiveRoots();
      setRoots(nextRoots);
      const rootId = preferredRoot && nextRoots.some(item => item.id === preferredRoot)
        ? preferredRoot : nextRoots[0]?.id;
      if (!rootId) { setTree(null); setSelected(null); return; }
      const nextTree = await fetchObjectiveTree(rootId);
      setTree(nextTree);
      const all = flatten(nextTree);
      const nodeId = preferredNode && all.some(item => item.id === preferredNode) ? preferredNode : nextTree.id;
      setSelected(await fetchObjective(nodeId));
    } catch (exc: any) {
      setError(exc.message || "Could not load objectives");
    } finally { setBusy(false); }
  }

  useEffect(() => { refresh(); }, []);

  function createDraft(parentId = "") {
    setObjectiveDraft({ id: "", parent_id: parentId, title: "", description: "", notes: "", status: "active", deadline_at: "", estimated: "", remaining: "", priority: "0" });
  }

  function editDraft(item: Objective) {
    setObjectiveDraft({
      id: item.id, parent_id: item.parent_id || "", title: item.title, description: item.description || "",
      notes: item.notes || "", status: item.status, deadline_at: dateValue(item.deadline_at),
      estimated: item.estimated_effort_minutes == null ? "" : String(item.estimated_effort_minutes),
      remaining: item.remaining_effort_minutes == null ? "" : String(item.remaining_effort_minutes),
      priority: String(item.priority || 0),
    });
  }

  async function saveObjective() {
    if (!objectiveDraft?.title.trim()) return;
    try {
      setBusy(true);
      const payload = {
        parent_id: objectiveDraft.parent_id || null, title: objectiveDraft.title.trim(),
        description: objectiveDraft.description.trim(), notes: objectiveDraft.notes.trim(), status: objectiveDraft.status,
        deadline_at: isoValue(objectiveDraft.deadline_at), priority: Number.parseInt(objectiveDraft.priority, 10) || 0,
        estimated_effort_minutes: objectiveDraft.estimated ? Number.parseInt(objectiveDraft.estimated, 10) : null,
        remaining_effort_minutes: objectiveDraft.remaining ? Number.parseInt(objectiveDraft.remaining, 10) : null,
      };
      const saved = objectiveDraft.id ? await updateObjective(objectiveDraft.id, payload) : await createObjective(payload);
      setObjectiveDraft(null);
      await refresh(saved.parent_id ? tree?.id : saved.id, saved.id);
      onChanged?.();
    } catch (exc: any) { setError(exc.message || "Could not save objective"); }
    finally { setBusy(false); }
  }

  function removeObjective(item: Objective) {
    const managed = String(item.metadata?.source || "").startsWith("study_");
    Alert.alert(
      "Delete objective?",
      `Delete “${item.title}”, its descendants, tasks, logs, and generated sessions?${managed ? " This is managed by Study and may remove linked study data." : ""}`,
      [{ text: "Cancel", style: "cancel" }, { text: "Delete", style: "destructive", onPress: async () => {
        try { setBusy(true); await deleteObjective(item.id); await refresh(null, null); onChanged?.(); }
        catch (exc: any) { setError(exc.message || "Could not delete objective"); }
        finally { setBusy(false); }
      }}],
    );
  }

  function createTaskDraft(objectiveId: string) {
    setTaskDraft({ id: "", objective_id: objectiveId, title: "", description: "", status: "todo", due_at: "", estimated: "60", remaining: "60" });
  }

  function editTaskDraft(task: ObjectiveTask) {
    setTaskDraft({ id: task.id, objective_id: task.objective_id, title: task.title, description: task.description || "", status: task.status, due_at: dateValue(task.due_at), estimated: task.estimated_effort_minutes == null ? "" : String(task.estimated_effort_minutes), remaining: task.remaining_effort_minutes == null ? "" : String(task.remaining_effort_minutes) });
  }

  async function saveTask() {
    if (!taskDraft?.title.trim()) return;
    try {
      setBusy(true);
      const payload = { objective_id: taskDraft.objective_id, title: taskDraft.title.trim(), description: taskDraft.description.trim(), status: taskDraft.status, due_at: isoValue(taskDraft.due_at), estimated_effort_minutes: taskDraft.estimated ? Number.parseInt(taskDraft.estimated, 10) : null, remaining_effort_minutes: taskDraft.remaining ? Number.parseInt(taskDraft.remaining, 10) : null };
      if (taskDraft.id) await updateObjectiveTask(taskDraft.id, payload); else await createObjectiveTask(taskDraft.objective_id, payload);
      const objectiveId = taskDraft.objective_id; setTaskDraft(null); await refresh(tree?.id, objectiveId); onChanged?.();
    } catch (exc: any) { setError(exc.message || "Could not save task"); }
    finally { setBusy(false); }
  }

  function removeTask(task: ObjectiveTask) {
    Alert.alert("Delete task?", `Delete “${task.title}”?`, [{ text: "Cancel", style: "cancel" }, { text: "Delete", style: "destructive", onPress: async () => {
      try { setBusy(true); await deleteObjectiveTask(task.id); await refresh(tree?.id, task.objective_id); onChanged?.(); }
      catch (exc: any) { setError(exc.message || "Could not delete task"); }
      finally { setBusy(false); }
    }}]);
  }

  return <View style={s.card}>
    <View style={s.header}><View style={s.flex}><Text style={s.kicker}>OBJECTIVES</Text><Text style={s.title}>Goals and tasks</Text></View><TouchableOpacity style={s.primary} onPress={() => createDraft()}><Text style={s.primaryText}>New root</Text></TouchableOpacity></View>
    {!!error && <Text style={s.error}>{error}</Text>}
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.tabs}>{roots.map(root => <TouchableOpacity key={root.id} style={[s.tab, tree?.id === root.id && s.tabActive]} onPress={() => refresh(root.id, root.id)}><Text style={s.tabText}>{root.title}</Text></TouchableOpacity>)}</ScrollView>
    {nodes.map((item) => <TouchableOpacity key={item.id} style={[s.node, selected?.id === item.id && s.nodeActive, { marginLeft: Math.min(nodes.filter(candidate => candidate.id === item.parent_id).length ? 14 : 0, 28) }]} onPress={async () => setSelected(await fetchObjective(item.id))}><Text style={s.nodeTitle}>{item.title}</Text><Text style={s.meta}>{item.status}{item.deadline_at ? ` · ${new Date(item.deadline_at).toLocaleDateString()}` : ""}</Text></TouchableOpacity>)}
    {selected && <View style={s.detail}><Text style={s.title}>{selected.title}</Text>{!!selected.description && <Text style={s.copy}>{selected.description}</Text>}<View style={s.actions}><Action label="Edit" onPress={() => editDraft(selected)} /><Action label="Add child" onPress={() => createDraft(selected.id)} /><Action label="Add task" onPress={() => createTaskDraft(selected.id)} /><Action label="Delete" danger onPress={() => removeObjective(selected)} /></View><Text style={s.kicker}>TASKS</Text>{selected.tasks.map(task => <View key={task.id} style={s.task}><View style={s.flex}><Text style={s.nodeTitle}>{task.title}</Text><Text style={s.meta}>{task.status}{task.due_at ? ` · due ${new Date(task.due_at).toLocaleString()}` : ""}</Text></View><Action label="Edit" onPress={() => editTaskDraft(task)} /><Action label="Delete" danger onPress={() => removeTask(task)} /></View>)}</View>}
    <ObjectiveModal draft={objectiveDraft} setDraft={setObjectiveDraft} nodes={[...new Map([...roots, ...nodes].map(item => [item.id, item])).values()]} busy={busy} save={saveObjective} />
    <TaskModal draft={taskDraft} setDraft={setTaskDraft} nodes={nodes} busy={busy} save={saveTask} />
  </View>;
}

function Action({ label, onPress, danger = false }: { label: string; onPress: () => void; danger?: boolean }) { return <TouchableOpacity style={s.action} onPress={onPress}><Text style={[s.actionText, danger && s.danger]}>{label}</Text></TouchableOpacity>; }

function ObjectiveModal({ draft, setDraft, nodes, busy, save }: { draft: ObjectiveDraft | null; setDraft: (value: ObjectiveDraft | null) => void; nodes: Objective[]; busy: boolean; save: () => void }) {
  if (!draft) return null;
  return <Modal visible transparent animationType="slide"><View style={s.backdrop}><View style={s.modal}><Text style={s.title}>{draft.id ? "Edit objective" : "Create objective"}</Text><ScrollView keyboardShouldPersistTaps="handled"><Field label="Title" value={draft.title} change={value => setDraft({ ...draft, title: value })} /><Text style={s.label}>Parent</Text><ScrollView horizontal contentContainerStyle={s.tabs}><Action label="Root" onPress={() => setDraft({ ...draft, parent_id: "" })} />{nodes.filter(item => item.id !== draft.id).map(item => <Action key={item.id} label={item.title} onPress={() => setDraft({ ...draft, parent_id: item.id })} />)}</ScrollView><Text style={s.label}>Status</Text><ScrollView horizontal contentContainerStyle={s.tabs}>{["active","paused","completed","canceled"].map(status => <Action key={status} label={status} onPress={() => setDraft({ ...draft, status })} />)}</ScrollView><Field label="Deadline (ISO or YYYY-MM-DD HH:mm)" value={draft.deadline_at} change={value => setDraft({ ...draft, deadline_at: value })} /><Field label="Priority" value={draft.priority} change={value => setDraft({ ...draft, priority: value })} numeric /><Field label="Estimated minutes" value={draft.estimated} change={value => setDraft({ ...draft, estimated: value })} numeric /><Field label="Remaining minutes" value={draft.remaining} change={value => setDraft({ ...draft, remaining: value })} numeric /><Field label="Description" value={draft.description} change={value => setDraft({ ...draft, description: value })} multiline /><Field label="Planning notes" value={draft.notes} change={value => setDraft({ ...draft, notes: value })} multiline /><View style={s.actions}><Action label="Cancel" onPress={() => setDraft(null)} /><TouchableOpacity style={s.primary} disabled={busy || !draft.title.trim()} onPress={save}><Text style={s.primaryText}>{busy ? "Saving…" : "Save"}</Text></TouchableOpacity></View></ScrollView></View></View></Modal>;
}

function TaskModal({ draft, setDraft, nodes, busy, save }: { draft: TaskDraft | null; setDraft: (value: TaskDraft | null) => void; nodes: Objective[]; busy: boolean; save: () => void }) {
  if (!draft) return null;
  return <Modal visible transparent animationType="slide"><View style={s.backdrop}><View style={s.modal}><Text style={s.title}>{draft.id ? "Edit task" : "Create task"}</Text><ScrollView keyboardShouldPersistTaps="handled"><Field label="Title" value={draft.title} change={value => setDraft({ ...draft, title: value })} /><Text style={s.label}>Objective</Text><ScrollView horizontal contentContainerStyle={s.tabs}>{nodes.map(item => <Action key={item.id} label={item.title} onPress={() => setDraft({ ...draft, objective_id: item.id })} />)}</ScrollView><Text style={s.label}>Status</Text><ScrollView horizontal contentContainerStyle={s.tabs}>{["todo","in_progress","blocked","done","canceled"].map(status => <Action key={status} label={status} onPress={() => setDraft({ ...draft, status })} />)}</ScrollView><Field label="Deadline (ISO or YYYY-MM-DD HH:mm)" value={draft.due_at} change={value => setDraft({ ...draft, due_at: value })} /><Field label="Estimated minutes" value={draft.estimated} change={value => setDraft({ ...draft, estimated: value })} numeric /><Field label="Remaining minutes" value={draft.remaining} change={value => setDraft({ ...draft, remaining: value })} numeric /><Field label="Description" value={draft.description} change={value => setDraft({ ...draft, description: value })} multiline /><View style={s.actions}><Action label="Cancel" onPress={() => setDraft(null)} /><TouchableOpacity style={s.primary} disabled={busy || !draft.title.trim()} onPress={save}><Text style={s.primaryText}>{busy ? "Saving…" : "Save"}</Text></TouchableOpacity></View></ScrollView></View></View></Modal>;
}

function Field({ label, value, change, numeric = false, multiline = false }: { label: string; value: string; change: (value: string) => void; numeric?: boolean; multiline?: boolean }) { return <View><Text style={s.label}>{label}</Text><TextInput style={[s.input, multiline && s.textarea]} value={value} onChangeText={change} keyboardType={numeric ? "number-pad" : "default"} multiline={multiline} /></View>; }

const s = StyleSheet.create({ card:{marginTop:18,padding:15,borderRadius:18,borderWidth:1,borderColor:"#24364c",backgroundColor:"#0d1b2d"},header:{flexDirection:"row",alignItems:"center",gap:10},flex:{flex:1},kicker:{color:"#49d6ae",fontSize:9,fontWeight:"800",letterSpacing:1.3,marginTop:9},title:{color:"#edf5ff",fontSize:17,fontWeight:"800"},primary:{backgroundColor:"#49d6ae",borderRadius:10,paddingHorizontal:12,paddingVertical:9},primaryText:{color:"#061418",fontWeight:"800"},tabs:{gap:7,paddingVertical:10},tab:{borderWidth:1,borderColor:"#24364c",borderRadius:999,paddingHorizontal:11,paddingVertical:7},tabActive:{borderColor:"#49d6ae",backgroundColor:"#12362f"},tabText:{color:"#d9e7f5",fontSize:11},node:{padding:10,borderRadius:11,borderWidth:1,borderColor:"#24364c",marginBottom:6},nodeActive:{borderColor:"#8b7cf6",backgroundColor:"#1b1d3c"},nodeTitle:{color:"#edf5ff",fontWeight:"700",fontSize:12},meta:{color:"#8fa5bc",fontSize:10,marginTop:3},copy:{color:"#c8d5e3",fontSize:12,lineHeight:18,marginVertical:6},detail:{borderTopWidth:1,borderTopColor:"#24364c",marginTop:8,paddingTop:12},actions:{flexDirection:"row",gap:7,flexWrap:"wrap",alignItems:"center",marginVertical:10},action:{borderWidth:1,borderColor:"#314861",borderRadius:9,paddingHorizontal:9,paddingVertical:7},actionText:{color:"#d9e7f5",fontSize:11,fontWeight:"600"},danger:{color:"#fb7185"},task:{flexDirection:"row",alignItems:"center",gap:6,paddingVertical:9,borderBottomWidth:1,borderBottomColor:"#24364c"},error:{color:"#fda4af",marginTop:8},backdrop:{flex:1,backgroundColor:"rgba(2,6,15,.82)",justifyContent:"flex-end"},modal:{maxHeight:"90%",backgroundColor:"#0d1b2d",padding:18,paddingBottom:32,borderTopLeftRadius:24,borderTopRightRadius:24,borderWidth:1,borderColor:"#24364c"},label:{color:"#c8d5e3",fontSize:11,fontWeight:"600",marginTop:11,marginBottom:4},input:{color:"#edf5ff",backgroundColor:"#101f32",borderWidth:1,borderColor:"#2b4058",borderRadius:11,paddingHorizontal:11,paddingVertical:10},textarea:{minHeight:80,textAlignVertical:"top"} });
