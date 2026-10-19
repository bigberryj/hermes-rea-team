# Hermes REA Team — 0.1.0

Restricted, on-demand Hermes integration for [morluto/rea](https://github.com/morluto/rea), built for Byron's bigbai installation. REA is the analyzer; Hermes owns model routing. This is **not** an unrestricted REA MCP installation.

## What works

- Local static JavaScript analysis of an unpacked staged application.
- Three independent MiniMax-M3 reviewers: architecture, security, verification.
- Native Hermes tools `rea_inspect` and `rea_team`, plus bundled skill `hermes-rea-team:rea-team`.
- Standalone `hermes-rea-team` CLI.
- Private evidence, per-role reports and provenance; deterministic run caching.

**Binary layout is not ready:** optional pwntools/pyelftools/Unicorn bridge dependencies were deliberately not installed. Hopper, IDA, Frida, Ghidra, HTTP MCP, browser capture, device access, debugging, injection, and target execution are not enabled by this integration.

## Install / exact deployment

This deployment intentionally pins machine paths, Node, REA source/build and selected Hermes APIs. It is not a portable cross-machine installer.

```bash
cd /home/byron/projects/hermes-rea-team
./install.sh
hermes-rea-team status
```

`install.sh` creates a private Python venv, installs this CLI editable without runtime dependencies, and links the executable in `~/.local/bin`. It does **not** install or enable the native Hermes plugin or modify models. Native plugin installation uses the normal Hermes plugin manager, pinned to the reviewed integration commit:

```bash
hermes plugins install bigberryj/hermes-rea-team --ref <reviewed-40-character-commit> --enable
hermes plugins doctor hermes-rea-team --ci
```

The plugin is installed into the **default profile only**. Existing reasoner credentials are resolved by Hermes itself for the three workers; no credentials are copied. Other profiles remain untouched.

## Call from a regular terminal

Place a clean copy of the authorized JavaScript artifact under `/home/byron/projects/rea-targets/my-app`. Do not copy `.git`, `node_modules`, credentials, symlinks or packed archives. Source can contain secrets despite innocuous filenames; review it before team mode.

```bash
# Validate target and limits: no REA process or model calls
hermes-rea-team prepare /home/byron/projects/rea-targets/my-app --kind javascript

# Local static evidence, no model calls
hermes-rea-team inspect /home/byron/projects/rea-targets/my-app --kind javascript

# Three bounded MiniMax reviewers; evidence is sent to MiniMax
hermes-rea-team team /home/byron/projects/rea-targets/my-app --kind javascript \
  --question 'Explain search, cite evidence, identify risks and unknowns.'
```

The result gives private artifact paths. Read `report.json`, `architecture-report.json`, `security-report.json`, and `verification-report.json` for findings. CLI output deliberately contains no source or model text.

## Call inside Hermes terminal

Start a fresh default-profile session after installing the plugin:

```text
Use rea_team on /home/byron/projects/rea-targets/my-app, kind javascript.
Explain search and its security risks. Preview first, then run the three-role team and summarize the saved reports.
```

For an explicit skill load use `/skill hermes-rea-team:rea-team`. No `/rea` slash command is registered.

## Call from Hermes Desktop

Select the default profile on **bigbai** (the backend where the files and plugin live), then use the same prompt as above. No Desktop renderer extension or extra network port is needed: these are backend tools.

A backend process already running before plugin installation may require a supported reload/restart and a fresh chat. This install does not restart the gateway, interrupt conversations, or modify your Windows client's settings. If the tool is not yet available in an existing chat, use this immediately through its existing terminal tool:

```text
Run ~/.local/bin/hermes-rea-team team /home/byron/projects/rea-targets/my-app --kind javascript --question 'Explain search and its evidence-supported risks.' Then read the returned role reports and summarize them.
```

Desktop click-through verification is a separate acceptance check; CLI/native plugin proof is not proof that your remote Desktop session has reloaded.

## Safety and privacy

- Only two allowlisted analysis commands; no arbitrary flags or executables.
- fd-relative snapshots reject symlinks, hardlinks, special files, secret-looking filenames, archives, traversal, overlarge trees and mutation races.
- Limits: 16 MiB/file, 64 MiB/tree, 2,000 entries, depth 32; REA 45-second wall limit and 2 MiB combined output; JavaScript parser heap 256 MiB.
- Minimal environment/private HOME for REA. Analysis never executes the supplied target.
- One team globally; three sequential independent reviewers, up to 2,048 output tokens each, one model iteration, 90-second model and 120-second worker budgets.
- The same bounded evidence is supplied to every reviewer (up to 96,000 bytes, with truncation declared). No shared conversation or automatic synthesis disguising disagreement.
- MiniMax OAuth uses native Hermes resolution in the existing reasoner profile. Workers assert empty tools/fallback and exact provider/model before and after calls. No private API/token extraction or copied credential files.
- Native Hermes SDK imports are **version-coupled**, deliberately pinned; host upgrades fail closed for re-review. Public `ctx.llm` was considered, but its auxiliary fallback behavior does not expose the strict no-fallback boundary used here.
- Stored artifacts are owner-private. Filenames are a screening measure, not secret-content detection. Team mode discloses evidence to MiniMax; reading/summarizing it in a separate chat discloses it to that chat's model.
- Repeating a target/question uses the cached result; failed runs are not automatically retried. Provider authentication refresh/transport retries are distinct from the role count, so three roles is not a blanket promise of exactly three billable HTTP requests.
- Application controls are not an OS sandbox. Arbitrary parser bugs and malicious same-user processes are outside that guarantee.

## Verification

```bash
python3 -m unittest discover -s tests -v
hermes plugins doctor /home/byron/projects/hermes-rea-team --ci
```

Verified installation smoke on the synthetic `smoke-js` fixture: real REA evidence and all three MiniMax roles completed. Each role reported provider `minimax-oauth`, model `MiniMax-M3`, one model API call, no tools, no fallback. Runtime evidence remains private and is not committed.

## Updates / rollback

Do not run `rea update`, `@latest`, broad `rea setup`, or regenerate pins to bypass errors. Re-review dependencies/source, rebuild and re-verify before changing the manifest. Disable the plugin with `hermes plugins disable hermes-rea-team`; the CLI and private artifacts are independent. No database schema or global model configuration is changed.

MIT applies to this wrapper and REA; optional external engines retain their own licenses.
