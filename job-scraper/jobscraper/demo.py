"""Made-up sample jobs, so the app can be tried without network access (`--demo`).

Companies and postings are fictional; links point to example.com.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from .models import Job

COMPANIES = [
    "Northwind Labs", "Brightwave", "Quanta Health", "Loop Logistics", "Fernhill Studio",
    "Cobalt Systems", "Tidal Analytics", "Juniper Bank", "Orbital Robotics", "Pinecrest Games",
    "Saltmarsh AI", "Harbor Energy",
]
ROLES = [
    ("Senior Backend Engineer", ["python", "django", "postgres"]),
    ("Backend Engineer (Go)", ["golang", "kubernetes"]),
    ("Frontend Engineer", ["react", "typescript"]),
    ("Full Stack Developer", ["node", "react"]),
    ("Data Scientist", ["python", "sql", "statistics"]),
    ("Machine Learning Engineer", ["pytorch", "python"]),
    ("Site Reliability Engineer", ["aws", "terraform"]),
    ("Product Designer", ["figma", "ux"]),
    ("Engineering Manager", ["leadership"]),
    ("iOS Developer", ["swift"]),
    ("Data Engineer", ["spark", "airflow", "sql"]),
    ("Product Manager", ["roadmap", "b2b"]),
    ("Security Engineer", ["appsec", "cloud"]),
    ("Junior Software Engineer", ["java", "spring"]),
    ("Technical Writer", ["docs", "api"]),
    ("Registered Nurse", ["healthcare", "nights"]),
    ("Cashier", ["retail", "part time"]),
    ("Warehouse Associate", ["logistics", "full time"]),
    ("Barista", ["food service", "part time"]),
    ("Delivery Driver", ["driving", "full time"]),
    ("Dental Assistant", ["healthcare"]),
    ("Line Cook", ["restaurant"]),
    ("Bank Teller", ["finance", "customer service"]),
    ("Electrician Apprentice", ["trades"]),
    ("Front Desk Receptionist", ["office", "customer service"]),
]
LOCATIONS = [
    ("Remote", True), ("Remote (Europe)", True), ("Remote - US", True), ("Berlin, Germany", False),
    ("London, UK", False), ("New York, NY", False), ("San Francisco, CA", False),
    ("Amsterdam, Netherlands", False), ("Toronto, Canada", False), ("Hybrid - Paris", False),
    ("Chicago, IL", False), ("Evanston, IL", False), ("Oak Park, IL", False), ("Naperville, IL", False),
    ("Schaumburg, IL", False), ("Milwaukee, WI", False), ("Austin, TX", False), ("Round Rock, TX", False),
    ("Brooklyn, NY", False), ("Jersey City, NJ", False),
]
SOURCES = ["greenhouse", "lever", "ashby", "remoteok", "remotive", "arbeitnow", "hackernews", "adzuna", "adzuna", "adzuna"]


def jobs(count: int = 150, seed: int = 7) -> list[Job]:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    out = []
    for i in range(count):
        company = rng.choice(COMPANIES)
        role, tags = rng.choice(ROLES)
        location, remote = rng.choice(LOCATIONS)
        source = rng.choice(SOURCES)
        if source in ("remoteok", "remotive"):
            location, remote = "Remote", True
        lo = rng.randrange(70, 180, 5)
        salary = f"${lo}k – ${lo + rng.randrange(20, 60, 5)}k" if rng.random() < 0.55 else ""
        out.append(Job(
            source=source,
            source_id=f"demo-{i}",
            title=role,
            company=company,
            url=f"https://example.com/jobs/{i}",
            location=location,
            remote=remote,
            posted_at=now - timedelta(hours=rng.randrange(1, 24 * 35)),
            tags=tags,
            salary=salary,
            description=(
                f"{company} is hiring a {role} to join a small, product-focused team.\n"
                f"You'll work with {', '.join(tags)} and ship to customers every week.\n"
                "This is sample data shown in demo mode."
            ),
        ))
    return out
