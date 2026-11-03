# The Copperleaf Coffee fleet: scoring cs on a fleet that runs

`fixtures/repos/` is five tiny repos with planted seams: right for testing that
the mechanics work, and by its own account wrong for judging whether search is
good. The Copperleaf Coffee fleet is the other half: a made-up coffee-bean shop
that really runs (docker compose, Postgres, RabbitMQ), 13 private repos in the
GitHub org `copperleaf-coffee`, six languages, events with publishers and
consumers, contract packages pinned at different versions, five incidents
replayed into git history, and a docs repo written the way different teams
write.

Its ground truth is a description file, `model/company.json`, which a check
(`scripts/check-model`) holds against the code. The question set,
`model/cs-questions.json`, is built from that file, in the same format as
`../expectations.json`: `expect` files (recall), `forbid` files (decoys), plus the
`answer` itself. Nobody chose those answers with cs. All of it lives in its own
repo, `copperleaf-coffee/answer-key`, cloned **outside** the fleet folder, so
nothing cs (or an agent) searches in the fleet holds the answers.

```sh
# once: the fleet and, beside it, the answer key (needs access to copperleaf-coffee)
mkdir -p ~/git/fixture-company && cd ~/git/fixture-company
gh repo list copperleaf-coffee --json name -q '.[].name' | grep -vx answer-key | xargs -I{} gh repo clone copperleaf-coffee/{}
gh repo clone copperleaf-coffee/answer-key ~/git/home/copperleaf-answer-key

fixtures/copperleaf/score                 # as first asked
fixtures/copperleaf/score --source-only   # following cs's own --source-only hint
fixtures/copperleaf/score --only price-callers -v
```

`queries.json` is how cs is asked each question: the verb from the skill's
"Which subcommand" table and the literal an agent would type, fixed before the
first run. Change it only to follow a change in that table, never to make a
question pass. `BASELINE.md` is the last measured run and what it found.

Decoys come from the fleet itself, not from planting: a docs page that mentions
a route in prose, `POST /charges` beside the dead `GET /charges`,
`/coffees/{sku}/price` beside `/coffees/{sku}`, `RENEWAL_MAX_ATTEMPTS` beside
`MAX_ATTEMPTS`, `RABBITMQ_URI` beside `RABBITMQ_URL`.

The five-repo fleet stays for `verify-search`: its seams that this fleet does
not have (a route split across two C# attributes, a DI-resolved
implementation, a versioned topic nobody produces, a repo with no CODEOWNERS)
are still tested there.
