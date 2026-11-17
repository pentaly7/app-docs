# Indonesian humanizer (built-in)

Makes the operator guide read like a senior operator wrote it in a hurry for a colleague, not like a translated AI report. It applies **only to Bahasa Indonesia prose**. The dev guide is never humanized.

## Contents
1. What must not change
2. Target voice
3. AI patterns to remove
4. Process
5. With an installed humanizer skill

---

## 1. What must not change

The humanizer edits **prose only**. Change any of these and the validator, the sync, or the reader breaks:

- Anchor comments (`<!-- docgen:section … -->`), headings, subtitle lines (`> \`sha\` · …`)
- Diagram embeds and their captions, Mermaid blocks, code spans and code blocks (`DB_DSN`, `kubectl logs …`)
- Table structure. Only the prose inside cells may change.
- Facts: numbers, durations, status codes, names of keys, tables, queues, endpoints, flows (flow labels must stay verbatim), the order of steps, and every "Kalau gagal" cause and check
- Placeholders (`_Belum diketahui — …_`) and the Removed / Diagram-outdated marks

If a sentence can't be made natural without changing a fact, keep the fact and leave the sentence a bit stiff.

## 2. Target voice

- Casual Indonesian, the way people write in a work chat or an internal wiki. Slang is fine when it's natural: `nggak`, `udah`, `aja`, `kalau`, `bikin`, `nyimpen`, `nandain`, `ngecek`.
- No "Anda", no "kamu". Use imperatives (`Cek …`, `Restart …`) or plain statements.
- Short sentences. One idea per sentence. Lead with the action or the symptom.
- Tech terms stay English (request, retry, queue, timeout, log, deploy). Indonesian affixes on them are fine where people actually say it (`request-nya`, `di-retry`, `nge-deploy`).
- Vary sentence openings. Not every step starts with "Aplikasi akan…".

## 3. AI patterns to remove

| Pattern | Example (AI) | Rewrite |
|---|---|---|
| Stiff connectors | "Selain itu,", "Adapun", "Dengan demikian,", "Oleh karena itu,", "Di samping itu," on every other sentence | Drop them, or use `Terus,` / `Jadi,` / `Nah,` sparingly |
| Significance inflation | "memainkan peran penting", "sangat krusial", "merupakan komponen vital" | Say what it does: "nyimpen semua transaksi" |
| Throat-clearing | "Penting untuk dicatat bahwa", "Perlu diketahui bahwa", "Berikut adalah", "Pada bagian ini akan dijelaskan" | Start with the fact |
| Formal pronouns and politeness | "Anda dapat", "Silakan Anda", "kamu bisa" | Imperative: "Cek …" |
| Officialese | "dalam rangka", "guna", "yang bersangkutan", "sehubungan dengan", "melakukan pengecekan" | "buat", "yang itu", "soal", "ngecek" |
| Noun stacks from "melakukan" | "melakukan validasi terhadap data" | "ngecek data" / "validasi data" |
| Calques of "which/where" | "yang mana", "di mana" as a relative pronoun ("tabel di mana data disimpan") | "tabel tempat data disimpan" / split the sentence |
| Passive chains | "akan diproses dan kemudian disimpan dan selanjutnya dikirim" | Active, short steps: "Datanya diproses, disimpan, terus dikirim ke …" |
| "Tidak hanya … tetapi juga …" | "Tidak hanya mencatat, tetapi juga mengirim" | "Nyatet sekaligus ngirim" |
| Triplets for rhythm | "cepat, aman, dan andal" | Keep only what's true and specific |
| Hedging | "dapat saja", "kemungkinan besar bisa jadi", "pada umumnya" | Say it plainly, or say exactly when it happens |
| Empty endings | "Semoga bermanfaat", "Dengan memahami alur ini, operator dapat…" | Delete |
| Over-formatting | bold on every other phrase, emoji, em-dash chains | Bold only the labels the template uses |
| Synonym cycling | "permintaan", "request", "permohonan" for the same thing | One term, every time |
| Formal "tidak/sudah/saja" everywhere | "tidak", "sudah", "saja", "apabila" | Mix in `nggak`, `udah`, `aja`, `kalau` where natural |

## 4. Process

1. Read the whole operator guide once to learn the facts.
2. Rewrite section by section, prose only (section 1).
3. Read your rewrite aloud in your head. If a line still sounds like a press release or a translated manual, rewrite it again.
4. Compare with the original: every number, name, step and check is still there.
5. Run the validator. It must still pass whatever passed before.

## 5. With an installed humanizer skill

Only when the orchestrator passes a humanizer skill path (the user asked for it). Read that skill's `SKILL.md` and apply its patterns **on top of** this file. Many humanizers are written for English, so translate their patterns to how they show up in Indonesian. Section 1 of this file always wins: no humanizer may change protected content.
