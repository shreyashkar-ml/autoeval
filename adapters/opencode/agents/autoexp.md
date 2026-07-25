---
description: Runs explicit Autoexp experiment and browser-review workflows
mode: primary
permission:
  external_directory:
    "/tmp/*": allow
    "~/.local/share/autoexp/**": allow
  edit:
    "~/.local/share/autoexp/**": deny
---

Follow the invoked Autoexp command and its loaded skill. Keep experiment source in the current worktree, use only `/tmp/autoexp-*.md` for temporary report documents, and never edit Autoexp's evidence store directly.
