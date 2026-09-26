import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  createWorkoutExercise,
  createWorkoutGoal,
  createWorkoutPlan,
  deleteWorkoutExercise,
  deleteWorkoutPlan,
  createWorkoutSession,
  deleteWorkoutSession,
  fetchActiveWorkoutSessions,
  finishWorkoutSession,
  startWorkoutSession,
  updateWorkoutExercise,
  updateWorkoutPlan,
  updateWorkoutSession,
  updateWorkoutSessionItem,
  updateWorkoutSet,
  updateWorkoutSessionState,
  fetchWorkoutDashboard,
  fetchWorkoutExerciseDetails,
  fetchWorkoutExercises,
  fetchWorkoutGoals,
  fetchWorkoutPlans,
  fetchWorkoutSessions,
  updateWorkoutGoal,
} from "./api";
import type {
  WorkoutDashboard,
  WorkoutExercise,
  WorkoutExerciseSpec,
  WorkoutGoal,
  WorkoutPlan,
  WorkoutSession,
} from "./types";
import "./workout.css";

const emptyLog = (): WorkoutExerciseSpec => ({ name: "", sets: 3, reps: 10 });
type PlanSessionDraft = {
  name: string;
  description: string;
  guidance_mode: "checklist" | "guided";
  guidance_level: "minimal" | "full";
  auto_start_phases: boolean;
  exercises: WorkoutExerciseSpec[];
};
const emptyPlanSession = (index = 0): PlanSessionDraft => ({
  name: `Session ${index + 1}`,
  description: "",
  guidance_mode: "checklist",
  guidance_level: "minimal",
  auto_start_phases: false,
  exercises: [emptyLog()],
});
function errText(error: unknown) {
  if (!(error instanceof Error)) return "Something went wrong";
  try {
    const body = JSON.parse(error.message);
    return body.detail || body.message || error.message;
  } catch {
    return error.message;
  }
}
function localInput(date = new Date()) {
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}
function durationText(seconds: number) {
  if (!seconds) return "—";
  const mins = Math.round(seconds / 60);
  return mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)}h ${mins % 60}m`;
}
function prescriptionText(row: {sets?:number|null;reps?:number|string|null;duration_seconds?:number|null;phase_type?:string;metadata?:Record<string,unknown>}) {
  const sets=row.sets ? `${row.sets} set${row.sets===1?"":"s"}` : "";
  const perSide=row.metadata?.per_side ? " / side" : "";
  if(row.phase_type==="timed" || row.duration_seconds){
    const low=row.metadata?.duration_seconds_min;
    const high=row.metadata?.duration_seconds_max ?? row.duration_seconds;
    const time=low&&high&&low!==high?`${String(low)}–${String(high)} sec`:high?`${String(high)} sec`:"time not set";
    return [sets,time+perSide].filter(Boolean).join(" × ");
  }
  const reps=row.reps || row.metadata?.prescribed_reps;
  return [sets,reps?`${String(reps)} reps${perSide}`:"reps not set"].filter(Boolean).join(" × ");
}
function setTargetText(target:Record<string,unknown>){
  if(target.reps)return `${String(target.reps)} reps${target.per_side?" / side":""}`;
  const low=target.duration_seconds_min,high=target.duration_seconds_max||target.duration_seconds;
  if(low&&high&&low!==high)return `${String(low)}–${String(high)} sec${target.per_side?" / side":""}`;
  return high?`${String(high)} sec${target.per_side?" / side":""}`:"Target not set";
}
function LineChart({
  points,
  label,
  color = "#2ad1a3",
}: {
  points: number[];
  label: string;
  color?: string;
}) {
  const width = 680,
    height = 180,
    pad = 18,
    max = Math.max(...points, 1),
    step = points.length > 1 ? (width - pad * 2) / (points.length - 1) : 0;
  const path = points
    .map(
      (value, index) =>
        `${index ? "L" : "M"} ${pad + index * step} ${height - pad - (value / max) * (height - pad * 2)}`,
    )
    .join(" ");
  return (
    <div className="workout-chart">
      <div>
        <strong>{label}</strong>
        <span>Peak {Math.round(max * 10) / 10}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
        <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} />
        <path d={path} style={{ stroke: color }} />
        {points.map((value, index) => (
          <circle
            key={index}
            cx={pad + index * step}
            cy={height - pad - (value / max) * (height - pad * 2)}
            r="3"
            style={{ fill: color }}
          >
            <title>{value}</title>
          </circle>
        ))}
      </svg>
    </div>
  );
}

function GuidedTimer({
  seconds,
  onComplete,
}: {
  seconds: number;
  onComplete: () => void;
}) {
  const [remaining, setRemaining] = useState(seconds),
    [running, setRunning] = useState(false);
  useEffect(() => {
    if (!running || remaining <= 0) return;
    const id = window.setTimeout(
      () => setRemaining((value) => value - 1),
      1000,
    );
    return () => window.clearTimeout(id);
  }, [running, remaining]);
  useEffect(() => {
    if (running && remaining === 0) {
      setRunning(false);
      onComplete();
    }
  }, [remaining, running, onComplete]);
  return (
    <div className={`guided-timer ${remaining <= 10 ? "ending" : ""}`}>
      <strong>
        {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, "0")}
      </strong>
      <button
        type="button"
        className="primary"
        onClick={() => setRunning((value) => !value)}
      >
        {running
          ? "Pause timer"
          : remaining === seconds
            ? "Start phase"
            : "Resume"}
      </button>
      <button
        type="button"
        className="ghost"
        onClick={() => setRemaining((value) => value + 30)}
      >
        +30s
      </button>
    </div>
  );
}

function PlanContents({ plan }: { plan: WorkoutPlan }) {
  return (
    <div className="saved-plan-days">
      {plan.sessions?.map((day) => (
        <section key={day.id}>
          <div>
            <strong>{day.name}</strong>
            <span>
              {day.guidance_mode} · {day.exercises.length} exercises
            </span>
          </div>
          <ol>
            {day.exercises.map((row) => (
              <li key={row.id}>
                <span>{row.exercise.name}</span>
                <small>
                  {[
                    prescriptionText(row),
                    row.rest_seconds != null && `${row.rest_seconds}s rest`, row.block_name,
                  ]
                    .filter(Boolean)
                    .join(" · ") || "As needed"}
                </small>
              </li>
            ))}
          </ol>
        </section>
      ))}
      {!!plan.exercises.length && (
        <section>
          <div>
            <strong>General session</strong>
            <span>{plan.exercises.length} exercises</span>
          </div>
          <ol>
            {plan.exercises.map((row) => (
              <li key={row.id}>
                <span>{row.exercise.name}</span>
                <small>
                  {[prescriptionText(row)]
                    .filter(Boolean)
                    .join(" · ") || "As needed"}
                </small>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

export default function WorkoutPanel() {
  const [view, setView] = useState<
    "live" | "plans" | "progress" | "history" | "exercises"
  >("live");
  const [showPlanForm, setShowPlanForm] = useState(false),
    [showLogForm, setShowLogForm] = useState(false),
    [showExerciseForm, setShowExerciseForm] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState<WorkoutPlan | null>(null),
    [selectedSession, setSelectedSession] = useState<WorkoutSession | null>(
      null,
    ),
    [selectedExercise, setSelectedExercise] = useState<WorkoutExercise | null>(
      null,
    );
  const [dashboard, setDashboard] = useState<WorkoutDashboard | null>(null),
    [plans, setPlans] = useState<WorkoutPlan[]>([]),
    [sessions, setSessions] = useState<WorkoutSession[]>([]),
    [activeSessions, setActiveSessions] = useState<WorkoutSession[]>([]),
    [exercises, setExercises] = useState<WorkoutExercise[]>([]),
    [goals, setGoals] = useState<WorkoutGoal[]>([]);
  const [loading, setLoading] = useState(true),
    [saving, setSaving] = useState(false),
    [enrichmentLoading, setEnrichmentLoading] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [logTitle, setLogTitle] = useState("Workout"),
    [logPlan, setLogPlan] = useState(""),
    [logStarted, setLogStarted] = useState(localInput()),
    [logEnded, setLogEnded] = useState(""),
    [logNotes, setLogNotes] = useState(""),
    [logRows, setLogRows] = useState<WorkoutExerciseSpec[]>([emptyLog()]);
  const [planTitle, setPlanTitle] = useState(""),
    [planGoal, setPlanGoal] = useState(""),
    [planDescription, setPlanDescription] = useState(""),
    [planSessions, setPlanSessions] = useState<PlanSessionDraft[]>([
      emptyPlanSession(),
    ]);
  const [exerciseName, setExerciseName] = useState(""),
    [exerciseGroup, setExerciseGroup] = useState(""),
    [exerciseEquipment, setExerciseEquipment] = useState("");
  const [goalTitle, setGoalTitle] = useState("Train consistently"),
    [goalMetric, setGoalMetric] = useState("sessions_per_week"),
    [goalTarget, setGoalTarget] = useState("3"),
    [goalExercise, setGoalExercise] = useState("");
  const [trendExercise, setTrendExercise] = useState("");
  async function refresh() {
    setLoading(true);
    try {
      const [d, p, s, a, e, g] = await Promise.all([
        fetchWorkoutDashboard(90, trendExercise),
        fetchWorkoutPlans(),
        fetchWorkoutSessions({ limit: 100 }),
        fetchActiveWorkoutSessions(),
        fetchWorkoutExercises(),
        fetchWorkoutGoals(),
      ]);
      setDashboard(d);
      setPlans(p.plans);
      setSessions(s.sessions);
      setActiveSessions(a.sessions);
      setExercises(e.exercises);
      setGoals(g.goals);
      setError("");
    } catch (err) {
      setError(errText(err));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void refresh();
  }, []);
  useEffect(() => {
    if (!dashboard) return;
    fetchWorkoutDashboard(90, trendExercise)
      .then(setDashboard)
      .catch(() => undefined);
  }, [trendExercise]);
  const weeklyGoal = useMemo(
    () =>
      goals.find((goal) => goal.active && goal.metric === "sessions_per_week"),
    [goals],
  );
  function updateRow(
    index: number,
    field: keyof WorkoutExerciseSpec,
    value: string,
  ) {
    setLogRows((rows) =>
      rows.map((row, i) =>
        i === index
          ? {
              ...row,
              [field]: [
                "sets",
                "reps",
                "weight_kg",
                "duration_seconds",
                "distance_km",
                "rpe",
              ].includes(field)
                ? value === ""
                  ? undefined
                  : Number(value)
                : value,
            }
          : row,
      ),
    );
  }
  async function submitLog(event: FormEvent) {
    event.preventDefault();
    const rows = logRows.filter((row) => row.name.trim());
    if (!rows.length) {
      setError("Add at least one exercise");
      return;
    }
    setSaving(true);
    try {
      const item = await createWorkoutSession({
        title: logTitle,
        plan: logPlan || undefined,
        started_at: new Date(logStarted).toISOString(),
        ended_at: logEnded ? new Date(logEnded).toISOString() : undefined,
        notes: logNotes,
        exercises: rows,
      });
      setNotice(
        `Logged ${item.exercises.length} exercise${item.exercises.length === 1 ? "" : "s"}${item.created_exercises?.length ? ` · added ${item.created_exercises.join(", ")} to the directory` : ""}.`,
      );
      setLogRows([emptyLog()]);
      setLogNotes("");
      setLogEnded("");
      setLogStarted(localInput());
      setShowLogForm(false);
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }
  async function startPlanSession(
    planId: string,
    plannedSession?: string,
    mode: "checklist" | "guided" = "checklist",
    guidance_level: "minimal" | "full" = "minimal",
  ) {
    setSaving(true);
    try {
      await startWorkoutSession({
        plan: planId,
        planned_session: plannedSession,
        mode,
        guidance_level,
      });
      setNotice(
        `${mode === "guided" ? "Guided" : "Checklist"} workout started.`,
      );
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }
  async function startAdHocSession() {
    const rows = logRows.filter((row) => row.name.trim());
    if (!rows.length) {
      setError("Add at least one exercise first");
      return;
    }
    setSaving(true);
    try {
      await startWorkoutSession({
        title: logTitle,
        started_at: new Date(logStarted).toISOString(),
        notes: logNotes,
        exercises: rows,
      });
      setNotice("Live workout started.");
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }
  async function toggleActiveItem(
    sessionId: string,
    logId: string,
    completed: boolean,
  ) {
    try {
      const item = await updateWorkoutSessionItem(logId, { completed });
      setActiveSessions((items) =>
        items.map((session) =>
          session.id === sessionId
            ? {
                ...session,
                exercises: session.exercises.map((row) =>
                  row.id === logId ? item : row,
                ),
              }
            : session,
        ),
      );
    } catch (err) {
      setError(errText(err));
    }
  }
  async function finishActiveSession(sessionId: string) {
    setSaving(true);
    try {
      await finishWorkoutSession(sessionId, { draft: true });
      setNotice("Draft report ready. Review it, then submit.");
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }
  async function removeSession(session: WorkoutSession) {
    if (
      !window.confirm(
        `Delete ${session.title || "this workout"} from ${new Date(session.started_at).toLocaleString()}?`,
      )
    )
      return;
    setSaving(true);
    setError("");
    try {
      await deleteWorkoutSession(session.id);
      setNotice("Workout session deleted.");
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }
  function updatePlanExercise(
    sessionIndex: number,
    rowIndex: number,
    field: keyof WorkoutExerciseSpec,
    value: string,
  ) {
    setPlanSessions((items) =>
      items.map((session, i) =>
        i !== sessionIndex
          ? session
          : {
              ...session,
              exercises: session.exercises.map((row, j) =>
                j !== rowIndex
                  ? row
                  : {
                      ...row,
                      [field]: [
                        "sets",
                        "reps",
                        "weight_kg",
                        "duration_seconds",
                        "rest_seconds",
                        "cycle_count",
                      ].includes(field)
                        ? value === ""
                          ? undefined
                          : Number(value)
                        : value,
                    },
              ),
            },
      ),
    );
  }
  async function submitPlan(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      const sessions = planSessions
        .map((session) => ({
          ...session,
          exercises: session.exercises.filter((row) => row.name.trim()),
        }))
        .filter((session) => session.exercises.length);
      await createWorkoutPlan({
        title: planTitle,
        goal: planGoal,
        description: planDescription,
        source: "manual",
        sessions,
      });
      setPlanTitle("");
      setPlanGoal("");
      setPlanDescription("");
      setPlanSessions([emptyPlanSession()]);
      setNotice("Workout plan saved with its named sessions.");
      setShowPlanForm(false);
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }
  async function submitExercise(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      const item = await createWorkoutExercise({
        name: exerciseName,
        muscle_group: exerciseGroup,
        equipment: exerciseEquipment,
      });
      setNotice(
        item.created
          ? `${item.name} joined the exercise directory.`
          : `${item.name} was already in the directory.`,
      );
      setExerciseName("");
      setExerciseGroup("");
      setExerciseEquipment("");
      setShowExerciseForm(false);
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }
  async function removePlan(plan: WorkoutPlan) {
    if (
      !window.confirm(
        `Delete the plan “${plan.title}”? Historical sessions will remain.`,
      )
    )
      return;
    setSaving(true);
    try {
      const result = await deleteWorkoutPlan(plan.id);
      setNotice(
        `Plan deleted${result.preserved_sessions ? ` · ${result.preserved_sessions} historical session${result.preserved_sessions === 1 ? "" : "s"} preserved` : ""}.`,
      );
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }
  async function removeExercise(exercise: WorkoutExercise) {
    if (
      !window.confirm(
        `Delete “${exercise.name}” from the exercise directory? If it is referenced, you will be asked to remove those references separately through Corv.`,
      )
    )
      return;
    setSaving(true);
    try {
      await deleteWorkoutExercise(exercise.id);
      setNotice("Exercise deleted from the directory.");
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }
  async function submitGoal(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await createWorkoutGoal({
        title: goalTitle,
        metric: goalMetric,
        target_value: Number(goalTarget),
        exercise:
          goalMetric === "exercise_weight_kg" ? goalExercise : undefined,
        unit:
          goalMetric === "exercise_weight_kg"
            ? "kg"
            : goalMetric === "minutes_per_week"
              ? "minutes"
              : "sessions",
      });
      setNotice("Goal saved. Now comes the suspiciously physical part.");
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }
  async function saveSelectedPlan() {
    if (!selectedPlan) return;
    setSaving(true);
    try {
      await updateWorkoutPlan(selectedPlan.id, {
        title: selectedPlan.title,
        description: selectedPlan.description,
        goal: selectedPlan.goal,
        active: selectedPlan.active,
      });
      setSelectedPlan(null);
      setNotice("Workout plan updated.");
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }
  async function saveSelectedSession() {
    if (!selectedSession) return;
    setSaving(true);
    try {
      await updateWorkoutSession(selectedSession.id, {
        title: selectedSession.title,
        notes: selectedSession.notes,
        started_at: selectedSession.started_at,
        ended_at: selectedSession.ended_at || undefined,
      });
      setSelectedSession(null);
      setNotice("Workout session updated.");
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }
  async function saveSelectedExercise() {
    if (!selectedExercise) return;
    setSaving(true);
    try {
      await updateWorkoutExercise(selectedExercise.id, {
        name: selectedExercise.name,
        category: selectedExercise.category,
        muscle_group: selectedExercise.muscle_group,
        equipment: selectedExercise.equipment,
        instructions: selectedExercise.instructions,
        aliases: selectedExercise.aliases,
      });
      setSelectedExercise(null);
      setNotice("Exercise updated.");
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }
  async function openExerciseDetails(exercise: WorkoutExercise, force = false) {
    setSelectedExercise(exercise);
    setEnrichmentLoading(true);
    setError("");
    try {
      const detailed = await fetchWorkoutExerciseDetails(exercise.id, force);
      setSelectedExercise(detailed);
      setExercises((items) =>
        items.map((item) => (item.id === detailed.id ? detailed : item)),
      );
      setActiveSessions((items) =>
        items.map((session) => ({
          ...session,
          exercises: session.exercises.map((row) =>
            row.exercise.id === detailed.id
              ? { ...row, exercise: detailed }
              : row,
          ),
        })),
      );
    } catch (err) {
      setError(errText(err));
    } finally {
      setEnrichmentLoading(false);
    }
  }
  const views = [
    {
      id: "live",
      label: "Live session",
      hint: activeSessions.length
        ? `${activeSessions.length} active`
        : "Start training",
    },
    { id: "plans", label: "Workout plans", hint: `${plans.length} saved` },
    { id: "progress", label: "Progress", hint: "Trends & goals" },
    { id: "history", label: "History", hint: `${sessions.length} sessions` },
    {
      id: "exercises",
      label: "Exercises",
      hint: `${exercises.length} movements`,
    },
  ] as const;
  return (
    <div className="settings-panel workout-panel" data-view={view}>
      <header className="main-header">
        <div>
          <p className="eyebrow">Training</p>
          <h2>Workout</h2>
          <p className="muted">
            Plans, logs, progress, and enough accountability to be useful.
          </p>
        </div>
        <button
          type="button"
          className="ghost"
          onClick={() => void refresh()}
          disabled={loading}
        >
          Refresh
        </button>
      </header>
      {error && (
        <div className="alert">
          {error}
          <button
            type="button"
            className="ghost pill-action"
            onClick={() => setError("")}
          >
            Dismiss
          </button>
        </div>
      )}
      {notice && (
        <div className="workout-notice">
          {notice}
          <button type="button" onClick={() => setNotice("")}>
            ×
          </button>
        </div>
      )}
      <nav className="workout-subnav" aria-label="Workout sections">
        {views.map((item) => (
          <button
            type="button"
            key={item.id}
            className={view === item.id ? "active" : ""}
            onClick={() => setView(item.id)}
          >
            <strong>{item.label}</strong>
            <span>{item.hint}</span>
          </button>
        ))}
      </nav>
      {view === "plans" && (
        <div className="workout-view-toolbar">
          <div>
            <p className="eyebrow">Programming</p>
            <h3>Your workout plans</h3>
          </div>
          <button
            type="button"
            className="primary"
            onClick={() => setShowPlanForm((value) => !value)}
          >
            {showPlanForm ? "Close builder" : "Add workout plan"}
          </button>
        </div>
      )}
      {view === "history" && (
        <div className="workout-view-toolbar">
          <div>
            <p className="eyebrow">Training log</p>
            <h3>Past sessions</h3>
          </div>
          <button
            type="button"
            className="primary"
            onClick={() => setShowLogForm((value) => !value)}
          >
            {showLogForm ? "Close form" : "Add completed session"}
          </button>
        </div>
      )}
      {view === "exercises" && (
        <div className="workout-view-toolbar">
          <div>
            <p className="eyebrow">Movement library</p>
            <h3>Exercise directory</h3>
          </div>
          <button
            type="button"
            className="primary"
            onClick={() => setShowExerciseForm((value) => !value)}
          >
            {showExerciseForm ? "Close form" : "Add exercise"}
          </button>
        </div>
      )}
      <section className="card workout-active scope-live">
        <div className="card-head">
          <div>
            <p className="eyebrow">Today</p>
            <h3>Active workout</h3>
          </div>
        </div>
        {activeSessions.length ? (
          activeSessions.map((session) => (
            <article className="workout-active-session" key={session.id}>
              <header>
                <div>
                  <strong>{session.title}</strong>
                  <span>
                    {session.mode} · {session.guidance_level} guidance ·{" "}
                    {session.status}
                  </span>
                </div>
                <b>
                  {session.exercises.filter((row) => row.completed).length} /{" "}
                  {session.exercises.length}
                </b>
              </header>
              <div>
                {session.exercises.map((row) => (
                  <div
                    className={`workout-phase ${row.completed ? "done" : ""}`}
                    key={row.id}
                  >
                    <div className="workout-phase-title">
                      <label>
                        <input
                          type="checkbox"
                          checked={row.completed}
                          onChange={(e) =>
                            void toggleActiveItem(
                              session.id,
                              row.id,
                              e.target.checked,
                            )
                          }
                        />
                        <span>
                          <button
                            type="button"
                            className="workout-exercise-link"
                            onClick={(event) => {
                              event.preventDefault();
                              event.stopPropagation();
                              void openExerciseDetails(row.exercise);
                            }}
                          >
                            {row.exercise.name}<i aria-hidden="true">Info</i>
                          </button>
                          <small>
                            {[
                              row.block_name,
                              row.cycle_index > 1 && `round ${row.cycle_index}`,
                              prescriptionText(row),
                              row.metadata?.rest_seconds &&
                                `${String(row.metadata.rest_seconds)}s rest`,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </small>
                        </span>
                      </label>
                    </div>
                    {session.mode === "guided" &&
                      row.phase_type === "timed" &&
                      !row.completed && (
                        <GuidedTimer
                          seconds={row.duration_seconds || 30}
                          onComplete={() =>
                            void toggleActiveItem(session.id, row.id, true)
                          }
                        />
                      )}
                    <div className="workout-sets">
                      {row.set_logs?.map((set) => (
                        <button
                          type="button"
                          key={set.id}
                          className={
                            set.status === "completed" ? "set-done" : "ghost"
                          }
                          onClick={() =>
                            updateWorkoutSet(set.id, {
                              status:
                                set.status === "completed"
                                  ? "pending"
                                  : "completed",
                              actual: set.target,
                            }).then((item) =>
                              setActiveSessions((items) =>
                                items.map((active) =>
                                  active.id === session.id
                                    ? {
                                        ...active,
                                        exercises: active.exercises.map(
                                          (log) =>
                                            log.id === item.id ? item : log,
                                        ),
                                      }
                                    : active,
                                ),
                              ),
                            )
                          }
                        >
                          Set {set.set_index}
                          {` · ${setTargetText(set.target)}`}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <div className="workout-session-actions">
                {session.status === "draft" ? (
                  <>
                    <button
                      type="button"
                      className="primary"
                      onClick={() =>
                        updateWorkoutSessionState(session.id, "submit").then(
                          refresh,
                        )
                      }
                    >
                      Submit report
                    </button>
                    <span className="muted">
                      Review and edit each set above before submitting.
                    </span>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      className="primary"
                      disabled={saving}
                      onClick={() => void finishActiveSession(session.id)}
                    >
                      Finish & review
                    </button>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() =>
                        updateWorkoutSessionState(
                          session.id,
                          session.status === "paused" ? "resume" : "pause",
                        ).then(refresh)
                      }
                    >
                      {session.status === "paused" ? "Resume" : "Pause"}
                    </button>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() =>
                        updateWorkoutSessionState(session.id, "abandon").then(
                          refresh,
                        )
                      }
                    >
                      Abandon
                    </button>
                  </>
                )}
              </div>
            </article>
          ))
        ) : (
          <div>
            <p className="muted">
              Choose a planned session and how you want to run it.
            </p>
            <div className="workout-start-grid">
              {plans.flatMap((plan) =>
                (plan.sessions?.length
                  ? plan.sessions
                  : [
                      {
                        id: "",
                        name: plan.title,
                        guidance_mode: "checklist",
                        guidance_level: "minimal",
                      } as any,
                    ]
                ).map((day) => (
                  <article key={`${plan.id}-${day.id}`}>
                    <div>
                      <strong>{day.name}</strong>
                      <span>{plan.title}</span>
                    </div>
                    <div>
                      <button
                        type="button"
                        className="ghost"
                        onClick={() =>
                          void startPlanSession(
                            plan.id,
                            day.id,
                            "checklist",
                            "minimal",
                          )
                        }
                      >
                        Checklist
                      </button>
                      <button
                        type="button"
                        className="primary"
                        onClick={() =>
                          void startPlanSession(
                            plan.id,
                            day.id,
                            "guided",
                            "full",
                          )
                        }
                      >
                        Full guided
                      </button>
                    </div>
                  </article>
                )),
              )}
            </div>
          </div>
        )}
      </section>
      <div className="workout-stat-grid scope-progress">
        <article>
          <small>Last 90 days</small>
          <strong>{dashboard?.session_count || 0}</strong>
          <span>sessions</span>
        </article>
        <article>
          <small>This week</small>
          <strong>
            {dashboard?.current_week_sessions || 0}
            {weeklyGoal ? ` / ${weeklyGoal.target_value}` : ""}
          </strong>
          <span>sessions</span>
        </article>
        <article>
          <small>Current streak</small>
          <strong>{dashboard?.current_streak_days || 0}</strong>
          <span>training days</span>
        </article>
        <article>
          <small>Exercise directory</small>
          <strong>{exercises.length}</strong>
          <span>movements</span>
        </article>
      </div>
      <section className="workout-dashboard-grid scope-progress">
        <div className="card workout-trends">
          <div className="card-head">
            <div>
              <p className="eyebrow">Consistency</p>
              <h3>Training trend</h3>
            </div>
            <select
              aria-label="Exercise trend"
              value={trendExercise}
              onChange={(e) => setTrendExercise(e.target.value)}
            >
              <option value="">All exercises</option>
              {exercises.map((x) => (
                <option key={x.id}>{x.name}</option>
              ))}
            </select>
          </div>
          <LineChart
            label="Weekly sessions"
            points={(dashboard?.weekly || []).map((x) => x.sessions)}
          />
          <LineChart
            label={
              trendExercise
                ? `${trendExercise} volume (kg)`
                : "Daily training volume (kg)"
            }
            color="#60a5fa"
            points={
              trendExercise
                ? (dashboard?.exercise_trend || []).map((x) => x.volume_kg)
                : (dashboard?.daily || []).slice(-30).map((x) => x.volume_kg)
            }
          />
        </div>
        <div className="card workout-goals">
          <div className="card-head">
            <div>
              <p className="eyebrow">Targets</p>
              <h3>Active goals</h3>
            </div>
          </div>
          {dashboard?.goals.length ? (
            dashboard.goals.map((goal) => (
              <article key={goal.id}>
                <div>
                  <strong>{goal.title}</strong>
                  <span>
                    {goal.current_value} / {goal.target_value} {goal.unit}
                  </span>
                </div>
                <div className="workout-progress">
                  <i style={{ width: `${goal.progress_percent}%` }} />
                </div>
                <button
                  type="button"
                  className="ghost pill-action"
                  onClick={() =>
                    updateWorkoutGoal(goal.id, false).then(refresh)
                  }
                >
                  Archive
                </button>
              </article>
            ))
          ) : (
            <p className="muted">
              No goals yet. Ambition remains safely theoretical.
            </p>
          )}
          <form onSubmit={submitGoal} className="workout-compact-form">
            <input
              required
              value={goalTitle}
              onChange={(e) => setGoalTitle(e.target.value)}
              placeholder="Goal name"
            />
            <select
              value={goalMetric}
              onChange={(e) => setGoalMetric(e.target.value)}
            >
              <option value="sessions_per_week">Sessions / week</option>
              <option value="minutes_per_week">Minutes / week</option>
              <option value="exercise_weight_kg">Exercise weight</option>
            </select>
            <input
              required
              type="number"
              min="0.1"
              step="0.1"
              value={goalTarget}
              onChange={(e) => setGoalTarget(e.target.value)}
              placeholder="Target"
            />
            {goalMetric === "exercise_weight_kg" && (
              <input
                required
                list="exercise-options"
                value={goalExercise}
                onChange={(e) => setGoalExercise(e.target.value)}
                placeholder="Exercise"
              />
            )}
            <button className="primary" disabled={saving}>
              Set goal
            </button>
          </form>
        </div>
      </section>
      <section className="workout-main-grid">
        <form
          className={
            "card workout-log-form scope-history" +
            (showLogForm ? "" : " is-collapsed")
          }
          onSubmit={submitLog}
        >
          <div className="card-head">
            <div>
              <p className="eyebrow">Session logging</p>
              <h3>Log workout</h3>
            </div>
            <button
              type="button"
              className="ghost"
              onClick={() => setLogRows((rows) => [...rows, emptyLog()])}
            >
              Add exercise
            </button>
          </div>
          <div className="workout-form-grid">
            <label>
              Title
              <input
                required
                value={logTitle}
                onChange={(e) => setLogTitle(e.target.value)}
              />
            </label>
            <label>
              Plan
              <select
                value={logPlan}
                onChange={(e) => setLogPlan(e.target.value)}
              >
                <option value="">No plan</option>
                {plans.map((x) => (
                  <option value={x.id} key={x.id}>
                    {x.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Started
              <input
                required
                type="datetime-local"
                value={logStarted}
                onChange={(e) => setLogStarted(e.target.value)}
              />
            </label>
            <label>
              Ended (optional)
              <input
                type="datetime-local"
                value={logEnded}
                onChange={(e) => setLogEnded(e.target.value)}
              />
            </label>
          </div>
          <datalist id="exercise-options">
            {exercises.map((x) => (
              <option key={x.id} value={x.name} />
            ))}
          </datalist>
          <div className="workout-log-rows">
            {logRows.map((row, index) => (
              <div className="workout-log-row" key={index}>
                <input
                  required
                  list="exercise-options"
                  value={row.name}
                  onChange={(e) => updateRow(index, "name", e.target.value)}
                  placeholder="Exercise"
                />
                <input
                  type="number"
                  min="1"
                  value={row.sets ?? ""}
                  onChange={(e) => updateRow(index, "sets", e.target.value)}
                  placeholder="Sets"
                />
                <input
                  type="number"
                  min="0"
                  value={row.reps ?? ""}
                  onChange={(e) => updateRow(index, "reps", e.target.value)}
                  placeholder="Reps"
                />
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={row.weight_kg ?? ""}
                  onChange={(e) =>
                    updateRow(index, "weight_kg", e.target.value)
                  }
                  placeholder="kg"
                />
                <input
                  type="number"
                  min="0"
                  value={row.duration_seconds ?? ""}
                  onChange={(e) =>
                    updateRow(index, "duration_seconds", e.target.value)
                  }
                  placeholder="Seconds"
                />
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={row.rpe ?? ""}
                  onChange={(e) => updateRow(index, "rpe", e.target.value)}
                  placeholder="RPE"
                />
                <button
                  type="button"
                  className="ghost"
                  onClick={() =>
                    setLogRows((rows) => rows.filter((_, i) => i !== index))
                  }
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          <label>
            Notes
            <textarea
              rows={3}
              value={logNotes}
              onChange={(e) => setLogNotes(e.target.value)}
              placeholder="How it felt, substitutions, minor acts of heroism…"
            />
          </label>
          <div className="workout-form-actions">
            <button className="primary" disabled={saving}>
              {saving ? "Saving…" : "Log completed workout"}
            </button>
            <button
              type="button"
              className="ghost"
              disabled={saving}
              onClick={() => void startAdHocSession()}
            >
              Start live session
            </button>
          </div>
        </form>
        <form
          className={
            "card workout-plan-form scope-plans" +
            (showPlanForm ? "" : " is-collapsed")
          }
          onSubmit={submitPlan}
        >
          <div className="card-head">
            <div>
              <p className="eyebrow">Plan builder</p>
              <h3>Build named sessions</h3>
            </div>
            <button
              type="button"
              className="ghost"
              onClick={() =>
                setPlanSessions((items) => [
                  ...items,
                  emptyPlanSession(items.length),
                ])
              }
            >
              Add session
            </button>
          </div>
          <label>
            Plan name
            <input
              required
              value={planTitle}
              onChange={(e) => setPlanTitle(e.target.value)}
              placeholder="Three-day strength"
            />
          </label>
          <label>
            Goal
            <input
              value={planGoal}
              onChange={(e) => setPlanGoal(e.target.value)}
              placeholder="Build strength, run 5K…"
            />
          </label>
          <label>
            Description
            <textarea
              rows={2}
              value={planDescription}
              onChange={(e) => setPlanDescription(e.target.value)}
            />
          </label>
          <div className="plan-session-builder">
            {planSessions.map((session, sessionIndex) => (
              <section key={sessionIndex}>
                <div className="plan-session-head">
                  <input
                    required
                    value={session.name}
                    onChange={(e) =>
                      setPlanSessions((items) =>
                        items.map((item, i) =>
                          i === sessionIndex
                            ? { ...item, name: e.target.value }
                            : item,
                        ),
                      )
                    }
                    aria-label="Session name"
                  />
                  <select
                    value={session.guidance_mode}
                    onChange={(e) =>
                      setPlanSessions((items) =>
                        items.map((item, i) =>
                          i === sessionIndex
                            ? {
                                ...item,
                                guidance_mode: e.target.value as
                                  | "checklist"
                                  | "guided",
                              }
                            : item,
                        ),
                      )
                    }
                  >
                    <option value="checklist">Checklist</option>
                    <option value="guided">Guided</option>
                  </select>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() =>
                      setPlanSessions((items) =>
                        items.filter((_, i) => i !== sessionIndex),
                      )
                    }
                  >
                    Remove
                  </button>
                </div>
                {session.exercises.map((row, rowIndex) => (
                  <div className="plan-exercise-row" key={rowIndex}>
                    <input
                      required
                      list="exercise-options"
                      value={row.name}
                      onChange={(e) =>
                        updatePlanExercise(
                          sessionIndex,
                          rowIndex,
                          "name",
                          e.target.value,
                        )
                      }
                      placeholder="Exercise"
                    />
                    <select
                      value={row.phase_type || "reps"}
                      onChange={(e) =>
                        updatePlanExercise(
                          sessionIndex,
                          rowIndex,
                          "phase_type",
                          e.target.value,
                        )
                      }
                    >
                      <option value="reps">Reps</option>
                      <option value="timed">Timed</option>
                    </select>
                    <input
                      type="number"
                      min="1"
                      value={row.sets ?? ""}
                      onChange={(e) =>
                        updatePlanExercise(
                          sessionIndex,
                          rowIndex,
                          "sets",
                          e.target.value,
                        )
                      }
                      placeholder="Sets"
                    />
                    <input
                      type="number"
                      min="0"
                      value={row.reps ?? ""}
                      onChange={(e) =>
                        updatePlanExercise(
                          sessionIndex,
                          rowIndex,
                          "reps",
                          e.target.value,
                        )
                      }
                      placeholder="Reps"
                    />
                    <input
                      type="number"
                      min="0"
                      value={row.duration_seconds ?? ""}
                      onChange={(e) =>
                        updatePlanExercise(
                          sessionIndex,
                          rowIndex,
                          "duration_seconds",
                          e.target.value,
                        )
                      }
                      placeholder="Seconds"
                    />
                    <input
                      type="number"
                      min="0"
                      value={row.rest_seconds ?? ""}
                      onChange={(e) =>
                        updatePlanExercise(
                          sessionIndex,
                          rowIndex,
                          "rest_seconds",
                          e.target.value,
                        )
                      }
                      placeholder="Rest (optional)"
                    />
                    <input
                      value={row.block_name || ""}
                      onChange={(e) =>
                        updatePlanExercise(
                          sessionIndex,
                          rowIndex,
                          "block_name",
                          e.target.value,
                        )
                      }
                      placeholder="Cycle name"
                    />
                    <input
                      type="number"
                      min="1"
                      value={row.cycle_count ?? 1}
                      onChange={(e) =>
                        updatePlanExercise(
                          sessionIndex,
                          rowIndex,
                          "cycle_count",
                          e.target.value,
                        )
                      }
                      title="Cycle rounds"
                    />
                    <button
                      type="button"
                      className="ghost"
                      onClick={() =>
                        setPlanSessions((items) =>
                          items.map((item, i) =>
                            i === sessionIndex
                              ? {
                                  ...item,
                                  exercises: item.exercises.filter(
                                    (_, j) => j !== rowIndex,
                                  ),
                                }
                              : item,
                          ),
                        )
                      }
                    >
                      ×
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="ghost"
                  onClick={() =>
                    setPlanSessions((items) =>
                      items.map((item, i) =>
                        i === sessionIndex
                          ? {
                              ...item,
                              exercises: [...item.exercises, emptyLog()],
                            }
                          : item,
                      ),
                    )
                  }
                >
                  Add exercise
                </button>
              </section>
            ))}
          </div>
          <button className="primary" disabled={saving}>
            Save workout plan
          </button>
        </form>
      </section>
      <section className="workout-library-grid">
        <div className="card scope-history">
          <div className="card-head">
            <div>
              <p className="eyebrow">History</p>
              <h3>Recent sessions</h3>
            </div>
          </div>
          <div className="workout-history">
            {sessions.length ? (
              sessions.slice(0, 20).map((session) => (
                <article
                  key={session.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelectedSession(session)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") setSelectedSession(session);
                  }}
                >
                  <time>{new Date(session.started_at).toLocaleString()}</time>
                  <div>
                    <strong>{session.title || "Workout"}</strong>
                    <span>
                      {session.exercises
                        .map((x) => x.exercise.name)
                        .join(" · ")}
                    </span>
                  </div>
                  <b>{durationText(session.duration_seconds)}</b>
                  <button
                    type="button"
                    className="ghost pill-action"
                    disabled={saving}
                    onClick={(e) => {
                      e.stopPropagation();
                      void removeSession(session);
                    }}
                  >
                    Delete
                  </button>
                </article>
              ))
            ) : (
              <p className="muted">No workouts logged yet.</p>
            )}
          </div>
        </div>
        <div className="card scope-exercises">
          <div className="card-head">
            <div>
              <p className="eyebrow">Directory</p>
              <h3>Exercises</h3>
            </div>
            <span className="muted">{exercises.length}</span>
          </div>
          <form
            className={
              "workout-directory-form" +
              (showExerciseForm ? "" : " is-collapsed")
            }
            onSubmit={submitExercise}
          >
            <input
              required
              value={exerciseName}
              onChange={(e) => setExerciseName(e.target.value)}
              placeholder="Exercise name"
            />
            <input
              value={exerciseGroup}
              onChange={(e) => setExerciseGroup(e.target.value)}
              placeholder="Muscle group"
            />
            <input
              value={exerciseEquipment}
              onChange={(e) => setExerciseEquipment(e.target.value)}
              placeholder="Equipment"
            />
            <button className="primary" disabled={saving}>
              Add
            </button>
          </form>
          <div className="workout-exercise-list">
            {exercises.map((x) => (
              <article
                key={x.id}
                role="button"
                tabIndex={0}
                onClick={() => void openExerciseDetails(x)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void openExerciseDetails(x);
                }}
              >
                <div>
                  <strong>{x.name}</strong>
                  <span>
                    {[x.muscle_group, x.equipment]
                      .filter(Boolean)
                      .join(" · ") || "Uncategorised"}
                  </span>
                </div>
                <button
                  type="button"
                  className="ghost pill-action"
                  disabled={saving}
                  onClick={(e) => {
                    e.stopPropagation();
                    void removeExercise(x);
                  }}
                >
                  Delete
                </button>
              </article>
            ))}
          </div>
        </div>
      </section>
      <section className="card workout-plans scope-plans">
        <div className="card-head">
          <div>
            <p className="eyebrow">Saved programming</p>
            <h3>Workout plans</h3>
          </div>
        </div>
        <div>
          {plans.length ? (
            plans.map((plan) => (
              <article
                key={plan.id}
                role="button"
                tabIndex={0}
                onClick={() => setSelectedPlan(plan)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") setSelectedPlan(plan);
                }}
              >
                <header>
                  <div>
                    <strong>{plan.title}</strong>
                    <span>
                      {plan.goal || plan.description || "No stated goal"}
                    </span>
                  </div>
                  <div className="workout-plan-actions">
                    <b>{plan.source}</b>
                    <button
                      type="button"
                      className="ghost pill-action"
                      disabled={saving}
                      onClick={(e) => {
                        e.stopPropagation();
                        void removePlan(plan);
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </header>
                <ol>
                  {plan.exercises.map((row) => (
                    <li key={row.id}>
                      <span>{row.exercise.name}</span>
                      <small>
                        {[
                          row.sets && `${row.sets} sets`,
                          row.reps && `${row.reps} reps`,
                          row.weight_kg && `${row.weight_kg} kg`,
                          row.duration_seconds && `${row.duration_seconds}s`,
                        ]
                          .filter(Boolean)
                          .join(" · ") || "As needed"}
                      </small>
                    </li>
                  ))}
                </ol>
              </article>
            ))
          ) : (
            <p className="muted">No plans saved yet.</p>
          )}
        </div>
      </section>
      {selectedPlan && (
        <div
          className="workout-modal-backdrop"
          onClick={() => setSelectedPlan(null)}
        >
          <section
            className="workout-detail-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <header>
              <div>
                <p className="eyebrow">Workout plan</p>
                <h3>Edit plan details</h3>
              </div>
              <button
                type="button"
                className="ghost"
                onClick={() => setSelectedPlan(null)}
              >
                Close
              </button>
            </header>
            <label>
              Name
              <input
                value={selectedPlan.title}
                onChange={(e) =>
                  setSelectedPlan({ ...selectedPlan, title: e.target.value })
                }
              />
            </label>
            <label>
              Goal
              <input
                value={selectedPlan.goal}
                onChange={(e) =>
                  setSelectedPlan({ ...selectedPlan, goal: e.target.value })
                }
              />
            </label>
            <label>
              Description
              <textarea
                rows={4}
                value={selectedPlan.description}
                onChange={(e) =>
                  setSelectedPlan({
                    ...selectedPlan,
                    description: e.target.value,
                  })
                }
              />
            </label>
            <label className="workout-check">
              <input
                type="checkbox"
                checked={selectedPlan.active}
                onChange={(e) =>
                  setSelectedPlan({ ...selectedPlan, active: e.target.checked })
                }
              />{" "}
              Active plan
            </label>
            <PlanContents plan={selectedPlan} />
            <footer>
              <button
                type="button"
                className="ghost"
                onClick={() => setSelectedPlan(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="primary"
                disabled={saving}
                onClick={() => void saveSelectedPlan()}
              >
                Save changes
              </button>
            </footer>
          </section>
        </div>
      )}
      {selectedSession && (
        <div
          className="workout-modal-backdrop"
          onClick={() => setSelectedSession(null)}
        >
          <section
            className="workout-detail-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <header>
              <div>
                <p className="eyebrow">Workout session</p>
                <h3>Edit session</h3>
              </div>
              <button
                type="button"
                className="ghost"
                onClick={() => setSelectedSession(null)}
              >
                Close
              </button>
            </header>
            <label>
              Title
              <input
                value={selectedSession.title}
                onChange={(e) =>
                  setSelectedSession({
                    ...selectedSession,
                    title: e.target.value,
                  })
                }
              />
            </label>
            <label>
              Notes
              <textarea
                rows={4}
                value={selectedSession.notes}
                onChange={(e) =>
                  setSelectedSession({
                    ...selectedSession,
                    notes: e.target.value,
                  })
                }
              />
            </label>
            <div className="workout-detail-list">
              {selectedSession.exercises.map((row) => (
                <article key={row.id}>
                  <strong>{row.exercise.name}</strong>
                  <span>
                    {row.set_logs?.filter((item) => item.status === "completed")
                      .length || 0}{" "}
                    / {row.set_logs?.length || row.sets || 1} sets complete
                  </span>
                </article>
              ))}
            </div>
            <footer>
              <button
                type="button"
                className="ghost"
                onClick={() => setSelectedSession(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="primary"
                disabled={saving}
                onClick={() => void saveSelectedSession()}
              >
                Save changes
              </button>
            </footer>
          </section>
        </div>
      )}
      {selectedExercise && (
        <div
          className="workout-modal-backdrop"
          onClick={() => setSelectedExercise(null)}
        >
          <section
            className="workout-detail-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <header>
              <div>
                <p className="eyebrow">Exercise directory</p>
                <h3>{selectedExercise.name}</h3>
              </div>
              <button
                type="button"
                className="ghost"
                onClick={() => setSelectedExercise(null)}
              >
                Close
              </button>
            </header>
            {enrichmentLoading && <div className="workout-enrichment-loading">Finding technique details and building the demo…</div>}
            {selectedExercise.demo_media_url && (
              <figure className="workout-exercise-demo">
                <img src={selectedExercise.demo_media_url} alt={`${selectedExercise.name} technique demonstration`} />
                <figcaption>Looped technique demonstration · cached by Corv</figcaption>
              </figure>
            )}
            {selectedExercise.enrichment_error && !enrichmentLoading && (
              <div className="workout-enrichment-warning"><span>{selectedExercise.enrichment_error}</span><button type="button" className="ghost" onClick={() => void openExerciseDetails(selectedExercise,true)}>Try again</button></div>
            )}
            {!!selectedExercise.enrichment_data.primary_muscles?.length && (
              <div className="workout-technique-facts">
                <span><small>Level</small>{selectedExercise.enrichment_data.level || "Any"}</span>
                <span><small>Primary muscles</small>{selectedExercise.enrichment_data.primary_muscles.join(", ")}</span>
                <span><small>Secondary muscles</small>{selectedExercise.enrichment_data.secondary_muscles?.join(", ") || "—"}</span>
              </div>
            )}
            <label>
              Name
              <input
                value={selectedExercise.name}
                onChange={(e) =>
                  setSelectedExercise({
                    ...selectedExercise,
                    name: e.target.value,
                  })
                }
              />
            </label>
            <div className="workout-detail-grid">
              <label>
                Category
                <input
                  value={selectedExercise.category}
                  onChange={(e) =>
                    setSelectedExercise({
                      ...selectedExercise,
                      category: e.target.value,
                    })
                  }
                />
              </label>
              <label>
                Muscle group
                <input
                  value={selectedExercise.muscle_group}
                  onChange={(e) =>
                    setSelectedExercise({
                      ...selectedExercise,
                      muscle_group: e.target.value,
                    })
                  }
                />
              </label>
              <label>
                Equipment
                <input
                  value={selectedExercise.equipment}
                  onChange={(e) =>
                    setSelectedExercise({
                      ...selectedExercise,
                      equipment: e.target.value,
                    })
                  }
                />
              </label>
            </div>
            <label>
              Instructions
              <textarea
                rows={5}
                value={selectedExercise.instructions}
                onChange={(e) =>
                  setSelectedExercise({
                    ...selectedExercise,
                    instructions: e.target.value,
                  })
                }
              />
            </label>
            {selectedExercise.enriched_at && <div className="workout-enrichment-source"><span>Saved locally {new Date(selectedExercise.enriched_at).toLocaleString()}</span>{selectedExercise.enrichment_data.source_url && <a href={selectedExercise.enrichment_data.source_url} target="_blank" rel="noreferrer">{selectedExercise.enrichment_data.source_name || "Exercise source"} · {selectedExercise.enrichment_data.license}</a>}<button type="button" className="ghost" disabled={enrichmentLoading} onClick={() => void openExerciseDetails(selectedExercise,true)}>Refresh details</button></div>}
            <footer>
              <button
                type="button"
                className="ghost"
                onClick={() => setSelectedExercise(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="primary"
                disabled={saving}
                onClick={() => void saveSelectedExercise()}
              >
                Save changes
              </button>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}
