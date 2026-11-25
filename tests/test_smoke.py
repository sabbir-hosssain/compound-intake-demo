"""M0 skeleton smoke test: the package imports. Real tests arrive with each M1 issue."""


def test_package_imports() -> None:
    import intake

    assert intake.__version__
