from django.test import SimpleTestCase
from django.urls import get_resolver

from wx.permissions_map import ENDPOINT_PARENT_PAGE


VALID_ACTIONS = {"read", "write", "delete"}


def _collect_url_names():
    """
    Walk all URL patterns and return a set of all named routes (url_name).
    Includes nested includes().
    """
    resolver = get_resolver()

    def walk(patterns):
        for p in patterns:
            # include() creates URLResolver with .url_patterns
            if hasattr(p, "url_patterns"):
                yield from walk(p.url_patterns)
            else:
                if getattr(p, "name", None):
                    yield p.name

    return set(walk(resolver.url_patterns))


class PermissionsMapTests(SimpleTestCase):
    """
    Unit tests for permissions_map.py

    These tests enforce:
    - Every endpoint name in ENDPOINT_PARENT_PAGE exists in urls.py
    - Every parent page name referenced exists in urls.py
    - Every action is one of: read/write/delete
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.all_url_names = _collect_url_names()

    def test_all_mapped_endpoints_exist_in_urls(self):
        """
        Every key in ENDPOINT_PARENT_PAGE must match a named url pattern.
        """
        missing = sorted([name for name in ENDPOINT_PARENT_PAGE.keys() if name not in self.all_url_names])

        self.assertEqual(
            missing,
            [],
            msg=(
                "These endpoint url_names are in ENDPOINT_PARENT_PAGE but NOT in urls.py:\n"
                + "\n".join(missing)
            ),
        )

    def test_all_parent_pages_exist_in_urls(self):
        """
        Every parent page referenced in ENDPOINT_PARENT_PAGE must match a named url pattern.
        (We treat parent pages as normal named routes too.)
        """
        parent_pages = sorted({parent for (parent, _action) in ENDPOINT_PARENT_PAGE.values()})
        missing = sorted([p for p in parent_pages if p not in self.all_url_names])

        self.assertEqual(
            missing,
            [],
            msg=(
                "These parent page url_names are referenced in ENDPOINT_PARENT_PAGE but NOT in urls.py:\n"
                + "\n".join(missing)
            ),
        )

    def test_all_actions_are_valid(self):
        """
        Only allow read/write/delete actions in the map.
        """
        bad = sorted(
            [(endpoint, action) for endpoint, (_parent, action) in ENDPOINT_PARENT_PAGE.items() if action not in VALID_ACTIONS],
            key=lambda x: x[0],
        )

        self.assertEqual(
            bad,
            [],
            msg=(
                "These mappings have invalid actions (must be read/write/delete):\n"
                + "\n".join([f"{endpoint}: {action}" for endpoint, action in bad])
            ),
        )

    def test_endpoint_not_mapped_to_itself(self):
        """
        Usually an endpoint should map to a parent page, not itself.
        This catches accidental self-maps.
        """
        self_maps = sorted(
            [endpoint for endpoint, (parent, _action) in ENDPOINT_PARENT_PAGE.items() if endpoint == parent]
        )

        self.assertEqual(
            self_maps,
            [],
            msg=(
                "These endpoints are mapped to themselves (usually a mistake):\n"
                + "\n".join(self_maps)
            ),
        )
