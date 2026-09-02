type LogItem = {
  key: string;
  kind: "command" | "message" | "note" | "raw";
  title: string;
  status?: string;
  command?: string;
  output?: string;
  text?: string;
  exitCode?: number | null;
};

type LogSection = { title: string; items: LogItem[] };

function friendlySection(value: string): string {
  const parts = value.split(" · ");
  if (parts.length < 2) return value;
  const date = parts.at(-1);
  if (date && !Number.isNaN(Date.parse(date))) parts[parts.length - 1] = new Date(date).toLocaleString();
  return parts.join(" · ");
}

function agentText(value: unknown): { title: string; text: string; status?: string } {
  const raw = String(value || "").trim();
  try {
    const parsed = JSON.parse(raw) as { status?: string; summary?: string; question?: string };
    return {
      title: parsed.status === "needs_input" ? "Decision needed" : parsed.status === "action" ? "Browser decision" : "Codex report",
      text: [parsed.summary, parsed.question].filter(Boolean).join("\n\n") || raw,
      status: parsed.status,
    };
  } catch {
    return { title: "Codex message", text: raw };
  }
}

function parseLogs(content: string): LogSection[] {
  const sections: LogSection[] = [];
  let section: LogSection = { title: "Session", items: [] };
  sections.push(section);
  const indexed = new Map<string, LogItem>();

  for (const [lineIndex, line] of content.split("\n").entries()) {
    const heading = line.match(/^===== (.+) =====$/);
    if (heading) {
      section = { title: friendlySection(heading[1]), items: [] };
      sections.push(section);
      continue;
    }
    if (!line.trim()) continue;
    if (line === "[waiting for output…]") {
      section.items.push({ key: `waiting-${lineIndex}`, kind: "note", title: "Waiting for Codex output…", status: "in_progress" });
      continue;
    }
    let event: any;
    try { event = JSON.parse(line); }
    catch {
      const previous = section.items.at(-1);
      if (previous?.kind === "raw") previous.text = `${previous.text || ""}\n${line}`;
      else section.items.push({ key: `raw-${lineIndex}`, kind: "raw", title: "Output", text: line });
      continue;
    }

    const eventType = String(event.type || "event");
    const item = event.item || {};
    const itemId = String(item.id || `${eventType}-${lineIndex}`);
    const indexedKey = `${sections.length}:${itemId}`;

    if (item.type === "command_execution") {
      const existing = indexed.get(indexedKey);
      const entry: LogItem = existing || {
        key: indexedKey,
        kind: "command",
        title: "Command",
      };
      entry.command = String(item.command || entry.command || "");
      entry.output = String(item.aggregated_output || entry.output || "");
      entry.status = String(item.status || (eventType === "item.started" ? "in_progress" : "completed"));
      entry.exitCode = item.exit_code ?? entry.exitCode ?? null;
      if (!existing) {
        indexed.set(indexedKey, entry);
        section.items.push(entry);
      }
      continue;
    }

    if (item.type === "agent_message") {
      const report = agentText(item.text);
      section.items.push({ key: indexedKey, kind: "message", ...report });
      continue;
    }

    if (item.type === "reasoning") {
      const text = String(item.text || item.summary || "").trim();
      if (text) section.items.push({ key: indexedKey, kind: "note", title: "Working", text, status: eventType === "item.started" ? "in_progress" : "completed" });
      continue;
    }

    if (item.type === "file_change") {
      const changes = Array.isArray(item.changes) ? item.changes.map((change: any) => `${change.kind || "changed"}: ${change.path || "file"}`).join("\n") : "Files updated";
      section.items.push({ key: indexedKey, kind: "note", title: "File changes", text: changes, status: item.status || "completed" });
      continue;
    }

    if (eventType === "browser.action.completed") {
      const action = String(event.action || "action").replaceAll("_", " ");
      const details = [event.url, event.error].filter(Boolean).join("\n");
      section.items.push({
        key: indexedKey,
        kind: "note",
        title: `Browser · ${action}`,
        text: details,
        status: event.success ? "completed" : "failed",
      });
      continue;
    }

    if (eventType === "thread.started") {
      section.items.push({ key: indexedKey, kind: "note", title: "Codex thread started", text: event.thread_id || "", status: "completed" });
    } else if (eventType === "turn.failed" || eventType === "error") {
      section.items.push({ key: indexedKey, kind: "message", title: "Codex error", text: String(event.message || event.error?.message || "The turn failed"), status: "failed" });
    }
  }
  return sections.filter((value, index) => value.items.length || index > 0);
}

function stateLabel(item: LogItem): string {
  if (item.kind === "command" && item.exitCode !== null && item.exitCode !== undefined) {
    return item.exitCode === 0 ? "Succeeded" : `Failed · exit ${item.exitCode}`;
  }
  return (item.status || "completed").replace("_", " ");
}

export default function CodingLogViewer({ content }: { content: string }) {
  const sections = parseLogs(content);
  return <div className="coding-log-rendered">
    {sections.map((section, sectionIndex) => <section className="coding-log-section" key={`${section.title}-${sectionIndex}`}>
      <h4>{section.title}</h4>
      {section.items.map((item) => {
        const failed = item.status === "failed" || (item.exitCode !== null && item.exitCode !== undefined && item.exitCode !== 0);
        const running = item.status === "in_progress";
        return <article className={`coding-log-entry ${item.kind} ${failed ? "failed" : running ? "running" : "completed"}`} key={item.key}>
          <header><strong>{item.title}</strong><span>{stateLabel(item)}</span></header>
          {item.command && <code className="coding-log-command">{item.command}</code>}
          {item.output && <details open={failed || running}><summary>{failed ? "Error output" : "Command output"}</summary><pre>{item.output}</pre></details>}
          {item.text && <p>{item.text}</p>}
        </article>;
      })}
    </section>)}
  </div>;
}
