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
| 1.31.2, `--source-only` | **29/42** |

By kind, last run: owner 4/4, config 5/5, pins 1/1, pins-behind 1/1,
table-definition 2/2, latent 1/1, callers 6/7, dead 4/6, table-writers 2/3,
incident-fix 1/2, publishers 1/4, consumers 1/4, definition 0/2. The 13 left are
#122 (no verb tells publish from consume or GET from POST: 11) and the two
scorer limits below.

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
