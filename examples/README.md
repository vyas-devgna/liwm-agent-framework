# Examples

- [Learning over time](learning-over-time.md) traces evidence, strategy, project
  exceptions, and human correction across five synthetic interactions.
- Run `python -m liwm eval converge --archetype <name>` for deterministic
  synthetic convergence studies.

Examples are synthetic test material. Never place a real `~/.liwm` profile in
this directory.

## `demo.sh`

```bash
sh examples/demo.sh
```

Six minutes of the framework doing the six things it claims to do, against a
throwaway home in a temp directory: a preference learned, a repository refused,
a project preference that does not leak, a prediction scored against what the
user actually did, a preference deleted from `user.json` and the intent graph
at once, and nothing ever reaching certainty.

Deterministic apart from ids and timestamps. No model, no network, and no
effectiveness statistics, because there is nobody in it.

