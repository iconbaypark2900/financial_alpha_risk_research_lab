# Task: finguard-integration-001

## Description

Integrate finGuard risk modules into portfolio_risk_service

## Human-in-the-loop rule

Each agent writes its phase result to:

`.spark-flow/tasks/finguard-integration-001/outbox/<phase>.md`

The human reviews it and runs:

`spark-flow approve <phase>`

or:

`spark-flow reject <phase> "reason"`
