import React, { useCallback, useEffect, useRef, useState } from "react";
import { getTimelineDebug, triggerTimelineRefresh, formatAdminError, getTimelineStageDetails } from "../../../api/adminApi";
import { API_BASE_URL } from "../../../config";
import UserSelector from "../UserSelector";
import StageFlowDiagram from "./StageFlowDiagram";
import StageDetailsPanel from "./StageDetailsPanel";
import AIProcessingPanel from "./AIProcessingPanel";
import GuardrailsPanel from "./GuardrailsPanel";
import EmailStage0Panel from "./EmailStage0Panel";
import BucketConsistencyBanner from "./BucketConsistencyBanner";
import LogViewer from "../shared/LogViewer";
import MetricCard from "../shared/MetricCard";
import "./Timeline.css";

const TimelineDebugDashboard = () => {
  const [selectedUser, setSelectedUser] = useState("");
  const [timelineData, setTimelineData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedStage, setSelectedStage] = useState(null);
  const [logs, setLogs] = useState([]);
  const [error, setError] = useState(null);
  const [contractError, setContractError] = useState(null);
  const [legacyInfo, setLegacyInfo] = useState(null);
  const [lastMeta, setLastMeta] = useState({ request_id: null, duration_ms: null });
  const [snapshot, setSnapshot] = useState(null);
  const [probeLoading, setProbeLoading] = useState(false);
  const [probeResult, setProbeResult] = useState(null);
  const [probeError, setProbeError] = useState(null);
  const [polling, setPolling] = useState(false);
  const [pollAttempts, setPollAttempts] = useState(0);
  const [stageDetail, setStageDetail] = useState(null);
  const [stageDetailPage, setStageDetailPage] = useState(1);
  const [stageDetailLoading, setStageDetailLoading] = useState(false);
  const [stageDetailError, setStageDetailError] = useState(null);
  const [stageDetailCached, setStageDetailCached] = useState(false);
  const stageCacheRef = useRef(new Map());
  const inFlightStageRef = useRef(new Map());
  const controllerRef = useRef(null);
  const seqRef = useRef(0);

  useEffect(() => {
    if (selectedUser) {
      fetchTimelineData();
    }
    setSelectedStage(null);
    setStageDetail(null);
    setStageDetailPage(1);
    setStageDetailError(null);
    setContractError(null);
  }, [selectedUser]);

  const fetchTimelineData = async () => {
    if (controllerRef.current) controllerRef.current.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const seq = ++seqRef.current;

    setLoading(true);
    setError(null);
    setContractError(null);
    try {
      const resp = await getTimelineDebug(selectedUser);
      if (seq !== seqRef.current) return;
      setLegacyInfo(resp?.debug?.legacy ? { request_id: resp?.request_id, status: resp?.status, endpoint: resp?.debug?.url } : null);
      setLastMeta({ request_id: resp?.request_id, duration_ms: resp?.duration_ms });
      if (!resp?.success) {
        setError({
          code: resp?.error?.code,
          message: resp?.error?.message || "Failed to load timeline data",
          details: resp?.error?.details || resp?.error,
          request_id: resp?.request_id,
          duration_ms: resp?.duration_ms,
          status: resp?.status,
        });
        setTimelineData(null);
        return;
      }

      const payload = resp?.data ?? {};
      const stagesArray = Array.isArray(payload.stages) ? payload.stages : [];
      const requiredOk =
        payload.user &&
        payload.user_id &&
        payload.data_source &&
        payload.pipeline_totals &&
        payload.current_timeline &&
        Array.isArray(payload.stages);
      if (!requiredOk) {
        console.error("[Admin/TimelineDebug] Contract mismatch", {
          request_id: resp?.request_id,
          endpoint: resp?.debug?.url,
          payload,
        });
        setContractError({
          message: "Contract mismatch",
          request_id: resp?.request_id,
          duration_ms: resp?.duration_ms,
        });
        setTimelineData(null);
        return;
      }

      const stageMap = stagesArray.reduce((acc, stage) => {
        if (!stage?.stage_key) return acc;
        acc[stage.stage_key] = {
          ...stage,
          total_items: stage?.output_count ?? stage?.input_count ?? null,
          items_out: stage?.output_count ?? null,
          items_in: stage?.input_count ?? null,
          removed: stage?.removed_count ?? null,
        };
        return acc;
      }, {});

      const normalized = {
        ...payload,
        stages: stageMap,
        stages_list: stagesArray,
      };
      setTimelineData(normalized);
      setSnapshot(resp?.debug?.timeline_snapshot || null);
      setLogs(Array.isArray(payload.logs) ? payload.logs : []);
    } catch (err) {
      console.error("Failed to fetch timeline data:", err);
      if (seq !== seqRef.current) return;
      setError({
        message: err?.message || "Failed to load timeline data",
        status: err?.status,
      });
      setTimelineData(null);
    } finally {
      if (seq === seqRef.current) {
        setLoading(false);
      }
    }
  };

  const triggerRefresh = async () => {
    if (!selectedUser) return;
    setRefreshing(true);
    setError(null);
    setPolling(true);
    setPollAttempts(0);
    try {
      await triggerTimelineRefresh(selectedUser);
      pollForUpdates();
    } catch (err) {
      console.error("Failed to trigger refresh:", err);
      setError(err);
    } finally {
      setRefreshing(false);
    }
  };

  const pollForUpdates = async () => {
    let attempts = 0;
    const startRefresh = timelineData?.last_refresh;
    while (attempts < 15) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      attempts += 1;
      setPollAttempts(attempts);
      try {
        const resp = await getTimelineDebug(selectedUser);
        setLegacyInfo(resp?.debug?.legacy ? { request_id: resp?.request_id, status: resp?.status, endpoint: resp?.debug?.url } : null);
        setLastMeta({ request_id: resp?.request_id, duration_ms: resp?.duration_ms });
        const payload = resp?.data ?? {};
        const stagesArray = Array.isArray(payload.stages) ? payload.stages : [];
        const stageMap = stagesArray.reduce((acc, stage) => {
          if (!stage?.stage_key) return acc;
          acc[stage.stage_key] = {
            ...stage,
            total_items: stage?.output_count ?? stage?.input_count ?? null,
            items_out: stage?.output_count ?? null,
            items_in: stage?.input_count ?? null,
            removed: stage?.removed_count ?? null,
          };
          return acc;
        }, {});
        setTimelineData({ ...payload, stages: stageMap, stages_list: stagesArray });
        setLogs(Array.isArray(payload.logs) ? payload.logs : []);
        const hasStages = Object.keys(stageMap).length > 0;
        if (hasStages || payload?.last_refresh !== startRefresh) {
          break;
        }
      } catch (err) {
        console.error("Polling failed:", err);
      }
    }
    setPolling(false);
  };

  const loadStageDetails = useCallback(
    async (stageKey, page = 1, force = false) => {
      if (!selectedUser || !stageKey) return;
      const key = `${selectedUser}::${stageKey}::${page}::50::${timelineData?.last_refresh || "none"}`;
      setStageDetailPage(page);
      setStageDetailError(null);
      if (!force && stageCacheRef.current.has(key)) {
        setStageDetail(stageCacheRef.current.get(key));
        setStageDetailCached(true);
        return;
      }
      if (inFlightStageRef.current.has(key)) {
        console.log("[Timeline] Skipping duplicate stage fetch", key);
        return;
      }

      const controller = new AbortController();
      inFlightStageRef.current.set(key, controller);
      setStageDetailLoading(true);
      setStageDetailCached(false);
      try {
        const resp = await getTimelineStageDetails(selectedUser, stageKey, 50, page, { signal: controller.signal });
        inFlightStageRef.current.delete(key);
        if (!resp?.success) {
          setStageDetailError(resp?.error || { message: "Failed to load stage detail", status: resp?.status });
          setStageDetail(null);
          return;
        }
        const detailPayload = resp?.data ?? {};
        const stageDetailNormalized = {
          ...detailPayload,
          debug: resp?.debug || {},
          request_id: resp?.request_id,
        };
        stageCacheRef.current.set(key, stageDetailNormalized);
        setStageDetail(stageDetailNormalized);
      } catch (err) {
        inFlightStageRef.current.delete(key);
        setStageDetailError(err);
        setStageDetail(null);
      } finally {
        setStageDetailLoading(false);
      }
    },
    [selectedUser, timelineData?.last_refresh]
  );

  useEffect(() => {
    if (selectedStage) {
      loadStageDetails(selectedStage, 1);
    }
  }, [selectedStage, loadStageDetails]);

  const runProbe = async () => {
    if (!selectedUser) return;
    setProbeLoading(true);
    setProbeError(null);
    setProbeResult(null);
    try {
      const url = `${API_BASE_URL}/api/admin/timeline/probe?user_email=${encodeURIComponent(selectedUser)}&force_refresh=true`;
      const resp = await fetch(url, { method: "POST", credentials: "include" });
      const json = await resp.json();
      if (!json?.success) {
        setProbeError(json?.error || { message: "Probe failed" });
        return;
      }
      setProbeResult(json);
    } catch (err) {
      setProbeError(err);
    } finally {
      setProbeLoading(false);
    }
  };

  return (
    <div className="timeline-debug-dashboard">
      {/* Header debug info */}
      <div className="debug-controls" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <div className="error-meta">last request_id: {lastMeta.request_id || "—"}</div>
          <div className="error-meta">duration_ms: {lastMeta.duration_ms ?? "—"}</div>
          <a href="/api/admin/_health" target="_blank" rel="noreferrer" className="error-meta">/api/admin/_health</a>
          <a href="/api/admin/_routes" target="_blank" rel="noreferrer" className="error-meta">/api/admin/_routes</a>
        </div>
      </div>

      {legacyInfo && (
        <div className="error-state" style={{ marginTop: 8 }}>
          <div style={{ fontWeight: 600 }}>Non-enveloped admin response</div>
          <div className="error-meta">endpoint: {legacyInfo.endpoint}</div>
          <div className="error-meta">request_id: {legacyInfo.request_id || "n/a"}</div>
          <div className="error-meta">status: {legacyInfo.status ?? "n/a"}</div>
        </div>
      )}

      <div className="debug-controls">
        <UserSelector
          value={selectedUser}
          onChange={setSelectedUser}
          placeholder="Select user to debug..."
        />

        {selectedUser && (
          <button onClick={triggerRefresh} disabled={refreshing} className="refresh-btn">
            {refreshing ? "🔄 Refreshing..." : "🔄 Trigger Refresh & Watch Live"}
          </button>
        )}
        {polling && (
          <div className="error-meta">Waiting for refresh... ({pollAttempts}s)</div>
        )}
      </div>

      {loading && <div className="loading-state">Loading timeline debug data...</div>}
      {!selectedUser && !loading && <div className="empty-state">Select a user to view timeline debug info</div>}
      {contractError && (
        <div className="error-state">
          <div style={{ fontWeight: 600 }}>Contract mismatch</div>
          <div className="error-meta">request_id: {contractError.request_id || "n/a"}</div>
          <div className="error-meta">duration_ms: {contractError.duration_ms ?? "n/a"}</div>
          <div className="error-meta">Details: {contractError.message}</div>
          <button className="refresh-btn" style={{ marginTop: 12 }} onClick={fetchTimelineData}>
            Retry
          </button>
        </div>
      )}
      {error && (
        <div
          className="error-state"
          style={{
            padding: "16px",
            background: "#fee2e2",
            border: "1px solid #ef4444",
            borderRadius: "8px",
            color: "#991b1b",
            margin: "16px 0",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: "8px" }}>Failed to load timeline data</div>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              fontSize: "12px",
              fontFamily: "monospace",
              margin: 0,
            }}
          >
            {error?.status === 404
              ? `Backend route missing: ${API_BASE_URL}/api/admin/timeline-debug/${selectedUser} (${error.message || ""})`
              : formatAdminError(error)}
          </pre>
          {error.status && (
            <details style={{ marginTop: "12px", fontSize: "12px" }}>
              <summary style={{ cursor: "pointer", fontWeight: 500 }}>
                Error Details (HTTP {error.status})
              </summary>
              <pre
                style={{
                  marginTop: "8px",
                  padding: "12px",
                  background: "rgba(0,0,0,0.05)",
                  borderRadius: "4px",
                  overflow: "auto",
                }}
              >
                {JSON.stringify(error, null, 2)}
              </pre>
            </details>
          )}
          <button
            onClick={fetchTimelineData}
            style={{
              marginTop: "12px",
              padding: "8px 16px",
              background: "#dc2626",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "13px",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {timelineData && !loading && (
        <>
      {/* Bucket Consistency Banner */}
      <BucketConsistencyBanner timelineData={timelineData} />

      {/* Snapshot visibility and probe */}
      <div className="metrics-grid" style={{ marginBottom: 12 }}>
        <div className="metric-card">
          <div className="metric-header">
            <h3 className="metric-title">Snapshot</h3>
          </div>
          <div className="metric-value">{snapshot?.snapshot_source || "n/a"}</div>
          <div className="metric-subtitle">Key: {snapshot?.snapshot_key || "n/a"}</div>
          <div className="metric-subtitle">Timestamp: {snapshot?.snapshot_timestamp || "n/a"}</div>
          <div className="metric-subtitle">Age (s): {snapshot?.snapshot_age_seconds ?? "n/a"}</div>
          {((snapshot?.snapshot_source || "") === "empty" || (snapshot?.snapshot_age_seconds || 0) > 600) && (
            <div className="error-meta" style={{ color: "#b91c1c", marginTop: 6 }}>
              Snapshot stale or empty
            </div>
          )}
          {snapshot?.worker_last_write_ts && (
            <div className="metric-subtitle">Worker last write: {snapshot.worker_last_write_ts}</div>
          )}
          {snapshot?.worker_last_run_id && (
            <div className="metric-subtitle">Worker run: {snapshot.worker_last_run_id}</div>
          )}
        </div>
        <div className="metric-card">
          <div className="metric-header">
            <h3 className="metric-title">Probe</h3>
          </div>
          <button className="refresh-btn" onClick={runProbe} disabled={probeLoading || !selectedUser}>
            {probeLoading ? "Probing..." : "Run Timeline Probe"}
          </button>
          {probeError && (
            <div className="error-meta" style={{ marginTop: 6, color: "#b91c1c" }}>
              {String(probeError?.message || probeError)}
            </div>
          )}
          {probeResult && (
            <details style={{ marginTop: 8 }}>
              <summary>Probe result</summary>
              <pre className="error-body" style={{ maxHeight: 200, overflow: "auto" }}>
                {JSON.stringify(probeResult, null, 2)}
              </pre>
            </details>
          )}
        </div>
      </div>

          {/* Raw Payload Viewer */}
          <details
            style={{
              marginBottom: "16px",
              padding: "12px",
              background: "#f9fafb",
              border: "1px solid #e5e7eb",
              borderRadius: "6px",
            }}
          >
            <summary
              style={{
                cursor: "pointer",
                fontWeight: 600,
                fontSize: "14px",
                color: "#374151",
                userSelect: "none",
              }}
            >
              🔍 Raw Payload Inspector (for debugging)
            </summary>
            <div style={{ marginTop: "12px" }}>
              <div style={{ fontSize: "12px", color: "#6b7280", marginBottom: "8px" }}>
                Full backend response (first 5000 chars):
              </div>
              <pre
                style={{
                  padding: "12px",
                  background: "#1f2937",
                  color: "#d1d5db",
                  borderRadius: "4px",
                  overflow: "auto",
                  maxHeight: "400px",
                  fontSize: "11px",
                  fontFamily: "monospace",
                }}
              >
                {JSON.stringify(timelineData, null, 2).slice(0, 5000)}
                {JSON.stringify(timelineData, null, 2).length > 5000 && "\n\n... (truncated)"}
              </pre>
            </div>
          </details>

          {/* Email Stage 0 Panel */}
          <EmailStage0Panel data={timelineData.email_stage_0} />

          <div className="metrics-grid">
            <MetricCard
              title="Total Items"
              value={timelineData.current_timeline?.total_items || 0}
              subtitle="In current timeline"
              icon="📊"
            />
            <MetricCard
              title="AI Processing"
              value={`${timelineData.ai_processing?.items_returned || 0}/${timelineData.ai_processing?.items_sent || "?"}`}
              subtitle="Returned / Sent"
              icon="🤖"
            />
            <MetricCard
              title="Recurring Patterns"
              value={timelineData.recurring_consolidation?.patterns_detected?.length || 0}
              subtitle="Detected"
              icon="🔄"
            />
            <MetricCard
              title="Last Refresh"
              value={
                timelineData.last_refresh ? new Date(timelineData.last_refresh).toLocaleTimeString() : "Never"
              }
              subtitle={timelineData.last_refresh ? new Date(timelineData.last_refresh).toLocaleDateString() : ""}
              icon="⏰"
            />
          </div>
          <div className="error-meta">
            Last refresh: {timelineData.last_refresh || "n/a"} | Request ID: {timelineData.request_id || "n/a"}
          </div>

          <div className="section">
            <h2>Pipeline Flow</h2>
            {!timelineData.stages_list || timelineData.stages_list.length === 0 ? (
              <div className="error-state" style={{ textAlign: "left" }}>
                No stages in snapshot.
              </div>
            ) : (
              <StageFlowDiagram
                stages={timelineData.stages_list}
                onStageClick={(key) => {
                  setSelectedStage(key);
                  setStageDetailPage(1);
                  loadStageDetails(key, 1);
                }}
                selectedStage={selectedStage}
              />
            )}
            {polling && <div className="loading-state">Waiting for refresh... ({pollAttempts}s)</div>}
            {!polling && pollAttempts >= 15 && (
              <div className="error-state" style={{ textAlign: "left" }}>
                Timed out waiting for refresh.
                <button className="refresh-btn" onClick={triggerRefresh} style={{ marginLeft: 8 }}>
                  Refresh again
                </button>
              </div>
            )}
          </div>

          <div className="details-grid">
            <StageDetailsPanel
              stage={selectedStage}
              summaryData={selectedStage ? timelineData.stages?.[selectedStage] : null}
              detailData={stageDetail}
              loading={stageDetailLoading}
              error={stageDetailError}
              page={stageDetailPage}
              isCached={stageDetailCached}
              onRefresh={() => loadStageDetails(selectedStage, stageDetailPage, true)}
              onPageChange={(nextPage) => {
                if (nextPage < 1) return;
                loadStageDetails(selectedStage, nextPage);
              }}
              parentStage={selectedStage ? timelineData.stages?.[selectedStage] : null}
            />
            <AIProcessingPanel data={timelineData.ai_processing} timeline={timelineData.current_timeline} />
            <GuardrailsPanel data={timelineData.guardrails} />
          </div>

          <div className="section">
            <h2>Current Timeline (Saved in DB)</h2>
            <div className="timeline-buckets">
              <div className="bucket">
                <h3>Daily Goals (1d)</h3>
                <p>Urgent: {timelineData.current_timeline?.["1d"]?.urgent?.length || 0}</p>
                <p>Normal: {timelineData.current_timeline?.["1d"]?.normal?.length || 0}</p>
              </div>
              <div className="bucket">
                <h3>Weekly Focus (7d)</h3>
                <p>Urgent: {timelineData.current_timeline?.["7d"]?.urgent?.length || 0}</p>
                <p>Normal: {timelineData.current_timeline?.["7d"]?.normal?.length || 0}</p>
              </div>
              <div className="bucket">
                <h3>Monthly Objectives (28d)</h3>
                <p>Urgent: {timelineData.current_timeline?.["28d"]?.urgent?.length || 0}</p>
                <p>Normal: {timelineData.current_timeline?.["28d"]?.normal?.length || 0}</p>
              </div>
            </div>
          </div>

          {logs?.length > 0 && (
            <div className="section">
              <h2>Logs</h2>
              <LogViewer logs={logs} />
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default TimelineDebugDashboard;
