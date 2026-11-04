# Baseline: cs on the Copperleaf Coffee fleet

Run 2026-11-03, cs 1.31.0 to 1.31.2, against
`~/git/fixture-company` (13 repos: Java, Kotlin, C#, Python, TypeScript, JSON
Schema, Markdown). 42 questions from the fleet's question set
(`model/cs-questions.json` in copperleaf-coffee/answer-key), asked with the commands in `queries.json`,
scored by `fixtures/copperleaf/score`. No tokensave graphs: no question here uses
a graph verb.

| Run | Passed |
| --- | --- |
| cs 1.31.0, as first asked | 16/42 |
| cs 1.31.0, `--source-only` added to `uses`/`seam` (cs's own hint) | 25/42 |
| with the 1.31.1 prose-filter fix, as first asked | 16/42 |
| with the 1.31.1 prose-filter fix, `--source-only` | 26/42 |
| 1.31.2 (`cs values` #120, `requirements.txt` #121), as first asked | 19/42 |
| 1.31.2, `--source-only` | 29/42 |

Then the fleet gained three seams the five-repo fixture already had: a route split
across a class prefix and a method (`@RequestMapping("/wholesale")` +
`@GetMapping("/accounts")`) and across a .NET `MapGroup("/green-lots")`, an
interface resolved only by DI registration (`ICardProvider` -> `FakeCardProvider`
in `Program.cs`), and a repo with no CODEOWNERS (docs). Three questions were added
(45):

| Run | Passed |
| --- | --- |
| 1.31.2, as first asked | 21/45 |
| 1.31.2, `--source-only` | 31/45 |

Then a consumer of an event nothing publishes (`stock.low`, contracts 1.3.0) and
its question (46), and cs 1.32.0's `cs route` / `cs event` (#122), asked as the
skill's table now says (`queries-1.32.json`) and read by the side each line is
labelled with:

| Run | Passed |
| --- | --- |
| 1.32.0, `queries-1.32.json` | 42/46 |
| 1.33.0, `queries-1.32.json` | **44/46** |

By kind, last run: publishers 5/5, consumers 4/4, dead 6/6, definition 3/3,
callers 7/7, owner 5/5, config 5/5, impls 1/1, pins 1/1, pins-behind 1/1,
table-definition 2/2, latent 1/1, table-writers 2/3, incident-fix 1/2. The two
left are the scorer limits below. 1.33.0 added the two callers that reach the
gateway through a helper adding the base path (`admin('/orders/...')` prepends
`/api/admin`, the shop's `call('/subscriptions/...')` prepends `/api`): cs route
now reads the helper's base and lists them as `[calls]`; the back office's
`admin('/subscriptions/{id}/renew-now')`, which shares only the tail of the
customer route, is named as `/api/admin/...`, another route.

As in the five-repo baseline, a FAIL is trustworthy and a PASS still needs
reading: the scorer checks which files an answer names, not what it says about
them.

## What the fleet found that the five tiny repos could not

1. **Docs drown `cs uses`.** The fleet has a docs repo: 64 pages that mention
   routes, keys and events in prose. As first asked, every route question failed
   on a docs page (16/42). cs says so itself ("most of this answer is NOT
   source ... `--source-only`"), and following the hint is worth 9 questions.
   The five tiny repos have no docs repo, so this was never measured.
2. **A `/*` in a line comment hid a whole file (fixed in 1.31.1).** The gateway's
   route table starts `// ... /api/* ...`. The prose filter took that `/*` as a
   block-comment opener and counted every line up to the file's last `*/` as
   prose, so `cs uses '/refund'` said nobody calls the refund route. The same
   hid generated contract code (`// Generated from ... events/*.json`) and both
   C# migrators (`/// ... Migrations/*.sql`).
3. **`cs versions` did not read `requirements.txt` (fixed in 1.31.2, #121).** Both
   Python services pin the contracts there; cs said "2 manifest(s) in a format
   this does not parse" and the drift question (which repos are behind 1.2.0)
   could not be answered.
4. **`cs values` matched a key inside a longer key, and parsed a Spring default
   wrongly (fixed in 1.31.2, #120).** `cs values MAX_ATTEMPTS` reports orders-service's
   `${RENEWAL_MAX_ATTEMPTS:3}` as a **set** of `MAX_ATTEMPTS` to the literal
   `"3}"`. It also counted comments (a Python `#` line, a SQL `--` line) as
   **reads**.
5. **Events have three spellings.** `order.paid` in JSON, `ORDER_PAID` in Kotlin,
   Python and TypeScript, `OrderPaid` in C#. Searching the constant misses the C#
   publisher of `stock.reserved` and the C# consumer of `payment.refunded`.
6. **No verb tells publish from consume, or a route's definition from its
   callers.** Every publisher and consumer question fails on precision: a text
   search names both sides. `cs uses '/charges'` cannot tell `GET` from `POST`,
   and `/coffees/` also matches `/coffees/{sku}/price`. These are the shape of a
   missing feature (an event or route seam verb), not a bug.

7. **A split route has no literal to find.** `uses "/wholesale/accounts"` finds
   the gateway and the back office, never `WholesaleController.kt`, where the path
   is `@RequestMapping("/wholesale")` plus `@GetMapping("/accounts")`; the same
   for inventory's `MapGroup("/green-lots")` + `MapPost("/allocate")`. The
   five-repo fixture's split C# attributes show the same, and tokensave found
   that one by symbol; no verb here assembles the path.
8. **DI is answered, in two verbs.** `cs impls ICardProvider` resolves
   `FakeCardProvider` (LSP) and `cs refs` reaches the `AddSingleton` line in
   `Program.cs`; neither alone answers "which class charges cards, and where is it
   chosen". A repo with no CODEOWNERS is reported as the gap ("docs declares no
   CODEOWNERS"), not filled in.

9. **The seam verbs (1.32.0).** `cs event` found every publisher and consumer,
   the C# ones through their PascalCase spelling, the Kotlin consumer through
   its `CONSUMED` list and `@RabbitListener`, the Python one through
   `queue_bind`; it named `stock.low` as consumed with nothing publishing it.
   `cs route` assembled both split definitions and the .NET group, kept
   `POST /charges` apart from `GET /charges`, and called the five dead routes
   dead. Its first run labelled a template function named like an event
   (`t.subscriptionPaymentFailed(...)` inside `send(...)`) a publisher; a
   spelling followed by `(` is now a function, not the event.

## Hollow and harsh verdicts

- `wholesale-accounts-writers` fails because `cs uses` names the file that
  *reads* the table; the question forbids naming a reader as a writer, and the
  scorer cannot tell the two.
- `inc-002-fix` needs two repos' fix commits; `cs history 'carton-l'` finds the
  fulfillment one, and the platform commit (the dead-letter queue) never
  contained that string.

## The answer key was in the fleet

These runs were made while the questions and answers still lived in the fleet
(`platform/model/`, `docs/ns-eval.json`): `cs uses` without `--source-only`
returned them. No verdict depended on it (those files are in no `expect` or
`forbid` list), and the key has since moved to its own repo outside the fleet,
so an agent searching the fleet can no longer read the answer instead of
finding it.
