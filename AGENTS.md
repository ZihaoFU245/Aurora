# Agent Email Tools Issue Log & Remediation Prompt

## Summary

We encountered a recurring bug when invoking email tools (notably `email_count_unread` and `email_fetch_unread`) through the agent pipeline:

1. Original async tool functions returned opaque error upstream: `Tool 'email_count_unread' error: Result is not set.`
2. Root cause: The executor layer expected sync return values but some async tool invocation paths produced unresolved/cleared results when exceptions bubbled or when LangChain's sync wrapper interacted with already-running loops.
3. Attempted mitigation: Converted tools to synchronous functions using `asyncio.run()` internally. That eliminated the opaque "Result is not set" but introduced a new failure inside an active event loop: `asyncio.run() cannot be called from a running event loop` (typical in web / graph execution contexts).
4. Reverting back to async restored the original symptom (opaque result) when underlying provider raised (e.g., SSL or auth issues) before structured response assembly.

## Current State

Tools have been restored to async, returning structured dicts: `{ success: bool, data|error, meta? }`.
However, the graph executor (`core/nodes.py` `_execute_tool_calls`) still uses primarily synchronous `tool.invoke()` logic and only falls back to an async path one tool at a time. This means multiple async tools are not awaited concurrently and some coroutine resolution edge cases can still yield the generic "Result is not set" message from LangChain internals if the coroutine raises before producing a value.

## Recommended Fix

Update the executor to:
1. Detect which requested tools are async (e.g., `inspect.iscoroutinefunction(tool._run)` or presence of `tool.coroutine`).
2. Collect all async tool coroutines first.
3. Await them concurrently with `asyncio.gather(return_exceptions=True)` inside a single event loop context.
4. Wrap each result in the unified `{ success: ..., ... }` shape (already done at tool layer) and convert exceptions into `_err()` there—ensuring no bare exception escapes unwrapped.
5. Remove per-tool fallback `asyncio.run` usage entirely from email tools (already done) to avoid nested loop issues.

## Minimal Executor Patch (Conceptual)

Pseudo-diff for `core/nodes._execute_tool_calls`:
```
if any async tools:
	# build list of (call_id, tool, args)
	async_calls = [...]
	async def runner():
		tasks = [t.ainvoke(a) for (_, t, a) in async_calls]
		return await asyncio.gather(*tasks, return_exceptions=True)
	results_list = asyncio.run(runner())  # or ensure we're already in loop and await directly
	# map back to ToolMessage with structured error if Exception
```
In a running loop context (FastAPI / graph), don't use `asyncio.run`; instead `await runner()` from an async executor function; if current function is sync, offload with `asyncio.get_event_loop().create_task` plus `asyncio.wait` or refactor node to async.

## Agent Prompt to Apply Fix

You can guide the system (or another autonomous agent) with the following prompt:

```
Task: Fix email tool execution returning "Result is not set" for async tools.

Context:
- email tools are async and return structured dicts {success,data|error,meta}.
- executor _execute_tool_calls in core/nodes.py invokes tools synchronously then fallback individually to async, losing some errors.
- Need concurrent, safe awaiting of all async tool calls; no nested asyncio.run inside running loop.

Requirements:
1. Refactor _execute_tool_calls into an async helper (e.g., _execute_tool_calls_async) that:
   - Gathers all tool calls.
   - Separates sync vs async tools.
   - Runs sync tools in order (blocking) and async tools via asyncio.gather.
2. Update executor_node to detect if any async tools present; if so, execute the async helper (may need making executor_node async and adjusting callers) OR run an event loop task and wait.
3. Ensure every tool result becomes a ToolMessage whose content is already JSON (serialize dict) to prevent "Result is not set".
4. Log failures with tracer.log("tool_call_error", ...).
5. Do not wrap successful results in additional strings; keep JSON stability.

Deliverables:
- Modified core/nodes.py with async gather logic.
- No usage of asyncio.run inside a running loop.
- Tests or a smoke path calling email_count_unread and email_fetch_unread simultaneously without "Result is not set".
```

## Follow-Up

After executor refactor, re-test scenarios:
- Single email tool call (count)
- Multiple email tools in a single reasoning step (fetch + count + list drafts)
- Provider failure (simulate network or invalid credentials) — should return `{ success: false, error: "..." }` without opaque wrapper errors.

## Notes

The SSL error observed earlier (`[SSL: WRONG_VERSION_NUMBER]`) is environmental (likely proxy or TLS interception) and separate from the tool result framing bug. The structural fix above ensures such errors surface cleanly without the ambiguous "Result is not set" message.

---
Document last updated after reverting async tools to restore proper coroutine handling.
