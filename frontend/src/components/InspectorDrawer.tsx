import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { FileText, ShieldCheck, X } from "lucide-react";
import type { DocumentRecord, GraphNode } from "../types";

interface InspectorDrawerProps {
  node: GraphNode;
  documents: DocumentRecord[];
  onClose: () => void;
}

function humanizeLabel(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function primitiveText(value: unknown) {
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? `${value}` : value.toFixed(2);
  }
  return String(value);
}

function isEmptyValue(value: unknown) {
  if (value == null || value === "") {
    return true;
  }
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  if (typeof value === "object") {
    return Object.keys(value as Record<string, unknown>).length === 0;
  }
  return false;
}

function ReadableValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (isEmptyValue(value)) {
    return <div className="text-sm text-[var(--mw-subtle)]">No structured details were recorded.</div>;
  }

  if (Array.isArray(value)) {
    const primitiveList = value.every((item) => item == null || typeof item !== "object");
    if (primitiveList) {
      return (
        <div className="space-y-2">
          {value.map((item, index) => (
            <div key={`${primitiveText(item)}-${index}`} className="flex gap-3 text-[13px] leading-6 text-[var(--mw-muted)]">
              <span className="mt-2 h-1.5 w-1.5 rounded-full bg-[var(--mw-accent)]" />
              <span>{primitiveText(item)}</span>
            </div>
          ))}
        </div>
      );
    }

    return (
      <div className="space-y-3">
        {value.map((item, index) => (
          <div key={index} className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
            <div className="mb-2 text-[10px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">
              Item {index + 1}
            </div>
            <ReadableValue value={item} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, entryValue]) => !isEmptyValue(entryValue));
    if (entries.length === 0) {
      return <div className="text-sm text-[var(--mw-subtle)]">No structured details were recorded.</div>;
    }

    return (
      <div className={depth === 0 ? "space-y-3" : "space-y-2.5"}>
        {entries.map(([key, entryValue]) => (
          <div
            key={key}
            className={depth === 0 ? "rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3" : ""}
          >
            <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">
              {humanizeLabel(key)}
            </div>
            <div className="mt-2">
              <ReadableValue value={entryValue} depth={depth + 1} />
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className={`${depth === 0 ? "font-serif text-[18px] leading-7 text-[var(--mw-text)]" : "text-[13px] leading-6 text-[var(--mw-muted)]"}`}>
      {primitiveText(value)}
    </div>
  );
}

function Section({
  title,
  eyebrow,
  children,
}: {
  title: string;
  eyebrow: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[22px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
      <div className="text-[10px] uppercase tracking-[0.24em] text-[var(--mw-subtle)]">{eyebrow}</div>
      <div className="mt-2 font-serif text-[24px] leading-none text-[var(--mw-text)]">{title}</div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function InspectorDrawer({ node, documents, onClose }: InspectorDrawerProps) {
  const evidenceRefsByDocument = new Map(
    node.evidence_refs.map((reference) => [reference.document_id, reference]),
  );
  const snippets = documents
    .filter((document) => evidenceRefsByDocument.has(document.id))
    .map((document) => ({
      id: document.id,
      name: document.name,
      text: document.extracted_text.slice(0, 220),
      evidence: evidenceRefsByDocument.get(document.id),
    }));

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[18px] bg-[var(--mw-panel)]">
      <div className="border-b border-[var(--mw-border)] px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-[11px] font-medium uppercase tracking-[0.26em] text-[var(--mw-accent)]">
              Trace Inspector
            </div>
            <div className="mt-1 font-serif text-[26px] leading-none tracking-[-0.03em] text-[var(--mw-text)]">
              {node.title}
            </div>
            <div className="mt-2 text-[13px] leading-6 text-[var(--mw-subtle)]">
              {node.subtitle}
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="flex h-10 w-10 items-center justify-center rounded-2xl border border-[var(--mw-border)] bg-[var(--mw-panel)] text-[var(--mw-muted)] transition hover:text-[var(--mw-text)]"
          >
            <X size={16} strokeWidth={1.8} />
          </button>
        </div>
      </div>

      <motion.div
        key={node.id}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.22, ease: [0.2, 1, 0.2, 1] }}
        className="flex-1 space-y-4 overflow-y-auto px-5 py-4"
      >
        <section className="rounded-[22px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
            <div className="mb-3 flex items-center gap-2 text-[var(--mw-accent)]">
              <ShieldCheck size={15} strokeWidth={1.7} />
              <span className="text-[11px] uppercase tracking-[0.22em]">Verification</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
                <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">Status</div>
                <div className="mt-2 font-serif text-[20px] text-[var(--mw-text)]">{humanizeLabel(node.verification_status)}</div>
              </div>
              <div className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
                <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--mw-subtle)]">Latency</div>
                <div className="mt-2 font-serif text-[20px] text-[var(--mw-text)]">
                  {node.latency_ms ? `${(node.latency_ms / 1000).toFixed(2)}s` : "--"}
                </div>
              </div>
            </div>
        </section>

        <Section title="Instruction" eyebrow="Current Step">
          <div className="font-serif text-[18px] leading-7 text-[var(--mw-text)]">{node.instruction}</div>
          {node.success_criteria.length > 0 && (
            <div className="mt-4">
              <div className="text-[10px] uppercase tracking-[0.22em] text-[var(--mw-subtle)]">Success Criteria</div>
              <div className="mt-3">
                <ReadableValue value={node.success_criteria} />
              </div>
            </div>
          )}
        </Section>

        <Section title="Incoming Context" eyebrow="Inputs">
          {Object.keys(node.inputs).length > 0 ? (
            <ReadableValue value={node.inputs} />
          ) : (
            <div className="text-[14px] leading-7 text-[var(--mw-muted)]">
              This node begins from the prompt, program rules, and retrieved evidence rather than upstream node outputs.
            </div>
          )}
        </Section>

        <Section title="Recorded Output" eyebrow="Outputs">
          <ReadableValue value={node.output} />
        </Section>

        <Section title="Evidence" eyebrow="Linked Sources">
          <div className="space-y-3">
            {snippets.length > 0 ? (
              snippets.map((snippet) => (
                <div key={snippet.id} className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-3">
                  <div className="mb-2 flex items-center gap-2 text-[var(--mw-text)]">
                    <FileText size={14} strokeWidth={1.7} />
                    <span className="text-[13px]">{snippet.name}</span>
                  </div>
                  <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">
                    {snippet.evidence?.page ? `Page ${snippet.evidence.page}` : "Chunk-linked evidence"}
                  </div>
                  <div className="font-serif text-[15px] leading-7 text-[var(--mw-muted)]">{snippet.text}</div>
                </div>
              ))
            ) : (
              <div className="text-[14px] leading-7 text-[var(--mw-subtle)]">No evidence is currently linked to this node.</div>
            )}
          </div>
        </Section>
      </motion.div>
    </section>
  );
}
