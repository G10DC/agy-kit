# Ultracode × Antigravity: routing policy for this session (claude-first)

This session pairs Claude Code ultracode with the user's Antigravity UltraCode mode from agy-kit (Gemini with the `ultracode` skill, orchestrating Gemini Flash subagents). The user decided that too much work was going to Gemini, so Claude does the work and Antigravity is the exception. This overrides your usual model choices:

- **Complex work stays on Claude Opus (you)**: complex reasoning, analysis, statistics, design, verification, judging, synthesis, and any task where an error would be costly or subtle.
- **Simple, mechanical work goes to a cheaper Claude model: Haiku.** Downloads, file checks, listings, reformatting, simple extraction with a clear format, running a command and reporting its output. Sonnet is not available in this session (a request for it falls back to Opus and wastes budget), so the cheap model is `haiku`.
- **Antigravity is used only when the user asks for it, or when sparing Claude quota is the point** (for example a large batch of independent tasks the user wants kept off the Claude budget). Do not pick it by default and do not use it for work where quality matters more than quota: its output on analytical work has been unreliable (keyword-filter scripts instead of reading, invented quotes), so verify every report against the real files.
- You reach Antigravity only through the `antigravity` subagent, which relays one task to the `mcp__antigravity__delegate` tool and returns a JSON report.

## How to route

- A quick look to scope the work or to check a claim (a directory listing, one short file, one targeted search, `git status` / `git diff`) is yours.
- Anything that needs judgment stays with Opus: `agent()` calls without `model` run on Opus in this session (sub-agents inherit it).
- Mechanical leaves go to Haiku: pass `model: 'haiku'` on the `agent()` call. Give Haiku complete, unambiguous instructions and check its output; if a Haiku task fails once, redo it on Opus instead of resending.
- Tasks that need tools only Claude has in this session (MCP connectors such as Google Drive, Gmail, Calendar, Notion, the Artifact and document tools) are yours, never Haiku's or Antigravity's.
- When the user does ask for Antigravity ("delega a Gemini", "usa Antigravity"), or you propose it to spare Claude quota and the user agrees, follow the rest of this document for that task.

## Two kinds of task

- **Read-only** (exploration, search, extraction, analysis, research, answering a question about files or data): put a line `mode: read-only` in the task text. Antigravity must not create, modify or delete files in the workspace, and it returns the full result in the report's `answer` field (Markdown). Read-only tasks may run in parallel on the same files.
- **Edit** (the default: implementation, fixes, tests, generated files): Antigravity changes files and reports them in `files_changed`. Give parallel edit tasks disjoint files, and run tasks that may touch the same file one after another.

## In workflow scripts

```js
// Reasoning stage (the default): default agent type and no model override, so it runs on Opus.
const check = await agent(verifyPrompt, { label: 'verify:parser', phase: 'Verify' })

// Simple mechanical leaf: the cheap Claude model.
const files = await agent(listPrompt, { model: 'haiku', label: 'list:inputs', phase: 'Gather' })

// Only when the user asked for Antigravity: always the relay, never a model override. effort 'low': the relay only copies text.
const r = await agent(taskText, { agentType: 'antigravity', effort: 'low', label: 'extract:movimenti', phase: 'Gather', schema: AG_REPORT })
```

- Default agent type on Opus for anything that needs judgment; `model: 'haiku'` for simple mechanical leaves; `agentType: 'antigravity'` only for tasks the user wants on Antigravity. Never pass `model: 'sonnet'`, and never pass `model` together with `agentType: 'antigravity'`.
- Never use `isolation: 'worktree'` on antigravity calls: Antigravity's edits would stay stranded in the worktree.
- Size each task to finish in about 15 minutes. Prefer more, smaller tasks over one big one.
- Follow every edit phase with a verification phase (a reasoning stage) that reads the real diff (`git diff`, `git status`) and runs the relevant tests or build. For read-only results, spot-check the figures and quotes that your conclusions depend on.
- Only a few Antigravity tasks run at the same time (the bridge has a small number of slots); larger fan-outs simply queue.

## Outside workflows

Do the work yourself or with a Haiku subagent. Call the `antigravity` subagent directly with the Agent tool only for tasks the user wants on Antigravity (read-only ones included), following the same task-writing rules. Several independent read-only tasks can be sent at once.

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
