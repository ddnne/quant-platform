"""Pin r2_io.default_r2_get_object: wrangler --remote get, not artifact authority."""

import inspect

import research.r2_io as r2_io
from research.r2_io import (
    WORKER_CHILDREN_THEN_MANIFEST_PATH,
    default_r2_get_object,
    put_children_then_manifest_via_worker,
)


def test_default_r2_get_object_is_wrangler_remote_not_artifact_authority() -> None:
    src = inspect.getsource(default_r2_get_object)
    doc = default_r2_get_object.__doc__ or ""

    assert "wrangler r2 object get" in doc
    assert '"r2"' in src
    assert '"object"' in src
    assert '"get"' in src
    assert "--remote" in src
    assert "subprocess.run" in src
    # 03409ccd / current origin: no Python R2 get overlay env.
    assert "QP_ALLOW_PYTHON_R2_GET" not in src

    # CLI get is not Coverage COMPLETE / FRESH and not immutable artifact authority.
    assert "COMPLETE" not in src
    assert "FRESH" not in src
    assert "children-then-manifest" not in src
    assert WORKER_CHILDREN_THEN_MANIFEST_PATH not in src

    authority_src = inspect.getsource(put_children_then_manifest_via_worker)
    authority_doc = put_children_then_manifest_via_worker.__doc__ or ""
    assert WORKER_CHILDREN_THEN_MANIFEST_PATH in authority_src
    assert "CLI put is not authority" in authority_doc
    mod_doc = " ".join((r2_io.__doc__ or "").split())
    assert "children-then-manifest is the immutable authority" in mod_doc
