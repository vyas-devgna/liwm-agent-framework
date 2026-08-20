# Consent — <study name>

A starting point for a form, not legal advice and not an ethics approval. Adapt
it, have it reviewed, and do not describe the study as approved because this
file exists.

---

## What we are studying

Whether a tool called LIWM, which builds a local model of how you like to work,
makes an AI assistant's output fit your intent better than the alternatives.

## What is recorded

On **your machine only**, LIWM records typed evidence about your working
preferences: what you asked for, what you corrected, which option you chose,
and how confident it is about each conclusion. It does not upload anything.
There is no telemetry.

For this study you will export a **minimized, pseudonymised** subset: event
kinds, timings relative to the study start, and a fixed list of numeric
measurements. Free-text prose is dropped by default. You can read the export
file before you send it, and we would prefer that you did.

- **Fields exported:** <list them>
- **Retention:** <period>, then deleted
- **Where it goes:** <recipient, storage, who has access>

## What is not recorded

- No protected or sensitive personal attributes. LIWM refuses to store them and
  logs the refusal.
- No intelligence or aptitude scoring of any kind.
- No raw conversation text, unless you explicitly enable it and export it.

## Pseudonymity, honestly stated

Your identifiers are replaced with pseudonyms that are stable within this study
so repeated sessions can be analysed together. That is **pseudonymity, not
anonymity**. Anyone holding two exports can link them, and the key on your
machine can re-identify every row. You can destroy that key at any time with
`liwm study forget-key`, after which existing exports can never be linked again.

A study this size may be identifiable from working patterns alone. We are
telling you that rather than promising you it is not.

## If the study changes how the tool behaves

<Include only if running canary or A/B evaluation:> For a small, randomly
selected fraction of your tasks, the assistant may follow an experimental
behaviour rule instead of the current one. The assignment is recorded before
the output is produced. You can turn this off at any time.

## Your rights

- Read any export before it is shared.
- Correct anything LIWM concluded about you: `liwm reject`, `liwm forget`.
- Withdraw at any time, for any reason, without giving one.
- Have your data deleted. Withdrawal will not be treated as a result, and your
  data will not be excluded selectively based on what it showed.

## Contact

<name, email, and who to contact if you have a concern about the study rather
than a question about it>

---

Participant: ______________________  Date: ____________

Researcher: ______________________  Consent form version: ____________
