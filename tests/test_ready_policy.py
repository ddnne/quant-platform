from paper_runtime.ready_policy import ReadyEvidenceBundle, ReadyEvidenceItem, ReadyPublicationPolicy


def test_bundle_pass_fail():
    b = ReadyEvidenceBundle(items=[
        ReadyEvidenceItem("a", True),
        ReadyEvidenceItem("b", False, reason="x"),
    ])
    assert not b.passed
    assert len(b.failures()) == 1


def test_policy_constructs():
    assert ReadyPublicationPolicy() is not None
