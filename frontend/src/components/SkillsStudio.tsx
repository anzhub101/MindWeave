import type { ReactNode } from "react";
import { FileCode2, FlaskConical, Play, Save, Sparkles } from "lucide-react";
import type { SkillArtifact, SkillSummary, SkillTestResult } from "../types";

interface SkillsStudioProps {
  skills: SkillSummary[];
  draft: SkillArtifact;
  selectedSkillId: string | null;
  isLoadingSkills: boolean;
  isGenerating: boolean;
  isTesting: boolean;
  isSaving: boolean;
  testResult: SkillTestResult | null;
  notice: { tone: "info" | "error"; message: string } | null;
  onSelectSkill: (skillId: string) => Promise<void>;
  onCreateDraft: () => void;
  onDraftChange: (patch: Partial<SkillArtifact>) => void;
  onGenerate: (prompt: string, language: string, skillType: string) => Promise<void>;
  onTest: () => Promise<void>;
  onSave: () => Promise<void>;
}

function humanize(value: string) {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
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
    <section className="rounded-[24px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-5">
      <div className="text-[10px] uppercase tracking-[0.24em] text-[var(--mw-subtle)]">{eyebrow}</div>
      <div className="mt-2 font-sans text-[24px] font-semibold leading-none text-[var(--mw-text)]">{title}</div>
      <div className="mt-5">{children}</div>
    </section>
  );
}

