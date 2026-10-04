import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

const MAX_LOG = 200;

/** État et contrôle du rejeu de scénario en direct (play/pause/vitesse). */
export function useScenarioSocket() {
  const wsRef = useRef(null);
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState("idle"); // idle | running | paused | complete | error
  const [faultType, setFaultType] = useState(null);
  const [blind, setBlind] = useState(false);
  const [raw, setRaw] = useState(false);
  const [m4Demo, setM4Demo] = useState(false);
  const [nServices, setNServices] = useState(null);
  const [reveal, setRevealData] = useState(null);
  const [totalSteps, setTotalSteps] = useState(0);
  const [current, setCurrent] = useState(null); // dernier résultat de step
  const [log, setLog] = useState([]);
  const [errorMsg, setErrorMsg] = useState(null);

  useEffect(() => {
    const ws = new WebSocket(api.scenarioSocketUrl());
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setErrorMsg("Connexion au backend impossible — vérifie que l'API tourne.");

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      switch (msg.event) {
        case "scenario_started":
          setStatus("running");
          setFaultType(msg.fault_type); // null en mode aveugle -- personne ne le connaît
          setBlind(Boolean(msg.blind));
          setRaw(Boolean(msg.raw));
          setM4Demo(Boolean(msg.m4_demo));
          setNServices(msg.n_services ?? null);
          setRevealData(null);
          setTotalSteps(msg.total_steps);
          setLog([]);
          setCurrent(null);
          setErrorMsg(null);
          break;
        case "step":
          setCurrent(msg.data);
          setLog((prev) => [msg.data, ...prev].slice(0, MAX_LOG));
          break;
        case "paused":
          setStatus("paused");
          break;
        case "resumed":
          setStatus("running");
          break;
        case "scenario_complete":
          setStatus("complete");
          break;
        case "reveal":
          setRevealData(msg);
          if (msg.fault_type) setFaultType(msg.fault_type);
          break;
        case "reset_done":
          setStatus("idle");
          setCurrent(null);
          setLog([]);
          setFaultType(null);
          setBlind(false);
          setRaw(false);
          setM4Demo(false);
          setNServices(null);
          setRevealData(null);
          break;
        case "error":
          setStatus("error");
          setErrorMsg(msg.message);
          break;
        default:
          break;
      }
    };

    return () => ws.close();
  }, []);

  const send = useCallback((payload) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    }
  }, []);

  const start = useCallback((fault_type, speed = 5) => send({ action: "start", fault_type, speed }), [send]);
  const startRandom = useCallback((speed = 5) => send({ action: "start_random", speed, blind: true }), [send]);
  const startUpload = useCallback((dataset_id, speed = 5) => send({ action: "start_upload", dataset_id, speed }), [send]);
  const startM4Demo = useCallback((speed = 5) => send({ action: "start_m4_demo", speed }), [send]);
  const revealTruth = useCallback(() => send({ action: "reveal" }), [send]);
  const pause = useCallback(() => send({ action: "pause" }), [send]);
  const resume = useCallback(() => send({ action: "resume" }), [send]);
  const setSpeed = useCallback((speed) => send({ action: "set_speed", speed }), [send]);
  const reset = useCallback(() => send({ action: "reset" }), [send]);

  return {
    connected,
    status,
    faultType,
    blind,
    raw,
    m4Demo,
    nServices,
    reveal,
    totalSteps,
    current,
    log,
    errorMsg,
    start,
    startRandom,
    startUpload,
    startM4Demo,
    revealTruth,
    pause,
    resume,
    setSpeed,
    reset,
  };
}
