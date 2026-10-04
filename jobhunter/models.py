"""The one shape every source returns. Sources fill what they can; the rest stays empty."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date


@dataclass
class Job:
    source: str
    title: str
    url: str
    company: str = ""
    location: str = ""
    work_mode: str = ""          # Remote / Hybrid / Onsite / ""
    posted: date | None = None
    salary: str = ""
    experience: str = ""         # as shown by the site, e.g. "2-5 Yrs"
    description: str = ""        # plain text, used for scoring only
    web3_native: bool = False    # source only lists crypto jobs
    web3_hint: bool = False      # crypto VC portfolio board: the company is probably, not surely, crypto
    kind: str = "job"            # "job" or "freelance" (bounty, gig, contract, part-time…)
    deadline: date | None = None # freelance: submissions close

    # filled by scoring
    score: int = 0
    priority: str = ""
    why: str = ""
    flags: str = ""
    also_on: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Same job on two sites → same key (title + company), so duplicates merge."""
        norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
        company = norm(self.company)
        base = f"{norm(self.title)}|{company}" if company else self.url.split("?")[0].lower()
        return hashlib.sha1(base.encode()).hexdigest()[:16]
