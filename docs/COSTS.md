# Costs

The app uses your own Anthropic API key, so you pay Anthropic directly for what it uses.
[Your first hour](FIRST_HOUR.md#7-cost-and-control) lists what each step cost in one measured run.

## See what you've spent

Every AI call is recorded on your machine: tokens, web searches, and the cost at Anthropic's
list prices. The **Usage** page (`/usage`, or `GET /api/usage`) shows spend for today, the last
7 and 30 days, and all time, by feature and by model.

If a model isn't in the app's price list, its tokens are still recorded and it shows
"price unknown".

## Set a daily limit

Add `AA_DAILY_BUDGET_USD=5` (any amount) to `.env` and restart the API. `0` blocks every call.

Before each call, the app checks what you've spent today. Once you reach the limit, new calls
stop with a message that says how much you spent and how to raise it. "Today" is the server's
local day. In Docker that's UTC unless you set `TZ`.

It's a soft limit based on recorded spend, not a hard billing cap:

- The app only knows a call's cost after it finishes. So the call that crosses the limit can
  go over it, and so can research searches already running next to it. Searches that haven't
  started are cancelled.
- When the Anthropic SDK retries a call by itself (after a timeout, say), the app isn't told.
  Those rare retries aren't counted.
- The app can't price a model it doesn't know. On the Anthropic backend, while a limit is set,
  calls to such a model are refused, and the setup check and the Usage page warn you. Pick a
  model from the price list or remove the limit.
- If the app can't read today's spend (for example, the database needs
  `uv run alembic upgrade head`), it refuses calls while a limit is set, rather than letting
  them through uncounted.

For a hard limit, also set a spend limit on the key in the Anthropic Console or OpenRouter.

## On OpenRouter

OpenRouter reports what it charged for each call, fees included, and the app records that
instead of its own price list. So the daily limit works for any model, priced or not.

- If OpenRouter ever leaves out the cost for a model the app has no price for, that model is
  refused under the limit for the rest of the day. It clears at midnight, or after one call
  made with the limit unset.
- OpenRouter doesn't enforce the cap on web searches for non-Claude models. A research step
  asks for at most 5 searches, but OpenRouter runs 6 to 10. They're billed and counted like
  any other spend.

## Use a Claude subscription instead

Set `AA_LLM_BACKEND=agent_sdk` in `.env`. This works without Docker only, and needs Claude Code
installed and logged in. Calls go through the Claude Agent SDK and your subscription pays for
them. It's slower. The Usage page shows the SDK's own cost estimate, and the daily limit doesn't
apply.
