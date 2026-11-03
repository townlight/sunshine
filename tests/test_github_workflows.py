from pathlib import Path

import yaml


RELEASE_WORKFLOW = Path(".github/workflows/release.yml")


def _workflow() -> dict:
    data = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _triggers(workflow: dict) -> dict:
    # PyYAML 1.1 treats the key "on" as boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def test_release_workflow_dispatch_release_tag_contract() -> None:
    workflow = _workflow()
    workflow_dispatch = _triggers(workflow)["workflow_dispatch"]
    release_tag = workflow_dispatch["inputs"]["release_tag"]

    assert release_tag["required"] is True
    assert release_tag["default"] == "v1.7.3"


def test_release_workflow_cleanroom_release_gate_contract() -> None:
    workflow_text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    release_notes_template = Path(".github/release-notes-v15-template.md").read_text(
        encoding="utf-8"
    )
    workflow = _workflow()
    jobs = workflow["jobs"]

    assert jobs["publish-release"]["needs"] == ["release-cleanroom-rehearsal"]
    assert "release-cleanroom-rehearsal" in jobs
    assert "townlight-cleanroom=1" in workflow_text
    assert "system prune" not in workflow_text
    assert (
        "Cleanroom rehearsal: PASSED in workflow run ${WORKFLOW_RUN_ID}"
        in release_notes_template
    )
    assert "Verified clean install of ${WHEEL_URL} from cold caches" in release_notes_template
