<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.png">
  <img src="assets/logo.png" width="200" alt="LIWM: a skeptical elephant inspecting a scrap of paper held in its trunk">
</picture>

# LIWM

**Latent Intent World Model**

*An elephant never forgets. This one asks where you heard that.*

[![CI](https://github.com/vyas-devgna/liwm-agent-framework/actions/workflows/ci.yml/badge.svg)](https://github.com/vyas-devgna/liwm-agent-framework/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-161719?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%20–%203.14-161719?style=flat-square)](pyproject.toml)
[![Dependencies](https://img.shields.io/badge/dependencies-0-C8873A?style=flat-square)](pyproject.toml)
[![Telemetry](https://img.shields.io/badge/telemetry-none-C8873A?style=flat-square)](PRIVACY.md)
[![Hosts](https://img.shields.io/badge/host%20adapters-documented-161719?style=flat-square)](adapters/README.md)

[Install](#install-by-pasting-a-prompt) · [How it learns](#how-it-learns) · [Privacy](#privacy) · [CLI](#cli) · [Does it work?](#does-it-work) · [Docs](#documentation)

</div>

---

**Your agent may already remember you. Typical prose memory does not require
structured provenance, scope, uncertainty, or evaluation. LIWM does.**

Agent memory is solved and shipping. Claude Code writes auto memory by default;
Cursor has Memories, Windsurf has Cascade Memories, Gemini CLI has `/memory`.
LIWM is not another one of those, and it does not replace them.

What they share is a *representation*: prose appended to a Markdown file. A
paragraph is a fine way to hold an instruction and a poor way to hold a claim
about a person, because there is nowhere in it to put the things that make such
a claim checkable.


| | Markdown agent memory | LIWM |
|---|---|---|
| **Where it came from** | often not structured — the note may read the same whether you said it or a `README` did | provenance on every observation; untrusted sources carry trust `0.0` |
| **How sure** | often not structured — a hunch and a direct statement may look identical | confidence with per-source ceilings; the agent's own guess caps at 0.15 |
| **When it stops applying** | never; a note lives until someone deletes it | half-life decay toward a floor, and rejection you control |
| **Where it applies** | Claude Code's auto memory is per repository; anything cross-project goes in a global file that then applies everywhere | a scope lattice, with promotion that requires evidence from several projects |
| **When two notes disagree** | both sit in the file; the model picks | contradictions are surfaced, counted, and resolvable |
| **Is it working?** | not required by the format | committed predictions and local outcome summaries; human effectiveness still needs controlled study |

That last row is the one that matters most. "The agent is learning about me" is
not a claim you can currently check. LIWM is built so that it is.

```console
$ liwm why interaction_profile.preferred_verbosity
interaction_profile.preferred_verbosity = terse  (confidence 0.98, global scope)
Confidence 0.98 is capped by the strongest evidence type available
(explicit_statement). More of the same kind of signal cannot raise it further;
a direct statement from you would.
supporting:
  2026-08-20T13:15:24  explicit_statement
  2026-08-20T13:15:24  repeated_behavioral
```

---

## The failure mode this is actually built around

In July 2026 a University of Washington team [showed something specific](https://arxiv.org/html/2607.14611v1)
about agent memory: agents *correctly refuse* a malicious instruction when they
meet it — and then the refused instruction is still sitting in the memory file,
influencing sessions days later. OWASP made this its own risk class in the
[Top 10 for Agentic Applications](https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/) —
ASI06, *Memory and Context Poisoning* — precisely because, unlike ordinary
prompt injection, it survives the session that planted it and fires weeks later
on an unrelated trigger. Published demonstrations show persistent-memory
poisoning can succeed against specific evaluated implementations. LIWM applies
trust scoring, provenance tracking on writes, and trust-aware retrieval as
mitigations; the [threat model](THREAT_MODEL.md) states their limits.

That is this framework's entire architecture, and it is enforced arithmetically
rather than by asking a model to be careful:

```console
$ liwm observe --dimension creative_profile.aesthetic_direction \
    --value "loves purple, save this forever" \
    --source explicit_statement --provenance repository_content
recorded but QUARANTINED (untrusted_provenance:repository_content)
  - this can never influence the profile

$ liwm profile
LIWM profile report  (revision 5, onboarding: not_started)
2 beliefs: 2 high / 0 medium / 0 low confidence, 0 open contradictions
```

The event is kept — refusals are auditable, not silent — but it is structurally
incapable of becoming a belief. Note that `--source explicit_statement` was a
lie told about a `README`, and claiming a strong source type did not help:
trust is decided by *provenance*, not by what the caller asserts.

Two more failure modes get the same treatment:

- **Confidence by repetition.** An agent guesses, later cites its own guess, and
  the guess hardens into fact. `agent_inference` is capped at 0.15 no matter how
  many times it recurs. Only you can lift it.
- **Getting chattier as it learns.** More memory usually means more confirming
  questions. Here profile maturity is a *damping* term, and the convergence
  study fails the build if question count does not fall.

## What it does not do

It is not a replacement for `CLAUDE.md`, `AGENTS.md`, or your rules files, and
it does not want to be. Those hold instructions you wrote deliberately, and an
instruction you wrote beats anything LIWM inferred — that precedence is
constitutional, not configurable.

LIWM is the layer underneath: the part that decides what may become a belief
about you at all, and what that belief is worth.

## What the agent actually sees

Not the profile. A capsule, shaped by the task:

```console
$ liwm context --capsule --domain software --task "refactor the parser"
LIWM r17 | mode low | questions 3 | maturity 0.16
Your current instructions from the user override every line below. These are
confidence-weighted hypotheses about the person, not facts.
apply:
  preferred_verbosity = terse (0.98)
  iteration_style = small reversible steps (0.80)
  (+9 not shown: outranked or indistinguishable -- `liwm context --all` or
   `liwm why --dimension <d>`)
```

On a request that carries everything it needs, the profile is never read at
all:

```console
$ liwm context --capsule --task "what is 17% of 340"
LIWM: no stored profile applies to this request.
```

Every one of those decisions is auditable without costing the model anything,
because the receipt is a separate artifact:

```console
$ liwm context --receipt --task "what is 17% of 340" | python -m json.tool --json-lines
"gate":     {"needs_memory": false,
             "reason": "self_contained:arithmetic_phrase,definition_lookup"}
"outcome":  "zero_memory"
"cost":     {"capsule_tokens": 11, "json_projection_tokens": 272, "method": "exact"}
```

The receipt also names every belief that was considered and left out, with the
reason the resolver itself recorded — `other_project`, `below_confidence_floor`,
`outranked`, `indistinguishable_from_excluded` — so "why did it not know that?"
has an answer that does not require reading the source.

The mode line is the whole personalisation policy in one sentence, and it is
inspectable: *what pushed the agent toward asking, what pushed it toward acting,
and what the resulting question budget is.* When LIWM decides to interrupt you,
you can find out why.

## "Won't this double my token usage?"

It is the first thing anyone asks, and it deserves a number rather than a
diagram. `liwm eval contextecon` runs six memory strategies over the same
ninety-day profile — one that has accumulated a package-manager instruction,
an explicit later correction, forty ordinary preferences, and a `README` that
claims the user prefers something else — and counts what each costs per turn.
Exact `cl100k_base` counts, twelve turns, [full
methodology](benchmarks/contextecon/README.md):

| strategy | tokens/turn | had the fact it needed | leaked the README's claim |
|---|---:|---:|---:|
| no memory | 0 | 0.00 | 0 |
| dump the whole profile | 22,266 | 1.00 | 0 |
| prose in a Markdown file | 679 | 1.00 | **12 / 12** |
| LIWM projection as JSON *(what 0.3.0 shipped)* | 620 | 0.88 | 0 |
| LIWM capsule | 122 | 0.88 | 0 |
| **LIWM capsule, zero-memory gate on** | **85** | 0.88 | 0 |

Three honest readings of that table.

**The objection is right about naive injection.** Dumping a matured profile
into every turn costs 22,266 tokens. Nobody should do that, and LIWM shipping
its projection as pretty-printed JSON was a milder version of the same mistake
— two thirds of those tokens were punctuation, repeated keys, and belief ids no
model has ever used.

**Cheap sufficiency is not sufficiency.** The Markdown-memory strategy scores a
perfect 1.00 and carries the repository's claim to speak for you into all twelve
turns. It is easy to always have the fact when you always send everything,
including the thing that should never have been written down.

**LIWM does not score 1.00, and that stays in the table.** One turn in eight needs a
formatting preference held at confidence 0.53 that forty accumulated
preferences at 0.55 outrank — a real limit of confidence-ordered retrieval
without semantics. What LIWM does is refuse to hide it: the capsule ends with
`(+N not shown)`, `liwm context --include <dimension>` fetches what was left
out, and a test holds *every* miss to being a signalled one. LIWM is allowed to
miss. It is not allowed to miss quietly.

Two costs the table does not show. The always-on block is 118–262 tokens
depending on host. Each consultation costs about 180 ms of local wall clock,
roughly 150 ms of which is Python starting up — LIWM trades that latency for
the tokens, which is a good trade against a multi-second model call and a bad
one if you call it in a loop.

## Install by pasting a prompt

There is no `install.sh` or PowerShell script that rewrites your
assistant's persona behind your back. Installation is a prompt, because the
thing being installed is an *understanding* of how your agent is configured, and
your agent is the only thing that knows that.

Open Claude Code, Codex, Gemini CLI, Cursor, or any capable coding agent and
paste [**INSTALL_PROMPT.md**](INSTALL_PROMPT.md). It instructs the agent to:

1. detect its own host and your OS, and check what is already there;
2. **back up** every file it is about to touch, with a timestamp;
3. add exactly **one delimited block** to your global instruction file, leaving
   every other byte alone;
4. install the skills, initialise `~/.liwm/`, run `liwm doctor`, and tell you
   precisely what changed;
5. offer onboarding — which you can decline.

The marker helpers are tested for idempotence and preservation, but the current
prompt-driven workflow still depends on the installing agent following the
contract. Review its plan and diff. [UNINSTALL_PROMPT.md](UNINSTALL_PROMPT.md)
asks whether to keep, export, or delete private data; [UPDATE_PROMPT.md](UPDATE_PROMPT.md)
describes an in-place upgrade.

Want to see the plan before an agent edits your config?

```console
$ liwm install plan --host claude-code --block adapters/claude-code/bootstrap.md
installation plan for Claude Code:
  backup         /home/you/.claude/CLAUDE.md
                 timestamped copy into <liwm home>/backups/ before any edit
  upsert_block   /home/you/.claude/CLAUDE.md
                 append one delimited LIWM block, preserving all other text
  copy_skills    /home/you/.claude/skills
                 hash-guarded copies of the 15 LIWM skills
```

## Documented host adapters

LIWM attaches through **one mechanism**: a delimited Markdown block in a file the
agent already reads. Skills, plugins and hooks are optimisations on top.

```console
$ liwm hosts
claude-code      Claude Code                  present, liwm-installed, skills
                 /home/you/.claude/CLAUDE.md
codex            Codex CLI                    present, skills
                 /home/you/.codex/AGENTS.md
gemini-cli       Gemini CLI                   -
                 /home/you/.gemini/GEMINI.md
opencode         opencode                     present
                 /home/you/.config/opencode/AGENTS.md
windsurf         Windsurf / Cascade           -
                 /home/you/.codeium/windsurf/memories/global_rules.md
...
Teach LIWM another host by adding it to /home/you/.liwm/hosts.json
```

Claude Code and Codex have documented router-plus-skills adapters. Other registry
entries use a standalone or compact block, manual UI configuration, or a
repo-scoped file. Registry and unit tests do not establish live host behavior;
see the [host acceptance protocol](docs/HOST_ACCEPTANCE.md). Budget checks report
whether a proposed block fits before an installer writes it.

**Adding a host takes no code.** Drop eight lines into `~/.liwm/hosts.json` and
`liwm hosts` picks it up. An entry matching a built-in *corrects* it, so when a
vendor moves a path you can fix it locally instead of waiting for a release. See
[adapters/README.md](adapters/README.md).

One profile serves them all: `~/.liwm/user.json` is plain JSON with a published
[schema](schemas/user.schema.json), not a Claude-shaped or Codex-shaped format.

### Genuinely cross-platform

Linux, macOS and Windows are all first-class, and CI runs the full suite on all
three. The details that usually break portability are handled explicitly rather
than assumed:

- **Locking** uses `os.open(O_CREAT|O_EXCL)` with stale-lock detection — atomic
  on POSIX and Windows alike, no `fcntl`/`msvcrt` fork in the code.
- **Skill installation** uses portable file copies. Existing same-path files are
  backed up and restored; unrelated skills are not touched.
- **Case-insensitive filesystems** are detected, because on macOS and Windows
  `liwm-profile` and `LIWM-Profile` are the same directory.
- **Paths** come from `Path.home()` and honour `CODEX_HOME`, `CLAUDE_CONFIG_DIR`
  and `LIWM_HOME`; `liwm doctor` reports every resolved path it will use.

```console
$ liwm doctor
LIWM 0.3.0  home=/home/you/.liwm
  [ok] home_exists
  [ok] home_outside_git
  [ok] event_integrity_ok
  [ok] constitution_hash_matches
  [--] platform: Linux 7.1.8, Python 3.14.7
  [--] host claude-code (present, LIWM not installed)
```

## How it learns

Four learning speeds, deliberately separated so a fast signal can never quietly
rewrite a slow one:

```mermaid
flowchart LR
    U[User intent and feedback] --> P[Provenance and privacy gates]
    P --> E[Append-only evidence events]
    E --> M[Materialized user and project models]
    M --> C[Task-relevant context projection]
    C --> A[Agent asks or acts]
    A --> R[Prediction and outcome]
    R --> U
    R --> X[Local metrics and retrospective]
    X --> S[Bounded personal strategy]
    X --> Q[Candidate core rule]
    Q --> G{Replay + regression + adversarial gates}
    G -->|pass| Z[Promoted rule]
    G -->|fail| J[Rejected rule]
```

1. **Project intent** updates immediately — it is what you just said.
2. **Personal beliefs** update only from permitted evidence, under confidence
   ceilings, with decay and scope.
3. **Interaction strategy** moves slowly, through bounded EWMA steps.
4. **Core behaviour** changes only through a six-stage gate: replay over ≥12
   episodes, ≥4% primary improvement, no regression on guarded metrics, an
   adversarial pass, a constitution check, and **≥5 resolved agent-recorded
   outcomes** — predictions committed before their recorded resolution. These
   are not independently verified human outcomes.
   Replay alone can never promote anything, because replay is LIWM grading its
   own model of you.

Level 4 promotes **data that skills consume**. It never rewrites skill text.
"The agent edits its own instructions" is not a feature here; it is the thing
the gate exists to prevent.

### Evidence arithmetic, in full

Independent evidence combines noisy-OR — `P = 1 − Π(1 − wᵢ)` — then
`confidence = P(supported) × (1 − P(opposed))`, clamped to the ceiling of the
strongest source type present.

| Source type | Weight | Ceiling |
|---|---|---|
| `explicit_statement`, `explicit_correction`, `explicit_rejection` | 1.00 | 0.98 |
| `direct_edit` | 0.90 | 0.92 |
| `repeated_selection` | 0.80 | 0.88 |
| `comparative_choice` | 0.75 | 0.82 |
| `onboarding_answer` | 0.70 | **0.70** |
| `repeated_behavioral` | 0.65 | 0.78 |
| `outcome_signal` | 0.55 | 0.72 |
| `single_behavioral` | 0.30 | 0.55 |
| `agent_inference` | 0.15 | **0.15** |

Nothing reaches 1.00, including your own words: a person can change their mind,
and a framework that recorded certainty about someone would be wrong about the
only thing it is for.

The ceilings are the point. Ten onboarding answers cannot make LIWM as sure of
you as one sentence you typed, and no amount of self-citation lets the agent's
own guess graduate into a fact. Evidence within one session is discounted
(×0.55) and within one correlated source group compounds down (×0.75), because
five signals from one afternoon are not five independent observations.

Beliefs decay on half-lives (45 / 180 / 540 days by volatility) toward a floor of
0.20 — history fades, it is never erased — and a preference you reject is
suppressed until *you* revive it.

### Scope never leaks upward

```
session  →  project  →  domain  →  global
```

A preference learned on one project stays there. Promotion to a domain needs
≥2 distinct projects and ≥2 sessions (×0.75 discount); promotion to global needs
≥2 distinct domains and ≥3 sessions (×0.60, weakest link). Cross-domain transfer
starts as a capped hypothesis (×0.35) and must be independently observed in the
target domain before it counts. Your API-design preferences do not become
opinions about your writing.

**Explicit project instructions always override learned preferences.** That is
constitutional, not configurable.

## Operating modes

| Mode | What changes |
|---|---|
| **AUTO** *(default)* | Scores uncertainty, novelty, consequence × irreversibility, project stage and recent corrections; subtracts specification completeness, profile maturity, domain evidence, fatigue and question aversion. Resolves per task. |
| **LOW** | Execution-biased. 0–3 questions, ~70% direct/technical, lean on reversible assumptions. |
| **MEDIUM** | Resolve material ambiguity first. 2–6 questions, ~50/50 technical and experiential. |
| **HIGH** | Intent-first. Experiential and counterfactual by default, one question at a time, up to 12, stopping when marginal utility falls below cost. |
| **OFF** | No profile, no questions, no learning. |

The modes change the *kind* of reasoning, not just the count — verified by
`liwm eval modes`, which asserts the experiential share is monotonic across
LOW/MEDIUM/HIGH (0.33 → 0.50 → 0.83) and the budgets are 3 / 6 / 12.

Budgets are ceilings, not quotas: zero questions is frequently the right answer.
Every candidate question is scored
`(EIG × decision_impact × misunderstanding_risk × relevance) / (cost × fatigue × redundancy)`
and dropped if it does not clear the bar. Say `LIWM high`, `LIWM off`,
`LIWM why`, `LIWM forget …` in plain language at any time.

## Onboarding: up to ten questions

It targets ten but stops immediately if the user is done. Questions are
adaptive, one at a time, scenario- and tradeoff-shaped rather than a form. At
least eight question families, follow-ups chosen from your prior answers, no
running score shown, and a short correctable summary at the end. Onboarding
confidence is stored separately and capped at 0.70 — a good first conversation
is a hypothesis, not a verdict.

Skipping it is a legitimate choice; AUTO simply starts more uncertain.

**LIWM's guarded mutation paths refuse IQ/intelligence labels and known protected
attributes** — race, religion, sexuality, gender identity, health, politics,
criminal or immigration status. A taxonomy check and pattern screen turn known
matches into a redacted refusal event. Open semantic values and regex screening
cannot classify everything; residual risk is documented in the threat model.

## Privacy

- **No LIWM-core telemetry or automatic upload.** The core contains no network
  client. A hosted agent may include the selected runtime projection in its
  model context under that host/provider's privacy policy.
- Your data lives in `~/.liwm/` (`%USERPROFILE%\.liwm` on Windows), `0700`,
  deliberately outside every Git repository. `liwm init` refuses to run inside
  one.
- **Incidental prose is dropped by default.** Quotes and notes are removed, but
  structured semantic strings such as belief values may persist because they
  are the model's content. Opt in to retaining incidental text with
  `liwm config set --key privacy.store_free_text`.
- `liwm export --anonymise` produces an allowlisted research export: numbers and
  controlled vocabulary only, with per-export pseudonyms. Distinctive patterns
  can still permit linkage; inspect the result before sharing.
- `liwm study on` enables a local event-derived research view; it remains
  default-off, never uploads, and `study export --anonymise` is still only risk
  reduction.
- `liwm forget`, `liwm reject`, `liwm reset`, `liwm rollback` and `liwm delete`
  all exist, and the event log makes each of them exact rather than approximate.

See [PRIVACY.md](PRIVACY.md) and [THREAT_MODEL.md](THREAT_MODEL.md).

## Data architecture

```mermaid
flowchart TB
    subgraph Private[User data directory — never the repository]
      EV[events/*.json<br/>source of truth]
      UJ[user.json<br/>materialized profile]
      RC[runtime_context.json<br/>task projection]
      PJ[projects/&lt;id&gt;/<br/>intent decisions feedback]
      LE[learning/<br/>strategy candidates rules]
      ME[metrics.json]
      BA[backups/ and logs/]
    end
    EV --> UJ
    UJ --> RC
    PJ --> RC
    EV --> ME
    EV --> LE
    BA -. recovery .-> UJ
```

`user.json` is a **cache**. The event log is the truth, so concurrency has no
merge heuristic: two agents writing at once produce two events, and the profile
is re-folded deterministically. A corrupt `user.json` is quarantined and rebuilt
from events rather than restored from a stale backup when event integrity is
sound. Every event carries a SHA-256 self-hash; an integrity failure is reported
and materialization fails closed rather than silently folding around missing or
corrupt evidence.

## CLI

Zero runtime dependencies, Python 3.9+, every command supports `--json` because
the primary caller is an agent.

```bash
python -m liwm init
python -m liwm hosts                     # what agents are on this machine
python -m liwm context --capsule --task "design an API"   # what the agent reads
python -m liwm context --receipt --task "design an API"   # what that cost, and why
python -m liwm context --capsule --task "..." --include creative_profile.polish_vs_rough
python -m liwm profile                   # what it thinks, and what it doesn't know
python -m liwm why interaction_profile.preferred_verbosity
python -m liwm contradictions            # where the evidence disagrees
python -m liwm assumptions               # what it acted on without asking
python -m liwm stats                     # calibration: were its predictions right?
python -m liwm eval intentbench          # synthetic benchmark mechanics
python -m liwm eval contextecon          # what each memory strategy costs a turn
python -m liwm study status              # opt-in local research export status
python -m liwm verify                    # integrity + schema + materialisation
python -m liwm rollback --as-of 2026-08-01T12:00:00Z --yes
```

Normal LIWM mutations are mediated through guarded framework APIs and the CLI.
Those paths enforce provenance, privacy, audit and atomicity checks.

To be precise about what that is not: it is not an OS security boundary. Your
agent runs with your filesystem authority, so anything that can run as you can
overwrite `~/.liwm/user.json`, rewrite the event log, or edit LIWM's own source.
The per-event SHA-256 and local chain manifest make accidental, missing, or
isolated changes *visible*. Materialisation fails closed instead of folding
around corrupt evidence. These are self-hashes, not signatures, so an attacker
who rewrites every file can rewrite the hashes too.

The defensible claim is that normal, compliant framework use is guarded. LIWM
cannot protect against a process with equivalent filesystem authority
deliberately rewriting the framework, events or host configuration, and such a
process can also replace the hashes. Making that stronger needs an independent
trusted boundary, which is [on the roadmap](ROADMAP.md) and not in 0.3.0.

```python
from liwm import open_home

liwm = open_home()
context = liwm.runtime_context(domain="software", task="refactor the parser")
```

## Does it work?

The honest answer: **the safety and persistence invariants are covered by tests;
the effectiveness numbers are simulation, and labelled as such.**

```bash
python tests/run_tests.py -v     # 511 tests, no dependencies
python -m liwm eval modes
python -m liwm eval converge --archetype impatient_technical_expert --rounds 10
python -m liwm eval intentbench --suite mechanism --adapter liwm
python -m liwm eval contextecon
```

The mechanism suite is the one worth running. Seventeen cases build a real
LIWM home out of typed evidence and check that a project preference does not
leak, that repository content and laundered inferences cannot set a belief,
that a tombstone drops the right evidence and only that, that a preference
learned in three domains reaches a fourth, and that no evidence produces no
opinion rather than a confident guess. LIWM passes all seventeen; a
fixed-choice baseline scores 0.29, and a test asserts that gap so the suite
cannot quietly become one everything passes.

`eval contextecon` is the other one worth running: six memory strategies over
the same profile, counted rather than argued about. Its numbers are in the
[token-cost section](#wont-this-double-my-token-usage) and its methodology,
including where LIWM loses, is in
[benchmarks/contextecon](benchmarks/contextecon/README.md). It measures
injected tokens and whether the needed fact was present. It does **not** measure
answer quality: no model runs, and nothing from it may be quoted as evidence
about accuracy.

It is still synthetic. A pass means the implementation matches the
specification, not that the specification helps anyone.

To watch it happen rather than read about it:

```bash
sh examples/demo.sh
```

Six steps against a throwaway home: a preference learned from a statement, a
repository file refused, a project preference that does not leak, a prediction
committed and then scored against what the user actually did, a preference
deleted from `user.json` and the intent graph by one tombstone, and nothing
reaching certainty. No model, no network, no invented statistics.

Over ten simulated rounds with an impatient expert, belief accuracy rises
0.21 → 1.00, synthetic observed acceptance 0.36 → 1.00, and questions asked fall
2.80 → 0.00. That is a deterministic simulator agreeing with its own model of a
person — evidence that this synthetic mechanism converges and does not get chattier,
and *not* evidence about real humans. Counterfactual replay acceptance is
explicitly modelled, never observed. A full trace is in
[examples/learning-over-time.md](examples/learning-over-time.md).

The adversarial suite is the part worth reading: it feeds realistic injection
payloads through repository content, tool output, MCP results and subagent
reports, and asserts the profile is unchanged.

## Limitations

- LIWM depends on the host agent reporting **truthful provenance**. The CLI
  makes known-untrusted classes structurally inert, but it cannot prove a
  malicious host did not relabel a web page as something you said.
- File locking suits local filesystems, not arbitrary network shares.
- Default relevance scoring is dependency-free structured/lexical ranking.
  Optional semantic rankers may reorder only evidence that already passed
  provenance, privacy, and scope eligibility. This has a measured cost:
  `eval contextecon` scores LIWM at 0.88 evidence sufficiency, because a
  genuinely relevant belief held at low confidence can be outranked by
  accumulated preferences held slightly higher. The capsule reports what it
  withheld and `--include` retrieves it, so the failure is recoverable — but it
  is a failure, and a semantic ranker is the honest fix rather than a nicety.
- The zero-memory gate is a deterministic rule list, so it can only recognise
  self-containment it has a rule for. It is built to fail toward retrieving,
  which makes its errors cost tokens rather than answers.
- Token counts are exact only where a BPE tokenizer is installed. LIWM's own
  estimator is dependency-free and, measured over 75 real payloads, lands
  within 10% on 71 of them and within −11.2%/+22.4% at worst.
- Replay estimates whether a strategy *would likely* have helped. Only a
  prospective controlled study establishes causal improvement.
- A local adversary with your account's filesystem access can read an
  unencrypted profile. Encryption is [designed](docs/ENCRYPTION.md), not shipped.
- One profile per LIWM home. Team and multi-user models are future work.

## Documentation

| | |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the folding, scoping and gating fit together |
| [adapters/README.md](adapters/README.md) | Documented host configurations and how to add one |
| [PRIVACY.md](PRIVACY.md) · [THREAT_MODEL.md](THREAT_MODEL.md) | What is stored, what is refused, what is assumed |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Design decisions and the alternatives rejected |
| [docs/PROFILE_SCHEMA.md](docs/PROFILE_SCHEMA.md) | Field-by-field profile reference |
| [docs/RESEARCH.md](docs/RESEARCH.md) · [IntentBench](benchmarks/intentbench/README.md) | Evaluation protocol and benchmark contract |
| [docs/HOST_ACCEPTANCE.md](docs/HOST_ACCEPTANCE.md) | Evidence required for host behavior claims |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | When something looks wrong |
| [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) | Where it is going, and how to help |

**[Full documentation index →](docs/README.md)**

> **Status: 0.3.0 alpha.** The invariants are tested — 511 tests, a mechanism
> benchmark that can fail, and a lint and coverage gate — and the API is stable
> enough to build on. The effectiveness claim is not tested at all, because
> that needs real people. Nobody has run the study yet.
> [docs/RESEARCH.md](docs/RESEARCH.md) has the protocol, the instrumentation,
> and a 20–40 person alpha designed to falsify the thesis cheaply. If you run
> one, the maintainers would like to hear from you, including if it fails.

### About the name

"Latent Intent World Model" describes where this is going, not what framework 0.x is. In
the sense an ML researcher means it, there is no world model here: no learned
latent representation of a person, no generative response/state transition such
as `P(R_t, I_{t+1} | I_t, A_t, C_t)`, no neural state-space model, and no
counterfactual simulator grounded in real human trajectories.

What 0.3.0 actually is, stated plainly:

> an evidence-sourced, uncertainty-aware persistent user model with active
> intent elicitation and an adaptive questioning policy.

The graph is likewise a typed provenance graph with a small amount of state
logic, not a dynamic inference engine: four edge types change an element's
status, the rest describe relationships and are inert by design.

The scoring is transparent arithmetic over typed evidence — noisy-OR, ceilings,
decay, scope — chosen because it is inspectable and falsifiable, not because it
is the most expressive thing available. It is also the baseline any learned
model has to beat on held-out real data before it becomes the default, which is
the opposite of treating it as technical debt. The prediction loop
(`liwm predict` → `liwm resolve` → `liwm stats`) exists so that a later learned
model has something to beat. Treat the name as the destination on the roadmap,
and judge 0.3.0 on the paragraph above.

## License

MIT. See [LICENSE](LICENSE).

<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.png">
    <img src="assets/logo.png" width="52" alt="">
  </picture>
</div>

Host documentation rechecked for 0.3.0: [Claude Code skills](https://code.claude.com/docs/en/skills)
· [memory](https://code.claude.com/docs/en/memory)
· [plugins](https://code.claude.com/docs/en/plugins)
· [Codex skills](https://developers.openai.com/codex/skills)
· [AGENTS.md](https://developers.openai.com/codex/guides/agents-md)
· [Gemini CLI context files](https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html)
· [opencode rules](https://opencode.ai/docs/rules/)
· [Windsurf memories](https://docs.windsurf.com/windsurf/cascade/memories)
· [agents.md](https://agents.md/)
