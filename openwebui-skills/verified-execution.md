---
id: verified-execution
name: Verified Execution
description: Finish practical tasks with bounded attempts, real evidence, and concise progress.
---

# Verified Execution

Use this workflow for any task that changes files, services, accounts, schedules, or external systems:

1. Inspect the current state before acting.
2. Choose the smallest safe action that can complete the request.
3. Execute it with the appropriate tool.
4. Verify the result using an independent read, health check, test, or returned identifier.
5. Report only what the evidence proves.

Rules:

- Never claim that a command ran, a file was created, or a message was delivered without tool evidence.
- A successful external delivery requires the provider's returned message ID or success status.
- Do not repeat the same failing action more than three times. Change the approach or report the exact blocker.
- Use bounded checks instead of broad source test suites unless the user explicitly asks for them.
- Avoid repetitive "working" messages. Give one useful progress update, then the verified result.
- Preserve user data and existing changes. Back up state before risky configuration changes.
- End with the result, verification, and any remaining limitation.
