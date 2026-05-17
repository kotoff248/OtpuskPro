from importlib import import_module


PROXY_TARGETS = {
    "_apply_candidate_scoring": "apps.leave.services.schedule_drafts.candidate_generation",
    "normalize_schedule_draft_adjacent_items": "apps.leave.services.schedule_drafts.normalization",
}


def _module_symbol(name, value, module_name):
    if name.startswith("__"):
        return False
    if name.isupper():
        return True
    return getattr(value, "__module__", None) == module_name


def _proxy(name, target_module):
    def wrapper(*args, **kwargs):
        return getattr(import_module(target_module), name)(*args, **kwargs)

    wrapper.__name__ = name
    wrapper.__qualname__ = name
    wrapper.__module__ = target_module
    return wrapper


def wire_modules(modules):
    registry = {}
    owners = {}
    for module in modules:
        for name, value in vars(module).items():
            if _module_symbol(name, value, module.__name__):
                registry[name] = value
                owners[name] = module.__name__

    for module in modules:
        for name, value in registry.items():
            if owners.get(name) == module.__name__:
                continue
            if name in PROXY_TARGETS:
                module.__dict__[name] = _proxy(name, PROXY_TARGETS[name])
            elif name not in module.__dict__:
                module.__dict__[name] = value
