---
tags: [app-docs, readme]
max_turns: 120
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent, AskUserQuestion]
---

/app-docs:readme

Input files: a monorepo already documented by /app-docs:generate (git repo with docs/ committed), whose old READMEs contain at least one claim the Dev Guide contradicts.
