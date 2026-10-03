# Security policy

## Supported versions

NexusGraph is pre-1.0; only the latest `main` receives security fixes.

## Reporting a vulnerability

This is a portfolio/open-source project without a dedicated security team.
Please **do not open public issues for exploitable findings**.

- Email: open a private GitHub security advisory against this repository
  (Recommended), or contact the maintainer directly.
- Include a description, reproduction steps and the affected commit.
- You can expect an initial response within a week; fixes land on `main` and
  are noted in the commit history.

## Scope notes

The threat model is documented in [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).
In particular:

- The bundled corpus is synthetic; the adversarial fixtures (D-9013, D-9014)
  are intentional test artifacts, not vulnerabilities.
- Deployment hardening (TLS, network egress control, real authentication on
  the HTTP surface beyond the optional static `X-API-Key`, secret management)
  is the operator's responsibility and is out of scope for the code in this
  repository.
