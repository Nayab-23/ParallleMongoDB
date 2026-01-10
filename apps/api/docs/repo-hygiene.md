# Repo Hygiene

- Ignore local artifacts (OS caches, virtualenvs, bytecode, logs, local DBs, env files) so commits stay portable and reproducible.
- If a local file was already committed by mistake, remove it from version control while keeping it locally: `git rm --cached path/to/file` then commit.
- Never commit `.env` or secrets; use `.env.example` as a template and set real values in your private `.env`.

