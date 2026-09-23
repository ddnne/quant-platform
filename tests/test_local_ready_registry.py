from scripts.local_ready_registry import load_scoped_ready_public_keys


def test_committed_staging_ready_key_does_not_activate_production():
    staged = load_scoped_ready_public_keys(expected_environment="staging")
    assert set(staged) == {
        ("staging", "ready-authority/staging/v1", "ready-staging-20260923-v1")
    }
    assert load_scoped_ready_public_keys(expected_environment="production") == {}
