"""Kivy shell scaffold: run a pure-Python Maverick skill on a phone.

Lists the bundled pure skills (today: one — ``disagreement.answer_entropy``,
the proposer-disagreement signal from ``packages/maverick-core/maverick/
disagreement.py``, chosen because it imports nothing but stdlib) and runs it
on sample fan-outs.

The module is loaded by file path with importlib, no package context needed:
it has zero intra-package imports. From a repo checkout the path resolves
into packages/; in a buildozer-built APK it must be copied next to main.py
first (see buildozer.spec and the README — packaging is a maintainer act).

Honest fallback: if Kivy is not installed (e.g. in this repo's test
environment), running ``python main.py`` executes the skill in the terminal
instead of crashing, so the scaffold stays exercisable everywhere.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BUNDLED_MODULE = _HERE / "disagreement.py"                      # APK layout
_REPO_MODULE = (                                                  # checkout layout
    _HERE.parents[2] / "packages" / "maverick-core" / "maverick" / "disagreement.py"
)

SAMPLES = {
    "all identical": ["paris", "paris", "paris"],
    "one dissenter": ["paris", "paris", "lyon"],
    "all unique": ["paris", "lyon", "nice"],
}


def load_skill():
    """Load the pure skill module by file path (no maverick install needed)."""
    for candidate in (_BUNDLED_MODULE, _REPO_MODULE):
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("disagreement", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise FileNotFoundError(
        "disagreement.py not found. From a checkout, run from the repo; for "
        "an APK, copy packages/maverick-core/maverick/disagreement.py next "
        "to main.py before `buildozer android debug` (see README.md)."
    )


def run_skill() -> str:
    skill = load_skill()
    lines = [
        f"{name:>14}: entropy={skill.answer_entropy(answers):.3f}"
        for name, answers in SAMPLES.items()
    ]
    lines.append("")
    lines.append("0 = proposers agree, 1 = every answer unique.")
    return "\n".join(lines)


def main() -> None:
    try:
        from kivy.app import App
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button
        from kivy.uix.label import Label
    except ImportError:
        print("kivy is not installed; running the skill in the terminal instead.\n")
        print(run_skill())
        return

    class MaverickSkillsApp(App):
        title = "Maverick Skills"

        def build(self):
            root = BoxLayout(orientation="vertical", padding=24, spacing=12)
            root.add_widget(Label(
                text="Bundled pure skills:\n  - disagreement.answer_entropy",
                size_hint_y=None, height=80,
            ))
            output = Label(text="Tap run.")

            def on_run(_button):
                try:
                    output.text = run_skill()
                except FileNotFoundError as exc:
                    output.text = str(exc)

            run_button = Button(
                text="Run answer_entropy", size_hint_y=None, height=56,
            )
            run_button.bind(on_press=on_run)
            root.add_widget(run_button)
            root.add_widget(output)
            return root

    MaverickSkillsApp().run()


if __name__ == "__main__":
    main()
