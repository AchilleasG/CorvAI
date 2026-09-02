import "./workspace-navigation.css";
import corvLogo from "./assets/corv-logo.png";

export type WorkspaceSection =
  | "chat"
  | "notes"
  | "calendar"
  | "scheduler"
  | "messages"
  | "calls"
  | "study"
  | "workout"
  | "ssh"
  | "coding"
  | "files"
  | "settings";

const WORKSPACE_SECTIONS: ReadonlyArray<{ key: WorkspaceSection; label: string }> = [
  { key: "chat", label: "Chat" },
  { key: "notes", label: "Notes" },
  { key: "calendar", label: "Calendar" },
  { key: "scheduler", label: "Scheduler" },
  { key: "messages", label: "Messages" },
  { key: "calls", label: "Calls" },
  { key: "study", label: "Study" },
  { key: "workout", label: "Workout" },
  { key: "ssh", label: "SSH" },
  { key: "coding", label: "Coding" },
  { key: "files", label: "Files" },
  { key: "settings", label: "Settings" },
];

type WorkspaceNavigationProps = {
  activeSection: WorkspaceSection;
  sidebarOpen: boolean;
  isMobileViewport: boolean;
  onNavigate: (section: WorkspaceSection) => void;
  onToggleSidebar: () => void;
  onNewChat: () => void;
};

export default function WorkspaceNavigation({
  activeSection,
  sidebarOpen,
  isMobileViewport,
  onNavigate,
  onToggleSidebar,
  onNewChat,
}: WorkspaceNavigationProps) {
  const activeLabel = WORKSPACE_SECTIONS.find((item) => item.key === activeSection)?.label || "Workspace";

  return (
    <nav className="shell-topbar workspace-navigation" aria-label="Workspace navigation">
      <div className="shell-topbar-row">
        <button className="ghost shell-menu-button" type="button" onClick={onToggleSidebar}>
          {sidebarOpen && isMobileViewport ? "Close" : "Menu"}
        </button>
        <div className="shell-brand-area">
          <img className="shell-brand-logo" src={corvLogo} alt="Corv" />
          <div className="shell-topbar-copy">
            <p className="eyebrow">Workspace</p>
            <h2>{activeLabel}</h2>
          </div>
        </div>
        <button className="ghost shell-utility-button" type="button" onClick={onNewChat}>
          New chat
        </button>
      </div>
      <div className="shell-tabstrip" role="tablist" aria-label="Workspace sections">
        {WORKSPACE_SECTIONS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={activeSection === key}
            className={`shell-tab ${activeSection === key ? "active" : ""}`}
            onClick={() => onNavigate(key)}
          >
            {label}
          </button>
        ))}
      </div>
    </nav>
  );
}
