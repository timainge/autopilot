# Agent Roles

Autopilot uses specialized agent roles, each defined by a markdown file in `src/autopilot/agents/` with YAML frontmatter specifying the system prompt, allowed tools, budget, and permission mode.

## Judge

Evaluates manifest readiness. Reads the project manifest and surrounding context, then returns a verdict: ready (with feedback) or not ready (with reasons). Never auto-approves — the human sets `approved: true`.

## Worker

Executes individual tasks from the manifest. Each task spawns a fresh Claude Code session. The worker is responsible for marking tasks done by updating the manifest checkbox.

## Planner

Generates or improves `.dev/autopilot.md` from project context. Used in `--plan` mode.

## Researcher

Analyses the project codebase and writes `.dev/project-summary.md`. Used in `--research` mode.

## Critic

Reviews a generated manifest and suggests improvements. Used with `--plan --review`.

## Roadmap

Produces a concrete shipping roadmap and writes `.dev/roadmap.md`. Used in `--roadmap` mode.

## Portfolio

Runs cross-project analysis and writes a portfolio summary. Used in `--portfolio` mode.

## Custom Roles

Add a new `.md` file to `src/autopilot/agents/` with YAML frontmatter to define a custom role. See existing role files for the schema.
