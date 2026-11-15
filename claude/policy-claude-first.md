# Ultracode × Antigravity: routing policy for this session (claude-first)

This session pairs Claude Code ultracode with the user's `claude-code-setup` agent fleet (`esploratore`, `meccanico`, `esecutore`, `analista`) and Antigravity UltraCode mode from agy-kit (Gemini with the `ultracode` skill, orchestrating Gemini Flash subagents). Claude does the work by default and Antigravity is used on request or to spare Claude quota:

- **Complex reasoning and orchestration stay on Claude Opus (you)**: architecture, complex reasoning, cross-source synthesis, verification, judging, and any decision where an error would be costly or subtle.
- **Delegate only when justified (`CLAUDE.md` rule)**: subagents pay 20–40k fixed startup tokens and grow at every turn. Delegate **only if** (at least one): there is $>40\text{k}$ tokens of material to read; there are $>3$ independent parallelizable steps; or an independent adversarial judgment is needed. Otherwise work inline. Group related tasks into **one** agent with a self-contained prompt requesting a dense report.
- **Route delegated Claude tasks to the user's specialized agents (`~/.claude/agents/`)**:
  - **`esploratore`** (Haiku, high, read-only): broad searches and codebase exploration when only the conclusion is needed. First choice for reading.
  - **`meccanico`** (Haiku, low; or `model: 'haiku'` in workflows): simple, mechanical work without judgment (downloads, file checks, listings, reformatting, simple extraction with a clear format, running a command and reporting its output).
  - **`esecutore`** (Sonnet, high): the rest of delegated operational work (code implementation, refactors, debugging, tests). Pass `effort: 'medium'` for targeted searches and simple edits, `xhigh` for hard bugs, broad refactors, concurrency and security (`max` only after a failure at `xhigh`).
  - **`analista`** (Opus, xhigh; `max` only for hard final verdicts): complex analysis and synthesis across multiple sources.
  - Subagents without explicit `model` run on Sonnet (`CLAUDE_CODE_SUBAGENT_MODEL=sonnet`); built-in `Explore` and `Plan` are disabled because they inherit Opus.
- **Antigravity is used only when the user asks for it, or when sparing Claude quota is the point** (for example a large batch of independent tasks the user wants kept off the Claude budget). Do not pick it by default and do not use it for work where quality matters more than quota: its output on analytical work has been unreliable (keyword-filter scripts instead of reading, invented quotes), so verify every report against the real files.
- You reach Antigravity only through the `antigravity` subagent, which relays one task to the `mcp__antigravity__delegate` tool and returns a JSON report.

## How to route

- A quick look to scope the work or to check a claim (a directory listing, one short file, one targeted search, `git status` / `git diff`) is yours (inline).
- Operational coding, debugging and multi-step implementation go to `esecutore` (Sonnet); broad read-only exploration goes to `esploratore` (Haiku); mechanical leaves go to `meccanico` (Haiku, or `model: 'haiku'` on `agent()` calls). Give Haiku complete, unambiguous instructions and check its output; if a Haiku task fails once, redo it on `esecutore` (Sonnet) or Opus instead of resending.
- Deep multi-source synthesis or adversarial judging stays with Opus (you) or `analista`.
- Tasks that need tools only Claude has in this session (MCP connectors such as Google Drive, Gmail, Calendar, Notion, document tools; `Artifact` is excluded by default unless reopened with `ultra-ag -Artifact`) are yours, never Haiku's or Antigravity's.
- When the user does ask for Antigravity ("delega a Gemini", "usa Antigravity"), or you propose it to spare Claude quota and the user agrees, follow the rest of this document for that task.

## Two kinds of task

- **Read-only** (exploration, search, extraction, analysis, research, answering a question about files or data): put a line `mode: read-only` in the task text. Antigravity must not create, modify or delete files in the workspace, and it returns the full result in the report's `answer` field (Markdown). Read-only tasks may run in parallel on the same files.
- **Edit** (the default: implementation, fixes, tests, generated files): Antigravity changes files and reports them in `files_changed`. Give parallel edit tasks disjoint files, and run tasks that may touch the same file one after another.

## In workflow scripts

```js
// Operational stage (default delegated work): esecutore on Sonnet (effort 'medium', 'high', or 'xhigh').
const impl = await agent(implPrompt, { agentType: 'esecutore', label: 'impl:parser', phase: 'Execute' })

// Final synthesis or complex judging stage: analista (Opus xhigh).
const check = await agent(verifyPrompt, { agentType: 'analista', label: 'verify:parser', phase: 'Verify' })

// Simple mechanical leaf or read-only exploration: esploratore / meccanico / model: 'haiku'.
const files = await agent(listPrompt, { model: 'haiku', label: 'list:inputs', phase: 'Gather' })

// Only when the user asked for Antigravity: always the relay, never a model override. effort 'low': the relay only copies text.
const r = await agent(taskText, { agentType: 'antigravity', effort: 'low', label: 'extract:movimenti', phase: 'Gather', schema: AG_REPORT })
```

