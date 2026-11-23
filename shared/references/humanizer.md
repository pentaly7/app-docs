# Humanizing the User Guide (humanizer version 2)

The User Guide's prose is the last thing edited, by the **humanizer-indonesia** skill (github.com/adhiprib/humanizer-indonesia). This file says how the plugin runs that skill unattended, what it must not touch, and what to do when it isn't installed. The dev guide is never humanized.

## Contents
1. Settings the plugin decides for the skill
2. Where the plugin overrides the skill
3. What must not change
4. Process
5. Fallback when the skill isn't installed

---

## 1. Settings the plugin decides for the skill

The skill normally asks its user a few questions in Step 1. You run unattended inside a subagent, so these are the answers. Don't ask anyone.

| Skill question | Answer |
|---|---|
| Register / metric preset | `semiformal` (`scripts/metrik.py <file> --preset semiformal`) |
| Was the source English? | No. It was written in Indonesian, from source code, by another model. Treat the run as an **edit** of model output, not a translation. |
| Voice calibration | Use the plugin's preset `<Shared>/references/voice-operator-docs.md`. **Never** use the skill's bundled `voice-prib-id.md`: that's one academic author's personal voice. |
| Term decisions | Already made by the plugin (section 2). Don't ask. |

## 2. Where the plugin overrides the skill

The skill targets academic and teaching text. Operator docs differ in three ways, and the plugin's rules win:

- **Foreign terms:** the skill italicizes a foreign term and adds an Indonesian equivalent in parentheses at first use. **Don't.** Tech terms (endpoint, request, queue, retry, timeout, log, deploy, health check, payload, status code…) stay in plain English, as operators say them. The glossary already explains them. Keep each term identical across the whole doc (that part of the skill's rule holds).
- **Pronouns:** no "Anda", no "kamu". Use imperatives and plain statements.
- **Lists, tables and numbered steps** are the operator guide's structure, not "enumeration padding". Keep every list item and step. Improve the wording inside them only.

Everything else in the skill applies: its AI-tells catalog, the mandatory calque/diction and register checks (5b–5c), varied rhythm, fewer connectors and light verbs, no `merupakan` habit, **no em or en dashes**, and its metrics.

## 3. What must not change

These stay byte-for-byte identical, except where noted:

- Anchor comments (`<!-- docgen:section … -->`), heading levels and order, subtitle lines (`> generated at …`)
- **Rendered blocks** (`<!-- docgen:render … -->` to `<!-- /docgen:render -->`): tables and lists generated from the facts file. Never touch them; the validator fails any difference.
- **Keep blocks** (`<!-- app-docs:keep -->` to `<!-- /app-docs:keep -->`): written by a person. The plan never includes them.
- Diagram embeds, Mermaid blocks, code spans and code blocks (`DB_DSN`, `kubectl logs …`)
- Table structure. Only the prose inside cells may change.
- Facts: numbers, units, durations, status codes, names of keys, tables, queues, endpoints and flows (flow labels must stay verbatim), the order of steps, and every "Jika gagal" cause and check
- The Removed / Diagram-outdated marks
- **Exception:** an em or en dash in a title, image caption or placeholder may be replaced with a colon or comma (`# Payment API: User Guide`).

If a sentence can't be made natural without changing a fact, keep the fact and leave the sentence a bit stiff.

## 4. Process

The orchestrator picks the paragraphs first (`docs_tool.py humanize-plan`): paragraphs with a known AI tell (section 5's list, pronouns, slang, dashes), and paragraphs the skill's `scripts/metrik.py --preset semiformal` marks `PERIKSA`. You get only those.

1. Read the skill's catalog and rules (with the settings and overrides above).
2. Edit each planned paragraph once, in place: the skill's mandatory checks (calque/diction, register) applied while you write, no separate draft, no audit report, no final revision pass.
3. Paragraphs not in the plan stay as they are, even if you'd phrase them differently.

The facts check after you (`facts-diff --strict`) is the gate. A `PERIKSA` that would require dropping a fact or a step stays as it is.

## 5. Fallback when the skill isn't installed

The orchestrator passes `Humanizer skill: none` and has already warned the user. Edit with these built-in rules instead, then run the validator as in section 4.

- Semiformal, no slang, no "Anda"/"kamu", no em/en dashes. Tech terms in plain English.
- Remove: stiff connectors on every sentence ("Selain itu,", "Adapun", "Dengan demikian,", "Oleh karena itu,"), significance inflation ("memainkan peran penting", "sangat krusial"), throat-clearing ("Penting untuk dicatat bahwa", "Berikut adalah"), officialese ("dalam rangka", "guna", "yang bersangkutan"), light-verb nouns ("melakukan pengecekan terhadap" → "memeriksa"), the "yang mana"/"di mana" relative-pronoun calques, habitual "merupakan", "Tidak hanya … tetapi juga …", rhythm triplets, empty closings ("Semoga bermanfaat").
- Vary sentence length and openings. Not every step starts with "Aplikasi akan…".
- One term per concept, every time.
