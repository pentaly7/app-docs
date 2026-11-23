---
tags: [app-docs]
max_turns: 200
timeout_seconds: 3600
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash, Agent]
---

/app-docs:generate

Input files: a small Go service, voucher-api. place-files.sh copies it into the working folder and makes it a git repo with a GitLab `origin` remote.
