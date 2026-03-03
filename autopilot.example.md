---
name: "My API Project"
approved: false
status: pending
worktree: false
branch_prefix: autopilot
max_budget_usd: 5.0
max_task_attempts: 3
---

# My API Project

A REST API built with Express.js and PostgreSQL for managing user accounts
and authentication.

## Architecture

- Express.js with TypeScript
- PostgreSQL via Prisma ORM
- JWT authentication
- Jest for testing

## Tasks

- [ ] Initialize Express.js project with TypeScript configuration [id: init]
- [ ] Add Prisma ORM with PostgreSQL connection and User model [id: prisma] [depends: init]
- [ ] Implement user registration endpoint POST /api/users [id: register] [depends: prisma]
- [ ] Implement user login endpoint POST /api/auth/login with JWT [id: login] [depends: prisma]
- [ ] Add authentication middleware for protected routes [id: auth-middleware] [depends: login]
- [ ] Implement GET /api/users/me endpoint [id: user-profile] [depends: auth-middleware]
- [ ] Add integration tests for auth flow [id: auth-tests] [depends: user-profile]

## Context

This is a greenfield project. Start from an empty directory. Use the latest
stable versions of all dependencies. Follow standard Express.js project structure
with `src/` directory.
