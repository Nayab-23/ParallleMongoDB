export default function VscodeConnectModal({
  state = "idle",
  error = "",
  onRetry = () => {},
  onApproved = () => {},
}) {
  if (state === "idle") return null;

  const waiting = state === "starting" || state === "polling";
  const timedOut = state === "timeout";
  const connected = state === "connected";

  return (
    <div className="vscode-connect-panel">
      {waiting && (
        <div className="vscode-waiting">
          <span className="spinner" aria-hidden />
          <div>
            <div className="vscode-strong">Waiting for approval…</div>
            <div className="vscode-muted">Keep the browser tab open and approve access.</div>
          </div>
        </div>
      )}

      {connected && (
        <div className="vscode-success">
          <span role="img" aria-label="check">
            ✅
          </span>
          <div>
            <div className="vscode-strong">Connected</div>
            <div className="vscode-muted">Your editor is linked. You can close this tab.</div>
          </div>
        </div>
      )}

      {timedOut && (
        <div className="vscode-waiting">
          <div>
            <div className="vscode-strong">Still waiting?</div>
            <div className="vscode-muted">
              We didn’t see the approval. Click retry or try again.
            </div>
          </div>
          <div className="vscode-actions">
            <button className="btn ghost" onClick={onApproved}>
              Check again
            </button>
            <button className="btn" onClick={onRetry}>
              Retry
            </button>
          </div>
        </div>
      )}

      {error && <div className="vscode-inline-error">{error}</div>}
    </div>
  );
}
