"""Publish one synthetic lesson into a pre-existing, isolated test branch."""
import os
from pathlib import Path

import github_publish as github
from core import validate_and_build

branch = "codex/vocab-cloud-test-synthetic"
root = Path(__file__).resolve().parents[1]
token = os.environ["VOCAB_TEST_GITHUB_TOKEN"]
errors, public, private = validate_and_build("fixture", {"冊": "fixture", "課": "fixture"}, [
    {"word":"甲", "meanings":{"en":"alpha"}, "sentence":"這是＿＿。", "accepted":"合成備選"},
], {"id":"IT_GITHUB_CLOUD", "version":"v1", "title":"Synthetic acceptance fixture"})
assert not errors
assert private["words"][0]["accepted"] == ["合成備選"]
assets = {root / name: name for name in github.ASSETS}
config = {"projectUrl":"https://fixture.supabase.co", "publishableKey":"sb_publishable_fixture"}
path, _ = github.publish(token, public, assets, config, branch)
sha = github.head(token, branch)["object"]["sha"]
assert b"accepted" not in github.read_at(path, token, sha)
assert github.publish(token, public, assets, config, branch)[0] == path
assert github.head(token, branch)["object"]["sha"] == sha
print("PASS: isolated GitHub publication and idempotent retry")
