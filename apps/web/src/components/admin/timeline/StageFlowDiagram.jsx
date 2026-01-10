import React from "react";

const StageFlowDiagram = ({ stages, onStageClick, selectedStage }) => {
  const stageList = Array.isArray(stages) ? stages : [];
  return (
    <div className="stage-flow">
      {stageList.map((stage, index) => {
        const stageKey = stage?.stage_key || `stage-${index}`;
        const stageLabel = stage?.label || stageKey;
        const itemCount = stage?.output_count ?? stage?.input_count ?? "—";
        const isSelected = selectedStage === stageKey;
        return (
          <React.Fragment key={stageKey}>
            <div className={`stage-box ${isSelected ? "selected" : ""}`} onClick={() => onStageClick(stageKey)}>
              <div className="stage-label">{stageLabel}</div>
              <div className="stage-count">{itemCount}</div>
              {stage?.timestamp && <div className="stage-time">{new Date(stage.timestamp).toLocaleTimeString()}</div>}
            </div>
            {index < stageList.length - 1 && <div className="stage-arrow">-&gt;</div>}
          </React.Fragment>
        );
      })}
    </div>
  );
};

export default StageFlowDiagram;
