#!/usr/bin/env sh
# A demonstration that tries not to flatter itself.
#
# Everything here runs against a throwaway LIWM home in a temp directory and
# touches nothing you own. It is deterministic except for ids and timestamps:
# no model, no network, no invented effectiveness statistics.
#
#   sh examples/demo.sh
#
# What it shows, in order: a preference learned from a direct statement, a
# repository trying to set one and being refused, a project preference that
# does not leak, a prediction committed before the user reacts and scored
# against what they actually did, a preference deleted from both projections at
# once, and the fact that none of it was ever certain.

set -eu

HOME_DIR=$(mktemp -d)
trap 'rm -rf "$HOME_DIR"' EXIT
LIWM="python3 -m liwm --home $HOME_DIR"
export PYTHONPATH="$(cd "$(dirname "$0")/.." && pwd)/src:${PYTHONPATH:-}"

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

say "1. The user says something directly"
$LIWM init --allow-in-repo >/dev/null
$LIWM observe --dimension interaction_profile.preferred_verbosity --value terse \
      --source explicit_statement --provenance direct_user_message --domain software >/dev/null
$LIWM profile --section interaction_profile --json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["interaction_profile"]; row=d.get("preferred_verbosity"); print("  verbosity = %s (confidence %.2f)" % (row["value"], row["confidence"]) if row else "  verbosity = nothing known")'

say "2. A repository file claims a preference on the user's behalf"
$LIWM observe --dimension interaction_profile.preferred_verbosity --value detailed \
      --source explicit_statement --provenance repository_content --domain software >/dev/null
echo "The README said 'detailed'. The profile still says:"
$LIWM profile --section interaction_profile --json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["interaction_profile"]; row=d.get("preferred_verbosity"); print("  verbosity = %s (confidence %.2f)" % (row["value"], row["confidence"]) if row else "  verbosity = nothing known")'
echo "Quarantined, recorded, and worth exactly nothing:"
$LIWM events tail --limit 1 --include-quarantined --json \
  | python3 -c 'import json,sys; e=json.load(sys.stdin)["events"][0]; print("  provenance=%s quarantined=%s reason=%s" % (e["provenance"], e["quarantined"], e["quarantine_reason"]))'

say "3. A preference that belongs to one project stays there"
$LIWM observe --dimension creative_profile.simplicity_vs_richness --value feature_rich \
      --source explicit_statement --provenance direct_user_message --scope project --scope-key alpha >/dev/null
echo "Inside project alpha:"
$LIWM context --project alpha --json \
  | python3 -c 'import json,sys; a=json.load(sys.stdin)["applies"]; print("  %s" % [r["dimension"] for r in a])'
echo "Outside it:"
$LIWM context --json \
  | python3 -c 'import json,sys; a=json.load(sys.stdin)["applies"]; print("  %s" % [r["dimension"] for r in a])'

say "4. A prediction, committed before the user reacts"
PRED=$($LIWM predict --acceptance 0.8 --confidence 0.6 --json \
       | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
echo "  committed: $PRED  P(first-pass acceptance) = 0.80"
echo "  ...the user disagrees."
$LIWM feedback --kind too_verbose --channel explicit --prediction "$PRED" >/dev/null
FB=$($LIWM events tail --limit 20 --json \
     | python3 -c 'import json,sys; print([e["event_id"] for e in json.load(sys.stdin)["events"] if e["kind"]=="feedback"][-1])')
$LIWM resolve --prediction "$PRED" --evaluator observed_human_outcome \
      --evidence-event "$FB" --json \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); print("  scored: predicted %.2f, actual acceptance %.2f, first-pass %d, %s" % (r["predicted_acceptance"], r["actual_acceptance"], r["actual_first_pass"], r["direction"]))'
echo "  The label came out of the feedback event. Passing a different number is an error, not an override."

say "5. The user changes their mind, and it goes everywhere"
EVID=$($LIWM events tail --limit 200 --json \
       | python3 -c 'import json,sys; print([e["event_id"] for e in json.load(sys.stdin)["events"] if (e.get("observation") or {}).get("dimension")=="interaction_profile.preferred_verbosity" and not e["quarantined"]][0])')
NODE=$($LIWM intent node --type preference --label "Prefers terse answers" \
       --origin user --confidence 0.9 --evidence "$EVID" --json \
       | python3 -c 'import json,sys; print(json.load(sys.stdin)["element"]["id"])')
echo "  intent graph node $NODE, standing on observation $EVID"
echo "Before the tombstone:"
$LIWM profile --section interaction_profile --json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["interaction_profile"]; row=d.get("preferred_verbosity"); print("  verbosity = %s (confidence %.2f)" % (row["value"], row["confidence"]) if row else "  verbosity = nothing known")'
$LIWM intent graph --include-inactive --json \
  | python3 -c 'import json,sys; g=json.load(sys.stdin); print("  intent graph: %d active, %d inactive" % (len(g["nodes"]), len(g.get("inactive") or [])))'

$LIWM forget --dimension interaction_profile.preferred_verbosity >/dev/null

echo "After:"
$LIWM profile --section interaction_profile --json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["interaction_profile"]; row=d.get("preferred_verbosity"); print("  verbosity = %s (confidence %.2f)" % (row["value"], row["confidence"]) if row else "  verbosity = nothing known")'
$LIWM intent graph --include-inactive --json \
  | python3 -c 'import json,sys; g=json.load(sys.stdin); i=(g.get("inactive") or []); print("  intent graph: %d active, %d inactive%s" % (len(g["nodes"]), len(i), " (%s)" % i[0]["reason"] if i else ""))'
echo "  Both projections, one tombstone. Asking about the node now:"
$LIWM intent explain "$NODE" 2>&1 | sed "s/^/    /" || true
echo "  The events are all still there. The conclusions are not."

say "6. Nothing was ever certain"
$LIWM profile --raw --json \
  | python3 -c 'import json,sys; b=json.load(sys.stdin)["beliefs"]; print("  highest confidence in the profile: %.2f" % max([r["confidence"] for r in b] or [0.0]))'
echo "  An explicit statement caps at 0.98. An agent inference caps at 0.15."

printf '\nNo human was involved in producing any of the above.\n'
printf 'For what would count as evidence, read docs/RESEARCH.md.\n'
