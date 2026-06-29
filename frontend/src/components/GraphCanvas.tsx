import {
  useCallback,
  useEffect,
  useMemo,
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
  Plus,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import type { GraphEdge, GraphNode, GraphPatchRequest } from "../types";

const BASE_CANVAS_WIDTH = 1280;
const CARD_WIDTH = 210;
const CARD_HEIGHT = 176;
const ROW_GAP = 220;
const COLUMN_SPACING = 360;
const HORIZONTAL_PADDING = 180;
const TOP_OFFSET = 44;
const FIRST_NODE_VIEW_TOP_MARGIN = 32;

type Point = {
  x: number;
  y: number;
};

type LayoutMetrics = {
  positions: Record<string, Point>;
  width: number;
  height: number;
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

type ConnectionMode = "after_node" | "before_node" | "between_nodes" | "branch_from";

interface GraphCanvasProps {
  programId: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedNodeId: string | null;
  canEditGraph: boolean;
  isApplyingPatch: boolean;
  onApplyGraphPatch: (request: GraphPatchRequest, focusNodeId?: string | null) => Promise<void>;
  onSelectNode: (node: GraphNode) => void;
  onPassNode: (node: GraphNode) => void;
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
  if (operationType === "calculate") {
    return "Calculate";
  }
  if (operationType === "tool") {
    return "Tool";
  }
  if (operationType === "hitl") {
    return "Human Review";
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

function executorLabel(executorType: string | undefined) {
  if (executorType === "agent_operator") {
    return "Agent";
  }
  if (executorType === "tool_operator") {
    return "Tool";
  }
  if (executorType === "human_operator") {
    return "Human";
  }
  return "LLM";
}

function approvalRequired(node: GraphNode) {
  return Boolean(node.approval_state?.requires_human_review || (node.required_approvals ?? 0) > 0);
}

function delegatedCount(node: GraphNode) {
  return node.delegated_children?.length ?? 0;
}

function canPassAndVerify(node: GraphNode) {
  return (
    node.status !== "completed" ||
    node.verification_status !== "passed" ||
    Boolean((node.approval_state?.pending_approvals ?? 0) > 0)
  );
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

function buildLayoutSignature(nodes: GraphNode[], edges: GraphEdge[]) {
  const nodeSignature = nodes
    .map((node) => ({
      id: node.id,
      depends_on: [...node.depends_on].sort(),
      next_nodes: [...node.next_nodes].sort(),
      placement: node.metadata.layout?.placement ?? node.metadata.expanded_from ?? null,
      reference_node_id: node.metadata.layout?.reference_node_id ?? null,
      parent_node_id: node.metadata.layout?.parent_node_id ?? null,
    }))
    .sort((left, right) => left.id.localeCompare(right.id));
  const edgeSignature = edges
    .map((edge) => `${edge.source}:${edge.target}:${edge.kind}`)
    .sort();
  return JSON.stringify({ nodeSignature, edgeSignature });
}

function buildAutoLayout(nodes: GraphNode[], edges: GraphEdge[]): LayoutMetrics {
  if (nodes.length === 0) {
    return {
      positions: {},
      width: BASE_CANVAS_WIDTH,
      height: 430,
    };
  }

  const stableIndex = new Map(nodes.map((node, index) => [node.id, index]));
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const incoming = new Map<string, Array<{ source: string; kind: string }>>();
  const outgoing = new Map<string, Array<{ target: string; kind: string }>>();

  for (const node of nodes) {
    incoming.set(node.id, []);
    outgoing.set(node.id, []);
  }

  for (const edge of edges) {
    if (!nodeMap.has(edge.source) || !nodeMap.has(edge.target)) {
      continue;
    }
    incoming.get(edge.target)?.push({ source: edge.source, kind: edge.kind });
    outgoing.get(edge.source)?.push({ target: edge.target, kind: edge.kind });
  }

  const indegree = new Map<string, number>(nodes.map((node) => [node.id, incoming.get(node.id)?.length ?? 0]));
  const depth = new Map<string, number>();
  const queue = nodes
    .filter((node) => (indegree.get(node.id) ?? 0) === 0)
    .sort((left, right) => (stableIndex.get(left.id) ?? 0) - (stableIndex.get(right.id) ?? 0))
    .map((node) => node.id);
  const visited = new Set<string>();

  if (queue.length === 0) {
    queue.push(nodes[0].id);
    depth.set(nodes[0].id, 0);
  }

  for (const rootId of queue) {
    depth.set(rootId, 0);
  }

  while (queue.length > 0) {
    const nodeId = queue.shift() as string;
    if (visited.has(nodeId)) {
      continue;
    }
    visited.add(nodeId);

    const currentDepth = depth.get(nodeId) ?? 0;
    const nextNodes = [...(outgoing.get(nodeId) ?? [])].sort(
      (left, right) => (stableIndex.get(left.target) ?? 0) - (stableIndex.get(right.target) ?? 0),
    );
    for (const edge of nextNodes) {
      const nextDepth = Math.max(depth.get(edge.target) ?? 0, currentDepth + 1);
      depth.set(edge.target, nextDepth);
      indegree.set(edge.target, Math.max((indegree.get(edge.target) ?? 1) - 1, 0));
      if ((indegree.get(edge.target) ?? 0) === 0) {
        queue.push(edge.target);
      }
    }
  }

  for (const node of nodes) {
    if (depth.has(node.id)) {
      continue;
    }
    const parents = incoming.get(node.id) ?? [];
    if (parents.length === 0) {
      depth.set(node.id, 0);
      continue;
    }
    const parentDepth = Math.max(...parents.map((parent) => depth.get(parent.source) ?? 0));
    depth.set(node.id, parentDepth + 1);
  }

  const primaryParent = new Map<string, string | null>();
  for (const node of nodes) {
    const parents = [...(incoming.get(node.id) ?? [])];
    if (parents.length === 0) {
      primaryParent.set(node.id, null);
      continue;
    }
    parents.sort((left, right) => {
      const expandedBias = (right.kind === "expanded_branch" ? 1 : 0) - (left.kind === "expanded_branch" ? 1 : 0);
      if (expandedBias !== 0) {
        return expandedBias;
      }
      const depthBias = (depth.get(right.source) ?? 0) - (depth.get(left.source) ?? 0);
      if (depthBias !== 0) {
        return depthBias;
      }
      return (stableIndex.get(left.source) ?? 0) - (stableIndex.get(right.source) ?? 0);
    });
    primaryParent.set(node.id, parents[0].source);
  }

  const childrenByParent = new Map<string, string[]>();
  for (const node of nodes) {
    childrenByParent.set(node.id, []);
  }
  for (const node of nodes) {
    const parentId = primaryParent.get(node.id);
    if (!parentId) {
      continue;
    }
    const children = childrenByParent.get(parentId) ?? [];
    children.push(node.id);
    childrenByParent.set(parentId, children);
  }

  const positions: Record<string, Point> = {};
  const visiting = new Set<string>();
  let cursorCenterX = HORIZONTAL_PADDING + CARD_WIDTH / 2;

  function orderedChildren(nodeId: string) {
    return [...(childrenByParent.get(nodeId) ?? [])].sort((leftId, rightId) => {
      const leftNode = nodeMap.get(leftId);
      const rightNode = nodeMap.get(rightId);
      const leftPlacement = leftNode?.metadata.layout?.placement ?? "";
      const rightPlacement = rightNode?.metadata.layout?.placement ?? "";
      if (leftPlacement === "expanded_child" || rightPlacement === "expanded_child") {
        const leftSibling = leftNode?.metadata.layout?.sibling_index ?? 0;
        const rightSibling = rightNode?.metadata.layout?.sibling_index ?? 0;
        if (leftSibling !== rightSibling) {
          return leftSibling - rightSibling;
        }
      }
      return (stableIndex.get(leftId) ?? 0) - (stableIndex.get(rightId) ?? 0);
    });
  }

  function placeNode(nodeId: string) {
    if (positions[nodeId]) {
      return;
    }
    if (visiting.has(nodeId)) {
      return;
    }

    visiting.add(nodeId);
    const childIds = orderedChildren(nodeId);
    for (const childId of childIds) {
      placeNode(childId);
    }

    let centerX = cursorCenterX;
    if (childIds.length > 0) {
      const childCenters = childIds
        .map((childId) => positions[childId]?.x)
        .filter((value): value is number => typeof value === "number")
        .map((left) => left + CARD_WIDTH / 2);
      if (childCenters.length > 0) {
        centerX = (childCenters[0] + childCenters[childCenters.length - 1]) / 2;
      }
    } else {
      cursorCenterX += COLUMN_SPACING;
    }

    positions[nodeId] = {
      x: centerX - CARD_WIDTH / 2,
      y: TOP_OFFSET + (depth.get(nodeId) ?? 0) * ROW_GAP,
    };
    visiting.delete(nodeId);
  }

  const roots = nodes
    .filter((node) => !primaryParent.get(node.id))
    .sort((left, right) => (stableIndex.get(left.id) ?? 0) - (stableIndex.get(right.id) ?? 0))
    .map((node) => node.id);

  for (const rootId of roots) {
    placeNode(rootId);
  }

  for (const node of nodes.sort((left, right) => (stableIndex.get(left.id) ?? 0) - (stableIndex.get(right.id) ?? 0))) {
    placeNode(node.id);
  }

  const maxX = Math.max(...Object.values(positions).map((position) => position.x), HORIZONTAL_PADDING);
  const maxY = Math.max(...Object.values(positions).map((position) => position.y), TOP_OFFSET);

  return {
    positions,
    width: Math.max(BASE_CANVAS_WIDTH, maxX + CARD_WIDTH + HORIZONTAL_PADDING),
    height: Math.max(430, maxY + CARD_HEIGHT + 120),
  };
}

function slugifyNodeId(value: string, existingIds: Set<string>) {
  const base = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "manual_node";
  let candidate = base;
  let counter = 2;
  while (existingIds.has(candidate)) {
    candidate = `${base}_${counter}`;
    counter += 1;
  }
  return candidate;
}

function parseEvidenceScope(input: string) {
  const trimmed = input.trim();
  if (!trimmed) {
    return {};
  }
  if (trimmed.startsWith("{")) {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    throw new Error("Evidence scope JSON must be an object.");
  }
  return { scope_note: trimmed };
}

export function GraphCanvas({
  programId,
  nodes,
  edges,
  selectedNodeId,
  canEditGraph,
  isApplyingPatch,
  onApplyGraphPatch,
  onSelectNode,
  onPassNode,
}: GraphCanvasProps) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [nodePositions, setNodePositions] = useState<Record<string, Point>>({});
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const zoomRef = useRef(zoom);
  const clickRef = useRef<{ nodeId: string | null; at: number }>({ nodeId: null, at: 0 });
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
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const firstNodeId = nodes[0]?.id ?? null;
  const layoutSignature = useMemo(() => buildLayoutSignature(nodes, edges), [nodes, edges]);
  const autoLayout = useMemo(() => buildAutoLayout(nodes, edges), [layoutSignature]);

  useEffect(() => {
    setNodePositions(autoLayout.positions);
    setZoom(1);
    zoomRef.current = 1;
    setPan({ x: 0, y: 0 });
  }, [autoLayout, layoutSignature]);

  useEffect(() => {
    zoomRef.current = zoom;
  }, [zoom]);

  const currentMaxX =
    Object.values(nodePositions).length > 0
      ? Math.max(...Object.values(nodePositions).map((position) => position.x))
      : 0;
  const currentMaxY =
    Object.values(nodePositions).length > 0
      ? Math.max(...Object.values(nodePositions).map((position) => position.y))
      : 0;
  const innerWidth = Math.max(autoLayout.width, currentMaxX + CARD_WIDTH + HORIZONTAL_PADDING);
  const innerHeight = Math.max(autoLayout.height, currentMaxY + CARD_HEIGHT + 120);

  const centerView = useCallback(
    (currentZoom = zoomRef.current) => {
      if (!canvasRef.current) {
        return;
      }

      const { clientWidth, clientHeight } = canvasRef.current;

      let targetX = 0;
      let targetY = 32;

      if (firstNodeId) {
        const firstNodePos = autoLayout.positions[firstNodeId] ?? { x: HORIZONTAL_PADDING, y: TOP_OFFSET };

        targetX = clientWidth / 2 - (firstNodePos.x + CARD_WIDTH / 2) * currentZoom;
        targetY = FIRST_NODE_VIEW_TOP_MARGIN - firstNodePos.y * currentZoom;
      } else {
        const graphWidth = innerWidth * currentZoom;
        const graphHeight = innerHeight * currentZoom;

        targetX = graphWidth > clientWidth ? 0 : (clientWidth - graphWidth) / 2;
        targetY = graphHeight > clientHeight ? 32 : (clientHeight - graphHeight) / 2;
      }

      setPan({ x: targetX, y: targetY });
    },
    [autoLayout.positions, firstNodeId, innerHeight, innerWidth],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      centerView(1);
    }, 10);
    return () => window.clearTimeout(timer);
  }, [centerView, layoutSignature]);

  function positionFor(node: GraphNode): Point {
    return nodePositions[node.id] ?? autoLayout.positions[node.id] ?? { x: HORIZONTAL_PADDING, y: TOP_OFFSET };
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
    setZoom(clamp(Number(nextZoom.toFixed(2)), 0.2, 2.2));
  }

  function zoomAroundPoint(nextZoom: number, viewportX: number, viewportY: number) {
    const clamped = clamp(Number(nextZoom.toFixed(2)), 0.2, 2.2);
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
      if (Math.abs(deltaX) > 6 || Math.abs(deltaY) > 6) {
        nodeDragRef.current.moved = true;
      }
      setNodePositions((current) => ({
        ...current,
        [nodeDragRef.current.nodeId as string]: {
          x: clamp(nodeDragRef.current.originX + deltaX, 24, innerWidth - CARD_WIDTH - 24),
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
      const clickedNodeId = nodeDragRef.current.nodeId;
      const moved = nodeDragRef.current.moved;
      nodeDragRef.current.active = false;
      nodeDragRef.current.nodeId = null;
      nodeDragRef.current.moved = false;
      event.currentTarget.releasePointerCapture(event.pointerId);
      if (!moved && clickedNodeId) {
        const clickedNode = nodeMap.get(clickedNodeId);
        if (clickedNode) {
          onSelectNode(clickedNode);
          const now = Date.now();
          if (clickRef.current.nodeId === clickedNodeId && now - clickRef.current.at < 320) {
            clickRef.current = { nodeId: null, at: 0 };
            if (canPassAndVerify(clickedNode)) {
              onPassNode(clickedNode);
            }
          } else {
            clickRef.current = { nodeId: clickedNodeId, at: now };
          }
        }
      }
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
        <div className="absolute left-4 top-4 z-10 rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">
          Program {programId}
        </div>

        <div className="absolute right-4 top-4 z-10 flex items-center gap-2">
          <button
            type="button"
            onClick={() => setIsEditorOpen(true)}
            disabled={!canEditGraph}
            className="flex h-10 items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 text-[11px] uppercase tracking-[0.16em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-45"
          >
            <Plus size={14} strokeWidth={1.8} />
            Add Node
          </button>
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
                setNodePositions(autoLayout.positions);
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
          <div className="relative" style={{ width: innerWidth, height: innerHeight }}>
            <svg className="absolute inset-0 h-full w-full" viewBox={`0 0 ${innerWidth} ${innerHeight}`}>
              {edges.map((edge) => {
                const source = nodeMap.get(edge.source);
                const target = nodeMap.get(edge.target);
                if (!source || !target) {
                  return null;
                }
                const active = source.status === "completed" && target.status !== "pending";
                const labelPosition = edgeLabelPosition(source, target);
                return (
                  <g key={`${edge.source}-${edge.target}-${edge.kind}`}>
                    <path
                      d={edgePath(source, target)}
                      fill="none"
                      stroke={active ? "var(--mw-text)" : "var(--mw-border-strong)"}
                      strokeOpacity={active ? 0.34 : 0.2}
                      strokeWidth="1.3"
                      strokeLinecap="round"
                      className={active ? "edge-flow" : ""}
                    />
                    {edge.kind !== "execution" ? (
                  <text
                    x={labelPosition.x}
                    y={labelPosition.y}
                    fill="var(--mw-subtle)"
                    fontSize="10"
                    letterSpacing="0.18em"
                    textAnchor="middle"
                    className="uppercase"
                  >
                    {humanizeBranch(edge.kind)}
                  </text>
                ) : null}
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
                        <ShieldCheck size={14} strokeWidth={1.8} className="text-[var(--mw-success)]" />
                      ) : node.status === "completed" ? (
                        <CheckCircle2 size={14} strokeWidth={1.8} className="text-[var(--mw-text)]" />
                      ) : (
                        <Circle size={14} strokeWidth={1.5} className="text-[var(--mw-subtle)]" />
                      )}
                    </div>

                    <div className="font-sans text-[19px] font-semibold leading-[1.05] tracking-[0.01em] text-[var(--mw-text)]">
                      {node.title}
                    </div>
                    <div className="mt-1.5 line-clamp-2 text-[12px] leading-5 text-[var(--mw-muted)]">
                      {node.subtitle}
                    </div>

                    <div className="mt-3 flex items-center justify-between text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">
                      <span className="flex items-center gap-1">
                        <FileText size={12} strokeWidth={1.6} />
                        {node.evidence_refs.length}
                      </span>
                      <span>{node.status}</span>
                    </div>

                    <div className="mt-auto flex flex-wrap gap-1.5 border-t border-[var(--mw-border)] pt-2.5">
                      <span className="rounded-full border border-[var(--mw-border)] px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-[var(--mw-text)]">
                        {executorLabel(node.executor_type)}
                      </span>
                      {approvalRequired(node) ? (
                        <span className="rounded-full border border-[var(--mw-border)] px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-[var(--mw-text)]">
                          Approval
                        </span>
                      ) : null}
                      {(node.expansion_contracts ?? []).includes("expand_subgraph") ? (
                        <span className="rounded-full border border-[var(--mw-border)] px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-[var(--mw-text)]">
                          Expanded
                        </span>
                      ) : null}
                      {delegatedCount(node) > 0 ? (
                        <span className="rounded-full border border-[var(--mw-border)] px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-[var(--mw-text)]">
                          Delegated {delegatedCount(node)}
                        </span>
                      ) : null}
                    </div>
                  </div>
                </motion.button>
              );
            })}
          </div>
        </div>
      </div>

      <ManualNodeEditorModal
        open={isEditorOpen}
        nodes={nodes}
        edges={edges}
        canEditGraph={canEditGraph}
        isApplyingPatch={isApplyingPatch}
        onClose={() => setIsEditorOpen(false)}
        onApplyGraphPatch={onApplyGraphPatch}
      />
    </section>
  );
}

interface ManualNodeEditorModalProps {
  open: boolean;
  nodes: GraphNode[];
  edges: GraphEdge[];
  canEditGraph: boolean;
  isApplyingPatch: boolean;
  onClose: () => void;
  onApplyGraphPatch: (request: GraphPatchRequest, focusNodeId?: string | null) => Promise<void>;
}

function ManualNodeEditorModal({
  open,
  nodes,
  edges,
  canEditGraph,
  isApplyingPatch,
  onClose,
  onApplyGraphPatch,
}: ManualNodeEditorModalProps) {
  const nodeOptions = useMemo(
    () =>
      [...nodes]
        .sort((left, right) => left.title.localeCompare(right.title))
        .map((node) => ({ id: node.id, label: `${node.title} (${node.id})` })),
    [nodes],
  );
  const [title, setTitle] = useState("");
  const [purpose, setPurpose] = useState("");
  const [instruction, setInstruction] = useState("");
  const [operationType, setOperationType] = useState("analyze");
  const [executorType, setExecutorType] = useState("llm_operator");
  const [connectionMode, setConnectionMode] = useState<ConnectionMode>("after_node");
  const [referenceNodeId, setReferenceNodeId] = useState("");
  const [betweenTargetNodeId, setBetweenTargetNodeId] = useState("");
  const [requireApproval, setRequireApproval] = useState(false);
  const [requiredApprovals, setRequiredApprovals] = useState(1);
  const [approvedBy, setApprovedBy] = useState("");
  const [evidenceScopeInput, setEvidenceScopeInput] = useState("");
  const [autoRerun, setAutoRerun] = useState(true);
  const [executorProfile, setExecutorProfile] = useState("general");
  const [maxChildAgents, setMaxChildAgents] = useState(2);
  const [maxRecursionDepth, setMaxRecursionDepth] = useState(1);
  const [childTokenBudget, setChildTokenBudget] = useState(4000);
  const [delegatedSummaryRequired, setDelegatedSummaryRequired] = useState(true);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    if (!referenceNodeId && nodeOptions[0]) {
      setReferenceNodeId(nodeOptions[0].id);
    }
  }, [nodeOptions, open, referenceNodeId]);

  const betweenTargets = useMemo(() => {
    if (!referenceNodeId) {
      return [];
    }
    const targets = edges
      .filter((edge) => edge.source === referenceNodeId)
      .map((edge) => nodes.find((node) => node.id === edge.target))
      .filter((node): node is GraphNode => Boolean(node))
      .sort((left, right) => left.title.localeCompare(right.title));
    return targets.map((node) => ({ id: node.id, label: `${node.title} (${node.id})` }));
  }, [edges, nodes, referenceNodeId]);

  useEffect(() => {
    if (connectionMode !== "between_nodes") {
      return;
    }
    if (!betweenTargets.some((target) => target.id === betweenTargetNodeId)) {
      setBetweenTargetNodeId(betweenTargets[0]?.id ?? "");
    }
  }, [betweenTargetNodeId, betweenTargets, connectionMode]);

  useEffect(() => {
    if (!open) {
      return;
    }
    setLocalError(null);
  }, [open, connectionMode, referenceNodeId, betweenTargetNodeId]);

  const referenceNodeLabel = nodeOptions.find((node) => node.id === referenceNodeId)?.label ?? "a selected node";
  const betweenTargetLabel = betweenTargets.find((node) => node.id === betweenTargetNodeId)?.label ?? "the downstream node";

  async function handleSubmit() {
    if (!title.trim()) {
      setLocalError("A node name is required.");
      return;
    }
    if (!instruction.trim()) {
      setLocalError("An instruction is required.");
      return;
    }
    if (!referenceNodeId) {
      setLocalError("Choose where the node should connect.");
      return;
    }
    if (connectionMode === "between_nodes" && !betweenTargetNodeId) {
      setLocalError("Choose the downstream node for the between placement.");
      return;
    }

    try {
      const nodeId = slugifyNodeId(title, new Set(nodes.map((node) => node.id)));
      const evidenceScope = parseEvidenceScope(evidenceScopeInput);
      const nodePayload: Record<string, unknown> = {
        id: nodeId,
        title: title.trim(),
        subtitle: purpose.trim() || "Manual graph edit",
        operation_type: operationType,
        instruction: instruction.trim(),
        executor_type: executorType,
        required_approvals: requireApproval ? Math.max(requiredApprovals, 1) : 0,
        evidence_scope: evidenceScope,
      };
      if (executorType === "agent_operator") {
        nodePayload.executor_profile = executorProfile;
        nodePayload.max_child_agents = Math.max(maxChildAgents, 1);
        nodePayload.max_recursion_depth = Math.max(maxRecursionDepth, 1);
        nodePayload.child_token_budget = Math.max(childTokenBudget, 1000);
        nodePayload.delegated_summary_required = delegatedSummaryRequired;
      }

      let request: GraphPatchRequest;
      if (connectionMode === "between_nodes") {
        request = {
          patch_type: "insert_node_between",
          target_node_id: betweenTargetNodeId,
          change_reason: `Insert ${title.trim()} between ${referenceNodeId} and ${betweenTargetNodeId}.`,
          requested_by: "dashboard-user",
          approved_by: approvedBy.trim() || null,
          payload: {
            source_node_id: referenceNodeId,
            target_node_id: betweenTargetNodeId,
            node: nodePayload,
          },
          auto_rerun: autoRerun,
        };
      } else {
        request = {
          patch_type: "add_node",
          target_node_id: referenceNodeId,
          change_reason: `Add ${title.trim()} with ${connectionMode.replace(/_/g, " ")} placement.`,
          requested_by: "dashboard-user",
          approved_by: approvedBy.trim() || null,
          payload: {
            placement: connectionMode,
            reference_node_id: referenceNodeId,
            node: nodePayload,
          },
          auto_rerun: autoRerun,
        };
      }

      setLocalError(null);
      await onApplyGraphPatch(request, nodeId);
      onClose();
      setTitle("");
      setPurpose("");
      setInstruction("");
      setEvidenceScopeInput("");
      setApprovedBy("");
      setRequireApproval(false);
      setRequiredApprovals(1);
      setExecutorType("llm_operator");
      setExecutorProfile("general");
      setMaxChildAgents(2);
      setMaxRecursionDepth(1);
      setChildTokenBudget(4000);
      setDelegatedSummaryRequired(true);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "The node could not be added.");
    }
  }

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 lg:p-8">
      <div
        className="absolute inset-0 bg-[color:rgba(0,0,0,0.36)] backdrop-blur-md"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Add node"
        className="relative z-10 flex h-[80vh] w-[min(80vw,1280px)] flex-col overflow-hidden rounded-[28px] border border-[var(--mw-border)] bg-[var(--mw-page)] shadow-[0_40px_120px_rgba(0,0,0,0.35)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--mw-border)] px-5 py-4">
          <div>
            <div className="text-[10px] uppercase tracking-[0.24em] text-[var(--mw-subtle)]">Manual Graph Editing</div>
            <div className="mt-1 font-sans text-[28px] font-semibold leading-none text-[var(--mw-text)]">Add Node</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-10 w-10 items-center justify-center rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)]"
          >
            <X size={16} strokeWidth={1.8} />
          </button>
        </div>

        <div className="grid min-h-0 flex-1 gap-0 lg:grid-cols-[1.45fr_0.95fr]">
          <div className="min-h-0 overflow-y-auto border-r border-[var(--mw-border)] px-5 py-5">
            <div className="grid gap-4 lg:grid-cols-2">
              <label className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4 lg:col-span-2">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Node Name</div>
                <input
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder="Controls Review"
                  className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                />
              </label>

              <label className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4 lg:col-span-2">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Purpose</div>
                <input
                  value={purpose}
                  onChange={(event) => setPurpose(event.target.value)}
                  className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                />
              </label>

              <label className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4 lg:col-span-2">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Instruction</div>
                <textarea
                  value={instruction}
                  onChange={(event) => setInstruction(event.target.value)}
                  rows={4}
                  placeholder="Explain exactly what this node should do and what evidence it should rely on."
                  className="mt-3 w-full resize-none rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] leading-6 text-[var(--mw-text)] outline-none"
                />
              </label>

              <label className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Operation Type</div>
                <select
                  value={operationType}
                  onChange={(event) => setOperationType(event.target.value)}
                  className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                >
                  <option value="analyze">Analyze</option>
                  <option value="verify">Verify</option>
                  <option value="synthesize">Synthesize</option>
                  <option value="aggregate">Aggregate</option>
                </select>
              </label>

              <label className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Executor Type</div>
                <select
                  value={executorType}
                  onChange={(event) => setExecutorType(event.target.value)}
                  className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                >
                  <option value="llm_operator">LLM</option>
                  <option value="agent_operator">Agent</option>
                  <option value="tool_operator">Tool</option>
                  <option value="human_operator">Human</option>
                </select>
              </label>

              <label className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Placement</div>
                <select
                  value={connectionMode}
                  onChange={(event) => setConnectionMode(event.target.value as ConnectionMode)}
                  className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                >
                  <option value="after_node">After Another Node</option>
                  <option value="before_node">Before Another Node</option>
                  <option value="between_nodes">Between Two Nodes</option>
                  <option value="branch_from">As A Branch From A Node</option>
                </select>
              </label>

              <label className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">
                  {connectionMode === "between_nodes" ? "Source Node" : "Reference Node"}
                </div>
                <select
                  value={referenceNodeId}
                  onChange={(event) => setReferenceNodeId(event.target.value)}
                  className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                >
                  {nodeOptions.map((node) => (
                    <option key={node.id} value={node.id}>
                      {node.label}
                    </option>
                  ))}
                </select>
              </label>

              {connectionMode === "between_nodes" ? (
                <label className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Downstream Node</div>
                  <select
                    value={betweenTargetNodeId}
                    onChange={(event) => setBetweenTargetNodeId(event.target.value)}
                    className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                  >
                    {betweenTargets.map((node) => (
                      <option key={node.id} value={node.id}>
                        {node.label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}

              {executorType === "agent_operator" ? (
                <>
                  <label className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
                    <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Agent Profile</div>
                    <select
                      value={executorProfile}
                      onChange={(event) => setExecutorProfile(event.target.value)}
                      className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                    >
                      <option value="general">General</option>
                      <option value="forensic">Forensic</option>
                      <option value="controls">Controls</option>
                      <option value="revenue">Revenue</option>
                    </select>
                  </label>
                  <label className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
                    <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Max Child Agents</div>
                    <input
                      type="number"
                      min={1}
                      value={maxChildAgents}
                      onChange={(event) => setMaxChildAgents(Number(event.target.value))}
                      className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                    />
                  </label>
                  <label className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
                    <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Max Recursion Depth</div>
                    <input
                      type="number"
                      min={1}
                      value={maxRecursionDepth}
                      onChange={(event) => setMaxRecursionDepth(Number(event.target.value))}
                      className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                    />
                  </label>
                  <label className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
                    <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Child Token Budget</div>
                    <input
                      type="number"
                      min={1000}
                      step={500}
                      value={childTokenBudget}
                      onChange={(event) => setChildTokenBudget(Number(event.target.value))}
                      className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                    />
                  </label>
                </>
              ) : null}

              <label className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4 lg:col-span-2">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Evidence Scope</div>
                <textarea
                  value={evidenceScopeInput}
                  onChange={(event) => setEvidenceScopeInput(event.target.value)}
                  rows={3}
                  className="mt-3 w-full resize-none rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] leading-6 text-[var(--mw-text)] outline-none"
                />
              </label>
            </div>
          </div>

          <div className="min-h-0 overflow-y-auto px-5 py-5">
            <div className="space-y-4">
              <section className="rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Placement Preview</div>
                <div className="mt-3 font-sans text-[24px] font-semibold leading-none text-[var(--mw-text)]">
                  {title.trim() || "New Node"}
                </div>
                <div className="mt-3 text-[14px] leading-7 text-[var(--mw-muted)]">
                  {connectionMode === "between_nodes"
                    ? `This will insert the node between ${referenceNodeLabel} and ${betweenTargetLabel}.`
                    : connectionMode === "before_node"
                      ? `This will place the node immediately before ${referenceNodeLabel}.`
                      : connectionMode === "after_node"
                        ? `This will place the node immediately after ${referenceNodeLabel}.`
                        : `This will create a branch from ${referenceNodeLabel}.`}
                </div>
                <div className="mt-3 text-[12px] uppercase tracking-[0.16em] text-[var(--mw-subtle)]">
                  {operationLabel(operationType)} · {executorLabel(executorType)}
                </div>
              </section>

              <section className="rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Governance</div>
                <label className="mt-3 flex items-center gap-2 text-[12px] uppercase tracking-[0.14em] text-[var(--mw-subtle)]">
                  <input
                    type="checkbox"
                    checked={requireApproval}
                    onChange={(event) => setRequireApproval(event.target.checked)}
                    className="h-4 w-4 accent-[var(--mw-accent)]"
                  />
                  Require approval before finalization
                </label>
                {requireApproval ? (
                  <label className="mt-3 block">
                    <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Required Approvals</div>
                    <input
                      type="number"
                      min={1}
                      value={requiredApprovals}
                      onChange={(event) => setRequiredApprovals(Number(event.target.value))}
                      className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                    />
                  </label>
                ) : null}
                <label className="mt-3 block">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Approver ID (Optional)</div>
                  <input
                    value={approvedBy}
                    onChange={(event) => setApprovedBy(event.target.value)}
                    placeholder="lead-reviewer"
                    className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none"
                  />
                </label>
                <label className="mt-3 flex items-center gap-2 text-[12px] uppercase tracking-[0.14em] text-[var(--mw-subtle)]">
                  <input
                    type="checkbox"
                    checked={autoRerun}
                    onChange={(event) => setAutoRerun(event.target.checked)}
                    className="h-4 w-4 accent-[var(--mw-accent)]"
                  />
                  Auto rerun affected scope
                </label>
                {executorType === "agent_operator" ? (
                  <label className="mt-3 flex items-center gap-2 text-[12px] uppercase tracking-[0.14em] text-[var(--mw-subtle)]">
                    <input
                      type="checkbox"
                      checked={delegatedSummaryRequired}
                      onChange={(event) => setDelegatedSummaryRequired(event.target.checked)}
                      className="h-4 w-4 accent-[var(--mw-accent)]"
                    />
                    Require delegated summary return
                  </label>
                ) : null}
              </section>

              <section className="rounded-[20px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Manual Editing Flow</div>
                <div className="mt-3 space-y-2 text-[14px] leading-7 text-[var(--mw-muted)]">
                  <div>1. Define the node and its purpose.</div>
                  <div>2. Choose how it should attach to the graph.</div>
                  <div>3. Submit a structured patch to the backend.</div>
                  <div>4. Refresh the graph with a full layout recompute.</div>
                </div>
              </section>

              {localError ? (
                <div className="rounded-[18px] border border-[color:rgba(190,111,93,0.36)] bg-[color:rgba(190,111,93,0.14)] px-4 py-3 text-[13px] leading-6 text-[color:rgba(251,236,230,0.88)]">
                  {localError}
                </div>
              ) : null}

              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => void handleSubmit()}
                  disabled={!canEditGraph || isApplyingPatch || (connectionMode === "between_nodes" && betweenTargets.length === 0)}
                  className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-5 py-2.5 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-45"
                >
                  {isApplyingPatch ? "Applying..." : "Create Node"}
                </button>
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-full border border-[var(--mw-border)] bg-transparent px-5 py-2.5 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-subtle)] transition hover:border-[var(--mw-accent)] hover:text-[var(--mw-text)]"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
