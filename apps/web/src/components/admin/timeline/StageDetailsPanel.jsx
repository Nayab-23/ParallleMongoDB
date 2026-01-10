import React from "react";

const StageDetailsPanel = ({
  stage,
  summaryData,
  detailData,
  loading = false,
  error = null,
  page = 1,
  onPageChange = () => {},
  isCached = false,
  onRefresh = null,
  parentStage = null,
}) => {
  if (!stage) {
    return (
      <div className="dashboard-stub">
        <h2>Stage Details</h2>
        <p>Select a stage to see inputs/outputs.</p>
      </div>
    );
  }

  const items = detailData?.items || [];
  const hasNext = detailData?.has_next || false;
  const hasPrev = page > 1;
  const itemsFound = detailData?.debug?.output?.items_found_count ?? detailData?.debug?.stage_detail?.items_found_count;
  const cacheKeyUsed = detailData?.debug?.output?.cache_key_used ?? detailData?.debug?.stage_detail?.cache_key_used;
  const availableStageKeys =
    detailData?.debug?.output?.available_stage_keys ?? detailData?.debug?.stage_detail?.available_stage_keys;
  const parentOut = parentStage?.output_count ?? parentStage?.items_out ?? parentStage?.total_items;
  const snapshotInconsistency = parentOut > 0 && (itemsFound === 0 || (Array.isArray(items) && items.length === 0));

  return (
    <div className="dashboard-stub">
      <h2>Stage Details</h2>
      <p className="subhead">{stage}</p>

      <div className="stage-details-grid">
        <div>
          <strong>Items In:</strong> {summaryData?.items_in ?? summaryData?.input ?? summaryData?.total_items ?? "—"}
        </div>
        <div>
          <strong>Items Out:</strong> {summaryData?.items_out ?? summaryData?.output ?? "—"}
        </div>
        {typeof summaryData?.removed_count === "number" && (
          <div>
            <strong>Removed:</strong> {summaryData.removed_count}
          </div>
        )}
      </div>
      {isCached && <div className="error-meta">Cached</div>}
      {onRefresh && (
        <button className="refresh-btn" onClick={() => onRefresh()} style={{ marginTop: 8 }}>
          Refresh stage
        </button>
      )}

      {snapshotInconsistency && (
        <div className="error-state" style={{ textAlign: "left" }}>
          Snapshot inconsistency: parent output_count {parentOut} but items_found {itemsFound ?? 0}
          <div className="error-meta">request_id: {detailData?.request_id || "n/a"}</div>
          {cacheKeyUsed && <div className="error-meta">cache_key_used: {cacheKeyUsed}</div>}
          {availableStageKeys && (
            <div className="error-meta">available_stage_keys: {Array.isArray(availableStageKeys) ? availableStageKeys.join(", ") : String(availableStageKeys)}</div>
          )}
        </div>
      )}

      {loading && <div className="loading-state">Loading stage items...</div>}

      {error && (
        <div className="error-state" style={{ textAlign: "left" }}>
          {error.status === 404 ? "Not available (backend not deployed)" : error.message || "Failed to load stage details"}
        </div>
      )}

      {!loading && !error && items.length === 0 && (
        <div className="empty-state" style={{ padding: "12px 0" }}>
          No items for this stage.
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <div className="stage-items">
          {items.map((item, idx) => (
            <div key={item.id || idx} className="stage-item-row">
              <div className="stage-item-main">
                <div className="stage-item-title">{item.title || item.subject || "(no title)"}</div>
                <div className="stage-item-meta">
                  <span>{item.timestamp ? new Date(item.timestamp).toLocaleString() : ""}</span>
                  <span>{item.source_type || item.type || ""}</span>
                </div>
              </div>
              {item.reason && (
                <div className="stage-item-reason">
                  <strong>Reason:</strong> {item.reason}
                </div>
              )}
              {item.decision && (
                <div className="stage-item-reason">
                  <strong>Decision:</strong> {item.decision}
                </div>
              )}
              {item.dedup_id && (
                <div className="stage-item-reason">
                  <strong>Dedup Match:</strong> {item.dedup_id}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="pagination-row">
        <button className="refresh-btn" onClick={() => onPageChange(page - 1)} disabled={!hasPrev || loading}>
          Prev
        </button>
        <span className="page-label">Page {page}</span>
        <button className="refresh-btn" onClick={() => onPageChange(page + 1)} disabled={!hasNext || loading}>
          Next
        </button>
      </div>
    </div>
  );
};

export default StageDetailsPanel;
