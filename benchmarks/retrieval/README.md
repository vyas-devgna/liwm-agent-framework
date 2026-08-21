# Retrieval sufficiency

Context economics answers what a memory strategy *costs*. This answers what it
*buys*. The two have to be read together: any arm can get cheaper by retrieving
less, and the only thing standing between "efficient" and "empty" is a
measurement of what got dropped.

```bash
python -m liwm eval retrieval                      # development split
python -m liwm eval retrieval --no-intent          # confidence-only ablation
python -m liwm --json eval retrieval --split all   # raw rows and manifest
```

## Why this suite exists

`eval contextecon` scored LIWM at 0.88 required-fact sufficiency — 7 of 8
scorable turns. That number was too small to improve against: one case is 12
percentage points, so any change looks like a result and none of them are.

This suite is 97 cases over all 47 taxonomy dimensions. One profile holds a
belief on every dimension plus forty undifferentiated `legacy_choice_*`
entries, standing in for the history any long-running profile accumulates.

**Confidence carries no signal about relevance here.** It is assigned to the
real beliefs pseudo-randomly from a fixed seed, so a ranker cannot score by
preferring what LIWM is surest about — it has to know what the request is
*for*. Cases never name their dimension or its value; a case whose wording
contains its own answer would measure string matching.

## Dev and holdout

Cases split on the SHA-256 of their id — not on any property anyone chose —
61 dev / 36 holdout. Development reads dev. The holdout was read once, after
the ranker was finished.

## Result

| arm | split | recall | 95% CI | precision | MRR | tokens/case |
|---|---|---:|---|---:|---:|---:|
| confidence only | dev | 0.279 | 0.182–0.402 | 0.021 | 0.066 | 235 |
| **+ intent cue** | dev | **0.803** | 0.687–0.884 | 0.058 | 0.232 | 239 |
| confidence only | holdout | 0.333 | 0.202–0.497 | 0.025 | 0.080 | 234 |
| **+ intent cue** | holdout | **0.611** | 0.449–0.752 | 0.045 | 0.245 | 235 |

Paired on the same 36 holdout cases: **10 fixed, 0 broken**, McNemar exact
two-sided **p = 0.002**. The intent cue does not lose a single case the
confidence baseline won, and token cost is unchanged — 234 against 235.

**Read the dev/holdout gap as overfitting, because that is what it is.** Dev is
0.803 and holdout is 0.611. Closing gaps in the action classifier meant looking
at which development cases matched nothing, so the classifier is fitted to dev
and 0.611 is the honest estimate of how it generalises. Quoting 0.803 as the
system's recall would be quoting a training score.

## How it works

Ranking by confidence answers "what is LIWM surest about", which is not the
question being asked. A preference for tables over prose held at 0.53 is
exactly what *"compare these three options"* needs, and it loses to forty
unrelated preferences held at 0.55.

The approach follows STITCH ([Yang, Jiang, Han et al., *Grounding Agent Memory
in Contextual Intent*, Findings of ACL 2026](https://arxiv.org/abs/2601.10702)):
index memory by a structured intent cue and retrieve by intent compatibility,
suppressing history that is semantically similar but context-incompatible.

LIWM gets that cheaply, because its memories are not free text. Every belief
names a dimension from a closed taxonomy, so "what is this memory about" needs
no extraction, no embedding and no model call — it is declared once per
taxonomy section, with a short override list. Only the request is classified,
by one shared vocabulary of ten action types.

What it is **not** is a keyword list per dimension. That version needs 47
hand-tuned vocabularies and matches nothing when a request is phrased in words
nobody guessed. Here there is one classifier and one affinity table, and adding
a dimension usually costs nothing.

Intent compatibility multiplies the structured score rather than being added to
it, so a belief that bears on the request still has to be believed, and
confidence still breaks ties among beliefs that bear on it equally. The
component scores appear in the ContextReceipt: `StructuredRanker`,
`LexicalRanker` and `IntentRanker` are reported separately, so no consumer has
to take a single opaque relevance number on faith.

## What is still wrong

- **Holdout recall is 0.611.** Two requests in five still miss the preference
  they turn on. This is not a solved problem.
- **Precision is 0.045.** About 95% of projected beliefs are irrelevant to the
  request. They are cheap — 235 tokens a case — but they are not free.
- **MRR is 0.245**, so the needed belief typically lands around rank four.
  Affinity is declared per taxonomy *section*, so every `interaction_profile`
  dimension scores identically for "explain" and ordering within a section
  falls back to confidence. Finer affinity would fix it and costs a larger
  hand-written table; that trade has not been made.
- Five development cases match no action type at all and fall back to
  confidence ranking.
- One profile shape, one noise model. Real accumulated history is not forty
  uniform entries.

## Limitations

No model runs. This measures whether the fact reached the projection, not
whether a model used it, and nothing here is evidence about answer accuracy.

---

[LIWM](../../README.md) · [Context economics](../contextecon/README.md) ·
[IntentBench](../intentbench/README.md)
