import VscodeConnectModal from "./VscodeConnectModal";

export default function VscodeGetStartedCard({
  onInstall,
  onViewDocs,
  onConnect,
  connectState,
  connectError,
  onApproved,
  onRetry,
  workspaceOptions = [],
  selectedWorkspace = "",
  onWorkspaceChange = () => {},
  onSaveWorkspace = () => {},
  savingWorkspace = false,
  showWorkspacePicker = false,
  comingSoon = false,
  preferenceMessage = "",
}) {
  const renderWorkspace = () => {
    if (!showWorkspacePicker) {
      return (
        <p className="vscode-muted">
          We’ll use your current workspace. If you join more workspaces later, you can
          set a default here.
        </p>
      );
    }

    return (
      <div className="vscode-workspace-row">
        <select
          value={selectedWorkspace}
          onChange={(e) => onWorkspaceChange(e.target.value)}
          className="vscode-select"
        >
          {workspaceOptions.map((ws) => {
            const value = ws.id || ws.workspace_id || ws.value || ws.slug || ws;
            const optionValue = value != null ? String(value) : "";
            const label = ws.name || ws.title || ws.label || ws.org_name || optionValue;
            return (
              <option key={optionValue} value={optionValue}>
                {label}
              </option>
            );
          })}
        </select>
        <button className="btn primary" onClick={onSaveWorkspace} disabled={savingWorkspace}>
          {savingWorkspace ? "Saving…" : "Save"}
        </button>
      </div>
    );
  };

  return (
    <div className="vscode-card glass">
      <div className="vscode-card-header">
        <div>
          <div className="eyebrow">Quick start</div>
          <h3>Get started</h3>
          <p className="vscode-muted">
            Install, connect, and optionally set a default workspace for your editor.
          </p>
        </div>
        {comingSoon && <div className="vscode-pill subtle">Coming soon</div>}
      </div>

      <div className="vscode-step">
        <div className="vscode-step-number">1</div>
        <div className="vscode-step-body">
          <div className="vscode-step-header">
            <h4>Install</h4>
            <p className="vscode-muted">Add the Parallel extension from the VS Code Marketplace.</p>
          </div>
          <div className="vscode-actions">
            <button className="btn primary" onClick={onInstall}>
              Install extension
            </button>
            <button className="btn ghost" onClick={onViewDocs}>
              View docs
            </button>
          </div>
        </div>
        {preferenceMessage && <div className="vscode-success-banner">{preferenceMessage}</div>}
      </div>

      <div className="vscode-step">
        <div className="vscode-step-number">2</div>
        <div className="vscode-step-body">
          <div className="vscode-step-header">
            <h4>Connect</h4>
            <p className="vscode-muted">
              Sign in with your browser and we’ll redirect you back to VS Code.
            </p>
          </div>

          <div className="vscode-connect-grid">
            <div className="vscode-subcard">
              <div className="vscode-subcard-head">
                <div>
                  <div className="eyebrow">Recommended</div>
                  <h5>Connect from VS Code</h5>
                </div>
              </div>
              <p className="vscode-muted">
                Open VS Code, run "Parallel: Sign In" from the Command Palette, and approve the request in your browser.
                We’ll send you back to VS Code automatically.
              </p>
              <div className="vscode-actions">
                <button
                  className="btn primary"
                  onClick={onConnect}
                  disabled={connectState === "starting" || connectState === "polling"}
                >
                  {connectState === "starting" || connectState === "polling"
                    ? "Waiting for approval..."
                    : "I've started from VS Code"}
                </button>
                <button className="btn ghost" onClick={onApproved}>
                  I approved in browser
                </button>
              </div>
              <VscodeConnectModal
                state={connectState}
                error={connectError}
                onRetry={onRetry}
                onApproved={onApproved}
              />
            </div>
          </div>
        </div>
      </div>

      <div className="vscode-step">
        <div className="vscode-step-number">3</div>
        <div className="vscode-step-body">
          <div className="vscode-step-header">
            <h4>Default workspace</h4>
            <p className="vscode-muted">
              Choose where VS Code sessions attach by default (optional).
            </p>
          </div>
          {renderWorkspace()}
        </div>
      </div>
    </div>
  );
}
