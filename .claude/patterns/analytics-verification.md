# Analytics Verification Checklist

Gate check for analytics coverage. Referenced by scaffold and change
procedures after implementing or modifying pages/routes/commands.

Skip this entire checklist if `stack.analytics` is absent in experiment.yaml.

## Event Coverage

- [ ] For each event in the experiment/EVENTS.yaml `events` map (filtered
      by `requires` matching experiment stack and `archetypes` matching
      experiment type), confirm a tracking call exists in the appropriate
      page/route/command
- [ ] Every user action described in experiment/EVENTS.yaml must have a
      corresponding tracking call — no deferred wiring

> REF: Archetype branching — see `.claude/patterns/archetype-behavior-check.md` Quick-Reference Table, row "Consent guard".
>
> [consent-guard] web-app: none | service: none | cli: opt-in consent on `trackServerEvent`

## CLI Consent Guard (if archetype is `cli`)

- [ ] Confirm the server analytics file wraps `trackServerEvent()` with
      an opt-in consent check (see analytics stack file's "CLI Opt-In
      Consent" section)
- [ ] CLI telemetry must be opt-in per the CLI archetype contract

## Completeness Rule

"I'll add analytics later" is not acceptable. Do not proceed until all
items above are confirmed.
