import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useScenarioSocket } from "../lib/useScenarioSocket";
import ScenarioControls from "../components/ScenarioControls";
import PipelineRail from "../components/PipelineRail";
import EventLog from "../components/EventLog";
import RevealPanel from "../components/RevealPanel";

export default function Cockpit({ onStatusChange }) {
  const socket = useScenarioSocket();
  const [scenarioMeta, setScenarioMeta] = useState(null);
  const [speed, setSpeedState] = useState(10);

  useEffect(() => {
    api
      .scenarios()
      .then((list) => {
        const byType = Object.fromEntries(list.map((s) => [s.fault_type, s]));
        setScenarioMeta(byType);
      })
      .catch(() => setScenarioMeta({}));
  }, []);

  useEffect(() => {
    onStatusChange?.(socket.status, socket.connected);
  }, [socket.status, socket.connected, onStatusChange]);

  const handleSetSpeed = (s) => {
    setSpeedState(s);
    socket.setSpeed(s);
  };

  const handleStart = (faultType) => {
    socket.start(faultType, speed);
  };

  const handleStartRandom = () => {
    socket.startRandom(speed);
  };

  const handleStartUpload = (datasetId) => {
    socket.startUpload(datasetId, speed);
  };

  return (
    <div className="cockpit">
      <ScenarioControls
        scenario={scenarioMeta}
        status={socket.status}
        faultType={socket.faultType}
        blind={socket.blind}
        raw={socket.raw}
        nServices={socket.nServices}
        speed={speed}
        onStart={handleStart}
        onStartRandom={handleStartRandom}
        onStartUpload={handleStartUpload}
        onPause={socket.pause}
        onResume={socket.resume}
        onSetSpeed={handleSetSpeed}
        onReset={socket.reset}
      />

      {socket.errorMsg && <div className="banner banner--error">{socket.errorMsg}</div>}

      <div className="cockpit__main">
        <PipelineRail step={socket.current} />
      </div>

      {socket.blind && (socket.status === "complete" || socket.status === "paused") && (
        <RevealPanel
          revealed={socket.reveal}
          log={socket.log}
          raw={socket.raw}
          onReveal={socket.revealTruth}
        />
      )}

      <EventLog log={socket.log} blind={socket.blind} raw={socket.raw} />
    </div>
  );
}
