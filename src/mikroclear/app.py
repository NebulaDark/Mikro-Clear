"""Top-level Mikro-Clear service orchestration."""


def main() -> int:
    from mikroclear import legacy

    return legacy.main()


__all__ = ["main"]
