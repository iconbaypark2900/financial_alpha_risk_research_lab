# Task: finguard-proof-001

## Description

Smoke finGuard migration_inbox assets with reporter closeout

## Human-in-the-loop rule

Each agent writes its phase result to:

`.spark-flow/tasks/finguard-proof-001/outbox/<phase>.md`

The human reviews it and runs:

`spark-flow approve <phase>`

or:

`spark-flow reject <phase> "reason"`
