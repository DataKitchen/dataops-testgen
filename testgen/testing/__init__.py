"""Testing support importable by the core test suite and any plugin test suite.

Fixtures live in ``testgen.testing.fixtures``; import the ones you need into a
``conftest.py`` to register them (pytest registers fixtures that are merely imported
into a conftest). An importable module is the only way to share fixtures across separate
test trees — sibling test directories do not share conftest fixtures.
"""
