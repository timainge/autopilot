# Concepts

## The Manifest

The manifest (`.dev/autopilot.md`) is the central artifact. It's a YAML-frontmatted markdown file with task checkboxes. It serves as both a specification and a live state tracker.

## The Judge

The judge agent evaluates whether your project manifest is ready to execute. It reads the manifest and gives feedback. You must set `approved: true` to proceed.

## The Worker

The worker agent executes each task sequentially. Each task spawns a fresh Claude Code session. The worker marks tasks done by checking their checkboxes in the manifest.

## The Approval Gate

Autopilot never auto-approves unless you pass `--auto-approve`. This ensures a human reviews the plan before execution begins.

## Task Dependencies

Tasks can declare dependencies with `[depends: task-id]`. Dependent tasks are skipped until their prerequisites are complete.
