# Releasing the SDKs

Publishing is automated: **cut a GitHub Release → the workflows publish to PyPI + npm.**
You set up credentials once. Tokens live in **GitHub repo Secrets**, never in the code or `.env`.

---

## 0. One-time: push this repo to GitHub

```bash
git add -A && git commit -m "initial SDKs"
git push origin main
```

---

## 1. One-time: PyPI (Python) — Trusted Publishing (recommended, no token)

1. Create the project owner on **PyPI → your account → Publishing → "Add a pending publisher"**:
   - **PyPI Project Name:** `crowkis`
   - **Owner:** your GitHub username or org
   - **Repository name:** `crowkis-sdk`
   - **Workflow name:** `publish-python.yml`
   - **Environment name:** `pypi`
2. In **GitHub → this repo → Settings → Environments → New environment → `pypi`** (name must match).

That's it — no token stored anywhere. (First check `crowkis` is free on pypi.org; if taken, pick a name and update `python/pyproject.toml`.)

*Fallback (token instead of Trusted Publishing):* create a PyPI API token, add it as GitHub secret `PYPI_API_TOKEN`, and add `with: password: ${{ secrets.PYPI_API_TOKEN }}` to the publish step.

---

## 2. One-time: npm (Node) — token secret

1. On **npmjs.com**: create the **`@crowkis` org** (the package is `@crowkis/client`).
2. **npm → Access Tokens → Generate New Token → "Automation"** → copy the `npm_…` token.
3. **GitHub → this repo → Settings → Secrets and variables → Actions → New repository secret**:
   - **Name:** `NPM_TOKEN`
   - **Value:** paste the token

---

## 3. Every release: cut a version

1. Bump the version in **both**:
   - `python/pyproject.toml` → `version = "0.5.2"`
   - `node/package.json` → `"version": "0.5.2"`
2. Commit + push:
   ```bash
   git commit -am "v0.5.2"
   git push origin main
   ```
3. **GitHub → Releases → Draft a new release → tag `v0.5.2` → Publish release.**
4. Publishing the release triggers both workflows → `crowkis` lands on PyPI and `@crowkis/client` on npm automatically. Watch **Actions** tab for the green check.

---

## Where each credential lives

| Credential | Where it goes | Notes |
|---|---|---|
| PyPI | **nowhere** (Trusted Publishing) | or GitHub secret `PYPI_API_TOKEN` |
| npm | GitHub secret **`NPM_TOKEN`** | never in `.env` or code |

`.env` is only for local development keys — it is gitignored and never used by CI.
