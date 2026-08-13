"""Compatibility entry point for canonical Fusion Layer exports.

The authoritative implementation lives in ``scripts/fusion_v1.py`` and reads the
current governed silver snapshot. Keeping this wrapper prevents an older schema
adapter from overwriting valid Fusion outputs with false zero counts.
"""

from fusion_v1 import main


if __name__ == "__main__":
    main()
