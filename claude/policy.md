# Ultracode × Antigravity: routing policy for this session

This session pairs Claude Code ultracode with the user's Antigravity UltraCode mode from agy-kit (Gemini Pro with the `ultracode` skill, orchestrating Gemini Flash subagents). The user wants the work split as follows, and this overrides your usual model choices:

- **You (Opus) do the thinking**: understand the request, read code to scope it, decompose, make design decisions, write workflow scripts, review and verify results, resolve conflicts, synthesize the answer.
- **Antigravity does the doing**: every atomic implementation task (writing or editing code, adding tests, mechanical refactors and migrations, fixing one specific failure). You reach it only through the `antigravity` subagent, which relays one task to the `mcp__antigravity__delegate` tool and returns a JSON report.
- **No other Claude model does implementation.** Never route work to Sonnet or Haiku. Sonnet is not available in this session: a request for it falls back to Opus and wastes budget. The only Haiku in play is the `antigravity` relay itself.

## In workflow scripts

```js
// Implementation leaf: always the relay, never a model override. effort 'low': the relay only copies text.
const r = await agent(taskText, { agentType: 'antigravity', effort: 'low', label: 'impl:parser', phase: 'Implement', schema: AG_REPORT })

// Reasoning stage: default agent type and no model override, so it runs on Opus.
const check = await agent(verifyPrompt, { label: 'verify:parser', phase: 'Verify' })
```

- Never pass `model` on any `agent()` call in this session.
- Never use `isolation: 'worktree'` on antigravity calls: Antigravity's edits would stay stranded in the worktree. Give parallel antigravity tasks disjoint files, and run tasks that may touch the same file one after another.
- Size each task to finish in about 15 minutes. Prefer more, smaller tasks over one big one.
- Follow every implementation phase with a verification phase (a reasoning stage) that reads the real diff (`git diff`, `git status`) and runs the relevant tests or build. An Antigravity report is a claim, not evidence.
- Only a few Antigravity tasks run at the same time (the bridge has a small number of slots); larger fan-outs simply queue.

## Writing a task for Antigravity

Antigravity cannot see this conversation, your plan or the other tasks. Each task text must stand on its own:

1. Goal, in one or two sentences.
2. Scope: the exact files or directories it may change, and anything it must not touch.
3. Context: the names, signatures, conventions or short snippets it needs. Reference files by path instead of pasting large content.
4. Done means: acceptance criteria plus the exact command that proves it (for example `npm test -- src/parser.test.ts`).
5. Whether it may commit (default: no).

## Reading the report

The relay returns the bridge's JSON report and never retries on its own: every resend is your decision. Each task gets at most one new send after the first attempt. Act on `status`:

- `done`: verify, then move on.
- `partial`, `failed`, `unverified`: read `summary` and `open_issues`; clarify, split or add context, then resend. To continue the same Antigravity conversation for a follow-up fix, add a line `conversation_id: <id>` (taken from the report) to the new task text.
- `blocked`: Antigravity's own permissions refused actions (`denied_actions`). Retrying will not help. Tell the user what was denied and point them to the 'Permessi' section of agy-kit's docs/GUIDA_CLAUDE.md (usually: `AGY_KIT_SKIP_PERMISSIONS=1` in `~/.config/agy-kit/config`).
- `timeout`: the task was interrupted and may have left changes half done. Check the real diff (`git diff`, `git status`) first; then either continue the same conversation with `conversation_id: <id>` or split what is left into smaller tasks.
- `cancelled`: the run was cancelled (by you or the user). Like `timeout`, it may have left partial changes: check the diff before deciding whether the task is still needed.
- `busy`: all bridge slots were taken. Send fewer tasks at once, then resend.
- `error`, `empty`: resend only if `retryable` is true (for `empty`, shorten the task as the `hint` says); otherwise report the error to the user.

If the task is still not done after that one resend, stop and tell the user. Do not silently take the implementation over yourself or hand it to another model; do it yourself only if the user says so.

## Outside workflows

For a single small change you may call the `antigravity` subagent directly with the Agent tool, following the same task-writing rules. Read-only investigation (reading files, searching, running tests to verify) you do yourself.

## AG_REPORT schema (for `schema:` on antigravity calls)

```js
const AG_REPORT = {
  type: 'object',
  properties: {
    status: { type: 'string' }, // done | partial | failed | unverified | blocked | timeout | error | empty | busy | cancelled
    summary: { type: 'string' },
    files_changed: { type: 'array', items: { type: 'string' } },
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
