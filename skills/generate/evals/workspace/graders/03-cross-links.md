---
type: llm
focus: output
weight: 2
---

Where a service calls another, its guides link to the other service's guide of the same kind with a GitLab link: shop's User Guide links to `https://gitlab.example.com/team/wallet/-/blob/HEAD/docs/wallet/operator-guide.md` (an anchor may follow), shop's Dev Guide to wallet's `dev-guide.md`, and wallet's guides to db-service's the same way. No guide contains a relative link that leaves its own repo (a path starting with `../` that climbs above the repo root).