export function SkillsStudio({
  skills,
  draft,
  selectedSkillId,
  isLoadingSkills,
  isGenerating,
  isTesting,
  isSaving,
  testResult,
  notice,
  onSelectSkill,
  onCreateDraft,
  onDraftChange,
  onGenerate,
  onTest,
  onSave,
}: SkillsStudioProps) {
  return (
    <div className="flex min-h-0 flex-1 gap-4 overflow-hidden px-4 pb-4 pt-4">
      <aside className="flex w-[320px] shrink-0 flex-col rounded-[24px] border border-[var(--mw-border)] bg-[var(--mw-panel)] p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[10px] uppercase tracking-[0.24em] text-[var(--mw-subtle)]">Skill Library</div>
            <div className="mt-2 font-sans text-[22px] font-semibold leading-none text-[var(--mw-text)]">Saved Skills</div>
          </div>
          <button
            type="button"
            onClick={onCreateDraft}
            className="rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)]"
          >
            New Draft
          </button>
        </div>

        <div className="mt-4 flex-1 space-y-3 overflow-y-auto pr-1">
          {isLoadingSkills ? (
            <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3 text-[14px] leading-7 text-[var(--mw-muted)]">
              Loading skills...
            </div>
          ) : skills.length ? (
            skills.map((skill) => {
              const active = skill.skill_id === selectedSkillId;
              return (
                <button
                  key={skill.skill_id}
                  type="button"
                  onClick={() => void onSelectSkill(skill.skill_id)}
                  className={`w-full rounded-[18px] border px-4 py-4 text-left transition ${
                    active
                      ? "border-[var(--mw-accent)] bg-[var(--mw-accent-soft)]"
                      : "border-[var(--mw-border)] bg-[var(--mw-node)] hover:border-[var(--mw-accent)]"
                  }`}
                >
                  <div className="flex items-center gap-2 text-[var(--mw-accent)]">
                    <FileCode2 size={14} />
                    <div className="text-[11px] uppercase tracking-[0.18em]">{humanize(skill.skill_type)}</div>
                  </div>
                  <div className="mt-3 font-sans text-[18px] font-semibold text-[var(--mw-text)]">{skill.name}</div>
                  <div className="mt-2 text-[13px] leading-6 text-[var(--mw-muted)]">{skill.description || "No description provided."}</div>
                  <div className="mt-3 flex flex-wrap gap-2 font-mono text-[11px] text-[var(--mw-subtle)]">
                    <span>{skill.language}</span>
                    <span>{skill.version}</span>
                  </div>
                </button>
              );
            })
          ) : (
            <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3 text-[14px] leading-7 text-[var(--mw-muted)]">
              No saved skills are available yet. Generate a draft from the studio and save it to deploy it on a node.
            </div>
          )}
        </div>
      </aside>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1">
        {notice ? (
          <div
            className={`rounded-[18px] border px-4 py-3 text-[13px] leading-6 ${
              notice.tone === "error"
                ? "border-[rgba(190,111,93,0.28)] bg-[rgba(190,111,93,0.10)] text-[var(--mw-text)]"
                : "border-[var(--mw-border)] bg-[var(--mw-node)] text-[var(--mw-muted)]"
            }`}
          >
            {notice.message}
          </div>
        ) : null}

        <Section title="Skill Studio" eyebrow="Prompt, Test, Improve, Save">
          <div className="grid gap-4 xl:grid-cols-[0.92fr_1.08fr]">
            <div className="space-y-4">
              <label className="block rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Name</div>
                <input
                  value={draft.name}
                  onChange={(event) => onDraftChange({ name: event.target.value })}
                  className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
                />
              </label>

              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Skill ID</div>
                  <input
                    value={draft.skill_id}
                    onChange={(event) => onDraftChange({ skill_id: event.target.value })}
                    className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 font-mono text-[14px] text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
                  />
                </label>
                <label className="block rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Version</div>
                  <input
                    value={draft.version}
                    onChange={(event) => onDraftChange({ version: event.target.value })}
                    className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 font-mono text-[14px] text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
                  />
                </label>
              </div>

              <div className="grid gap-4 sm:grid-cols-3">
                <label className="block rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Language</div>
                  <select
                    value={draft.language}
                    onChange={(event) => onDraftChange({ language: event.target.value })}
                    className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
                  >
                    <option value="python">Python</option>
                    <option value="javascript">JavaScript</option>
                  </select>
                </label>
                <label className="block rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Type</div>
                  <select
                    value={draft.skill_type}
                    onChange={(event) => onDraftChange({ skill_type: event.target.value })}
                    className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
                  >
                    <option value="script">Script</option>
                    <option value="program">Program</option>
                    <option value="checker">Checker</option>
                    <option value="extractor">Extractor</option>
                  </select>
                </label>
                <label className="block rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Entrypoint</div>
                  <input
                    value={draft.entrypoint_filename}
                    onChange={(event) => onDraftChange({ entrypoint_filename: event.target.value })}
                    className="mt-3 w-full rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 font-mono text-[14px] text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
                  />
                </label>
              </div>

              <label className="block rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Description</div>
                <textarea
                  value={draft.description}
                  onChange={(event) => onDraftChange({ description: event.target.value })}
                  rows={4}
                  className="mt-3 w-full resize-none rounded-[12px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-3 py-2 text-[14px] leading-6 text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
                />
              </label>
            </div>

            <div className="space-y-4">
              <label className="block rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                <div className="flex items-center gap-2 text-[var(--mw-accent)]">
                  <Sparkles size={15} />
                  <div className="text-[11px] uppercase tracking-[0.18em]">Skill Request</div>
                </div>
                <textarea
                  value={draft.description}
                  onChange={(event) => onDraftChange({ description: event.target.value })}
                  rows={5}
                  placeholder="Build a script that validates revenue rows, normalizes dates, and returns failed records as JSON."
                  className="mt-3 w-full resize-none rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-3 text-[14px] leading-6 text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
                />
                <button
                  type="button"
                  onClick={() => void onGenerate(draft.description, draft.language, draft.skill_type)}
                  disabled={isGenerating || !draft.description.trim()}
                  className="mt-4 inline-flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Sparkles size={14} />
                  {isGenerating ? "Generating..." : draft.code.trim() ? "Improve Draft" : "Generate Draft"}
                </button>
              </label>

              <label className="block rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                <div className="flex items-center gap-2 text-[var(--mw-accent)]">
                  <FlaskConical size={15} />
                  <div className="text-[11px] uppercase tracking-[0.18em]">Test Input</div>
                </div>
                <textarea
                  value={draft.test_input}
                  onChange={(event) => onDraftChange({ test_input: event.target.value })}
                  rows={5}
                  className="mt-3 w-full resize-none rounded-[14px] border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-3 font-mono text-[13px] leading-6 text-[var(--mw-text)] outline-none transition focus:border-[var(--mw-accent)]"
                />
                <div className="mt-4 flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={() => void onTest()}
                    disabled={isTesting || !draft.code.trim()}
                    className="inline-flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Play size={14} />
                    {isTesting ? "Running..." : "Test Skill"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void onSave()}
                    disabled={isSaving || !draft.code.trim() || !draft.skill_id.trim()}
                    className="inline-flex items-center gap-2 rounded-full border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-2 text-[12px] uppercase tracking-[0.18em] text-[var(--mw-text)] transition hover:border-[var(--mw-accent)] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Save size={14} />
                    {isSaving ? "Saving..." : "Save Skill"}
                  </button>
                </div>
              </label>
            </div>
          </div>
        </Section>

        <Section title="Source Code" eyebrow="Editable Draft">
          <textarea
            value={draft.code}
            onChange={(event) => onDraftChange({ code: event.target.value })}
            rows={24}
            className="min-h-[420px] w-full resize-y rounded-[18px] border border-[var(--mw-border)] bg-[#11161f] px-4 py-4 font-mono text-[13px] leading-6 text-[#dce6f7] outline-none transition focus:border-[var(--mw-accent)]"
          />
          {draft.notes.length ? (
            <div className="mt-4 grid gap-2">
              {draft.notes.map((note) => (
                <div key={note} className="rounded-[16px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3 text-[13px] leading-6 text-[var(--mw-muted)]">
                  {note}
                </div>
              ))}
            </div>
          ) : null}
        </Section>

        <Section title="Test Output" eyebrow="Execution Result">
          {testResult ? (
            <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
              <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Status</div>
                <div className="mt-3 font-sans text-[24px] font-semibold text-[var(--mw-text)]">
                  {testResult.passed ? "Passed" : "Failed"}
                </div>
                <div className="mt-2 font-mono text-[12px] leading-6 text-[var(--mw-subtle)]">
                  Exit code: {testResult.exit_code}
                  <br />
                  {testResult.command.join(" ")}
                </div>
              </div>
              <div className="grid gap-4">
                <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Stdout</div>
                  <pre className="mt-3 overflow-x-auto whitespace-pre-wrap font-mono text-[12px] leading-6 text-[var(--mw-text)]">
                    {testResult.stdout || "// no stdout"}
                  </pre>
                </div>
                <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] p-4">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--mw-subtle)]">Stderr</div>
                  <pre className="mt-3 overflow-x-auto whitespace-pre-wrap font-mono text-[12px] leading-6 text-[var(--mw-text)]">
                    {testResult.stderr || "// no stderr"}
                  </pre>
                </div>
              </div>
            </div>
          ) : (
            <div className="rounded-[18px] border border-[var(--mw-border)] bg-[var(--mw-node)] px-4 py-3 text-[14px] leading-7 text-[var(--mw-muted)]">
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}
