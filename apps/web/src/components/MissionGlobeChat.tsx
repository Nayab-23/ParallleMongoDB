"use client";

import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { feature } from "topojson-client";
import { PARALLEL_DEMO_SCRIPTS } from "../lib/parallel-demo-scripts";
import "./MissionGlobeChat.css";

type XY = { x: number; y: number } | null;

const VIEW_WIDTH = 1240;
const VIEW_HEIGHT = 700;

function interpolateProjection(raw0: any, raw1: any) {
  let alpha = 0;
  const projection: any = d3.geoProjection(function (x: number, y: number) {
    const p0 = raw0(x, y);
    const p1 = raw1(x, y);
    return [(1 - alpha) * p0[0] + alpha * p1[0], (1 - alpha) * p0[1] + alpha * p1[1]];
  });
  projection.alpha = function (_: number) {
    if (!arguments.length) return alpha;
    alpha = _;
    return projection;
  };
  return projection;
}

function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n));
}

function useTypewriter(text: string, speedMs: number) {
  const [out, setOut] = useState("");
  useEffect(() => {
    let i = 0;
    let cancelled = false;
    setOut("");
    const tick = () => {
      if (cancelled) return;
      i += 1;
      setOut(text.slice(0, i));
      if (i < text.length) setTimeout(tick, speedMs);
    };
    if (text.length) setTimeout(tick, speedMs);
    return () => {
      cancelled = true;
    };
  }, [text, speedMs]);
  return out;
}

