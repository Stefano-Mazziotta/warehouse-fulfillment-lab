# Source review and adaptation decisions

Treat this as a project-specific synthesis of three reviewed skills, not a claim
that every recommendation is an industry requirement. Verify technology behavior
against official documentation for the installed version.

| Source | Retain | Adapt or reject |
| --- | --- | --- |
| [ECC hexagonal-architecture](https://github.com/affaan-m/ecc/blob/b38be6a7f6350964d59328b52f0624e1d1d552d1/skills/hexagonal-architecture/SKILL.md) | Inward dependencies, consuming ports, explicit wiring, incremental slices, contract tests | Replace TypeScript with Python Protocols/context managers; avoid an interface/DTO per operation and unsafe remote-call-then-save shipping |
| [robust-skills clean-ddd-hexagonal](https://github.com/ccheney/robust-skills/blob/0eea7b060d12e3520556a73b15fbfa79480987d1/skills/clean-ddd-hexagonal/SKILL.md) | Business language, entity/value distinction, invariant-driven aggregates, explicit consistency trade-offs | Keep simple work simple; do not force aggregate-per-transaction rules, CQRS, event sourcing, or bounded-context microservices |
| [Mindrally flask-python](https://github.com/mindrally/skills/blob/7682ca77710e0971eab4e0ae5dddfa281aea0ba5/flask-python/SKILL.md) | Factories, blueprints, validation, safe errors, pytest clients, documented APIs, measured queries | Keep domain/use-case classes; retain SQLAlchemy Core/Alembic, Strawberry, Pika and Valkey instead of requiring extra Flask/REST/JWT/Celery extensions |

Do not carry JavaScript-like named-export or brace guidance into Python. Prefer
clear control flow to compressed one-liners, and typed values/commands to mandatory
untyped object-in/object-out functions.

Route tasks by responsibility: architecture/domain, Flask/API, or concrete backend
reliability. Load companion skills only when the requested change crosses their
boundaries. Do not duplicate the whole architecture guide in every skill.

Keep the modular WMS learning scope and honor explicit implementation requests.
Treat the extended stack as branch-dependent, not a reason to add dependencies
to master. Retain the MIT notices in architecture/reliability and the Apache-2.0
license in the Flask adaptation when redistributing these skills.
