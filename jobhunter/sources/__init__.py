"""Source registry.

Every source module has one function:

    fetch(cfg: dict, profile: dict, log: Callable[[str], None]) -> list[Job]

`cfg` is that source's block from config/sources.yaml, `profile` is config/profile.yaml.
"""
import importlib

BUILT_IN = {
    "rss": "jobhunter.sources.rss",
    "html": "jobhunter.sources.html_list",
    "ats": "jobhunter.sources.ats",
    "linkedin": "jobhunter.sources.linkedin",
    "naukri": "jobhunter.sources.naukri",
    "naukrigulf": "jobhunter.sources.naukrigulf",
    "telegram": "jobhunter.sources.telegram",
    "superteam": "jobhunter.sources.superteam",
    "remote_boards": "jobhunter.sources.remote_boards",
    "apna": "jobhunter.sources.apna",
    # added 2026-09-25
    "vc_boards": "jobhunter.sources.vc_boards",
    "jobstash": "jobhunter.sources.jobstash",
    "remote_apis": "jobhunter.sources.remote_apis",
    "india_boards": "jobhunter.sources.india_boards",
    "indeed": "jobhunter.sources.indeed",
    "hn_hiring": "jobhunter.sources.hn_hiring",
    "freelancer": "jobhunter.sources.freelancer",
}


def load(cfg: dict):
    kind = cfg.get("type")
    if kind == "custom":
        return importlib.import_module(f"jobhunter.sources.{cfg['module']}")
    if kind not in BUILT_IN:
        raise ValueError(f"unknown source type '{kind}' (use one of {sorted(BUILT_IN)} or custom)")
    return importlib.import_module(BUILT_IN[kind])