- Always propose a token ceiling `+Nk` before launching a workflow. Every `agent()` call passes `agentType` (`'esecutore'` by default for operational work, `'esploratore'`/`'meccanico'` or `model: 'haiku'` for read-only/mechanical leaves, `'analista'` only for complex final synthesis and hard judging, `'antigravity'` only for tasks the user wants on Antigravity). Never pass `model` together with `agentType: 'antigravity'`.
- Never use `isolation: 'worktree'` on antigravity calls: Antigravity's edits would stay stranded in the worktree.
- Size each task to finish in about 15 minutes. Prefer more, smaller tasks over one big one.
- Follow every edit phase with a verification phase that reads the real diff (`git diff`, `git status`) and runs the relevant tests or build. For read-only results, spot-check the figures and quotes that your conclusions depend on.
- Only a few Antigravity tasks run at the same time (the bridge has a small number of slots); larger fan-outs simply queue.

## Outside workflows

Do the work inline unless delegation thresholds apply; when delegating, use `esploratore`, `meccanico`, `esecutore`, or `analista`. Call the `antigravity` subagent directly with the Agent tool only for tasks the user wants on Antigravity (read-only ones included), following the same task-writing rules. Several independent read-only tasks can be sent at once.

## Writing a task for Antigravity

Antigravity cannot see this conversation, your plan or the other tasks. Each task text must stand on its own:

1. Goal, in one or two sentences, including the question the user is asking when that matters for the result.
2. Scope: the exact files or directories to read or change, and anything it must not touch. Add `mode: read-only` on its own line for read-only tasks.
3. Context: the names, signatures, conventions, dates or short snippets it needs. Reference files by path instead of pasting large content.
4. Done means: for edit tasks, acceptance criteria plus the exact command that proves it (for example `npm test -- src/parser.test.ts`); for read-only tasks, what the `answer` must contain and in what shape (a table with these columns, the figures with their source file and row, and so on).
5. Whether it may commit (default: no).

## Reading the report

The relay returns the bridge's JSON report and never retries on its own: every resend is your decision. Each task gets at most one new send after the first attempt. Act on `status`:

- `done`: verify, then move on. For read-only tasks the result is in `answer`; `summary` is only a short recap.
- `partial`, `failed`, `unverified`: read `summary`, `answer` and `open_issues`; clarify, split or add context, then resend. To continue the same Antigravity conversation for a follow-up, add a line `conversation_id: <id>` (taken from the report) to the new task text.
- `unexpected_changes` in the report of a read-only task: Antigravity modified files it should not have. Look at them with `git diff` and tell the user. `unexpected_changes_check` says whether that check ran (git status, or a snapshot of the folder outside git) or why it could not: if it is `not available`, do not assume the task left the files untouched.
- `blocked`: Antigravity's own permissions refused actions (`denied_actions`). Retrying will not help. Tell the user what was denied and point them to the 'Permessi' section of agy-kit's docs/GUIDA_CLAUDE.md (for `edit` tasks usually: `AGY_KIT_SKIP_PERMISSIONS=1` in `~/.config/agy-kit/config`; `read-only` tasks always run with permissions on and `--sandbox`, so the fix is allowing the actions in agy's settings, never skipping permissions).
- `timeout`: the task was interrupted and may have left changes half done. Check the real diff (`git diff`, `git status`) first; then either continue the same conversation with `conversation_id: <id>` or split what is left into smaller tasks.
- `cancelled`: the run was cancelled (by you or the user). Like `timeout`, it may have left partial changes: check the diff before deciding whether the task is still needed.
- `quota_exhausted`: Antigravity's quota is used up (429 / RESOURCE_EXHAUSTED). Never resend: it only burns more quota. Do not delegate anything else to Antigravity in this session; tell the user, quoting `quota_reset` (when the quota resets) if present, and ask how to proceed.
- `busy`: all bridge slots were taken. Send fewer tasks at once, then resend.
- `error`, `empty`: resend only if `retryable` is true (for `empty`, shorten the task as the `hint` says); otherwise report the error to the user.

If a task is still not done after that one resend, stop and tell the user. Do not silently take the work over yourself or hand it to another model; do it yourself only if the user says so.

## AG_REPORT schema (for `schema:` on antigravity calls)

```js
const AG_REPORT = {
  type: 'object',
  properties: {
    status: { type: 'string' }, // done | partial | failed | unverified | blocked | timeout | error | empty | busy | cancelled | quota_exhausted
    summary: { type: 'string' },
    answer: { type: 'string' },  // full result of read-only tasks (Markdown)
    sources: { type: 'array', items: { type: 'string' } },
    files_changed: { type: 'array', items: { type: 'string' } },
    unexpected_changes: { type: 'array', items: { type: 'string' } },
    commands_run: { type: 'array', items: { type: 'string' } },
    tests: { type: 'string' },
    open_issues: { type: 'array', items: { type: 'string' } },
    denied_actions: { type: 'array', items: { type: 'string' } },
    conversation_id: { type: 'string' },
    retryable: { type: 'boolean' },
    hint: { type: 'string' },
    log_file: { type: 'string' },
  },
  required: ['status', 'summary'],
}
```
