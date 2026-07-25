import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]


def test_adapters_delegate_to_shared_skills():
    for root in ("adapters/opencode/commands", "adapters/pi/prompts"):
        paths = list((ROOT / root).glob("*.md"))
        assert all("$ARGUMENTS" in path.read_text() for path in paths)
        assert "`autoexp` skill" in (ROOT / root / "autoexp.md").read_text()
        assert "`autoexp-review` skill" in (ROOT / root / "autoexp-review.md").read_text()


def test_installer_wires_both_adapters(tmp_path):
    home = tmp_path / "home"
    env = {
        **os.environ,
        "HOME": str(home),
        "AUTOEXP_SOURCE_DIR": str(ROOT),
        "AUTOEXP_SKIP_RUNTIME": "1",
    }
    subprocess.run(["bash", str(ROOT / "install.sh")], env=env, check=True)

    for skill in ("autoexp", "autoexp-review"):
        assert (home / ".agents/skills" / skill / "SKILL.md").is_file()
        assert (home / ".config/opencode/commands" / f"{skill}.md").is_file()
        assert (home / ".pi/agent/prompts" / f"{skill}.md").is_file()
    assert (home / ".config/opencode/agents/autoexp.md").is_file()
