# Scout report template

Raw module reports written by `fledge-context-scout` to `.fledge/nest/raw/<module>.md`. Every section must be present, in this order; write `None observed.` where a section is empty.

```markdown
---
module: <module name>
authored: <UTC ISO 8601>
agent: fledge-context-scout
fledge_version: <VERSION file contents>
---

# Module: <module name>

## Purpose
What this module is for, in 1–3 sentences.

## Structure & Key Files
Layout of the module; the files that matter most and why. Bullet list with paths.

## Entry Points & Public Interfaces
CLIs, exported APIs, main functions, routes — where execution enters this module and what it exposes to others.

## Data Types
Core types, schemas, structs, tables defined here, with file references.

## External Dependencies
Third-party libraries, tools, and services this module uses, and for what.

## Conventions Observed
Naming, error handling, layering, idioms, formatting patterns seen in this module.

## Tests
Test files, frameworks, how they appear to be run, what they cover.

## Domain Terms
Business/domain vocabulary this module embodies, with brief definitions.

## Open Questions
Things that could not be determined from the assigned files alone.
```
