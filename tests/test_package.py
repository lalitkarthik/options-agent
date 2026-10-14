from importlib.metadata import version

import options_agent


def test_package_reports_its_installed_version():
    assert options_agent.__version__ == version("options-agent")
