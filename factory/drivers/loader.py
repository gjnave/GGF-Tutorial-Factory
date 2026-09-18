from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from factory.adapters.base import ApplicationAdapter
from factory.core.profile import ApplicationProfile


def load_project_driver(profile: ApplicationProfile, run_root: Path) -> ApplicationAdapter:
    driver_path = profile.driver_path
    project_root = profile.path.parent.resolve()
    try:
        driver_path.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(f"Project driver must live inside {project_root}: {driver_path}") from exc
    if not driver_path.is_file():
        raise FileNotFoundError(f"Project driver does not exist: {driver_path}")
    module_name = "tutorial_factory_project_driver_" + re.sub(r"[^a-z0-9]+", "_", profile.slug.lower())
    spec = importlib.util.spec_from_file_location(module_name, driver_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load project driver: {driver_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, "create_driver", None)
    if not callable(factory):
        raise ValueError(f"Project driver must define create_driver(profile, run_root): {driver_path}")
    driver = factory(profile, run_root)
    if not isinstance(driver, ApplicationAdapter):
        raise TypeError(f"create_driver returned {type(driver).__name__}, not ApplicationAdapter")
    if not callable(getattr(driver, "execute_operation", None)):
        raise TypeError("Project driver must expose execute_operation(name, value, **kwargs)")
    if not callable(getattr(driver, "capabilities", None)):
        raise TypeError("Project driver must expose capabilities()")
    return driver
