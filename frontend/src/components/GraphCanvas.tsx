import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import { motion } from "framer-motion";
import {
  CheckCircle2,
  Circle,
  FileText,
  Minus,
  Move,
  Plus,
  RotateCcw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { GraphEdge, GraphNode } from "../types";

const CANVAS_WIDTH = 1280;
const CARD_WIDTH = 188;
const CARD_HEIGHT = 132;
const TOP_OFFSET = 44;
const ROW_GAP = 170;
const COLUMN_X: Record<number, number> = {
  0: 150,
  1: 546,
  2: 942,
};

type Point = {
  x: number;
  y: number;
};

type DragState = {
  active: boolean;
  startX: number;
  startY: number;
  originX: number;
  originY: number;
  nodeId: string | null;
  moved: boolean;
};

function defaultNodePosition(node: GraphNode): Point {
  const layout = node.metadata.layout ?? { column: 1, row: 0 };
  return {
    x: COLUMN_X[layout.column] ?? COLUMN_X[1],
    y: TOP_OFFSET + layout.row * ROW_GAP,
  };
}

function operationLabel(operationType: string) {
  if (operationType === "analyze") {
    return "Analyze";
  }
  if (operationType === "verify") {
    return "Verify";
  }
  if (operationType === "synthesize") {
    return "Synthesize";
  }
  if (operationType === "aggregate") {
    return "Aggregate";
  }
  return "Generate";
}

function humanizeBranch(kind: string) {
  const normalized = kind?.trim() ? kind : "execution";
  return `${normalized.replace(/[_-]+/g, " ")} branch`.replace(/\b\w/g, (char) => char.toUpperCase());
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function statusTone(node: GraphNode, active: boolean) {
  if (node.status === "running") {
    return "border-[var(--mw-border-strong)] bg-[var(--mw-panel)]";
  }
  if (node.status === "completed" && node.verification_status === "passed") {
    return active
      ? "border-[var(--mw-accent)] bg-[var(--mw-accent-soft)]"
      : "border-[var(--mw-border)] bg-[var(--mw-panel)]";
  }
  if (active) {
    return "border-[var(--mw-border-strong)] bg-[var(--mw-panel)]";
  }
  return "border-[var(--mw-border)] bg-[var(--mw-panel)]";
}

interface GraphCanvasProps {
  programId: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedNodeId: string | null;
  onSelectNode: (node: GraphNode) => void;
}

export function GraphCanvas({
  programId,
  nodes,
  edges,
  selectedNodeId,
  onSelectNode,
}: GraphCanvasProps) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [nodePositions, setNodePositions] = useState<Record<string, Point>>({});
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const zoomRef = useRef(zoom);
  const panRef = useRef<DragState>({
    active: false,
    startX: 0,
    startY: 0,
    originX: 0,
    originY: 0,
    nodeId: null,
    moved: false,
  });
  const nodeDragRef = useRef<DragState>({
    active: false,
    startX: 0,
    startY: 0,
    originX: 0,
    originY: 0,
    nodeId: null,
    moved: false,
  });
  const suppressClickRef = useRef<string | null>(null);

  useEffect(() => {
    setNodePositions(
      Object.fromEntries(nodes.map((node) => [node.id, defaultNodePosition(node)])),
    );
  }, [nodes]);

  useEffect(() => {
    zoomRef.current = zoom;
  }, [zoom]);

  // 1. Calculate the standard minimum height based on your layout rows
  const baseHeight = Math.max(...nodes.map((node) => (node.metadata.layout?.row ?? 0) + 1), 5) * ROW_GAP + 96;

  // 2. Find the lowest 'y' value currently in state (fallback to 0 if state is empty on first render)
  const currentMaxY = Object.values(nodePositions).length > 0 
    ? Math.max(...Object.values(nodePositions).map(p => p.y)) 
    : 0;

  // 3. The canvas height is whichever is larger: the base height, or the lowest node + padding
  const innerHeight = Math.max(baseHeight, currentMaxY + CARD_HEIGHT + 120);

  const centerView = useCallback((currentZoom = zoomRef.current) => {
    if (!canvasRef.current) {
      return;
    }

    const { clientWidth, clientHeight } = canvasRef.current;
    const targetX = (clientWidth - CANVAS_WIDTH * currentZoom) / 2;
    const targetY =
      innerHeight * currentZoom < clientHeight
        ? (clientHeight - innerHeight * currentZoom) / 2
        : 48;

    setPan({ x: targetX, y: targetY });
  }, [innerHeight]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      centerView();
    }, 10);

    return () => window.clearTimeout(timer);
  }, [nodes.length, centerView]);

  const nodeMap = new Map(nodes.map((node) => [node.id, node]));

  function positionFor(node: GraphNode): Point {
    return nodePositions[node.id] ?? defaultNodePosition(node);
  }

  function edgeEndpoints(source: GraphNode, target: GraphNode) {
    const sourcePosition = positionFor(source);
    const targetPosition = positionFor(target);
    const flowsDownward = targetPosition.y >= sourcePosition.y;

    return {
      startX: sourcePosition.x + CARD_WIDTH / 2,
      startY: flowsDownward ? sourcePosition.y + CARD_HEIGHT : sourcePosition.y,
      endX: targetPosition.x + CARD_WIDTH / 2,
      endY: flowsDownward ? targetPosition.y : targetPosition.y + CARD_HEIGHT,
    };
  }

  function edgePath(source: GraphNode, target: GraphNode) {
    const { startX, startY, endX, endY } = edgeEndpoints(source, target);
    const midY = (startY + endY) / 2;
    return `M ${startX} ${startY} C ${startX} ${midY}, ${endX} ${midY}, ${endX} ${endY}`;
  }

  function edgeLabelPosition(source: GraphNode, target: GraphNode) {
    const { startX, startY, endX, endY } = edgeEndpoints(source, target);
    return {
      x: (startX + endX) / 2,
      y: (startY + endY) / 2 - 8,
    };
  }

  function applyZoom(nextZoom: number) {
    setZoom(clamp(Number(nextZoom.toFixed(2)), 0.4, 2.2));
  }

  function zoomAroundPoint(nextZoom: number, viewportX: number, viewportY: number) {
    const clamped = clamp(Number(nextZoom.toFixed(2)), 0.4, 2.2);
    const ratio = clamped / zoom;
    setPan({
      x: viewportX - (viewportX - pan.x) * ratio,
      y: viewportY - (viewportY - pan.y) * ratio,
    });
    setZoom(clamped);
  }

  function handleCanvasPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget || nodeDragRef.current.active) {
      return;
    }
    panRef.current = {
      active: true,
      startX: event.clientX,
      startY: event.clientY,
      originX: pan.x,
      originY: pan.y,
      nodeId: null,
      moved: false,
    };
    setIsPanning(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handleCanvasPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (nodeDragRef.current.active && nodeDragRef.current.nodeId) {
      const deltaX = (event.clientX - nodeDragRef.current.startX) / zoom;
      const deltaY = (event.clientY - nodeDragRef.current.startY) / zoom;
      if (Math.abs(deltaX) > 1 || Math.abs(deltaY) > 1) {
        nodeDragRef.current.moved = true;
      }
      // Inside handleCanvasPointerMove (around line 133)
      setNodePositions((current) => ({
        ...current,
        [nodeDragRef.current.nodeId as string]: {
          // Keep the horizontal clamp
          x: clamp(nodeDragRef.current.originX + deltaX, 24, CANVAS_WIDTH - CARD_WIDTH - 24),
          // Remove the bottom limit, only enforce the top 24px margin
          y: Math.max(24, nodeDragRef.current.originY + deltaY), 
        },
      }));
      return;
    }

    if (!panRef.current.active) {
      return;
    }

    const deltaX = event.clientX - panRef.current.startX;
    const deltaY = event.clientY - panRef.current.startY;
    if (Math.abs(deltaX) > 1 || Math.abs(deltaY) > 1) {
      panRef.current.moved = true;
    }
    setPan({
      x: panRef.current.originX + deltaX,
      y: panRef.current.originY + deltaY,
    });
  }

  function handleCanvasPointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    if (panRef.current.active) {
      panRef.current.active = false;
      setIsPanning(false);
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (nodeDragRef.current.active) {
      if (nodeDragRef.current.moved) {
        suppressClickRef.current = nodeDragRef.current.nodeId;
      }
      nodeDragRef.current.active = false;
      nodeDragRef.current.nodeId = null;
      nodeDragRef.current.moved = false;
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handleWheel(event: ReactWheelEvent<HTMLDivElement>) {
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const viewportX = event.clientX - rect.left;
    const viewportY = event.clientY - rect.top;
    const delta = -event.deltaY * 0.0015;
    if (Math.abs(delta) < 0.0001) {
      return;
    }
    zoomAroundPoint(zoom * (1 + delta), viewportX, viewportY);
  }

  function handleNodePointerDown(node: GraphNode, event: ReactPointerEvent<HTMLButtonElement>) {
    event.stopPropagation();
    nodeDragRef.current = {
      active: true,
      startX: event.clientX,
      startY: event.clientY,
      originX: positionFor(node).x,
      originY: positionFor(node).y,
      nodeId: node.id,
      moved: false,
    };
    const canvas = canvasRef.current;
    if (canvas) {
      canvas.setPointerCapture(event.pointerId);
    }
  }

  function handleNodeClick(node: GraphNode) {
    if (suppressClickRef.current === node.id) {
      suppressClickRef.current = null;
      return;
    }
    onSelectNode(node);
  }

  return (
    <section className="relative flex min-h-0 flex-1 flex-col overflow-hidden px-1 pt-1">
      <div
        ref={canvasRef}
        className={`grid-canvas relative min-h-[430px] flex-1 overflow-hidden ${isPanning ? "cursor-grabbing" : "cursor-grab"}`}
        onPointerDown={handleCanvasPointerDown}
        onPointerMove={handleCanvasPointerMove}
        onPointerUp={handleCanvasPointerUp}
        onPointerLeave={handleCanvasPointerUp}
        onWheel={handleWheel}
      >
        <div className="absolute right-4 top-4 z-10 flex items-center gap-2">
          <div className="flex items-center gap-1 rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] p-1">
            <button
              type="button"
              onClick={() => applyZoom(zoom - 0.1)}
              className="flex h-8 w-8 items-center justify-center rounded-full text-[var(--mw-muted)] transition hover:bg-[var(--mw-panel)] hover:text-[var(--mw-text)]"
              aria-label="Zoom out"
            >
              <Minus size={14} strokeWidth={1.8} />
            </button>
            <div className="min-w-[52px] text-center font-mono text-[11px] text-[var(--mw-subtle)]">
              {Math.round(zoom * 100)}%
            </div>
            <button
              type="button"
              onClick={() => applyZoom(zoom + 0.1)}
              className="flex h-8 w-8 items-center justify-center rounded-full text-[var(--mw-muted)] transition hover:bg-[var(--mw-panel)] hover:text-[var(--mw-text)]"
              aria-label="Zoom in"
            >
              <Plus size={14} strokeWidth={1.8} />
            </button>
            <button
              type="button"
              onClick={() => {
                setZoom(1);
                setNodePositions(Object.fromEntries(nodes.map((node) => [node.id, defaultNodePosition(node)])));
                centerView(1);
              }}
              className="flex h-8 w-8 items-center justify-center rounded-full text-[var(--mw-muted)] transition hover:bg-[var(--mw-panel)] hover:text-[var(--mw-text)]"
              aria-label="Reset graph view"
            >
              <RotateCcw size={13} strokeWidth={1.8} />
            </button>
          </div>
        </div>
        <div
          className="pointer-events-none relative h-full w-full"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "top left",
          }}
        >
          <div className="relative w-[1280px]" style={{ height: innerHeight }}>
            <svg className="absolute inset-0 h-full w-full" viewBox={`0 0 ${CANVAS_WIDTH} ${innerHeight}`}>
              {edges.map((edge) => {
                const source = nodeMap.get(edge.source);
                const target = nodeMap.get(edge.target);
                if (!source || !target) {
                  return null;
                }
                const active = source.status === "completed" && target.status !== "pending";
                const labelPosition = edgeLabelPosition(source, target);
                return (
                  <g key={`${edge.source}-${edge.target}`}>
                    <path
                      d={edgePath(source, target)}
                      fill="none"
                      stroke={active ? "var(--mw-text)" : "var(--mw-border-strong)"}
                      strokeOpacity={active ? 0.34 : 0.2}
                      strokeWidth="1.3"
                      strokeLinecap="round"
                      className={active ? "edge-flow" : ""}
                    />
                    <text
                      x={labelPosition.x}
                      y={labelPosition.y}
                      fill="var(--mw-subtle)"
                      fontSize="10"
                      letterSpacing="0.22em"
                      textAnchor="middle"
                      className="uppercase"
                    >
                      {humanizeBranch(edge.kind)}
                    </text>
                  </g>
                );
              })}
            </svg>

            {nodes.map((node, index) => {
              const position = positionFor(node);
              const active = selectedNodeId === node.id;
              return (
                <motion.button
                  key={node.id}
                  type="button"
                  onClick={() => handleNodeClick(node)}
                  onPointerDown={(event) => handleNodePointerDown(node, event)}
                  initial={{ opacity: 0, scale: 0.98, y: 8 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  transition={{ delay: index * 0.05, duration: 0.32 }}
                className={`pointer-events-auto absolute rounded-[20px] border px-3.5 py-3 text-left transition ${statusTone(node, active)} ${
                  node.status === "running" ? "animate-pulse" : ""
                }`}
                style={{
                  width: CARD_WIDTH,
                  height: CARD_HEIGHT,
                  left: position.x,
                  top: position.y,
                }}
              >
                <div className="flex h-full flex-col">
                  <div className="mb-3 flex items-center justify-between">
                    <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.2em] text-[var(--mw-muted)]">
                      <Sparkles size={12} strokeWidth={1.7} />
                      {operationLabel(node.operation_type)}
                    </div>
                    {node.verification_status === "passed" ? (
                      <ShieldCheck size={14} strokeWidth={1.8} className="text-[var(--mw-accent)]" />
                    ) : node.status === "completed" ? (
                      <CheckCircle2 size={14} strokeWidth={1.8} className="text-[var(--mw-text)]" />
                    ) : (
                      <Circle size={14} strokeWidth={1.5} className="text-[var(--mw-subtle)]" />
                    )}
                  </div>

                  <div className="font-serif text-[19px] leading-[1.05] tracking-[0.01em] text-[var(--mw-text)]">
                    {node.title}
                  </div>
                  <div className="mt-1.5 text-[12px] leading-5 text-[var(--mw-muted)]">{node.subtitle}</div>

                  <div className="mt-auto flex items-center justify-between border-t border-[var(--mw-border)] pt-2.5 text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">
                    <span>{node.status}</span>
                    <div className="flex items-center gap-3">
                      <span>{node.latency_ms ? `${(node.latency_ms / 1000).toFixed(1)}s` : "--"}</span>
                      <span className="flex items-center gap-1">
                        <FileText size={12} strokeWidth={1.6} />
                        {node.evidence_refs.length}
                      </span>
                    </div>
                  </div>
                </div>
              </motion.button>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