export default function MissionGlobeChat() {
  const svgRef = useRef<SVGSVGElement | null>(null);

  const [worldData, setWorldData] = useState<any[]>([]);
  const [dataError, setDataError] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [isAnimating, setIsAnimating] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [canTypeAnswer, setCanTypeAnswer] = useState(false);
  const [minDelayPassed, setMinDelayPassed] = useState(false);

  // 100 = map, 0 = globe (start unrolled)
  const [progress, setProgress] = useState(100);

  const [rotation, setRotation] = useState<[number, number]>([-25, 0]);
  const [isDragging, setIsDragging] = useState(false);
  const [lastPointer, setLastPointer] = useState<[number, number]>([0, 0]);

  const [usAnchor, setUsAnchor] = useState<XY>(null);
  const [bdAnchor, setBdAnchor] = useState<XY>(null);

  // Chat rotation
  const [scriptIdx, setScriptIdx] = useState(0);
  const script =
    PARALLEL_DEMO_SCRIPTS[scriptIdx] ??
    PARALLEL_DEMO_SCRIPTS[0] ?? { q: "", a: "" };
  const questionText = script.q ?? "";
  const answerText = script.a ?? "";

  // Typewriter: question first, then answer
  const typedQ = useTypewriter(questionText, 18);
  const typedA = useTypewriter(canTypeAnswer ? answerText : "", 14);
  const isAnswerDone = canTypeAnswer && typedA.length >= answerText.length;

  useEffect(() => {
    setIsProcessing(false);
    setCanTypeAnswer(false);
  }, [scriptIdx]);

  useEffect(() => {
    if (!questionText) return;
    if (typedQ.length < questionText.length) return;
    if (canTypeAnswer) return;

    setIsProcessing(true);
    const timer = setTimeout(() => {
      setIsProcessing(false);
      setCanTypeAnswer(true);
    }, 3000);
    return () => clearTimeout(timer);
  }, [typedQ, questionText, canTypeAnswer]);

  useEffect(() => {
    setMinDelayPassed(false);
    const timer = setTimeout(() => setMinDelayPassed(true), 15000);
    return () => clearTimeout(timer);
  }, [scriptIdx]);

  useEffect(() => {
    if (!minDelayPassed || !isAnswerDone) return;
    setScriptIdx((i) => (i + 1) % PARALLEL_DEMO_SCRIPTS.length);
  }, [minDelayPassed, isAnswerDone]);

  // Load topojson once
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const localUrl = `${import.meta.env.BASE_URL}countries-110m.json`;
    const cdnUrl = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";

    const fetchWorld = async (url: string, sourceLabel: string) => {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) {
        throw new Error(`${sourceLabel} map request failed (${response.status})`);
      }
      const world = await response.json();
      if (!world?.objects?.countries) {
        console.error("[MissionGlobeChat] Missing countries object:", world);
        throw new Error("Map data missing countries.");
      }
      const countries = feature(world, world.objects.countries).features;
      if (!Array.isArray(countries)) {
        console.error("[MissionGlobeChat] Invalid countries features:", {
          world,
          countries,
        });
        throw new Error("Map data invalid (countries feature array missing).");
      }
      return countries;
    };

    (async () => {
      try {
        const countries = await fetchWorld(localUrl, "Local");
        if (!cancelled) {
          setWorldData(countries);
          setDataError(null);
        }
        return;
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return;
        console.error("[MissionGlobeChat] Failed to load local map data:", err);
      }

      try {
        const countries = await fetchWorld(cdnUrl, "CDN");
        if (!cancelled) {
          setWorldData(countries);
          setDataError(null);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof Error && err.name === "AbortError") return;
        console.error("[MissionGlobeChat] Failed to load CDN map data:", err);
        const message = err instanceof Error ? err.message : "Unable to load world map data.";
        setDataError(message);
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  // Render D3 each update
  useEffect(() => {
    if (!svgRef.current || !worldData.length) return;

    try {
      const width = VIEW_WIDTH;
      const height = VIEW_HEIGHT;

      const svg = d3.select(svgRef.current);
      svg.selectAll("*").remove();

      const t = progress / 100;
      const alpha = Math.pow(t, 0.5);

      const globeScale = Math.min(width, height) * 0.28;
      const mapScale = (width / (2 * Math.PI)) * 1.12;
      const scale = d3.scaleLinear().domain([0, 1]).range([globeScale, mapScale]);
      const projection = interpolateProjection(d3.geoOrthographicRaw, d3.geoEquirectangularRaw)
        .scale(scale(alpha))
        .translate([width / 2, height / 2])
        .rotate([rotation[0], clamp(rotation[1], -90, 90)])
        .precision(0.1);

      projection.alpha(alpha);

      // Compute anchors (San Jose + Dhaka)
      const us = projection([-121.8863, 37.3382]) as [number, number] | null;
      const bd = projection([90.4125, 23.8103]) as [number, number] | null;
      setUsAnchor(us ? { x: us[0], y: us[1] } : null);
      setBdAnchor(bd ? { x: bd[0], y: bd[1] } : null);

      const path = d3.geoPath(projection);

      // Sphere / ocean
      svg
        .append("path")
        .datum({ type: "Sphere" })
        .attr("d", path as any)
        .attr("fill", "#0b1220")
        .attr("opacity", 1);

      // Graticule
      const graticule = d3.geoGraticule();
      svg
        .append("path")
        .datum(graticule())
        .attr("d", path as any)
        .attr("fill", "none")
        .attr("stroke", "#ffffff")
        .attr("stroke-width", 1)
        .attr("opacity", 0.08);

      // Countries
      svg
        .selectAll(".country")
        .data(worldData)
        .enter()
        .append("path")
        .attr("class", "country")
        .attr("d", path as any)
        .attr("fill", "#111c33")
        .attr("stroke", "#ffffff")
        .attr("stroke-width", 0.6)
        .attr("opacity", 0.95);

      // Outline
      svg
        .append("path")
        .datum({ type: "Sphere" })
        .attr("d", path as any)
        .attr("fill", "none")
        .attr("stroke", "#ffffff")
        .attr("stroke-width", 1)
        .attr("opacity", 0.15);
      setRenderError(null);
    } catch (err) {
      console.error("[MissionGlobeChat] Map render failed:", err);
      setRenderError("Unable to render the map right now.");
    }
  }, [worldData, progress, rotation]);

  const handlePointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || !svgRef.current) return;
    svgRef.current.setPointerCapture(e.pointerId);
    setIsDragging(true);
    setLastPointer([e.clientX - rect.left, e.clientY - rect.top]);
  };

  const handlePointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!isDragging) return;
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const cur: [number, number] = [e.clientX - rect.left, e.clientY - rect.top];
    const dx = cur[0] - lastPointer[0];
    const dy = cur[1] - lastPointer[1];

    setRotation((prev) => [prev[0] + dx * 0.35, clamp(prev[1] - dy * 0.35, -90, 90)]);
    setLastPointer(cur);
  };

  const handlePointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    setIsDragging(false);
    if (svgRef.current?.hasPointerCapture(e.pointerId)) {
      svgRef.current.releasePointerCapture(e.pointerId);
    }
  };

  const toggle = () => {
    if (isAnimating) return;
    setIsAnimating(true);

    const start = progress;
    const end = start >= 50 ? 0 : 100; // map -> globe, globe -> map
    const duration = 1600;
    const startTime = performance.now();

    const animate = (now: number) => {
      const elapsed = now - startTime;
      const tt = Math.min(elapsed / duration, 1);
      const eased = tt < 0.5 ? 2 * tt * tt : -1 + (4 - 2 * tt) * tt;
      const cur = start + (end - start) * eased;
      setProgress(cur);
      if (tt < 1) requestAnimationFrame(animate);
      else setIsAnimating(false);
    };

    requestAnimationFrame(animate);
  };

  const mapMode = progress >= 70;
  const isDev = import.meta.env.DEV;
  const errorMessage = dataError || renderError;
  const errorDisplay = errorMessage
    ? isDev
      ? errorMessage
      : "Map temporarily unavailable."
    : null;

  return (
    <div className="mission-globe">
      <div className="mission-globe-card">
        <div className="mission-globe-header">
          <div className="mission-globe-title">Team awareness across time zones</div>
          <button
            type="button"
            onClick={toggle}
            className="mission-globe-toggle"
            disabled={isAnimating}
          >
            {mapMode ? "Roll to Globe" : "Unroll to Map"}
          </button>
        </div>

        <div className="mission-globe-stage">
          {errorDisplay && <div className="mission-globe-error">{errorDisplay}</div>}
          <svg
            ref={svgRef}
            viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
            className={`mission-globe-svg${isDragging ? " is-dragging" : ""}`}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerLeave={handlePointerUp}
            onPointerCancel={handlePointerUp}
          />

          <div className={`mission-globe-overlays${mapMode ? " is-visible" : ""}`}>
            {usAnchor && (
              <div
                className="mission-chat-anchor"
                style={{
                  left: usAnchor.x,
                  top: usAnchor.y,
                  transform:
                    usAnchor.x < VIEW_WIDTH * 0.25
                      ? "translate(10%, -115%)"
                      : "translate(-20%, -115%)",
                }}
              >
                <div className="mission-chat-bubble">
                  <div className="mission-chat-header">
                    <div className="mission-chat-avatar">🧑‍💻</div>
                    <div className="mission-chat-name">Severin (USA)</div>
                  </div>
                  <div className="mission-chat-text">{typedQ}</div>
                </div>
              </div>
            )}

            {bdAnchor && (
              <div
                className="mission-chat-anchor"
                style={{
                  left: bdAnchor.x,
                  top: bdAnchor.y,
                  transform:
                    bdAnchor.x > VIEW_WIDTH * 0.6
                      ? "translate(-110%, -120%)"
                      : "translate(10%, -120%)",
                }}
              >
                <div className="mission-chat-bubble">
                  <div className="mission-chat-header">
                    <div className="mission-chat-avatar">🤖</div>
                    <div className="mission-chat-name">Nayab’s AI agent (Bangladesh)</div>
                  </div>
                  <div className="mission-chat-text">
                    {canTypeAnswer ? typedA : isProcessing ? (
                      <div className="mission-chat-spinner" aria-label="processing" />
                    ) : null}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="mission-globe-hint">Drag to rotate</div>
      </div>
    </div>
  );
}
