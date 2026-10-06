"""Kinds of job, using Adzuna's category tags so every source shares one list.

Adzuna labels its own jobs. For other sources the kind is guessed from the
job title; jobs that match nothing are left without a kind.
"""

from __future__ import annotations

import re

# Adzuna category tag -> name shown in the app
CATEGORIES = {
    "accounting-finance-jobs": "Accounting & Finance",
    "admin-jobs": "Admin & Office",
    "charity-voluntary-jobs": "Charity & Volunteer",
    "consultancy-jobs": "Consulting",
    "creative-design-jobs": "Creative & Design",
    "customer-services-jobs": "Customer Service",
    "domestic-help-cleaning-jobs": "Cleaning & Domestic Help",
    "energy-oil-gas-jobs": "Energy, Oil & Gas",
    "engineering-jobs": "Engineering",
    "graduate-jobs": "Entry Level & Graduate",
    "healthcare-nursing-jobs": "Healthcare & Nursing",
    "hospitality-catering-jobs": "Hospitality & Food Service",
    "hr-jobs": "HR & Recruiting",
    "it-jobs": "IT & Software",
    "legal-jobs": "Legal",
    "logistics-warehouse-jobs": "Logistics & Warehouse",
    "maintenance-jobs": "Maintenance",
    "manufacturing-jobs": "Manufacturing",
    "part-time-jobs": "Part Time",
    "pr-advertising-marketing-jobs": "Marketing & PR",
    "property-jobs": "Real Estate",
    "retail-jobs": "Retail",
    "sales-jobs": "Sales",
    "scientific-qa-jobs": "Science & QA",
    "social-work-jobs": "Social Work",
    "teaching-jobs": "Teaching & Education",
    "trade-construction-jobs": "Trades & Construction",
    "travel-jobs": "Travel",
    "other-general-jobs": "Other",
}

# First match wins, so more specific patterns come first.
_GUESSES = [
    ("healthcare-nursing-jobs", r"nurse|nursing|\brn\b|\blpn\b|cna|medical|clinic|dental|pharmac|therapist|physician|caregiver|patient|health"),
    ("teaching-jobs", r"teacher|tutor|instructor|professor|educat|school"),
    ("legal-jobs", r"lawyer|attorney|paralegal|counsel|legal"),
    ("accounting-finance-jobs", r"account(ant|ing)|bookkeep|financ|payroll|auditor|tax|controller|teller|underwrit"),
    ("hr-jobs", r"recruit|talent acquisition|\bhr\b|human resources|people (partner|ops)"),
    ("pr-advertising-marketing-jobs", r"marketing|seo|content|brand|communications|social media|\bpr\b"),
    ("creative-design-jobs", r"design(er)?\b|ux|ui\b|illustrat|video|photograph|copywrit"),
    ("retail-jobs", r"cashier|retail|store|sales associate|merchandis|stock(er)?\b"),
    ("sales-jobs", r"sales|account executive|business development|\bsdr\b|\bbdr\b|account manager"),
    ("customer-services-jobs", r"customer (service|success|support)|support (specialist|agent|rep)|call center|help ?desk"),
    ("it-jobs", r"software|developer|engineer.*(software|data|platform|backend|frontend|full ?stack|devops|cloud|ml|security)|"
                r"devops|\bsre\b|site reliability|\bdba\b|database|data (scientist|engineer|analyst)|programmer|it support|sysadmin|network admin|machine learning|"
                r"frontend|backend|full ?stack|ios|android|cyber|\bqa\b"),
    ("logistics-warehouse-jobs", r"warehouse|forklift|picker|packer|logistic|shipping|receiving|driver|delivery|courier|dispatch"),
    ("hospitality-catering-jobs", r"cook|chef|barista|server|bartender|dishwasher|host(ess)?\b|housekeep|hotel|restaurant|food"),
    ("trade-construction-jobs", r"electrician|plumb|carpent|hvac|welder|construction|roofer|mason|painter|apprentice"),
    ("maintenance-jobs", r"maintenance|technician|janitor|custodian|groundskeep"),
    ("manufacturing-jobs", r"manufactur|production|assembler|machinist|operator"),
    ("admin-jobs", r"receptionist|administrative|admin\b|office (manager|assistant)|clerk|secretary|data entry|assistant"),
    ("engineering-jobs", r"engineer"),
]
_GUESS_RES = [(tag, re.compile(rx, re.I)) for tag, rx in _GUESSES]


def guess_category(title: str) -> str:
    for tag, rx in _GUESS_RES:
        if rx.search(title or ""):
            return tag
    return ""


def add_categories(jobs) -> None:
    for j in jobs:
        if not j.category:
            j.category = guess_category(j.title)
